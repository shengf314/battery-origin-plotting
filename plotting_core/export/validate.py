"""Export validation: what the documented checks actually measure."""

import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree

from ..config import SKILL_ROOT
from . import runtime

PNG_INSPECTOR = SKILL_ROOT / "scripts" / "inspect_png.cjs"


def inspect_png(path: str) -> Dict:
    """Size, DPI, colour space and corner pixels of an exported PNG."""
    if not PNG_INSPECTOR.exists():
        raise RuntimeError("the PNG inspection asset is missing: %s" % PNG_INSPECTOR)
    node, modules = runtime.require()
    completed = subprocess.run([node, str(PNG_INSPECTOR), str(path), modules],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise RuntimeError("PNG inspection failed: %s"
                           % completed.stderr.decode("utf-8", "replace"))
    return json.loads(completed.stdout.decode("utf-8"))


def inspect_svg(path: str) -> Dict:
    """Vector structure, background and text state of an exported SVG."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    root = None
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise RuntimeError("the exported SVG cannot be parsed: %s" % exc)
    tags: Dict[str, int] = {}
    for element in root.iter():
        tag = element.tag.split("}")[-1]
        tags[tag] = tags.get(tag, 0) + 1
    vector_tags = ("path", "polyline", "polygon", "rect", "line", "circle", "ellipse")
    fonts = sorted(set(re.findall(r'font-family="([^"]+)"', text)))
    return {
        "root_tag": root.tag.split("}")[-1],
        "tags": tags,
        "vector_elements": sum(tags.get(tag, 0) for tag in vector_tags),
        "nested_svg": tags.get("svg", 0) - 1,
        "image_elements": tags.get("image", 0),
        "text_elements": tags.get("text", 0),
        "fonts": fonts,
        "width": root.get("width"),
        "height": root.get("height"),
        "viewBox": root.get("viewBox"),
        "white_background": bool(re.search(r'fill="white"', text)),
    }


def measure_curve_style(path: str) -> Dict:
    """Stroke widths and colours actually used by the exported data curves.

    ``width_units`` is what the Origin polylines use (page units, 1 unit =
    0.0847 mm); ``overlay_width_pt`` is the width of the vector-overlay curves that
    carry the template line width, given in points.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    body = text.split("</defs>", 1)[-1]
    widths: Dict[str, int] = {}
    overlay_widths = []
    for match in re.finditer(r'<polyline points="([^"]+)"([^>]*)>', body):
        # Two/three-point measured lines are valid curves. Native frame and
        # tick lines use named black, while the configured palette is hex RGB.
        # Excluding every short polyline hid valid supplied-data curves.
        width = re.search(r"stroke-width: ([\d.]+)", match.group(2))
        if width:
            widths[width.group(1)] = widths.get(width.group(1), 0) + 1
    for match in re.finditer(r'<path d="([^"]{200,})"([^>]*)>', body):
        width = re.search(r'stroke-width="([\d.]+)"', match.group(2))
        if width:
            overlay_widths.append(float(width.group(1)))
    # Native open symbols carry palette colours in inline CSS stroke, while
    # filled symbols may use presentation attributes. Parse visible geometry;
    # text colours and unused definitions cannot prove a plotted palette.
    colors = _geometry_colors(ElementTree.fromstring(text))
    overlay_pt = (round(max(overlay_widths) / 25.4 * 72.0, 2) if overlay_widths else None)
    return {"width_units": widths, "overlay_width_pt": overlay_pt,
            "distinct_colors": len(set(colors)),
            "colors": sorted(set(colors))[:200]}


def _geometry_colors(root) -> List[str]:
    """Read native vector paint without modifying the SVG.

    Inline CSS overrides presentation attributes; group paint is inherited only
    when attached to an actual geometry node. Unused definitions, clip/mask
    geometry, text and hidden paint are excluded. This is palette presence
    evidence, not proof of a particular series binding (the native QA owns that).
    """
    geometry = {"path", "polyline", "polygon", "rect", "line", "circle", "ellipse"}
    excluded = {"defs", "clipPath", "mask", "marker", "pattern", "symbol",
                "text", "tspan", "textPath", "style", "title", "desc", "metadata"}
    inherited_keys = {"fill", "stroke", "fill-opacity", "stroke-opacity", "stroke-width", "visibility"}
    colors = []

    def opacity(value):
        try:
            return float(str(value).rstrip("%")) / (100 if str(value).endswith("%") else 1)
        except (ValueError, TypeError):
            return None

    def rgb(value):
        match = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", str(value).strip())
        if not match:
            return None
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        return "#" + digits.upper()

    def walk(element, inherited):
        tag = element.tag.split("}")[-1]
        if tag in excluded:
            return
        paint = dict(inherited)
        paint.update({key: element.get(key) for key in inherited_keys | {"display", "opacity"}
                      if element.get(key) is not None})
        # Origin uses inline declarations. Property whitespace and attribute
        # order do not change CSS paint; CSS takes precedence over attributes.
        for declaration in (element.get("style") or "").split(";"):
            if ":" in declaration:
                key, value = declaration.split(":", 1)
                paint[key.strip().lower()] = re.sub(r"\s*!important\s*$", "", value,
                                                   flags=re.I).strip()
        if paint.get("display") == "none" or opacity(paint.get("opacity", 1)) == 0:
            return
        if tag in geometry and paint.get("visibility", "visible") not in ("hidden", "collapse"):
            for key in ("fill", "stroke"):
                color = rgb(paint.get(key, ""))
                if not color or opacity(paint.get(key + "-opacity", 1)) == 0:
                    continue
                if key == "fill" and tag == "line":
                    continue
                if key == "stroke" and re.fullmatch(r"0(?:\.0+)?(?:px|pt|mm|cm|in)?", str(paint.get("stroke-width", "1"))):
                    continue
                colors.append(color)
        child_paint = {key: value for key, value in paint.items() if key in inherited_keys}
        for child in element:
            walk(child, child_paint)

    walk(root, {})
    return colors


def validate_exports(exports: Dict[str, str], config: Dict, *,
                     expected_canvas_mm: Optional[List[float]] = None,
                     dpi: int = 600,
                     expected_tick_labels: Optional[List[str]] = None,
                     expected_line_width_pt: Optional[float] = None,
                     expected_curve_colors: Optional[List[str]] = None,
                     expected_legend_entries: Optional[List[str]] = None) -> Dict:
    """Run every confirmed export check and return a JSON-serialisable report."""
    report: Dict = {"files": {key: Path(value).exists() for key, value in exports.items()},
                    "checked": {}, "issues": [], "visual_deviations": []}
    svg = exports.get("svg")
    if svg and Path(svg).exists():
        info = inspect_svg(svg)
        report["svg"] = info
        style = measure_curve_style(svg)
        report["curve_style"] = style
        if expected_legend_entries:
            tree = ElementTree.parse(svg)
            drawn = ["".join(element.itertext()).strip() for element in tree.iter()
                     if element.tag.split("}")[-1] == "text"]
            def normalized(value):
                return " ".join(unicodedata.normalize("NFKC", value).split())
            missing = [value for value in expected_legend_entries
                       if not any(normalized(value) in normalized(text) for text in drawn)]
            report["checked"]["legend_entries_present"] = not missing
            if missing:
                report["issues"].append("scientific legend entries missing from SVG: %s" % ", ".join(missing))
        if style["overlay_width_pt"]:
            # the overlay curves carry the template width and cover the Origin line
            drawn_pt = style["overlay_width_pt"]
            report["checked"]["curve_line_width_pt"] = drawn_pt
            report["checked"]["curve_line_width_source"] = "vector overlay"
            if expected_line_width_pt and abs(drawn_pt - expected_line_width_pt) > 0.05:
                report["visual_deviations"].append(
                    "visual template line width %.2f pt, drawn %.2f pt by the overlay"
                    % (expected_line_width_pt, drawn_pt))
        elif style["width_units"]:
            # SVG page units: 1005 units = 85 mm, so 1 unit = 0.0847 mm = 0.240 pt
            unit_pt = 85.0 / 1005.0 * 72.0 / 25.4
            drawn_units = float(
                sorted(style["width_units"].items(), key=lambda item: -item[1])[0][0])
            drawn_pt = round(drawn_units * unit_pt, 2)
            report["checked"]["curve_line_width_pt"] = drawn_pt
            report["checked"]["curve_line_width_source"] = "Origin plot style"
            # Origin writes whole page units, so a 0.8 pt line measures 0.72 pt here;
            # the tolerance is therefore one unit, not an absolute point difference.
            expected_units = (expected_line_width_pt / unit_pt
                              if expected_line_width_pt else None)
            if expected_units and abs(drawn_units - expected_units) > 0.75:
                report["visual_deviations"].append(
                    "visual template line width %.2f pt, drawn %.2f pt (%d page units); "
                    "Origin's line width override is not effective in this build"
                    % (expected_line_width_pt, drawn_pt, int(round(drawn_units))))
        if expected_curve_colors:
            drawn_colors = {value.upper() for value in style["colors"]}
            missing = [value.upper() for value in expected_curve_colors
                       if value.upper() not in drawn_colors]
            report["checked"]["curve_colors_present"] = not missing
            if missing:
                report["issues"].append("series colours missing from the export: %s"
                                        % ", ".join(missing[:10]))
        if expected_tick_labels:
            text = Path(svg).read_text(encoding="utf-8", errors="replace")
            drawn = [re.sub(r"<[^>]+>", "", item).strip()
                     for item in re.findall(r"<text[^>]*>(.*?)</text>", text, re.S)]
            missing = [value for value in expected_tick_labels if value not in drawn]
            report["checked"]["tick_labels_drawn"] = sorted(set(drawn))
            if missing:
                report["issues"].append("tick labels missing from the SVG: %s"
                                        % ", ".join(missing))
        if info["vector_elements"] == 0:
            report["issues"].append("the SVG contains no vector elements")
        if info["image_elements"]:
            report["issues"].append("the SVG embeds raster image nodes")
        if not info["white_background"]:
            report["issues"].append("the SVG has no explicit white background")
        report["checked"]["svg_vector_preserved"] = info["vector_elements"] > 0
        report["checked"]["svg_background_white"] = info["white_background"]
    png = exports.get("png")
    if png and Path(png).exists():
        info = inspect_png(png)
        report["png"] = info
        density = info.get("density") or 0
        if abs(density - dpi) > 1:
            report["issues"].append("PNG density is %s dpi, %s expected" % (density, dpi))
        corners_white = all(corner == [255, 255, 255] for corner in info["corners"])
        if not corners_white:
            report["issues"].append("PNG corners are not white")
        if info.get("hasAlpha"):
            report["issues"].append("PNG has an alpha channel (transparent export)")
        report["checked"]["png_dpi"] = density
        report["checked"]["png_background_white"] = corners_white
        report["checked"]["png_has_content"] = info["non_white_sampled"] > 0
    if expected_canvas_mm:
        report["expected_canvas_mm"] = expected_canvas_mm
    report["ok"] = not report["issues"]
    return report
