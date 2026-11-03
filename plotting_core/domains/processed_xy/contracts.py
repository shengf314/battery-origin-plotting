"""Declarations for supplied XY data; checks completeness, never scientific truth."""

import math
from ... import registry

ROLES = ("measurement", "processed", "derived", "reference")
CONNECTIONS = ("line", "scatter", "line_points")
FIELDS = ("SeriesID", "Sample", "X", "Y", "Cycle", "Branch", "Segment", "Role",
          "Frequency", "Phase", "Element", "Condition")
PROCESSED_ROLES = ("processed", "derived")
WAVELENGTH_UNITS = ("angstrom", "Å", "nm", "pm", "m")


def _unknown(value):
    return isinstance(value, str) and value.strip().lower() == "unknown"


def _positive_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value > 0
    except (OverflowError, TypeError, ValueError):
        return False


def _text(mapping, key, report, context, required=True, allow_unknown=False):
    value = mapping.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        report.question("%s.%s must be a non-empty string; no scientific meaning is inferred" % (context, key))
        return None
    if _unknown(value) and not allow_unknown:
        report.question("%s.%s must be known; unknown cannot define scientific coordinates" % (context, key))
        return None
    return value


def _enum(mapping, key, allowed, report, context):
    value = _text(mapping, key, report, context, allow_unknown="unknown" in allowed)
    if value is not None and value not in allowed:
        report.question("%s.%s must explicitly be one of %s; no conversion or inference is performed"
                        % (context, key, ", ".join(allowed)))
    return value if value in allowed else None


def _object(value, report, context):
    if not isinstance(value, dict):
        report.question("%s must be an object" % context)
        return {}
    return value


def _parameters(record, report, context, required=False):
    parameters = record.get("parameters")
    if parameters is None:
        if required:
            report.question("%s.parameters must record the already applied processing parameters" % context)
    elif not isinstance(parameters, dict):
        report.question("%s.parameters must be an object containing supplied historical parameters" % context)


def source_declaration(record, report, context):
    """Legacy strings remain valid; a structured source carries an explicit value."""
    value = record.get("source")
    if isinstance(value, dict):
        _enum(value, "status", ("declared",), report, context + ".source")
        _text(value, "value", report, context + ".source")
    else:
        _text(record, "source", report, context)


def method_declaration(record, report, context, required=True):
    """Unknown historical methods may be drawn, but are never certified or executed."""
    value = record.get("method")
    if value is None and not required:
        _parameters(record, report, context)
        return
    if isinstance(value, dict):
        status = _enum(value, "status", ("declared", "unknown"), report, context + ".method")
        if status == "declared":
            _text(value, "name", report, context + ".method")
        elif status == "unknown":
            _text(value, "reason", report, context + ".method")
            if "name" in value and not _unknown(value["name"]):
                report.error("%s.method cannot combine status=unknown with a declared method name" % context)
        _parameters(value, report, context + ".method")
    else:
        _text(record, "method", report, context, allow_unknown=True)
    _parameters(record, report, context)


def provenance(record, report, context, method=True):
    record = _object(record, report, context)
    source_declaration(record, report, context)
    if method or "method" in record:
        method_declaration(record, report, context, required=method)
    else:
        _parameters(record, report, context)
    return record


def _unknown_method(record):
    value = record.get("method")
    return _unknown(value) or (isinstance(value, dict) and value.get("status") == "unknown")


def _reject_requests(value, report, context):
    """Inspect explicit execution requests, including new nested provenance records.

    Method names and parameter values are historical declarations, not instructions;
    no scientific protocol is guessed from free text.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            path = "%s.%s" % (context, key)
            request_key = isinstance(key, str) and (key.lower().startswith("requested_") or key.lower() in ("request", "requested", "execute"))
            if request_key and item not in (None, False, "", [], {}):
                report.error("%s requests an operation; supplied-series rendering performs no calculation, smoothing or conversion" % path)
            if key == "status" and isinstance(item, str) and item.lower() in ("requested", "to_be_computed", "to_be_applied"):
                report.error("%s describes pending processing; provide existing results instead" % path)
            _reject_requests(item, report, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_requests(item, report, "%s[%d]" % (context, index))


def _validate_na(semantics, x, report):
    if "na_content" in semantics:
        record = _object(semantics["na_content"], report, "semantics.na_content")
        for key in ("definition", "reference"):
            _text(record, key, report, "semantics.na_content")
        source_declaration(record, report, "semantics.na_content")
        if "status" in record:
            _enum(record, "status", ("declared",), report, "semantics.na_content")
    elif x.get("quantity") == "sodium_content":
        report.warn("legacy supplied sodium_content has no na_content definition/reference record; coordinates are retained but scientific traceability is unknown")


def validate_semantics(family, semantics, report):
    """Aggregate typed declarations before any unsafe mapping or row access."""
    registry.validate_data_kind(family, "excel_processed_series")
    if not isinstance(semantics, dict):
        report.error("data.semantics must be an object")
        return
    _reject_requests(semantics, report, "semantics")
    axes = {}
    for key in ("x", "y"):
        axis = _object(semantics.get(key), report, "semantics." + key)
        axes[key] = axis
        for field in ("quantity", "unit"):
            _text(axis, field, report, "semantics." + key)
        _enum(axis, "scale", ("linear", "log10"), report, "semantics." + key)
        _enum(axis, "direction", ("ascending", "descending"), report, "semantics." + key)
        if "label" in axis:
            _text(axis, "label", report, "semantics." + key)
    x, y = axes["x"], axes["y"]
    _text(semantics, "variant", report, "semantics")
    variant = semantics.get("variant")
    if not isinstance(variant, str):
        variant = None
    if semantics.get("error_bars"):
        report.error("error bars are not implemented; do not silently omit requested uncertainty")
    metadata = _object(semantics.get("series_metadata"), report, "semantics.series_metadata")
    for series_id, record in metadata.items():
        if not isinstance(series_id, str) or not series_id.strip():
            report.error("semantics.series_metadata keys must be non-empty SeriesID strings")
        validate_series(family, semantics, record, report, series_id)
    if "row_layout" in semantics:
        _enum(semantics, "row_layout", ("contiguous", "interleaved"), report, "semantics")
    if "frequency" in semantics:
        frequency = _object(semantics["frequency"], report, "semantics.frequency")
        _enum(frequency, "unit", ("Hz",), report, "semantics.frequency")
        _enum(frequency, "order", ("as_provided",), report, "semantics.frequency")
    preprocessing = provenance(semantics.get("preprocessing"), report, "semantics.preprocessing", method=False)
    _enum(preprocessing, "state", ("raw", "provided_processed", "provided_results"), report, "preprocessing")
    # Even optional supplied processing records must be typed, never silently discarded.
    # Historical method records disclose provenance; they never authorize a
    # calculation. Family/role routing and explicit request rejection set scope.
    for key in ("derivative", "normalization", "diffusion", "offset", "energy_reference", "composition"):
        if key in preprocessing:
            record = preprocessing[key]
            if not isinstance(record, dict):
                report.question("preprocessing.%s must be an object" % key)
                continue
            if "source" in record:
                source_declaration(record, report, "preprocessing." + key)
            if "method" in record:
                method_declaration(record, report, "preprocessing." + key)
            _parameters(record, report, "preprocessing." + key)
            if "applied" in record and not isinstance(record["applied"], bool):
                report.question("preprocessing.%s.applied must be true/false" % key)
    _validate_na(semantics, x, report)
    if family == "eis":
        if variant != "nyquist":
            report.error("eis implements supplied Nyquist XY series only")
        _enum(x, "quantity", ("real_impedance",), report, "semantics.x")
        quantity = _enum(y, "quantity", ("imaginary_impedance", "minus_imaginary_impedance"), report, "semantics.y")
        xu = _enum(x, "unit", ("Ohm", "kOhm", "mOhm"), report, "semantics.x")
        yu = _enum(y, "unit", ("Ohm", "kOhm", "mOhm"), report, "semantics.y")
        if xu and yu and xu != yu:
            report.error("Nyquist real/imaginary impedance units must match")
        convention = {"imaginary_impedance": "imaginary", "minus_imaginary_impedance": "minus_imaginary"}
        sign = _enum(semantics, "sign_convention", ("imaginary", "minus_imaginary"), report, "semantics")
        if quantity and sign and sign != convention[quantity]:
            report.question("EIS sign_convention must agree with the already supplied Y ordinate")
        if x.get("scale") != "linear" or y.get("scale") != "linear":
            report.error("Nyquist axes must be linear; no impedance values are transformed")
    elif family == "gitt":
        if variant != "supplied_diffusion":
            report.error("gitt implements supplied_diffusion only; time-voltage response is not implemented")
        else:
            quantity = _enum(x, "quantity", ("sodium_content", "voltage", "time"), report, "semantics.x")
            units = {"sodium_content": ("1", "Na/f.u."), "voltage": ("V", "mV"), "time": ("s", "min", "h")}
            _enum(x, "unit", units.get(quantity, ()), report, "semantics.x")
            quantity = _enum(y, "quantity", ("diffusion_coefficient", "log10_diffusion_coefficient"), report, "semantics.y")
            if quantity == "log10_diffusion_coefficient":
                _enum(y, "unit", ("log10(cm2 s-1)", "log10(m2 s-1)"), report, "semantics.y")
                if y.get("scale") != "linear":
                    report.error("already log10 diffusion values require a linear Y axis; double log is forbidden")
            else:
                _enum(y, "unit", ("cm2 s-1", "m2 s-1"), report, "semantics.y")
            provenance(preprocessing.get("diffusion"), report, "preprocessing.diffusion")
    elif family == "xrd":
        if variant != "provided_spectrum":
            report.error("%s.variant must be provided_spectrum" % family)
        _enum(y, "quantity", ("intensity",), report, "semantics.y")
        _enum(y, "unit", ("counts", "counts/s", "cps", "a.u.", "%"), report, "semantics.y")
        for key in ("normalization", "offset"):
            record = _object(preprocessing.get(key), report, "preprocessing." + key)
            if not isinstance(record.get("applied"), bool):
                report.question("%s preprocessing.%s.applied must explicitly be true/false" % (family, key))
            elif record["applied"]:
                provenance(record, report, "preprocessing." + key)
                _parameters(record, report, "preprocessing." + key,
                            required=not _unknown_method(record) and not isinstance(record.get("method"), dict))
                if isinstance(record.get("method"), dict) and not _unknown_method(record):
                    _parameters(record["method"], report, "preprocessing." + key + ".method",
                                required="parameters" not in record)
            else:
                if "source" in record:
                    source_declaration(record, report, "preprocessing." + key)
                method_declaration(record, report, "preprocessing." + key, required=False)
        _enum(x, "quantity", ("two_theta",), report, "semantics.x")
        _enum(x, "unit", ("degree",), report, "semantics.x")
        radiation = provenance(semantics.get("radiation"), report, "semantics.radiation", method=False)
        wavelength = radiation.get("wavelength")
        if not _positive_number(wavelength):
            report.question("XRD radiation.wavelength must be a known positive number, excluding bool")
        _enum(radiation, "unit", WAVELENGTH_UNITS, report, "semantics.radiation")
    elif family == "icp":
        if variant not in ("element_ratio", "normalized_composition"):
            report.error("icp implements supplied element_ratio/normalized_composition only; concentration is not enabled")
        _enum(x, "quantity", ("element_index",), report, "semantics.x")
        _enum(x, "unit", ("1",), report, "semantics.x")
        quantities = {"element_ratio": ("element_ratio",), "normalized_composition": ("atomic_fraction", "molar_fraction", "mass_fraction")}
        _enum(y, "quantity", quantities.get(variant, ()), report, "semantics.y")
        _enum(y, "unit", ("1",) if variant == "element_ratio" else ("1", "%"), report, "semantics.y")
        composition = provenance(preprocessing.get("composition"), report, "preprocessing.composition")
        _text(composition, "basis", report, "preprocessing.composition")


def validate_series(family, semantics, record, report, series_id):
    registry.validate_data_kind(family, "excel_processed_series")
    context = "series_metadata[%r]" % series_id
    if not isinstance(record, dict):
        report.question("%s must be a source/method object" % context)
        return
    _text(record, "legend", report, context)
    role = _enum(record, "role", ROLES, report, context)
    if record.get("role") in ("fit", "background", "component"):
        report.error("%s is an excluded fitted/decomposed analysis result; this skill accepts direct data and simple formula results" % context)
    connection = _enum(record, "connection", CONNECTIONS, report, context)
    source_declaration(record, report, context)
    method_declaration(record, report, context, required=role in PROCESSED_ROLES)
    for key in ("sample", "branch", "condition"):
        if key in record:
            _text(record, key, report, context)
    if "cycle" in record and (isinstance(record["cycle"], bool) or not isinstance(record["cycle"], int)):
        report.error("%s.cycle must be an integral number excluding bool" % context)
    if role == "reference":
        _text(record, "reference_id", report, context)
        if family == "xrd":
            kind = _enum(record, "reference_kind", ("supplied_curve", "peak_positions"), report, context)
            if kind == "peak_positions" and connection != "scatter":
                report.error("XRD discrete reference peaks require scatter; native stick rendering is not implemented")
    if family == "icp" and connection != "scatter":
        report.error("ICP elemental categories are independent observations; this adapter accepts scatter only")
    if family == "gitt" and semantics.get("variant") == "supplied_diffusion" and role != "derived":
        report.error("GITT supplied_diffusion series must declare role derived and its calculation provenance")
    if record.get("error_bars"):
        report.error("error bars are not implemented by the processed-series adapter")
