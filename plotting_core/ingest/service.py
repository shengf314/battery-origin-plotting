"""Entry point of the input stage: spec + workbook -> normalised plotting data."""

from pathlib import Path
import hashlib
from typing import Tuple

from .. import registry
from ..config import SKILL_ROOT
from ..models import PlotSpec
from .normalize import NormalizedData
from .report import ValidationReport
from .xlsx import Workbook


def check_sheets(workbook: Workbook, spec: PlotSpec, report: ValidationReport) -> str:
    """Enforce the documented sheet policy; an explicit sheet needs no guessing."""
    names = workbook.sheet_names()
    report.source["sheets"] = names
    if not names:
        report.error("the workbook has no worksheets")
        report.raise_if_blocking("sheet check")
    requested = spec.data.sheet
    if requested:
        if requested not in names:
            report.error("worksheet %r was not found; available: %s"
                         % (requested, ", ".join(names)))
            report.raise_if_blocking("sheet check")
        others = [name for name in names if name != requested
                  and workbook.has_content(name)]
        if others:
            report.question("worksheet %r was requested, but %s also hold data; confirm "
                            "that only %r is used" % (requested, ", ".join(others), requested))
        report.note("worksheet %r used as requested in the plot spec" % requested)
        return requested
    if "Sheet1" not in names:
        report.question("worksheet Sheet1 was not found (available: %s); confirm which "
                        "sheet to read" % ", ".join(names))
        report.raise_if_blocking("sheet check")
    others = [name for name in names if name != "Sheet1" and workbook.has_content(name)]
    if others:
        report.question("worksheet Sheet1 has data and %s also hold content; confirm "
                        "which sheet to read" % ", ".join(others))
        report.raise_if_blocking("sheet check")
    if not workbook.has_content("Sheet1"):
        report.error("Sheet1 has no data to plot")
        report.raise_if_blocking("sheet check")
    return "Sheet1"


def load_normalized_data(spec: PlotSpec) -> Tuple[NormalizedData, ValidationReport]:
    """Read, validate and normalise the input workbook exactly once."""
    registry.validate_data_kind(spec.plot_type, spec.data.kind)
    report = ValidationReport()
    report.source["file"] = spec.data.file
    source = Path(resolve_data_file(spec.data.file)).resolve()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    report.source.update({"resolved_file": str(source), "sha256": before})
    with Workbook(str(source)) as workbook:
        sheet = check_sheets(workbook, spec, report)
        if not spec.data.sheet:
            spec.data.sheet = sheet
        data = registry.ingest_module(spec.plot_type).load(spec, workbook, report)
    report.source["sheet"] = spec.data.sheet
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    if before != after:
        report.error("source workbook changed while input was being read; rerun validation")
        report.raise_if_blocking("source freshness")
    data.source.update({"resolved_file": str(source), "sha256": before})
    return data, report


def resolve_data_file(path: str) -> str:
    """Absolute path of a source workbook, resolving a relative one sensibly.

    A relative ``data.file`` is interpreted against the current working directory
    first (the historical behaviour) and against the skill root second, so a spec
    that ships with the skill keeps working when the task runs from elsewhere.  The
    recorded value in the delivery documents stays exactly what the spec wrote.
    """
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return str(candidate)
    fallback = Path(SKILL_ROOT) / candidate
    if fallback.exists():
        return str(fallback)
    return str(candidate)
