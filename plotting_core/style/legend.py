"""Legend semantics: entry lists, grouped sample/metric legend, gradient bar."""

from copy import deepcopy
from typing import Dict, List, Sequence

from .colors import rgb_to_hex
from . import typography


def sample_legend_plan(spec, config, data, sample_colors):
    """Sample-only use of the existing grouped legend geometry and renderer."""
    requested = spec.legend or {}
    position = requested.get("position") or (config.get("legend") or {}).get("position") or "auto"
    rows = [{"label": name, "color": sample_colors[name]} for name in data.sample_order]
    grouped = {"samples": rows, "metrics": []}
    plan = dict(grouped, position=position, corner=auto_corner(data, position),
                size_pt=typography.legend_size_pt(config),
                inset_mm=float(requested.get("inset_mm") or 2.0),
                row_gap_mm=float(requested.get("row_gap_mm") or 0.8),
                swatch_mm=float(requested.get("swatch_mm") or 4.0),
                text_gap_mm=float(requested.get("text_gap_mm") or 1.0),
                group_gap_mm=float(requested.get("group_gap_mm") or 1.4))
    return grouped, plan


def grouped_legend(sample_color_map: Dict[str, str], config: Dict) -> Dict:
    """Separate sample identity from metric marker semantics (no cross product)."""
    rule = ((config.get("plot_type") or {}).get("legend")
            or (config.get("cycle_performance") or {}).get("legend")
            or (config.get("legend") or {}))
    if rule.get("mode") != "grouped":
        raise ValueError("Unsupported legend mode: %r" % rule.get("mode"))
    return dict(
        samples=[dict(label=name, color=color) for name, color in sample_color_map.items()],
        metrics=deepcopy(rule.get("metric_legend", {}).get("entries") or []),
    )


def cycle_gradient_bar_layout(area: Dict[str, float], bar_cfg: Dict) -> Dict[str, float]:
    """Gradient-bar box in millimetres of the plot area (0,0 = its top-left corner).

    The overlay SVG uses exactly this frame, so the bar geometry is independent of
    where the plot area sits on the page.
    """
    x_from = float(bar_cfg.get("x_from_frac", 0.1005))
    x_to = float(bar_cfg.get("x_to_frac", 0.3664))
    top_from_bottom = float(bar_cfg.get("top_frac", 0.9423))
    height_frac = float(bar_cfg.get("height_frac", 0.0221))
    if not 0 <= x_from < x_to <= 1:
        raise ValueError("cycle gradient bar x fractions must satisfy 0 <= from < to <= 1")
    left_mm = x_from * area["width_mm"]
    right_mm = x_to * area["width_mm"]
    top_mm = (1.0 - top_from_bottom) * area["height_mm"]
    height_mm = height_frac * area["height_mm"]
    return {
        "left_mm": left_mm,
        "right_mm": right_mm,
        "top_mm": top_mm,
        "bottom_mm": top_mm + height_mm,
        "height_mm": height_mm,
        "center_x_mm": (left_mm + right_mm) / 2.0,
        "label_gap_mm": float(bar_cfg.get("label_gap_mm", 1.0)),
    }


def sample_color_swatch(color: str) -> Dict[str, str]:
    return {"color": color}


def auto_corner(data, position: str) -> str:
    """Choose the least occupied plot corner when the position is 'auto'."""
    if position not in ("auto", None):
        return str(position)
    corners = ("top_right", "top_left", "bottom_left", "bottom_right")
    counts = {corner: 0 for corner in corners}
    if not data.series:
        return "top_right"
    x_from, x_to = data.data_bounds("x")
    y_from, y_to = data.data_bounds("y")
    if x_to == x_from or y_to == y_from:
        return "top_right"
    for item in data.series:
        for x, y in item.points:
            x_frac = (x - x_from) / (x_to - x_from)
            y_frac = (y - y_from) / (y_to - y_from)
            horizontal = "right" if x_frac >= 0.5 else "left"
            vertical = "top" if y_frac >= 0.5 else "bottom"
            counts["%s_%s" % (vertical, horizontal)] += 1
    return min(corners, key=lambda corner: counts[corner])
