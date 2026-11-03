"""Deliverable documents: effective plot spec, export check, task README."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from ..config import export_settings
from ..style import layout as layout_style


def refresh_delivery_metadata(export_report):
    """Refresh actual existence; omit the recursive report's own byte count."""
    for key, info in (export_report.get("delivery") or {}).items():
        if not isinstance(info, dict) or not info.get("path"):
            continue
        path = Path(info["path"])
        info["exists"] = path.is_file()
        info["bytes"] = None if key == "export_check.json" else (path.stat().st_size if path.is_file() else 0)
        if key == "export_check.json":
            info["bytes_note"] = "self-referential report size is deliberately not reported"


def _replace_section(text, name, section):
    start = "<!-- %s:start -->" % name
    end = "<!-- %s:end -->" % name
    block = start + "\n" + section + "\n" + end
    if start in text and end in text and text.index(start) < text.index(end):
        first, last = text.index(start), text.index(end) + len(end)
        return text[:first] + block + text[last:]
    return text.rstrip() + "\n\n" + block + "\n"


def _image_review_text(acceptance):
    image = (acceptance.get("stages") or {}).get("image") or {}
    evidence = image.get("evidence") or {}
    lines = ["- 实际图像审阅：%s；仅已绑定当前 OPJU/PNG/SVG 的审阅可作为验收证据。" %
             image.get("status", "not_run")]
    if evidence.get("reviewer"):
        lines.append("- 审阅者：%s；记录时间：%s。" %
                     (evidence["reviewer"], evidence.get("reviewed_at", "未记录")))
    if evidence.get("note"):
        lines.append("- 审阅观察：%s" % evidence["note"])
    for reason in image.get("reasons") or []:
        lines.append("- 图像审阅限制：%s" % reason)
    return "\n".join(lines)


def update_readme_acceptance(task_dir, acceptance, render_state=None):
    """Update an existing README's acceptance summary, preserving other content.

    Retry and failure paths use this without creating a README before delivery.
    """
    path = Path(task_dir) / "README.md"
    if not path.is_file():
        return
    start = "<!-- acceptance-summary:start -->"
    end = "<!-- acceptance-summary:end -->"
    lines = [start, "", "## 验收状态", "",
             "- 自动检查通过：%s" % str(acceptance["automatic_checks_passed"]).lower(),
             "- 完整验收通过：%s" % str(acceptance["accepted"]).lower(),
             "- 每项验收及证据见 `export_check.json` 的 `acceptance`。", ""]
    for name, stage in acceptance["stages"].items():
        lines.append("- %s：%s%s" % (name, stage["status"],
                                   "；" + "；".join(stage["reasons"]) if stage["reasons"] else ""))
    binding = acceptance.get("artifact_binding") or {}
    if binding.get("status"):
        lines.append("- 渲染证据绑定：%s%s" % (binding["status"],
                     "；" + "；".join(binding.get("reasons") or []) if binding.get("reasons") else ""))
    lines.extend(["", end])
    section = "\n".join(lines)
    text = path.read_text(encoding="utf-8-sig")
    if start in text and end in text and text.index(start) < text.index(end):
        first, last = text.index(start), text.index(end) + len(end)
        text = text[:first] + section + text[last:]
    else:
        text = text.rstrip() + "\n\n" + section + "\n"
    # Remove the old unmarked pending-image sentence when updating legacy tasks;
    # a persisted actual review must update the body, not only the final summary.
    text = re.sub(r"(?m)^- 视觉检查记录：.*(?:\r?\n|$)", "", text)
    text = _replace_section(text, "image-review", _image_review_text(acceptance))
    state = render_state or acceptance.get("render_state") or {}
    if state:
        current_body = (state.get("status") == "completed" and state.get("mode") != "dry_run")
        section = "\n".join([
            "## 当前运行尝试", "",
            "- run_id：`%s`；状态：%s；阶段：%s；模式：%s。" %
            (state.get("run_id", "legacy"), state.get("status", "unknown"),
             state.get("phase", "unknown"), state.get("mode", "render")),
            "- Origin 已执行：%s。" % (str(state["origin_executed"]).lower()
                                        if "origin_executed" in state else "旧报告未记录"),
            ("- 正文与成果由上述 Origin 运行生成；完整验收仍以五项验收和当前成果哈希绑定为准。"
             if current_body else
             "- 当前验收仅属于上述运行。此前正文与尚未重新生成的工程/导出文件属于历史成果，不能接受当前失败、运行中或 dry-run 的尝试。"),
            "- 旧文档归档：%s。" % (state.get("archive_path") or "无")])
        text = _replace_section(text, "run-attempt", section)
    path.write_text(text, encoding="utf-8")


def effective_spec(spec, config: Dict, data, plan, backend_info: Dict,
                   validation: Dict) -> Dict:
    """The plot spec as executed, including the resolved style and plan summary."""
    document = spec.to_dict()
    document["executed_at"] = datetime.now().isoformat(timespec="seconds")
    document["resolved"] = {
        "visual_template": spec.style_template,
        "canvas": layout_style.canvas(config),
        "margins_configured": layout_style.margins(config),
        "margins_used": backend_info.get("margins_mm"),
        "plot_area_mm": backend_info.get("area_mm"),
        "axes": config.get("axes"),
        "labels": config.get("labels"),
        "colors": {"sample_palette": (config.get("colors") or {}).get("sample_palette"),
                   "cycle_shading_rule": (config.get("colors") or {}).get(
                       "cycle_shading_rule")},
        "export": export_settings(config),
        "axis_ticks": {
            key: {"major_mode": value["major_mode"], "interval": value["interval"],
                  "minor_ticks": value["minor_ticks"]}
            for key, value in (backend_info.get("ticks") or {}).items()},
        "axis_ranges": backend_info.get("axis_ranges"),
        "native_axis": backend_info.get("native_axis"),
        "dual_y": config.get("dual_y") if plan.page.get("axis_capability") == "native_dual_y" else None,
        "note": "resolved values are read-only output; change the visual template or "
                "the spec overrides, never this file",
    }
    document["plan"] = plan.to_dict()
    document["data_source"] = data.source
    document["input_validation"] = validation
    document["backend"] = {key: value for key, value in backend_info.items()
                           if key in ("graph", "book", "plots", "overlay",
                                      "worksheet_transfer", "verified", "reopened_project", "editability_probe",
                                      "native_axis_contract", "environment", "capabilities", "native_export_paths")}
    return document


def write_readme(spec, config: Dict, data, plan, backend_info: Dict,
                 validation: Dict, export_report: Dict, files: Dict[str, str],
                 qa_report: Dict = None) -> str:
    settings = export_settings(config)
    area = backend_info.get("area_mm") or {}
    margins = backend_info.get("margins_mm") or {}
    configured = layout_style.margins(config)
    lines: List[str] = []
    lines.append("# %s" % spec.task_name)
    lines.append("")
    lines.append("## 数据范围与来源")
    lines.append("")
    source = data.source
    lines.append("- 输入：`%s`，工作表 `%s`，表头行 %s；源文件只读，未修改。"
                 % (source.get("file"), source.get("sheet"), source.get("header_row")))
    scientific = plan.data_series
    markers = [item for item in plan.series if item.role == "native_marker"]
    other = [item for item in plan.series if item.role not in ("data", "native_marker")]
    lines.append("- 图类型：%s；科学数据系列 %d 条、%d 个数据点。"
                 % (plan.plot_type, len(scientific), sum(item.n_points for item in scientific)))
    lines.append("- 原生绘图对象：%d 条、共 %d 个转写点；其中 marker 表现系列 %d 条、%d 个 marker 点；其他辅助系列 %d 条。marker 不重复计入科学数据。"
                 % (len(plan.series), plan.total_points(), len(markers),
                    sum(item.n_points for item in markers), len(other)))
    if source.get("x_representation"):
        lines.append("- GCD 横轴表示：%s；循环选择：%s。"
                     % (source.get("x_representation"), source.get("selection")))
    lines.append("- 样品顺序：%s。" % ", ".join(data.sample_order))
    traceability = source.get("scientific_traceability") or {}
    if traceability:
        lines.append("- 科学来源声明完整性：%s；仅检查已提供的记录，未证明结果的科学正确性。" % traceability.get("status", "unknown"))
        for gap in traceability.get("gaps", []):
            lines.append("  - 待补记录 `%s`：%s。" % (gap.get("path"), gap.get("reason")))
    if data.excluded:
        lines.append("- 排除记录：%s。"
                     % "；".join("%s = %d" % item for item in data.excluded.items()))
    if validation.get("applied_mappings"):
        lines.append("- 已确认的字段/取值映射：")
        for item in validation["applied_mappings"]:
            lines.append("  - %s" % item)
    points = (backend_info.get("verified") or {}).get("verified_points")
    reopened_series = (backend_info.get("reopened_project") or {}).get("series") or []
    verified_scope = "科学数据"
    if not points and reopened_series and all(item.get("points_equal") is True for item in reopened_series):
        points = sum(item["point_count"] for item in reopened_series)
        backend_verified_series = len(reopened_series)
        verified_scope = "原生转写数据（含 marker 表现系列）"
    else:
        backend_verified_series = (backend_info.get("verified") or {}).get("verified_series", 0)
    if points:
        lines.append("- 数据完整性：逐点从 Origin 回读核对 %s %d 个点、%d 条系列，顺序一致。"
                     % (verified_scope, points,
                        backend_verified_series))
    else:
        lines.append("- 数据完整性：本次未逐点回读；按 QA Level %s 核对系列数、点数、"
                     "首末点与 min/max（需要逐点核对时在 plot spec 设 "
                     "`verification.level: 3`）。"
                     % ((qa_report or {}).get("level", "2")))
    lines.append("")
    lines.append("## 视觉规则（来自 publication visual template；绘图任务本身不修改模板参数）")
    lines.append("")
    canvas = layout_style.canvas(config)
    lines.append("- 画布 %.2f × %.2f mm；绘图区 %.2f × %.2f mm；边距 配置 %s / 实际 %s。"
                 % (canvas["width_mm"], canvas["height_mm"],
                    area.get("width_mm", 0.0), area.get("height_mm", 0.0),
                    _margins_text(configured), _margins_text(margins)))
    line_info = (plan.page or {}).get("line_width_source")
    if line_info:
        template = (plan.page or {}).get("graph_template_used")
        lines.append("- 曲线样式来源：%s。" % line_info)
        if template:
            lines.append("- 绘图模板：`%s`；模板名称/初始探测值不能替代保存后的曲线样式回读。" % template)
    native_widths = [(item.get("series_id"), (item.get("native_style") or {}).get("line_width_pt"))
                     for item in reopened_series
                     if item.get("series_id") in {series.series_id for series in scientific}
                     and (item.get("native_style") or {}).get("line_width_pt") is not None]
    if native_widths:
        lines.append("- 保存重开后的 Origin 原生曲线线宽回读（pt）：%s。" %
                     "；".join("%s = %.4g" % (sid, float(width)) for sid, width in native_widths))
    else:
        lines.append("- 保存重开后的 Origin 原生曲线线宽：本次未取得回读证据。")
    lines.append("- 字体 %s；轴标题 %.2f pt；刻度标签 %.2f pt。"
                 % ((config.get("global") or {}).get("font_family"),
                    (config.get("labels") or {}).get("axis_title_font_size", 0.0),
                    (config.get("labels") or {}).get("tick_label_font_size", 0.0)))
    for key in sorted((backend_info.get("ticks") or {})):
        plan_ticks = backend_info["ticks"][key]
        lines.append("- %s 轴主刻度：Origin 原生 By Increment，间隔 %s；数值标签由 Origin Axis 生成。"
                     % (key, plan_ticks["interval"]))
    if backend_info.get("native_axis"):
        lines.append("- Axis 机制核对：已回读 Origin 的 From/To、Increment、tick mask 与标签字号；"
                     "未创建模拟轴线、刻度或刻度数字的普通图形对象。")
    # The plot type owns its visual-rule wording (imported here so that the document
    # layer keeps no dependency on the plot-type modules at import time).
    from ..plot_types import readme_lines as plot_type_readme_lines

    lines.extend(plot_type_readme_lines(plan, config))
    lines.append("- 图例：%s。" % _legend_text(plan))
    lines.append("")
    lines.append("## 导出与验收")
    lines.append("")
    lines.append("- SVG（主）：`%s`；PNG（600 dpi）：`%s`；可编辑工程：`%s`。"
                 % (files.get("svg", "-"), files.get("png", "-"), files.get("opju", "-")))
    png = export_report.get("png") or {}
    if png:
        lines.append("- PNG：%s×%s px、%s dpi、颜色空间 %s、四角白底 %s。"
                     % (png.get("width"), png.get("height"), png.get("density"),
                        png.get("space"), export_report.get("checked", {})
                        .get("png_background_white")))
    svg = export_report.get("svg") or {}
    if svg:
        lines.append("- SVG：矢量元素 %d 个；嵌套矢量对象 %d 个；栅格 image 节点 %d 个；白底 %s。"
                     % (svg.get("vector_elements"), svg.get("nested_svg"),
                        svg.get("image_elements"), svg.get("white_background")))
    if export_report.get("issues"):
        lines.append("- 导出检查问题：")
        for issue in export_report["issues"]:
            lines.append("  - %s" % issue)
    else:
        lines.append("- 导出检查：未发现问题。")
    measured_width = (export_report.get("checked") or {}).get("curve_line_width_pt")
    if measured_width is not None:
        lines.append("- SVG 路径线宽估值：%.2f pt（导出路径换算，用于导出核对；不等同于 Origin 原生对象线宽）。" % measured_width)
    if export_report.get("visual_deviations"):
        lines.append("- 视觉参数实测与模板配置的差异（需确认）：")
        for item in export_report["visual_deviations"]:
            lines.append("  - %s" % item)
    acceptance = export_report.get("acceptance")
    lines.extend(["<!-- image-review:start -->", _image_review_text(acceptance or {}),
                  "<!-- image-review:end -->"])
    if backend_info.get("visual_check"):
        lines.append("- 预览生成记录（不能替代实际图像审阅）：%s" % backend_info["visual_check"])
    if acceptance:
        lines.extend(["", "<!-- acceptance-summary:start -->", "## 验收状态", "",
                      "- 自动检查通过：%s；完整验收通过：%s。" %
                      (acceptance["automatic_checks_passed"], acceptance["accepted"])])
        for name, stage in acceptance["stages"].items():
            lines.append("- %s：%s（%s）。" % (name, stage["status"], stage["method"]))
            for reason in stage.get("reasons", []):
                lines.append("  - %s" % reason)
        lines.append("- 成果与自动证据绑定：%s。" % (acceptance.get("artifact_binding") or {}).get("status", "not_run"))
        lines.append("<!-- acceptance-summary:end -->")
    lines.append("")
    lines.append("## 验收等级（QA）")
    lines.append("")
    if qa_report:
        lines.append("- QA Level %s（%s）；执行的检查层级：%s。"
                     % (qa_report.get("level"), qa_report.get("level_name"),
                        ", ".join(str(item) for item in qa_report.get("levels_run", []))))
        checks = qa_report.get("checks") or {}
        if "series_planned" in checks and "points_planned" in checks:
            lines.append("- 科学数据统计（marker 表现点除外）：%s 条系列、%s 个数据点；X 范围 %s；Y 范围 %s。"
                         % (checks.get("series_planned"), checks.get("points_planned"),
                            checks.get("x_range"), checks.get("y_range")))
        if qa_report.get("pointwise"):
            lines.append("- 逐点核对：%s 个点、%s 条系列。"
                         % (checks.get("verified_points"), checks.get("verified_series")))
        else:
            lines.append("- 逐点核对：未执行（Level 3 才执行；本次为 Level %s）。"
                         % qa_report.get("level"))
        if qa_report.get("issues"):
            lines.append("- QA 问题：")
            for issue in qa_report["issues"]:
                lines.append("  - %s" % issue)
        else:
            lines.append("- QA 结论：未发现问题。")
    else:
        lines.append("- 本次运行未记录 QA 报告（旧版本产物）。")
    lines.append("")
    lines.append("## 文件与临时目录")
    lines.append("")
    lines.append("- 交付文件：%s。" % ", ".join("`%s`" % name for name in files.values()))
    lines.append("- 过程文件（工作表转写、Origin 导出中间文件、预览）按运行写入 `.tmp/<run_id>/`；"
                 "成功后清理当前运行目录，失败目录保留供排查。此前验收/审图/规范文档保存在 `verification/previous_runs/`。")
    lines.append("")
    return "\n".join(lines)


def _margins_text(margins: Dict) -> str:
    if not margins:
        return "-"
    return "L%.2f/R%.2f/T%.2f/B%.2f mm" % (float(margins.get("left")),
                                           float(margins.get("right")),
                                           float(margins.get("top")),
                                           float(margins.get("bottom")))


def _legend_text(plan) -> str:
    if plan.legend.mode == "cycle_gradient_bar":
        cycles = plan.legend.grouped.get("cycles") or []
        return ("Cycle %s–%s 渐变色条（经用户批准替换逐条图例），"
                "标题与首末圈标签均为 Origin 原生对象" % (cycles[0], cycles[-1]) if cycles
                else "Cycle 渐变色条")
    if plan.legend.mode == "grouped":
        plan_info = plan.page.get("legend_plan") or {}
        return ("分组图例：样品色块 %s；指标条目 %s；位置 %s"
                % (", ".join(row["label"] for row in plan_info.get("samples", [])),
                   ", ".join(str(row.get("label")) for row in plan_info.get("metrics", [])),
                   plan_info.get("corner")))
    return "Origin 原生图例：%s" % "；".join(plan.legend.entries)


def dumps(document) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2)
