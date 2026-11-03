"""Bridge explicit B results to the existing A workbook contracts.

Uses only the standard library; these workbooks are ordinary supplied-value A
inputs, never an added data.kind or a request to repeat their processing.
"""

import copy
import json
import math
import zipfile
import hashlib
from collections import OrderedDict
from pathlib import Path
from xml.etree import ElementTree as ET

from ...models import PlotSpec
from ...ingest import load_normalized_data
from ...ingest.xlsx import Workbook
from ...ingest.report import ValidationReport
from ..electrochemistry import schema

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ET.register_namespace("", NS)


def _letter(index):
    out = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        out = chr(65 + remainder) + out
    return out


def write_standard_xlsx(path, headers, rows):
    """Write finite supplied values and explicit text, with no formulas."""
    path = Path(path)
    if path.exists():
        raise ValueError("Do not overwrite an existing bridge workbook: %s" % path)
    sheet = ET.Element("{%s}worksheet" % NS)
    table = ET.SubElement(sheet, "{%s}sheetData" % NS)
    for index, values in enumerate([list(headers)] + list(rows), 1):
        row = ET.SubElement(table, "{%s}row" % NS, r=str(index))
        for col, value in enumerate(values, 1):
            if value is None:
                continue
            cell = ET.SubElement(row, "{%s}c" % NS, r=_letter(col) + str(index))
            if isinstance(value, bool):
                raise ValueError("Boolean cells are not scientific numeric input")
            if isinstance(value, (int, float)):
                if not math.isfinite(value):
                    raise ValueError("Nonfinite bridge value; no dropping is allowed")
                ET.SubElement(cell, "{%s}v" % NS).text = repr(value)
            elif isinstance(value, str):
                cell.set("t", "inlineStr")
                node = ET.SubElement(ET.SubElement(cell, "{%s}is" % NS), "{%s}t" % NS)
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                node.text = value
            else:
                raise ValueError("Unsupported bridge cell type: %s" % type(value).__name__)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        package.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        package.writestr("xl/workbook.xml", '<workbook xmlns="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % NS)
        package.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        package.writestr("xl/worksheets/sheet1.xml", b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(sheet, encoding="utf-8"))
    return str(path)


def _axis(quantity, unit, label):
    return dict(quantity=quantity, unit=unit, scale="linear", direction="ascending", label=label)


def recover_gcd_source_rows(data, spec):
    """Re-read actual standard rows, matching each selected XY point in order.

    The legacy GCD reader retains only first/last rows. Do not invent interior
    row numbers from those bounds: blank, excluded or skipped rows can exist.
    Unused source columns are copied as provenance only, never interpreted as
    new scientific input fields or a new instrument parser.
    """
    filename = Path(data.source.get("resolved_file") or spec.data.file)
    expected_hash = data.source.get("sha256")
    if hashlib.sha256(filename.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("GCD source changed before recovering row identities")
    selected = {(item.sample, item.cycle, item.branch): item for item in data.series}
    recovered = {item.series_id: dict(source_rows=[], source_extra=[]) for item in data.series}
    report = ValidationReport()
    binding = data.source.get("axis_binding", "capacity_voltage")
    capacity_fields = {"charge": "Charge Specific Capacity", "discharge": "Discharge Specific Capacity"}
    if data.source.get("x_representation") == "na_content":
        capacity_fields = {"charge": "Charge Na Content", "discharge": "Discharge Na Content"}
    with Workbook(str(filename)) as workbook:
        sheet = data.source.get("sheet") or "Sheet1"
        header_row = data.source.get("header_row", 1)
        header = workbook.header(sheet, header_row)
        fields = schema.map_headers(header, spec.data.field_map, report)
        report.raise_if_blocking("GCD source row mapping")
        for number, cells in workbook.rows(sheet, start_row=header_row + 1):
            if all(cell.is_empty for cell in cells.values()):
                continue
            def cell(field):
                return cells.get(fields.get(field))
            branch_cell = cell("Branch")
            if schema.excluded_value_matches(branch_cell, spec.data.exclude_values.get("Branch", [])):
                continue
            cycle = schema.normalize_cycle(cell("Cycle"), report, number)
            branch = schema.normalize_branch(branch_cell, spec.data.value_map.get("Branch", {}), report, number)
            sample_cell = cell("Sample")
            sample = str(sample_cell.text).strip() if spec.data.sample_column and sample_cell else (spec.samples[0].get("name") if spec.samples else "sample")
            item = selected.get((sample, cycle, branch))
            if item is None or number in item.approved_skips:
                continue
            q = schema.numeric_value(cell(capacity_fields[branch]), capacity_fields[branch], report, number)
            voltage = schema.numeric_value(cell("Voltage"), "Voltage", report, number)
            point = (q, voltage) if binding == "capacity_voltage" else (voltage, q)
            identity = recovered[item.series_id]
            index = len(identity["source_rows"])
            if index >= len(item.points) or tuple(item.points[index]) != point:
                raise RuntimeError("GCD actual source row %d does not match selected series %s point %d" % (number, item.series_id, index))
            identity["source_rows"].append(number)
            identity["source_extra"].append({header.get(letter, letter): (value.text if value.text is not None else value.value)
                for letter, value in cells.items() if letter not in fields.values() and not value.is_empty})
    report.raise_if_blocking("GCD actual source row mapping")
    if any(len(recovered[item.series_id]["source_rows"]) != len(item.points) for item in data.series):
        raise RuntimeError("GCD source-row mapping lost a selected point")
    if hashlib.sha256(filename.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("GCD source changed while recovering row identities")
    return recovered


def _icp_denominator_label(ratios):
    """Display the actual canonical denominator, never an inferred normalization."""
    if not ratios:
        raise ValueError("ICP bridge needs calculated ratios with canonical denominators")
    denominator = ratios[0].get("denominator")
    if not isinstance(denominator, dict) or any(row.get("denominator") != denominator for row in ratios):
        raise ValueError("ICP global Y label needs one explicit canonical denominator shared by all results")
    normalization, elements = denominator.get("normalization"), denominator.get("elements")
    if (isinstance(normalization, bool) or not isinstance(normalization, (int, float))
            or not math.isfinite(normalization) or normalization <= 0 or not isinstance(elements, list)
            or not elements or any(not isinstance(element, str) or not element for element in elements)):
        raise ValueError("ICP calculated denominator needs actual positive normalization and exact elements")
    value = str(int(normalization)) if float(normalization).is_integer() else repr(normalization)
    if denominator.get("type") == "element" and len(elements) == 1:
        basis = elements[0]
    elif denominator.get("type") == "sum":
        basis = "sum(" + ", ".join(elements) + ")"
    else:
        raise ValueError("Unsupported calculated ICP denominator")
    return "Element molar ratio (%s=%s)" % (basis, value), copy.deepcopy(denominator)


def export_result(operation, result, data, source_spec, request, destination, record):
    """Export, reread with the existing reader, and compare every derived value."""
    if operation not in ("gcd_na", "xrd_normalization", "icp_molar_ratios"):
        raise ValueError("Only gcd_na, xrd_normalization and icp_molar_ratios can produce standard plotting inputs")
    destination = Path(destination).resolve()
    workbook = destination / "standard_result.xlsx"
    source_text = "%s; processing record: %s" % (request["source"], record)
    method = dict(status="declared", name=operation, parameters=copy.deepcopy(request["settings"]))
    if operation == "xrd_normalization":
        # The PDF identity is retained in the processing record; it is neither
        # a normalization parameter nor a new A request to create reference data.
        method["parameters"].pop("pdf_reference", None)
    if source_spec is not None:
        spec = copy.deepcopy(source_spec.to_dict())
    else:
        spec = dict(task_name="processed_icp", plot_type="icp", data={},
                    style_template="templates/publication_visual_template.yaml", backend={"name": "origin"})
    spec.update(task_name="processed_" + operation, output_root=str(destination / "figures"))
    # The B input selection was already applied. A must use every exported result.
    spec.update(selection={}, samples=[], labels={},
                verification=dict(level=3, reopen_project=True, editability_probe=True))
    recovered = recover_gcd_source_rows(data, source_spec) if operation == "gcd_na" else {}
    expected, mapping = [], []
    if operation == "gcd_na":
        binding = result.source.get("axis_binding", "capacity_voltage")
        capacity_index = 0 if binding == "capacity_voltage" else 1
        headers = ["Sample", "Cycle", "Branch", "Voltage(V)", "Charge Na Content", "Discharge Na Content"]
        rows = []
        for item in result.series:
            new_rows = []
            for point in item.points:
                na, voltage = point[capacity_index], point[1 - capacity_index]
                rows.append([item.sample, item.cycle, item.branch, voltage,
                             na if item.branch == "charge" else None,
                             na if item.branch == "discharge" else None])
                new_rows.append(len(rows) + 1)
            expected.append((item.sample, item.cycle, item.branch, item.points))
            identity = recovered[item.series_id]
            mapping.append(dict(series_id=item.series_id, source_rows=identity["source_rows"], source_extra=identity["source_extra"],
                                result_rows=new_rows, provenance=copy.deepcopy(item.metadata.get("na_conversion"))))
        semantics = copy.deepcopy(result.source["semantics"])
        semantics["processing_record"] = dict(source=source_text, method=method, series=mapping)
        spec["data"] = dict(kind="excel_long", file=str(workbook), sheet="Sheet1", sample_column="Sample", semantics=semantics)
        spec["selection"] = dict(mode="all", x_representation="na_content", axis_binding=binding)
        spec["labels"] = copy.deepcopy(result.axis_labels)
    else:
        headers = ["SeriesID", "Sample", "X", "Y", "Cycle", "Branch", "Element"]
        rows, metadata = [], {}
        if operation == "icp_molar_ratios":
            if result.get("replicate_summary"):
                raise ValueError("Replicate statistics are retained by B; the A bridge does not omit requested uncertainty")
            y_label, canonical_denominator = _icp_denominator_label(result["ratios"])
            elements = list(OrderedDict((row["element"], None) for row in result["ratios"]))
            groups = OrderedDict()
            for row in result["ratios"]:
                groups.setdefault((row["sample"], row["replicate"]), []).append(row)
            series = []
            for index, ((sample, replicate), items) in enumerate(groups.items(), 1):
                series.append(dict(series_id="ICP_%d" % index, sample=sample,
                                   points=[[elements.index(row["element"]) + 1, row["value"]] for row in items],
                                   elements=[row["element"] for row in items], replicate=replicate,
                                   source_record_indices=[row["source_row"] for row in items]))
            semantics = dict(variant="element_ratio", x=_axis("element_index", "1", "Element"),
                             y=_axis("element_ratio", "1", y_label),
                             preprocessing=dict(state="provided_results", source=source_text,
                                 composition=dict(basis="molar ratio; canonical denominator=" + json.dumps(canonical_denominator, ensure_ascii=False),
                                                  method=method, source=source_text)))
        else:
            series = []
            for item, original in zip(result["series"], data.series):
                series.append(dict(series_id=item["series_id"], sample=original.sample, cycle=original.cycle,
                                   branch=original.branch, points=item["points"], original=original))
            semantics = copy.deepcopy(source_spec.data.semantics)
            semantics["y"] = _axis("intensity", "%" if request["settings"]["method"] == "range100" else "a.u.",
                                    "Normalized intensity (%)" if request["settings"]["method"] == "range100" else "Normalized intensity (a.u.)")
            # a.u. is the established A spectral convention; B native columns
            # record the exact dimensionless unit 1 for max/range.
            semantics["preprocessing"] = dict(state="provided_processed", source=source_text,
                normalization=dict(applied=True, method=method, source=source_text), offset=dict(applied=False))
        for item in series:
            sid = item["series_id"]
            original = item.get("original")
            legend = (original.metadata.get("legend") if original else None) or item["sample"]
            if item.get("replicate") is not None:
                legend += " – replicate " + str(item["replicate"])
            entry = dict(role="derived" if operation == "icp_molar_ratios" else "processed", legend=legend,
                         source=source_text, method=method, connection="scatter" if operation == "icp_molar_ratios" else "line")
            if item.get("cycle") is not None:
                entry["cycle"] = item["cycle"]
            if item.get("branch") is not None:
                entry["branch"] = item["branch"]
            metadata[sid] = entry
            for index, point in enumerate(item["points"]):
                rows.append([sid, item["sample"], point[0], point[1], item.get("cycle"), item.get("branch"),
                             item.get("elements", [None] * len(item["points"]))[index]])
            expected.append((sid, item["points"]))
            identity = recovered.get(sid, {})
            mapping.append(dict(series_id=sid, source_rows=identity.get("source_rows", original.metadata.get("source_rows") if original else None),
                                source_extra=identity.get("source_extra"),
                                result_rows=list(range(len(rows) - len(item["points"]) + 2, len(rows) + 2))))
            if operation == "icp_molar_ratios":
                mapping[-1]["source_record_indices"] = item["source_record_indices"]
                mapping[-1]["source_record_index_meaning"] = "1-based index in supplied JSON records or explicit table rows; not an Excel file row number"
        semantics["series_metadata"] = metadata
        semantics["processing_record"] = dict(source=source_text, result_mapping=mapping)
        spec["plot_type"] = "xrd" if operation == "xrd_normalization" else "icp"
        spec["data"] = dict(kind="excel_processed_series", file=str(workbook), sheet="Sheet1", semantics=semantics)
    if source_spec is not None:
        spec["data"]["notes"] = copy.deepcopy(source_spec.data.notes)
    spec["data"].setdefault("notes", []).append("B processing and exact source/result row mapping: " + str(record))
    mapping_path = destination / "source_result_mapping.json"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(dict(operation=operation, source=copy.deepcopy(data.source) if data else result["provenance"],
                                            input_notes=source_spec.data.notes if source_spec else [], series=mapping),
                                       ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    mapping_ref = dict(file=str(mapping_path), sha256=hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
                       meaning="one-to-one actual supplied source rows to derived standard rows; no row numbers inferred")
    if operation == "icp_molar_ratios":
        mapping_ref["meaning"] = "one-to-one supplied JSON record indices to derived standard rows; original Excel file row numbers are unknown"
    semantics["processing_record"] = dict(source=source_text, method=method, source_result_mapping=mapping_ref)
    if operation == "gcd_na":
        semantics["na_content"]["source_result_mapping"] = mapping_ref
    else:
        for entry in semantics["series_metadata"].values():
            entry["source_result_mapping"] = mapping_ref
    # Optional columns that do not apply to this family must be absent; an
    # existing Element/Branch column promises actual per-row semantic values.
    indices = [index for index, header in enumerate(headers)
               if header not in ("Cycle", "Branch", "Element") or any(row[index] is not None for row in rows)]
    write_standard_xlsx(workbook, [headers[index] for index in indices],
                        [[row[index] for index in indices] for row in rows])
    target = destination / "plot_spec.json"
    target.write_text(json.dumps(spec, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    candidate = PlotSpec.from_dict(spec)
    reread, validation = load_normalized_data(candidate)
    actual = [(item.sample, item.cycle, item.branch, item.points) for item in reread.series] if operation == "gcd_na" else [(item.series_id, item.points) for item in reread.series]
    # Reader points are tuples; normalize sequence representation only.
    if json.loads(json.dumps(actual, ensure_ascii=False)) != json.loads(json.dumps(expected, ensure_ascii=False)):
        raise RuntimeError("B→A readback changed a series, branch, point or order")
    return dict(workbook=str(workbook), plot_spec=str(target), validation=validation.to_dict(),
                pointwise_verified=True, series=len(reread.series), points=sum(len(s.points) for s in reread.series),
                mapping=mapping, plot_type=candidate.plot_type, data_kind=candidate.data.kind)
