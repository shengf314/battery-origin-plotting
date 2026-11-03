"""Cycle Performance plot type: shared X, dual Y, point + connecting line.

Each sample contributes a native Origin line series plus, when needed, a native
symbol-only companion series (discharge capacity on the left Y, Coulombic
efficiency on the right Y).  Every validated point stays in the connecting line.
"""

from typing import Dict, List, Optional, Tuple

from ....ingest.normalize import NormalizedData
from ....models import (LayerPlan, LegendSpec, PlotSpec, RenderingPlan, SeriesSpec,
                        SeriesStyle)
from ....plot_types import base, dual_y, markers
from ....style import colors as color_style
from ....style import layout as layout_style
from ....style import legend as legend_style
from ....style import typography

METRIC_Y_AXIS = {"discharge_capacity": "left", "coulombic_efficiency": "right"}
METRIC_LEGEND_LABEL = {"discharge_capacity": "Discharge capacity",
                       "coulombic_efficiency": "Coulombic efficiency"}
PAIRED_LEGEND_HEADERS = ["Discharge capacity", "CE"]

# Each cycle figure format names its own axes; the flat keys stay readable for
# old configurations.  ``axis_sets`` is the path new formats use.
AXIS_SET_KEY = "axis_sets"
DEFAULT_AXIS_SET_KEY = "default_axis_set"
AXIS_TITLE_KEYS = {"x": "x_axis_label",
                   "left_y": "left_y_axis_label",
                   "right_y": "right_y_axis_label"}


def axis_set_name(spec: PlotSpec, config: Dict) -> Optional[str]:
    """Which ``cycle_performance.axis_sets`` entry this figure asks for."""
    block = base.plot_type_block(config)
    sets = block.get(AXIS_SET_KEY) or {}
    name = spec.axis_set or block.get(DEFAULT_AXIS_SET_KEY)
    if name and sets and name not in sets:
        raise ValueError("cycle_performance.axis_sets has no %r (configured: %s)"
                         % (name, ", ".join(sorted(sets))))
    return name if name in sets else None


def axis_titles(spec: PlotSpec, config: Dict,
                overrides: Dict[str, str]) -> Dict[str, str]:
    """Axis titles of the selected figure format.

    Priority: plot spec ``labels`` > the selected ``axis_sets`` entry > legacy
    flat keys.  No single left axis is fixed for cycle figures: every format
    block carries its own titles, and a spec can select one with ``axis_set``.
    """
    block = base.plot_type_block(config)
    chosen = (block.get(AXIS_SET_KEY) or {}).get(axis_set_name(spec, config)) or {}
    titles: Dict[str, str] = {}
    for key, template_key in AXIS_TITLE_KEYS.items():
        text = overrides.get(key) or chosen.get(template_key) or block.get(template_key)
        if text:
            titles[key] = text
    return titles


def readme_lines(plan: PlotSpec, config: Dict) -> List[str]:
    """Cycle Performance visual rule as it appears in the task README."""
    return ["- Cycle Performance：双 Y 轴共享 X；容量（左轴）实心圆、库仑效率（右轴）空心圆，"
            "均为 Origin 原生点 + 连线；全部数据点保留在可编辑的 Origin 系列中。"]


def qa_checks(plan: RenderingPlan, data: NormalizedData, config: Dict,
              backend_info=None) -> Dict:
    """Cycle Performance invariants: two metrics, one native dual-Y layer."""
    checks: Dict = {}
    issues: List[str] = []
    samples = sorted({item.sample for item in plan.data_series})
    for sample in samples:
        own = [item for item in plan.data_series if item.sample == sample]
        metrics = sorted(item.metric for item in own)
        if metrics != sorted(METRIC_Y_AXIS):
            issues.append("样品 %s 的指标系列为 %s，应为 %s"
                          % (sample, metrics, sorted(METRIC_Y_AXIS)))
            continue
        for item in own:
            expected_axis = METRIC_Y_AXIS[item.metric]
            if item.layer != 0 or item.y_axis != expected_axis:
                issues.append("样品 %s 的 %s 应绑定单 Layer 的 %s Y，实际 layer=%d, axis=%s"
                              % (sample, item.metric, expected_axis, item.layer,
                                 item.y_axis))
            rows = [series for series in data.series_for(sample, item.metric)]
            expected_points = len(rows[0].points) if rows else 0
            if item.n_points != expected_points:
                issues.append("样品 %s 的 %s 连线保留 %d 点，校验数据为 %d 点（连线被抽稀）"
                              % (sample, item.metric, item.n_points, expected_points))
            indices = list(item.marker_indices)
            if indices:
                if indices[0] < 0 or indices[-1] >= item.n_points:
                    issues.append("样品 %s 的 %s marker 下标越界" % (sample, item.metric))
                if sorted(set(indices)) != indices:
                    issues.append("样品 %s 的 %s marker 下标重复或未递增"
                                  % (sample, item.metric))
                checks["markers_%s_%s" % (sample, item.metric)] = len(indices)
    checks["samples_checked"] = len(samples)
    checks["single_layer_native_y2"] = (len(plan.layers) == 1 and
                                           plan.page.get("axis_mode") == dual_y.MODE and
                                           plan.page.get("independent_y_scales") is True)
    if not checks["single_layer_native_y2"]:
        issues.append("Cycle Performance 必须声明 Common Dual-Y 的单 Layer 原生 Y/Y2 结构")
    native = (backend_info or {}).get("native_axis") or {}
    native_axes = ((native.get("layers") or {}).get("left") or {})
    if native_axes:
        right = native_axes.get("right") or {}
        left = native_axes.get("left") or {}
        checks["native_y2_axis"] = right.get("native_axis") == "y2"
        checks["origin_independent_y_scale"] = (
            left.get("independent_y_scale") == 1 and
            right.get("independent_y_scale") == 1)
        checks["origin_right_y_labels"] = right.get("show_tick_labels") == 1
        if not checks["native_y2_axis"]:
            issues.append("Origin 回读未确认 Right Y 使用 layer.y2")
        if not checks["origin_independent_y_scale"]:
            issues.append("Origin 回读未确认 layer.y.IndivScale=1")
        if not checks["origin_right_y_labels"]:
            issues.append("Origin 回读未确认 Right Y tick labels 已开启")
    checks["legend_mode"] = plan.legend.mode
    if plan.legend.mode != "entries":
        issues.append("Cycle Performance 的图例应为 Origin 原生 entries，实际为 %r" % plan.legend.mode)
    _check_legend_links(plan, data.sample_order, checks, issues)
    if plan.page.get('native_cycle_layout') and backend_info:
        from .native_layout import verify_layout
        saved=backend_info.get('reopened_project') or {}
        actual_axes=saved.get('native_axis') or backend_info.get('native_axis')
        legend=(saved.get('native_legend') or {}).get('bounds') or backend_info.get('native_legend')
        if not actual_axes:
            issues.append('Separated cycle layout has no actual native axes readback')
        else:
            layout=verify_layout(plan,actual_axes,backend_info['area_mm'],legend)
            checks['native_cycle_layout']=layout
            issues.extend(layout['issues'])
    return {"checks": checks, "issues": issues}


def build_plan(spec: PlotSpec, config: Dict, data: NormalizedData) -> RenderingPlan:
    area = layout_style.plot_area(config)
    overrides = spec.axis_label_overrides()
    samples = data.sample_order
    sample_colors = color_style.assign_sample_colors(samples, config)
    series: List[SeriesSpec] = []
    marker_summary: Dict[str, Dict[str, int]] = {}

    dual_y.require(config)
    for sample in samples:
        for metric, y_axis in METRIC_Y_AXIS.items():
            items = [item for item in data.series_for(sample, metric)]
            if not items:
                raise ValueError("no %s series for sample %r" % (metric, sample))
            item = items[0]
            plan = markers.marker_plan(item.points, config)
            style = base.metric_series_style(config, metric)
            color = sample_colors[sample]
            line_style = SeriesStyle(line_width_pt=style.line_width_pt,
                                     line_style=style.line_style or "solid",
                                     symbol_shape="none")
            native_style = SeriesStyle(line_width_pt=style.line_width_pt,
                                       line_style=style.line_style or "solid",
                                       symbol_shape=style.symbol_shape,
                                       symbol_size_pt=style.symbol_size_pt,
                                       symbol_fill=style.symbol_fill,
                                       symbol_edge_width_pt=style.symbol_edge_width_pt)
            series.append(dual_y.bind(SeriesSpec(
                series_id="%s_%s_line" % (sample, metric),
                points=list(plan["line_points"]),
                sample=sample, metric=metric, color=color, style=line_style,
                metadata=dict(item.metadata),
                role="data",
                legend_entry="%s — %s" % (sample, METRIC_LEGEND_LABEL[metric]),
                marker_indices=list(plan["marker_indices"])), y_axis))
            indices = plan["marker_indices"]
            if indices:
                # This is an Origin scatter plot, not an SVG/vector overlay.  It
                # keeps the full connecting line editable while controlling visible
                # marker density with the existing shared marker policy.
                series.append(dual_y.bind(SeriesSpec(
                    series_id="%s_%s_markers" % (sample, metric),
                    points=[plan["line_points"][index] for index in indices],
                    sample=sample, metric=metric, color=color, style=native_style,
                    metadata=dict(item.metadata, marker_indices=list(indices)),
                    role="native_marker", legend_entry=None,
                    marker_indices=list(indices)), y_axis))
            marker_summary["%s_%s" % (sample, metric)] = {
                "line_points": len(plan["line_points"]),
                "native_symbols": len(plan["line_points"]),
                "requested_marker_indices": len(indices)}

    # Axis titles live in native Origin axis-title objects.  No outlined title
    # labels or imported SVG objects are generated for cycle figures.
    titles = axis_titles(spec, config, overrides)
    if data.source.get("ce_unit") == "fraction":
        if overrides.get("right_y") and "%" in overrides["right_y"]:
            raise ValueError("CE fraction values cannot be labelled percent without an explicit conversion")
        titles["right_y"] = overrides.get("right_y") or "Coulombic efficiency (fraction)"
    labels = []
    legend = _native_legend(spec, samples, series)

    layers = [dual_y.layer(config, series, titles)]
    page = dual_y.page_state(config)
    page.update({"area": area,
                 "axis_set": axis_set_name(spec, config),
                 "tick_label_size_pt": typography.tick_label_size_pt(config),
                 "sample_colors": sample_colors,
                 "line_overlay": base.line_overlay(config, series, {0: "native_y_y2"}),
                 "layer_bounds": {"native_y_y2": base.series_data_bounds(series, 0)},
                 "axis_ranges_override": _axis_ranges_override(config)})
    result = RenderingPlan(
        plot_type="cycle_performance",
        graph_name=spec.task_name,
        series=series,
        layers=layers,
        labels=labels,
        legend=legend,
        worksheet={"columns_per_series": 2},
        notes=["Cycle Performance declares Common Dual-Y: one Origin Layer with "
               "native independent Y/Y2. Curves, marker plots, axis titles and "
               "legend are Origin objects."],
        page=page)
    from .native_layout import apply_layout
    return apply_layout(result, config)


def _legend_series(sample: str, metric: str,
                   series: List[SeriesSpec]) -> SeriesSpec:
    """Select an existing native symbol, falling back to its actual data line.

    Legend links use stable series IDs rather than a presumed plot ordinal.  A
    symbol-only companion has the metric's real fill/shape and native Y side;
    no extra plot or legend-only symbol is introduced.
    """
    own = [item for item in series
           if item.sample == sample and item.metric == metric]
    candidates = [item for item in own if item.role == "native_marker"]
    if not candidates:
        candidates = [item for item in own if item.role == "data"]
    if len(candidates) != 1:
        raise ValueError("sample %r metric %r has %d native legend candidates"
                         % (sample, metric, len(candidates)))
    chosen = candidates[0]
    if chosen.layer != 0 or chosen.y_axis != METRIC_Y_AXIS[metric]:
        raise ValueError("sample %r metric %r legend link is on layer=%d axis=%s"
                         % (sample, metric, chosen.layer, chosen.y_axis))
    return chosen


def _native_legend(spec: PlotSpec, samples: List[str],
                   series: List[SeriesSpec]) -> LegendSpec:
    """One sample name and the real capacity/CE symbols per native legend row."""
    layout = (spec.legend or {}).get("layout", "paired_samples")
    if layout == "series_entries":
        return LegendSpec(
            mode="entries",
            entries=[item.legend_entry for item in series if item.legend_entry],
            grouped={"layout": "series_entries"})
    if layout != "paired_samples":
        raise ValueError("cycle_performance.legend.layout must be paired_samples "
                         "or series_entries, got %r" % layout)
    if len(set(samples)) != len(samples):
        raise ValueError("cycle legend sample_order contains repeated samples")
    if len({item.series_id for item in series}) != len(series):
        raise ValueError("cycle legend requires unique native series IDs")
    rows = [{"label": sample,
             "series_ids": [_legend_series(sample, metric, series).series_id
                            for metric in METRIC_Y_AXIS]}
            for sample in samples]
    return LegendSpec(
        mode="entries", entries=list(samples),
        grouped={"layout": "paired_samples",
                 "headers": list(PAIRED_LEGEND_HEADERS),
                 "metric_order": list(METRIC_Y_AXIS), "rows": rows})


def _check_legend_links(plan: RenderingPlan, samples: List[str],
                        checks: Dict, issues: List[str]) -> None:
    """Reject missing, repeated, cross-sample or wrong-side paired glyph links."""
    grouping = plan.legend.grouped or {}
    layout = grouping.get("layout")
    checks["legend_layout"] = layout
    if layout == "series_entries":
        expected = [item.legend_entry for item in plan.series if item.legend_entry]
        if plan.legend.entries != expected:
            issues.append("Cycle Performance series_entries 图例与实际系列名称不一致")
        return
    if layout != "paired_samples":
        issues.append("Cycle Performance 图例未声明 paired_samples 或 series_entries 布局")
        return
    if plan.legend.entries != list(samples):
        issues.append("Cycle Performance paired 图例必须按 sample_order 每个样品只列一次")
    if grouping.get("headers") != PAIRED_LEGEND_HEADERS:
        issues.append("Cycle Performance paired 图例的容量/CE列含义缺失或顺序错误")
    if grouping.get("metric_order") != list(METRIC_Y_AXIS):
        issues.append("Cycle Performance paired 图例指标顺序应为左轴容量、右轴CE")
    rows = grouping.get("rows")
    if not isinstance(rows, list):
        issues.append("Cycle Performance paired 图例 rows 缺失")
        return
    if len(rows) != len(samples):
        issues.append("Cycle Performance paired 图例行数与样品数不一致")
    series_by_id = {item.series_id: item for item in plan.series}
    if len(series_by_id) != len(plan.series):
        issues.append("Cycle Performance paired 图例存在重复 native series ID")
    linked = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append("Cycle Performance paired 图例第%d行格式错误" % (index + 1))
            continue
        sample = row.get("label")
        if index >= len(samples) or sample != samples[index]:
            issues.append("Cycle Performance paired 图例第%d行样品/顺序不正确" % (index + 1))
        ids = row.get("series_ids")
        if not isinstance(ids, list) or len(ids) != 2:
            issues.append("样品 %s 的paired图例必须恰有容量、CE两个链接" % sample)
            continue
        for metric, series_id in zip(METRIC_Y_AXIS, ids):
            linked.append(series_id)
            item = series_by_id.get(series_id)
            if item is None:
                issues.append("样品 %s 的paired图例链接不存在：%s" % (sample, series_id))
                continue
            if (item.sample != sample or item.metric != metric or item.layer != 0 or
                    item.y_axis != METRIC_Y_AXIS[metric]):
                issues.append("样品 %s 的paired图例 %s 链接样品/指标/附着轴错误"
                              % (sample, metric))
            try:
                expected_id = _legend_series(sample, metric, plan.series).series_id
                if series_id != expected_id:
                    issues.append("样品 %s 的paired图例 %s 未使用实际native marker或data line"
                                  % (sample, metric))
            except ValueError as exc:
                issues.append("Cycle Performance paired 图例：%s" % exc)
    if len(set(linked)) != len(linked):
        issues.append("Cycle Performance paired 图例容量/CE链接重复")
    checks["paired_sample_rows"] = len(rows)
    checks["paired_series_links"] = len(linked)


def _axis_ranges_override(config: Dict) -> Dict:
    """Explicit axis ranges from the template; null keeps Origin's auto scaling."""
    block = base.plot_type_block(config)
    override = {}
    for key, name in (("x", "x_axis_range"), ("y", "left_y_axis_range"),
                      ("y_right", "right_y_axis_range")):
        value = block.get(name)
        if value:
            override[key] = list(value)
    return override

def _grouped_legend(spec: PlotSpec, config: Dict, area: Dict[str, float],
                    samples: List[str], sample_colors: Dict[str, str],
                    data: NormalizedData) -> Tuple[LegendSpec, Dict]:
    """Grouped legend: sample colour swatches plus the two metric symbols."""
    block = base.plot_type_block(config)
    rule = block.get("legend") or {}
    if rule.get("mode") != "grouped":
        raise ValueError("Cycle Performance requires the grouped legend configuration")
    metrics = []
    for entry in rule.get("metric_legend", {}).get("entries", []):
        metrics.append({"label": entry.get("label"),
                        "marker": entry.get("marker"),
                        "line_style": entry.get("line_style")})
    if not metrics:
        raise ValueError("cycle_performance.legend.metric_legend.entries is not configured")
    sample_rows = [{"label": name, "color": sample_colors[name]} for name in samples]
    requested = (spec.legend or {})
    position = requested.get("position") or (config.get("legend") or {}).get("position") or "auto"
    corner = _auto_corner(data, position)
    size = typography.legend_size_pt(config)
    plan = {"position": position, "corner": corner, "size_pt": size,
            "samples": sample_rows, "metrics": metrics,
            "inset_mm": float(requested.get("inset_mm") or 2.0),
            "row_gap_mm": float(requested.get("row_gap_mm") or 0.8),
            "swatch_mm": float(requested.get("swatch_mm") or 4.0),
            "text_gap_mm": float(requested.get("text_gap_mm") or 1.0),
            "group_gap_mm": float(requested.get("group_gap_mm") or 1.4)}
    legend = LegendSpec(mode="grouped",
                        grouped=legend_style.grouped_legend(sample_colors, config)
                        if _grouped_rule_available(config) else
                        {"samples": sample_rows, "metrics": metrics},
                        entries=[row["label"] for row in sample_rows] +
                                [entry["label"] for entry in metrics])
    return legend, plan


def _grouped_rule_available(config: Dict) -> bool:
    rule = ((config.get("plot_type") or {}).get("legend") or {})
    return rule.get("mode") == "grouped" and bool(
        (rule.get("metric_legend") or {}).get("entries"))


def _auto_corner(data: NormalizedData, position: str) -> str:
    return legend_style.auto_corner(data, position)
