"""Independent B command: explicit plans, owned Origin processing and A bridge."""

import argparse
import json
import sys
from pathlib import Path

from .domains.processing.orchestrator import (OPERATIONS, execute_request, preflight,
                                              read_object, record_cli_failure, _write_json)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "preflight", "execute"))
    parser.add_argument("--request", required=True, help="Absolute B request JSON, schema_version=1")
    parser.add_argument("--output", help="Absolute plan/preflight report JSON")
    parser.add_argument("--output-root", help="Independent absolute task directory for execute attempts")
    parser.add_argument("--confirmation", help="Existing scientific confirmation with exact reviewed_request_sha256")
    parser.add_argument("--render", action="store_true", help="After saved B verification, call existing A render; image review remains separate")
    args = parser.parse_args(argv)
    if args.command == "execute":
        if not args.output_root or args.output:
            parser.error("execute requires --output-root and does not accept --output")
    else:
        if not args.output or args.output_root or args.render or args.confirmation:
            parser.error("plan/preflight requires --output JSON and does not launch Origin")
        destination = Path(args.output)
        if not destination.is_absolute() or destination.suffix.lower() != ".json":
            parser.error("--output must be an absolute JSON report path")
        skill_root = Path(__file__).resolve().parents[1]
        if skill_root in destination.resolve().parents:
            parser.error("Audit output must be outside the skill")
        if destination.resolve() == Path(args.request).resolve():
            parser.error("--output cannot overwrite the request")
    request = None
    try:
        request = read_object(args.request)
        if args.command == "execute":
            confirmation = read_object(args.confirmation) if args.confirmation else None
            outcome = execute_request(request, confirmation, args.output_root, render=args.render)
        else:
            source_spec = (request.get("input") or {}).get("plot_spec")
            protected = [args.request, source_spec]
            if source_spec:
                protected.append(read_object(source_spec).get("data", {}).get("file"))
            skill_root = Path(__file__).resolve().parents[1]
            if destination.resolve() == skill_root or skill_root in destination.resolve().parents:
                parser.error("Audit output must be outside the skill")
            if any(value and destination.resolve() == Path(value).resolve() for value in protected):
                parser.error("--output cannot overwrite the request, PlotSpec or source")
            outcome = preflight(request)[0]
            _write_json(destination, outcome)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        outcome = dict(ready=False, stage="blocked", questions=[], errors=[str(exc)],
                       origin_executed=False, plotted=False, processing_accepted=False)
        if args.command == "execute":
            try:
                outcome = record_cli_failure(args.output_root, exc, args.request)
            except (ValueError, OSError) as report_error:
                outcome["errors"].append("Failure report not written: " + str(report_error))
        else:
            _write_json(destination, outcome)
    fields = ("ready", "stage", "operation", "request_sha256", "processing_accepted", "task_dir", "questions", "errors")
    print(json.dumps({key: outcome.get(key) for key in fields}, ensure_ascii=False, indent=2))
    return 0 if outcome.get("ready") else 2


if __name__ == "__main__":
    sys.exit(main())
