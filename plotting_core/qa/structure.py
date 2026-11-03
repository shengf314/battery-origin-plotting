"""QA Level 1 - structure checks (default cost, always run).

Everything here answers "is the delivered object complete and shaped as the plan
and the visual template require": plan integrity, declared labels/legend, then
the exported files (vector content, white background, 600 dpi raster, canvas
size, tick labels, series colours).  The measurement itself is done by
``export.validate``; this module turns it into graded checks and issues.
"""

from typing import Dict, List, Optional

from ..style import layout as layout_style

LEVEL = 1
NAME = "structure"


def check(plan, config: Dict, export_report: Optional[Dict] = None) -> Dict:
    """Run the structure checks and return a JSON-serialisable report."""
    checks: Dict = {}
    issues: List[str] = []

    data_series = plan.data_series
    checks["series_declared"] = len(data_series)
    checks["all_series_have_points"] = all(item.points for item in data_series)
    if not data_series:
        issues.append("the plan declares no data series")
    if not checks["all_series_have_points"]:
        issues.append("at least one series has no plotting points")

    axis_titles = []
    for layer in plan.layers:
        for key, role in (("bottom", "axis_title_x"), ("left", "axis_title_y"),
                          ("right", "axis_title_y_right")):
            axis = layer.axes.get(key)
            if axis is not None and axis.label:
                axis_titles.append(role)
    # Compatibility for plans which intentionally keep title labels outside axes.
    axis_titles.extend(label.role for label in plan.labels
                       if label.role.startswith("axis_title"))
    checks["axis_titles"] = sorted(set(axis_titles))
    if "axis_title_x" not in axis_titles:
        issues.append("no X axis title is declared")
    if not any(role.startswith("axis_title_y") for role in axis_titles):
        issues.append("no Y axis title is declared")

    checks["legend_mode"] = plan.legend.mode
    if plan.legend.mode == "entries" and not plan.legend.entries:
        issues.append("the legend mode is 'entries' but no entry was declared")
    if plan.legend.mode == "cycle_gradient_bar" and not plan.legend.grouped.get("cycles"):
        issues.append("the gradient bar has no cycle range")
    if plan.legend.mode == "grouped" and not plan.page.get("legend_plan"):
        issues.append("the grouped legend has no resolved layout")

    canvas = layout_style.canvas(config)
    checks["canvas_mm"] = [canvas["width_mm"], canvas["height_mm"]]

    if export_report is not None:
        issues.extend(_check_exports(export_report, checks, canvas))
        delivery = export_report.get("delivery") or {}
        if delivery:
            checks["delivery_files"] = sorted(delivery)
            absent = [key for key, info in delivery.items() if not info.get("exists")]
            if absent:
                issues.append("交付文件不存在：%s" % ", ".join(sorted(absent)))
        missing = export_report.get("missing_core_deliverables") or []
        if missing:
            checks["missing_core_deliverables"] = list(missing)
            issues.append("缺少核心交付物：%s" % ", ".join(missing))

    return {"level": LEVEL, "name": NAME, "checks": checks, "issues": issues,
            "ok": not issues}


def _check_exports(export_report: Dict, checks: Dict, canvas: Dict) -> List[str]:
    issues: List[str] = []
    files = export_report.get("files") or {}
    checks["export_files"] = dict(files)
    for key, present in files.items():
        if not present:
            issues.append("the %s export was not written" % key)

    svg = export_report.get("svg") or {}
    if svg:
        checks["svg_vector_elements"] = svg.get("vector_elements")
        checks["svg_image_elements"] = svg.get("image_elements")
        checks["svg_white_background"] = svg.get("white_background")
        if not svg.get("vector_elements"):
            issues.append("the SVG holds no vector elements")
        if svg.get("image_elements"):
            issues.append("the SVG embeds raster image nodes")
        if not svg.get("white_background"):
            issues.append("the SVG has no explicit white background")

    png = export_report.get("png") or {}
    if png:
        checks["png_size_px"] = [png.get("width"), png.get("height")]
        checks["png_dpi"] = png.get("density")
        checks["png_has_alpha"] = png.get("hasAlpha")
        corners_white = all(corner == [255, 255, 255] for corner in png.get("corners", []))
        checks["png_background_white"] = corners_white
        if png.get("hasAlpha"):
            issues.append("the PNG has an alpha channel (transparent export)")
        if not corners_white:
            issues.append("the PNG corners are not white")
        density = float(png.get("density") or 0)
        if density > 0:
            # The raster size must match the configured canvas; Origin rounds to whole
            # pixels, so the tolerance is a couple of pixels, not an absolute size.
            expected_px = [canvas["width_mm"] / 25.4 * density,
                           canvas["height_mm"] / 25.4 * density]
            checks["png_size_expected_px"] = [round(value, 1) for value in expected_px]
            for measured, wanted, axis in zip([png.get("width"), png.get("height")],
                                              expected_px, ("width", "height")):
                if measured is None or abs(float(measured) - wanted) > 3:
                    issues.append("the PNG %s is %s px, %.1f px expected for the configured "
                                  "canvas at %d dpi" % (axis, measured, wanted, int(density)))
        if export_report.get("expected_canvas_mm"):
            expected = export_report["expected_canvas_mm"]
            checks["expected_canvas_mm"] = list(expected)
            if [canvas["width_mm"], canvas["height_mm"]] != [float(v) for v in expected]:
                issues.append("the canvas in the resolved configuration (%s) differs from "
                              "the expected canvas (%s)"
                              % ([canvas["width_mm"], canvas["height_mm"]], list(expected)))

    unknown = export_report.get("issues") or []
    checks["export_issues"] = list(unknown)
    issues.extend(unknown)
    return issues
