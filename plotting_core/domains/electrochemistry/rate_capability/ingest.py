"""Rate field normalisation on the shared excel_cycle_summary contract."""

import re
from fractions import Fraction

from .. import cycle_summary

METRICS = (("discharge_capacity", "Discharge Specific Capacity"),)
_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_MULTIPLE = re.compile(r"^(" + _NUMBER + r")\s*C$", re.I)
_RECIPROCAL = re.compile(r"^C\s*/\s*(" + _NUMBER + r")$", re.I)


def normalize_rate(cell, report, row, column="Rate"):
    """Exact positive rational canonical value plus a deterministic display label.

    Bare numbers have no unit and are rejected. No text-to-rate mapping, numeric
    cleaning or tolerance-based equivalence is performed.
    """
    raw = (cell.text if cell.text is not None else cell.value) if cell else None
    text = str(raw).strip() if raw is not None else ""
    multiple, reciprocal = _MULTIPLE.fullmatch(text), _RECIPROCAL.fullmatch(text)
    reason = None
    if cell and cell.formula and not cell.cached:
        reason = "formula has no cached Rate value; save calculated values first"
    elif not (multiple or reciprocal):
        reason = "expected an explicit positive C-rate such as 0.1 C or C/10"
    else:
        number = Fraction((multiple or reciprocal).group(1))
        if number <= 0:
            reason = "C-rate and reciprocal denominator must be positive"
    if reason:
        report.question("Rate column %s row %d raw value %r: %s" % (column, row, raw, reason))
        return None
    value = number if multiple else 1 / number
    # Decimal expansion is exact when the denominator has only factors 2 and 5.
    denominator, twos, fives = value.denominator, 0, 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator == 1:
        places = max(twos, fives)
        digits = str(value.numerator * 2 ** (places - twos) * 5 ** (places - fives))
        if places:
            digits = digits.zfill(places + 1)
            digits = (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")
        label = digits + " C"
    else:
        label = ("C/%d" % value.denominator if value.numerator == 1 else
                 "%d/%d C" % (value.numerator, value.denominator))
    return {"canonical": "%d/%d" % (value.numerator, value.denominator), "label": label}


def load(spec, workbook, report):
    data, records = cycle_summary.load(spec, workbook, report, METRICS,
                                       extra_parsers={"Rate": normalize_rate}, sort_cycles=True)
    data.source["rate_rows"] = {
        sample: [dict(cycle=row["cycle"], rate=row["extra"]["Rate"], row=row["row"])
                 for row in rows] for sample, rows in records.items()}
    return data
