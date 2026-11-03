"""Shared construction helpers for the plot types."""

from typing import Dict, List, Optional
import math

from ..models import SeriesSpec, SeriesStyle


def plot_type_block(config: Dict) -> Dict:
    return config.get("plot_type") or {}


def axis_label(config: Dict, variant: Optional[str], axis: str,
               overrides: Dict[str, str], fallback: Optional[str] = None) -> Optional[str]:
    """Axis title: template string, plus an explicit spec override."""
    block = plot_type_block(config)
    key = None
    if variant and isinstance(block.get(variant), dict):
        key = block[variant].get("%s_axis_label" % axis)
    if key is None:
        key = block.get("%s_axis_label" % axis)
    if axis in overrides:
        return overrides[axis]
    return key if key is not None else fallback


def general_series_style(config: Dict) -> SeriesStyle:
    """Style for a plot type that uses one shared line style (GCD)."""
    general = plot_type_block(config).get("general") or {}
    return SeriesStyle(
        line_width_pt=curve_line_width_pt(config, general.get("line_width")),
        line_style=general.get("line_style"),
        symbol_shape=general.get("symbol_shape") or "none",
        symbol_size_pt=general.get("symbol_size"),
        symbol_fill=general.get("symbol_fill"),
        symbol_edge_width_pt=general.get("symbol_edge_width"))


def metric_series_style(config: Dict, metric: str) -> SeriesStyle:
    block = plot_type_block(config).get(metric) or {}
    return SeriesStyle(
        line_width_pt=curve_line_width_pt(config, block.get("line_width")),
        line_style=block.get("line_style"),
        symbol_shape=block.get("symbol_shape"),
        symbol_size_pt=block.get("symbol_size"),
        symbol_fill=block.get("symbol_fill"),
        symbol_edge_width_pt=block.get("symbol_edge_width"))


def curve_line_width_pt(config: Dict, explicit=None) -> Optional[float]:
    """Resolve a native scientific curve width; axes have independent settings.

    Existing plot-specific styles retain precedence. Supplied XY adapters also
    use this shared default instead of inheriting an unverified Origin width.
    An absent setting preserves old custom-template behavior.
    """
    value = explicit if explicit is not None else (config.get("curves") or {}).get("line_width")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("scientific curve line_width must be a positive finite pt value")
    return float(value)


def legend_entry_series(series: List[SeriesSpec], excluded: List[str]) -> List[SeriesSpec]:
    return [item for item in series if item.legend_entry and item.series_id not in excluded]


def axis_ranges_from_template(config: Dict, variant: Optional[str]) -> Dict[str, Optional[float]]:
    """Explicit axis ranges from the template (null means Origin auto-scaling)."""
    block = plot_type_block(config)
    scope = block.get(variant) if variant and isinstance(block.get(variant), dict) else block
    scope = scope or {}
    return {
        "x_from": scope.get("x_axis_range", [None, None])[0] if scope.get("x_axis_range") else None,
        "x_to": scope.get("x_axis_range", [None, None])[1] if scope.get("x_axis_range") else None,
        "y_from": scope.get("y_axis_range", [None, None])[0] if scope.get("y_axis_range") else None,
        "y_to": scope.get("y_axis_range", [None, None])[1] if scope.get("y_axis_range") else None,
    }


def line_overlay(config: Dict, series: List[SeriesSpec],
                 layer_keys: Dict[int, str]) -> List[Dict]:
    """Return no overlay curves.

    The Origin project is the editable source of truth.  Curve appearance must be
    controlled by native plot properties, never by a duplicated SVG polyline placed
    on top of the graph.  The arguments remain for backwards-compatible callers.
    """
    return []


def series_data_bounds(series: List[SeriesSpec], layer: int) -> Optional[Dict[str, float]]:
    """Data extent of one graph layer (used to reproduce Origin's own auto range)."""
    xs: List[float] = []
    ys: List[float] = []
    for item in series:
        if item.layer != layer or item.role != "data" or not item.points:
            continue
        for x_value, y_value in item.points:
            xs.append(float(x_value))
            ys.append(float(y_value))
    if not xs:
        return None
    return {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)]}
