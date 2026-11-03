"""Axis construction: shared settings plus plot-type overrides."""

from typing import Dict, Optional

from ..config import resolve_axes as _resolve_axes
from ..models import AxisSpec


def resolve_axes(config: Dict, family: str) -> Dict:
    """Compatibility facade: merge shared ``axes`` with ``<family>.axes_override``."""
    return _resolve_axes(config, family)


def build_axis(key: str, config: Dict, *, label: Optional[str] = None,
               ticks=None, tick_labels=None) -> AxisSpec:
    """Create an AxisSpec from the resolved style configuration."""
    axes_cfg = config.get("axes") or {}
    labels_cfg = config.get("labels") or {}
    show_axis = {
        "bottom": axes_cfg.get("show_bottom_axis", True),
        "left": axes_cfg.get("show_left_axis", True),
        "top": axes_cfg.get("show_top_axis", True),
        "right": axes_cfg.get("show_right_axis", True),
    }[key]
    show_ticks = {
        "bottom": axes_cfg.get("show_bottom_ticks", True),
        "left": axes_cfg.get("show_left_ticks", True),
        "top": axes_cfg.get("show_top_ticks", False),
        "right": axes_cfg.get("show_right_ticks", False),
    }[key]
    show_labels = {
        "bottom": axes_cfg.get("show_bottom_tick_labels", True),
        "left": axes_cfg.get("show_left_tick_labels", True),
        "top": axes_cfg.get("show_top_tick_labels", False),
        "right": axes_cfg.get("show_right_tick_labels", False),
    }[key]
    return AxisSpec(
        key=key,
        label=label,
        ticks=list(ticks) if ticks else None,
        tick_labels=list(tick_labels) if tick_labels else None,
        show_axis=bool(show_axis),
        show_ticks=bool(show_ticks),
        show_tick_labels=bool(show_labels),
        tick_direction=axes_cfg.get("tick_direction"),
        tick_length_pt=axes_cfg.get("tick_length"),
        thickness_pt=axes_cfg.get("axis_line_width"),
        color=axes_cfg.get("axis_color") or axes_cfg.get("color"),
    )
