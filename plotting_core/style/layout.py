"""Canvas, margins and the plot-area rectangle (single source of geometry)."""

from typing import Dict, Tuple

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


def _num(value, name):
    if value is None:
        raise ValueError("%s is not configured" % name)
    return float(value)


def canvas(config: Dict) -> Dict[str, float]:
    canvas_cfg = config.get("canvas") or {}
    unit = canvas_cfg.get("size_unit", "mm")
    width = _num(canvas_cfg.get("width"), "canvas.width")
    height = _num(canvas_cfg.get("height"), "canvas.height")
    if unit != "mm":
        raise ValueError("canvas.size_unit must be mm, got %r" % unit)
    return {"width_mm": width, "height_mm": height}


def margins(config: Dict) -> Dict[str, float]:
    canvas_cfg = config.get("canvas") or {}
    margins_cfg = canvas_cfg.get("margins") or {}
    unit = margins_cfg.get("unit", "mm")
    if unit != "mm":
        raise ValueError("canvas.margins.unit must be mm, got %r" % unit)
    return {
        key: _num(margins_cfg.get(key), "canvas.margins.%s" % key)
        for key in ("left", "right", "top", "bottom")
    }


def plot_area(config: Dict) -> Dict[str, float]:
    """Plot-area rectangle in mm, measured from the page top-left corner."""
    box = canvas(config)
    margin = margins(config)
    return {
        "left_mm": margin["left"],
        "top_mm": margin["top"],
        "width_mm": box["width_mm"] - margin["left"] - margin["right"],
        "height_mm": box["height_mm"] - margin["top"] - margin["bottom"],
        "page_width_mm": box["width_mm"],
        "page_height_mm": box["height_mm"],
    }


def page_percent(area: Dict[str, float], x_mm: float, y_mm: float) -> Tuple[float, float]:
    """Convert absolute page millimetres (from the top-left) to page percent."""
    return (x_mm / area["page_width_mm"] * 100.0, y_mm / area["page_height_mm"] * 100.0)


def fraction_to_page_mm(area: Dict[str, float], x_frac: float, y_frac: float) -> Tuple[float, float]:
    """Layer-fraction position (0,0 = bottom-left of the plot area) to page mm."""
    return (
        area["left_mm"] + x_frac * area["width_mm"],
        area["top_mm"] + (1.0 - y_frac) * area["height_mm"],
    )


def mm_to_page_fraction(area: Dict[str, float], x_mm: float, y_mm: float) -> Tuple[float, float]:
    """Absolute page mm to layer fraction (0,0 = bottom-left of the plot area)."""
    return (
        (x_mm - area["left_mm"]) / area["width_mm"],
        1.0 - (y_mm - area["top_mm"]) / area["height_mm"],
    )


def data_to_fraction(area: Dict[str, float], axis_ranges: Dict[str, Tuple[float, float]],
                     x: float, y: float) -> Tuple[float, float]:
    (x_from, x_to) = axis_ranges["x"]
    (y_from, y_to) = axis_ranges["y"]
    return ((x - x_from) / (x_to - x_from), (y - y_from) / (y_to - y_from))


def fraction_to_data(axis_ranges: Dict[str, Tuple[float, float]],
                     x_frac: float, y_frac: float) -> Tuple[float, float]:
    (x_from, x_to) = axis_ranges["x"]
    (y_from, y_to) = axis_ranges["y"]
    return (x_from + x_frac * (x_to - x_from), y_from + y_frac * (y_to - y_from))


def pt_to_mm(value_pt: float) -> float:
    return float(value_pt) * MM_PER_INCH / PT_PER_INCH


def mm_to_pt(value_mm: float) -> float:
    return float(value_mm) * PT_PER_INCH / MM_PER_INCH
