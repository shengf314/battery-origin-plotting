"""Bridge declared native measurements into the existing Excel/PlotSpec inputs.

No decoder, Origin connection, fitting, record repair or instrument-specific
guessing lives here. A caller supplies immutable canonical reader results.
"""

from collections import OrderedDict, Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

from ..config import SKILL_ROOT
from ..models import PlotSpec
from ..pipeline import prepare
from ..ingest.report import InputContractError, ValidationReport
from ..domains.processing.standard_export import write_standard_xlsx
from ..domains.electrochemistry.rate_capability.ingest import normalize_rate


PLOT_TYPES = ("gcd", "cycle_performance", "rate_capability")
BRANCHES = ("charge", "discharge")
BASES = ("step_cumulative", "branch_cumulative", "cycle_branch_cumulative")
MAX_DATA_ROWS = 1048575  # One header row in the existing single-sheet contract.


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _integer(value):
    return _finite(value) and int(value) == value


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value)


def _runs(indices):
    """Compress only observed adjacent identities; never infer missing rows."""
    runs = []
    for value in indices:
        if runs and value == runs[-1][1] + 1:
            runs[-1][1] = value
        else:
            runs.append([value, value])
    return runs


def _rate(value, location, questions, native=False):
    if value is None:
        return None
    if native and _finite(value):
        value = format(Decimal(str(value)), "f") + " C"
    report = ValidationReport()
    result = normalize_rate(SimpleNamespace(text=value, value=None, formula=None, cached=True), report, 0, location)
    if report.blocking:
        questions.extend(report.questions + report.errors)
        return None
    return result


def _mass(source, dataset, location, questions):
    metadata = dataset.get("metadata") or {}
    supplied = source.get("mass_g")
    native = metadata.get("mass_g")
    if supplied is not None:
        if not _finite(supplied) or supplied <= 0 or not _text(source.get("mass_source")):
            questions.append(location + ": explicit mass_g requires a positive finite g value and mass_source")
            return None
        if _finite(native) and native > 0 and not math.isclose(float(supplied), float(native), rel_tol=1e-6, abs_tol=1e-12):
            questions.append(location + ": supplied active-material mass conflicts with the instrument-stored mass; choose and document the normalization basis")
            return None
        return dict(value_g=float(supplied), basis="active_material", source=source["mass_source"],
                    method="explicit task mass; previously confirmed active-material convention")
    if native is not None and (not _finite(native) or native <= 0):
        return None
    if _finite(native) and native > 0:
        if metadata.get("mass_basis") != "active_material" or not _text(metadata.get("mass_source")):
            return None
        return dict(value_g=float(native), basis="active_material", source=metadata["mass_source"],
                    method="reader-declared instrument active-material mass")
    return None


def _specific(row, native_field, absolute_field, mass, location, questions):
    native, absolute = row.get(native_field), row.get(absolute_field)
    if native is not None:
        if not _finite(native):
            questions.append(location + ": supplied " + native_field + " is nonfinite/non-numeric; no fallback or dropping")
            return None, None
        if mass is not None and _finite(absolute):
            expected = absolute / mass["value_g"]
            if not math.isclose(float(native), float(expected), rel_tol=1e-5, abs_tol=1e-5):
                questions.append(location + ": native specific capacity conflicts with absolute capacity / declared active mass")
                return None, None
        return float(native), dict(method="supplied_native_specific_capacity", field=native_field,
                                   unit="mAh/g", mass=deepcopy(mass))
    if not _finite(absolute):
        questions.append(location + ": needs finite " + native_field + " or " + absolute_field)
        return None, None
    if mass is None:
        questions.append(location + ": conversion to mAh/g needs positive active-material mass in g with its source")
        return None, None
    return absolute / mass["value_g"], dict(method="capacity_mAh / active_material_mass_g", field=absolute_field,
                                           unit="mAh/g", mass=deepcopy(mass))


def _branch_groups(records, cycle):
    return {branch: [(position, row) for position, row in enumerate(records)
                     if row.get("cycle") == cycle and row.get("branch") == branch] for branch in BRANCHES}


def _continuous(rows, all_records, basis, location, questions, one_step=False):
    if not rows:
        return False
    positions = [position for position, _ in rows]
    if positions != list(range(positions[0], positions[-1] + 1)):
        questions.append(location + ": branch returns after Rest/another branch/cycle; existing GCD has no Segment and will not connect it silently")
        return False
    steps = [row.get("step") for _, row in rows]
    if any(value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()) for value in steps):
        questions.append(location + ": native step identity is missing")
        return False
    distinct = list(OrderedDict((str(value), None) for value in steps))
    if one_step and len(distinct) != 1:
        questions.append(location + ": raw-record summary fallback requires one native step per branch")
        return False
    if basis not in BASES:
        questions.append(location + ": capacity_basis must explicitly identify step_cumulative or branch/cycle_branch_cumulative")
        return False
    if len(distinct) > 1 and basis == "step_cumulative":
        questions.append(location + ": multiple steps have step-cumulative capacity; no offset, reset repair or step summation is inferred")
        return False
    return True


def _nondecreasing(values, location, questions):
    if any(after < before for before, after in zip(values, values[1:])):
        questions.append(location + ": cumulative capacity decreases/resets; source values are not repaired, sorted or joined")
        return False
    return True


def _cycle_capacity(cycle, branch, summary, groups, metadata, mass, location, questions):
    if summary is not None:
        value, method = _specific(summary, branch + "_specific_capacity_mAh_g", branch + "_capacity_mAh", mass, location, questions)
        if method is not None:
            # The canonical cycle table can be a manufacturer summary or an
            # explicitly derived sum of native step endpoints. Preserve that
            # distinction even when the downstream formula is only Q / mass.
            method = dict(method, cycle_capacity_basis=metadata.get("cycle_capacity_basis"),
                          cycle_summary_source=metadata.get("cycle_summary_source"))
        return value, method
    rows = groups[branch]
    if not _continuous(rows, None, metadata.get("capacity_basis"), location, questions, one_step=True):
        return None, None
    capacities = [row.get("capacity_mAh") for _, row in rows]
    if any(not _finite(value) for value in capacities):
        questions.append(location + ": fallback endpoint capacity requires finite native cumulative capacity values")
        return None, None
    if not _nondecreasing(capacities, location, questions):
        return None, None
    value, method = _specific(rows[-1][1], "specific_capacity_mAh_g", "capacity_mAh", mass, location, questions)
    if method is not None:
        method = dict(method, summary_method="last native cumulative record of one continuous branch step; no subtraction/reintegration")
    return value, method


def _cycle_rate(source, dataset, cycle, summary, groups, location, questions):
    explicit = source.get("rates_by_cycle")
    selected = None
    if explicit is not None:
        if not isinstance(explicit, dict) or not _text(source.get("rate_source")):
            questions.append(location + ": rates_by_cycle requires a cycle mapping and rate_source")
            return None, None
        matches = [value for key, value in explicit.items() if str(key) == str(cycle)]
        if len(matches) > 1:
            questions.append(location + ": duplicate equivalent cycle keys in rates_by_cycle")
            return None, None
        if matches:
            selected = _rate(matches[0], location + ".rates_by_cycle", questions)
    native_value = summary.get("rate_c") if summary else None
    if native_value is None:
        observed = [row.get("rate_c") for branch in BRANCHES for _, row in groups[branch] if row.get("rate_c") is not None]
        native_rates = [_rate(value, location + ".native_rate_c", questions, native=True) for value in observed]
        signatures = {value["canonical"] for value in native_rates if value is not None}
        if len(signatures) > 1:
            questions.append(location + ": native C-rate varies within the cycle; one cycle-summary Rate cannot be inferred")
            return None, None
        native = next((value for value in native_rates if value is not None), None)
    else:
        native = _rate(native_value, location + ".native_rate_c", questions, native=True)
    if native is not None and selected is not None and native["canonical"] != selected["canonical"]:
        questions.append(location + ": explicit Rate conflicts with native rate_c")
        return None, None
    if selected is not None:
        return selected["label"], dict(method="explicit cycle-to-C-rate mapping", source=source["rate_source"])
    if native is not None:
        return native["label"], dict(method="reader-supplied native rate_c", source="canonical native rate_c field; no current or filename inference")
    questions.append(location + ": needs native rate_c or an explicit rates_by_cycle entry and source; no rate is guessed from current/filename")
    return None, None


def _source_info(source, dataset, number, errors):
    supplied = dataset.get("original_source") or {}
    raw = dataset.get("source") or {}
    if isinstance(supplied, str):
        supplied = {"file": supplied}
    if not isinstance(supplied, dict) or not isinstance(raw, dict):
        errors.append("source %d: reader source identities must be objects" % number)
        return None
    digest = supplied.get("sha256") or raw.get("sha256")
    if not _hash(digest):
        errors.append("source %d: canonical reader must preserve the native file SHA256" % number)
        return None
    original = supplied.get("file") or source["file"]
    if str(Path(original).resolve()) != str(Path(source["file"]).resolve()):
        errors.append("source %d: original source identity conflicts with request" % number)
    return dict(number=number, file=source["file"], sha256=digest,
                source_copy=raw.get("snapshot_file") or raw.get("file"),
                reader_source=deepcopy(raw), original_source=deepcopy(supplied),
                vendor=dataset.get("vendor"), format=dataset.get("format"),
                metadata=deepcopy(dataset.get("metadata") or {}), units=deepcopy(dataset.get("units") or {}),
                reader_issues=deepcopy(dataset.get("issues") or []))


def _standardize_rows(request, datasets, questions, errors):
    plot_type = request["plot_type"]
    selected = request.get("cycles", "all")
    selected = None if selected == "all" else set(int(value) for value in selected)
    wanted_branches = request.get("branches", list(BRANCHES))
    if plot_type == "cycle_performance" and set(wanted_branches) != set(BRANCHES):
        questions.append("cycle_performance needs both charge and discharge to supply capacity/CE")
    if plot_type == "rate_capability" and "discharge" not in wanted_branches:
        questions.append("rate_capability requires discharge capacity")
    headers = (["Sample", "Cycle", "Branch", "Voltage (V)", "Charge Specific Capacity (mAh/g)", "Discharge Specific Capacity (mAh/g)"]
               if plot_type == "gcd" else
               ["Sample", "Cycle", "Discharge Specific Capacity (mAh/g)", "Coulombic Efficiency (%)"]
               if plot_type == "cycle_performance" else
               ["Sample", "Cycle", "Rate", "Discharge Specific Capacity (mAh/g)"])
    headers += ["Source File", "Source SHA256", "Source Record Index", "Source Step"]
    rows, mapping, source_reports, expected = [], [], [], OrderedDict()
    hashes, samples = {}, {}
    for number, (source, dataset) in enumerate(zip(request["sources"], datasets), 1):
        location = "source %d (%s)" % (number, source["sample"])
        info = _source_info(source, dataset, number, errors)
        if info is None:
            continue
        if source.get("vendor", "auto") != "auto" and info["vendor"] != source["vendor"]:
            questions.append(location + ": decoded vendor conflicts with the explicitly selected instrument vendor")
        if info["sha256"] in hashes:
            questions.append(location + ": byte-identical source is also selected as source %d; no duplicate file is treated as another test" % hashes[info["sha256"]])
        hashes[info["sha256"]] = number
        if source["sample"] in samples:
            questions.append(location + ": another file uses the same Sample; provide distinct test identities, no continuation or averaging is inferred")
        samples[source["sample"]] = number
        mass = _mass(source, dataset, location, questions)
        info["selected_mass"] = deepcopy(mass)
        if plot_type != "gcd":
            # A stale/nonempty cycle table must not bypass reader findings.
            # Do not combine repeated native cycle IDs or select one pair.
            if info["metadata"].get("native_cycle_reset_detected"):
                questions.append(location + ": native cycle counter resets; cycle/rate grouping requires an explicit unambiguous cycle definition")
            if info["metadata"].get("native_cycle_contains_multiple_branch_pairs"):
                questions.append(location + ": a native cycle contains multiple charge/discharge pairs; no cycle/rate capacities are merged automatically")
        # Canonical decoded field names carry fixed units. Supplied unit
        # metadata must never contradict that interface or be guessed by scale.
        units = dataset.get("units") or {}
        accepted_units = {"voltage_V": ("V",), "capacity_mAh": ("mAh",),
                          "specific_capacity_mAh_g": ("mAh/g", "mAh g-1"),
                          "ce_percent": ("%",), "mass_g": ("g",), "rate_c": ("C",)}
        if not isinstance(units, dict):
            errors.append(location + ": canonical units metadata must be an object")
        else:
            for field, allowed in accepted_units.items():
                if field in units and units[field] not in allowed:
                    questions.append(location + ": decoded " + field + " unit contradicts its canonical interface; no scale inference")
        records = dataset.get("records")
        if not isinstance(records, list) or not records:
            questions.append(location + ": no canonical native records are available")
            source_reports.append(info)
            continue
        if any(not isinstance(row, dict) for row in records):
            errors.append(location + ": every native record must be an object")
            source_reports.append(info)
            continue
        identities = [row.get("record_index") for row in records]
        if any(not _integer(value) for value in identities) or len(set(identities)) != len(identities):
            questions.append(location + ": native record_index must be finite integral and unique; repeated rows are not deduplicated")
        elif any(after != before + 1 for before, after in zip(identities, identities[1:])):
            questions.append(location + ": record_index order has a gap/reset; no missing observations are filled or connected")
        summaries = dataset.get("cycles") or []
        if not isinstance(summaries, list) or any(not isinstance(row, dict) or not _integer(row.get("cycle")) for row in summaries):
            questions.append(location + ": native cycle summaries have ambiguous Cycle identities")
            summaries = []
        native_summary = {}
        for row in summaries:
            cycle = int(row["cycle"])
            if cycle in native_summary:
                questions.append(location + ": multiple native summary records for Cycle %d; no merging/first/last choice" % cycle)
            native_summary[cycle] = row
        observed = []
        grouped = {}
        for position, row in enumerate(records):
            branch, cycle = row.get("branch"), row.get("cycle")
            if branch == "rest":
                continue
            if not _integer(cycle):
                questions.append(location + ": an active/unknown record lacks an integral native Cycle")
                continue
            if selected is not None and int(cycle) not in selected:
                continue
            if branch not in BRANCHES:
                questions.append(location + ": selected record %r has an unknown native branch; current sign is not used" % row.get("record_index"))
                continue
            grouped.setdefault(int(cycle), {name: [] for name in BRANCHES})[branch].append((position, row))
            if int(cycle) not in observed:
                observed.append(int(cycle))
        available = observed if plot_type == "gcd" else list(native_summary) or observed
        cycles = [cycle for cycle in available if selected is None or cycle in selected]
        if selected is not None:
            missing = selected - set(cycles)
            if missing:
                questions.append(location + ": requested Cycle values are absent: " + str(sorted(missing)))
        if not cycles:
            questions.append(location + ": no selected cycles can be exported")
        if plot_type == "cycle_performance" and any(b <= a for a, b in zip(cycles, cycles[1:])):
            questions.append(location + ": cycle summary order is not strictly increasing; it is not sorted or renumbered automatically")
        counts = Counter()
        for row in records:
            if row.get("branch") == "rest":
                counts["rest_records_not_plotted"] += 1
            elif selected is not None and row.get("cycle") not in selected:
                counts["unselected_cycle_records"] += 1
            elif row.get("branch") not in wanted_branches:
                counts["unselected_branch_records"] += 1
            else:
                counts["selected_active_records"] += 1
        counts["all_native_records_retained_by_reader"] = len(records)
        info["record_disposition_counts"] = dict(counts)
        source_reports.append(info)
        for cycle in cycles:
            summary = native_summary.get(cycle)
            groups = grouped.get(cycle, {name: [] for name in BRANCHES})
            for branch in wanted_branches:
                if not groups[branch] or (summary and summary.get(branch + "_present") is False):
                    questions.append(location + ": Cycle %d lacks the requested %s branch; no missing branch is created" % (cycle, branch))
            if plot_type == "gcd":
                duplicate_points = {}
                values_by_record = {}
                for branch in wanted_branches:
                    group = groups[branch]
                    label = location + " Cycle %d %s" % (cycle, branch)
                    if not _continuous(group, records, info["metadata"].get("capacity_basis"), label, questions):
                        continue
                    specific_values = []
                    for _, record in group:
                        voltage = record.get("voltage_V")
                        if not _finite(voltage):
                            questions.append(label + ": record %r lacks finite voltage_V" % record.get("record_index"))
                            continue
                        value, method = _specific(record, "specific_capacity_mAh_g", "capacity_mAh", mass, label, questions)
                        if value is None:
                            continue
                        point = (float(value), float(voltage))
                        duplicate_key = (branch, point)
                        if duplicate_key in duplicate_points:
                            questions.append(label + ": duplicate Q/V at native records %r and %r; existing GCD duplicate policy remains blocking" % (duplicate_points[duplicate_key], record["record_index"]))
                        duplicate_points[duplicate_key] = record["record_index"]
                        specific_values.append(value)
                        values_by_record[record["record_index"]] = (branch, value, voltage, method)
                    _nondecreasing(specific_values, label, questions)
                observed_rows = [item for branch in wanted_branches for item in groups[branch]]
                for _, record in sorted(observed_rows, key=lambda item: item[0]):
                    if record.get("record_index") not in values_by_record:
                        continue
                    branch, value, voltage, method = values_by_record[record["record_index"]]
                    rows.append([source["sample"], cycle, branch, voltage,
                                 value if branch == "charge" else None, value if branch == "discharge" else None,
                                 source["file"], info["sha256"], record["record_index"], record.get("step")])
                    expected.setdefault((source["sample"], cycle, branch), []).append((float(value), float(voltage)))
                    mapping.append(dict(standard_row=len(rows) + 1, source_number=number, cycle=cycle, branch=branch,
                                        record_index=record["record_index"], native_record_number=record.get("native_record_number"),
                                        step=record.get("step"), capacity=method))
            else:
                discharge, discharge_method = _cycle_capacity(cycle, "discharge", summary, groups, info["metadata"], mass,
                    location + " Cycle %d discharge" % cycle, questions)
                if discharge is None:
                    continue
                values = [source["sample"], cycle]
                methods = {"discharge_capacity": discharge_method}
                if plot_type == "cycle_performance":
                    native_ce = summary.get("ce_percent") if summary is not None else None
                    if native_ce is not None:
                        if not _finite(native_ce):
                            questions.append(location + ": native ce_percent is not finite")
                            continue
                        ce = float(native_ce)
                        basis = info["metadata"].get("cycle_capacity_basis")
                        ce_method = ("reader_derived_ce_percent" if basis == "sum_of_native_step_endpoints" else
                                     "supplied_native_ce_percent" if basis == "native_cycle_branch_summary" else
                                     "reader_supplied_ce_percent")
                        methods["ce_percent"] = dict(method=ce_method, unit="%", cycle_capacity_basis=basis,
                                                     cycle_summary_source=info["metadata"].get("cycle_summary_source"))
                    else:
                        charge, charge_method = _cycle_capacity(cycle, "charge", summary, groups, info["metadata"], mass,
                            location + " Cycle %d charge" % cycle, questions)
                        if charge is None or charge == 0:
                            questions.append(location + ": CE needs nonzero charge capacity; no zero denominator or invented efficiency")
                            continue
                        ce = discharge / charge * 100.
                        methods["ce_percent"] = dict(method="100 * discharge_specific_capacity / charge_specific_capacity", unit="%", charge=charge_method)
                    values += [discharge, ce]
                    expected.setdefault((source["sample"], "discharge_capacity"), []).append((float(cycle), float(discharge)))
                    expected.setdefault((source["sample"], "coulombic_efficiency"), []).append((float(cycle), float(ce)))
                else:
                    rate, rate_method = _cycle_rate(source, dataset, cycle, summary, groups, location + " Cycle %d" % cycle, questions)
                    if rate is None:
                        continue
                    values += [rate, discharge]
                    methods["rate"] = rate_method
                    expected.setdefault((source["sample"], "discharge_capacity"), []).append((float(cycle), float(discharge)))
                values += [source["file"], info["sha256"], None, None]
                rows.append(values)
                mapping.append(dict(standard_row=len(rows) + 1, source_number=number, cycle=cycle,
                                    native_summary_row=summary.get("source_row_index") if summary else None,
                                    record_ranges={branch: _runs([int(row["record_index"]) for _, row in groups[branch] if _integer(row.get("record_index"))]) for branch in BRANCHES},
                                    steps={branch: list(OrderedDict((str(row.get("step")), None) for _, row in groups[branch])) for branch in BRANCHES},
                                    methods=methods, completion_status=summary.get("completion_status", "not_inferred") if summary else "not_inferred"))
    if plot_type == "rate_capability":
        expected = OrderedDict((key, sorted(points, key=lambda point: point[0])) for key, points in expected.items())
    return headers, rows, mapping, source_reports, expected


def standardize(request, datasets, destination):
    """Return a ready existing-input bridge, or concentrated scientific gaps.

    Public XLSX/PlotSpec/manifest are committed only after the standard reader and
    plan accept the candidate values. A failed candidate leaves no public bridge.
    """
    result = dict(ready=False, questions=[], errors=[], plot_spec=None, workbook=None, manifest=None,
                  origin_executed=False, data_kind_expanded=False, scientific_truth_verified=False)
    questions, errors = result["questions"], result["errors"]
    if not isinstance(request, dict) or request.get("schema_version") != 1 or isinstance(request.get("schema_version"), bool):
        errors.append("instrument request requires schema_version=1")
        return result
    if request.get("plot_type") not in PLOT_TYPES:
        errors.append("instrument standardization supports gcd, cycle_performance or rate_capability only")
        return result
    sources = request.get("sources")
    if not isinstance(sources, list) or not sources or not isinstance(datasets, list) or len(datasets) != len(sources):
        errors.append("sources and canonical reader datasets must be nonempty equal-length lists")
        return result
    if not _text(request.get("source")):
        questions.append("request.source must describe this task's input/selection provenance")
    cycles = request.get("cycles", "all")
    if cycles != "all" and (not isinstance(cycles, list) or not cycles or any(not _integer(value) for value in cycles) or len(set(cycles)) != len(cycles)):
        errors.append("cycles must be all or a nonempty unique list of native integral Cycle values")
    branches = request.get("branches", list(BRANCHES))
    if not isinstance(branches, list) or not branches or any(value not in BRANCHES for value in branches) or len(set(branches)) != len(branches):
        errors.append("branches must explicitly select charge/discharge without duplicates")
    task_name = request.get("task_name")
    if not _text(task_name) or task_name in (".", "..") or any(c in task_name for c in '\\/:*?"<>|;\r\n\x00'):
        errors.append("task_name must be one explicit safe output component")
    directory = Path(destination)
    if not directory.is_absolute():
        errors.append("standardization destination must be an absolute independent task directory")
        return result
    directory = directory.resolve()
    if _inside(directory, Path(SKILL_ROOT).resolve()):
        errors.append("standardized data cannot be written inside the skill")
    for index, (source, dataset) in enumerate(zip(sources, datasets), 1):
        if not isinstance(source, dict) or not isinstance(dataset, dict):
            errors.append("source %d and its reader dataset must be objects" % index)
            continue
        if not _text(source.get("file")) or not Path(source["file"]).is_absolute():
            errors.append("source %d file must be an explicit absolute original path" % index)
        elif _inside(directory, Path(source["file"]).resolve().parent):
            errors.append("standardization must not write inside an original source directory")
        if source.get("vendor", "auto") not in ("auto", "land", "neware"):
            errors.append("source %d vendor must be auto/land/neware" % index)
        if not _text(source.get("sample")):
            questions.append("source %d needs an explicit test/sample label; no identity is guessed from filename" % index)
    if questions or errors:
        return result
    try:
        headers, rows, mapping, source_reports, expected = _standardize_rows(request, datasets, questions, errors)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        errors.append(str(exc))
        return result
    result["source_reports"] = source_reports
    if not rows:
        questions.append("no standard plotting rows were produced")
    if len(rows) > MAX_DATA_ROWS:
        questions.append("Selected data exceed the existing single-sheet Excel row limit; explicitly select cycles/sources or split tasks; no records are truncated")
    if questions or errors:
        return result
    names = ("standard_input.xlsx", "plot_spec.json", "instrument_manifest.json")
    if any((directory / name).exists() for name in names):
        errors.append("bridge destination already contains a standard input/spec/manifest; no overwrite")
        return result
    directory.mkdir(parents=True, exist_ok=True)
    workbook, spec_path, manifest_path = [directory / name for name in names]
    manifest = dict(schema_version=1, source_kind="instrument_project", request=deepcopy(request),
                    sources=source_reports, row_mapping=mapping,
                    output=dict(workbook=str(workbook), plot_spec=str(spec_path), plot_type=request["plot_type"], rows=len(rows)),
                    policy=dict(source_data_modified=False, source_rows_dropped=False,
                                rest_and_unselected_records="retained in reader datasets; not GCD/summary plotting observations; exact disposition counts retained",
                                duplicate_policy="blocking; no blanket native duplicate approval",
                                branch_source="canonical native branch; never current sign", cycle_numbering="preserved native canonical cycle; no restart renumbering",
                                capacity_policy="native specific/summary preferred; only explicit mAh / active-material g conversion",
                                ce_policy="native percent preferred; otherwise 100 * Qdis / Qcharge with recorded inputs",
                                rate_policy="native rate_c or explicit cycle mapping only", completion_not_inferred=True))
    created = []
    try:
        with tempfile.TemporaryDirectory(prefix="instrument_bridge_", dir=str(directory)) as staging:
            temporary = Path(staging)
            staged_workbook = temporary / names[0]
            write_standard_xlsx(staged_workbook, headers, rows)
            manifest["output"]["workbook_sha256"] = _sha(staged_workbook)
            manifest_text = _json(manifest)
            manifest_hash = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
            reference = dict(manifest_file=str(manifest_path), sha256=manifest_hash, source_kind="instrument_project")
            document = dict(spec_version=1, task_name=request["task_name"], plot_type=request["plot_type"],
                            output_root=str(directory / "figures"),
                            data=dict(kind="excel_long" if request["plot_type"] == "gcd" else "excel_cycle_summary",
                                      file=str(staged_workbook), sheet="Sheet1", sample_column="Sample",
                                      notes=["Automatically standardized from native instrument data; original engineering files remain read-only",
                                             "Original/native record to standard row mapping: " + str(manifest_path)],
                                      semantics=dict(instrument_import=reference)),
                            selection=dict(mode="all") if request["plot_type"] == "gcd" else {},
                            style_template=str(Path(SKILL_ROOT) / "templates/publication_visual_template.yaml"),
                            backend=dict(name="origin"), verification=dict(level=3, reopen_project=True, editability_probe=True))
            if request["plot_type"] == "gcd":
                # Native measurement fields establish voltage and V, but do
                # not establish a Na/Na+ (or any other) reference electrode.
                # Use the existing PlotSpec axis-title override contract.
                document["labels"] = {"y": "Voltage (V)"}
            if request["plot_type"] == "cycle_performance":
                document["data"]["semantics"]["ce_unit"] = "percent"
                document["overrides"] = {"plot_type": {"native_layout": {"enabled": True, "mode": "separated_bands"}}}
                document["legend"] = {"mode": "entries", "layout": "paired_samples", "position": "bottom_left"}
            _, normalized, validation, plan = prepare(PlotSpec.from_dict(document))
            actual = OrderedDict(((item.sample, item.cycle, item.branch) if request["plot_type"] == "gcd" else (item.sample, item.metric), item.points)
                                 for item in normalized.series)
            if dict(actual) != dict(expected):
                raise RuntimeError("Existing A reader changed an imported group, point value or point order")
            for item in plan.data_series:
                if item.metadata.get("instrument_import") != reference:
                    raise RuntimeError("Native plotting plan lost the complete instrument manifest identity")
            shutil.copyfile(str(staged_workbook), str(workbook))
            created.append(workbook)
            # The reference hashes these exact UTF-8 bytes. Do not let Windows
            # text newline translation change the committed manifest identity.
            manifest_path.write_bytes(manifest_text.encode("utf-8"))
            created.append(manifest_path)
            document["data"]["file"] = str(workbook)
            spec_path.write_text(_json(document), encoding="utf-8")
            created.append(spec_path)
            _, final_data, final_validation, final_plan = prepare(PlotSpec.from_file(str(spec_path)))
            final_actual = {((item.sample, item.cycle, item.branch) if request["plot_type"] == "gcd" else (item.sample, item.metric)): item.points
                            for item in final_data.series}
            if final_actual != dict(expected) or _sha(workbook) != manifest["output"]["workbook_sha256"] or _sha(manifest_path) != manifest_hash:
                raise RuntimeError("Committed standard input/mapping differs from verified staged values")
            result.update(ready=True, plot_spec=str(spec_path), workbook=str(workbook), manifest=str(manifest_path),
                          manifest_sha256=manifest_hash, pointwise_verified=True, rows=len(rows),
                          series=len(final_data.series), points=sum(len(item.points) for item in final_data.series),
                          validation=final_validation.to_dict(), instrument_import=reference,
                          selection_preserved=dict(cycles=deepcopy(request.get("cycles", "all")), branches=list(branches)),
                          plan=dict(plot_type=final_plan.plot_type, scientific_series=len(final_plan.data_series),
                                    rate_stages=deepcopy(final_plan.page.get("rate_stages"))))
    except InputContractError as exc:
        if exc.report is not None:
            questions.extend(exc.report.questions)
            errors.extend(exc.report.errors)
        if not questions and not errors:
            errors.append(str(exc))
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        errors.append(str(exc))
    if not result["ready"]:
        # Remove only the exact new public files this invocation created. Source
        # engineering files and caller-owned extraction evidence are untouched.
        for path in created:
            if path.resolve().parent != directory:
                raise RuntimeError("Unsafe bridge cleanup target")
            path.unlink()
    return result
