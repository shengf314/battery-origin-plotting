"""Independent scientific title and saved display-range acceptance.

Explicit endpoints come from the plan, while automatic display endpoints use
the pre-save native configuration baseline. Data extents are never substitutes
for display ranges. This module only checks readbacks; it never mutates Origin.
"""

import math
from copy import deepcopy

from ..style import typography


PHYSICAL_AXES = {"bottom": "x", "top": "x2", "left": "y", "right": "y2"}
TITLE_OBJECTS = {"bottom": "xb", "left": "yl", "right": "yr"}


def _finite(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float)) and
            math.isfinite(value))


def _close(actual, expected):
    return (_finite(actual) and _finite(expected) and
            math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9))


def _lines(text):
    # Only the two observed line serializations; preserve every other character,
    # including whitespace and all Origin rich-text commands.
    return str(text).replace("\r\n", "\n").replace("\\n", "\n").split("\n")


def expected_title_lines(text, bold=None):
    if bold is not None and not isinstance(bold, bool):
        raise ValueError("native axis title bold must be boolean or null")
    lines = _lines(text)
    return ["\\b(%s)" % line for line in lines] if bold is True else lines


def _native_dual_y(plan):
    return (plan.page.get("axis_capability") == "native_dual_y" and
            plan.page.get("axis_mode") == "single_layer_native_y2")


def _layer_key(index):
    return "left" if index == 0 else "right"


def _override(plan, layer_index, side):
    ranges = plan.page.get("axis_ranges_override") or {}
    key = None
    if side == "bottom":
        key = "x"
    elif side == "left":
        key = "y_right" if layer_index > 0 and ranges.get("y_right") else "y"
    elif side == "right" and layer_index == 0 and _native_dual_y(plan):
        key = "y_right"
    pair = ranges.get(key) if key else None
    if pair is None:
        return None, None
    if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or
            not all(_finite(value) for value in pair) or pair[0] == pair[1]):
        raise ValueError("axis_ranges_override.%s requires two distinct finite endpoints" % key)
    return list(pair), "plan.page.axis_ranges_override.%s" % key


def planned_endpoints(plan, layer_index, side, spec, baseline=None):
    """Resolve the same narrow precedence as the native adapter.

    AxisSpec non-null endpoints override a page range. Direction orders the
    resulting endpoints. Undeclared endpoints require the captured native
    baseline; a standalone saved read is deliberately insufficient evidence.
    """
    pair, source = _override(plan, layer_index, side)
    values = list(pair or [None, None])
    sources = [source, source]
    for position, value in enumerate((spec.from_, spec.to)):
        if value is not None:
            if not _finite(value):
                raise ValueError("AxisSpec %s endpoint must be finite" % side)
            values[position] = value
            sources[position] = "AxisSpec.%s" % ("from_" if position == 0 else "to")
    if spec.direction == "descending" and values.count(None) == 1 and baseline:
        # A single explicit endpoint can become either physical endpoint after
        # reversal. Recover the *other* configured endpoint from the frozen pair,
        # rather than filling from the identically named final endpoint.
        known = values[0] if values[0] is not None else values[1]
        missing = 0 if values[0] is None else 1
        other = baseline.get("to") if _close(baseline.get("from"), known) else baseline.get("from")
        values[missing] = other
        sources[missing] = "pre-save configured native display baseline"
    for position, name in enumerate(("from", "to")):
        if values[position] is None and baseline:
            values[position] = baseline.get(name)
            sources[position] = "pre-save configured native display baseline"
    if spec.direction not in ("ascending", "descending"):
        raise ValueError("invalid scientific axis direction %r" % spec.direction)
    # The renderer reverses endpoints only for a declared descending axis.
    if spec.direction == "descending" and all(_finite(value) for value in values):
        ordered = sorted(zip(values, sources), key=lambda item: item[0], reverse=True)
        values, sources = [item[0] for item in ordered], [item[1] for item in ordered]
    return values, sources


def capture_axis_contract(plan, config, native_axis):
    """Freeze actual configured display endpoints before export/save."""
    baseline = deepcopy(native_axis)
    result = {"schema_version": 1,
              "basis": "independent plan titles/explicit endpoints + pre-save configured native display baseline",
              "native_dual_y": _native_dual_y(plan), "axes": [], "titles": []}
    for index, layer in enumerate(plan.layers):
        for side, spec in layer.axes.items():
            state = ((baseline.get("layers") or {}).get(_layer_key(index)) or {}).get(side) or {}
            endpoints, sources = planned_endpoints(plan, index, side, spec, state)
            if not all(_finite(value) for value in endpoints):
                raise RuntimeError("configured layer %d %s display endpoints could not be captured" % (index + 1, side))
            result["axes"].append({"layer": index + 1, "side": side,
                                     "native_axis": PHYSICAL_AXES[side],
                                     "expected_from": endpoints[0], "expected_to": endpoints[1],
                                     "endpoint_sources": sources,
                                     "configured_from": state.get("from"), "configured_to": state.get("to")})
    bold = typography.axis_title_bold(config)
    # These are the existing adapter's native special title objects. Empty
    # labels retain the template's unused title and are not scientific claims.
    if plan.layers:
        for side, name in TITLE_OBJECTS.items():
            spec = plan.layers[0].axes.get(side)
            if spec and spec.label:
                result["titles"].append({"layer": 1, "side": side, "object": name,
                                         "semantic_text": str(spec.label),
                                         "expected_native_lines": expected_title_lines(spec.label, bold)})
    return result


def verify_axis_contract(plan, config, native_axis, contract=None):
    """Compare reopened readbacks against an independently established contract."""
    issues, axes, titles = [], [], []
    baseline_map = {(entry["layer"], entry["side"]): entry
                    for entry in (contract or {}).get("axes", [])}
    for index, layer in enumerate(plan.layers):
        actual_layer = ((native_axis.get("layers") or {}).get(_layer_key(index)) or {})
        for side, spec in layer.axes.items():
            actual = actual_layer.get(side) or {}
            baseline = baseline_map.get((index + 1, side))
            baseline_values = ({"from": baseline.get("configured_from"),
                                "to": baseline.get("configured_to")} if baseline else None)
            try:
                endpoints, sources = planned_endpoints(plan, index, side, spec, baseline_values)
            except (ValueError, TypeError) as exc:
                issues.append("reopened layer %d %s invalid range contract: %s" % (index + 1, side, exc))
                endpoints, sources = [None, None], [None, None]
            equality = [_close(actual.get(name), expected)
                        for name, expected in zip(("from", "to"), endpoints)]
            entry = {"layer": index + 1, "side": side, "native_axis": actual.get("native_axis"),
                     "expected_native_axis": PHYSICAL_AXES[side],
                     "actual_from": actual.get("from"), "actual_to": actual.get("to"),
                     "expected_from": endpoints[0], "expected_to": endpoints[1],
                     "endpoint_sources": sources, "from_equal": equality[0], "to_equal": equality[1]}
            if actual.get("native_axis") != PHYSICAL_AXES[side] or actual.get("read_error"):
                issues.append("reopened layer %d %s native axis read/mapping differs" % (index + 1, side))
            if not all(_finite(value) for value in endpoints):
                issues.append("reopened layer %d %s automatic display range lacks an independent pre-save baseline" % (index + 1, side))
            elif not all(equality):
                issues.append("reopened layer %d %s display range differs from the scientific/configured contract" % (index + 1, side))
            if _native_dual_y(plan) and side in ("left", "right") and actual.get("independent_y_scale") != 1:
                issues.append("reopened native dual-Y independent scale differs")
            axes.append(entry)
    if plan.layers:
        bold = typography.axis_title_bold(config)
        for side, name in TITLE_OBJECTS.items():
            spec = plan.layers[0].axes.get(side)
            if not spec or not spec.label:
                continue
            actual = (native_axis.get("titles") or {}).get(side) or {}
            expected = expected_title_lines(spec.label, bold)
            read_ok = actual.get("text") is not None and not actual.get("read_error")
            equal = read_ok and _lines(actual["text"]) == expected
            entry = {"layer": 1, "side": side, "object": name,
                     "semantic_text": str(spec.label), "actual_text": actual.get("text"),
                     "expected_native_lines": expected, "text_equal": bool(equal),
                     "actual_show": actual.get("show")}
            if not equal:
                issues.append("reopened native %s axis title text/unit differs from the scientific plan" % side)
            if actual.get("show") != 1:
                issues.append("reopened native %s scientific axis title is hidden or unreadable" % side)
            titles.append(entry)
    return {"ok": not issues, "issues": issues, "axes": axes, "titles": titles,
            "basis": "planned title/explicit endpoints; automatic endpoints require pre-save configured native baseline",
            "tolerance": {"relative": 1e-9, "absolute": 1e-9},
            "native_dual_y": _native_dual_y(plan)}
