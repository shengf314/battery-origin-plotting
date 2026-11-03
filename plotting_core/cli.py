"""Command line entry point of the rendering pipeline.

    python -X utf8 -m plotting_core.cli render --spec plot_spec.json [--keep-tmp]
    python -X utf8 -m plotting_core.cli check  --spec plot_spec.json
    python -X utf8 -m plotting_core.cli review --task-dir TASK --status pass \
        --reviewer NAME --note OBSERVATIONS --evidence TASK/figure.png

``render`` is the stable entry: a task writes a plot spec (data), never a plot script.
"""

import argparse
import json
import sys
from pathlib import Path

from . import qa as qa_pkg
from .ingest.report import InputContractError
from .models import PlotSpec
from .pipeline import prepare, render_plot
from .export.report import refresh_delivery_metadata, update_readme_acceptance
from .qa.acceptance import build_acceptance, load_image_review, write_image_review


def _load(path: str) -> PlotSpec:
    return PlotSpec.from_file(path)


def cmd_check(args) -> int:
    spec = _load(args.spec)
    config, data, validation, plan = prepare(spec)
    acceptance = build_acceptance(validation.to_dict(), None, None, None)
    print(json.dumps({"ok": True, "stage": "validated_plan", "origin_executed": False,
                      "executed_stages": ["input", "plan"],
                      "automatic_checks_passed": acceptance["automatic_checks_passed"],
                      "accepted": acceptance["accepted"], "acceptance": acceptance,
                      "qa_status": "requested_level_not_executed", "data": data.summary(),
                      "plan": plan.to_dict(),
                      "validation": validation.to_dict(),
                      "qa": qa_pkg.describe_level(qa_pkg.resolve_level(spec))},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_render(args) -> int:
    spec = _load(args.spec)
    result = render_plot(spec, workspace_root=args.output_root, keep_tmp=args.keep_tmp,
                         dry_run=args.dry_run, preview=not args.no_preview,
                         qa_level=args.qa_level)
    acceptance = getattr(result, "acceptance", None) or (result.export_report or {}).get("acceptance")
    if not acceptance:
        image_review = load_image_review(result.task_dir, result.files, result.export_report)
        acceptance = build_acceptance(result.validation, result.qa, result.backend_info,
                                      result.export_report, image_review)
    summary = {
        "ok": result.ok,
        "operation_status": "validated_plan" if args.dry_run else "render_completed",
        "origin_executed": not args.dry_run,
        "run_id": result.run_id,
        "render_state": (result.export_report or {}).get("render_state"),
        "automatic_checks_passed": acceptance["automatic_checks_passed"],
        "accepted": acceptance["accepted"],
        "acceptance": acceptance,
        "task_dir": result.task_dir,
        "files": result.files,
        "data": result.data_summary,
        "qa": {"level": result.qa.get("level"), "name": result.qa.get("level_name"),
               "issues": result.qa.get("issues", [])},
        "export_issues": (result.export_report or {}).get("issues", []),
        "preview": result.preview,
        "tmp_dir": result.tmp_dir,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if not result.ok:
        return 1
    return 3 if getattr(args, "require_accepted", False) and not acceptance["accepted"] else 0


def _load_json_object(path):
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError("Expected a JSON object: %s" % path)
    return document


# Kept for callers of the original CLI helper; implementation is shared with
# render retry/failure paths so their persisted summaries cannot disagree.
_update_readme_acceptance = update_readme_acceptance


def cmd_review(args) -> int:
    """Persist an actual visual review, with no Origin or scientific-data edits."""
    task_dir = Path(args.task_dir).resolve()
    check_path = task_dir / "export_check.json"
    document_path = task_dir / "plot_spec.json"
    export_report = _load_json_object(check_path)
    document = _load_json_object(document_path)
    state = export_report.get("render_state") or {}
    if state.get("status") in ("running", "failed") or state.get("mode") == "dry_run":
        raise ValueError("The current attempt has no successfully completed Origin render; "
                         "rerender before recording an image review. Prior artifacts cannot accept this attempt.")
    refresh_delivery_metadata(export_report)
    image_review = write_image_review(task_dir, args.status, args.note, args.reviewer,
                                      args.evidence, export_report=export_report)
    acceptance = build_acceptance(document.get("input_validation"), export_report.get("qa"),
                                  document.get("backend"), export_report, image_review)
    export_report["image_review"] = image_review
    export_report["acceptance"] = acceptance
    export_report["automatic_checks_passed"] = acceptance["automatic_checks_passed"]
    export_report["accepted"] = acceptance["accepted"]
    _update_readme_acceptance(task_dir, acceptance)
    # Keep delivery metadata consistent after the review summary changed size.
    delivery = export_report.get("delivery") or {}
    refresh_delivery_metadata(export_report)
    check_path.write_text(json.dumps(export_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "stage": "image_review_recorded", "origin_executed": False,
                      "task_dir": str(task_dir), "review_status": image_review["status"],
                      "automatic_checks_passed": acceptance["automatic_checks_passed"],
                      "accepted": acceptance["accepted"], "acceptance": acceptance},
                     ensure_ascii=False, indent=2))
    return 3 if getattr(args, "require_accepted", False) and not acceptance["accepted"] else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="plotting_core",
                                     description="Publication Plot Rendering Pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="validate the input and build the plan")
    check.add_argument("--spec", required=True)
    check.set_defaults(func=cmd_check)
    render = subparsers.add_parser("render", help="render, export and verify")
    render.add_argument("--spec", required=True)
    render.add_argument("--output-root", default=None,
                        help="覆盖 plot spec 的 output_root；相对路径按当次工作目录解析，"
                             "作为全局 skill 使用时建议给绝对路径")
    render.add_argument("--keep-tmp", action="store_true",
                        help="keep .tmp for inspection (debugging)")
    render.add_argument("--dry-run", action="store_true")
    render.add_argument("--no-preview", action="store_true")
    render.add_argument("--qa-level", type=int, choices=(1, 2, 3), default=None,
                        help="override the QA level of the plot spec "
                             "(default: verification.level, else 2)")
    render.add_argument("--require-accepted", action="store_true",
                        help="严格交付：只有五项完整验收 accepted=true 才退出 0；"
                             "自动检查无问题但完整验收未完成时退出 3。默认保留原退出码。")
    render.set_defaults(func=cmd_render)
    review = subparsers.add_parser("review", help="record an actual PNG/SVG visual review")
    review.add_argument("--task-dir", required=True)
    review.add_argument("--status", choices=("pass", "fail"), required=True)
    review.add_argument("--note", required=True, help="observations from the actual image inspection")
    review.add_argument("--reviewer", required=True, help="human or agent that inspected the evidence")
    review.add_argument("--evidence", action="append", required=True,
                        help="actual PNG/SVG within the task directory; may be repeated")
    review.add_argument("--require-accepted", action="store_true",
                        help="图像审阅记录后完整验收仍未通过时退出 3（默认保留退出 0）。")
    review.set_defaults(func=cmd_review)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except InputContractError as exc:
        print(str(exc), file=sys.stderr)
        if exc.report is not None:
            report = exc.report.to_dict()
            report["acceptance"] = build_acceptance(report, None, None, None)
            report["automatic_checks_passed"] = False
            report["accepted"] = False
            print(json.dumps(report, ensure_ascii=False, indent=2),
                  file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        # Registry/spec validation precedes the table contract. Present those
        # failures as actionable input errors rather than an uncaught traceback.
        if args.command == "review":
            stage = "image_review"
            acceptance = build_acceptance(None, None, None, None, {
                "validated": True, "status": "blocked", "method": "artifact_bound_visual_review",
                "evidence": {"task_dir": args.task_dir}, "reasons": [str(exc)]})
        else:
            stage = "spec/input/plan"
            acceptance = build_acceptance({"errors": [str(exc)], "questions": []}, None, None, None)
        print(json.dumps({"ok": False, "error": str(exc), "stage": stage,
                          "automatic_checks_passed": False, "accepted": False,
                          "acceptance": acceptance},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        # render_plot already persists the failed attempt; present COM/export
        # failures as machine-readable runtime errors, preserving exit code 1.
        print(json.dumps({"ok": False, "error": str(exc),
                          "error_type": type(exc).__name__, "stage": "runtime",
                          "automatic_checks_passed": False, "accepted": False},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
