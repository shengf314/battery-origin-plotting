"""Generic SVG drawing primitives - the renderer vocabulary.

Each function returns one SVG element as a string and knows nothing about
cycles, branches or metrics: it only turns geometry into markup.  Plot types,
legend renderers and overlays build their pieces from these primitives, so a
future CV / EIS / XRD figure reuses the same drawing vocabulary instead of
re-implementing rectangles, lines and symbols.
"""

from typing import List, Optional, Sequence, Tuple


def svg_mm(width_mm: float, height_mm: float, body: str) -> str:
    """An SVG document whose intrinsic size is given in millimetres."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%.6fmm" height="%.6fmm" '
            'viewBox="0 0 %.6f %.6f">%s</svg>'
            % (width_mm, height_mm, width_mm, height_mm, body))


def svg_pt(width_pt: float, height_pt: float, body: str) -> str:
    """An SVG document whose intrinsic size is given in points (text outlines)."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%.6fpt" height="%.6fpt" '
            'viewBox="0 0 %.6f %.6f">%s</svg>'
            % (width_pt, height_pt, width_pt, height_pt, body))


def rect(x: float, y: float, width: float, height: float, fill: str,
         opacity: Optional[float] = None, stroke: Optional[str] = None) -> str:
    attributes = ['fill="%s"' % fill]
    attributes.append('fill-opacity="%s"' % opacity if opacity is not None else "")
    attributes.append('stroke="%s"' % stroke if stroke else 'stroke="none"')
    return ('<path d="M %.6f,%.6f L %.6f,%.6f L %.6f,%.6f L %.6f,%.6f Z" %s/>'
            % (x, y, x + width, y, x + width, y + height, x, y + height,
               " ".join(item for item in attributes if item)))


def rect_stroke(x: float, y: float, width: float, height: float,
                stroke_mm: float, color: str) -> str:
    """An outlined (white-filled) rectangle, used for open square symbols."""
    return ('<path d="M %.6f,%.6f L %.6f,%.6f L %.6f,%.6f L %.6f,%.6f Z" fill="white" '
            'stroke="%s" stroke-width="%.4f"/>'
            % (x, y, x + width, y, x + width, y + height, x, y + height, color,
               stroke_mm))


def line(x0: float, y0: float, x1: float, y1: float, color: str,
         width_mm: float) -> str:
    return ('<path d="M %.6f,%.6f L %.6f,%.6f" stroke="%s" stroke-width="%.4f" '
            'fill="none"/>' % (x0, y0, x1, y1, color, width_mm))


def circle(cx: float, cy: float, radius: float, color: str, filled: bool,
           stroke_mm: float = 0.25) -> str:
    if filled:
        return '<circle cx="%.6f" cy="%.6f" r="%.6f" fill="%s"/>' % (cx, cy, radius, color)
    return ('<circle cx="%.6f" cy="%.6f" r="%.6f" fill="white" stroke="%s" '
            'stroke-width="%s"/>'
            % (cx, cy, radius, color, _compact(stroke_mm)))


def _compact(value: float) -> str:
    """Shortest exact decimal of a small millimetre value (0.25 -> "0.25")."""
    text = ("%.4f" % float(value)).rstrip("0").rstrip(".")
    return text or "0"


def marker(cx: float, cy: float, radius: float, color: str, filled: bool,
           edge_mm: float, shape: str) -> str:
    """One data symbol: circle by default, square when the template asks for it.

    Symbols keep their own coordinate precision (the accepted reference export
    writes four decimals), which is why they are not routed through ``circle``.
    """
    key = (shape or "circle").lower()
    if key in ("circle", "none", ""):
        if filled:
            return '<circle cx="%.4f" cy="%.4f" r="%.4f" fill="%s"/>' % (cx, cy, radius,
                                                                        color)
        return ('<circle cx="%.4f" cy="%.4f" r="%.4f" fill="white" stroke="%s" '
                'stroke-width="%.4f"/>'
                % (cx, cy, radius, color, edge_mm or 0.25))
    if key == "square":
        if filled:
            return rect(cx - radius, cy - radius, radius * 2, radius * 2, color)
        return rect_stroke(cx - radius, cy - radius, radius * 2, radius * 2,
                           edge_mm or 0.5, color)
    raise ValueError("unsupported marker shape: %r" % shape)


def polyline(points_mm: Sequence[Tuple[float, float]], color: str,
             width_mm: float) -> str:
    """A connected polyline in piece millimetres (used for data curves)."""
    commands: List[str] = []
    for index, (x_mm, y_mm) in enumerate(points_mm):
        commands.append("%s%.4f,%.4f" % ("M" if index == 0 else "L", x_mm, y_mm))
    return ('<path d="%s" fill="none" stroke="%s" stroke-width="%.4f" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
            % (" ".join(commands), color, width_mm))


def glyph_group(path_d: str, x_mm: float, y_mm: float, scale: float,
                fill: str = "black") -> str:
    """A text outline (from the outline asset) placed at a piece position."""
    return ('<g transform="translate(%.6f,%.6f) scale(%.8f)">'
            '<path d="%s" fill="%s" fill-rule="evenodd"/></g>'
            % (x_mm, y_mm, scale, path_d, fill))


def label_glyph(path_d: str, width_pt: float, height_pt: float) -> str:
    """A standalone text-outline piece in its own intrinsic point size."""
    return svg_pt(width_pt, height_pt,
                  '<path d="%s" fill="black" fill-rule="evenodd"/>' % path_d)


def anchor_offset(align: str, width_mm: float, height_mm: float, x_mm: float,
                  y_mm: float) -> Tuple[float, float]:
    """Top-left corner of a box of the given alignment relative to ``(x, y)``."""
    if align == "center_center":
        return x_mm - width_mm / 2.0, y_mm - height_mm / 2.0
    if align == "center_top":
        return x_mm - width_mm / 2.0, y_mm
    if align == "center_bottom":
        return x_mm - width_mm / 2.0, y_mm - height_mm
    if align == "right_center":
        return x_mm - width_mm, y_mm - height_mm / 2.0
    if align == "left_center":
        return x_mm, y_mm - height_mm / 2.0
    if align == "left_top":
        return x_mm, y_mm
    raise ValueError("unsupported label alignment: %r" % align)
