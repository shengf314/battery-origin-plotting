"""Font families, sizes and the confirmed label placement offsets (in mm)."""

from typing import Dict, Optional

from . import layout as layout_style

# Offsets retained from the historical accepted reference figure. They are
# layout constants inside the configured margins, not visual-template values:
# the template fixes the canvas/margins and the font sizes, these place the
# axis-title boxes inside the margins without clipping.
DEFAULT_X_TITLE_TOP_GAP_MM = 5.0    # plot-area bottom edge -> title box top edge
DEFAULT_Y_TITLE_RIGHT_GAP_MM = 6.15  # plot-area left edge <-> title box right edge
DEFAULT_Y_TITLE_LEFT_LABEL_GAP_MM = 1.5  # left Y tick labels <-> title box right edge


def font_family(config: Dict) -> Optional[str]:
    return (config.get("global") or {}).get("font_family")


def axis_title_size_pt(config: Dict) -> float:
    value = (config.get("labels") or {}).get("axis_title_font_size")
    if value is None:
        raise ValueError("labels.axis_title_font_size is not configured")
    return float(value)


def tick_label_size_pt(config: Dict) -> float:
    value = (config.get("labels") or {}).get("tick_label_font_size")
    if value is None:
        raise ValueError("labels.tick_label_font_size is not configured")
    return float(value)


def legend_size_pt(config: Dict) -> float:
    value = ((config.get("legend") or {}).get("font_size")
             or (config.get("labels") or {}).get("tick_label_font_size"))
    if value is None:
        raise ValueError("legend.font_size is not configured")
    return float(value)


def _optional_bold(section: Dict, key: str, path: str) -> Optional[bool]:
    """An absent option preserves existing native typography."""
    value = section.get(key)
    if value is not None and not isinstance(value, bool):
        raise ValueError("%s must be a boolean or null" % path)
    return value


def tick_label_bold(config: Dict) -> Optional[bool]:
    return _optional_bold(config.get("labels") or {}, "tick_label_bold",
                          "labels.tick_label_bold")


def axis_title_bold(config: Dict) -> Optional[bool]:
    return _optional_bold(config.get("labels") or {}, "axis_title_bold",
                          "labels.axis_title_bold")


def legend_bold(config: Dict) -> Optional[bool]:
    return _optional_bold(config.get("legend") or {}, "bold", "legend.bold")


def annotation_bold(config: Dict) -> Optional[bool]:
    """Ordinary native labels inherit the explicit axis-title weight by default."""
    value = _optional_bold(config.get("labels") or {}, "annotation_bold", "labels.annotation_bold")
    return axis_title_bold(config) if value is None else value


def title_offsets(config: Dict) -> Dict[str, float]:
    """Offsets used to place axis titles inside the configured margins (mm)."""
    plot_type = config.get("plot_type") or {}
    configured = plot_type.get("title_offsets") or {}
    return {
        "x_title_top_gap_mm": float(configured.get("x_title_top_gap_mm",
                                                   DEFAULT_X_TITLE_TOP_GAP_MM)),
        "y_title_right_gap_mm": float(configured.get("y_title_right_gap_mm",
                                                     DEFAULT_Y_TITLE_RIGHT_GAP_MM)),
        "y_title_left_label_gap_mm": float(
            configured.get("y_title_left_label_gap_mm",
                           DEFAULT_Y_TITLE_LEFT_LABEL_GAP_MM)),
    }


# Average glyph-width factor of the confirmed font at the configured sizes.  It is
# only used to reserve margin space (a text-outline measurement replaces it for the
# labels themselves), so it stays a single documented constant.
AVERAGE_GLYPH_WIDTH_FACTOR = 0.52


def estimate_width_mm(text: str, size_pt: float) -> float:
    """Reserve the width of a tick label before the real glyph outline is known."""
    return (len(str(text)) * float(size_pt) * AVERAGE_GLYPH_WIDTH_FACTOR
            * layout_style.MM_PER_INCH / layout_style.PT_PER_INCH)
