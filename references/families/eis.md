# 已提供的EIS Nyquist

当前状态：**测试阶段**，不列为稳定支持。见 [能力状态](../capability-status.md)。

下文只保留绘图契约与结构示例。私人历史工程未随公开包分发，不作为运行前提或本次科学确认。

`plot_type: eis`、`data.kind: excel_processed_series`、`semantics.variant: nyquist`。只画明确的实测阻抗与已有参考XY；不接 fit/background/component 系列，不计算阻抗、不拟合电路、不自动给Im取负。公共表与校验见 [processed-input.md](../processed-input.md)。

## 字段、单位、X/Y与符号

|项目|明确声明|
|---|---|
|标准字段|SeriesID、Sample、X、Y；Condition可标before/after等；不同条件不能混同一连续区间|
|X|`real_impedance`，单位Ohm/kOhm/mOhm|
|Y|`imaginary_impedance`或`minus_imaginary_impedance`，单位必须与X相同|
|符号|分别对应 `sign_convention: imaginary/minus_imaginary`；声明匹配已提供的Y，不改变数值|
|轴|两轴linear；direction各显式ascending/descending，显示方向不重排采样|
|可选Frequency|每行正频率，声明 `frequency: {unit: "Hz", order: "as_provided"}`；不排序|

**规范依据：** [Gamry EIS tutorial](https://www.gamry.com/application-notes/eis/potentiostatic-eis-tutorial)的常用Nyquist为X=Re(Z)、Y=−Im(Z)。若表中已有Im(Z)，本入口如实画Im轴并注明；用户要求−Im图时须另提供符号已确认的结果，不能文案写−Im但实际画Im。 [Gamry感性响应](https://www.gamry.com/application-notes/EIS/accuracy-contour-plots-measurement-and-discussion)允许横轴下方值，负Y不能作为清理理由。不取abs，不按象限猜符号。


## 系列角色、边界与图例

measurement 与明确 reference 各自独立 SeriesID；metadata 必须有 role/legend/source/connection，reference 还需 reference_id。拟合曲线、背景模型与峰组分不在本技能范围，不能改 role 后交入。条件或角色改变须新ID/Segment，连续线中断后再次出现须独立Segment。marker/line选择来自connection声明，所有点保持提供顺序。频率列是辅助溯源而非重排指令。


## Origin步骤、错误与QA

1. 校验Im/−Im与单位/condition、series角色；缺测/文本数值/重复/连续块冲突一次报告源行，不自动跳过或排序。
2. 每个区间写任务X/Y源列，显式创建一层原生plot、axis title和legend；数量/单位/频率/role/源行保留metadata，保持现有视觉模板。[Origin add_plot](https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GLayer.html)支持明确源列；本页不另设外部视觉参数。
3. 保存重开核对真实XY绑定、逐点正负号/顺序/单位、频率列表、条件/role边界、linear轴和native图例；不以半圆外观/电路图片验证数据。实机验收状态由执行报告给出。

**集中追问：** 已提供Y究竟Im还是−Im、阻抗单位、样品/测试状态/SOC、实测与参考身份、来源、frequency是否Hz与区间边界。缺参考不阻止明确的 measurement 系列绘图；不追问拟合方法或生成 fit。

## 中文调用与最小标准表

“画Sample_A循环后的Nyquist，表中Y已经是−Im(Z)，两轴Ohm；按提供频率顺序保留所有点，包括负Y，不再变号或拟合。”

|SeriesID|Sample|X|Y|Frequency|Condition|
|---|---|---:|---:|---:|---|
|Sample_A_after_measured|Sample_A|10|-2|1000|after-cycle|
|Sample_A_after_measured|Sample_A|20|5|100|after-cycle|

非历史值的结构示例。X=`real_impedance/Ohm/linear/ascending`，Y=`minus_imaginary_impedance/Ohm/linear/ascending`，sign_convention=minus_imaginary；frequency=Hz/as_provided；preprocessing.state=raw、source指此已测XY记录。系列metadata为role=measurement、legend="Sample_A – after cycle – measured"、source、connection=scatter，condition与表一致。如有明确参考另设 ID/role=reference/reference_id/source；不接拟合、背景或峰组分结果。
