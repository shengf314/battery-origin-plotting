"""Graded post-render QA.

===========================  ==========================================
Level                        Cost and content
===========================  ==========================================
1 - structure                default; plan integrity plus the measured
                             export checks (vector, white background,
                             600 dpi, canvas size, tick labels, colours)
2 - statistics               default for a normal task; series and point
                             counts, first/last, min/max, data range,
                             transferred row counts, axis coverage
3 - pointwise                opt-in; every point read back from the
                             drawing program and compared with the plan
===========================  ==========================================

The level comes from the plot spec (``verification.level``) and defaults to 2.
Level 3 keeps the original exhaustive comparison; it is no longer paid for by
every task, and nothing was removed: levels are additive.
"""

from typing import Any, Dict, List, Optional

from .. import registry
from . import pointwise, statistics, structure

DEFAULT_LEVEL = 2
MAX_LEVEL = 3
LEVELS = {structure.LEVEL: structure.NAME,
          statistics.LEVEL: statistics.NAME,
          pointwise.LEVEL: pointwise.NAME}

_ALIASES = {"1": 1, "level1": 1, "level_1": 1, "structure": 1,
            "2": 2, "level2": 2, "level_2": 2, "statistics": 2,
            "3": 3, "level3": 3, "level_3": 3, "pointwise": 3}


def resolve_level(spec: Any) -> int:
    """QA level of one task: ``verification.level``, defaulting to Level 2."""
    verification = getattr(spec, "verification", None) or {}
    raw = verification.get("level")
    if raw is None:
        return DEFAULT_LEVEL
    if isinstance(raw, bool):
        raise ValueError("verification.level must be 1, 2 or 3")
    if isinstance(raw, int):
        level = raw
    else:
        key = str(raw).strip().lower().replace(" ", "")
        if key not in _ALIASES:
            raise ValueError("verification.level must be 1, 2 or 3, got %r" % raw)
        level = _ALIASES[key]
    if not 1 <= level <= MAX_LEVEL:
        raise ValueError("verification.level must be 1, 2 or 3, got %r" % raw)
    return level


def describe_level(level: int) -> Dict[str, Any]:
    return {"level": int(level), "name": LEVELS[int(level)],
            "pointwise": int(level) >= pointwise.LEVEL}


def family_check(plan, data, config: Dict,
                 backend_info: Optional[Dict] = None) -> Optional[Dict]:
    """Run the plot type's own checks, when it declares them.

    A family may implement ``qa_checks(plan, data, config, backend_info)`` in its
    plan module and return ``{"checks": {...}, "issues": [...]}``.  This is how a
    new figure family adds the checks that only it can express (which layers carry
    which metric, which colour rule holds, which rate stage is expected) without
    touching the generic levels.  A hook that raises is reported as an issue: QA
    never silently passes.
    """
    hook = getattr(registry.plan_module(plan.plot_type), "qa_checks", None)
    name = "family:%s" % plan.plot_type
    if hook is None:
        return None
    try:
        result = hook(plan, data, config, backend_info) or {}
    except Exception as exc:  # a broken hook must not look like a passing check
        return {"level": statistics.LEVEL, "name": name, "checks": {},
                "issues": ["图族 %s 的 QA 钩子执行失败：%s" % (plan.plot_type, exc)],
                "ok": False}
    issues = [str(item) for item in (result.get("issues") or [])]
    return {"level": statistics.LEVEL, "name": name,
            "checks": dict(result.get("checks") or {}), "issues": issues,
            "ok": not issues}


def build_report(*, plan, config: Dict, data, level: int,
                 export_report: Optional[Dict] = None,
                 backend_info: Optional[Dict] = None,
                 pointwise_report: Optional[Dict] = None) -> Dict:
    """Run the checks the requested level implies and merge them into one report."""
    level = int(level)
    if not 1 <= level <= MAX_LEVEL:
        raise ValueError("QA level must be 1, 2 or 3, got %r" % level)
    reports = [structure.check(plan, config, export_report)]
    if level >= statistics.LEVEL:
        reports.append(statistics.check(plan, data, backend_info))
        own = family_check(plan, data, config, backend_info)
        if own is not None:
            reports.append(own)
    if level >= pointwise.LEVEL:
        reports.append(pointwise_report or {
            "level": pointwise.LEVEL, "name": pointwise.NAME, "checks": {},
            "issues": ["the point-by-point check was requested but not executed"],
            "ok": False})

    checks: Dict[str, Any] = {}
    issues = []
    levels_run: List[int] = []
    for report in reports:
        if report["level"] not in levels_run:
            levels_run.append(report["level"])
        for key, value in (report.get("checks") or {}).items():
            if key in checks:
                key = "%s_%s" % (report["name"], key)
            checks[key] = value
        issues.extend(report.get("issues") or [])
    return {
        "level": level,
        "level_name": LEVELS[level],
        "levels_run": sorted(levels_run),
        "pointwise": level >= pointwise.LEVEL,
        "checks": checks,
        "issues": issues,
        "ok": not issues,
    }


__all__ = ["DEFAULT_LEVEL", "LEVELS", "MAX_LEVEL", "build_report",
           "describe_level", "pointwise", "resolve_level", "statistics",
           "structure"]
