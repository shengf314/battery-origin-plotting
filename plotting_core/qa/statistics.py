"""QA Level 2 - data statistics (default level for a normal task).

What is compared, without reading Excel or Origin twice:

* series count and total point count against the validated input data
* per-series point counts, first/last point and min/max (bounds)
* overall X/Y range
* the row counts Origin reported when the worksheet was transferred
* the axis ranges Origin resolved, against the data extent

This catches truncation, reordering, dropped series and rescaled axes without
paying for a point-by-point readback.  Level 3 does the exhaustive comparison.
"""

from typing import Dict, List, Optional

LEVEL = 2
NAME = "statistics"


def check(plan, data, backend_info: Optional[Dict] = None) -> Dict:
    """Run the statistics checks and return a JSON-serialisable report."""
    checks: Dict = {}
    issues: List[str] = []
    planned = plan.data_series
    normalized = list(getattr(data, "series", []) or [])

    checks["series_planned"] = len(planned)
    checks["series_normalized"] = len(normalized)
    if len(planned) != len(normalized):
        issues.append("the plan draws %d series but the validated data holds %d"
                      % (len(planned), len(normalized)))

    planned_points = [item.n_points for item in planned]
    normalized_points = [len(item.points) for item in normalized]
    checks["points_planned"] = sum(planned_points)
    checks["points_normalized"] = sum(normalized_points)
    if sum(planned_points) != sum(normalized_points):
        issues.append("the plan carries %d points, the validated data holds %d"
                      % (sum(planned_points), sum(normalized_points)))
    checks["points_per_series_planned"] = planned_points
    checks["points_per_series_normalized"] = normalized_points
    if sorted(planned_points) != sorted(normalized_points):
        issues.append("the per-series point counts differ from the validated data")

    match, how = _pair_series(planned, normalized)
    checks["per_series_matching"] = how
    mismatched: List[Dict] = []
    for planned_series, source in match:
        bounds_planned = planned_series.bounds()
        bounds_source = source.bounds()
        if bounds_planned != bounds_source:
            mismatched.append({"series": planned_series.series_id,
                               "planned_bounds": bounds_planned,
                               "source_bounds": bounds_source})
        if planned_series.points and source.points:
            if planned_series.points[0] != source.points[0] or \
                    planned_series.points[-1] != source.points[-1]:
                mismatched.append({"series": planned_series.series_id,
                                   "planned_ends": [planned_series.points[0],
                                                    planned_series.points[-1]],
                                   "source_ends": [source.points[0], source.points[-1]]})
    checks["series_with_differing_summary"] = len(mismatched)
    if mismatched:
        issues.append("%d series differ from the validated data in bounds or first/last "
                      "point" % len(mismatched))
        checks["differences"] = mismatched[:5]

    if planned:
        xs = [point[0] for item in planned for point in item.points]
        ys = [point[1] for item in planned for point in item.points]
        checks["x_range"] = [min(xs), max(xs)]
        checks["y_range"] = [min(ys), max(ys)]

    if backend_info:
        issues.extend(_check_backend(plan, checks, backend_info))

    return {"level": LEVEL, "name": NAME, "checks": checks, "issues": issues,
            "ok": not issues}


def _pair_series(planned, normalized):
    """Pair planned series with their source series (by id, else by order)."""
    by_id = {}
    for item in normalized:
        by_id[getattr(item, "series_id", None)] = item
    if planned and all(item.series_id in by_id for item in planned):
        return [(item, by_id[item.series_id]) for item in planned], "series_id"
    if len(planned) == len(normalized):
        return list(zip(planned, normalized)), "order"
    return [], "unmatched"


def _check_backend(plan, checks: Dict, backend_info: Dict) -> List[str]:
    issues: List[str] = []
    transfer = backend_info.get("worksheet_transfer") or []
    if transfer:
        transferred = {row.get("series"): row.get("points") for row in transfer}
        checks["worksheet_rows_transferred"] = sum(transferred.values())
        for item in plan.series:
            if item.role != "data":
                continue
            if item.series_id in transferred and transferred[item.series_id] != item.n_points:
                issues.append("series %s: the worksheet holds %d rows, %d expected"
                              % (item.series_id, transferred[item.series_id], item.n_points))

    ranges = backend_info.get("axis_ranges") or {}
    for layer_index in {item.layer for item in plan.data_series}:
        native_ranges = ranges.get("left" if layer_index == 0 else "right") or {}
        for side in ("left", "right"):
            series = [item for item in plan.data_series if item.layer == layer_index and item.y_axis == side]
            if not series:
                continue
            for axis, value_index in (("x", 0), ("y2" if side == "right" else "y", 1)):
                if axis not in native_ranges:
                    continue
                low, high = sorted(native_ranges[axis])
                vals = [p[value_index] for s in series for p in s.points]
                if min(vals) < low - 1e-9 or max(vals) > high + 1e-9:
                    issues.append("native layer %d %s %s scale does not cover its bound data" %
                                  (layer_index, side, axis))
    bounds = plan.page.get("layer_bounds") or {}
    for layer_key, layer_bounds in bounds.items():
        axis_ranges = ranges.get(layer_key)
        if not layer_bounds or not axis_ranges:
            continue
        checks["axis_ranges_%s" % layer_key] = {
            key: list(value) for key, value in axis_ranges.items()}
        for axis in ("x", "y"):
            low, high = axis_ranges.get(axis, [None, None])
            data_low, data_high = layer_bounds.get(axis) or [None, None]
            if None in (low, high, data_low, data_high):
                continue
            low, high = sorted((low, high))
            if data_low < low - 1e-9 or data_high > high + 1e-9:
                issues.append("layer %r %s axis range %s does not contain the data "
                              "extent %s" % (layer_key, axis, [low, high],
                                             [data_low, data_high]))
    return issues
