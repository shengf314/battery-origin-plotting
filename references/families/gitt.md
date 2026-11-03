# GITT已提供的扩散系数或log10 D

下文只保留绘图契约与结构示例。私人历史工程未随公开包分发，不作为运行前提或本次科学确认。

当前入口仅 `plot_type: gitt`、`data.kind: excel_processed_series`、`semantics.variant: supplied_diffusion`。用于已有D分析结果，不绘制time–voltage脉冲响应、不从电压响应计算D，不识别脉冲、不选择扩散模型或拟合参数。公共严格规范见 [processed-input.md](../processed-input.md)。

## 字段、单位、方向和尺度

|项目|本入口要求|
|---|---|
|表字段|SeriesID、Sample、X、Y；Branch在列或metadata明确charge/discharge；Cycle有提供时保留|
|X|voltage(V/mV)、sodium_content(1/Na/f.u.)、time(s/min/h)之一；D对time仍是扩散结果图，不能把Y换成Voltage|
|Y=D|`diffusion_coefficient`，unit cm2 s-1或m2 s-1，所有D>0；显式linear/log10|
|Y=已有log10 D|`log10_diffusion_coefficient`，unit log10(cm2 s-1)/log10(m2 s-1)，Y必须linear，数值可为负|
|direction|X/Y显式ascending或descending，仅控制显示，不排序源数据|
|分析来源|preprocessing.diffusion的method/source；系列role必须derived，有method/source/legend/connection|


**规范依据：** [BioLogic AN70](https://www.biologic.net/documents/determination-diffusion-coefficient-inserted-species-host-electrode-eis-pitt-gitt-techniques-an70/)式(11)的D涉及脉冲时间、质量、摩尔量、面积、稳/瞬态响应及假设。这里只记录已有分析来源，不补参数或重新计算。 [Gamry GITT定义](https://help.gamry.com/Framework/experiments_j_galvanostaticintermittenttitrationtechnique.html)中的pulse/rest响应和D结果不同；前者不属于本技能范围。

## 分组、边界、图例和处理身份

按sample/charge-discharge/cycle/condition明确ID或Segment，保留数据顺序和源行；独立区间不连。图例说明样品+分支+D/预log身份，不由左右位置或下降电压猜branch。已计算D用derived角色，method缺失可写明确unknown及结果来源，不能填造公式/假设；这不会放宽单位、Y身份、branch与正D要求。不能把state改raw来绕过diffusion记录。

样品身份、图例与源列若冲突，应停止并核对当前来源；不能根据曲线外观修正样品。

## Origin步骤、错误与QA

1. 验证provided D/log10 D语义、单位、branch和分析来源，所有结果值保留；非正D、double-log、缺记录/重复/中断区间集中报告。
2. 每个独立区间写任务X/Y列，创建一层原生系列；轴尺度和方向按semantics设置，预log列明确linear，metadata保存derived/branch/source。使用现有模板与 [Origin add_plot](https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GLayer.html)，不从参考图提取轴限/版式。
3. 保存重开核对XY值/顺序、source rows、derived角色/branch、轴direction和scale；确认预log未再次log，正D没有被换算cm²↔m²。实机状态由执行报告给出。

**集中追问：** 仅询问当次未知的D/已Log身份、底数/单位、X物理量与voltage参比/Na定义、样品分支、提供结果来源/未知方法及Segment。复用已确认XLSX底数10，不将其问题重复提出。若请求time–voltage图或现场算D，说明该请求不属于本技能范围，并保留可整理的信息，不能通过改semantics伪装成supplied_diffusion。

## 中文调用与最小标准表

“用已经计算且取log10的Sample_A充电D结果画图，X是Na⁺/Na参比电压V，Y是log10(cm²/s)，用线性Y轴，不计算D、不重复取log。”

|SeriesID|Sample|X|Y|Branch|
|---|---|---:|---:|---|
|Sample_A_charge_logD|Sample_A|2.5|-11.7|charge|
|Sample_A_charge_logD|Sample_A|3.0|-12.0|charge|

非历史结构示例。X=`voltage/V/linear/ascending`，Y=`log10_diffusion_coefficient/log10(cm2 s-1)/linear/ascending`；preprocessing为provided_results、source、diffusion.method/source；系列metadata role=derived、legend="Sample_A – charge – log10 D"、source、method、connection=line，branch与表一致。真实方法未知如实标记，不虚构此示例的D算法。
