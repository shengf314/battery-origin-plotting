"""Explicit, separately reviewed capacity -> Na stoichiometric-equivalent conversion.

No renderer imports this module. It reads supplied in-memory point records only,
never guesses composition, mass normalization, direction, reference, or cycles.
"""

import copy
import hashlib
import json
import math

from ....ingest.report import ValidationReport
from ...chemistry.formula_mass import calculate_formula_mass

AVOGADRO_CONSTANT_MOL_1 = 6.02214076e23
ELEMENTARY_CHARGE_C = 1.602176634e-19
FARADAY_CONSTANT_C_MOL = AVOGADRO_CONSTANT_MOL_1 * ELEMENTARY_CHARGE_C
CONSTANT_SOURCE = "https://physics.nist.gov/cuu/Constants/Table/allascii.txt"
CHEMISTRY_SOURCE = "https://doi.org/10.1016/j.isci.2018.07.020"
METHOD = "faraday_stoichiometry"


def _object(value, report, path):
    if not isinstance(value, dict):
        report.question("%s must be an explicit object" % path)
        return {}
    return value


def _text(mapping, key, report, path):
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip() or value.strip().lower() == "unknown":
        report.question("%s.%s requires a known non-empty declaration; it is not inferred" % (path, key))
        return None
    return value


def _number(mapping, key, report, path, positive=False):
    value = mapping.get(key)
    valid = not isinstance(value, bool) and isinstance(value, (int, float))
    try:
        valid = valid and math.isfinite(value) and (not positive or value > 0)
    except (OverflowError, TypeError, ValueError):
        valid = False
    if not valid:
        report.question("%s.%s must be a finite %snumber, excluding bool" % (path, key, "positive " if positive else ""))
        return None
    return value


def _enum(mapping, key, allowed, report, path):
    value = mapping.get(key)
    if not isinstance(value, str) or value not in allowed:
        report.question("%s.%s must explicitly be one of %s" % (path, key, ", ".join(allowed)))
        return None
    return value


def _digest(value, report, path):
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        report.question("%s must contain JSON-safe supplied records with finite numeric values" % path)
        return None
    return hashlib.sha256(encoded).hexdigest()


def validate_na_conversion(point_data, declaration, report=None):
    """Dry validation only: return readiness, input hashes, declarations and report.

    Missing scientific decisions are aggregated in ValidationReport.questions.
    A shared report is optional; this function does not raise or compute Na values.
    One call describes one explicitly identified series and one signed reference.
    """
    if report is None:
        report = ValidationReport()
    declared = copy.deepcopy(_object(declaration, report, "declaration"))
    _enum(declared, "method", (METHOD,), report, "declaration")
    output = _enum(declared, "output", ("delta_x", "absolute_x"), report, "declaration")
    series_id = _text(declared, "series_id", report, "declaration")
    _text(declared, "source", report, "declaration")
    _enum(declared, "capacity_unit", ("mAh g-1",), report, "declaration")
    _enum(declared, "voltage_unit", ("V",), report, "declaration")
    normalization = _object(declared.get("mass_normalization"), report, "mass_normalization")
    basis = _enum(normalization, "basis", ("active_material", "electrode_composite"), report, "mass_normalization")
    _text(normalization, "source", report, "mass_normalization")
    if "active_fraction" in normalization or basis == "electrode_composite":
        fraction = _object(normalization.get("active_fraction"), report, "mass_normalization.active_fraction")
        value = _number(fraction, "value", report, "mass_normalization.active_fraction", positive=True)
        if value is not None and value > 1:
            report.question("active_fraction.value is a mass fraction and must be <= 1")
        _enum(fraction, "basis", ("active_material_mass/electrode_composite_mass",), report, "mass_normalization.active_fraction")
        _text(fraction, "source", report, "mass_normalization.active_fraction")
    material = _object(declared.get("material"), report, "material")
    for key in ("formula", "formula_source", "formula_unit_basis"):
        _text(material, key, report, "material")
    mass_method = material.get("molar_mass_method")
    if mass_method is not None:
        _enum(material, "molar_mass_method", ("ciaaw2024_formula", "supplied"), report, "material")
    if "molar_mass_g_mol" not in material or mass_method == "ciaaw2024_formula":
        computed_mass = calculate_formula_mass(material.get("formula"), report, "material.formula")
        if computed_mass["ready"]:
            supplied = material.get("molar_mass_g_mol")
            if supplied is not None:
                supplied = _number(material, "molar_mass_g_mol", report, "material", positive=True)
                if supplied is not None and not math.isclose(supplied, computed_mass["molar_mass_g_mol"], rel_tol=1e-10, abs_tol=1e-10):
                    report.question("material supplied molar mass conflicts with the explicitly requested CIAAW formula calculation; resolve the material/formula basis")
            material["molar_mass_g_mol"] = computed_mass["molar_mass_g_mol"]
            material["molar_mass_source"] = computed_mass["table"]["source"]
            material["molar_mass_method"] = "ciaaw2024_formula"
            material["formula_mass_record"] = {key: copy.deepcopy(value) for key, value in computed_mass.items() if key != "report"}
    else:
        _text(material, "molar_mass_source", report, "material")
    _number(material, "molar_mass_g_mol", report, "material", positive=True)
    assumptions = _object(declared.get("assumptions"), report, "assumptions")
    _enum(assumptions, "reaction", ("stoichiometric_na_intercalation",), report, "assumptions")
    n = _number(assumptions, "electrons_per_na", report, "assumptions", positive=True)
    if n is not None and n != 1:
        report.question("this method accepts electrons_per_na=1 only, for the explicitly supplied Na intercalation assumption")
    _text(assumptions, "source", report, "assumptions")
    parasitic = _enum(assumptions, "parasitic_charge", ("unknown", "assumed_negligible", "externally_corrected"), report, "assumptions")
    if parasitic in ("assumed_negligible", "externally_corrected"):
        _text(assumptions, "parasitic_charge_source", report, "assumptions")
    elif parasitic == "unknown":
        report.warn("Parasitic charge is unknown; converted Na values are capacity equivalents under the supplied one-electron assumption, not verified composition")
    relation = _object(declared.get("relation"), report, "relation")
    direction = _number(relation, "direction_sign", report, "relation")
    if direction is not None and direction not in (-1, 1):
        report.question("relation.direction_sign must be explicitly +1 or -1; charge/discharge names do not determine it")
    _enum(relation, "delta_convention", ("x_minus_reference_x",), report, "relation")
    _text(relation, "source", report, "relation")
    _number(relation, "reference_capacity_mAh_g", report, "relation")
    _text(relation, "reference_source", report, "relation")
    if output == "absolute_x":
        _number(relation, "reference_x", report, "relation")
        _text(relation, "reference_x_source", report, "relation")
    elif "reference_x" in relation:
        _number(relation, "reference_x", report, "relation")
        _text(relation, "reference_x_source", report, "relation")
    if output == "delta_x" or "reference_delta_x" in relation:
        _number(relation, "reference_delta_x", report, "relation")
        _text(relation, "reference_delta_x_source", report, "relation")
    if not isinstance(point_data, list) or not point_data:
        report.question("point_data must be a non-empty supplied list of capacity_mAh_g/voltage_V records")
        points = []
    else:
        points = point_data
    identities = {}
    for index, raw in enumerate(points):
        path = "point_data[%d]" % index
        point = _object(raw, report, path)
        _number(point, "capacity_mAh_g", report, path)
        _number(point, "voltage_V", report, path)
        if "series_id" in point and point["series_id"] != series_id:
            report.question("%s.series_id differs from declaration.series_id; convert explicitly identified series separately" % path)
        for field in ("sample", "cycle", "branch", "segment"):
            if field in point:
                if field in identities and identities[field] != point[field]:
                    report.question("%s changes %s within the supplied series; supply a separate signed relation/reference for each series" % (path, field))
                else:
                    identities[field] = point[field]
    declaration_sha256 = _digest(declared, report, "declaration")
    input_sha256 = _digest({"declaration": declared, "point_data": point_data}, report, "conversion input")
    report.counts.update(supplied_points=len(points), converted_points=0)
    return {"ready": not report.blocking, "declaration_sha256": declaration_sha256,
            "input_sha256": input_sha256, "contract": copy.deepcopy(declared),
            "report": report.to_dict(), "scientific_truth_verified": False}


def convert_na_coordinates(point_data, declaration, approval):
    """Convert reviewed supplied inputs, returning new points and full provenance.

    ``approval`` records a prior scientific confirmation, not a new permission
    interaction. Once the actual inputs/reference are confirmed, call directly
    with user_approved=True, matching reviewed_input_sha256 and evidence text.
    """
    report = ValidationReport()
    validation = validate_na_conversion(point_data, declaration, report)
    approval_record = _object(approval, report, "approval")
    if approval_record.get("user_approved") is not True:
        report.question("approval must record user_approved=true after the actual data, mass basis, signed relation and reference were confirmed")
    _text(approval_record, "evidence", report, "approval")
    if approval_record.get("reviewed_input_sha256") != validation["input_sha256"] or not validation["input_sha256"]:
        report.question("approval.reviewed_input_sha256 must identify these exact supplied points and scientific declarations")
    report.raise_if_blocking("Na conversion scientific input contract")
    declared = validation["contract"]
    normalization = declared["mass_normalization"]
    fraction = normalization["active_fraction"]["value"] if normalization["basis"] == "electrode_composite" else 1.0
    material, relation, assumptions = declared["material"], declared["relation"], declared["assumptions"]
    # Both Q and Q_ref are declared on the SAME original mass basis. No independent
    # correction is guessed; active-normalised input is never divided by f twice.
    factor = material["molar_mass_g_mol"] * 3.6 / (FARADAY_CONSTANT_C_MOL * assumptions["electrons_per_na"])
    converted, xy_points = [], []
    for index, point in enumerate(point_data):
        try:
            local_delta = ((point["capacity_mAh_g"] - relation["reference_capacity_mAh_g"]) / fraction
                           * factor * relation["direction_sign"])
            coordinate = (local_delta + relation["reference_x"] if declared["output"] == "absolute_x"
                          else local_delta + relation["reference_delta_x"])
        except (ArithmeticError, ValueError, TypeError):
            report.error("Na conversion arithmetic is not finite at point_data[%d]; no point is omitted" % index)
            continue
        if not math.isfinite(local_delta) or not math.isfinite(coordinate):
            report.error("Na conversion overflow at point_data[%d]; no point is omitted" % index)
            continue
        output = copy.deepcopy(point)
        output["delta_from_reference"] = local_delta
        output["delta_x"] = local_delta if declared["output"] == "absolute_x" else coordinate
        if declared["output"] == "absolute_x":
            output["na_x"] = coordinate
        converted.append(output)
        xy_points.append((coordinate, point["voltage_V"]))
    report.raise_if_blocking("Na conversion finite results")
    report.counts["converted_points"] = len(converted)
    provenance = {"method": METHOD, "version": 1, "status": "declared",
                  "scientific_truth_verified": False,
                  "coordinate_interpretation": "capacity-equivalent estimate under supplied assumptions; not independent composition determination",
                  "declaration": copy.deepcopy(declared), "approval": copy.deepcopy(approval_record),
                  "input_sha256": validation["input_sha256"], "declaration_sha256": validation["declaration_sha256"],
                  "formula": "local_delta = ((Q - Q_ref) / mass_basis_fraction) * M * 3.6 / (F * electrons_per_na) * direction_sign; delta_x = reference_delta_x + local_delta; absolute_x = reference_x + local_delta",
                  "mass_basis_fraction_applied": fraction,
                  "constants": {"faraday_C_mol": FARADAY_CONSTANT_C_MOL,
                                "avogadro_mol_1": AVOGADRO_CONSTANT_MOL_1,
                                "elementary_charge_C": ELEMENTARY_CHARGE_C,
                                "definition": "F = N_A * e; exact SI inputs, evaluated in binary float",
                                "source": CONSTANT_SOURCE},
                  "chemistry_source": CHEMISTRY_SOURCE,
                  "limitations": ["Parasitic/non-Na charge is not removed by this module",
                                  "No cross-cycle composition continuity is inferred",
                                  "Formula identity, mass normalization and reference are not independently verified; formula-calculated M retains its versioned atomic-weight source",
                                  "No physical x range is imposed; every finite result is retained"]}
    if assumptions["parasitic_charge"] == "unknown":
        provenance["status"] = "unknown"
        provenance["gaps"] = [{"path": "assumptions.parasitic_charge", "kind": "charge_attribution", "reason": "Parasitic charge contribution is unknown"}]
    return {"series_id": declared["series_id"], "output": declared["output"],
            "points": converted, "xy_points": xy_points,
            "axis_labels": {"x": "x (Na per formula unit)" if declared["output"] == "absolute_x" else "Delta x (Na per formula unit)", "y": "Voltage (V)"},
            "provenance": provenance, "report": report.to_dict()}
