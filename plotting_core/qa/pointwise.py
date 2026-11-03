"""QA Level 3 - point-by-point readback (opt-in).

The old pipeline always read every point back from Origin and compared it with
the plan; that is the strongest check but it costs a full round trip per series.
It stays available, unchanged in behaviour, and runs only when the plot spec asks
for it (``verification.level: 3``) - for example before submission, after a
complex conversion, or when an anomaly needs to be localised.
"""

from typing import Callable, Dict, List

LEVEL = 3
NAME = "pointwise"


def check(plan, reader: Callable, *, max_report: int = 5) -> Dict:
    """Compare every drawn series with what the drawing program stored.

    ``reader(index, series_spec)`` returns the rows the backend holds for that
    series; the comparison itself stays here, so the backend only has to expose
    the readback mechanism.
    """
    checks: Dict = {"series_checked": 0, "points_checked": 0}
    issues: List[str] = []
    mismatches: List[Dict] = []
    for index, item in enumerate(plan.series):
        if item.role != "data":
            continue
        rows = list(reader(index, item))
        if len(rows) != item.n_points:
            issues.append("series %s: %d rows were stored, %d expected"
                          % (item.series_id, len(rows), item.n_points))
            if len(mismatches) < max_report:
                mismatches.append({"series": item.series_id, "stored": len(rows),
                                   "expected": item.n_points})
            continue
        for row, point in zip(rows, item.points):
            if float(row[0]) != float(point[0]) or float(row[1]) != float(point[1]):
                if len(mismatches) < max_report:
                    mismatches.append({"series": item.series_id,
                                       "stored": [float(row[0]), float(row[1])],
                                       "expected": [float(point[0]), float(point[1])]})
                issues.append("series %s: point mismatch after transfer (%r vs %r)"
                              % (item.series_id, tuple(row), point))
                break
        checks["series_checked"] += 1
        checks["points_checked"] += len(item.points)
    if mismatches:
        checks["mismatches"] = mismatches
    # The delivery documents keep the historical key names for this level.
    checks["verified_points"] = checks["points_checked"]
    checks["verified_series"] = checks["series_checked"]
    return {"level": LEVEL, "name": NAME, "checks": checks, "issues": issues,
            "ok": not issues}
