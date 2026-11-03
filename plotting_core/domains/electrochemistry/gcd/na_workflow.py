"""Independent Na preflight/conversion using the standard GCD NormalizedData.

No workbook dialect, parser, renderer or style is added here. Per-cycle discharge
references use the same sample/cycle charge endpoint, as explicitly authorised.
"""

import copy
import math

from ....ingest.normalize import NormalizedData
from ....ingest.report import ValidationReport
from ....provenance import traceability_summary
from .na_conversion import (METHOD, _digest, _number, _object, _text,
                            convert_na_coordinates, validate_na_conversion)

def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _source_row(item, index):
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    rows = metadata.get("source_rows")
    if isinstance(rows, list) and len(rows) == len(item.points):
        return rows[index]
    if index == len(item.points) - 1:
        return item.last_row
    if index == 0:
        return item.first_row
    return None  # No interior row numbers are invented from a row range.


def preflight_gcd_na(data, settings, report=None):
    """Audit the existing GCD series and compute formula M, without Na conversion.

    settings: output, samples[sample] (formula/material/assumptions and optional
    mass override), per_series[series_id] explicit signed relation and Q reference.
    Charge initial delta or absolute x must be supplied per cycle. Discharge
    offsets are deferred to the matching charge endpoint, with exact row identity.
    Discharge reference_state must identify the first supplied point as the actual
    same_cycle_discharge_start; its Q reference must equal that point's capacity.
    """
    if report is None:
        report = ValidationReport()
    configured = _object(settings, report, "gcd_na.settings")
    output = configured.get("output")
    if output not in ("delta_x", "absolute_x"):
        report.question("gcd_na.settings.output must be delta_x/absolute_x")
    samples = _object(configured.get("samples"), report, "gcd_na.settings.samples")
    per_series = _object(configured.get("per_series"), report, "gcd_na.settings.per_series")
    if not isinstance(data, NormalizedData) or data.plot_type != "gcd":
        report.question("GCD Na workflow requires standard GCD NormalizedData from the existing input interface")
        return {"ready": False, "input_sha256": None, "series": [], "report": report.to_dict()}
    source = _object(data.source, report, "gcd.source")
    if source.get("x_representation") != "specific_capacity":
        report.question("GCD Na workflow requires the supplied specific_capacity representation; already converted Na coordinates are not reinterpreted")
    binding = source.get("axis_binding", "capacity_voltage")
    if binding not in ("capacity_voltage", "voltage_capacity"):
        report.question("gcd.source.axis_binding must be capacity_voltage/voltage_capacity")
        binding = "capacity_voltage"
    capacity_index = 0 if binding == "capacity_voltage" else 1
    _text(source, "file", report, "gcd.source")
    semantics = source.get("semantics") or {}
    if not isinstance(semantics, dict):
        report.question("gcd.source.semantics must be an object")
        semantics = {}
    for axis, capacity in (("x", capacity_index == 0), ("y", capacity_index == 1)):
        axis_record = semantics.get(axis) or {}
        if not isinstance(axis_record, dict):
            report.question("gcd.source.semantics.%s must be an axis object" % axis)
            continue
        if "unit" in axis_record and axis_record["unit"] != ("mAh g-1" if capacity else "V"):
            report.question("GCD source %s unit conflicts with the standard supplied capacity/voltage contract" % axis)
        if "quantity" in axis_record and axis_record["quantity"] != ("specific_capacity" if capacity else "voltage"):
            report.question("GCD source %s quantity conflicts with its explicit axis binding" % axis)
        if capacity and axis_record.get("scale", "linear") != "linear":
            report.question("Na conversion output needs an explicitly linear Na coordinate axis; resolve the prior logarithmic capacity scale")
    descriptors, groups, ids = [], {}, set()
    if not data.series:
        report.question("GCD Na workflow has no supplied series")
    for position, item in enumerate(data.series):
        if not isinstance(item.sample, str) or not item.sample or isinstance(item.cycle, bool) or not isinstance(item.cycle, int) or item.branch not in ("charge", "discharge"):
            report.question("gcd series %d must identify a sample, integral cycle and explicit charge/discharge branch" % position)
            continue
        key = (item.sample, item.cycle, item.branch)
        if key in groups or item.series_id in ids:
            report.question("GCD has ambiguous repeated sample/cycle/branch or SeriesID; define independent series before Na conversion")
        ids.add(item.series_id)
        points, endpoint = [], None
        for index, point in enumerate(item.points):
            if not isinstance(point, (tuple, list)) or len(point) != 2 or not all(_finite(value) for value in point):
                report.question("series %s point %d must contain two finite numeric coordinates; no invalid point is dropped" % (item.series_id, index))
                continue
            record = {"capacity_mAh_g": point[capacity_index], "voltage_V": point[1 - capacity_index],
                      "sample": item.sample, "cycle": item.cycle, "branch": item.branch,
                      "series_id": item.series_id, "source_row": _source_row(item, index), "point_index": index}
            points.append(record)
            endpoint = copy.deepcopy(record)
        if not points:
            report.question("series %s has no supplied numeric GCD points" % item.series_id)
        sample_record = _object(samples.get(item.sample), report, "gcd_na.samples[%r]" % item.sample)
        material = sample_record.get("material")
        if material is None:
            material = {"formula": sample_record.get("formula"),
                        "formula_source": sample_record.get("formula_source", "user supplied numeric formula for this GCD sample"),
                        "formula_unit_basis": "one supplied formula unit of the reference active material"}
        material = copy.deepcopy(_object(material, report, "gcd_na.material[%r]" % item.sample))
        material.setdefault("formula_source", "user supplied numeric formula for this GCD sample")
        material.setdefault("formula_unit_basis", "one supplied formula unit of the reference active material")
        material["molar_mass_method"] = "ciaaw2024_formula"
        # A public installation cannot inherit the author's scientific
        # confirmation. Missing declarations are reported by the validator.
        mass_basis = sample_record.get("mass_normalization", configured.get("mass_normalization"))
        relation = copy.deepcopy(_object(per_series.get(item.series_id), report, "gcd_na.per_series[%r]" % item.series_id))
        relation.setdefault("delta_convention", "x_minus_reference_x")
        if item.branch == "discharge":
            if relation.get("reference_state") != "same_cycle_discharge_start":
                report.question("discharge %s needs reference_state=same_cycle_discharge_start and reference_source confirming that the first supplied point is this cycle's actual discharge start; truncated or unknown starts cannot inherit the charge endpoint" % item.series_id)
            if points:
                start = points[0]
                if _finite(relation.get("reference_capacity_mAh_g")) and relation["reference_capacity_mAh_g"] != start["capacity_mAh_g"]:
                    report.question("discharge %s reference_capacity_mAh_g must equal its explicitly confirmed first supplied discharge-start capacity (%r); the charge endpoint cannot be assigned to another capacity state" % (item.series_id, start["capacity_mAh_g"]))
                if isinstance(start["source_row"], bool) or not isinstance(start["source_row"], int):
                    report.question("discharge %s start needs an exact source row; its identity cannot be inferred from an interior range" % item.series_id)
        declared = {"method": METHOD, "output": output, "series_id": item.series_id,
                    "source": "%s!%s / %s" % (source.get("file"), source.get("sheet"), item.series_id),
                    "capacity_unit": "mAh g-1", "voltage_unit": "V", "material": material,
                    "mass_normalization": copy.deepcopy(mass_basis),
                    "assumptions": copy.deepcopy(sample_record.get("assumptions")), "relation": relation}
        # A temporary placeholder validates other fields without Na arithmetic.
        # It is removed from the public prepared contract and never used to convert.
        deferred_key = "reference_x" if output == "absolute_x" else "reference_delta_x"
        temporary = copy.deepcopy(declared)
        if item.branch == "discharge":
            temporary["relation"][deferred_key] = 0.
            temporary["relation"][deferred_key + "_source"] = "deferred same-sample same-cycle charge endpoint; no numerical offset chosen in preflight"
        validation = validate_na_conversion(points, temporary, report)
        prepared = validation["contract"]
        if item.branch == "discharge":
            prepared["relation"].pop(deferred_key, None)
            prepared["relation"].pop(deferred_key + "_source", None)
        descriptor = {"position": position, "series_id": item.series_id, "sample": item.sample,
                      "cycle": item.cycle, "branch": item.branch, "points": points,
                      "declaration": prepared, "supplied_relation": relation, "endpoint_input_point": endpoint}
        descriptors.append(descriptor)
        groups[key] = descriptor
    for descriptor in descriptors:
        if descriptor["branch"] != "discharge":
            continue
        charge = groups.get((descriptor["sample"], descriptor["cycle"], "charge"))
        if charge is None or charge["endpoint_input_point"] is None:
            report.question("discharge %s requires the same sample/cycle charge endpoint; no other cycle is substituted" % descriptor["series_id"])
            continue
        endpoint = charge["endpoint_input_point"]
        if isinstance(endpoint["source_row"], bool) or not isinstance(endpoint["source_row"], int):
            report.question("charge %s endpoint needs an exact source row; its row is not inferred from an interior range" % charge["series_id"])
        descriptor["reference_derivation"] = {"method": "same_sample_same_cycle_charge_endpoint",
            "charge_series_id": charge["series_id"], "endpoint_input_point": copy.deepcopy(endpoint),
            "discharge_start_input_point": copy.deepcopy(descriptor["points"][0]) if descriptor["points"] else None,
            "discharge_reference_state": descriptor["supplied_relation"].get("reference_state"),
            "discharge_reference_source": descriptor["supplied_relation"].get("reference_source")}
    report.counts.update(supplied_series=len(data.series), supplied_points=sum(len(item.points) for item in data.series), converted_points=0)
    original = {"plot_type": data.plot_type, "source": copy.deepcopy(data.source),
                "series": [{"sample": item.sample, "cycle": item.cycle, "branch": item.branch,
                            "series_id": item.series_id, "points": item.points, "first_row": item.first_row,
                            "last_row": item.last_row, "metadata": item.metadata} for item in data.series]}
    fingerprint = _digest({"input": original, "settings": settings, "prepared": descriptors}, report, "GCD Na workflow input")
    return {"ready": not report.blocking, "input_sha256": fingerprint, "axis_binding": binding,
            "output": output, "series": descriptors, "report": report.to_dict(), "scientific_truth_verified": False}


def convert_gcd_na(data, settings, approval):
    """Return a new standard GCD object after already recorded scientific review."""
    report = ValidationReport()
    preflight = preflight_gcd_na(data, settings, report)
    approved = _object(approval, report, "gcd_na.approval")
    if approved.get("user_approved") is not True:
        report.question("GCD Na conversion requires a record that these scientific inputs were confirmed")
    _text(approved, "evidence", report, "gcd_na.approval")
    if approved.get("reviewed_input_sha256") != preflight["input_sha256"] or not preflight["input_sha256"]:
        report.question("GCD Na confirmation must identify these exact inputs, formulas and per-cycle references")
    report.raise_if_blocking("GCD Na scientific preflight")
    converted = {}
    # Dependency order is internal only; the output retains original series order.
    ordered = [item for item in preflight["series"] if item["branch"] == "charge"] + [item for item in preflight["series"] if item["branch"] == "discharge"]
    for descriptor in ordered:
        declared = copy.deepcopy(descriptor["declaration"])
        endpoint_record = None
        if descriptor["branch"] == "discharge":
            derivation = descriptor["reference_derivation"]
            charge = converted[derivation["charge_series_id"]]
            endpoint_index = derivation["endpoint_input_point"]["point_index"]
            endpoint_coordinate = charge["points"][endpoint_index]["na_x" if preflight["output"] == "absolute_x" else "delta_x"]
            key = "reference_x" if preflight["output"] == "absolute_x" else "reference_delta_x"
            supplied = descriptor["supplied_relation"].get(key)
            if supplied is not None and supplied != endpoint_coordinate:
                report.question("discharge %s supplied %s differs from the exact same-cycle charge endpoint; resolve the conflicting reference" % (descriptor["series_id"], key))
                report.raise_if_blocking("GCD charge/discharge continuity")
            declared["relation"][key] = endpoint_coordinate
            declared["relation"][key + "_source"] = "same sample/cycle charge %s point %d, source row %s" % (derivation["charge_series_id"], endpoint_index, derivation["endpoint_input_point"]["source_row"])
            endpoint_record = copy.deepcopy(derivation)
            endpoint_record["endpoint_calculated_coordinate"] = endpoint_coordinate
        dry = validate_na_conversion(descriptor["points"], declared)
        local_approval = {"user_approved": True, "evidence": approved["evidence"], "reviewed_input_sha256": dry["input_sha256"]}
        result = convert_na_coordinates(descriptor["points"], declared, local_approval)
        if endpoint_record is not None:
            result["provenance"]["charge_endpoint_reference"] = endpoint_record
        converted[descriptor["series_id"]] = result
    output = copy.deepcopy(data)
    capacity_index = 0 if preflight["axis_binding"] == "capacity_voltage" else 1
    quantity = "delta_na_content" if preflight["output"] == "delta_x" else "na_content"
    for descriptor in preflight["series"]:
        item = output.series[descriptor["position"]]
        result = converted[descriptor["series_id"]]
        item.points = [point if capacity_index == 0 else (point[1], point[0]) for point in result["xy_points"]]
        item.explicit_id = descriptor["series_id"]
        item.metric = quantity
        item.metadata = copy.deepcopy(item.metadata or {})
        item.metadata["na_conversion"] = copy.deepcopy(result["provenance"])
        item.metadata["source"] = result["provenance"]["declaration"]["source"]
        item.metadata["method"] = {"status": "declared", "name": METHOD, "parameters": copy.deepcopy(result["provenance"]["declaration"])}
        item.metadata["role"] = "derived"
        na_axis = {"quantity": quantity, "unit": "1", "scale": "linear"}
        voltage_axis = {"quantity": "voltage", "unit": "V"}
        item.metadata.update(x=copy.deepcopy(na_axis if capacity_index == 0 else voltage_axis),
                             y=copy.deepcopy(voltage_axis if capacity_index == 0 else na_axis))
    axis = "x" if capacity_index == 0 else "y"
    output.axis_labels[axis] = "Delta x (Na per formula unit)" if preflight["output"] == "delta_x" else "x (Na per formula unit)"
    semantics = copy.deepcopy(output.source.get("semantics") or {})
    semantics.setdefault(axis, {}).update(quantity=quantity, unit="1", scale="linear", label=output.axis_labels[axis])
    semantics["na_content"] = {"definition": quantity + "; capacity equivalent under supplied one-electron assumptions",
                              "source": "explicit independent GCD Na workflow", "reference": "per-cycle charge initial reference and exact same-cycle endpoint transfer; see na_workflow.series"}
    output.source.update(x_representation="na_content", semantics=semantics,
                         na_workflow={"input_sha256": preflight["input_sha256"], "approval": copy.deepcopy(approved),
                                      "series": {key: value["provenance"] for key, value in converted.items()},
                                      "scientific_truth_verified": False})
    gaps = []
    for series_id, result in converted.items():
        for gap in result["provenance"].get("gaps", []):
            entry = copy.deepcopy(gap)
            entry["path"] = "na_workflow.series[%r].%s" % (series_id, entry["path"])
            gaps.append(entry)
    output.source["traceability_gaps"] = copy.deepcopy(output.source.get("traceability_gaps", [])) + gaps
    output.source["scientific_traceability"] = traceability_summary(output)
    return output
