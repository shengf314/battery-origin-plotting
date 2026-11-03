# 倍率阶段与居中标签

本页对应 `rate_capability` / `excel_cycle_summary` 的科学规则。曲线按当前模板0.5pt，阶段标签与其他文字均常规体、可见刻度朝外；5.8pt全点符号、样品配色、字号和画布保持。以下规则只决定倍率阶段识别与阶段标签科学位置。一般输入要求见 [原有输入](input-schema.md)，科学角色与验证边界见 [循环与倍率](families/cycle-rate.md) 和 [能力状态](capability-status.md)。

## 可复制的输入表

单个数据工作表按圈提供已有数值。`Cycle` 是整数，`Rate` 必须含明确 C-rate 单位；放电容量沿用本入口的 `mAh g⁻¹` 语义。推荐填写每行 `Sample`，缺失样品列或空样品按原有公共命名/显式单样品规则处理。容量不用于反推倍率。

|Sample|Cycle|Rate|Discharge Specific Capacity|
|---|---:|---|---:|
|A|1|0.1 C|180|
|A|2|0.1 C|179|
|A|3|C/10|178|
|A|4|0.1 C|177|
|A|5|0.1 C|176|
|A|6|1 C|160|
|A|7|1 C|159|
|A|8|1 C|158|
|A|9|0.1 C|175|

示例数值只解释结构，不是实验数据。1–5 圈是第一个阶段，标签 X=3；6–8 圈是第二个阶段，X=7；第 9 圈恢复到初始倍率，仍是第三个阶段，X=9。可有任意数量的阶段，无固定七阶段或固定每段五圈的假设。

## 阶段规则

1. 仅在内存按 Cycle 排序，保存源行号；不改 Excel，不补圈。
2. 相邻记录的规范 Rate 相同且 Cycle 差为 1，才属于同一阶段。0.1 C 与 C/10 采用既有精确有理数等价规则。
3. Rate 改变、Cycle 缺口都会开始新阶段。恢复倍率不与较早同倍率阶段合并。
4. 多样品需具有相同的倍率、起止圈和阶段次序；不一致仍阻塞。
5. 标签的 X=`(start_cycle + end_cycle) / 2`，单位是真实 Cycle。五个等间隔连续圈对应第三个点；偶数点阶段可落在中间两点之间。

每样品仍为一条完整容量系列，保留原有 Cycle–capacity 配对与排序。阶段标签不跨缺圈合并；**既有完整系列的连线可以跨缺圈，本次不改变连接契约，也不插值或补点。** `plan.page.cycle_gaps` 按样品记录 `after_cycle`、`before_cycle`、`missing_from`、`missing_to`、`missing_count`，不会展开或生成缺失记录。

## 标签 API

在 PlotSpec 的 `overrides.plot_type.rate_labels` 中设置：

|字段|自动模式|显式旧比例模式|
|---|---|---|
|`y_position`|缺省或 null：按各阶段全样品容量边界定位|0–1：保留 `x_scale_y_fraction` 的比例 Y 位置，优先于 placement|
|`placement`|`above`（缺省）或 `below`|不改变显式比例 Y；非法值仍报错|
|`font_size`|沿用既有值；null 继承全局刻度字号|保留既有继承和覆盖行为|
|`y_offset_mm`|null=0；非负，增加沿 placement 方向的间距|保留旧 `gap_mm` 字段和后端解释，本次不改旧偏移行为|

自动模式的 Y 使用本阶段 **所有样品、所有已有点** 的极值。above 取最大容量之上，below 取最小容量之下，生成 Origin 原生可编辑的 `layer_scale` 标签；不会只依赖第一个样品或阶段中心点的 Y。

计划在 Origin 测量自动轴范围之前生成。文本中心间距按 `既有字号的半行高度 + y_offset_mm` 换成 mm，再乘以 `全图已提供容量跨度 / 既有图层高度` 换成容量坐标；间距已计入 position，因此自动标签的 `gap_mm=null`，避免重复偏移。所有容量相同时，仅标签几何采用 `max(abs(capacity), 1)` 的非零跨度，实际数据不变。这个 mm 换算采用数据范围估计；最终 Origin 自动范围、字形大小与裁切仍须实机和图像验收，不能只凭离线测试宣称视觉通过。

自动上方使用缺省配置即可：

```json
{"overrides": {"plot_type": {"rate_labels": {"y_position": null}}}}
```

自动下方并增加 1 mm 计划间距：

```json
{"overrides": {"plot_type": {"rate_labels": {"placement": "below", "y_offset_mm": 1}}}}
```

保留旧比例输入：

```json
{"overrides": {"plot_type": {"rate_labels": {"y_position": 0.8}}}}
```

可复制的完整 spec 模板见 [rate_capability_auto_spec.json](../examples/rate_capability_auto_spec.json)，其中输入和 output_root 为示例绝对路径，使用前须替换为真实任务路径。表格行示例不代表科学验证；任务测试另用既有合成工作簿。

可直接打开填写的 [rate_input_example.xlsx](../examples/rate_input_example.xlsx) 只有 `RateInput` 一个工作表，第一行为单行字段名，后面是 60 条明确标为 `A_synthetic_example` / `B_synthetic_example` 的合成记录。每个样品含六阶段，每阶段五圈：0.1、0.2、0.5、1、2、0.1 C。末段是独立恢复阶段。

配套 [plot_spec.json](../examples/plot_spec.json) 明确将源列 `Discharge Specific Capacity (mAh/g)` 映射到规范字段 `Discharge Specific Capacity`，其他三列为同名映射；容量值为已有 `mAh/g` 数值，不做质量归一化或单位换算。合成容量用固定示例值说明表格结构，不来自实际实验、历史项目或物理计算。工作表不增加说明行或额外 Notes sheet，以满足现有单数据工作表 reader。填写真实数据时，在副本中替换示例记录和样品名，并同步更新 spec 的样品清单、输入文件和输出绝对路径；阶段数量和每段圈数仍由实际 Rate/Cycle 决定。

## 验收边界

离线测试检查任意阶段数、恢复阶段、缺圈披露、X 居中、全样品 Y 极值、above/below、字号继承、有限值拒绝、旧比例兼容与模板/曲线样式不变。QA-R1 的每样品一条系列规则保留；新增 `rate_cycle_gaps` 核对缺圈记录，QA-R4 核对标签完整计划。

正式验收仍需经过统一 pipeline，保存 OPJU、重开、逐点与原生绑定回读，核对原生标签文字/附件/中心及图像；离线计划通过不等于 Origin 实机通过。本次新增测试不启动 Origin。
