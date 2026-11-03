"""Single-Y capacity series and shared continuous rate-stage annotations."""

import math
from copy import deepcopy

from ....ingest.report import ValidationReport
from ....models import LabelSpec, LayerPlan, LegendSpec, RenderingPlan, SeriesSpec, SeriesStyle
from ....plot_types import base, markers
from ....style import axes, colors, layout, legend as legend_style, typography


def segment_stages(rows):
    """Equal rates on adjacent Cycle values, never groupby(rate) or bridge gaps."""
    stages = []
    for row in sorted(rows, key=lambda item: item["cycle"]):
        rate = row["rate"]
        if (not stages or stages[-1]["canonical"] != rate["canonical"] or
                row["cycle"] != stages[-1]["end_cycle"] + 1):
            stages.append(dict(canonical=rate["canonical"], label=rate["label"],
                               start_cycle=row["cycle"], end_cycle=row["cycle"]))
        else:
            stages[-1]["end_cycle"] = row["cycle"]
    return stages


def stage_programs(data):
    return {sample: segment_stages(data.source["rate_rows"][sample])
            for sample in data.sample_order}


def cycle_gaps(data):
    """Record absent integer Cycle intervals without allocating or filling rows."""
    gaps = {}
    for sample in data.sample_order:
        cycles = sorted(row["cycle"] for row in data.source["rate_rows"][sample])
        gaps[sample] = [dict(after_cycle=before, before_cycle=after,
                             missing_from=before + 1, missing_to=after - 1,
                             missing_count=after - before - 1)
                        for before, after in zip(cycles, cycles[1:]) if after > before + 1]
    return gaps


def _signature(stages):
    return [(stage["canonical"], stage["start_cycle"], stage["end_cycle"])
            for stage in stages]


def common_program(data):
    programs = stage_programs(data)
    report = ValidationReport()
    if not programs or any(not program for program in programs.values()):
        report.question("no Rate stage program was found")
    elif len({tuple(_signature(program)) for program in programs.values()}) != 1:
        report.question("Samples have different Rate stage programs (Rate/start/end): %s"
                        % programs)
    report.raise_if_blocking("Rate Capability stage validation")
    return deepcopy(next(iter(programs.values())))


def _stage_y_extents(stages, data):
    """Capacity bounds use every supplied sample point in each observed run."""
    extents = []
    report = ValidationReport()
    for stage in stages:
        values = [y for item in data.series for x, y in item.points
                  if stage["start_cycle"] <= x <= stage["end_cycle"]]
        if not values:
            report.question("Rate stage %s-%s has no capacity points" %
                            (stage["start_cycle"], stage["end_cycle"]))
            continue
        extents.append((min(values), max(values)))
    report.raise_if_blocking("Rate label data bounds")
    return extents


def _rate_labels(stages, config, data):
    rule = base.plot_type_block(config).get("rate_labels") or {}
    report = ValidationReport()
    if not isinstance(rule, dict):
        report.question("rate_labels must be an object")
        report.raise_if_blocking("Rate label configuration")
    y = rule.get("y_position")
    size = rule.get("font_size")
    if size is None:
        size = typography.tick_label_size_pt(config)
    offset = rule.get("y_offset_mm")
    placement = rule.get("placement", "above")
    if placement not in ("above", "below"):
        report.question("rate_labels.placement must be above or below")
    for name, value in (("y_position", y), ("font_size", size), ("y_offset_mm", offset)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value)):
            report.question("rate_labels.%s must be a finite number" % name)
    report.raise_if_blocking("Rate label configuration")
    if (y is not None and not 0 <= y <= 1) or size <= 0:
        report.question("rate_labels requires 0 <= y_position <= 1 and font_size > 0")
    if y is None and offset is not None and offset < 0:
        report.question("automatic rate_labels.y_offset_mm must be nonnegative; "
                        "use placement=above or below for direction")
    report.raise_if_blocking("Rate label configuration")
    if y is not None:
        # Preserve explicit legacy fraction inputs, including their gap field.
        return [LabelSpec(name="RateStage%d" % (index + 1), text=stage["label"],
                          size_pt=float(size), anchor="x_scale_y_fraction",
                          position=((stage["start_cycle"] + stage["end_cycle"]) / 2.0, y),
                          gap_mm=offset, role="rate_stage", render="native")
                for index, stage in enumerate(stages)]

    extents = _stage_y_extents(stages, data)
    low, high = min(bounds[0] for bounds in extents), max(bounds[1] for bounds in extents)
    # The plan is created before Origin measures its auto axis range. Convert a
    # half-line text clearance and the existing optional offset using the supplied
    # capacity span and unchanged plot height. Constant data need a nonzero span
    # only for label geometry; no points or scientific units are transformed.
    span = high - low if high > low else max(abs(low), 1.0)
    height = layout.plot_area(config)["height_mm"]
    if height <= 0:
        report.question("rate label placement requires a positive plot-area height")
    report.raise_if_blocking("Rate label configuration")
    capacity_style = (config.get("plot_type") or {}).get("discharge_capacity") or {}
    symbol_size = float(capacity_style.get("symbol_size") or 0.0)
    # Keep text outside both the data center and the now-visible native marker.
    clearance_mm = layout.pt_to_mm(float(size) + symbol_size) / 2.0 + (offset or 0.0)
    clearance = span * clearance_mm / height
    direction = 1 if placement == "above" else -1
    return [LabelSpec(name="RateStage%d" % (index + 1), text=stage["label"],
                      size_pt=float(size), anchor="layer_scale",
                      position=((stage["start_cycle"] + stage["end_cycle"]) / 2.0,
                                bounds[1 if direction == 1 else 0] + direction * clearance),
                      gap_mm=None, role="rate_stage", render="native")
            for index, (stage, bounds) in enumerate(zip(stages, extents))]


def build_plan(spec, config, data):
    if spec.axis_set is not None:
        raise ValueError("Rate Capability uses one axis format; override labels.x/labels.y instead")
    stages = common_program(data)
    sample_colors = colors.assign_sample_colors(data.sample_order, config)
    style = base.metric_series_style(config, "discharge_capacity")
    series = []
    for item in data.series:
        display = markers.marker_plan(item.points, config)
        color = sample_colors[item.sample]
        series.append(SeriesSpec(
            series_id=item.series_id + "_line", sample=item.sample, metric=item.metric,
            points=display["line_points"], color=color, layer=0,
            style=SeriesStyle(line_width_pt=style.line_width_pt,
                              line_style=style.line_style,
                              symbol_shape=style.symbol_shape,
                              symbol_size_pt=style.symbol_size_pt,
                              symbol_fill=style.symbol_fill,
                              symbol_edge_width_pt=style.symbol_edge_width_pt),
            legend_entry=item.sample, marker_indices=display["marker_indices"]))
    titles = {axis: base.axis_label(config, None, axis, spec.axis_label_overrides())
              for axis in ("x", "y")}
    # Axis titles are carried by AxisSpec and become Origin's xb/yl objects.
    # Only rate-stage scientific annotations remain ordinary native labels.
    labels = _rate_labels(stages, config, data)
    legend = LegendSpec(mode="entries", entries=list(data.sample_order))
    return RenderingPlan(
        plot_type=spec.plot_type, graph_name=spec.task_name, series=series,
        layers=[LayerPlan(index=0, series_ids=[item.series_id for item in series],
                          axes={key: axes.build_axis(key, config, label=title)
                                for key, title in (("bottom", titles["x"]),
                                                   ("left", titles["y"]),
                                                   ("top", None), ("right", None))})],
        labels=labels, legend=legend,
        page={"area": layout.plot_area(config), "tick_label_size_pt": typography.tick_label_size_pt(config),
              "sample_colors": sample_colors,
              "line_overlay": base.line_overlay(config, series, {0: "left"}),
              "layer_bounds": {"left": base.series_data_bounds(series, 0)},
              "rate_stages": stages, "cycle_gaps": cycle_gaps(data)},
        worksheet={"columns_per_series": 2},
        notes=["Rate Capability uses one capacity series per sample; stages follow "
               "adjacent Cycle runs of equal canonical Rate; gaps and recovery runs "
               "remain separate. Null y_position places centered native labels "
               "above/below each stage's all-sample capacity extent. No points are filled; "
               "the existing one-series-per-sample line connection can cross Cycle gaps "
               "and is unchanged. Source Excel is unchanged."])


def qa_checks(plan, data, config, backend_info=None):
    issues, checks = [], {}
    stages = common_program(data)
    samples = data.sample_order
    checks["QA-R1"] = (len(plan.data_series) == len(samples) and
                        all(len([s for s in plan.data_series if s.sample == name and
                                 s.metric == "discharge_capacity" and s.layer == 0]) == 1
                            for name in samples))
    checks["QA-R2"] = all(
        len(data.series_for(s.sample, s.metric)) == 1 and
        s.points == data.series_for(s.sample, s.metric)[0].points for s in plan.data_series)
    checks["QA-R3"] = plan.page.get("rate_stages") == stages
    labels = [label for label in plan.labels if label.role == "rate_stage"]
    expected_labels = _rate_labels(stages, config, data)
    checks["QA-R4"] = [label.to_dict() for label in labels] == [
        label.to_dict() for label in expected_labels]
    checks["QA-R5"] = all(_signature(program) == _signature(stages)
                          for program in stage_programs(data).values())
    checks["rate_cycle_gaps"] = plan.page.get("cycle_gaps") == cycle_gaps(data)
    checks["sample_only_legend"] = plan.legend.entries == samples
    checks["single_y_layer"] = len(plan.layers) == 1 and all(s.layer == 0 for s in plan.series)
    checks["marker_display"] = True
    for item in plan.data_series:
        indices = markers.marker_plan(item.points, config)["marker_indices"]
        checks["marker_display"] = checks["marker_display"] and (
            item.marker_indices == indices and item.style.symbol_shape is not None)
    for key, valid in checks.items():
        if not valid:
            issues.append("Rate Capability %s failed" % key)
    checks["rate_stage_count"] = len(stages)
    checks["rate_label_count"] = len(labels)
    return {"checks": checks, "issues": issues}


def readme_lines(plan, config):
    return ["- Rate Capability：单 Y 放电比容量–Cycle；每个样品一条完整点线系列，"
            "颜色与图例仅表示样品。倍率按连续阶段标注，恢复倍率保留为新阶段。",
            "- 倍率标签字号未配置时继承全局刻度字号；X 为阶段起止圈中点。"
            "y_position 为空时按全样品阶段容量边界自动放置，placement=above/below；"
            "字号半行高度与非负 y_offset_mm 按容量跨度/既有图高换算间距。"
            "显式 0–1 y_position 保留旧图层比例位置。缺圈不合并阶段、不补点。",
            "- plan.page.cycle_gaps 记录每个样品缺失的整数圈区间；"
            "既有每样品完整容量系列的连线可跨缺圈，本次未改变该连接契约。"]
