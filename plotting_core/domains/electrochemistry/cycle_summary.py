"""Shared cycle-summary contract: headers, Sample, Cycle, numbers and uniqueness.

Families supply metrics and optional field parsers. Extra domain values and row
provenance stay in records alongside the normalised XY series; no workbook writes.
"""

from collections import OrderedDict
import math
from pathlib import Path

from ...ingest.normalize import NormalizedData, NormalizedSeries
from . import naming, schema


def _requested_cycles(selection, report):
    rule = selection.get("cycles") or {}
    mode = rule.get("mode", "all")
    if mode == "all":
        return None
    values = ([rule.get("from"), rule.get("to")] if mode == "range" else
              [rule.get("cycle")] if mode == "single" and "cycle" in rule else
              rule.get("cycles", []))
    if mode not in ("single", "selected", "range") or not values:
        report.question("selection.cycles must declare all/single/selected/range and values")
        report.raise_if_blocking()
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) or v != int(v) for v in values):
        report.question("selection.cycles must contain finite integer values")
        report.raise_if_blocking()
    values = [int(v) for v in values]
    if mode == "range":
        if values[0] > values[1]:
            report.question("selection.cycles.from must not exceed to")
            report.raise_if_blocking()
        return set(range(values[0], values[1] + 1))
    if mode == "single" and len(values) != 1:
        report.question("selection.cycles.single requires exactly one cycle")
        report.raise_if_blocking()
    return set(values)


def load(spec, workbook, report, metrics, extra_parsers=None, sort_cycles=False):
    """Return (NormalizedData, records_by_sample) using one input contract."""
    extra_parsers = extra_parsers or {}
    source = spec.data
    sheet = source.sheet or "Sheet1"
    header_row = int(spec.selection.get("header_row", 1))
    header = workbook.header(sheet, header_row)
    mapping = schema.map_headers(header, source.field_map, report)
    schema.validate_legacy_units(header, mapping, report, source.semantics.get("ce_unit", "percent"))
    report.header_map = mapping
    required = ["Cycle"] + [field for _, field in metrics] + list(extra_parsers)
    if source.sample_column:
        required.append("Sample")
    schema.require_fields(mapping, required, report)
    report.counts["required_columns"] = required
    report.raise_if_blocking("Cycle summary input validation")
    wanted_cycles = _requested_cycles(spec.selection, report)
    requested_samples = [item.get("name") for item in spec.samples]
    if any(not isinstance(name, str) or not name.strip() for name in requested_samples):
        report.question("every requested Sample needs an explicit non-empty name")
        report.raise_if_blocking()
    if any(item.get("cycles") for item in spec.samples):
        report.question("cycle-summary selection uses selection.cycles, not per-sample cycles")
        report.raise_if_blocking()

    # First inspect Sample for the whole table, before selection can hide blanks.
    populated, blank_rows = [], []
    if "Sample" in mapping:
        for row, cells in workbook.rows(sheet, start_row=header_row + 1):
            if all(cell.is_empty and not cell.formula for cell in cells.values()):
                continue
            cell = cells.get(mapping["Sample"])
            raw = (cell.text if cell.text is not None else cell.value) if cell else None
            if raw is None or not str(raw).strip():
                blank_rows.append(row)
            else:
                populated.append(str(raw).strip())
        if populated and blank_rows:
            report.question("Sample is partially empty at rows %s; do not fill missing names"
                            % blank_rows[:15])
    report.raise_if_blocking("Cycle summary Sample validation")
    single_name = None
    if not populated:
        if len(requested_samples) > 1:
            report.question("multiple Samples requested but no populated Sample column exists")
        elif "Sample" in mapping and not requested_samples:
            report.question("Sample column is all empty; provide the single sample display name")
        else:
            single_name = naming.display_name(
                requested_samples[0] if requested_samples else None, report,
                filename=Path(source.file).name, single_sample=True)
    report.raise_if_blocking("Cycle summary Sample validation")

    records = OrderedDict()
    selected_samples_seen = []
    seen_cycles, duplicates = {}, []
    rows_read, excluded = 0, 0
    for row, cells in workbook.rows(sheet, start_row=header_row + 1):
        if all(cell.is_empty and not cell.formula for cell in cells.values()):
            continue
        cycle_cell = cells.get(mapping["Cycle"])
        if schema.excluded_value_matches(cycle_cell, source.exclude_values.get("Cycle", [])):
            excluded += 1
            continue
        rows_read += 1
        cycle = schema.normalize_cycle(cycle_cell, report, row)
        if cycle is None:
            continue
        if populated:
            cell = cells[mapping["Sample"]]
            sample = str(cell.text if cell.text is not None else cell.value).strip()
        else:
            sample = single_name
        # Structure is checked before selection; never infer a rate from cycles.
        extras = {field: parser(cells.get(mapping[field]), report, row, mapping[field])
                  for field, parser in extra_parsers.items()}
        if requested_samples and sample not in requested_samples:
            continue
        if sample not in selected_samples_seen:
            selected_samples_seen.append(sample)
        if wanted_cycles is not None and cycle not in wanted_cycles:
            continue
        key = (sample, cycle)
        if key in seen_cycles and len(duplicates) < 15:
            duplicates.append({"sample": sample, "cycle": cycle, "row": row,
                               "first_row": seen_cycles[key]})
        seen_cycles.setdefault(key, row)
        values = {metric: schema.numeric_value(cells.get(mapping[field]), field, report,
                                              row, " (%s / cycle %d)" % (sample, cycle))
                  for metric, field in metrics}
        if any(value is None for value in list(values.values()) + list(extras.values())):
            continue
        records.setdefault(sample, []).append(dict(cycle=cycle, values=values,
                                                   extra=extras, row=row))
    if duplicates:
        report.duplicates = duplicates
        report.question("%d sample/cycle combination(s) appear more than once; "
                        "one record per Sample/Cycle is required; no merging or averaging"
                        % len(duplicates))
    if excluded:
        report.counts["rows_excluded"] = excluded
    report.counts["rows_read"] = rows_read
    for sample in requested_samples:
        if sample not in records:
            report.question("requested Sample %r has no data" % sample)
    if wanted_cycles is not None:
        for sample in selected_samples_seen:
            rows = records.get(sample, [])
            missing = sorted(wanted_cycles - {row["cycle"] for row in rows})
            if missing:
                report.question("Sample %r is missing requested Cycle values %s" % (sample, missing))
    if not records:
        report.question("no complete cycle-summary rows to plot")
    report.raise_if_blocking("Cycle summary input validation")
    if requested_samples:
        records = OrderedDict((sample, records[sample]) for sample in requested_samples)
    if sort_cycles:
        for rows in records.values():
            rows.sort(key=lambda row: row["cycle"])

    series = []
    for sample, rows in records.items():
        for metric, field in metrics:
            series.append(NormalizedSeries(
                sample=sample, metric=metric,
                points=[(float(row["cycle"]), float(row["values"][metric])) for row in rows],
                first_row=rows[0]["row"], last_row=rows[-1]["row"]))
    samples = list(records)
    data = NormalizedData(
        plot_type=spec.plot_type, series=series, sample_order=samples,
        excluded={"excluded rows (Cycle in exclude_values)": excluded} if excluded else {},
        source={"file": source.file, "sheet": sheet, "header_row": header_row,
                "rows": rows_read, "samples": samples,
                "cycles_per_sample": {sample: len(rows) for sample, rows in records.items()},
                "series": len(series), "points": sum(len(item.points) for item in series)})
    return data, records
