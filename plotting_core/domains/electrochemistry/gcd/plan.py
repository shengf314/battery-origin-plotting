"""GCD plot type: one line series per Sample + Cycle + Branch, no markers.

Sample identity is encoded by hue, cycle by a lighter shade of the same hue
(``style.colors.cycle_colors``); both branches of a cycle share one colour.
The legend semantics stay explicit: either one entry per Sample + Cycle
(documented default) or the task-approved gradient bar that replaces 100 entries.
"""

from copy import deepcopy
from typing import Dict, List, Optional

from ....ingest.normalize import NormalizedData
from ....ingest.report import ValidationReport
from ....models import LabelSpec, LegendSpec, PlotSpec, RenderingPlan, SeriesSpec, LayerPlan
from ....plot_types import base
from ....style import colors as color_style
from ....style import layout as layout_style
from ....style import typography
from ..cycle_summary import instrument_import_reference

# Fallback geometry of the approved cycle-gradient bar, for a visual template that
# does not configure the block yet.  The configured values live in
# ``publication_visual_template.yaml`` under ``gcd.legend.bar``; a plot spec may
# override them per task.  Priority: this fallback < template < spec.
DEFAULT_BAR = {
    "x_from_frac": 0.10093,
    "x_to_frac": 0.36719,
    "top_frac": 0.94255,
    "height_frac": 0.02212,
    "label_gap_mm": 1.0,
}
DEFAULT_ENTRY_FORMAT = "{sample} – Cycle {cycle}"

# The spec names the x representation; the visual template names its block after
# the resulting axes.  Keeping both names explicit avoids silently losing the
# confirmed axis titles.
VARIANT_BLOCKS = {"specific_capacity": "capacity_voltage",
                  "na_content": "na_content_voltage"}


def series_plan(points, config: Dict) -> Dict:
    """GCD draws line-only series: every point, and never a marker interval."""
    return dict(line_points=list(points), marker_indices=[])


def readme_lines(plan: PlotSpec, config: Dict) -> List[str]:
    """GCD visual rule as it appears in the task README."""
    width = ((config.get("plot_type") or {}).get("general") or {}).get("line_width")
    return ["- GCD：无 marker、%s pt 实线；同一样品的 charge/discharge 同色，色阶按 Cycle 由深到浅。"
            % width]


def qa_checks(plan: RenderingPlan, data: NormalizedData, config: Dict,
              backend_info=None) -> Dict:
    """GCD invariants that the generic levels cannot express.

    The colour encoding is a GCD rule (hue = sample, shade = cycle, one colour per
    sample + cycle shared by both branches), so it is checked here, from the plan,
    without touching the drawing backend.
    """
    checks: Dict = {}
    issues: List[str] = []
    by_key: Dict[tuple, List[str]] = {}
    for item in plan.data_series:
        if item.cycle is None:
            continue
        by_key.setdefault((item.sample, item.cycle), []).append(item.color)
    shared = {key: values for key, values in by_key.items() if len(set(values)) != 1}
    checks["sample_cycle_colour_groups"] = len(by_key)
    checks["groups_with_mixed_colour"] = len(shared)
    if shared:
        preview = ", ".join("%s cycle %s" % key for key in list(shared)[:5])
        issues.append("同一样品同一圈的分支颜色不一致：%s" % preview)

    # Shade direction is only asserted when the template actually configures the
    # confirmed rule (an unconfigured rule must not fail the figure).
    rule = (config.get("colors") or {}).get("cycle_shading_rule") or {}
    if rule.get("lightest_white_mix") is not None:
        violations = []
        for sample in sorted({item.sample for item in plan.data_series}):
            shades = {}
            for item in plan.data_series:
                if item.sample == sample and item.cycle is not None:
                    shades[item.cycle] = item.color
            cycles = sorted(shades)
            reds = [int(str(shades[cycle]).lstrip("#")[0:2], 16) for cycle in cycles]
            if any(later < earlier for earlier, later in zip(reds, reds[1:])):
                violations.append(sample)
        checks["shading_direction"] = "lighter towards later cycles"
        if violations:
            issues.append("色阶方向与模板的 cycle_shading_rule 相反：%s"
                          % ", ".join(violations))
    else:
        checks["shading_direction"] = "not configured"

    if plan.legend.mode == "cycle_gradient_bar":
        cycles = list(plan.legend.grouped.get("cycles") or [])
        colors = list(plan.legend.grouped.get("colors") or [])
        checks["gradient_bar_segments"] = len(colors)
        if len(cycles) != len(colors):
            issues.append("渐变色条的圈数与颜色数不一致（%d 圈 / %d 色）"
                          % (len(cycles), len(colors)))
    elif plan.legend.mode == "entries":
        expected = len({(item.sample, item.cycle) for item in plan.data_series})
        checks["legend_entries"] = len(plan.legend.entries)
        if len(plan.legend.entries) != expected:
            issues.append("图例条目 %d 条，应为 Sample + Cycle 组合数 %d 条"
                          % (len(plan.legend.entries), expected))
    return {"checks": checks, "issues": issues}


def build_plan(spec: PlotSpec, config: Dict, data: NormalizedData) -> RenderingPlan:
    import_report = ValidationReport()
    instrument_import = instrument_import_reference(data.source.get("semantics") or {}, import_report)
    import_report.raise_if_blocking("GCD instrument provenance")
    if instrument_import is not None:
        data.source["instrument_import"] = deepcopy(instrument_import)
    area = layout_style.plot_area(config)
    overrides = spec.axis_label_overrides()
    variant = data.source.get("x_representation")
    block_key = VARIANT_BLOCKS.get(variant, variant)
    selection = data.source.get("selection") or {}
    cycles = _selected_cycles(selection, data)
    sample_colors = _sample_colors(data.sample_order, config)
    style = base.general_series_style(config)
    tick_size = typography.tick_label_size_pt(config)

    series: List[SeriesSpec] = []
    legend_entries: List[str] = []
    legend_keys = set()
    shading: Dict[str, Dict[int, tuple]] = {
        sample: color_style.cycle_colors(color, cycles, config)
        for sample, color in sample_colors.items()
    }
    entry_format = _entry_format(spec)
    for item in data.series:
        capacity_axis = {"quantity": "specific_capacity" if variant == "specific_capacity" else "na_content",
                         "unit": "mAh g-1" if variant == "specific_capacity" else "1"}
        voltage_axis = {"quantity": "voltage", "unit": "V"}
        metadata = {"source": data.source.get("file"), "sheet": data.source.get("sheet"),
                    "source_row_bounds": [item.first_row, item.last_row],
                    "cycle": item.cycle, "branch": item.branch, "sample": item.sample}
        if instrument_import is not None:
            metadata["instrument_import"] = deepcopy(instrument_import)
        if data.source.get("axis_binding") == "voltage_capacity":
            metadata.update(x=voltage_axis, y=capacity_axis)
        else:
            metadata.update(x=capacity_axis, y=voltage_axis)
        for axis in ("x", "y"):
            metadata[axis].update((data.source.get("semantics") or {}).get(axis) or {})
        if variant == "na_content":
            metadata["na_content_provenance"] = (data.source.get("semantics") or {}).get("na_content", {"status": "legacy supplied coordinate; origin/reference not verified"})
            conversion_metadata = item.metadata if isinstance(item.metadata, dict) else {}
            if isinstance(conversion_metadata.get("na_conversion"), dict):
                # Native column comments need the full independent conversion
                # record. Its scientific role is separate from drawable role=data.
                metadata["na_conversion"] = deepcopy(conversion_metadata["na_conversion"])
                if "method" in conversion_metadata:
                    method_record = deepcopy(conversion_metadata["method"])
                    declaration = conversion_metadata["na_conversion"].get("declaration")
                    if (isinstance(method_record, dict) and
                            isinstance(method_record.get("parameters"), dict) and
                            isinstance(declaration, dict) and
                            method_record["parameters"] == declaration and
                            method_record.get("parameters_ref", "na_conversion.declaration") == "na_conversion.declaration"):
                        # Replace only an identical parameter record by its
                        # in-comment path; distinct parameters/sources stay intact.
                        method_record.pop("parameters")
                        method_record["parameters_ref"] = "na_conversion.declaration"
                    metadata["method"] = method_record
                metadata["scientific_role"] = deepcopy(conversion_metadata.get("scientific_role", conversion_metadata.get("role", "derived")))
        color = color_style.rgb_to_hex(shading[item.sample][item.cycle])
        entry = entry_format.format(sample=item.sample, cycle=item.cycle,
                                    branch=item.branch or "")
        key = (item.sample, item.cycle)
        native_entry = entry if key not in legend_keys else None
        legend_keys.add(key)
        series.append(SeriesSpec(
            series_id=item.series_id,
            points=list(item.points),
            sample=item.sample,
            cycle=item.cycle,
            branch=item.branch,
            color=color,
            style=style,
            layer=0,
            role="data",
            metadata=metadata,
            legend_entry=native_entry,
            marker_indices=[]))
        if native_entry:
            legend_entries.append(native_entry)

    # Axis titles are native Origin axis-title objects, not outlined overlays.
    labels = []
    legend, legend_labels = _legend(spec, config, area, data, cycles, sample_colors)
    labels.extend(legend_labels)

    layers = [LayerPlan(index=0, series_ids=[item.series_id for item in series], axes={
        "bottom": base_axis("bottom", config, base.axis_label(config, block_key, "x", overrides)),
        "left": base_axis("left", config, base.axis_label(config, block_key, "y", overrides)),
        "top": base_axis("top", config, None),
        "right": base_axis("right", config, None),
    })]
    if data.source.get("axis_binding") == "voltage_capacity":
        capacity_title = base.axis_label(config, block_key, "x", {})
        voltage_title = base.axis_label(config, block_key, "y", {})
        layers[0].axes["bottom"].label = overrides.get("x") or voltage_title
        layers[0].axes["left"].label = overrides.get("y") or capacity_title
    for axis, side in (("x", "bottom"), ("y", "left")):
        declared = (data.source.get("semantics") or {}).get(axis) or {}
        if declared:
            layers[0].axes[side].scale_type = declared.get("scale", "linear")
            layers[0].axes[side].direction = declared.get("direction", "ascending")
            if declared.get("label"):
                layers[0].axes[side].label = declared["label"]
    ranges = base.axis_ranges_from_template(config, block_key)
    axis_ranges_override = {}
    layer_bounds = {"left": base.series_data_bounds(series, 0)}
    if ranges.get("x_from") is not None and ranges.get("x_to") is not None:
        axis_ranges_override["x"] = [ranges["x_from"], ranges["x_to"]]
    if ranges.get("y_from") is not None and ranges.get("y_to") is not None:
        axis_ranges_override["y"] = [ranges["y_from"], ranges["y_to"]]

    return RenderingPlan(
        plot_type="gcd",
        graph_name=spec.task_name,
        series=series,
        layers=layers,
        labels=labels,
        legend=legend,
        page={
            "area": area,
            "tick_label_size_pt": tick_size,
            "shading": {sample: {cycle: list(value) for cycle, value in values.items()}
                        for sample, values in shading.items()},
            "sample_colors": sample_colors,
            "variant": variant,
            "selection_cycles": list(cycles),
            "axis_ranges_override": axis_ranges_override,
            "line_overlay": base.line_overlay(config, series, {0: "left"}),
            "layer_bounds": layer_bounds,
        },
        worksheet={"columns_per_series": 2},
        notes=["GCD draws line-only series; the marker interval is not read."])


def base_axis(key: str, config: Dict, label: Optional[str]):
    from ....style import axes as axis_style
    return axis_style.build_axis(key, config, label=label)


def _selected_cycles(selection: Dict, data: NormalizedData) -> List[int]:
    cycles = data.cycles()
    mode = selection.get("mode", "all")
    if mode == "range":
        cycles = [c for c in cycles if selection["from"] <= c <= selection["to"]]
    elif mode == "single":
        cycles = [c for c in cycles if c == selection["cycles"][0]]
    elif mode == "selected":
        wanted = set(selection["cycles"])
        cycles = [c for c in cycles if c in wanted]
    return cycles


def _sample_colors(samples: List[str], config: Dict) -> Dict[str, str]:
    palette = color_style.palette(config)
    if not palette:
        raise ValueError("colors.sample_palette is not configured; the sample colour "
                         "encoding cannot be produced")
    return color_style.assign_sample_colors(samples, config)


def _entry_format(spec: PlotSpec) -> str:
    pattern = (spec.legend or {}).get("entry_format") or DEFAULT_ENTRY_FORMAT
    for token in ("{sample}", "{cycle}"):
        if token not in pattern:
            raise ValueError("legend.entry_format must contain %s" % token)
    return pattern


def _legend(spec: PlotSpec, config: Dict, area: Dict[str, float], data: NormalizedData,
            cycles: List[int], sample_colors: Dict[str, str]):
    """Legend semantics rendered as an editable native Origin legend."""
    requested = dict(spec.legend or {})
    mode = requested.get("mode") or "entries"
    if mode == "entries":
        entries = []
        seen = set()
        for item in data.series:
            key = (item.sample, item.cycle)
            if key not in seen:
                entries.append(_entry_format(spec).format(sample=item.sample, cycle=item.cycle,
                                                           branch=item.branch or ""))
                seen.add(key)
        legend = LegendSpec(mode="entries", entries=entries)
        return legend, []
    if mode != "cycle_gradient_bar":
        raise ValueError("unsupported GCD legend mode: %r" % mode)
    # A gradient bar used to be an imported SVG.  Native-only output instead uses
    # Origin's editable per-curve legend entries, retaining every cycle identity.
    entries, seen = [], set()
    for item in data.series:
        key = (item.sample, item.cycle)
        if key not in seen:
            entries.append(_entry_format(spec).format(sample=item.sample, cycle=item.cycle,
                                                       branch=item.branch or ""))
            seen.add(key)
    return LegendSpec(mode="entries", entries=entries), []
