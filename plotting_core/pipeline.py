"""Publication Plot Rendering Pipeline: one stable entry point per figure.

``render_plot(plot_spec)`` runs the fixed order

    validate inputs -> normalise data -> build the plot-type plan
    -> apply the resolved visual style -> draw with the backend
    -> export and verify

so that a new GCD / Cycle Performance task only has to produce a plot spec
(data), never a new plotting script.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from . import plot_types, qa as qa_pkg
from .config import export_settings, load_template, resolve_config, merge
from .export import preview as preview_export
from .export import report as report_export
from .export import validate as validate_export
from .ingest import load_normalized_data
from .models import PlotSpec, RenderingPlan
from .provenance import traceability_summary
from .qa.acceptance import (build_acceptance, capture_artifact_fingerprints,
                            load_image_review)
from .workspace import TaskWorkspace
from . import run_state


@dataclass
class RenderResult:
    """Everything a caller needs to report or to continue working."""

    task_dir: str
    files: Dict[str, str] = field(default_factory=dict)
    plan: Optional[RenderingPlan] = None
    spec_document: Dict = field(default_factory=dict)
    export_report: Dict = field(default_factory=dict)
    backend_info: Dict = field(default_factory=dict)
    data_summary: Dict = field(default_factory=dict)
    validation: Dict = field(default_factory=dict)
    qa: Dict = field(default_factory=dict)
    tmp_dir: Optional[str] = None
    preview: Optional[str] = None
    run_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not (self.export_report or {}).get("issues")

    @property
    def accepted(self) -> bool:
        return bool((self.export_report.get("acceptance") or {}).get("accepted"))


def prepare(spec: PlotSpec):
    """Validate and normalise the input, then build the rendering plan."""
    template = load_template(spec.style_template)
    config = resolve_config(template, spec.plot_type, spec.overrides)
    # backend policy (how the drawing program is driven) comes from the spec, not
    # from the visual template
    config["backend"] = dict(spec.backend or {})
    # Position is shared layout intent; family-specific legend meaning stays in
    # the domain plan. Do not merge arbitrary legend keys into visual config.
    if (spec.legend or {}).get("position"):
        config["legend"] = merge(config.get("legend") or {}, {"position": spec.legend["position"]})
    data, validation = load_normalized_data(spec)
    data.source["scientific_traceability"] = traceability_summary(data)
    plan = plot_types.build_plan(spec, config, data)
    plan.page["data_bounds"] = {"x": list(data.data_bounds("x")),
                                "y": list(data.data_bounds("y"))}
    plan.page["selection"] = spec.selection
    return config, data, validation, plan


def render_plot(spec: PlotSpec, *, workspace_root: Optional[str] = None,
                keep_tmp: bool = False, dry_run: bool = False,
                backend=None, preview: bool = True,
                qa_level: Optional[int] = None) -> RenderResult:
    """Render one figure exactly once, from spec to verified deliverables."""
    workspace = TaskWorkspace(workspace_root or spec.output_root, spec.task_name)
    workspace.prepare()
    attempt = run_state.begin_attempt(workspace, spec, dry_run=dry_run)
    try:
        return _render_plot_attempt(spec, workspace=workspace, attempt=attempt,
                                    keep_tmp=keep_tmp, dry_run=dry_run, backend=backend,
                                    preview=preview, qa_level=qa_level)
    except Exception as exc:
        run_state.fail_attempt(workspace, attempt, exc)
        raise


def _render_plot_attempt(spec, *, workspace, attempt, keep_tmp=False,
                         dry_run=False, backend=None, preview=True, qa_level=None):
    config, data, validation, plan = prepare(spec)
    attempt["input_validation"] = validation.to_dict()
    level = int(qa_level) if qa_level else qa_pkg.resolve_level(spec)
    result = RenderResult(task_dir=str(workspace.task_dir), plan=plan,
                          data_summary=data.summary(),
                          validation=validation.to_dict(),
                          qa=qa_pkg.describe_level(level),
                          tmp_dir=str(workspace.tmp_dir), run_id=attempt["run_id"])
    (workspace.tmp_dir / "plan.json").write_text(
        report_export.dumps(plan.to_dict()), encoding="utf-8")
    if dry_run:
        # No backend, no export: Level 1 and 2 still verify the plan itself.
        result.qa = qa_pkg.build_report(plan=plan, config=config, data=data,
                                        level=min(level, qa_pkg.statistics.LEVEL))
        result.export_report = {"ok": result.qa.get("ok", False),
                                "issues": list(result.qa.get("issues") or []),
                                "qa": result.qa, "origin_executed": False,
                                "input_validation": validation.to_dict()}
        result.export_report["acceptance"] = build_acceptance(
            validation.to_dict(), result.qa, None, result.export_report)
        result.export_report["automatic_checks_passed"] = False
        result.export_report["accepted"] = False
        run_state.complete_attempt(workspace, attempt, result.export_report, "validated_plan")
        if not keep_tmp:
            workspace.clean_tmp()
            result.tmp_dir = None
        return result

    run_state.set_phase(workspace, attempt, "Origin connect/render/save/reopen")
    settings = export_settings(config)
    if backend is None:
        from .backend import OriginBackend
        backend = OriginBackend()
        owns_backend = True
    else:
        owns_backend = False
    try:
        backend.connect()
        run_state.set_phase(workspace, attempt, "Origin connect/render/save/reopen", origin_executed=True)
        project_path = (workspace.task_dir / (spec.task_name + ".opju")).resolve()
        backend_info = backend.render(
            plan, config, workspace.tmp_dir,
            export_svg=True, export_png=True, dpi=int(settings["raster_dpi"]),
            save_project=bool(settings["save_editable_source"]),
            project_path=str(project_path) if settings["save_editable_source"] else None)
        # Level 3 has to read back while the drawing program is still connected.
        pointwise_report = None
        if level >= qa_pkg.pointwise.LEVEL:
            pointwise_report = qa_pkg.pointwise.check(
                plan, lambda index, item: backend.read_series(index, item))
            backend_info["verified"] = {
                "verified_points": pointwise_report["checks"].get("verified_points", 0),
                "verified_series": pointwise_report["checks"].get("verified_series", 0)}
        if settings["save_editable_source"] and hasattr(backend, "verify_project"):
            if spec.verification.get("reopen_project", True):
                contract = backend_info.get("native_axis_contract")
                backend_info["reopened_project"] = (
                    backend.verify_project(str(project_path), plan, config, axis_contract=contract)
                    if contract is not None else backend.verify_project(str(project_path), plan, config))
            if spec.verification.get("editability_probe", False):
                if hasattr(backend, "probe_editability"):
                    backend_info["editability_probe"] = backend.probe_editability(
                        str(project_path), plan, config, workspace.task_dir / "verification")
                else:
                    backend_info["editability_probe"] = {"status": "blocked", "issues": [
                        "The selected backend has no native editability operation probe."]}
    except Exception as exc:
        workspace.write("failure.json", report_export.dumps({
            "stage": "Origin connect/render/save/reopen", "error": str(exc),
            "source": data.source, "backend_log": list(getattr(backend, "log", []) or []),
            "recovery": "Source unchanged. Keep plan/evidence; fix the stated cause and rerun in a new task directory."}))
        raise
    finally:
        if owns_backend:
            backend.disconnect()

    try:
        run_state.set_phase(workspace, attempt, "export/staging/delivery")
        exports = backend_info.get("exports") or {}
        if exports.get("opju"):
            workspace.record("opju", project_path)
        for key, suffix in (("svg", ".svg"), ("png", ".png")):
            if exports.get(key):
                workspace.record(key, workspace.stage(key, exports[key], suffix=suffix))
        files = workspace.files()

        export_report = validate_export.validate_exports(
            {key: value for key, value in files.items() if key in ("svg", "png")},
            config,
            expected_canvas_mm=[config["canvas"]["width"], config["canvas"]["height"]],
            dpi=int(settings["raster_dpi"]),
            # Origin now owns numeric label generation.  The axis formatter verifies
            # native axis state instead of comparing a Python-built label string list.
            expected_tick_labels=None,
            expected_line_width_pt=_expected_line_width(config, plan),
            expected_curve_colors=[item.color for item in plan.data_series if item.color],
            expected_legend_entries=plan.legend.entries if plan.legend.mode == "entries" else None)
        qa_report = qa_pkg.build_report(plan=plan, config=config, data=data, level=level,
                                        export_report=export_report,
                                        backend_info=backend_info,
                                        pointwise_report=pointwise_report
                                        if level >= qa_pkg.pointwise.LEVEL else None)
        export_report["qa"] = qa_report
        reopened = backend_info.get("reopened_project")
        if reopened is not None:
            export_report["reopened_project"] = reopened
            if reopened.get("issues"):
                qa_report["issues"].extend(reopened["issues"])
                qa_report["ok"] = False
        if qa_report["issues"]:
            # QA problems belong to this render, so they are reported next to the
            # export issues; the QA block keeps the detail.
            export_report["issues"] = list(export_report.get("issues") or []) + \
                list(qa_report["issues"])
            export_report["ok"] = False

        if preview and files.get("svg"):
            scale = 1 if settings["raster_dpi"] >= 600 else 2
            size = (int(round(config["canvas"]["width"] / 25.4 * 96 * scale)),
                    int(round(config["canvas"]["height"] / 25.4 * 96 * scale)))
            preview_target = workspace.task_dir / "visual_check.png"
            try:
                preview_info = preview_export.render(
                    files["svg"], str(preview_target), size[0], size[1])
                result.preview = preview_info.get("preview")
                workspace.record("visual_check.png", preview_target)
                backend_info["visual_check"] = (
                    "已渲染 SVG 预览 `visual_check.png`（%d×%d px，按画布等比放大），"
                    "供识图核对裁切、图例遮挡、轴标题与文字；导出内容的量化核对见 export_check.json。"
                    % (size[0], size[1]))
            except Exception as exc:  # preview is evidence, not a gate
                backend_info["visual_check"] = "预览渲染未完成：%s" % exc
            files = workspace.files()   # the preview is part of the delivered artifacts

        document = report_export.effective_spec(spec, config, data, plan, backend_info,
                                                validation.to_dict())
        readme = report_export.write_readme(spec, config, data, plan, backend_info,
                                            validation.to_dict(), export_report, files,
                                            qa_report)
        spec_path = workspace.write("plot_spec.json", report_export.dumps(document))
        readme_path = workspace.write("README.md", readme)
        check_path = workspace.task_dir / "export_check.json"
        # Recorded in the historical order; the inventory written into export_check.json
        # is refreshed after every artifact (including these documents) exists.
        for key, path in (("plot_spec.json", spec_path),
                          ("export_check.json", check_path),
                          ("README.md", readme_path)):
            workspace.record(key, path)

        # Create the report before checking its own existence. A freshly completed
        # render must not carry a stale 'export_check.json does not exist' record.
        workspace.write("export_check.json", report_export.dumps(export_report))
        export_report["delivery"] = workspace.describe()
        missing_core = workspace.missing_core()
        export_report["missing_core_deliverables"] = missing_core
        if missing_core:
            message = "缺少核心交付物：%s" % ", ".join(missing_core)
            export_report["issues"] = list(export_report.get("issues") or []) + [message]
            export_report["ok"] = False
            qa_report = dict(qa_report)
            qa_report["issues"] = list(qa_report.get("issues") or []) + [message]
            qa_report["ok"] = False
            export_report["qa"] = qa_report
        export_report["render_state"] = dict(attempt, status="completed", phase="completed")
        try:
            export_report["artifact_fingerprints"] = capture_artifact_fingerprints(
                workspace.task_dir, workspace.files(), export_report)
        except ValueError as exc:
            export_report["artifact_fingerprints"] = {}
            export_report["artifact_fingerprint_error"] = str(exc)
        acceptance = build_acceptance(validation.to_dict(), qa_report, backend_info, export_report,
                                     load_image_review(workspace.task_dir, workspace.files(), export_report))
        export_report["acceptance"] = acceptance
        export_report["automatic_checks_passed"] = acceptance["automatic_checks_passed"]
        export_report["accepted"] = acceptance["accepted"]
        export_report["editability_probe"] = backend_info.get("editability_probe")
        # Produce the summary only after actual delivery and native checks exist.
        workspace.write("README.md", report_export.write_readme(
            spec, config, data, plan, backend_info, validation.to_dict(), export_report,
            workspace.files(), qa_report))
        report_export.refresh_delivery_metadata(export_report)
        workspace.write("export_check.json",
                        json.dumps(export_report, ensure_ascii=False, indent=2))
        run_state.complete_attempt(workspace, attempt, export_report)
        files = workspace.files()

        result.files = files
        result.backend_info = {key: value for key, value in backend_info.items()
                               if key != "worksheet_transfer"}
        result.spec_document = document
        result.export_report = export_report
        result.qa = qa_report
        if not keep_tmp and result.ok and not ((backend_info.get("editability_probe") or {}).get("ok") is False):
            workspace.clean_tmp()
            result.tmp_dir = None
        return result
    except Exception as exc:
        failure = {"stage": "export/staging/delivery", "error": str(exc), "source": data.source,
                   "backend_log": list(getattr(backend, "log", []) or []),
                   "recovery": "Keep the source and task plan; repair the stated failure and rerun."}
        workspace.write("failure.json", report_export.dumps(failure))
        raise



def _expected_line_width(config: Dict, plan: RenderingPlan):
    """Configured line width of the data curves (GCD uses one shared style)."""
    for item in plan.data_series:
        if item.style and item.style.line_width_pt:
            return float(item.style.line_width_pt)
    return None
