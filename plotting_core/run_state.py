"""One persisted attempt per render, including failures before Origin exists.

Prior documents are archived before a retry. Existing OPJU/PNG/SVG artifacts
remain untouched by preflight: their existence cannot pass the current attempt.
"""

import json
import os
import shutil
from datetime import datetime, timezone
from uuid import uuid4

from .qa.acceptance import build_acceptance, invalidate_image_review


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write(path, document):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(temporary), str(path))


def begin_attempt(workspace, spec, dry_run=False):
    """Archive previous evidence and invalidate acceptance before ``prepare``."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:12]
    archive = workspace.task_dir / "verification" / "previous_runs" / run_id
    archived = []
    for name in ("export_check.json", "image_review.json", "plot_spec.json",
                 "README.md", "failure.json", "run_state.json"):
        source = workspace.task_dir / name
        if source.is_file():
            archive.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(archive / name))
            archived.append(name)
    old_failure = workspace.task_dir / "failure.json"
    if old_failure.is_file():
        old_failure.unlink()  # exact file already archived; never a recursive delete
    state = {"schema_version": 1, "run_id": run_id, "task_name": spec.task_name,
             "mode": "dry_run" if dry_run else "render", "status": "running",
             "phase": "spec/input/plan", "started_at": _now(),
             "origin_executed": False, "archived_documents": archived,
             "archive_path": str(archive) if archived else None}
    workspace.start_attempt(run_id)
    # Older review observations survive in the archive, never as this run's proof.
    invalidate_image_review(workspace.task_dir, "new render attempt %s started before preflight" % run_id)
    report = {"ok": False, "issues": [], "accepted": False,
              "automatic_checks_passed": False, "render_state": dict(state)}
    report["acceptance"] = build_acceptance(None, None, None, report)
    save_attempt(workspace, state, report)
    return state


def save_attempt(workspace, state, report=None):
    state["updated_at"] = _now()
    _write(workspace.task_dir / "run_state.json", state)
    history = workspace.task_dir / "verification" / "runs"
    history.mkdir(parents=True, exist_ok=True)
    _write(history / (state["run_id"] + ".json"), state)
    if report is None:
        try:
            candidate = json.loads((workspace.task_dir / "export_check.json").read_text(encoding="utf-8-sig"))
            if (candidate.get("render_state") or {}).get("run_id") == state["run_id"]:
                report = candidate
        except (ValueError, OSError, AttributeError):
            pass
    if report is not None:
        report["render_state"] = dict(state)
        if report.get("acceptance"):
            report["acceptance"]["render_state"] = dict(state)
        from .export.report import refresh_delivery_metadata, update_readme_acceptance
        update_readme_acceptance(workspace.task_dir, report["acceptance"], render_state=state)
        refresh_delivery_metadata(report)
        _write(workspace.task_dir / "export_check.json", report)


def set_phase(workspace, state, phase, origin_executed=None):
    state["phase"] = phase
    if origin_executed is not None:
        state["origin_executed"] = bool(origin_executed)
    save_attempt(workspace, state)


def fail_attempt(workspace, state, exc):
    """Persist current failure without importing any previous automatic checks."""
    state.update(status="failed", completed_at=_now(),
                 error={"type": type(exc).__name__, "message": str(exc)})
    validation = state.get("input_validation")
    if getattr(exc, "report", None) is not None:
        validation = exc.report.to_dict()
    elif state["phase"] == "spec/input/plan":
        validation = {"errors": [str(exc)], "questions": []}
    report = {"ok": False, "issues": [str(exc)], "accepted": False,
              "automatic_checks_passed": False, "render_state": dict(state),
              "input_validation": validation or {}}
    report["acceptance"] = build_acceptance(validation, None, None, report)
    # Preserve useful backend failure details written by the pipeline, when any.
    failure_path = workspace.task_dir / "failure.json"
    failure = {}
    if failure_path.is_file():
        try:
            failure = json.loads(failure_path.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError):
            pass
    if not isinstance(failure, dict):
        failure = {}
    failure.update(run_id=state["run_id"], stage=state["phase"],
                   error=str(exc), error_type=type(exc).__name__,
                   recovery="Current attempt failed. Prior reports are archived; existing artifacts are not current acceptance evidence.")
    _write(failure_path, failure)
    save_attempt(workspace, state, report)


def complete_attempt(workspace, state, report, phase="completed"):
    state.update(status="completed", phase=phase, completed_at=_now())
    save_attempt(workspace, state, report)
