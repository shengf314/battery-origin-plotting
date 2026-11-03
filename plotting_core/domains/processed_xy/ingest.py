"""Read supplied XY series with exact grouping, units and provenance declarations."""

from collections import OrderedDict
import copy
import math
import re

from ...ingest.normalize import NormalizedData, NormalizedSeries
from ... import registry
from ...provenance import traceability_summary
from ..electrochemistry import schema
from . import contracts


def _key(value):
    return re.sub(r"[\s_\-]+", "", str(value)).lower()


def _text(cell, report, field, row):
    if cell is None or cell.is_empty:
        return None
    if cell.text is not None:
        return str(cell.text).strip()
    if isinstance(cell.value, bool) or not isinstance(cell.value, (int, float)):
        report.question("%s at row %d must be text or a finite numeric identifier" % (field, row))
        return None
    try:
        if not math.isfinite(cell.value):
            report.question("%s at row %d is a non-finite identifier" % (field, row))
            return None
        return str(int(cell.value)) if cell.value == int(cell.value) else str(cell.value)
    except (OverflowError, TypeError, ValueError):
        report.question("%s at row %d is not a finite identifier" % (field, row))
        return None


def _mapping(header, field_map, report):
    known = {_key(name): name for name in contracts.FIELDS}
    if not isinstance(field_map, dict):
        report.error("data.field_map must be an object of raw header -> canonical field")
        field_map = {}
    for raw, target in field_map.items():
        if not isinstance(raw, str) or not isinstance(target, str):
            report.error("data.field_map keys and targets must be strings")
    explicit = {_key(raw): target for raw, target in (field_map or {}).items()}
    mapping = {}
    error_names = ("yerror", "yerr", "yerrorminus", "yerrorplus", "errorbar", "sd", "stderr",
                   "standarddeviation", "standarderror", "errorminus", "errorplus", "sigma",
                   "uncertainty", "error", "se", "sem", "stdev", "stddev", "variance",
                   "误差", "标准差", "标准误")
    for letter, raw in header.items():
        key = _key(raw)
        if key in error_names or any(word in key for word in ("error", "uncertainty", "sigma", "stddev", "stdev", "误差", "标准差", "标准误")):
            report.error("uncertainty column %r is present, but error bars are not implemented" % raw)
        field = explicit.get(key, known.get(key))
        if field is None:
            continue
        if field not in contracts.FIELDS:
            report.error("field_map target %r is unsupported (header %r)" % (field, raw))
        elif field in mapping:
            report.error("two columns map to %s; binding is ambiguous" % field)
        else:
            mapping[field] = letter
            if key not in known:
                report.record_mapping("%s -> %s (explicit processed-series field_map)" % (raw, field))
    for field in ("SeriesID", "Sample", "X", "Y"):
        if field not in mapping:
            report.question("required processed-series field %s is missing" % field)
    return mapping


def load(family, spec, workbook, report):
    registry.validate_data_kind(family, "excel_processed_series")
    if spec.plot_type != family:
        raise ValueError("processed reader family must match the registered PlotSpec plot type")
    semantics = copy.deepcopy(spec.data.semantics)
    contracts.validate_semantics(family, semantics, report)
    if not isinstance(semantics, dict):
        semantics = {}
    selection = spec.selection or {}
    verification = spec.verification or {}
    if not isinstance(selection, dict):
        report.error("processed selection must be an object")
        selection = {}
    if not isinstance(verification, dict):
        report.error("processed verification must be an object")
        verification = {}
    if spec.data.exclude_values or spec.data.value_map:
        report.error("processed-series inputs do not silently filter or recode rows; supply explicit values")
    if verification.get("approved_skip_rows"):
        report.error("processed-series missing points cannot be skipped; provide separate explicit segments")
    unknown_selection = set(selection) - {"header_row", "series_ids", "cycles", "branches"}
    if unknown_selection:
        report.error("unsupported processed-series selection fields: %s" % ", ".join(sorted(str(key) for key in unknown_selection)))
    sheet = spec.data.sheet or "Sheet1"
    header_row = selection.get("header_row", 1)
    if isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1:
        report.error("selection.header_row must be a positive integral row number excluding bool")
        header_row = 1
    header = workbook.header(sheet, header_row)
    mapping = _mapping(header, spec.data.field_map, report)
    report.header_map = mapping
    if family == "icp" and "Element" not in mapping:
        report.question("ICP requires Element for each supplied observation")
    if "Frequency" in mapping:
        frequency = semantics.get("frequency") or {}
        if not isinstance(frequency, dict):
            frequency = {}
        if frequency.get("unit") != "Hz" or frequency.get("order") != "as_provided":
            report.question("Frequency requires semantics.frequency={unit:Hz, order:as_provided}; no sorting is performed")
    report.raise_if_blocking("%s processed input contract" % family)
    groups = OrderedDict()
    group_rows = {}
    group_metadata = {}
    sample_order = []
    closed = set()
    previous = None
    seen_records = set()
    validated_ids = set(semantics["series_metadata"])
    elements_by_x = {}
    x_by_element = {}
    row_count = 0

    def cell(cells, field):
        return cells.get(mapping.get(field))

    for number, cells in workbook.rows(sheet, start_row=header_row + 1):
        if all(value.is_empty for value in cells.values()):
            if previous is not None:
                closed.add(previous)
                previous = None
            continue
        row_count += 1
        series_id = _text(cell(cells, "SeriesID"), report, "SeriesID", number)
        sample = _text(cell(cells, "Sample"), report, "Sample", number)
        if not series_id or not sample:
            report.question("SeriesID/Sample missing at row %d" % number)
            continue
        if sample not in sample_order:
            sample_order.append(sample)
        record = copy.deepcopy((semantics.get("series_metadata") or {}).get(series_id) or {})
        if series_id not in validated_ids:
            contracts.validate_series(family, semantics, record, report, series_id)
            validated_ids.add(series_id)
        if record.get("sample") is not None and str(record["sample"]) != sample:
            report.error("SeriesID %s sample declaration conflicts with row %d" % (series_id, number))
        segment = _text(cell(cells, "Segment"), report, "Segment", number) if "Segment" in mapping else None
        if "Segment" in mapping and not segment:
            report.question("Segment is missing at row %d; a connection boundary cannot be inferred" % number)
        group = (series_id, segment)
        connection = record.get("connection")
        if group != previous:
            if previous is not None:
                closed.add(previous)
            allow_interleaved_scatter = semantics.get("row_layout") == "interleaved" and connection == "scatter"
            if group in closed and not allow_interleaved_scatter:
                report.question("SeriesID %s Segment %s reappears at row %d after a boundary; provide distinct Segment values"
                                % (series_id, segment, number))
            previous = group
        x = schema.numeric_value(cell(cells, "X"), "X", report, number)
        y = schema.numeric_value(cell(cells, "Y"), "Y", report, number)
        if x is None or y is None:
            continue
        for axis, value in (("x", x), ("y", y)):
            if semantics[axis]["scale"] == "log10" and value <= 0:
                report.error("%s log10 axis has non-positive data at row %d" % (axis.upper(), number))
        current = {"sample": sample}
        for field in ("Branch", "Role", "Condition"):
            value = _text(cell(cells, field), report, field, number) if field in mapping else record.get(field.lower())
            if field in mapping and not value:
                report.question("%s is missing at row %d" % (field, number))
            if field in mapping and record.get(field.lower()) is not None and value != str(record[field.lower()]):
                report.error("%s declaration conflicts with row %d in SeriesID %s" % (field, number, series_id))
            current[field.lower()] = value
        if current["role"] is None:
            current["role"] = record.get("role")
        if current["role"] not in contracts.ROLES:
            report.error("unknown scientific Role at row %d" % number)
        if "Cycle" in mapping:
            cycle = schema.normalize_cycle(cell(cells, "Cycle"), report, number)
        else:
            cycle = record.get("cycle")
            if cycle is not None and (not isinstance(cycle, int) or isinstance(cycle, bool)):
                report.error("cycle metadata for %s must be integral" % series_id)
        if "Cycle" in mapping and record.get("cycle") is not None and cycle != record["cycle"]:
            report.error("Cycle declaration conflicts with row %d" % number)
        current["cycle"] = cycle
        if family == "gitt":
            if current["branch"] not in ("charge", "discharge"):
                report.question("%s requires explicit charge/discharge branch at row %d" % (family, number))
        if group in group_metadata:
            prior = group_metadata[group]["identity"]
            if prior != current:
                report.error("SeriesID %s Segment %s crosses sample/cycle/branch/role/condition at row %d; split series or segment"
                             % (series_id, segment, number))
        else:
            group_metadata[group] = {"identity": current, "record": record, "frequency": [],
                                     "phase": [], "elements": []}
        extra = []
        if "Frequency" in mapping:
            frequency = schema.numeric_value(cell(cells, "Frequency"), "Frequency", report, number)
            if frequency is not None and frequency <= 0:
                report.error("Frequency must be positive at row %d" % number)
            group_metadata[group]["frequency"].append(frequency)
            extra.append(frequency)
        if "Phase" in mapping:
            phase = _text(cell(cells, "Phase"), report, "Phase", number)
            if not phase:
                report.question("Phase is missing at row %d" % number)
            group_metadata[group]["phase"].append(phase)
            extra.append(phase)
        if "Element" in mapping:
            element = _text(cell(cells, "Element"), report, "Element", number)
            if not element:
                report.question("Element is missing at row %d" % number)
            group_metadata[group]["elements"].append(element)
            extra.append(element)
            if family == "icp":
                if x != int(x) or x <= 0:
                    report.error("ICP element_index X must be a positive integer at row %d" % number)
                if (x in elements_by_x and elements_by_x[x] != element) or (element in x_by_element and x_by_element[element] != x):
                    report.error("ICP Element and element_index must have one consistent mapping")
                elements_by_x[x] = element
                x_by_element[element] = x
        record_key = (group, tuple(sorted(current.items())), x, y, tuple(extra))
        if record_key in seen_records:
            report.duplicates.append({"series_id": series_id, "segment": segment, "row": number, "x": x, "y": y})
            report.error("duplicate record at row %d; repeated observations need explicit independent SeriesID/Segment" % number)
        seen_records.add(record_key)
        if family == "icp" and semantics.get("variant") == "element_ratio" and y < 0:
            report.error("an elemental ratio cannot be negative at row %d" % number)
        if family == "gitt" and semantics.get("variant") == "supplied_diffusion" and semantics["y"]["quantity"] == "diffusion_coefficient" and y <= 0:
            report.error("supplied diffusion coefficients must be positive (row %d)" % number)
        if family == "icp" and semantics.get("variant") == "normalized_composition":
            limit = 1.0 if semantics["y"]["unit"] == "1" else 100.0
            if not 0 <= y <= limit:
                report.error("composition fraction is outside the explicitly declared unit range at row %d" % number)
        groups.setdefault(group, []).append((x, y))
        group_rows.setdefault(group, []).append(number)
    if not groups:
        report.error("no supplied XY series were produced")
    report.counts.update(rows_read=row_count, rows_excluded=0, series=len(groups),
                         points=sum(len(points) for points in groups.values()))
    report.raise_if_blocking("%s processed input contract" % family)
    series = []
    output_ids = set()
    for (series_id, segment), points in groups.items():
        info = group_metadata[(series_id, segment)]
        identity = info["identity"]
        metadata = copy.deepcopy(info["record"])
        metadata.update(identity)
        metadata.update(series_id=series_id, segment=segment, source_rows=group_rows[(series_id, segment)],
                        x=copy.deepcopy(semantics["x"]), y=copy.deepcopy(semantics["y"]))
        metadata["preprocessing"] = copy.deepcopy(semantics["preprocessing"])
        for key in ("radiation", "sign_convention", "frequency", "na_content"):
            if key in semantics:
                metadata[key + "_declaration"] = copy.deepcopy(semantics[key])
        for field in ("frequency", "phase", "elements"):
            if info[field]:
                metadata[field] = info[field]
        explicit_id = series_id if segment is None else "%s__segment_%s" % (series_id, segment)
        if explicit_id in output_ids:
            report.error("rendered SeriesID collision: %s; rename the input IDs/segments" % explicit_id)
        output_ids.add(explicit_id)
        rows = group_rows[(series_id, segment)]
        series.append(NormalizedSeries(sample=identity["sample"], points=points,
                                       cycle=identity["cycle"], branch=identity["branch"],
                                       metric=semantics["y"]["quantity"], first_row=rows[0], last_row=rows[-1],
                                       explicit_id=explicit_id, metadata=metadata))
    report.raise_if_blocking("%s processed input IDs" % family)
    original_series = list(series)
    requested_samples = None
    if spec.samples:
        requested_samples = []
        for value in spec.samples:
            if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not value["name"].strip():
                report.error("processed spec.samples requires explicit non-empty name objects")
                continue
            name = value["name"].strip()
            if name in requested_samples:
                report.error("spec.samples contains duplicate sample %r" % name)
            requested_samples.append(name)
        missing = set(requested_samples) - set(sample_order)
        if missing:
            report.question("requested samples have no supplied series: %s" % ", ".join(sorted(missing)))
    criteria = {}
    for key, field in (("series_ids", "series_id"), ("cycles", "cycle"), ("branches", "branch")):
        if key not in (spec.selection or {}):
            continue
        requested = spec.selection[key]
        if not isinstance(requested, list) or not requested:
            report.error("selection.%s must be a non-empty explicit list" % key)
            continue
        if key == "cycles" and any(not isinstance(value, int) or isinstance(value, bool) for value in requested):
            report.error("selection.cycles must contain integral cycle numbers")
            continue
        if key != "cycles" and any(not isinstance(value, str) or not value for value in requested):
            report.error("selection.%s must contain non-empty strings" % key)
            continue
        if len(requested) != len(set(requested)):
            report.error("selection.%s contains duplicate requested values" % key)
        available = {item.metadata.get(field) for item in series}
        missing = set(requested) - available
        if missing:
            report.question("selection.%s requests values absent from supplied series: %s" %
                            (key, ", ".join(str(value) for value in sorted(missing))))
        criteria[field] = set(requested)
    report.raise_if_blocking("%s processed whole-series selection" % family)
    series = [item for item in series if (requested_samples is None or item.sample in requested_samples)
              and all(item.metadata.get(field) in values for field, values in criteria.items())]
    if not series:
        report.error("the requested sample/series/cycle/branch combination produces no complete series")
    actual_samples = {item.sample for item in series}
    sample_order = [sample for sample in (requested_samples if requested_samples is not None else sample_order)
                    if sample in actual_samples]
    if requested_samples is not None:
        order = {sample: index for index, sample in enumerate(sample_order)}
        series.sort(key=lambda item: order[item.sample])
    filtered_points = sum(len(item.points) for item in original_series) - sum(len(item.points) for item in series)
    report.counts.update(rows_selected=sum(len(item.points) for item in series), rows_excluded=filtered_points,
                         series=len(series), points=sum(len(item.points) for item in series))
    report.raise_if_blocking("%s processed selected series" % family)
    quantity_names = {"voltage": "Voltage",
                      "real_impedance": "Z'", "imaginary_impedance": "Z''",
                      "minus_imaginary_impedance": "-Z''", "time": "Time",
                      "sodium_content": "Na content", "diffusion_coefficient": "D",
                      "log10_diffusion_coefficient": "log10 D", "two_theta": "2theta",
                      "intensity": "Intensity",
                      "element_index": "Element", "element_ratio": "Element ratio",
                      "atomic_fraction": "Atomic fraction", "molar_fraction": "Molar fraction",
                      "mass_fraction": "Mass fraction", "concentration": "Concentration"}
    axis_labels = {}
    for key in ("x", "y"):
        axis = semantics[key]
        name = quantity_names.get(axis["quantity"], axis["quantity"])
        axis_labels[key] = axis.get("label") or (name if axis["unit"] == "1" else "%s (%s)" % (name, axis["unit"]))
    data = NormalizedData(plot_type=family, series=series, sample_order=sample_order,
                          axis_labels=axis_labels, excluded={"explicit whole-series selection": filtered_points} if filtered_points else {},
                          source={"file": spec.data.file, "sheet": sheet,
                          "header_row": header_row, "semantics": semantics, "rows_total": row_count,
                          "rows": sum(len(item.points) for item in series), "selection": copy.deepcopy(spec.selection),
                          "series": len(series), "points": sum(len(item.points) for item in series),
                          "element_ticks": [[value, label] for value, label in sorted(elements_by_x.items())
                                            if any(value == point[0] for item in series for point in item.points)]})
    data.source["scientific_traceability"] = traceability_summary(data)
    if data.source["scientific_traceability"]["status"] == "unknown":
        report.note("Scientific provenance contains declared gaps; supplied values are drawn as provided and scientific truth is not verified")
    return data
