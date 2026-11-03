"""Place an existing editable Origin legend using its measured physical box.

This adapter changes position, attachment and explicitly configured native bold.
It never abbreviates names, changes font family/size, hides data, or resizes the canvas. Origin objects must have
their final text/font and native annotations before :func:`place_legend` runs.
The caller still performs image review: an empty geometric collision score is
not evidence that the exported figure has passed visual acceptance.

Official interfaces: LabTalk Graphic Objects (attach, x/y, left/top/width/height)
and Label command.  Page/object physical coordinates are converted using the
actual native page dimensions, not data-axis dx/dy (which is unsafe for log axes).
"""

import math
import re

from ..style import typography
from . import native_text


_CORNERS = ("top_right", "top_left", "bottom_left", "bottom_right")
_POINT_TO_MM = 25.4 / 72.0


def _number(value, description):
    value = float(value)
    # Origin's missing sentinel is finite, so isfinite alone is insufficient.
    if not math.isfinite(value) or (value != 0 and abs(value) < 1e-250):
        raise RuntimeError("Origin did not return a numeric %s" % description)
    return value


def _object_name(name):
    if not isinstance(name, str) or not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", name):
        raise ValueError("native legend/label name must be a LabTalk identifier")
    return name


def _area(area):
    required = ("left_mm", "top_mm", "width_mm", "height_mm",
                "page_width_mm", "page_height_mm")
    result = {key: _number(area[key], "plot area %s" % key) for key in required}
    if any(result[key] <= 0 for key in required[2:]):
        raise ValueError("plot area and page dimensions must be positive")
    return result


def read_legend_bounds(backend, config, area, name):
    """Read only: return the final native box in page mm and plot fractions.

    ``normalized_box`` is [left, top, right, bottom], with origin at the plot's
    top-left.  The unrounded ``native_page`` values are retained for save/reopen
    evidence.  The same reader also works for native annotation text objects.
    """
    name, area = _object_name(name), _area(area)
    native = {key: _number(backend.value("page.%s" % key), "page.%s" % key)
              for key in ("width", "height")}
    if native["width"] <= 0 or native["height"] <= 0:
        raise RuntimeError("Origin page physical dimensions are not positive")
    obj = {key: _number(backend.value("%s.%s" % (name, key)), "%s.%s" % (name, key))
           for key in ("left", "top", "width", "height", "attach")}
    if obj["width"] <= 0 or obj["height"] <= 0:
        raise RuntimeError("native object %s has no measurable positive text box" % name)
    sx, sy = area["page_width_mm"] / native["width"], area["page_height_mm"] / native["height"]
    physical = {"left_mm": obj["left"] * sx, "top_mm": obj["top"] * sy,
                "width_mm": obj["width"] * sx, "height_mm": obj["height"] * sy}
    physical["right_mm"] = physical["left_mm"] + physical["width_mm"]
    physical["bottom_mm"] = physical["top_mm"] + physical["height_mm"]
    box = [(physical["left_mm"] - area["left_mm"]) / area["width_mm"],
           (physical["top_mm"] - area["top_mm"]) / area["height_mm"],
           (physical["right_mm"] - area["left_mm"]) / area["width_mm"],
           (physical["bottom_mm"] - area["top_mm"]) / area["height_mm"]]
    state = {"name": name, "attachment": int(obj["attach"]),
            "normalized_box": box, "physical_page_mm": physical,
            "native_page": dict(native, object=obj)}
    wanted_bold = typography.legend_bold(config)
    if wanted_bold is not None and name == getattr(backend, "_legend_object", "ScientificLegend"):
        state["typography"] = native_text.read_native_text_bold(backend, name, expected=wanted_bold)
    return state


def _axis(backend, name):
    first = _number(backend.value("layer.%s.from" % name), "%s.from" % name)
    last = _number(backend.value("layer.%s.to" % name), "%s.to" % name)
    scale = int(_number(backend.value("layer.%s.type" % name), "%s.type" % name))
    if scale not in (0, 1, 2):
        raise ValueError("native legend positioning supports linear/log10 axes, got %s" % scale)
    if first == last or (scale == 2 and min(first, last) <= 0):
        raise ValueError("native legend positioning requires a valid nonzero axis span")
    return {"from": first, "to": last, "scale": "log10" if scale == 2 else "linear"}


def _axis_fraction(value, axis):
    first, last, value = axis["from"], axis["to"], float(value)
    if not math.isfinite(value):
        raise ValueError("non-finite plotted coordinate in legend collision check")
    if axis["scale"] == "log10":
        if value <= 0:
            raise ValueError("nonpositive coordinate on a log10 axis")
        first, last, value = math.log10(first), math.log10(last), math.log10(value)
    return (value - first) / (last - first)


def _fraction_value(fraction, axis):
    first, last = axis["from"], axis["to"]
    if axis["scale"] == "log10":
        return 10 ** (math.log10(first) + fraction * (math.log10(last) - math.log10(first)))
    return first + fraction * (last - first)


def _intersects(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def _expand(box, rx, ry):
    return (box[0] - rx, box[1] - ry, box[2] + rx, box[3] + ry)


def _segment_hits_box(first, last, box):
    """Liang-Barsky clipping; catches segments whose endpoints miss the box."""
    dx, dy = last[0] - first[0], last[1] - first[1]
    lower, upper = 0.0, 1.0
    for p, q in ((-dx, first[0] - box[0]), (dx, box[2] - first[0]),
                 (-dy, first[1] - box[1]), (dy, box[3] - first[1])):
        if p == 0:
            if q < 0:
                return False
        else:
            bound = q / p
            if p < 0:
                lower = max(lower, bound)
            else:
                upper = min(upper, bound)
            if lower > upper:
                return False
    return True


def _scene(backend, plan, config, area, legend_name):
    """Transform every series through its actual native X and Y/Y2 scale."""
    axes, points, segments, annotations, unmeasured = {}, [], [], [], []
    ordinals = {}
    for item in plan.series:
        layer = int(item.layer) + 1
        ordinals[layer] = ordinals.get(layer, 0) + 1
        if layer not in axes:
            backend.run("layer -s %d;" % layer, expect=False)
            axes[layer] = {"x": _axis(backend, "x"), "y": _axis(backend, "y")}
        y_name = "y2" if getattr(item, "y_axis", "left") == "right" else "y"
        if y_name not in axes[layer]:
            backend.run("layer -s %d;" % layer, expect=False)
            axes[layer][y_name] = _axis(backend, y_name)
        transformed = [(_axis_fraction(x, axes[layer]["x"]),
                        1 - _axis_fraction(y, axes[layer][y_name])) for x, y in item.points]
        style = getattr(item, "style", None)
        shape = getattr(style, "symbol_shape", None)
        kind = getattr(item, "plot_kind", None)
        has_markers = kind in ("scatter", "line_points") or (shape and shape != "none")
        native_size, native_width = None, None
        if getattr(backend, "app", None) is not None and (getattr(style, "symbol_size_pt", None) is None or getattr(style, "line_width_pt", None) is None):
            # Unconfigured styles remain native defaults; measure their geometry.
            backend.run("layer -s %d; layer.plot=%d; get %%C -z nativeLegendSize; get %%C -wp nativeLegendWidth;" % (layer, ordinals[layer]), expect=False)
            native_size = _number(backend.value("nativeLegendSize"), "native marker size")
            native_width = _number(backend.value("nativeLegendWidth"), "native line width")
        if has_markers:
            size = float(getattr(style, "symbol_size_pt", None) or native_size or 0)
            radius = size * _POINT_TO_MM / 2
            # Native-marker plots already contain the selected source subset.
            indices = set(getattr(item, "marker_indices", None) or []) if getattr(item, "role", "data") != "native_marker" else set()
            for index, point in enumerate(transformed):
                if indices and index not in indices:
                    continue
                if 0 <= point[0] <= 1 and 0 <= point[1] <= 1:
                    points.append((point, radius / area["width_mm"], radius / area["height_mm"]))
        if kind != "scatter" and getattr(item, "role", "data") != "native_marker":
            half_width = float(getattr(style, "line_width_pt", None) or native_width or 0) * _POINT_TO_MM / 2
            for first, last in zip(transformed, transformed[1:]):
                segments.append((first, last, half_width / area["width_mm"], half_width / area["height_mm"]))
    backend.run("layer -s 1;", expect=False)
    for label in getattr(plan, "labels", []):
        if label.name == legend_name or label.role.startswith("axis_title") or not label.text:
            continue
        try:
            annotations.append(read_legend_bounds(backend, config, area, label.name)["normalized_box"])
        except (RuntimeError, ValueError, KeyError, TypeError):
            unmeasured.append(label.name)
    return {"axes": axes, "points": points, "segments": segments,
            "annotations": annotations, "unmeasured_labels": unmeasured}


def _score(box, scene):
    point_hits = sum(1 for point, rx, ry in scene["points"]
                     if _intersects((point[0], point[1], point[0], point[1]), _expand(box, rx, ry)))
    line_hits = sum(1 for first, last, rx, ry in scene["segments"]
                    if _segment_hits_box(first, last, _expand(box, rx, ry)))
    label_hits = sum(1 for obstacle in scene["annotations"] if _intersects(box, obstacle))
    return {"points": point_hits, "segments": line_hits, "labels": label_hits,
            "total": point_hits + line_hits + 10 * label_hits}


def _candidates(width, height, inset_x, inset_y, preferred):
    xmin, xmax = inset_x, 1 - inset_x - width
    ymin, ymax = inset_y, 1 - inset_y - height
    if xmin > xmax + 1e-12 or ymin > ymax + 1e-12:
        raise ValueError("native legend text box exceeds available plot area; provide an explicit layout/name decision")
    # A box exactly filling an available dimension is valid; guard float noise.
    xmax, ymax = max(xmin, xmax), max(ymin, ymax)
    corners = {"top_left": (xmin, ymin), "top_right": (xmax, ymin),
               "bottom_left": (xmin, ymax), "bottom_right": (xmax, ymax)}
    order = []
    for corner in list(preferred) + list(_CORNERS):
        if corner in corners and corner not in order:
            order.append(corner)
    seen = set()
    for key, left, top in [(key, *corners[key]) for key in order] + [
            ("grid_%d_%d" % (ix, iy), xmin + (xmax - xmin) * ix / 4,
             ymin + (ymax - ymin) * iy / 4) for iy in range(5) for ix in range(5)]:
        point = (round(left, 12), round(top, 12))
        if point not in seen:
            seen.add(point)
            yield key, [left, top, left + width, top + height]


def place_legend(backend, plan, config, area, name):
    """Position an existing legend without changing its content or appearance.

    Resolved ``plan.page.legend_layout`` / ``legend_plan`` overrides global
    ``config.legend``.  Supported positions are auto and the four named corners.
    A nonzero collision score or unmeasured label returns needs_image_review.
    """
    name, area = _object_name(name), _area(area)
    settings = dict(config.get("legend") or {})
    settings.update(plan.page.get("legend_plan") or {})
    settings.update(plan.page.get("legend_layout") or {})
    position = settings.get("position") or "auto"
    if position not in ("auto",) + _CORNERS:
        raise ValueError("legend position must be auto/top_left/top_right/bottom_left/bottom_right")
    inset = float(settings.get("inset_mm", 2.0))
    if not math.isfinite(inset) or inset < 0:
        raise ValueError("legend inset_mm must be finite and nonnegative")
    backend.run("layer -s 1; %s.attach=0;" % name, expect=False)
    # Bold changes the measured native text frame, so apply it before placement.
    native_text.apply_native_text_bold(backend, name, typography.legend_bold(config))
    measured = read_legend_bounds(backend, config, area, name)
    physical = measured["physical_page_mm"]
    width, height = physical["width_mm"] / area["width_mm"], physical["height_mm"] / area["height_mm"]
    preferred = settings.get("preferred_corners") or []
    if isinstance(preferred, str):
        preferred = [preferred]
    preferred = list(preferred)
    if settings.get("corner") in _CORNERS:
        preferred.insert(0, settings["corner"])
    if position != "auto":
        preferred.insert(0, position)
    candidates = list(_candidates(width, height, inset / area["width_mm"], inset / area["height_mm"], preferred))
    if position != "auto":
        candidates = [(key, box) for key, box in candidates if key == position]
    scene = _scene(backend, plan, config, area, name)
    scored = [(key, box, _score(box, scene)) for key, box in candidates]
    key, desired, planned_score = min(scored, key=lambda candidate: candidate[2]["total"])
    backend.run("layer -s 1;", expect=False)
    bounds = measured
    native_left = (area["left_mm"] + desired[0] * area["width_mm"]) * measured["native_page"]["width"] / area["page_width_mm"]
    native_top = (area["top_mm"] + desired[1] * area["height_mm"]) * measured["native_page"]["height"] / area["page_height_mm"]
    # Physical left/top are documented read/write properties. Avoid Origin's
    # x/y object-center conversion, which is not reliable on reversed log axes.
    for _ in range(3):
        backend.run("%s.left=%.17g; %s.top=%.17g;" % (name, native_left, name, native_top), expect=False)
        bounds = read_legend_bounds(backend, config, area, name)
        box = bounds["normalized_box"]
        error_x, error_y = desired[0] - box[0], desired[1] - box[1]
        if abs(error_x) < 1e-5 and abs(error_y) < 1e-5:
            break
        native_left += error_x * area["width_mm"] * measured["native_page"]["width"] / area["page_width_mm"]
        native_top += error_y * area["height_mm"] * measured["native_page"]["height"] / area["page_height_mm"]
    box = bounds["normalized_box"]
    # 0.1 mm allows native pixel rounding, without accepting a clipped legend.
    tolerance_x, tolerance_y = 0.1 / area["width_mm"], 0.1 / area["height_mm"]
    if box[0] < -tolerance_x or box[1] < -tolerance_y or box[2] > 1 + tolerance_x or box[3] > 1 + tolerance_y:
        raise RuntimeError("Origin placed native legend outside the plot frame after positioning")
    final_score = _score(box, scene)
    status = "needs_image_review" if final_score["total"] or scene["unmeasured_labels"] else "positioned"
    return dict(bounds, status=status, position=position, selected_candidate=key,
                collision_score=final_score, planned_collision_score=planned_score,
                unmeasured_labels=scene["unmeasured_labels"], image_review_required=True,
                desired_normalized_box=desired)
