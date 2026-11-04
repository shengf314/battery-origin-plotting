# 循环性能、CE与分段倍率性能

下文只保留绘图契约与结构示例。私人历史工程未随公开包分发，不作为运行前提或本次科学确认。

入口均为 `data.kind: excel_cycle_summary`；循环图 `plot_type: cycle_performance`，倍率图 `plot_type: rate_capability`。此 A 层采用圈级汇总，不从 GCD 轨迹提取容量或计算 CE。用户给受支持蓝电／新威工程时，先由 [独立预处理](../instrument-projects.md) 校验原生循环／容量并记录必要的简单公式，生成本入口所需标准表。公共字段见 [input-schema.md](../input-schema.md)，倍率阶段实现见 [rate-capability-implementation.md](../rate-capability-implementation.md)。

## 字段、单位、X/Y与分组

|图族|标准字段|坐标/单位语义|
|---|---|---|
|Cycle|Sample、Cycle、Discharge Specific Capacity、Coulombic Efficiency|X=圈次；左Y=放电质量比容量（例如mAh g⁻¹）；右Y=提供的CE|
|Rate|Sample、Cycle、Rate、Discharge Specific Capacity|X=圈次；Y=提供的放电质量比容量；Rate为显式正C-rate文本|

Cycle的 `data.semantics.ce_unit` 为 `percent`（旧契约默认）或 `fraction`。两者均保留存储数值，不乘100/除100；fraction轴标签不得写%。Excel百分比格式与底层值有歧义时集中确认，不能按数值大小猜单位。轴尺度/方向和范围继续采用已确认模板；本页不改视觉默认。


**规范依据：** [Origin Axis/GLayer](https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GLayer.html)的原生曲线源与 [layer axis object](https://docs.originlab.com/labtalk/ref/layer-axis-obj/)的独立Y尺度需要分别确认。循环图沿用单Layer原生Y/Y2结构，每样品的容量/CE是不同科学系列，图例表达样品+指标；marker子plot不增加科学观测数。旧get-ay整数含义不可未经复验套用。

每Sample/Cycle只能一条汇总记录；重复阻断，不平均或任选。Cycle保留提供圈次顺序，非单调顺序须先说明连线影响。Rate的现有实现将只读内存副本按Cycle排序，保留源行映射；这项既有行为不扩展到GCD/processed XY。

## 倍率阶段与连接边界

Rate必须在表中明确给出，如 `0.1 C`、`2C`、`C/10`；无单位数字与slow/fast拒绝。按每个样品连续圈记录的相同精确倍率定义stage，恢复初始倍率是新stage，不能按唯一Rate聚合；多个所选样品的完整 `(Rate,start_cycle,end_cycle)`程序须一致。缺圈不补点，显式请求缺失圈阻断。


旧圈级入口没有processed XY的Segment能力；阶段是科学元数据，不代表自动断线。缺测/独立实验被拼成同一样品汇总时先整理及报告连接影响，不宣称空行已被自动处理为gap。保持率、CE或C-rate基准的未知方法可记录，不能计算新结果或用臆造字段覆盖契约缺口。

## Origin步骤、错误与QA

1. 校验Sample/Cycle唯一、实际使用的数值、CE表示或逐圈Rate；一次列出缺字段、冲突样品/阶段、重复源行。此 A 层使用现有标准入口；工程原生记录的读取与公式整理在独立预处理完成，不在渲染时补算。
2. 写各科学系列独立X/Y列。Cycle容量绑定左Y、CE绑定原生右Y2并确认独立尺度；Rate一Y轴并保留stage标签。原生标题/legend表达量名、单位及sample/metric；视觉仍由原模板控制。
3. 保存重开，读回所有XY源、逐点值/源行、原生轴与plot-to-side；Cycle确认fraction/percent标签正确且没有换算，Rate确认stage程序和恢复段未合并。核对科学点数时去除marker表现层计数差异，不能用plot-n替代有效点计数。实机状态由执行报告给出。

**集中追问：** 样品列映射、容量单位/基准、CE表示/定义、Rate单位与1 C依据、阶段边界冲突、重复/缺测、非单调Cycle连接。未知保持率分母不影响已有容量/CE整理，但阻止自动添加保持率计算。

## 中文调用与最小表

“用标准圈级表画Sample_A循环性能，CE按fraction原值放右轴，不换算百分数；现有模板。”设 `plot_type: cycle_performance`、`data.semantics.ce_unit: fraction`。

|Sample|Cycle|Discharge Specific Capacity(mAh/g)|Coulombic Efficiency|
|---|---:|---:|---:|
|Sample_A|1|100|0.98|
|Sample_A|2|99|0.99|

“画Sample_A的分段倍率放电容量，按表里的C-rate标阶段，末尾恢复倍率单列，保留来源行。”设 `plot_type: rate_capability`。

|Sample|Cycle|Rate|Discharge Specific Capacity(mAh/g)|
|---|---:|---|---:|
|Sample_A|1|0.1 C|100|
|Sample_A|2|0.1 C|101|
|Sample_A|3|1 C|90|
|Sample_A|4|0.1 C|99|

两表均为合成结构示例，不能当作历史数据或本机验收证明。
