"""Compose the vector overlay pieces (curves, markers, labels, legend).

Each piece is one SVG whose intrinsic size is exactly the size of the element it
draws, inserted at its own page position.  That is the scheme the accepted
reference figure used, and it keeps the vector content intact: Origin imports the
SVG at its declared size, so no geometry has to be fixed up afterwards, and no
content sits outside the imported viewport (which the SVG/PNG export clips).

This module only composes: shapes come from :mod:`plotting_core.export.primitives`
and legend modes from :mod:`plotting_core.export.legend_pieces`.  Nothing here
knows what a cycle, a branch or a metric is.

Overlay coordinates are millimetres: ``(0, 0)`` is the top-left corner of the
plot area for layer-fraction maths, and piece placements are converted to page
percent by the backend.
"""

from typing import Dict, List, Optional, Tuple

from ..models import LabelSpec
from ..style import layout as layout_style
from . import legend_pieces, primitives

PT_TO_MM = layout_style.MM_PER_INCH / layout_style.PT_PER_INCH


def _anchor_offset(align: str, width_mm: float, height_mm: float, x_mm: float,
                   y_mm: float) -> Tuple[float, float]:
    """Backwards-compatible name for the shared alignment primitive."""
    return primitives.anchor_offset(align, width_mm, height_mm, x_mm, y_mm)


def label_box(label: LabelSpec, glyph: Dict, area: Dict[str, float],
              axis_ranges: Optional[Dict] = None) -> Tuple[float, float, float, float]:
    """Box of one label in plot-area millimetres (0,0 = plot-area top-left)."""
    width_mm = layout_style.pt_to_mm(glyph["width_pt"])
    height_mm = layout_style.pt_to_mm(glyph["height_pt"])
    x_frac, y_frac = label.position
    if label.anchor in ("layer_scale", "x_scale_y_fraction"):
        ranges = (axis_ranges or {}).get("left")
        if not ranges:
            raise ValueError("data-coordinate labels require the actual left layer axis ranges")
        x_from, x_to = ranges["x"]
        x_frac = (x_frac - x_from) / (x_to - x_from)
        if label.anchor == "layer_scale":
            y_from, y_to = ranges["y"]
            y_frac = (y_frac - y_from) / (y_to - y_from)
    elif label.anchor != "layer_fraction":
        raise ValueError("unsupported label anchor %r" % label.anchor)
    x_mm = x_frac * area["width_mm"]
    y_mm = (1.0 - y_frac) * area["height_mm"]
    if label.gap_mm is not None:
        y_mm += label.gap_mm
    x0, y0 = _anchor_offset(label.align, width_mm, height_mm, x_mm, y_mm)
    return x0, y0, width_mm, height_mm


def _label_piece(label: LabelSpec, glyph: Dict, area: Dict[str, float],
                 axis_ranges: Optional[Dict] = None) -> Dict:
    x0, y0, width_mm, height_mm = label_box(label, glyph, area, axis_ranges)
    return {"name": label.name,
            "svg": primitives.label_glyph(glyph["path_d"], glyph["width_pt"],
                                          glyph["height_pt"]),
            "role": label.role,
            "left_mm": area["left_mm"] + x0, "top_mm": area["top_mm"] + y0,
            "width_mm": width_mm, "height_mm": height_mm}


MAX_OVERLAY_POINTS_PER_SERIES = 60000


def _curve_piece(plan, area: Dict[str, float],
                 axis_ranges: Dict[str, Dict[str, List[float]]],
                 notes: List[str]) -> Optional[Dict]:
    """Data curves at the template line width, plus the symbols drawn over them.

    Origin's line-width override has no effect in the installed build, so the
    plotted line keeps its default width.  Re-drawing the same polylines in the
    overlay at the configured width makes the rendered width exactly the template
    value (the narrower line underneath is fully covered).  The symbols live in the
    same piece, after the curves, so their stacking is fixed by SVG order and cannot
    depend on how the backend orders graph objects.
    """
    curves = plan.page.get("line_overlay") or []
    markers = plan.page.get("marker_overlay") or []
    if not curves and not markers:
        return None
    parts: List[str] = []
    for curve in curves:
        points = curve["points"]
        if len(points) > MAX_OVERLAY_POINTS_PER_SERIES:
            notes.append(
                "series %s has %d points; the template line width was not applied "
                "because the overlay is limited to %d points per series"
                % (curve["series_id"], len(points), MAX_OVERLAY_POINTS_PER_SERIES))
            continue
        ranges = axis_ranges.get(curve.get("layer") or "left")
        if not ranges:
            raise ValueError("no axis range recorded for layer %s" % curve.get("layer"))
        x_from, x_to = ranges["x"]
        y_from, y_to = ranges["y"]
        points_mm = [data_to_piece_mm(x_value, y_value, area, x_from, x_to,
                                      y_from, y_to)
                     for x_value, y_value in points]
        parts.append(primitives.polyline(points_mm, curve["color"],
                                         layout_style.pt_to_mm(curve["width_pt"])))
    parts.extend(_marker_paths(markers, area, axis_ranges))
    if not parts:
        return None
    return {"name": "Curves",
            "svg": primitives.svg_mm(area["width_mm"], area["height_mm"],
                                     "".join(parts)),
            "role": "curves",
            "left_mm": area["left_mm"], "top_mm": area["top_mm"],
            "width_mm": area["width_mm"], "height_mm": area["height_mm"]}


def data_to_piece_mm(x_value: float, y_value: float, area: Dict[str, float],
                     x_from: float, x_to: float, y_from: float,
                     y_to: float) -> Tuple[float, float]:
    """One data coordinate to overlay millimetres (0,0 = plot-area top-left)."""
    x_mm = (x_value - x_from) / (x_to - x_from) * area["width_mm"]
    y_mm = (y_to - y_value) / (y_to - y_from) * area["height_mm"]
    return x_mm, y_mm


def _marker_paths(markers: List[Dict], area: Dict[str, float],
                  axis_ranges: Dict[str, Dict[str, List[float]]]) -> List[str]:
    """Cycle Performance symbols, drawn from the verified data coordinates."""
    if not markers:
        return []
    parts: List[str] = []
    for group in markers:
        layer_key = "left" if group["layer"] == 0 else "right"
        ranges = axis_ranges.get(layer_key)
        if not ranges:
            raise ValueError("no axis range recorded for layer %s" % layer_key)
        x_from, x_to = ranges["x"]
        y_from, y_to = ranges["y"]
        size_pt = float(group.get("symbol_size_pt") or 0.0)
        radius = max(size_pt * 0.5 * PT_TO_MM, 0.05)
        edge = float(group.get("symbol_edge_width_pt") or 0.0)
        filled = (group.get("symbol_fill") or "filled").lower() != "open"
        shape = (group.get("symbol_shape") or "circle").lower()
        for x_value, y_value in group["points"]:
            x_mm, y_mm = data_to_piece_mm(x_value, y_value, area, x_from, x_to,
                                          y_from, y_to)
            parts.append(primitives.marker(x_mm, y_mm, radius, group["color"],
                                           filled, layout_style.pt_to_mm(edge or 0.5),
                                           shape))
    return parts


def build_pieces(plan, area: Dict[str, float], glyphs: Dict[str, Dict],
                 axis_ranges: Optional[Dict] = None) -> List[Dict]:
    """All overlay pieces, each with its own SVG and page position in mm."""
    pieces: List[Dict] = []
    notes: List[str] = []
    curves = _curve_piece(plan, area, axis_ranges or {}, notes)
    if curves:
        pieces.append(curves)
    builder = legend_pieces.LEGEND_PIECE_BUILDERS.get(plan.legend.mode)
    if builder is not None:
        piece = builder(plan, area, glyphs)
        if piece:
            pieces.append(piece)
    for label in plan.labels:
        glyph = glyphs.get(label.name)
        if glyph is None:
            raise KeyError("no outline was generated for label %r" % label.name)
        pieces.append(_label_piece(label, glyph, area, axis_ranges))
    if notes:
        plan.notes = list(plan.notes) + notes
    return pieces
