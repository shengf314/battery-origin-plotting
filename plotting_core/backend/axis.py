"""Origin-native axis formatting.

This module is the single adapter between a :class:`~plotting_core.models.AxisSpec`
and Origin's Axis dialog objects.  It deliberately emits only ``layer.x``,
``layer.x2``, ``layer.y`` and ``layer.y2`` properties (and Origin's built-in
axis-title objects); it never creates line, text, label, rectangle, or image
objects to imitate an axis.
"""

from typing import Dict, List, Optional

from ..models import AxisSpec, RenderingPlan
from ..style import ticks as tick_style
from ..style import typography
from . import labtalk
from . import native_text


# Origin Axis > Line and Ticks bit mask.  Keep these values here rather than
# turning template values into an unrelated private convention.
TICK_MASKS = {
    "in": (1, 4),
    "out": (2, 8),
    "both": (3, 12),
}

PHYSICAL_AXIS_MAP = {"x": "bottom", "x2": "top", "y": "left", "y2": "right"}
TITLE_OBJECTS = {"bottom": "xb", "left": "yl", "right": "yr"}


class AxisFormatter:
    """Apply Scale, Tick Labels, Line and Ticks, and titles through Origin.

    ``origin`` is the small execution surface supplied by ``OriginBackend``:
    it provides ``run``, ``value`` and ``text``.  Keeping it narrow makes the
    formatter easy to test without an Origin process and isolates LabTalk
    compatibility handling from data renderers.
    """

    def __init__(self, origin, config: Dict):
        self.origin = origin
        self.config = config

    @staticmethod
    def uses_native_dual_y(plan: RenderingPlan) -> bool:
        """Whether a plan declared the reusable one-layer Y/Y2 capability."""
        return (plan.page.get("axis_capability") == "native_dual_y" and
                plan.page.get("axis_mode") == "single_layer_native_y2")

    def prepare_structure(self, plan: RenderingPlan) -> None:
        """Enable the Origin 2023+ independent Y/Y2 mechanism before plotting."""
        if not self.uses_native_dual_y(plan):
            return
        if len(plan.layers) != 1:
            raise ValueError("native_dual_y requires exactly one Origin layer")
        structure = (self.config.get("dual_y") or {}).get("structure") or {}
        if not (structure.get("single_layer") and structure.get("native_y2") and
                structure.get("independent_scale")):
            raise ValueError("resolved dual_y template does not permit native independent Y2")
        self.origin.run("layer -s 1; layer.y.IndivScale=1;", expect=False)
        if self.origin.value("layer.y.IndivScale") != 1:
            raise RuntimeError("Origin lacks the requested native independent Y/Y2 capability")

    def read_ranges(self, plan: RenderingPlan) -> Dict[str, Dict[str, List[float]]]:
        """Apply explicit native scale bounds (if any) and read Origin's ranges."""
        ranges = {}
        layers = len(plan.layers) if plan.layers else 1
        native_dual_y = self.uses_native_dual_y(plan)
        override = plan.page.get("axis_ranges_override") or {}
        for index in range(1, layers + 1):
            self.origin.run("layer -s %d;" % index)
            self._set_semantic_scales(plan.layers[index - 1])
            statements = []
            if override.get("x"):
                statements.append("layer.x.from=%s; layer.x.to=%s;" %
                                  (override["x"][0], override["x"][1]))
            y_override = override.get("y_right" if index > 1 else "y") or override.get("y")
            if y_override:
                statements.append("layer.y.from=%s; layer.y.to=%s;" %
                                  (y_override[0], y_override[1]))
            if statements:
                self.origin.run(" ".join(statements))
            ranges["left" if index == 1 else "right"] = {
                "x": [self.origin.value("layer.x.from"), self.origin.value("layer.x.to")],
                "y": [self.origin.value("layer.y.from"), self.origin.value("layer.y.to")],
            }
            if native_dual_y and index == 1:
                if override.get("y_right"):
                    self.origin.run("layer.y2.from=%s; layer.y2.to=%s;" %
                                    (override["y_right"][0], override["y_right"][1]))
                ranges["left"]["y2"] = [self.origin.value("layer.y2.from"),
                                        self.origin.value("layer.y2.to")]
        if layers > 1:
            self.origin.run("layer -s 1;")
        return ranges

    def _set_semantic_scales(self, layer) -> None:
        """Set scientific axis scales before rescaling; 2D reversal uses endpoints."""
        changed = False
        for axis, side in PHYSICAL_AXIS_MAP.items():
            spec = layer.axes.get(side)
            if spec and spec.scale_type == "log10" and spec.direction == "descending":
                raise ValueError("Origin reversed log10 axes are blocked: saved endpoints can pass while exported physical Y-axis position changes; a dedicated native/image verification is required")
            if spec and spec.scale_type:
                if spec.scale_type not in ("linear", "log10"):
                    raise ValueError("unsupported scientific scale %r" % spec.scale_type)
                self.origin.run("layer.%s.type=%d;" % (axis, 2 if spec.scale_type == "log10" else 1))
                changed = True
        if changed:
            self.origin.run("layer -a;")

    def plan_intervals(self, axis_ranges: Dict[str, Dict[str, List[float]]], plan=None) -> Dict:
        """Choose only a native major increment; do not manufacture label text."""
        cfg = self.config.get("axis_ticks") or {}
        if (cfg.get("major_tick_type") or "by_increment") != "by_increment":
            raise ValueError("axis_ticks.major_tick_type must be 'by_increment'")
        target = int(cfg.get("target_major_tick_count") or 5)
        requested = cfg.get("major_interval") or "auto"
        intervals = {}
        for layer_key, ranges in axis_ranges.items():
            for axis in ("x", "y", "y2"):
                if axis not in ranges:
                    continue
                low, high = ranges[axis]
                side = PHYSICAL_AXIS_MAP[axis]
                layer_idx = 0 if layer_key == "left" else 1
                spec = plan.layers[layer_idx].axes.get(side) if plan else None
                if spec and spec.tick_labels:
                    intervals["%s_%s" % (layer_key, axis)] = {
                        "major_mode": "increment", "interval": 1, "minor_ticks": False,
                        "minor_tick_count": 0}
                    continue
                if spec and spec.scale_type == "log10":
                    # Arithmetic half-steps are a continuous linear-axis rule.
                    # Log minor ticks require their own explicitly declared count.
                    log_count = cfg.get("log_minor_tick_count")
                    self._validate_minor_count(log_count)
                    intervals["%s_%s" % (layer_key, axis)] = {
                        "major_mode": "increment", "interval": 1, "scale_type": "log10",
                        "minor_ticks": bool(log_count), "minor_tick_count": log_count or 0}
                    continue
                native = tick_style.nice_ticks(
                    min(low, high), max(low, high), interval="auto" if requested in (None, "auto") else requested,
                    target=target)
                count = (self.config.get("axes") or {}).get("minor_tick_count")
                if count is None:
                    count = cfg.get("minor_tick_count")
                self._validate_minor_count(count)
                intervals["%s_%s" % (layer_key, axis)] = {
                    "major_mode": "increment",
                    "interval": native["interval"],
                    "minor_ticks": bool(cfg.get("minor_ticks", False)),
                    "minor_tick_count": count,
                }
        return intervals

    def apply(self, plan: RenderingPlan, intervals: Dict) -> Dict:
        """Apply all configured axes and return properties read from Origin."""
        for index, layer in enumerate(plan.layers or [], start=1):
            self._apply_layer(layer, index, intervals)
        self._apply_titles(plan)
        return self.inspect(plan)

    def _apply_layer(self, layer, index: int, intervals: Dict) -> None:
        self.origin.run("layer -s %d;" % index)
        self._apply_axis_visibility(layer)
        for native_axis, side in PHYSICAL_AXIS_MAP.items():
            spec = layer.axes.get(side)
            if spec is None:
                continue
            interval = self._interval_for(index, native_axis, intervals)
            statements = []
            statements.extend(self.apply_axis_scale(native_axis, spec, interval))
            statements.extend(self.apply_tick_labels(native_axis, spec))
            statements.extend(self.apply_line_and_ticks(native_axis, spec, interval))
            self.origin.run(" ".join(statements), expect=False)

    def _apply_axis_visibility(self, layer) -> None:
        """Expose each frame side through the owning Origin X/Y axis bit mask."""
        bottom, top = layer.axes.get("bottom"), layer.axes.get("top")
        left, right = layer.axes.get("left"), layer.axes.get("right")
        x_mask = ((1 if bottom and bottom.show_axis else 0) |
                  (2 if top and top.show_axis else 0))
        y_mask = ((1 if left and left.show_axis else 0) |
                  (2 if right and right.show_axis else 0))
        self.origin.run("layer.x.showaxes=%d; layer.y.showaxes=%d;" % (x_mask, y_mask),
                        expect=False)

    def apply_axis_scale(self, axis: str, spec: AxisSpec, interval: Optional[Dict]) -> List[str]:
        """Return Origin-native Scale property statements for one axis."""
        scale_type = spec.scale_type or (self.config.get("axes") or {}).get("scale_type") or "linear"
        if scale_type not in ("linear", "log10"):
            raise ValueError("unsupported Origin axis scale_type %r" % scale_type)
        if scale_type == "log10" and spec.direction == "descending":
            raise ValueError("Origin reversed log10 axes are blocked: saved endpoints can pass while exported physical Y-axis position changes; a dedicated native/image verification is required")
        # Origin accepts 0 or 1 for Linear.  Use 1 to match Axis-dialog's native
        # Linear representation found in the audited reference project.
        statements = ["layer.%s.type=%d;" % (axis, 2 if scale_type == "log10" else 1)]
        rescale = ((self.config.get("axes") or {}).get("rescale_behavior") or
                   "normal").lower().replace("_", " ")
        rescale_values = {"manual": 1, "normal": 2, "auto": 3,
                          "fixed from": 4, "fixed to": 5}
        if rescale not in rescale_values:
            raise ValueError("unsupported Origin rescale_behavior %r" % rescale)
        statements.append("layer.%s.rescale=%d;" % (axis, rescale_values[rescale]))
        if spec.from_ is not None:
            statements.append("layer.%s.from=%s;" % (axis, spec.from_))
        if spec.to is not None:
            statements.append("layer.%s.to=%s;" % (axis, spec.to))
        if spec.direction not in ("ascending", "descending"):
            raise ValueError("invalid scientific axis direction %r" % spec.direction)
        if spec.direction == "descending":
            # Pending explicit assignments must participate in reversal. Reading
            # only the old native values here silently discarded requested bounds.
            low = spec.from_ if spec.from_ is not None else self.origin.value("layer.%s.from" % axis)
            high = spec.to if spec.to is not None else self.origin.value("layer.%s.to" % axis)
            statements.append("layer.%s.from=%s; layer.%s.to=%s;" %
                              (axis, max(low, high), axis, min(low, high)))
        if interval:
            # An empty explicit list keeps Axis > Major Ticks > Type as By Increment.
            statements.append('layer.%s.ticksbydata$="";' % axis)
            increment = abs(interval["interval"])
            if spec.direction == "descending":
                increment = -increment
            statements.append("layer.%s.inc=%s;" % (axis, increment))
        count = interval.get("minor_tick_count") if interval and "minor_tick_count" in interval else (self.config.get("axes") or {}).get("minor_tick_count")
        if count is None and not (interval and "minor_tick_count" in interval):
            count = (self.config.get("axis_ticks") or {}).get("minor_tick_count")
        if count is not None:
            self._validate_minor_count(count)
            # Remove a template's custom minor-position dataset before By Counts.
            statements.append('layer.%s.mticksbydata$="";' % axis)
            statements.append("layer.%s.minorTicks=%d;" % (axis, int(count)))
        return statements

    @staticmethod
    def _validate_minor_count(count) -> None:
        if count is not None and (isinstance(count, bool) or not isinstance(count, (int, float)) or
                                  count < 0 or int(count) != count):
            raise ValueError("minor_tick_count must be a non-negative integer or null")

    def apply_tick_labels(self, axis: str, spec: AxisSpec) -> List[str]:
        """Use Origin numeric tick labels only; never add label/text objects."""
        labels = self.config.get("labels") or {}
        font = typography.font_family(self.config)
        size = typography.tick_label_size_pt(self.config)
        decimal = labels.get("tick_label_decimal_places")
        rotation = labels.get("tick_label_rotation_deg")
        offset_h = labels.get("tick_label_offset_h")
        offset_v = labels.get("tick_label_offset_v")
        bold = typography.tick_label_bold(self.config)
        label_color = labels.get("tick_label_color") or (self.config.get("axes") or {}).get("tick_label_color")
        statements = [
            "layer.%s.label.type=%d;" % (axis, 2 if spec.label_dataset else 1),
            "layer.%s.label.font=font(%s);" % (axis, font),
            "layer.%s.label.pt=%s;" % (axis, size),
            "layer.%s.label.numformat=1;" % axis,
            "layer.%s.label.decplaces=%s;" % (axis, -1 if decimal is None else decimal),
        ]
        if spec.label_dataset:
            statements.append('layer.%s.labelText$="%s";' % (axis, spec.label_dataset))
        if bold is not None:
            statements.append("layer.%s.label.bold=%d;" % (axis, 1 if bold else 0))
        if rotation is not None:
            statements.append("layer.%s.label.rotate=%s;" % (axis, rotation))
        if offset_h is not None:
            statements.append("layer.%s.label.offsetH=%s;" % (axis, offset_h))
        if offset_v is not None:
            statements.append("layer.%s.label.offsetV=%s;" % (axis, offset_v))
        if label_color is not None:
            statements.append("layer.%s.label.color=%s;" % (axis, _origin_color(label_color)))
        # ``showlabel`` is per physical axis (unlike paired-axis ``showlabels``).
        # It therefore enables Y2 labels without affecting Y and explicitly hides
        # top labels without suppressing bottom labels.
        statements.append("layer.%s.showlabel=%d;" %
                          (axis, 1 if spec.show_tick_labels else 0))
        return statements

    def apply_line_and_ticks(self, axis: str, spec: AxisSpec, interval=None) -> List[str]:
        """Return Origin Axis > Line and Ticks statements, including tick masks."""
        axes = self.config.get("axes") or {}
        thickness = spec.thickness_pt if spec.thickness_pt is not None else axes.get("axis_line_width")
        tick_width = axes.get("tick_width") or thickness
        minor_tick_width = axes.get("minor_tick_width") or tick_width
        direction = (spec.tick_direction or axes.get("tick_direction") or "in").lower()
        if direction not in TICK_MASKS:
            raise ValueError("unsupported tick direction %r" % direction)
        major, minor = TICK_MASKS[direction]
        major_enabled = bool(axes.get("major_tick", True)) and spec.show_ticks
        minor_enabled = (bool(axes.get("minor_tick", False)) or
                         bool((self.config.get("axis_ticks") or {}).get("minor_ticks", False)))
        if interval is not None:
            minor_enabled = bool(interval.get("minor_ticks", minor_enabled))
        minor_enabled = minor_enabled and spec.show_ticks
        mask = (major if major_enabled else 0) | (minor if minor_enabled else 0)
        statements = [
            "layer.%s.ticks=%d;" % (axis, mask),
            "layer.%s.grid.show=0;" % axis,
        ]
        if thickness is not None:
            statements.append("layer.%s.thickness=%s;" % (axis, thickness))
        if tick_width is not None:
            statements.extend([
                "layer.%s.tickthickness=%s;" % (axis, tick_width),
                "layer.%s.mtickthickness=%s;" % (axis, minor_tick_width),
            ])
        if spec.tick_length_pt is not None:
            statements.append("layer.%s.ticklength=%s;" % (axis, spec.tick_length_pt))
            minor_length = axes.get("minor_tick_length")
            if minor_length is None:
                minor_length = spec.tick_length_pt / 2.0
            statements.append("layer.%s.mticklength=%s;" % (axis, minor_length))
        color = spec.color or axes.get("axis_color") or axes.get("color")
        if color is not None:
            statements.append("layer.%s.color=%s;" % (axis, _origin_color(color)))
        return statements

    def _apply_titles(self, plan: RenderingPlan) -> None:
        if not plan.layers:
            return
        self.origin.run("layer -s 1;", expect=False)
        for side, name in TITLE_OBJECTS.items():
            spec = plan.layers[0].axes.get(side)
            self.apply_axis_title(name, spec.label if spec else None)
        self.origin.run("layer -s 1;", expect=False)

    def apply_axis_title(self, object_name: str, text: Optional[str]) -> None:
        """Set an editable Origin axis-title object (xb, yl, or yr)."""
        if not text:
            return
        escaped = str(text).replace("\\", "\\\\").replace('"', '\\"')
        font = typography.font_family(self.config)
        size = typography.axis_title_size_pt(self.config)
        # In Origin, secondary-axis title objects (especially ``yr``) can exist
        # but remain hidden in a graph template.  Showing the native special
        # object is required before assigning its text; no replacement text
        # object is created.
        self.origin.run("%s.show=1;" % object_name, expect=False)
        self.origin.run('%s.text$="%s";' % (object_name, escaped), expect=False)
        self.origin.run("%s.font=font(%s); %s.fsize=%s;" %
                        (object_name, font, object_name, size), expect=False)
        native_text.apply_native_text_bold(self.origin, object_name,
                                         typography.axis_title_bold(self.config))
        title_color = (self.config.get("axes") or {}).get("axis_title_color")
        if title_color is not None:
            self.origin.run("%s.color=%s;" % (object_name, _origin_color(title_color)),
                            expect=False)

    def inspect(self, plan: RenderingPlan) -> Dict:
        """Read key native values back for mechanism-level QA and reporting."""
        result = {"layers": {}, "titles": {}, "bold_issues": []}
        wanted_tick_bold = typography.tick_label_bold(self.config)
        wanted_title_bold = typography.axis_title_bold(self.config)
        for index, layer in enumerate(plan.layers or [], start=1):
            self.origin.run("layer -s %d;" % index, expect=False)
            layer_result = {}
            for axis, side in PHYSICAL_AXIS_MAP.items():
                if side not in layer.axes:
                    continue
                try:
                    layer_result[side] = {
                        "native_axis": axis,
                        "from": self.origin.value("layer.%s.from" % axis),
                        "to": self.origin.value("layer.%s.to" % axis),
                        "increment": self.origin.value("layer.%s.inc" % axis),
                        "scale_type": self.origin.value("layer.%s.type" % axis),
                        "reverse_flag": self.origin.value("layer.%s.reverse" % axis),
                        "independent_y_scale": self.origin.value("layer.y.IndivScale"),
                        "rescale": self.origin.value("layer.%s.rescale" % axis),
                        "tick_mask": self.origin.value("layer.%s.ticks" % axis),
                        "minor_tick_count": self.origin.value("layer.%s.minorTicks" % axis),
                        "minor_positions": self.origin.text("layer.%s.mticksbydata$" % axis) if hasattr(self.origin, "text") else None,
                        "major_tick_length": self.origin.value("layer.%s.ticklength" % axis),
                        "minor_tick_length": self.origin.value("layer.%s.mticklength" % axis),
                        "label_type": self.origin.value("layer.%s.label.type" % axis),
                        "show_tick_labels": self.origin.value("layer.%s.showlabel" % axis),
                        "label_size_pt": self.origin.value("layer.%s.label.pt" % axis),
                    }
                    if wanted_tick_bold is not None:
                        actual_bold = self.origin.value("layer.%s.label.bold" % axis)
                        layer_result[side].update(label_bold=actual_bold,
                                                  expected_label_bold=wanted_tick_bold,
                                                  label_bold_equal=actual_bold == int(wanted_tick_bold))
                        if actual_bold not in (0, 1) or actual_bold != int(wanted_tick_bold):
                            result["bold_issues"].append("layer %d %s native tick bold differs: expected %d, read %r" %
                                                         (index, side, int(wanted_tick_bold), actual_bold))
                except Exception as exc:
                    layer_result[side] = {"native_axis": axis, "read_error": str(exc)}
                    if wanted_tick_bold is not None:
                        result["bold_issues"].append("layer %d %s native tick bold could not be verified: %s" %
                                                     (index, side, exc))
            result["layers"]["left" if index == 1 else "right"] = layer_result
        self.origin.run("layer -s 1;", expect=False)
        for side, name in TITLE_OBJECTS.items():
            try:
                result["titles"][side] = {"object": name,
                                            "text": self.origin.text("%s.text$" % name),
                                            "show": self.origin.value("%s.show" % name),
                                            "x": self.origin.value("%s.x" % name),
                                            "y": self.origin.value("%s.y" % name)}
                spec = plan.layers[0].axes.get(side) if plan.layers else None
                if wanted_title_bold is not None and spec and spec.label:
                    result["titles"][side]["typography"] = native_text.read_native_text_bold(
                        self.origin, name, expected=wanted_title_bold)
            except Exception as exc:
                result["titles"][side] = {"object": name, "read_error": str(exc)}
                spec = plan.layers[0].axes.get(side) if plan.layers else None
                if wanted_title_bold is not None and spec and spec.label:
                    result["bold_issues"].append(str(exc))
        self.origin.run("layer -s 1;", expect=False)
        if result["bold_issues"]:
            raise RuntimeError("; ".join(result["bold_issues"]))
        return result

    @staticmethod
    def _interval_for(index: int, axis: str, intervals: Dict) -> Optional[Dict]:
        key = "left" if index == 1 else "right"
        if axis in ("x", "x2"):
            return intervals.get("%s_x" % key)
        if axis == "y2":
            return intervals.get("%s_y2" % key)
        return intervals.get("%s_y" % key)


def _origin_color(value) -> str:
    """Normalise the small template colour vocabulary to a LabTalk colour."""
    named = {"black": "1", "white": "0"}
    key = str(value).strip().lower()
    return named[key] if key in named else labtalk.color(str(value))
