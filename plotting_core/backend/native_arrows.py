"""Native editable Origin arrows declared as layer-frame geometry.

Official LabTalk interfaces: Draw -lm creates a named two-point line; Graphic
Objects arrowBeginShape/arrowEndShape enable heads; x#/y# read actual endpoints.
Production defaults to documented axes-scale attachment (2). Layer/page
attachment is an explicit probe path: no percent-coordinate assumption is made.
The helper never inserts SVG/images, edits exports, or changes supplied data.
"""

import math
import re


TOLERANCE_MM = 0.2
_PROPERTIES = ("type", "attach", "show", "x1", "y1", "x2", "y2", "left", "top",
               "width", "height", "lineType", "lineWidth", "color", "arrowBeginShape",
               "arrowEndShape", "arrowEndLength", "arrowEndWidth", "hMove", "vMove")


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError("%s must be numeric" % name)
    value = float(value)
    if not math.isfinite(value) or (value != 0 and abs(value) < 1e-250):
        raise RuntimeError("Origin did not return a numeric %s" % name)
    return value


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise ValueError("native arrow name must be a LabTalk identifier")
    return value


def _fraction_pair(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("native arrow %s must be a layer-fraction XY pair" % name)
    result = [_number(item, "arrow %s" % name) for item in value]
    if any(item < 0 or item > 1 for item in result):
        raise ValueError("native arrow %s must be inside the layer frame" % name)
    return result


def _axes(backend):
    axes = {}
    for key in ("x", "y"):
        axes[key] = {name: _number(backend.value("layer.%s.%s" % (key, name)), "%s.%s" % (key, name))
                     for name in ("from", "to", "type")}
        if int(axes[key]["type"]) not in (0, 1) or axes[key]["from"] >= axes[key]["to"]:
            raise ValueError("native arrow layer fractions currently require ascending linear X/left Y")
    return axes


def _scale_point(point, axes):
    return [axes[key]["from"] + float(value) * (axes[key]["to"] - axes[key]["from"])
            for key, value in zip(("x", "y"), point)]


def _fraction_point(point, axes):
    return [(float(value) - axes[key]["from"]) / (axes[key]["to"] - axes[key]["from"])
            for key, value in zip(("x", "y"), point)]


def _physical_frame(backend, native, area):
    """Read frame geometry for evidence only; never use text-frame setters.

    width/height are documented read-only layer-coordinate dimensions. The raw
    values and page dimensions are retained; candidate page-mm conversion uses
    the calibration already used by this Origin backend, not percent endpoints.
    """
    page = {key: _number(backend.value("page.%s" % key), "page.%s" % key) for key in ("width", "height")}
    if page["width"] <= 0 or page["height"] <= 0:
        raise RuntimeError("Origin page dimensions must be positive")
    sx, sy = float(area["page_width_mm"]) / page["width"], float(area["page_height_mm"]) / page["height"]
    frame = {"left_mm": native["left"] * sx, "top_mm": native["top"] * sy,
             "width_mm": native["width"] * sx, "height_mm": native["height"] * sy}
    frame.update(right_mm=frame["left_mm"] + frame["width_mm"],
                 bottom_mm=frame["top_mm"] + frame["height_mm"])
    return {"physical_page_mm_candidate": frame, "raw_page_dimensions": page,
            "frame_conversion": "page-dimension calibration; actual arrow frame requires image inspection"}


def _read(backend, name, axes, area):
    native = {key: _number(backend.value("%s.%s" % (name, key)), "%s.%s" % (name, key)) for key in _PROPERTIES}
    tail, head = [native["x1"], native["y1"]], [native["x2"], native["y2"]]
    return dict(name=name, native=native, object_type=backend.text("%s.type$" % name),
                attachment_name=backend.text("%s.attach$" % name), axes=axes,
                endpoints_axis_coordinates={"tail": tail, "head": head},
                endpoints_layer_fraction={"tail": _fraction_point(tail, axes), "head": _fraction_point(head, axes)},
                **_physical_frame(backend, native, area))


def _endpoint_errors(state, rule, area):
    errors = []
    for end in ("tail", "head"):
        actual, requested = state["endpoints_layer_fraction"][end], rule[end]
        if (abs(actual[0] - requested[0]) * float(area["width_mm"]) > TOLERANCE_MM or
                abs(actual[1] - requested[1]) * float(area["height_mm"]) > TOLERANCE_MM):
            errors.append("%s actual %s endpoint differs from its layer-fraction declaration" % (rule["name"], end))
    return errors


def _rules(plan):
    values = plan.page.get("native_arrows") or []
    if not isinstance(values, list):
        raise ValueError("plan.page.native_arrows must be a list")
    names, result = set(), []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("each native arrow declaration must be an object")
        rule = dict(value)
        rule["name"] = _name(rule.get("name"))
        if rule["name"] in names:
            raise ValueError("duplicate native arrow name")
        names.add(rule["name"])
        layer = rule.get("layer", 0)
        if isinstance(layer, bool) or not isinstance(layer, int) or not 0 <= layer < len(plan.layers):
            raise ValueError("native arrow layer is invalid")
        rule["layer"] = layer
        if rule.get("coordinate_system", "layer_fraction") != "layer_fraction":
            raise ValueError("native arrows require declared layer_fraction geometry")
        if rule.get("role", "axis_indicator") != "axis_indicator" or rule.get("target_axis") not in ("left", "right"):
            raise ValueError("native arrow requires an axis_indicator role and left/right target_axis")
        attachment = rule.get("attachment", 2)
        if isinstance(attachment, bool) or attachment not in (0, 1, 2):
            raise ValueError("native arrow attachment must be 0, 1 or 2")
        rule["attachment"] = attachment
        rule["tail"], rule["head"] = _fraction_pair(rule.get("tail"), "tail"), _fraction_pair(rule.get("head"), "head")
        if rule["head"] == rule["tail"]:
            raise ValueError("native arrow endpoints must be distinct")
        if ((rule["target_axis"] == "left" and rule["head"][0] >= rule["tail"][0]) or
                (rule["target_axis"] == "right" and rule["head"][0] <= rule["tail"][0])):
            raise ValueError("native arrow head must point toward its declared left/right axis")
        style = rule.get("style") or {}
        if not isinstance(style, dict) or set(style) - {'line_width_pt','head_length_pt','head_width_pt'}:
            raise ValueError('native arrow style permits only declared positive point dimensions')
        for key, value in style.items():
            if _number(value, key) <= 0:
                raise ValueError('native arrow dimensions must be positive')
        rule['style'] = style
        metric = rule.get("metric")
        if metric and not any(item.layer == layer and item.metric == metric and item.y_axis == rule["target_axis"]
                              for item in plan.series):
            raise ValueError("native arrow metric/axis declaration does not match any native series binding")
        result.append(rule)
    return result


def _create_line(backend, name, tail, head, axes):
    first, last = _scale_point(tail, axes), _scale_point(head, axes)
    backend.run("draw -n %s -lm {%.17g,%.17g,%.17g,%.17g};" % (name, first[0], first[1], last[0], last[1]))
    # Do not rely on @AR or current tool preferences to choose attachment.
    backend.run("%s.attach=2;" % name, expect=False)


def probe_native_arrow_attachment(backend, name, tail, head, area, attachment=0):
    """Explicit disposable-graph probe; caller owns the Origin session/save.

    Create a documented axes-scale line, capture raw endpoints and physical
    frame, switch attachment, and read again. No percent semantics are assumed.
    This does create a native object; call only in a caller-owned test graph.
    """
    name, tail, head = _name(name), _fraction_pair(tail, "tail"), _fraction_pair(head, "head")
    if attachment not in (0, 1, 2):
        raise ValueError("arrow attachment probe requires 0/1/2")
    axes = _axes(backend)
    _create_line(backend, name, tail, head, axes)
    before = _read(backend, name, axes, area)
    backend.run("%s.attach=%d; draw -n %s -u;" % (name, attachment, name), expect=False)
    after = _read(backend, name, axes, area)
    rule = dict(name=name, tail=tail, head=head)
    issues = _endpoint_errors(before, rule, area) + _endpoint_errors(after, rule, area)
    if int(after["native"]["attach"]) != attachment:
        issues.append("native arrow attachment switch did not persist")
    for key in ("left", "top", "width", "height"):
        # Retain raw before/after values; physical behavior after rescale/moving
        # a layer still needs an independent caller-controlled experiment.
        if abs(before["native"][key] - after["native"][key]) > 1e-5:
            issues.append("attachment switch changed raw native %s" % key)
    return {"ok": not issues, "issues": issues, "before": before, "after": after,
            "scope": "current graph attachment transition only; no general attachment capability claim"}


def insert_native_arrows(backend, plan, config, area):
    """Insert named native end-head arrows with explicitly declared dimensions."""
    rules, states, issues = _rules(plan), [], []
    if not rules:return {'ok':True,'issues':[],'arrows':[],'enabled':False}
    for rule in rules:
        backend.run("layer -s %d;" % (rule["layer"] + 1), expect=False)
        axes, name = _axes(backend), rule["name"]
        attachment_probe = None
        if rule["attachment"] == 2:
            _create_line(backend, name, rule["tail"], rule["head"], axes)
        else:
            attachment_probe = probe_native_arrow_attachment(backend, name, rule["tail"], rule["head"], area, rule["attachment"])
            if not attachment_probe["ok"]:
                # Keep the failed experiment as evidence. Do not silently use
                # percent coordinates or change the declaration's attachment.
                raise RuntimeError("Native arrow attachment probe blocked: %s" % "; ".join(attachment_probe["issues"]))
        defaults = _read(backend, name, axes, area)
        # Origin 2024 uses the documented 1-based head enum: 1 None, 2 Filled.
        # Execute success alone is insufficient (unsupported 0 silently stays 1).
        backend.run("%s.color=color(black); %s.arrowBeginShape=1; %s.arrowEndShape=2; draw -n %s -u;"
                    % (name, name, name, name))
        for key, prop in (('line_width_pt','lineWidth'),('head_length_pt','arrowEndLength'),('head_width_pt','arrowEndWidth')):
            if key in rule['style']:
                backend.run('%s.%s=%.17g;' % (name,prop,rule['style'][key]))
        backend.run('draw -n %s -u;' % name)
        state = _read(backend, name, axes, area)
        errors = _endpoint_errors(state, rule, area)
        native = state["native"]
        if int(native["type"]) != 2 or int(native["arrowBeginShape"]) != 1 or int(native["arrowEndShape"]) != 2:
            errors.append("%s is not a native line with one filled end head" % name)
        if int(native["attach"]) != rule["attachment"] or int(native["show"]) != 1:
            errors.append("%s native attachment or visibility differs" % name)
        if native["arrowEndLength"] <= 0 or native["arrowEndWidth"] <= 0:
            errors.append("%s native default head dimensions do not draw a visible head" % name)
        for key, prop in (('line_width_pt','lineWidth'),('head_length_pt','arrowEndLength'),('head_width_pt','arrowEndWidth')):
            requested=rule['style'].get(key,defaults['native'][prop])
            if not math.isclose(native[prop],requested,abs_tol=.01):
                errors.append('%s native %s differs from its declared/default dimension' % (name,prop))
        states.append(dict(state, declaration=rule, native_defaults=defaults,
                           attachment_probe=attachment_probe, issues=errors,
                           status="created" if not errors else "blocked", image_review_required=True))
        issues.extend(errors)
    backend.run("layer -s 1;", expect=False)
    report = {"ok": not issues, "issues": issues, "arrows": states,
              "method": "native named Draw line + filled EndShape, documented scale endpoints, actual property readback",
              "tolerance_mm": TOLERANCE_MM, "image_review_required": True}
    backend._arrow_state = report
    if issues:
        raise RuntimeError("Native arrow insertion blocked: %s" % "; ".join(issues))
    return report


def verify_native_arrows(backend, plan, config, area, expected=None):
    """Read saved/reopened native arrow identity, endpoints and default style."""
    rules, states, issues = _rules(plan), [], []
    if not rules:return {'ok':True,'issues':[],'arrows':[],'enabled':False}
    previous = {state["name"]: state for state in (expected or {}).get("arrows", [])}
    for rule in rules:
        name = rule["name"]
        backend.run("layer -s %d;" % (rule["layer"] + 1), expect=False)
        state = _read(backend, name, _axes(backend), area)
        errors = _endpoint_errors(state, rule, area)
        native = state["native"]
        if (int(native["type"]) != 2 or int(native["attach"]) != rule["attachment"] or
                int(native["show"]) != 1 or int(native["arrowBeginShape"]) != 1 or
                int(native["arrowEndShape"]) != 2):
            errors.append("%s reopened native object type/attachment/visibility/head differs" % name)
        if native["arrowEndLength"] <= 0 or native["arrowEndWidth"] <= 0:
            errors.append("%s reopened native head has no positive size" % name)
        if name in previous:
            for key in ("type", "attach", "show", "lineType", "lineWidth", "color",
                        "arrowBeginShape", "arrowEndShape", "arrowEndLength", "arrowEndWidth"):
                if not math.isclose(native[key], previous[name]["native"][key], abs_tol=1e-7, rel_tol=1e-8):
                    errors.append("%s reopened native %s differs from rendered evidence" % (name, key))
        states.append(dict(state, declaration=rule, issues=errors, equal=not errors,
                           image_review_required=True))
        issues.extend(errors)
    backend.run("layer -s 1;", expect=False)
    return {"ok": not issues, "issues": issues, "arrows": states,
            "method": "saved native object/endpoints/style readback; target_axis remains declared scientific meaning",
            "tolerance_mm": TOLERANCE_MM, "image_review_required": True}
