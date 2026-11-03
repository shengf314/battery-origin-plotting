"""GCD dialect: point-level long-format rows -> grouped XY series."""

from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from ....ingest.normalize import NormalizedData, NormalizedSeries
from ....ingest.report import ValidationReport
from ....ingest.xlsx import Workbook
from ....models import PlotSpec
from .. import schema

BRANCH_ORDER = ("charge", "discharge")
VARIANT_COLUMNS = {
    "specific_capacity": {"charge": "Charge Specific Capacity",
                          "discharge": "Discharge Specific Capacity"},
    "na_content": {"charge": "Charge Na Content",
                   "discharge": "Discharge Na Content"},
}


def _selection(selection: Dict) -> Dict:
    mode = (selection or {}).get("mode") or "all"
    if mode not in ("all", "single", "selected", "range"):
        raise ValueError("gcd selection.mode must be all/single/selected/range")
    out = {"mode": mode}
    if mode == "single":
        out["cycles"] = [int(selection.get("cycle", selection.get("cycles", [None])[0]))]
    elif mode == "selected":
        out["cycles"] = [int(value) for value in selection.get("cycles", [])]
    elif mode == "range":
        out["from"] = int(selection["from"])
        out["to"] = int(selection["to"])
        if out["from"] > out["to"]:
            raise ValueError("gcd selection.from must not exceed selection.to")
    return out


def _selected(cycle: int, selection: Dict) -> bool:
    mode = selection["mode"]
    if mode == "all":
        return True
    if mode == "single":
        return cycle == selection["cycles"][0]
    if mode == "selected":
        return cycle in set(selection["cycles"])
    return selection["from"] <= cycle <= selection["to"]


def load(spec: PlotSpec, workbook: Workbook, report: ValidationReport) -> NormalizedData:
    data = spec.data
    variant = str((spec.selection or {}).get("x_representation") or "specific_capacity")
    if variant not in VARIANT_COLUMNS:
        raise ValueError("gcd x_representation must be specific_capacity or na_content")
    selection = _selection(spec.selection or {})
    binding = (spec.selection or {}).get("axis_binding", "capacity_voltage")
    if binding not in ("capacity_voltage", "voltage_capacity"):
        raise ValueError("gcd axis_binding must be capacity_voltage/voltage_capacity")
    skip_rows = {int(row) for row in ((spec.verification or {}).get("approved_skip_rows") or [])}
    use_sample_column = bool(data.sample_column)

    sheet = data.sheet or "Sheet1"
    header = workbook.header(sheet, int((spec.selection or {}).get("header_row", 1)))
    if not header:
        report.question("worksheet %r has no header row" % sheet)
        return NormalizedData(plot_type="gcd")
    mapping = schema.map_headers(header, data.field_map, report)
    schema.validate_legacy_units(header, mapping, report)
    semantics = data.semantics or {}
    if not isinstance(semantics, dict):
        report.error("GCD data.semantics must be an object")
        report.raise_if_blocking("GCD scientific semantics")
    for axis in ("x", "y"):
        declared = semantics.get(axis) or {}
        if not isinstance(declared, dict):
            report.error("GCD semantics.%s must be an axis object" % axis)
            continue
        if declared.get("direction", "ascending") not in ("ascending", "descending"):
            report.error("GCD semantics.%s.direction must be ascending/descending" % axis)
        if declared.get("scale", "linear") not in ("linear", "log10"):
            report.error("GCD semantics.%s.scale must be linear/log10" % axis)
        voltage_axis = (axis == "y") == (binding == "capacity_voltage")
        quantities = (("voltage",) if voltage_axis else
                      ("specific_capacity",) if variant == "specific_capacity" else
                      ("na_content", "delta_na_content"))
        units = (("V",) if voltage_axis else ("mAh g-1",) if variant == "specific_capacity" else
                 ("1", "Na fu-1"))
        if declared.get("quantity") and declared["quantity"] not in quantities:
            report.error("GCD semantics.%s.quantity conflicts with the selected field binding" % axis)
        if declared.get("unit") and declared["unit"] not in units:
            report.error("GCD semantics.%s.unit conflicts with the legacy standard field unit" % axis)
        if declared.get("quantity") == "delta_na_content" and not declared.get("label"):
            report.question("delta Na requires an explicit delta-x axis label, not the absolute-content template title")
    if variant == "na_content" and semantics:
        record = semantics.get("na_content") or {}
        if not isinstance(record, dict):
            report.error("GCD semantics.na_content must be an object")
        elif any(not isinstance(record.get(key), str) or not record[key].strip() or
                 record[key].strip().lower() == "unknown" for key in ("source", "reference")):
            report.question("declared Na semantics require na_content.source and reference; do not infer its origin or zero")
    if variant == "na_content" and not semantics:
        report.warn("Legacy supplied Na coordinates accepted; absolute x versus delta x and the reference/source remain unknown. No conversion was performed.")
    report.header_map = mapping
    required = ["Cycle", "Branch", "Voltage", VARIANT_COLUMNS[variant]["charge"],
                VARIANT_COLUMNS[variant]["discharge"]]
    if use_sample_column:
        required.append("Sample")
    schema.require_fields(mapping, required, report)
    report.counts["required_columns"] = required

    groups: "OrderedDict[Tuple[str, int, str], List[Tuple[float, float]]]" = OrderedDict()
    rows_of: Dict[Tuple[str, int, str], List[int]] = {}
    skipped: Dict[Tuple[str, int, str], List[int]] = {}
    samples_seen: List[str] = []
    duplicates: List[Dict] = []
    seen_points = set()
    active_branch, closed_branches = {}, set()
    excluded_counts: Dict[str, int] = {}
    rest_rows = 0
    row_count = 0
    start_row = int((spec.selection or {}).get("header_row", 1)) + 1

    if report.blocking:
        report.raise_if_blocking("GCD input validation")

    def cell_value(row_cells, field):
        letter = mapping.get(field)
        return row_cells.get(letter) if letter else None

    for row_number, cells in workbook.rows(sheet, start_row=start_row):
        branch_cell = cell_value(cells, "Branch")
        if schema.excluded_value_matches(branch_cell, data.exclude_values.get("Branch", [])):
            rest_rows += 1
            continue
        if all(cell.is_empty for cell in cells.values()):
            continue
        row_count += 1
        cycle = schema.normalize_cycle(cell_value(cells, "Cycle"), report, row_number)
        branch = schema.normalize_branch(branch_cell, data.value_map.get("Branch", {}),
                                         report, row_number)
        if cycle is None or branch is None:
            continue
        sample_cell = cell_value(cells, "Sample") if use_sample_column else None
        if use_sample_column:
            raw_sample = (sample_cell.text if sample_cell and sample_cell.text is not None
                          else None)
            if raw_sample is None or not str(raw_sample).strip():
                report.question("Sample is empty at row %d; confirm which sample it "
                                "belongs to" % row_number)
                continue
            sample = str(raw_sample).strip()
        else:
            sample = spec.samples[0].get("name") if spec.samples else "sample"
        if sample not in samples_seen:
            samples_seen.append(sample)
        if not _selected(cycle, selection):
            continue
        key = (sample, cycle, branch)
        scope = (sample, cycle)
        previous = active_branch.get(scope)
        if previous is not None and previous != branch:
            closed_branches.add((sample, cycle, previous))
        if key in closed_branches:
            report.error("GCD branch returns after another branch at row %d; define separate continuous series instead of connecting segments" % row_number)
        active_branch[scope] = branch
        x_field = VARIANT_COLUMNS[variant][branch]
        x = schema.numeric_value(cell_value(cells, x_field), x_field, report, row_number,
                                 " (%s / cycle %d / %s)" % (sample, cycle, branch))
        y = schema.numeric_value(cell_value(cells, "Voltage"), "Voltage", report,
                                 row_number, " (%s / cycle %d / %s)" % (sample, cycle, branch))
        if x is None or y is None:
            if row_number in skip_rows:
                skipped.setdefault(key, []).append(row_number)
                continue
            continue
        if binding == "voltage_capacity":
            x, y = y, x
        for axis, value in (("x", x), ("y", y)):
            if (semantics.get(axis) or {}).get("scale") == "log10" and value <= 0:
                report.error("GCD %s log10 axis has nonpositive value at row %d" % (axis, row_number))
        point_key = (sample, cycle, branch, x, y)
        if point_key in seen_points and len(duplicates) < 15:
            duplicates.append({"sample": sample, "cycle": cycle, "branch": branch,
                               "x": x, "y": y, "row": row_number})
        seen_points.add(point_key)
        groups.setdefault(key, []).append((x, y))
        rows_of.setdefault(key, []).append(row_number)

    if duplicates:
        report.duplicates = duplicates
        report.question("%d possible duplicate point(s) were found (see duplicates); "
                        "confirm that they should be kept" % len(duplicates))
    if rest_rows:
        excluded_counts["excluded rows (Branch in exclude_values)"] = rest_rows
    report.counts["rows_read"] = row_count
    report.counts["rows_excluded"] = rest_rows

    expected = _expected_keys(samples_seen, spec, selection)
    missing = [key for key in expected if key not in groups]
    if missing:
        preview = ", ".join("%s cycle %d %s" % item for item in missing[:10])
        report.question("%d requested sample/cycle/branch combination(s) have no points: %s"
                        % (len(missing), preview))
    report.raise_if_blocking("GCD input validation")

    series: List[NormalizedSeries] = []
    for (sample, cycle, branch), points in groups.items():
        series.append(NormalizedSeries(
            sample=sample, cycle=cycle, branch=branch, points=points,
            first_row=min(rows_of.get((sample, cycle, branch), [0])) or None,
            last_row=max(rows_of.get((sample, cycle, branch), [0])) or None,
            approved_skips=skipped.get((sample, cycle, branch), [])))
    normalized = NormalizedData(
        plot_type="gcd",
        series=series,
        sample_order=samples_seen,
        axes=("x", "y"),
        excluded=excluded_counts,
        source={
            "file": data.file,
            "sheet": sheet,
            "header_row": int((spec.selection or {}).get("header_row", 1)),
            "x_representation": variant,
            "axis_binding": binding,
            "semantics": semantics,
            "selection": selection,
            "rows": row_count,
            "series": len(series),
            "points": sum(len(item.points) for item in series),
        })
    return normalized


def _expected_keys(samples: List[str], spec: PlotSpec,
                   selection: Dict) -> List[Tuple[str, int, str]]:
    """Combinations the request implies (used to report missing data)."""
    cycles: List[int] = []
    for item in spec.samples:
        mode = (item.get("cycles") or {}).get("mode")
        if mode == "range":
            cycles.extend(range(int(item["cycles"]["from"]), int(item["cycles"]["to"]) + 1))
        elif mode in ("single", "selected"):
            cycles.extend(int(cycle) for cycle in item.get("cycles", {}).get("cycles", []))
    if not cycles:
        if selection["mode"] == "range":
            cycles = list(range(selection["from"], selection["to"] + 1))
        elif selection["mode"] in ("single", "selected"):
            cycles = list(selection["cycles"])
    cycles = sorted(set(cycles))
    keys = []
    for sample in samples:
        for cycle in cycles:
            for branch in BRANCH_ORDER:
                keys.append((sample, cycle, branch))
    return keys
