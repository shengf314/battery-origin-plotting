"""Explicit ICP result concentration -> element molar ratios, before plotting.

This independent API accepts declared result records, not instrument raw files.
It keeps the original input unchanged and records conversion/denominator choices.
"""

import copy
import math
import re
from collections import OrderedDict

from ...ingest.report import ValidationReport
from .formula_mass import atomic_weight, load_atomic_weights


_UNITS = {"g/L": ("mass", 1.0), "mg/L": ("mass", 1e-3),
          "ug/L": ("mass", 1e-6), "ng/L": ("mass", 1e-9),
          "mol/L": ("amount", 1.0), "mmol/L": ("amount", 1e-3),
          "umol/L": ("amount", 1e-6), "nmol/L": ("amount", 1e-9)}
_CENSORED = {"nd", "n.d.", "not detected", "<lod", "<loq", "lod", "loq",
             "bql", "bdl", "n/a", "na", "nan", "--", "-"}

def _question(report, context, message):
    report.question("%s: %s" % (context, message))


def _number(value, report, context, positive=False):
    if (value is None or isinstance(value, bool) or
            (isinstance(value, str) and (not value.strip() or
             value.strip().lower() in _CENSORED or value.strip().startswith(("<", ">", "≤", "≥"))))):
        _question(report, context, "missing/censored/non-numeric value requires clarification; ND/<LOD is not zero")
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        _question(report, context, "a finite numeric value is required")
        return None
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        _question(report, context, "a finite %s value is required" % ("positive" if positive else "non-negative"))
        return None
    return number


def _unit(value, report, context):
    if not isinstance(value, str) or not value.strip():
        _question(report, context, "explicit mass/volume or amount/volume concentration unit is required")
        return None
    unit = value.strip().replace("µ", "u").replace("μ", "u").replace(" ", "")
    if unit.endswith("/l"):
        unit = unit[:-1] + "L"
    if unit not in _UNITS:
        _question(report, context, "unsupported/ambiguous unit %r; ppm, ppb, percentages and mass fractions are not assumed to be mg/L" % value)
        return None
    return unit


def _symbol(value, element_map, table, report, context):
    if not isinstance(value, str) or not value.strip():
        _question(report, context, "an exact element symbol or explicitly mapped alias is required")
        return None
    token = value.strip()
    symbol = element_map.get(token, token)
    if not isinstance(symbol, str) or not symbol.strip():
        _question(report, context, "element alias %r has an ambiguous/non-string mapping" % token)
        return None
    symbol = symbol.strip()
    if token in table["elements"] and symbol != token:
        _question(report, context, "an existing exact element symbol cannot be remapped to a different element")
        return None
    if atomic_weight(symbol, report, context) is None:
        return None
    return symbol


def _records(raw_results, report):
    if isinstance(raw_results, (list, tuple)):
        return list(raw_results), {"format": "explicit_long_results"}
    if not isinstance(raw_results, dict):
        _question(report, "ICP input", "provide result records or an explicit standard-table mapping")
        return [], {}
    rows = raw_results.get("rows")
    columns = raw_results.get("column_map")
    if not isinstance(rows, (list, tuple)) or not isinstance(columns, dict):
        _question(report, "ICP standard table", "rows and explicit column_map are required; instrument raw parsing is not automatic")
        return [], {}
    for field in ("sample", "element", "concentration"):
        if not isinstance(columns.get(field), str) or not columns[field]:
            _question(report, "ICP standard table", "column_map.%s is required" % field)
    mapped = [value for value in columns.values() if isinstance(value, str)]
    if len(mapped) != len(columns):
        _question(report, "ICP standard table", "every declared column mapping must identify a header string")
    if len(mapped) != len(set(mapped)):
        _question(report, "ICP standard table", "different scientific fields cannot share one column identity")
    concentration_header = columns.get("concentration", "")
    match = re.search(r"(?:\(([^()]*)\)|\[([^\[\]]*)\])\s*$", concentration_header) if isinstance(concentration_header, str) else None
    header_unit = (match.group(1) or match.group(2)) if match else None
    if not header_unit and "unit" not in columns:
        _question(report, "ICP standard table", "concentration header must carry a unit, or unit must be explicitly mapped")
    normalized = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            _question(report, "ICP table row %d" % (index + 1), "each row must be a mapping")
            continue
        # Retain explicitly mapped qualifier/basis fields too; dropping them
        # would turn a censored or already-corrected concentration into raw data.
        result = {field: row.get(header) for field, header in columns.items() if isinstance(header, str)}
        if header_unit:
            if result.get("unit") is None:
                result["unit"] = header_unit
            else:
                row_unit = _unit(result["unit"], report, "ICP table row %d unit" % (index + 1))
                explicit_header = _unit(header_unit, report, "ICP concentration header unit")
                if row_unit != explicit_header:
                    _question(report, "ICP table row %d" % (index + 1), "row unit differs from concentration header; no automatic reinterpretation")
        result["source_record"] = copy.deepcopy(row)
        normalized.append(result)
    return normalized, {"format": "explicit_standard_long_table", "column_map": copy.deepcopy(columns),
                        "concentration_header_unit": header_unit}


def _denominator(value, element_map, table, report):
    if not isinstance(value, dict):
        _question(report, "ICP denominator", "declare type=element with element, or type=sum with the exact selected elements")
        return None
    mode = value.get("type")
    allowed = {"type", "element"} if mode == "element" else {"type", "elements"}
    extra = sorted(str(key) for key in value if key not in allowed)
    if extra:
        _question(report, "ICP denominator", "unsupported denominator options %s; normalization/mass basis is not guessed" % ", ".join(extra))
    if mode == "element":
        symbol = _symbol(value.get("element"), element_map, table, report, "ICP denominator.element")
        return {"type": mode, "elements": [symbol], "normalization": 1.0} if symbol else None
    if mode == "sum":
        selected = value.get("elements")
        if not isinstance(selected, (list, tuple)) or not selected:
            _question(report, "ICP denominator", "sum requires a nonempty explicit list of elements")
            return None
        symbols = [_symbol(item, element_map, table, report, "ICP denominator.elements") for item in selected]
        if len(set(symbols)) != len(symbols):
            _question(report, "ICP denominator", "sum elements must be distinct after explicit alias mapping")
        return {"type": mode, "elements": symbols, "normalization": 1.0} if all(symbols) else None
    _question(report, "ICP denominator", "type must be element or sum; no formula or oxygen/sodium completion is inferred")
    return None


def _replicate_summaries(ratios, design, report):
    if design is None:
        return []
    if (not isinstance(design, dict) or design.get("kind") != "independent_preparations" or
            not isinstance(design.get("source"), str) or not design["source"].strip() or
            design.get("method") not in ("sample_sd", "standard_error")):
        _question(report, "ICP replicate design", "uncertainty requires declared independent_preparations, a source, and sample_sd or standard_error method; repeated instrument readings alone are insufficient")
        return []
    by_sample = OrderedDict()
    for row in ratios:
        by_sample.setdefault(row["sample"], OrderedDict()).setdefault(row["replicate"], {})[row["element"]] = row["value"]
    summaries = []
    for sample, replicates in by_sample.items():
        if None in replicates or len(replicates) < 2:
            _question(report, "ICP sample %s" % sample, "at least two actual distinct independent replicate identities are needed for an error statistic")
            continue
        sets = [set(values) for values in replicates.values()]
        if any(elements != sets[0] for elements in sets[1:]):
            _question(report, "ICP sample %s" % sample, "independent replicates must contain the same element set; no missing result is imputed")
            continue
        for element in next(iter(replicates.values())):
            values = [items[element] for items in replicates.values()]
            try:
                mean = math.fsum(value / len(values) for value in values)
                delta = [value - mean for value in values]
                scale = max(abs(value) for value in delta)
                sd = (scale * math.sqrt(math.fsum((value / scale) ** 2 for value in delta) /
                      (len(values) - 1))) if scale else 0.0
                if not math.isfinite(mean) or not math.isfinite(sd):
                    raise ValueError("non-finite replicate statistic")
            except (ValueError, OverflowError):
                _question(report, "ICP sample %s element %s" % (sample, element), "replicate statistic overflowed; no uncertainty is produced")
                continue
            summaries.append({"sample": sample, "element": element, "value": mean,
                              "error": sd if design["method"] == "sample_sd" else sd / math.sqrt(len(values)),
                              "error_kind": design["method"], "n": len(values),
                              "replicates": list(replicates), "quantity": "element_ratio", "unit": "1",
                              "method": "ratio per independent preparation, then arithmetic mean and sample SD (n-1)"})
    return summaries


def calculate_icp_ratios(raw_results, denominator=None, *, element_map=None,
                         replicate_design=None, source=None, report=None):
    """Return auditable element molar ratios from explicitly declared ICP results.

    Records contain sample, exact element, concentration and unit; optional
    dilution_factor is the total multiplier from measured solution to its common
    sample basis. All missing factors may cancel as one common unknown factor.
    Mixed known/missing factors or different aliquots require clarification.
    ``denominator`` is {type: element, element: Ni} or {type: sum, elements: [...]}.
    Errors/questions are aggregated; blocked calls return no ratio/summary values.
    """
    if report is None:
        report = ValidationReport()
    table = load_atomic_weights()
    metadata = {key: copy.deepcopy(value) for key, value in table.items() if key != "elements"}
    if element_map is None:
        element_map = {}
    if not isinstance(element_map, dict):
        _question(report, "ICP element_map", "an explicit alias-to-exact-symbol mapping is required")
        element_map = {}
    records, table_mapping = _records(raw_results, report)
    basis = _denominator(denominator, element_map, table, report)
    if not records:
        _question(report, "ICP input", "no result records were provided")
    normalized = []
    seen = set()
    groups = OrderedDict()
    for index, raw in enumerate(records):
        context = "ICP row %d" % (index + 1)
        if not isinstance(raw, dict):
            _question(report, context, "each result must be a mapping")
            continue
        sample = raw.get("sample")
        if not isinstance(sample, str) or not sample.strip():
            _question(report, context, "a nonempty explicit sample identity is required")
            sample = None
        else:
            sample = sample.strip()
        replicate = raw.get("replicate")
        if replicate is not None:
            if isinstance(replicate, bool) or not isinstance(replicate, (str, int)) or not str(replicate).strip():
                _question(report, context, "replicate identity must be an explicit nonempty string/integer")
                replicate = None
            else:
                replicate = str(replicate).strip()
        element = _symbol(raw.get("element"), element_map, table, report, context + " element")
        concentration = _number(raw.get("concentration"), report, context + " concentration")
        unit = _unit(raw.get("unit"), report, context + " unit")
        qualifier = raw.get("qualifier")
        if qualifier is not None and str(qualifier).strip().lower() not in ("", "ok", "detected", "quantified"):
            _question(report, context, "qualifier %r requires interpretation; a censored result is not a quantified concentration" % qualifier)
        if raw.get("below_lod") or raw.get("below_loq") or raw.get("not_detected"):
            _question(report, context, "below detection/quantification limit or ND flags cannot be treated as exact zero")
        if raw.get("blank_correction") or raw.get("subtract_blank"):
            _question(report, context, "automatic blank subtraction is not supported; supply an explicitly resolved result and provenance")
        if raw.get("already_dilution_corrected") or raw.get("dilution_applied"):
            _question(report, context, "already corrected concentrations require an explicit measured-solution basis; dilution is not applied twice")
        for field in ("analyte_basis", "mass_basis"):
            if field in raw and raw[field] not in ("element", "elemental", element):
                _question(report, context, "%s must identify elemental concentration; compound/oxide concentration is not converted with an element's molar mass" % field)
        if any(raw.get(field) is not None for field in ("sd", "se", "sem", "error", "uncertainty", "stddev")):
            _question(report, context, "supplied uncertainty fields require method clarification; this API only computes declared statistics from actual independent preparation records")
        dilution = None if raw.get("dilution_factor") is None else _number(
            raw["dilution_factor"], report, context + " dilution_factor", positive=True)
        aliquot = raw.get("aliquot")
        if aliquot is not None and not isinstance(aliquot, (str, int)):
            _question(report, context, "aliquot identity must be a string/integer")
            aliquot = None
        identity = (sample, replicate, element)
        if identity in seen:
            report.duplicates.append({"row": index + 1, "sample": sample, "replicate": replicate, "element": element})
            _question(report, context, "duplicate sample/replicate/element identity; results are not silently averaged")
        seen.add(identity)
        if sample is None or element is None or concentration is None or unit is None:
            continue
        kind, factor = _UNITS[unit]
        mass = table["elements"][element]["atomic_weight"]
        molar = concentration * factor / mass if kind == "mass" else concentration * factor
        if not math.isfinite(molar) or (concentration > 0 and molar == 0):
            _question(report, context, "unit conversion overflowed/underflowed; no rounded zero is substituted")
            continue
        row = {"row_index": index + 1, "sample": sample, "replicate": replicate,
               "element": element, "input_element": raw.get("element"),
               "concentration": concentration, "input_unit": raw.get("unit"), "unit": unit,
               "molar_concentration_mol_L": molar, "dilution_factor": dilution, "aliquot": aliquot,
               "conversion": {"kind": kind, "unit_multiplier": factor,
                              "molar_mass_g_mol": mass if kind == "mass" else None,
                              "equation": "c_mol_L = c * unit_multiplier / M_g_mol" if kind == "mass" else
                                          "c_mol_L = c * unit_multiplier"}}
        normalized.append(row)
        groups.setdefault((sample, replicate), []).append(row)
    dilution_audit = []
    ratios = []
    for (sample, replicate), rows in groups.items():
        context = "ICP sample %s replicate %s" % (sample, replicate)
        factors = [row["dilution_factor"] for row in rows]
        specified = [factor for factor in factors if factor is not None]
        aliquots = {str(row["aliquot"]) for row in rows if row["aliquot"] is not None}
        if specified and len(specified) != len(factors):
            _question(report, context, "dilution factors are only partially specified; different factors cannot be inferred or cancelled")
        if len(aliquots) > 1:
            _question(report, context, "different aliquots need a common sample-equivalent basis/volume; dilution factors alone do not establish comparable amounts")
        elif aliquots and any(row["aliquot"] is None for row in rows):
            _question(report, context, "aliquot identity is only partially specified; a common solution basis is not inferred")
        common = len(set(specified)) == 1 and len(specified) == len(factors)
        dilution_audit.append({"sample": sample, "replicate": replicate,
                               "mode": "common_explicit_factor_cancels" if common else
                                       "common_unspecified_factor_cancels" if not specified else "explicit_per_element_factors",
                               "factors": factors})
        by_element = {}
        for row in rows:
            effective = row["molar_concentration_mol_L"] * (row["dilution_factor"] if row["dilution_factor"] is not None else 1.0)
            if not math.isfinite(effective) or (row["molar_concentration_mol_L"] > 0 and effective == 0):
                _question(report, context, "dilution correction overflowed/underflowed; no rounded zero is substituted")
            row["ratio_effective_molar_concentration_mol_L"] = effective
            by_element[row["element"]] = effective
        if basis is None:
            continue
        absent = [element for element in basis["elements"] if element not in by_element]
        if absent:
            _question(report, context, "denominator elements are missing: %s; no element is imputed" % ", ".join(absent))
            continue
        try:
            divisor = math.fsum(by_element[element] for element in basis["elements"])
        except (ValueError, OverflowError):
            divisor = float("inf")
        if not math.isfinite(divisor) or divisor <= 0:
            _question(report, context, "the declared denominator must have a finite positive measured molar amount/concentration")
            continue
        for row in rows:
            ratio = row["ratio_effective_molar_concentration_mol_L"] / divisor
            if not math.isfinite(ratio):
                _question(report, context, "molar ratio is non-finite")
            ratios.append({"sample": sample, "replicate": replicate, "element": row["element"],
                           "value": ratio, "quantity": "element_ratio", "unit": "1",
                           "denominator": copy.deepcopy(basis), "denominator_mol_L": divisor,
                           "within_denominator_set": row["element"] in basis["elements"],
                           "source_row": row["row_index"]})
    summaries = _replicate_summaries(ratios, replicate_design, report)
    report.counts.update({"icp_input_records": len(records), "icp_normalized_records": len(normalized),
                          "icp_sample_replicate_groups": len(groups)})
    ready = not report.blocking and bool(ratios)
    return {"ready": ready, "normalized_results": normalized,
            "ratios": ratios if ready else [], "replicate_summary": summaries if ready else [],
            "scientific_truth_verified": False,
            "provenance": {"operation": "explicit_element_concentration_to_molar_ratio",
                           "source": copy.deepcopy(source), "original_input": copy.deepcopy(raw_results),
                           "table_mapping": table_mapping, "element_map": copy.deepcopy(element_map),
                           "atomic_weight_table": metadata, "denominator": copy.deepcopy(denominator),
                           "dilution": dilution_audit, "replicate_design": copy.deepcopy(replicate_design),
                           "blank_subtraction": "not performed", "missing_element_completion": "not performed",
                           "interpretation": "ratios among explicitly supplied quantified elements; not a complete chemical formula or proof of analytical accuracy"},
            "report": report.to_dict()}


__all__ = ["calculate_icp_ratios"]
