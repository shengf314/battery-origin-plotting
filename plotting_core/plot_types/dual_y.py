"""Reusable native single-layer double-Y capability.

This module owns the structural contract shared by any future double-Y family:
one Origin layer, independent Y/Y2 scales, native axis-title objects and a
per-plot left/right Y binding.  It deliberately contains no domain labels,
metric names, colours or marker rules.
"""

from typing import Dict, Iterable

from ..models import LayerPlan, SeriesSpec
from ..style import axes as axis_style

CAPABILITY = "native_dual_y"
MODE = "single_layer_native_y2"


def enabled(config: Dict) -> bool:
    """Whether the resolved template explicitly enabled this capability."""
    structure = (config.get("dual_y") or {}).get("structure") or {}
    return (CAPABILITY in (config.get("capabilities") or []) and
            structure.get("mode") == MODE and
            bool(structure.get("single_layer")) and
            bool(structure.get("native_y2")) and
            bool(structure.get("independent_scale")))


def require(config: Dict) -> None:
    if not enabled(config):
        raise ValueError("native_dual_y capability is not enabled by the resolved template")


def axes(config: Dict, titles: Dict[str, str]) -> Dict:
    """Return physical native axes; titles are domain data supplied by callers."""
    require(config)
    return {
        "bottom": axis_style.build_axis("bottom", config, label=titles.get("x")),
        "left": axis_style.build_axis("left", config, label=titles.get("left_y")),
        "right": axis_style.build_axis("right", config, label=titles.get("right_y")),
        "top": axis_style.build_axis("top", config, label=None),
    }


def layer(config: Dict, series: Iterable[SeriesSpec], titles: Dict[str, str]) -> LayerPlan:
    """Build the single Layer that owns both Y and Y2 scales."""
    return LayerPlan(index=0, series_ids=[item.series_id for item in series],
                     axes=axes(config, titles))


def bind(series: SeriesSpec, side: str) -> SeriesSpec:
    """Attach a logical series to a native Y side without choosing its semantics."""
    if side not in ("left", "right"):
        raise ValueError("dual-Y side must be 'left' or 'right', got %r" % side)
    series.layer = 0
    series.y_axis = side
    return series


def page_state(config: Dict) -> Dict:
    """Backend-readable, domain-neutral declaration of the chosen topology."""
    require(config)
    return {"axis_capability": CAPABILITY, "axis_mode": MODE,
            "single_layer": True, "native_y2": True,
            "independent_y_scales": True}
