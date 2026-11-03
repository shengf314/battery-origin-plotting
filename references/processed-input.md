# 已提供 XY 数据的输入契约

本页是 `eis`、`gitt`、`xrd`、`icp` 的正式输入规范。XPS、dQ/dV 整族及 fit/background/component 角色不接入；不能通过更换图族名或 role 将拟合、分峰、求导结果作为普通数据路由。GITT 明确提供的 D/log10 D 结果是只读绘图例外，不在本技能计算。使用 `data.kind: excel_processed_series`；历史 OPJU、仪器原始文件和截图不因此成为正式绘图输入。原始数据分析与绘图分开：此入口只绘制已有数值，不求导、不拟合、不计算扩散系数、不分峰、不变号、不转换单位、不排序、不删除或补齐记录。

## 标准工作表

|字段|要求|含义|
|---|---|---|
|SeriesID|必需，文本|一个明确的科学系列；不得用同一个 ID 混入另一种角色或测试条件|
|Sample|必需，文本|样品对象；同一系列内必须一致|
|X / Y|必需，有限数值|已经采用声明单位和符号约定的绘图坐标|
|Segment|可选；存在时每行必填|同一系列的独立连续区间，区间之间不连接|
|Cycle / Branch|可在列或系列元数据声明|循环号和 charge/discharge 分支；GITT 必须明确分支|
|Role|可在列或元数据声明|measurement、processed、derived、reference；fit/background/component 不属于正式契约|
|Condition|可选|如 before-cycle/after-cycle；条件改变必须另设系列或区间|
|Frequency|可选；存在时每行正数|频率 Hz，严格保留提供的顺序；须声明 frequency.unit/order|
|Phase|可选；存在时每行必填|原表已有的区段标签；不实现 GITT 时间响应图|
|Element|ICP 每行必需|与 X 元素索引的一一映射，例如 Mn、Ni、Ti、Na|

例如已给 EIS 测量数据：

|SeriesID|Sample|X|Y|Frequency|Condition|
|---|---|---:|---:|---:|---|
|Sample_A_after_measured|Sample_A|10|-2|1000|after-cycle|
|Sample_A_after_measured|Sample_A|20|5|100|after-cycle|

此表仅演示结构，数值不来自历史工程。`field_map` 与旧契约同向，使用“原始列标题 → 规范字段”，例如 `{"样品名":"Sample", "实部/Ohm":"X"}`。规范列名只接受大小写及空格等拼写差异；不根据未知标题猜测量纲。一个字段不能绑定两列。

## 显式科学语义

`data.semantics.x` 和 `.y` 均必须声明 `quantity`、`unit`、`scale`（linear/log10）和 `direction`（ascending/descending）。`label` 可提供科学轴标题。显示方向不改变源数据顺序；对数轴要求所有相应坐标大于零。Y2 不由本入口自动推断或启用。

每个 `SeriesID` 都必须有 `series_metadata`，至少包括 `role`、`legend`、`source`、`connection`（line/scatter/line_points）。角色为 processed、derived 时还必须记录 `method`；reference 必须记录 `reference_id`。这些是已有结果的来源记录，不是授权本技能运行该方法。图例必须明确代表样品、分支、测量/明确简单公式结果或参考等对象；不能依靠颜色猜测角色。

`preprocessing` 必须记录 `state`（raw/provided_processed/provided_results）和 `source`。声明已经执行的处理时，应在该记录内保留方法和参数；未知历史方法可明确记为未知，不虚构历史处理。轴、系列元数据、处理记录和方法的类型错误会集中报告。决定坐标含义的 quantity、unit、符号约定、分支、归一化 basis 等仍须明确，不能以 unknown 绕过。

已有的非空 `source` / `method` 字符串继续兼容。`source` 必须定位到已提供数据或历史记录，不能填 unknown；也可以使用 `{"status":"declared","value":"结果表.xlsx!Sheet1:X/Y","archive_id":"原有标识"}`。方法可写为 `{"status":"declared","name":"历史方法名称","parameters":{"历史参数":"原记录值"},"software":{"name":"原工具","version":"原版本"}}`。这些附加记录原样保存，不执行其中的方法。

已处理结果的历史方法暂不可追溯时，允许 `method: "unknown"`，或更明确的 `{"status":"unknown","reason":"历史处理步骤未留档"}`。这只允许绘制已提供结果，并在报告中记录方法缺口；不会把未知方法标成已核实。缺失方法仍会阻塞，需要明确声明 unknown。已实施的谱图 normalization/offset 若方法明确 unknown，可不虚构参数；已知方法保留原有参数要求。其他旧方法字符串不因本次增加结构化记录而被要求补新字段。建议补录方法参数、软件版本及历史记录位置，以便后来复核。

`source.scientific_traceability` 汇总 `declared` / `unknown` 状态、逐项声明和缺口。`declared` 仅表示用户提供了声明；`scientific_truth_verified` 始终为 false，本入口不核实方法或结果的科学真实性。未提供的历史方法参数也会列为缺口，但不会据此运行分析或阻塞旧结果绘图。完整的 source、method、parameters 和附加历史字段仍保留在系列元数据中，用于原生列注释与回读验收。

GITT 的旧 `sodium_content` 输入若没有 Na 定义/参照记录，保留原坐标并产生 warning 与溯源缺口。新提供的 `na_content` 声明须是对象，含已知的 `definition`、`reference`、`source`，如 `{"definition":"每化学式单位的绝对 Na 含量","reference":"原始化学式单位与零点定义","source":"原有组成或换算记录"}`。显式声明 unknown、错型或空定义不能绕过校验；本入口不从容量推算 Na，也不自行决定绝对含量、变化量或零点。

嵌套 source/method/历史记录中的 `requested_*`、非空 request/requested、execute 或 `status: requested/to_be_computed/to_be_applied` 会阻塞，防止将待计算、平滑或单位换算请求藏在来源记录中。自由文本中的已实施方法名称不会被猜测为执行命令。

```json
{
  "variant": "nyquist",
  "x": {"quantity": "real_impedance", "unit": "Ohm", "scale": "linear", "direction": "ascending", "label": "Z′ (Ohm)"},
  "y": {"quantity": "minus_imaginary_impedance", "unit": "Ohm", "scale": "linear", "direction": "ascending", "label": "−Z″ (Ohm)"},
  "sign_convention": "minus_imaginary",
  "frequency": {"unit": "Hz", "order": "as_provided"},
  "preprocessing": {"state": "raw", "source": "明确的测量结果表/列定位"},
  "series_metadata": {
    "Sample_A_after_measured": {"role": "measurement", "legend": "Sample_A – after cycle – measured", "source": "原表/列定位", "connection": "scatter", "condition": "after-cycle"}
  }
}
```

完整 PlotSpec 的入口字段为 `task_name`、`plot_type`、`data:{kind,file,sheet,semantics}`、`style_template`、`backend:{name:"origin"}`。视觉模板仍使用现有 `templates/publication_visual_template.yaml`，不在数据契约中增加线宽、字号或配色默认值。

## 正式变体

|图族 / variant|X / Y 约束|必需的附加说明|明确不执行的操作|
|---|---|---|---|
|eis / nyquist|real_impedance / imaginary_impedance 或 minus_imaginary_impedance；两轴同为 Ohm、kOhm 或 mOhm；线性轴|sign_convention=imaginary/minus_imaginary 与已有 Y 相符；实测和明确参考数据使用不同 SeriesID/Role，不接拟合结果；若有频率，声明 Hz/as_provided|不将 ImZ 自动取负；不拟合电路；不重排频率|
|gitt / supplied_diffusion|已提供的 diffusion_coefficient：cm2 s-1 或 m2 s-1；或已经取 log10 的 log10_diffusion_coefficient：log10(cm2 s-1)/log10(m2 s-1)|preprocessing.diffusion 的方法/来源；role=derived；charge/discharge；X 明确为 voltage、sodium_content 或 time|不从脉冲响应计算 D；已有 log10 D 必须用线性 Y 轴，禁止重复取对数；时间响应图不在本技能范围|
|xrd / provided_spectrum|two_theta：degree；intensity：counts、counts/s、cps、a.u. 或 %|radiation 的有限正数波长（不接受 bool）、单位 angstrom/Å/nm/pm/m、来源；normalization.applied 和 offset.applied 必须明确；已有归一化/平移记录方法/参数/来源或明确未知历史方法；参考曲线需来源标识|不做相鉴定、不换算波长、不做背景扣除/归一化/纵移|
|icp / element_ratio 或 normalized_composition|element_index：1；element_ratio：1；atomic_fraction/molar_fraction/mass_fraction：1 或 %|Element 与索引一一对应；preprocessing.composition 的 basis、method、source；无连线 scatter|不从浓度重算化学式或配比；本轮不启用浓度图和误差棒|

GITT 只画已给 D/log10 D；时间响应、脉冲识别和 D 计算不在范围内。ICP 的浓度图未实现，不能通过修改说明文案宣称已支持。组合图、多层图、不同量纲的双轴、原始仪器格式和误差棒也不属于这个入口的实际能力。

## 顺序、连接和拒绝规则

1. 每个系列内逐点保留 Excel 原顺序。默认工作表按连续块组织；同一个 SeriesID/Segment 在另一块之后重新出现会阻塞，要求给独立区间不同 Segment。空白行也形成待确认边界，不能把断开的曲线自动连起来。
2. `row_layout: interleaved` 只允许明确的 scatter 系列按 ID 分组，因为这些点没有连线。连续曲线的穿插行仍需明确拆段，不能借排序恢复连接。
3. 同一系列/区间内样品、循环、分支、角色或测试条件改变会阻塞。列与元数据矛盾也会阻塞。不同独立系列可有相同坐标，不据此删点。
4. 规范记录重复会阻塞，不删除、不平均。重复观测应使用明确的独立 ID 或区间。缺值、文本数值、无缓存公式及非有限数阻塞，不自动跳过。
5. ICP 元素索引仅用于轴标签绑定；同一元素和索引必须有一致映射。组成小数须在 0–1，百分数须在 0–100；不自动乘 100，不验证未声明的组成闭合关系。
6. 本轮不支持误差棒。表中含 YError、SD、标准误等已识别不确定性字段，或元数据要求 error_bars，会明确阻塞；不能静默忽略科学信息。

可使用 `samples: [{"name":"Sample_A"}]` 筛选并明确样品顺序，以及 `selection.series_ids`、`selection.cycles`、`selection.branches` 的显式非空列表筛选整条系列。筛选不截取区间中的单点，不改变点顺序；找不到的样品、系列、循环或分支会阻塞。多个条件取交集，交集为空也会阻塞。未知 selection 字段不被忽略；本入口不接受 sort、smooth、normalize 等命令。

## 原生工程和验收

完成输入校验后，每个独立区间生成一个 SeriesSpec 和一对 Origin X/Y 工作表列；每个系列的 plot_kind 来自显式连接语义。quantity/unit、来源行、分支与科学角色保存在元数据及原生列注释中。一层原生图窗使用这些列创建可编辑曲线、轴标题和图例。

验收须比较规范数据与计划的系列 ID、每个点的坐标和原顺序、来源行、单位、分支/循环/条件边界、连接方式及轴的方向/尺度。Origin 实机验收还要保存 OPJU，重新打开后回读工作表、图层和真实数据绑定，并检查导出图像。契约单元测试不替代实机验证；接口合成案例也不等同于历史方法的科学真实性核实。具体历史来源及本轮验证状态保留在独立任务报告内。

所有图族的误差棒请求当前均阻塞，不能默默省略；元素ratio不得为负，不作abs修正。XRD reference另声明reference_kind=supplied_curve/peak_positions，离散峰仅支持scatter。
