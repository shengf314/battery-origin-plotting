"""Marker display policy for cycle-level series; never thins line data.

The global default is one editable native Origin marker for every validated
point.  Sparse marker display is an explicit opt-in, not an automatic response
to point density.
"""

from typing import Dict, List, Sequence


def marker_plan(points: Sequence, config: Dict) -> Dict[str, List[int]]:
    """Return the full line data and separate zero-based marker display indices."""
    line_points = list(points)
    count = len(line_points)
    rule = ((config.get("plot_type") or {}).get("marker_interval")
            or (config.get("cycle_performance") or {}).get("marker_interval"))
    if not rule or rule.get("enabled") in (None, False):
        return dict(line_points=line_points, marker_indices=list(range(count)))
    if rule.get("scope") not in ("cycle_performance_only", "cycle_level"):
        raise ValueError("Unsupported marker scope; request clarification")
    mode = rule.get("mode") or "all"
    if mode == "all":
        return dict(line_points=line_points, marker_indices=list(range(count)))
    expected = dict(mode="evenly_spaced",
                    strategy="evenly_spaced", apply_to="markers_only",
                    keep_all_line_data=True)
    for key, value in expected.items():
        if rule.get(key) != value:
            raise ValueError("Unsupported marker policy; request clarification")
    target = rule.get("target_visible_points")
    if type(target) is not int or target < 2:
        raise ValueError("Marker target must be a configured integer >= 2")
    visible = min(count, target)
    if count <= target:
        indices = list(range(count))
    else:
        indices = [(i * (count - 1) + (visible - 1) // 2) // (visible - 1)
                   for i in range(visible)]
    return dict(line_points=line_points, marker_indices=indices)
