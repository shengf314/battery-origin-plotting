"""Header semantics, branch enumeration and value validation of the input contract."""

import math
import re
import unicodedata
from typing import Dict, List, Optional

from ...ingest.report import ValidationReport

CANONICAL_FIELDS = (
    "Sample",
    "Cycle",
    "Rate",
    "Branch",
    "Voltage",
    "Charge Specific Capacity",
    "Discharge Specific Capacity",
    "Charge Na Content",
    "Discharge Na Content",
    "Coulombic Efficiency",
)

ALIASES: Dict[str, List[str]] = {
    "Rate": ["rate", "c-rate", "c rate", "倍率"],
    "Sample": ["sample", "sample name", "sample id", "样品", "样品名", "样品编号"],
    "Cycle": ["cycle", "cycle number", "cycle no", "cycleno", "循环", "循环圈数",
              "循环号", "循环序号", "圈数"],
    "Branch": ["branch", "branch type", "step type", "充放电分支", "工步类型", "工步", "分支"],
    "Voltage": ["voltage", "电压"],
    "Charge Specific Capacity": ["charge specific capacity", "charge capacity",
                                 "充电比容量", "充电容量"],
    "Discharge Specific Capacity": ["discharge specific capacity", "discharge capacity",
                                    "放电比容量", "放电容量"],
    "Charge Na Content": ["charge na content", "充电钠含量"],
    "Discharge Na Content": ["discharge na content", "放电钠含量"],
    "Coulombic Efficiency": ["coulombic efficiency", "库仑效率", "库伦效率", "ce"],
}

BRANCH_ALIASES: Dict[str, List[str]] = {
    "charge": ["charge", "chg", "充电"],
    "discharge": ["discharge", "dchg", "dischg", "放电"],
}

_UNIT_PATTERN = re.compile(
    r"(?:\(|\[|（|【)?\s*(?:/|·|\*|,|\s)?\s*"
    r"(?:mah\s*/?\s*g[−\-]?1|mah/g|mah\s*g-1|na\s*/?\s*fu|%|v|mv|x)"
    r"\s*(?:\)|\]|）|】)?\s*$",
    re.IGNORECASE)


def normalize_header(text) -> str:
    """Normalise a header cell: case, spacing, unicode form and unit suffixes."""
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text)).strip().lower()
    value = re.sub(r"\s+", "", value)
    value = value.replace("（", "(").replace("）", ")")
    value = _UNIT_PATTERN.sub("", value)
    value = re.sub(r"(?<=[a-z])/[a-z]+$", "", value)
    return value.strip("()[]·.,;: ")


def _alias_index() -> Dict[str, str]:
    index = {}
    for field, names in ALIASES.items():
        index[normalize_header(field)] = field
        for name in names:
            index[normalize_header(name)] = field
    return index


ALIAS_INDEX = _alias_index()


def map_headers(header: Dict[str, str], field_map: Dict[str, str],
                report: ValidationReport) -> Dict[str, str]:
    """Map canonical fields to column letters.

    ``field_map`` carries explicitly approved mappings (raw header text -> canonical
    field); anything outside the alias table is recorded as an applied mapping so the
    interpretation stays visible in the deliverables.
    """
    approved = {normalize_header(key): value for key, value in (field_map or {}).items()}
    mapping: Dict[str, str] = {}
    for letter, raw in sorted(header.items()):
        key = normalize_header(raw)
        canonical = approved.get(key)
        if canonical is None:
            canonical = ALIAS_INDEX.get(key)
        if canonical is None:
            continue
        if canonical not in CANONICAL_FIELDS:
            report.error("approved mapping for header %r targets unknown field %r"
                         % (raw, canonical))
            continue
        if canonical in mapping:
            report.error("columns %s and %s both map to %s (%r, %r); check the header row"
                         % (mapping[canonical], letter, canonical,
                            header[mapping[canonical]], raw))
            continue
        mapping[canonical] = letter
        if key not in ALIAS_INDEX:
            report.record_mapping("%s -> %s (approved field_map)" % (raw, canonical))
    return mapping


def validate_legacy_units(header, mapping, report, ce_unit="percent"):
    """Reject explicit units contradicting the legacy contract; never convert."""
    for field, letter in mapping.items():
        raw = unicodedata.normalize("NFKC", str(header.get(letter, ""))).lower()
        raw = raw.replace("−", "-").replace("⁻", "-")
        if field == "Voltage" and re.search(r"mv\s*[)\]]?\s*$", raw):
            report.error("Voltage header declares mV but legacy GCD expects V; provide standard V data without automatic conversion")
        if "Specific Capacity" in field:
            declared = re.search(r"(?:\(|\[)([^)\]]+)(?:\)|\])\s*$", raw)
            if declared:
                unit = re.sub(r"\s+", "", declared.group(1))
                if unit not in ("mah/g", "mahg-1", "mahg^-1"):
                    report.error("%s header unit %r contradicts mAh g-1" % (field, declared.group(1)))
        if field == "Coulombic Efficiency":
            if "%" in raw and ce_unit != "percent":
                report.error("CE header declares percent but data.semantics.ce_unit is fraction")
            if re.search(r"(?:\(|\[)(?:fraction|decimal|1)(?:\)|\])\s*$", raw) and ce_unit != "fraction":
                report.error("CE header declares a fraction; explicitly declare ce_unit=fraction")


def require_fields(mapping: Dict[str, str], required: List[str],
                   report: ValidationReport) -> None:
    for field in required:
        if field not in mapping:
            report.question("required column %r was not found in the header row; "
                            "confirm the mapping" % field)


def normalize_cycle(cell, report: ValidationReport, row: int) -> Optional[int]:
    """Accept finite integral numbers only; never renumber or interpolate."""
    if cell is None or cell.is_empty:
        report.question("Cycle is empty at row %d; confirm the value" % row)
        return None
    if cell.value is None:
        report.question("Cycle at row %d holds %r, which cannot be parsed as an integer"
                        % (row, cell.text))
        return None
    number = cell.value
    if not math.isfinite(number) or number != int(number):
        report.question("Cycle at row %d is %r, which is not an integer" % (row, number))
        return None
    return int(number)


def normalize_branch(cell, value_map: Dict[str, str], report: ValidationReport,
                     row: int) -> Optional[str]:
    """Only documented aliases or explicitly approved values are accepted."""
    if cell is None or cell.is_empty:
        report.question("Branch is empty at row %d; confirm the value" % row)
        return None
    raw = (cell.text if cell.text is not None else str(cell.value)).strip()
    key = normalize_header(raw)
    local = {normalize_header(k): v for k, v in (value_map or {}).items()}
    if key in local:
        canonical = local[key]
        if canonical not in BRANCH_ALIASES:
            report.question("approved branch mapping %r -> %r is not charge/discharge"
                            % (raw, canonical))
            return None
        report.record_mapping(
            "Branch value %r -> %s (approved value_map)" % (raw, canonical))
        return canonical
    for canonical, names in BRANCH_ALIASES.items():
        if key in {normalize_header(name) for name in names}:
            return canonical
    report.question("Branch value %r at row %d is not a recognised charge/discharge "
                    "value; confirm its meaning" % (raw, row))
    return None


def excluded_value_matches(cell, exclude_values: List[str]) -> bool:
    if cell is None:
        return False
    raw = cell.text if cell.text is not None else cell.value
    if raw is None:
        return False
    key = normalize_header(str(raw))
    return any(key == normalize_header(candidate) for candidate in (exclude_values or []))


def numeric_value(cell, field: str, report: ValidationReport, row: int,
                  context: str = "") -> Optional[float]:
    """Validate one plotting number; text is never coerced into a number."""
    if cell is None or cell.is_empty:
        report.question("%s is blank at row %d%s; confirm whether to skip this point"
                        % (field, row, context))
        return None
    if cell.formula and not cell.cached:
        report.question("%s at row %d is a formula without a cached result; provide a "
                        "saved workbook with values" % (field, row))
        return None
    if cell.value is None:
        report.question("%s at row %d holds %r, which is not a number"
                        % (field, row, cell.text))
        return None
    number = cell.value
    if not math.isfinite(number):
        report.question("%s at row %d is %r, which is not a finite number"
                        % (field, row, number))
        return None
    return number
