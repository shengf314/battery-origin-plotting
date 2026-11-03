"""Explicit B processing orchestration; algorithms remain in their domain APIs.

preflight does not launch Origin. execute_request owns an independent session,
verifies saved columns and exports existing A contracts without new data.kind.
"""

import copy
import dataclasses
import hashlib
import json
from pathlib import Path
import datetime
import uuid
from ...models import PlotSpec

DEFAULT_SKILL = str(Path(__file__).resolve().parents[3])
OPERATIONS = ("gcd_na", "xrd_normalization", "icp_molar_ratios")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def absolute_file(value, context):
    if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_file():
        raise ValueError(context + " must be an existing absolute file path")
    return Path(value)


def read_object(path):
    result = json.loads(absolute_file(str(path), "JSON input").read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError("JSON input must be an object")
    return result


def import_apis(skill_root=None):
    # Package-relative imports keep staging and installed runs isolated.
    from ...models import PlotSpec
    from ...ingest import load_normalized_data, InputContractError
    from ..electrochemistry.gcd.na_workflow import preflight_gcd_na, convert_gcd_na
    from .origin_analysis import build_xrd_normalization_plan
    from ..chemistry.icp_calculation import calculate_icp_ratios
    return dict(PlotSpec=PlotSpec, load=load_normalized_data, InputContractError=InputContractError,
                na_preflight=preflight_gcd_na, na_convert=convert_gcd_na,
                xrd=build_xrd_normalization_plan, icp=calculate_icp_ratios)


def preflight(request, skill_root=DEFAULT_SKILL):
    """Return auditable readiness; Origin operations stop at their native plan.

    ICP's existing API combines validation and arithmetic. It is invoked here,
    but candidate ratios are not published until calculate. This fact is explicit
    in executed_stages rather than pretending it was validation only.
    """
    apis = import_apis(skill_root)
    outcome = dict(ready=False, stage="blocked", origin_executed=False, plotted=False,
                   operation=request.get("operation") if isinstance(request, dict) else None,
                   questions=[], errors=[], executed_stages=[], result=None,
                   scientific_truth_verified=False)
    data = None
    calculation = None
    try:
        if not isinstance(request, dict):
            raise ValueError("processing request must be an object")
        extra = set(request) - {"schema_version", "operation", "input", "settings", "source"}
        if extra:
            raise ValueError("Unsupported request fields: " + ", ".join(sorted(extra)))
        if isinstance(request.get("schema_version"), bool) or request.get("schema_version") != 1:
            raise ValueError("schema_version=1 is required")
        operation = request.get("operation")
        if operation not in OPERATIONS:
            raise ValueError("Choose an explicit supported operation: " + ", ".join(OPERATIONS))
        source = request.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must record this task's scientific input/method provenance")
        inputs, settings = request.get("input"), request.get("settings")
        if not isinstance(inputs, dict) or not isinstance(settings, dict):
            raise ValueError("input and settings must be explicit objects")
        audit = {}
        if operation != "icp_molar_ratios":
            if set(inputs) != {"plot_spec"}:
                raise ValueError("This operation reuses the existing PlotSpec: input must contain only plot_spec")
            spec_path = absolute_file(inputs["plot_spec"], "input.plot_spec")
            spec_document = read_object(spec_path)
            absolute_file((spec_document.get("data") or {}).get("file"), "PlotSpec data.file")
            spec = apis["PlotSpec"].from_file(str(spec_path))
            required_family = "xrd" if operation == "xrd_normalization" else "gcd"
            if spec.plot_type != required_family:
                raise ValueError("This operation requires the existing %s PlotSpec" % required_family)
            data, validation = apis["load"](spec)
            outcome["input_validation"] = validation.to_dict()
            outcome["input_summary"] = data.summary()
            audit = dict(plot_spec_path=str(spec_path), plot_spec_sha256=file_hash(spec_path),
                         data_file=data.source.get("resolved_file"), data_sha256=data.source.get("sha256"))
            outcome["executed_stages"].append("existing_readonly_plot_input")
        else:
            if set(inputs) not in ({"records"}, {"table"}):
                raise ValueError("ICP input must contain records or explicit mapped table; no instrument parser is provided")
            extra = set(settings) - {"denominator", "element_map", "replicate_design"}
            if extra:
                raise ValueError("Unsupported ICP settings: " + ", ".join(sorted(extra)))
        outcome["request_sha256"] = digest(dict(request=request, input_audit=audit))
        outcome["input_audit"] = audit
        if operation == "gcd_na":
            extra = set(settings) - {"output", "samples", "per_series"}
            if extra:
                raise ValueError("Unsupported Na settings: " + ", ".join(sorted(extra)))
            dry = apis["na_preflight"](data, settings)
            outcome["native_preflight"] = dry
            outcome["ready"] = dry["ready"]
            outcome["questions"] = dry["report"]["questions"]
            outcome["errors"] = dry["report"]["errors"]
            outcome["executed_stages"].append("formula_mass_and_na_reference_preflight")
        elif operation == "xrd_normalization":
            plan = apis["xrd"](data, settings)
            outcome["native_plan"] = plan
            outcome["ready"] = True
            outcome["executed_stages"].append("native_origin_processing_plan")
            outcome["remaining_stages"] = ["Origin execute in independent session", "save processing OPJU",
                                            "reopen and verify raw/result native columns", "standard plotting input", "render and full QA"]
        else:
            calculation = apis["icp"](inputs.get("records", inputs.get("table")),
                                      denominator=settings.get("denominator"),
                                      element_map=settings.get("element_map"),
                                      replicate_design=settings.get("replicate_design"),
                                      source={"record": source})
            outcome["ready"] = calculation["ready"]
            outcome["native_preflight"] = {key: copy.deepcopy(calculation[key]) for key in
                                            ("ready", "report", "normalized_results", "scientific_truth_verified")}
            outcome["questions"] = calculation["report"]["questions"]
            outcome["errors"] = calculation["report"]["errors"]
            outcome["executed_stages"].append("existing_icp_validation_and_candidate_arithmetic")
            outcome["candidate_values_published"] = False
        outcome["stage"] = "ready_for_scientific_review" if outcome["ready"] else "blocked"
    except apis["InputContractError"] as exc:
        report = exc.report.to_dict() if exc.report is not None else {}
        outcome["native_preflight"] = {"report": report}
        outcome["questions"] = report.get("questions", [])
        outcome["errors"] = report.get("errors", [])
        if not outcome["questions"] and not outcome["errors"]:
            outcome["errors"].append(str(exc))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        outcome["errors"].append(str(exc))
    return outcome, data, calculation



def _confirmed(outcome, confirmation):
    return (isinstance(confirmation, dict) and confirmation.get("user_approved") is True
            and isinstance(confirmation.get("evidence"), str) and bool(confirmation["evidence"].strip())
            and confirmation.get("reviewed_request_sha256") == outcome.get("request_sha256"))


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(str(path))


def record_cli_failure(output_root, error, request_path):
    """Record an unreadable invocation without reviving an older accepted result."""
    root = _processing_destination(output_root, {})
    if root == Path(request_path).resolve().parent:
        raise ValueError("A CLI failure report must not be written in the request/source directory")
    attempt_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
    directory = root / "attempts" / attempt_id
    outcome = dict(ready=False, stage="blocked", processing_accepted=False, origin_executed=False, plotted=False,
                   attempt_id=attempt_id, task_dir=str(directory), questions=[], errors=[str(error)],
                   request_path=str(request_path), scientific_truth_verified=False)
    _write_json(directory / "processing_check.json", outcome)
    _write_json(root / "current_processing.json", dict(attempt_id=attempt_id, stage="blocked", ready=False,
                processing_accepted=False, report=str(directory / "processing_check.json")))
    return outcome


def _processing_destination(output_root, request):
    root = Path(output_root)
    if not root.is_absolute():
        raise ValueError("Processing output_root must be an absolute task directory")
    resolved = root.resolve()
    skill = Path(__file__).resolve().parents[3]
    if resolved == skill or skill in resolved.parents:
        raise ValueError("Processing artifacts must not be written inside the skill")
    source = (request.get("input") or {}).get("plot_spec")
    protected = []
    if source:
        protected.append(Path(source).resolve())
        document = read_object(source)
        protected.append(Path(document["data"]["file"]).resolve())
    if any(resolved == item or item.parent == resolved for item in protected):
        raise ValueError("Use an independent task output directory, not the source directory")
    return resolved


def _column_snapshot(backend, book, counts):
    """Read real native values and unit/source metadata for every populated column."""
    sheet = backend.app.FindWorksheet("[%s]Sheet1" % book)
    entries = []
    for number, count in sorted(counts.items()):
        column = sheet.Columns(number - 1)
        backend.run("range processingVerifyC=[%s]Sheet1!col(%d); processingVerifyN=processingVerifyC.GetSize();" % (book, number))
        if int(backend.value("processingVerifyN")) != count:
            raise RuntimeError("Native processing column %d point count changed" % number)
        values = backend.app.GetWorksheet("[%s]Sheet1" % book, 0, number - 1, count - 1, number - 1)
        if len(values) != count:
            raise RuntimeError("Native processing column %d lost a row" % number)
        entries.append(dict(column=number, rows=count, long_name=str(column.LongName or ""),
                            unit=str(column.Units or ""), source=str(column.Comments or ""),
                            designation=int(column.Type), values=[list(row) for row in values]))
    return dict(book=book, worksheet="Sheet1", columns=entries)


def verify_processing_snapshot(expected, actual):
    """Strict saved-column comparison, independent of any graph backend state."""
    issues = []
    if actual.get("book") != expected.get("book") or actual.get("worksheet") != expected.get("worksheet"):
        issues.append("saved processing workbook identity changed")
    previous, current = expected.get("columns", []), actual.get("columns", [])
    if len(previous) != len(current):
        issues.append("saved populated-column count changed")
    for before, after in zip(previous, current):
        for key in ("column", "rows", "long_name", "unit", "source", "designation", "values"):
            if before.get(key) != after.get(key):
                issues.append("saved processing column %s changed %s" % (before.get("column"), key))
    return dict(ok=not issues, issues=issues, populated_columns=len(current),
                native_values_verified=not issues, units_and_source_verified=not issues)


def _put_calculation(backend, request, data, result, record):
    """Na/ICP arithmetic is Python; store supplied raw values separately in Origin."""
    import re
    backend.run("newbook;")
    book = backend.text("%H")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", book):
        raise RuntimeError("Unsafe Origin workbook short name")
    columns = []
    if request["operation"] == "gcd_na":
        for raw, converted in zip(data.series, result.series):
            for stage, series in (("raw_input", raw), ("calculated_result", converted)):
                for index, axis in enumerate(("x", "y")):
                    semantics = (series.metadata.get(axis) or (result.source if stage == "calculated_result" else data.source).get("semantics", {}).get(axis) or {})
                    unit = semantics.get("unit")
                    if unit is None:
                        capacity = (index == 0) == (data.source.get("axis_binding", "capacity_voltage") == "capacity_voltage")
                        unit = "mAh g-1" if capacity else "V"
                    columns.append(dict(name=stage + "_" + axis, unit=unit, designation=3 if index == 0 else 0,
                                        values=[point[index] for point in series.points],
                                        source=dict(record=record, operation="gcd_na", stage=stage, series_id=series.series_id,
                                            input_source=copy.deepcopy(data.source), metadata=copy.deepcopy(series.metadata))))
    else:
        # Keep each original record as its own native concentration column so
        # mixed concentration units never masquerade as one common unit.
        ratios = {(row["sample"], row["replicate"], row["element"]): row for row in result["ratios"]}
        for raw in result["normalized_results"]:
            ratio = ratios[(raw["sample"], raw["replicate"], raw["element"])]
            raw_record = result["provenance"]["original_input"]
            details = dict(record=record, operation="icp_molar_ratios", source_record=copy.deepcopy(raw_record),
                           normalized_record=raw, calculated_ratio=ratio, provenance=result["provenance"])
            columns.append(dict(name="raw_concentration_" + raw["element"], unit=raw["input_unit"], designation=0,
                                values=[raw["concentration"]], source=dict(details, stage="raw_input")))
            columns.append(dict(name="element_molar_ratio_" + raw["element"], unit="1", designation=0,
                                values=[ratio["value"]], source=dict(details, stage="calculated_result")))
    backend.run("wks.ncols=%d;" % len(columns))
    sheet = backend.app.FindWorksheet("[%s]Sheet1" % book)
    counts = {}
    for index, item in enumerate(columns):
        backend.app.PutWorksheet("[%s]Sheet1" % book, [[value] for value in item["values"]], 0, index)
        column = sheet.Columns(index)
        column.LongName, column.Units, column.Type = item["name"], item["unit"], item["designation"]
        column.Comments = json.dumps(item["source"], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        actual = backend.app.GetWorksheet("[%s]Sheet1" % book, 0, index, len(item["values"]) - 1, index)
        if [list(row) for row in actual] != [[value] for value in item["values"]]:
            raise RuntimeError("Native calculation workbook transfer changed a supplied/result value")
        counts[index + 1] = len(item["values"])
    return book, counts


def _save_reopen(backend, factory, project, book, counts, expected, directory):
    backend.app.Save(str(project))
    if not project.is_file() or project.stat().st_size == 0:
        raise RuntimeError("Origin did not save the processing project")
    backend.disconnect()
    reopened = factory()
    try:
        reopened.connect()
        if not reopened.app.Load(str(project)):
            raise RuntimeError("Saved processing OPJU could not be reopened")
        actual = _column_snapshot(reopened, book, counts)
        _write_json(directory / "saved_columns.json", actual)
        verification = verify_processing_snapshot(expected, actual)
        _write_json(directory / "saved_columns_check.json", verification)
        if not verification["ok"]:
            raise RuntimeError("Saved processing column verification failed: " + "; ".join(verification["issues"]))
        verification.update(project=str(project), project_sha256=file_hash(project))
        return verification
    finally:
        reopened.disconnect()


def execute_request(request, confirmation, output_root, *, render=False, backend_factory=None):
    """Execute exactly confirmed B settings; optionally call the unchanged A pipeline.

    Each attempt has a separate directory. current_processing.json always points
    to the latest attempt, including failures, without overwriting older results.
    Processing acceptance never substitutes for A image/editability acceptance.
    """
    root = _processing_destination(output_root, request)
    attempt_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
    directory = root / "attempts" / attempt_id
    directory.mkdir(parents=True, exist_ok=False)
    outcome = dict(ready=False, stage="preflight", attempt_id=attempt_id, task_dir=str(directory),
                   operation=request.get("operation"), origin_executed=False, plotted=False,
                   processing_accepted=False, scientific_truth_verified=False, questions=[], errors=[])
    backend = None
    _write_json(directory / "request.json", request)
    _write_json(directory / "confirmation.json", confirmation)
    try:
        pre, data, icp = preflight(request)
        outcome.update(pre)
        _write_json(directory / "preflight.json", pre)
        if not pre["ready"]:
            return outcome
        if not _confirmed(pre, confirmation):
            outcome.update(ready=False, stage="blocked")
            outcome["questions"].append("Record already given scientific confirmation for this exact request_sha256; no prior task references or scientific parameters are inferred")
            return outcome
        operation = request["operation"]
        source_spec = PlotSpec.from_file(request["input"]["plot_spec"]) if operation != "icp_molar_ratios" else None
        if operation == "gcd_na":
            result = import_apis()["na_convert"](data, request["settings"],
                dict(user_approved=True, evidence=confirmation["evidence"], reviewed_input_sha256=pre["native_preflight"]["input_sha256"]))
        elif operation == "icp_molar_ratios":
            result = icp
            if result.get("replicate_summary"):
                outcome.update(ready=False, stage="blocked")
                outcome["errors"].append("B calculates replicate statistics, but this end-to-end A bridge does not implement error bars; no uncertainty will be silently omitted")
                return outcome
        else:
            result = None
        from ...backend.origin import OriginBackend
        from .origin_analysis import execute as origin_execute
        from .standard_export import export_result
        factory = backend_factory or OriginBackend
        outcome["stage"] = "origin_processing"
        backend = factory()
        backend.connect()
        outcome["origin_session_started"] = True
        outcome["origin_execution_attempted"] = True
        if result is None:
            result = origin_execute(backend, pre["native_plan"], authorized=True)
            book = result["book"]
            counts = {}
            for index, item in enumerate(pre["native_plan"]["series"]):
                for offset in range(4):
                    counts[index * 4 + offset + 1] = len(item["points"])
            serializable = result
        else:
            book, counts = _put_calculation(backend, request, data, result, str(directory / "processing_result.json"))
            serializable = dataclasses.asdict(result) if operation == "gcd_na" else result
        outcome["origin_executed"] = True
        expected = _column_snapshot(backend, book, counts)
        _write_json(directory / "before_save_columns.json", expected)
        _write_json(directory / "processing_result.json", serializable)
        project = directory / "processing.opju"
        outcome["stage"] = "processing_saved_readback"
        outcome["processing_verification"] = _save_reopen(backend, factory, project, book, counts, expected, directory)
        for field in ("plot_spec_path", "data_file"):
            path = pre.get("input_audit", {}).get(field)
            expected_hash = pre.get("input_audit", {}).get("plot_spec_sha256" if field == "plot_spec_path" else "data_sha256")
            if path and file_hash(path) != expected_hash:
                raise RuntimeError("Source changed during processing: " + path)
        outcome["stage"] = "standard_export"
        bridge = export_result(operation, result, data, source_spec, request, directory, str(directory / "processing_result.json"))
        outcome.update(bridge=bridge, ready=True, processing_accepted=True, stage="processed_and_standard_input_verified",
                       confirmation=copy.deepcopy(confirmation), result_file=str(directory / "processing_result.json"))
        if render:
            from ...pipeline import render_plot
            rendered = render_plot(PlotSpec.from_file(bridge["plot_spec"]), qa_level=3)
            outcome.update(plotted=True, stage="processed_and_rendered", render=dict(task_dir=rendered.task_dir,
                           accepted=rendered.accepted, ok=rendered.ok, files=rendered.files,
                           acceptance=rendered.export_report.get("acceptance")))
        outcome["remaining_stages"] = (["A Origin render", "saved native graph/editability/image acceptance"] if not render
                                       else ["A image inspection and hash-bound review", "user scientific/visual review as applicable"])
        return outcome
    except Exception as exc:
        outcome.update(ready=False, stage="failed", processing_accepted=False, exception_type=type(exc).__name__)
        outcome.setdefault("errors", []).append(str(exc))
        return outcome
    finally:
        if backend is not None:
            if getattr(backend, "log", None):
                _write_json(directory / "origin_commands.json", backend.log)
            if outcome["stage"] == "failed" and getattr(backend, "app", None) is not None:
                try:
                    failed_project = directory / "processing_failed.opju"
                    backend.app.Save(str(failed_project))
                    if failed_project.is_file():
                        outcome["failed_native_project"] = str(failed_project)
                except Exception as save_error:
                    outcome["failure_preservation_error"] = str(save_error)
            backend.disconnect()
        _write_json(directory / "processing_check.json", outcome)
        _write_json(root / "current_processing.json", dict(attempt_id=attempt_id, stage=outcome["stage"],
                    processing_accepted=outcome["processing_accepted"], ready=outcome["ready"],
                    report=str(directory / "processing_check.json")))
