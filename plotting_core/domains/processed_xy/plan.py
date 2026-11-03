"""Native single-layer plans for already supplied, explicitly described XY series."""

import copy
from ... import registry

from ...models import LegendSpec, RenderingPlan, SeriesSpec, SeriesStyle, LayerPlan
from ...plot_types import base
from ...style import axes as axis_style
from ...style import colors, layout, typography


def build_plan(family, spec, config, data):
    registry.validate_data_kind(family, "excel_processed_series")
    if spec.plot_type != family or data.plot_type != family:
        raise ValueError("processed family, PlotSpec and normalized data must have the same registered plot type")
    from . import contracts
    from ...ingest.report import ValidationReport
    scope_report = ValidationReport()
    for item in data.series:
        # Readers add None for absent optional identity fields. Revalidate a
        # declaration view without treating those placeholders as new claims.
        declaration = {key: value for key, value in item.metadata.items() if value is not None}
        contracts.validate_series(family, data.source["semantics"], declaration, scope_report, item.series_id)
    scope_report.raise_if_blocking("processed plan scientific roles")
    semantics = data.source["semantics"]
    sample_colors = colors.assign_sample_colors(data.sample_order, config)
    series = []
    entries = []
    for item in data.series:
        metadata = copy.deepcopy(item.metadata)
        entry = str(metadata["legend"])
        style = SeriesStyle()
        if metadata["connection"] in ("line", "line_points"):
            style.line_width_pt = base.curve_line_width_pt(config)
        series.append(SeriesSpec(series_id=item.series_id, points=list(item.points), sample=item.sample,
                                 cycle=item.cycle, branch=item.branch, metric=item.metric,
                                 color=sample_colors[item.sample], style=style, layer=0,
                                 y_axis="left", role="data", legend_entry=entry,
                                 plot_kind=metadata["connection"], metadata=metadata))
        entries.append(entry)
    labels = spec.axis_label_overrides()
    axes = {}
    for key in ("bottom", "left", "top", "right"):
        variable = "x" if key in ("bottom", "top") else "y"
        axis = axis_style.build_axis(key, config,
                                    label=labels.get(variable, data.axis_labels[variable])
                                    if key in ("bottom", "left") else None)
        axis.scale_type = semantics[variable]["scale"]
        axis.direction = semantics[variable]["direction"]
        axes[key] = axis
    ticks = data.source.get("element_ticks") or []
    if ticks:
        axes["bottom"].ticks = [value for value, _ in ticks]
        axes["bottom"].tick_labels = [label for _, label in ticks]
    return RenderingPlan(
        plot_type=family, graph_name=spec.task_name, series=series,
        layers=[LayerPlan(index=0, series_ids=[item.series_id for item in series], axes=axes)],
        labels=[], legend=LegendSpec(mode="entries", entries=entries),
        page={"area": layout.plot_area(config), "tick_label_size_pt": typography.tick_label_size_pt(config),
              "sample_colors": sample_colors, "variant": semantics["variant"],
              "axis_ranges_override": {}, "line_overlay": [],
              "layer_bounds": {"left": base.series_data_bounds(series, 0)},
              "scientific_semantics": copy.deepcopy(semantics)},
        worksheet={"columns_per_series": 2},
        notes=["Only the supplied XY values are rendered; no differentiation, fitting, normalization, "
               "sign inversion, sorting, interpolation or scientific computation is performed.",
               "Scientific series roles and units are retained as metadata; all Origin objects remain native."])


def qa_checks(plan, data, config, backend_info=None):
    issues = []
    expected = {item.series_id: item for item in data.series}
    actual = {item.series_id: item for item in plan.data_series}
    if len(actual) != len(plan.data_series):
        issues.append("processed plan contains duplicate series identifiers")
    if set(actual) != set(expected):
        issues.append("processed plan series identifiers do not match validated input segments")
    for key in set(actual) & set(expected):
        source, target = expected[key], actual[key]
        if target.points != source.points:
            issues.append("processed plan changed point values/order in %s" % key)
        if target.metadata != source.metadata:
            issues.append("processed plan lost scientific/provenance metadata in %s" % key)
        if target.plot_kind != source.metadata.get("connection"):
            issues.append("processed plan connection semantics differ in %s" % key)
        expected_width = (base.curve_line_width_pt(config)
                          if source.metadata.get("connection") in ("line", "line_points") else None)
        if target.style.line_width_pt != expected_width:
            issues.append("processed plan native curve width disagrees with configured connection in %s" % key)
        if target.y_axis != "left":
            issues.append("processed-series adapter unexpectedly bound %s to Y2" % key)
    semantics = data.source["semantics"]
    for axis, key in (("x", "bottom"), ("y", "left")):
        planned = plan.layers[0].axes[key]
        if planned.scale_type != semantics[axis]["scale"] or planned.direction != semantics[axis]["direction"]:
            issues.append("processed plan %s axis direction/scale disagrees with the input contract" % axis)
    return {"checks": {"supplied_series": len(expected), "supplied_points": sum(len(item.points) for item in data.series),
                       "scientific_roles": {key: item.metadata.get("role") for key, item in expected.items()},
                       "axis_semantics": {axis: semantics[axis] for axis in ("x", "y")},
                       "no_scientific_computation": True}, "issues": issues}


def readme_lines(spec, config):
    return ["- 本图使用已提供的标准 XY 数据；不执行求导、拟合、扩散系数计算、峰分解或数据修饰。",
            "- SeriesID/Segment 决定连接边界；单位、分支、系列角色、处理记录随计划和工程保存。"]
