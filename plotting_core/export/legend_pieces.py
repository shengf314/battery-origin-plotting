"""Legend renderers: one builder per legend mode.

These are renderers, not plot-type logic: they receive the legend the plan
declared (``LegendSpec`` plus the resolved ``legend_plan``) and draw it with the
generic primitives.  A future figure family that needs a grouped legend or a
gradient bar reuses these builders by declaring the same legend mode.
"""

from typing import Dict, List, Optional

from ..style import legend as legend_style
from ..style import layout as layout_style
from . import primitives

PT_TO_MM = layout_style.MM_PER_INCH / layout_style.PT_PER_INCH


def gradient_bar_piece(plan, area: Dict[str, float],
                       glyphs: Optional[Dict] = None) -> Optional[Dict]:
    """The approved cycle gradient bar (one rectangle per selected cycle)."""
    bar = plan.legend.bar
    cycles = list(plan.legend.grouped.get("cycles") or [])
    colors = list(plan.legend.grouped.get("colors") or [])
    if not cycles or len(cycles) != len(colors):
        raise ValueError("the gradient bar needs one colour per selected cycle")
    box = legend_style.cycle_gradient_bar_layout(area, bar)
    width = box["right_mm"] - box["left_mm"]
    height = box["height_mm"]
    step = width / len(cycles)
    segments = [primitives.rect(index * step, 0.0, step, height, color)
                for index, color in enumerate(colors)]
    return {"name": "LegendBar",
            "svg": primitives.svg_mm(width, height, "".join(segments)),
            "role": "legend_bar",
            "left_mm": area["left_mm"] + box["left_mm"],
            "top_mm": area["top_mm"] + box["top_mm"],
            "width_mm": width, "height_mm": height}


def grouped_legend_piece(plan, area: Dict[str, float],
                         glyphs: Dict[str, Dict]) -> Optional[Dict]:
    """Sample colour swatches plus the metric symbols, grouped in one box."""
    spec = plan.page.get("legend_plan") or {}
    rows: List[Dict] = []
    for row in spec.get("samples", []):
        rows.append({"kind": "sample", "label": row.get("label"), "color": row.get("color")})
    reference = spec.get("samples", [{}])[0].get("color") if spec.get("samples") else "#000000"
    for row in spec.get("metrics", []):
        rows.append({"kind": "metric", "label": row.get("label"),
                     "marker": row.get("marker"), "color": reference})
    if not rows:
        return None
    size_pt = float(spec.get("size_pt") or 6.5)
    swatch = float(spec.get("swatch_mm") or 4.0)
    text_gap = float(spec.get("text_gap_mm") or 1.0)
    row_gap = float(spec.get("row_gap_mm") or 0.8)
    group_gap = float(spec.get("group_gap_mm") or 1.4)
    padding = 1.0
    line_height = size_pt * 1.25 * PT_TO_MM
    glyph_rows = [glyphs.get("LegendRow%d" % index) for index in range(len(rows))]
    text_width = max((layout_style.pt_to_mm(item["width_pt"]) for item in glyph_rows if item),
                     default=0.0)
    box_width = padding * 2 + swatch + text_gap + text_width
    box_height = (padding * 2 + len(rows) * line_height +
                  max(len(rows) - 1, 0) * row_gap + group_gap)
    inset = float(spec.get("inset_mm") or 2.0)
    corner = spec.get("corner") or "top_right"
    x = inset if "left" in corner else area["width_mm"] - inset - box_width
    y = inset if "top" in corner else area["height_mm"] - inset - box_height
    parts = [primitives.rect(0.0, 0.0, box_width, box_height, "white", opacity=0.9)]
    cursor = padding
    for index, row in enumerate(rows):
        center = cursor + line_height / 2.0
        if row["kind"] == "sample":
            parts.append(primitives.line(padding, center, padding + swatch, center,
                                         row.get("color") or "#000000", 0.5))
            parts.append(primitives.rect(padding, center - size_pt * 0.35 * PT_TO_MM,
                                         swatch, size_pt * 0.7 * PT_TO_MM,
                                         row.get("color") or "#000000"))
        else:
            color = row.get("color") or "#000000"
            filled = (row.get("marker") or "filled_circle") != "open_circle"
            parts.append(primitives.circle(padding + swatch / 2.0, center,
                                           size_pt * 0.45 * PT_TO_MM, color, filled))
            parts.append(primitives.line(padding + swatch / 2.0, center,
                                         padding + swatch, center, color, 0.4))
        glyph = glyph_rows[index]
        if glyph is not None:
            parts.append(primitives.glyph_group(
                glyph["path_d"], padding + swatch + text_gap,
                center - glyph["height_pt"] * PT_TO_MM / 2.0, PT_TO_MM))
        cursor += line_height + row_gap
    return {"name": "Legend",
            "svg": primitives.svg_mm(box_width, box_height, "".join(parts)),
            "role": "legend",
            "left_mm": area["left_mm"] + x, "top_mm": area["top_mm"] + y,
            "width_mm": box_width, "height_mm": box_height}


# legend mode -> piece builder (add a mode here, not in the composition code)
LEGEND_PIECE_BUILDERS = {
    "cycle_gradient_bar": gradient_bar_piece,
    "grouped": grouped_legend_piece,
}
