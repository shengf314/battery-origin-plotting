"""Cycle Performance: shared cycle-summary input with two metrics per sample."""

from copy import deepcopy
from .. import cycle_summary

METRICS = (("discharge_capacity", "Discharge Specific Capacity"),
           ("coulombic_efficiency", "Coulombic Efficiency"))


def load(spec, workbook, report):
    data, _ = cycle_summary.load(spec, workbook, report, METRICS)
    unit = spec.data.semantics.get("ce_unit", "percent")
    if unit not in ("percent", "fraction"):
        report.error("data.semantics.ce_unit must be percent/fraction; no CE conversion is inferred")
        report.raise_if_blocking("CE unit")
    data.source["ce_unit"] = unit
    data.source["ce_unit_source"] = ("explicit data.semantics" if spec.data.semantics.get("ce_unit")
                                     else "legacy excel_cycle_summary contract: percent")
    report.note("CE stored values preserved; unit=%s, no multiplication or division" % unit)
    for series in data.series:
        series.metadata = {"source": data.source.get("file"), "sheet": data.source.get("sheet"),
                           "source_row_bounds": [series.first_row, series.last_row], "sample": series.sample,
                           "x": {"quantity": "cycle_number", "unit": "1"},
                           "y": ({"quantity": "coulombic_efficiency", "unit": "%" if unit == "percent" else "1"}
                                 if series.metric == "coulombic_efficiency" else
                                 {"quantity": "specific_capacity", "unit": "mAh g-1"})}
        if "instrument_import" in data.source:
            series.metadata["instrument_import"] = deepcopy(data.source["instrument_import"])
    return data
