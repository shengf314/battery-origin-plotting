"""gitt input route; scientific validation lives in the family-aware contract."""
from ...processed_xy.ingest import load as _load

def load(spec, workbook, report):
    return _load("gitt", spec, workbook, report)
