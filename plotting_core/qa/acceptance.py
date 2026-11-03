"""Evidence-based acceptance, separate from the historical render ``ok``.

The five required stages are deliberately conservative: an absent check is not
a passing check.  Image approval is a persisted review of actual deliverables,
bound to their SHA256 digests, rather than a boolean in a plot specification.
This module performs no rendering and never connects to Origin.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


SCHEMA_VERSION = 1
STAGES = ("input", "data", "native_structure", "editability", "image")
STATUSES = ("pass", "fail", "not_run", "blocked")
REVIEW_FILENAME = "image_review.json"
ARTIFACT_KEYS = ("opju", "svg", "png")


def _stage(status, method, evidence=None, reasons=None):
    return {"status": status, "required": True, "method": method,
            "evidence": evidence or {}, "reasons": list(reasons or [])}


def _messages(value):
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)] if value else []


def _dict(value):
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return value if isinstance(value, dict) else {}


def build_acceptance(validation, qa_report, backend_info, export_report,
                     image_review=None):
    """Combine executed checks into the five required acceptance stages.

    ``image_review`` must be the verified stage returned by
    :func:`load_image_review`; raw spec declarations are never sufficient.
    Automatic QA may pass while image/editability acceptance remains pending.
    """
    validation = _dict(validation)
    qa_report = _dict(qa_report)
    backend_info = _dict(backend_info)
    export_report = _dict(export_report)
    stages = {}
    errors = _messages(validation.get("errors"))
    questions = _messages(validation.get("questions"))
    input_evidence = {key: validation[key] for key in
                      ("source", "header_map", "counts", "applied_mappings", "warnings")
                      if key in validation}
    if errors:
        stages["input"] = _stage("fail", "input_contract", input_evidence, errors + questions)
    elif questions:
        stages["input"] = _stage("blocked", "input_contract", input_evidence, questions)
    elif "errors" in validation and "questions" in validation:
        stages["input"] = _stage("pass", "input_contract", input_evidence)
    else:
        stages["input"] = _stage("not_run", "input_contract", reasons=[
            "No executed input-validation report is available."])

    checks = _dict(qa_report.get("checks"))
    qa_issues = _messages(qa_report.get("issues"))
    levels_run = qa_report.get("levels_run") or []
    data_evidence = {key: checks[key] for key in
                     ("series_planned", "series_normalized", "points_planned",
                      "points_normalized", "points_per_series_planned",
                      "points_per_series_normalized", "series_with_differing_summary",
                      "worksheet_rows_transferred", "verified_points", "verified_series")
                     if key in checks}
    reopened = _dict(backend_info.get("reopened_project") or
                     export_report.get("reopened_project"))
    native_data = reopened.get("series") or []
    if native_data:
        data_evidence["reopened_series"] = native_data
    has_native_data = bool(backend_info.get("worksheet_transfer") or native_data or
                           "worksheet_rows_transferred" in checks or
                           checks.get("verified_points"))
    exact_native_data = (bool(native_data) and all(
        isinstance(item, dict) and item.get("points_equal") is True and
        isinstance(item.get("point_count"), int) and item["point_count"] > 0
        for item in native_data))
    mismatched_native_data = [item for item in native_data
                              if isinstance(item, dict) and item.get("points_equal") is False]
    if mismatched_native_data:
        stages["data"] = _stage("fail", "saved_project_exact_data_readback", data_evidence,
                                 ["Reopened native series differ from the supplied data."])
    elif exact_native_data:
        stages["data"] = _stage("pass", "saved_project_exact_data_readback", data_evidence)
    elif any(level in levels_run for level in (2, 3)):
        if qa_issues or qa_report.get("ok") is False:
            stages["data"] = _stage("fail", "statistics_or_pointwise_readback",
                                     data_evidence, qa_issues or ["The data QA report failed."])
        elif qa_report.get("ok") is True and data_evidence and has_native_data:
            stages["data"] = _stage("pass", "statistics_or_pointwise_readback", data_evidence)
        else:
            stages["data"] = _stage("not_run", "statistics_or_pointwise_readback",
                                     data_evidence, ["Native data verification was not evidenced."])
    else:
        stages["data"] = _stage("not_run", "statistics_or_pointwise_readback", reasons=[
            "Statistics or pointwise data QA was not executed."])

    native_issues = _messages(reopened.get("issues"))
    native_method = reopened.get("method") or "saved_project_reopen_and_native_bindings"
    native_evidence = {key: reopened[key] for key in
                       ("opened_path", "native_plot_count", "series", "native_axis", "native_legend")
                       if key in reopened}
    if native_issues or reopened.get("ok") is False:
        stages["native_structure"] = _stage("fail", native_method, native_evidence,
                                             native_issues or ["Saved-project verification failed."])
    elif (reopened.get("ok") is True and exact_native_data and
          reopened.get("native_plot_count") == len(native_data) and
          reopened.get("opened_path") and reopened.get("native_axis") and
          all(item.get("x_range") and item.get("y_range") for item in native_data)):
        stages["native_structure"] = _stage("pass", native_method, native_evidence)
    else:
        stages["native_structure"] = _stage("not_run", native_method, native_evidence, [
            "The saved native graph and bindings were not verified by reopening the project."])

    probe = _dict(backend_info.get("editability_probe"))
    probe_issues = _messages(probe.get("issues"))
    probe_evidence = {key: value for key, value in probe.items()
                      if key not in ("ok", "issues", "method", "status")}
    probe_method = probe.get("method") or "reversible_native_editability_probe"
    if probe.get("status") == "blocked":
        stages["editability"] = _stage("blocked", probe_method, probe_evidence,
                                        _messages(probe.get("reasons")) or probe_issues or
                                        ["The probe was blocked."])
    elif probe.get("status") == "not_run":
        stages["editability"] = _stage("not_run", probe_method, probe_evidence,
                                        _messages(probe.get("reasons")) or ["The probe was not executed."])
    elif probe_issues or probe.get("ok") is False:
        stages["editability"] = _stage("fail", probe_method, probe_evidence,
                                        probe_issues or ["The native editability probe failed."])
    elif probe.get("ok") is True and probe.get("evidence") and probe.get("operations"):
        stages["editability"] = _stage("pass", probe_method, probe_evidence)
    else:
        stages["editability"] = _stage("not_run", probe_method, probe_evidence, [
            "A native binding alone does not prove editability; the operation probe was not executed."])

    image_review = _dict(image_review)
    if image_review.get("validated") is True and image_review.get("status") in STATUSES:
        stages["image"] = _stage(image_review["status"], image_review.get("method") or
                                  "artifact_bound_visual_review", image_review.get("evidence"),
                                  image_review.get("reasons"))
    else:
        stages["image"] = _stage("not_run", "artifact_bound_visual_review", reasons=[
            "No validated review of the actual PNG/SVG deliverables is available."])

    if stages["input"]["status"] in ("fail", "blocked"):
        for name in STAGES[1:]:
            if stages[name]["status"] == "not_run":
                stages[name]["status"] = "blocked"
                stages[name]["reasons"].append("Input validation did not pass.")
    elif stages["native_structure"]["status"] == "fail" and stages["editability"]["status"] == "not_run":
        stages["editability"]["status"] = "blocked"
        stages["editability"]["reasons"].append("Saved-project verification did not pass.")

    artifact_binding = _verify_render_artifacts(export_report)
    if artifact_binding["status"] == "blocked":
        for name in ("data", "native_structure", "editability"):
            previous = stages[name]["status"]
            stages[name]["status"] = "blocked"
            stages[name]["evidence"]["previous_status"] = previous
            stages[name]["reasons"].extend(artifact_binding["reasons"])

    render_state = _dict(export_report.get("render_state"))
    if render_state.get("status") in ("running", "failed"):
        reason = ("The current render is %s; previous automatic checks and image reviews "
                  "cannot accept this run. Complete a successful rerender first." %
                  render_state["status"])
        for name in ("data", "native_structure", "editability", "image"):
            stages[name]["evidence"]["previous_status"] = stages[name]["status"]
            stages[name]["evidence"]["render_state"] = render_state
            stages[name]["status"] = "blocked"
            stages[name]["reasons"].append(reason)

    export_files = _dict(export_report.get("files"))
    delivery = _dict(export_report.get("delivery"))
    export_evidenced = all(export_files.get(key) is True for key in ("svg", "png"))
    missing_delivery = [key for key, info in delivery.items()
                        if isinstance(info, dict) and info.get("exists") is not True]
    automatic = (all(stages[name]["status"] == "pass" for name in
                     ("input", "data", "native_structure")) and
                 qa_report.get("ok") is True and not qa_issues and
                 export_report.get("ok") is True and not export_report.get("issues") and
                 export_evidenced and not missing_delivery and
                 not export_report.get("missing_core_deliverables") and
                 artifact_binding["status"] != "blocked" and
                 stages["editability"]["status"] not in ("fail", "blocked"))
    return {"schema_version": SCHEMA_VERSION, "required_stages": list(STAGES),
            "stages": stages, "artifact_binding": artifact_binding, "render_state": render_state,
            "automatic_checks_passed": bool(automatic),
            "accepted": bool(automatic and all(stages[name]["status"] == "pass"
                                               for name in STAGES) and
                             artifact_binding["status"] == "pass")}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path):
    result = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object: %s" % path)
    return result


def _contained_path(task_dir, value):
    target = Path(value)
    if not target.is_absolute():
        in_task = task_dir / target
        # CLI paths may be task-relative (figure.png) or cwd-relative
        # (tasks/example/figure.png); both still have to resolve inside the task.
        target = in_task if in_task.exists() else target.resolve()
    target = target.resolve()
    try:
        target.relative_to(task_dir)
    except ValueError:
        raise ValueError("Review artifacts must be inside the task directory: %s" % target)
    return target


def _artifact_paths(task_dir, artifacts=None, export_report=None):
    artifacts = artifacts or {}
    delivery = _dict((export_report or {}).get("delivery"))
    paths = {}
    for key in ARTIFACT_KEYS:
        value = artifacts.get(key) or _dict(delivery.get(key)).get("path")
        if value:
            target = _contained_path(task_dir, value)
        else:
            matches = list(task_dir.glob("*." + key))
            if key == "png":
                matches = [path for path in matches if path.name != "visual_check.png"]
            if len(matches) != 1:
                raise ValueError("Exactly one delivered %s artifact must be identified." % key.upper())
            target = matches[0].resolve()
        if target.suffix.lower() != "." + key or not target.is_file():
            raise ValueError("Delivered %s artifact is missing or has the wrong suffix: %s" %
                             (key.upper(), target))
        paths[key] = target
    return paths


def _fingerprint(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ValueError("Artifact changed while hashing: %s" % path)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": after.st_size}


def capture_artifact_fingerprints(task_dir, artifacts=None, export_report=None):
    """Bind one completed render's automatic evidence to actual OPJU/SVG/PNG.

    The returned dictionary belongs in ``export_report.artifact_fingerprints``.
    Capturing digests does not itself verify native structures or image quality.
    """
    task_dir = Path(task_dir).resolve()
    paths = _artifact_paths(task_dir, artifacts, export_report)
    return {key: _fingerprint(path) for key, path in paths.items()}


def _verify_render_artifacts(export_report):
    method = "render_artifact_sha256"
    if "artifact_fingerprints" not in export_report:
        result = _stage("not_run", method, reasons=[
            "This legacy report has no render artifact fingerprints; rerender before complete acceptance."])
        result["required"] = True
        return result
    expected = _dict(export_report.get("artifact_fingerprints"))
    actual = {}
    reasons = []
    delivery = _dict(export_report.get("delivery"))
    for key in ARTIFACT_KEYS:
        recorded = _dict(expected.get(key))
        value = recorded.get("path")
        if not value or not recorded.get("sha256") or "bytes" not in recorded:
            reasons.append("Render evidence binding is missing for %s; rerender to verify current artifacts." % key.upper())
            continue
        try:
            path = Path(value)
        except (TypeError, ValueError):
            reasons.append("Render evidence path is invalid for %s; rerender to verify current artifacts." % key.upper())
            continue
        delivered_path = _dict(delivery.get(key)).get("path")
        if (not path.is_absolute() or path.suffix.lower() != "." + key or
                (delivered_path and Path(delivered_path).resolve() != path.resolve())):
            reasons.append("Render evidence path binding differs for %s; rerender to verify current artifacts." % key.upper())
            continue
        try:
            if not path.is_file():
                raise ValueError("artifact is missing")
            measured = _fingerprint(path)
            actual[key] = measured
            if measured["sha256"] != recorded["sha256"] or measured["bytes"] != recorded["bytes"]:
                raise ValueError("artifact content changed")
        except (OSError, ValueError) as exc:
            reasons.append("Render evidence for %s is stale (%s); rerender before reusing automatic checks." %
                           (key.upper(), exc))
    return _stage("blocked" if reasons else "pass", method,
                  {"recorded": expected, "current": actual}, reasons)


def _image_file(path):
    if path.suffix.lower() == ".png":
        with path.open("rb") as handle:
            if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("Image evidence is not a PNG file: %s" % path)
    elif path.suffix.lower() == ".svg":
        try:
            root = ElementTree.parse(str(path)).getroot()
        except (ElementTree.ParseError, OSError) as exc:
            raise ValueError("Image evidence is not a readable SVG: %s" % exc)
        if root.tag.split("}")[-1] != "svg":
            raise ValueError("Image evidence has no SVG root: %s" % path)
    else:
        raise ValueError("Image review evidence must be an actual PNG or SVG file.")


def load_image_review(task_dir, artifacts=None, export_report=None):
    """Load and verify a review against all current OPJU/SVG/PNG artifacts.

    Returns an image acceptance stage with ``validated=True``.  Missing reviews
    are ``not_run``; malformed, invalidated or stale reviews are ``blocked``.
    """
    task_dir = Path(task_dir).resolve()
    review_path = task_dir / REVIEW_FILENAME
    evidence = {"review_file": str(review_path)}
    result = _stage("not_run", "artifact_bound_visual_review", evidence,
                    ["No image review has been recorded for this task."])
    result["validated"] = True
    if not review_path.is_file():
        return result
    try:
        review = _read_json(review_path)
        if review.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported image review schema.")
        if review.get("invalidated"):
            raise ValueError("Image review was invalidated: %s" %
                             _dict(review["invalidated"]).get("reason", "new render"))
        if review.get("status") not in ("pass", "fail"):
            raise ValueError("Image review status must be pass or fail.")
        if not str(review.get("reviewer") or "").strip() or not str(review.get("note") or "").strip():
            raise ValueError("An image review must identify its reviewer and observations.")
        current = _artifact_paths(task_dir, artifacts, export_report)
        recorded = _dict(review.get("artifacts"))
        fingerprints = {}
        for key in ARTIFACT_KEYS:
            fingerprint = _fingerprint(current[key])
            fingerprints[key] = fingerprint
            expected = _dict(recorded.get(key))
            if (expected.get("path") != fingerprint["path"] or
                    expected.get("sha256") != fingerprint["sha256"] or
                    expected.get("bytes") != fingerprint["bytes"]):
                raise ValueError("Image review is stale: %s artifact changed or its binding is missing." % key.upper())
        reviewed_images = review.get("evidence")
        if not isinstance(reviewed_images, list) or not reviewed_images:
            raise ValueError("Image review has no actual PNG/SVG evidence.")
        for item in reviewed_images:
            item = _dict(item)
            image_path = _contained_path(task_dir, item.get("path") or "")
            if not image_path.is_file():
                raise ValueError("Reviewed image evidence is missing: %s" % image_path)
            _image_file(image_path)
            actual = _fingerprint(image_path)
            if item.get("sha256") != actual["sha256"] or item.get("bytes") != actual["bytes"]:
                raise ValueError("Image review is stale: reviewed PNG/SVG evidence changed.")
        evidence.update({"reviewer": review["reviewer"], "note": review["note"],
                         "reviewed_at": review.get("reviewed_at"),
                         "artifacts": fingerprints, "images": reviewed_images})
        result = _stage(review["status"], "artifact_bound_visual_review", evidence,
                        [review["note"]] if review["status"] == "fail" else [])
    except (ValueError, OSError, TypeError) as exc:
        result = _stage("blocked", "artifact_bound_visual_review", evidence, [str(exc)])
    result["validated"] = True
    return result


def write_image_review(task_dir, status, note, reviewer, evidence,
                       artifacts=None, export_report=None):
    """Record observations after the human/agent has inspected actual images.

    ``evidence`` is one path or a sequence of PNG/SVG paths within the task.
    The command records the review; it does not inspect visual quality for the
    caller, edit an image, or open/change the Origin project.
    """
    task_dir = Path(task_dir).resolve()
    if not task_dir.is_dir():
        raise FileNotFoundError("Task directory does not exist: %s" % task_dir)
    if status not in ("pass", "fail"):
        raise ValueError("Image review status must be pass or fail.")
    note, reviewer = str(note or "").strip(), str(reviewer or "").strip()
    if not note or not reviewer:
        raise ValueError("Image review requires a nonempty note and reviewer.")
    image_paths = evidence if isinstance(evidence, (list, tuple)) else [evidence]
    if not image_paths:
        raise ValueError("Image review requires actual PNG/SVG evidence.")
    images = []
    for value in image_paths:
        path = _contained_path(task_dir, value)
        if not path.is_file():
            raise FileNotFoundError("Image review evidence does not exist: %s" % path)
        _image_file(path)
        images.append(_fingerprint(path))
    paths = _artifact_paths(task_dir, artifacts, export_report)
    review = {"schema_version": SCHEMA_VERSION, "status": status,
              "reviewer": reviewer, "note": note, "reviewed_at": _utc_now(),
              "artifacts": {key: _fingerprint(path) for key, path in paths.items()},
              "evidence": images}
    (task_dir / REVIEW_FILENAME).write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    result = load_image_review(task_dir, artifacts, export_report)
    if result["status"] == "blocked":
        raise ValueError("The recorded image review could not be verified: %s" %
                         "; ".join(result["reasons"]))
    return result


def invalidate_image_review(task_dir, reason="render restarted"):
    """Preserve old observations while invalidating them before every rerender."""
    review_path = Path(task_dir) / REVIEW_FILENAME
    if not review_path.is_file():
        return
    try:
        review = _read_json(review_path)
    except (ValueError, OSError):
        # A malformed old review already cannot pass verification.
        return
    review["invalidated"] = {"reason": str(reason), "at": _utc_now()}
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["ARTIFACT_KEYS", "REVIEW_FILENAME", "SCHEMA_VERSION", "STAGES", "STATUSES",
           "build_acceptance", "capture_artifact_fingerprints", "invalidate_image_review", "load_image_review",
           "write_image_review"]
