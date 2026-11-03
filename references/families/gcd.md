# GCD、选定圈次与已提供Na含量

下文只保留绘图契约与结构示例。私人历史工程未随公开包分发，不作为运行前提或本次科学确认。

用于首圈跨样品、单样品多圈、指定圈次的充放电轨迹；入口为 `plot_type: gcd`、`data.kind: excel_long`。容量–圈数性能转到 [cycle-rate.md](cycle-rate.md)。本页只规定科学语义，视觉参数继续使用既有独立模板；输入细节见 [input-schema.md](../input-schema.md)。

## 字段、单位与轴绑定

|字段/设置|要求与作用|
|---|---|
|Sample|按公共单/多样品规则；多样品必须明确身份，不由文件名、颜色、趋势分配|
|Cycle / Branch|每点圈次有限整数；分支明确 `charge` / `discharge`，不能按电流或容量列猜测|
|Voltage|已有电压数值，单位/参比明确，例如V vs. Na⁺/Na|
|Charge Specific Capacity / Discharge Specific Capacity|`specific_capacity`表示的两分支列；当前分支使用的值必须有效，单位须明确为质量比容量，不能把绝对Capacity/Q当同义词|
|Charge Na Content / Discharge Na Content|`na_content`表示的已有数值；明确绝对x还是Δx、参考态、单位/符号。用户授权容量转换时另用[独立转换流程](../na-conversion.md)，绘图不自动调用|
|selection.x_representation|`specific_capacity`（默认）或 `na_content`；不要自动选择未知物理量|
|selection.axis_binding|`capacity_voltage`（默认：容量/Na列为X、Voltage为Y）；`voltage_capacity`（Voltage为X、容量/Na列为Y）|



## 分组、边界、图例与处理身份

按Sample + Cycle + Branch成独立系列，组内保留Excel行序，两分支不拼成跨分支线。圈次选择使用GCD自己的 `selection.mode: all/single/selected/range` 与对应值。图例明确样品+圈次，分支由对应系列元数据保留。当前原生后端仅输出逐圈 entries；旧 `cycle_gradient_bar` 输入保留兼容但会转为 entries，不输出原生渐变色条。这是升级前已有的能力缺口；本轮未完成100圈图例的实机与图像验收，不能宣称色条或大量圈次布局已通过。


缺测/重复/被中断后重新出现的分支要集中列源行和连接影响。旧GCD入口没有processed-series的通用Segment契约，不能暗示它自动支持所有断点；按现有契约确认可用分支，存在未解决连接边界则先整理并停止执行。不通过跳点、重排、平滑弥补，获准例外按原契约记录。

## Origin步骤与QA

1. 只读校验标准长表、当前Branch所用列及筛选完整性，在计划中记录每个Sample/Cycle/Branch和源行；不要引用旧工程的临时Graph1或空plot。
2. 为每条独立分支写任务工作表X/Y列，按axis_binding创建原生曲线和对应原生轴标题；保存数据来源/单位/分支。调用机制见 [rendering-pipeline.md](../rendering-pipeline.md)；[Origin add_plot](https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GLayer.html)定义显式X/Y列绑定。
3. 保存新OPJU，重开检查真实源列、逐点数值/顺序、分支数、图例分组和横纵轴语义；按 [Origin range notation](https://docs.originlab.com/labtalk/guide/range-notation/)的 `-wx/-wy`读回源。plot数量或原生`-n`不等于有效点数；视觉检查不能替代绑定读回。

**集中追问：** 样品映射、单位/参比、Na是x还是Δx及符号参考、目标axis_binding、缺失预期分支、重复/缺测和断开后是否连线。方法未知可以记录整理，但这些关键语义不能猜。此页不声明实机验收状态。

## 中文调用与最小表

“用这份标准GCD长表画Sample_A第1圈充放电，横轴比容量、纵轴电压，采用现有模板；不改点和顺序。”选择 `x_representation: specific_capacity`、`axis_binding: capacity_voltage`、`mode: single, cycle: 1`。要电压横轴时明确改成 `voltage_capacity`。

以下为结构示例，非历史科研值；两容量列存在，非当前分支的空值不参与该点数值校验。

|Sample|Cycle|Branch|Voltage(V)|Charge Specific Capacity(mAh/g)|Discharge Specific Capacity(mAh/g)|
|---|---:|---|---:|---:|---:|
|Sample_A|1|charge|2.5|0||
|Sample_A|1|charge|3.0|20||
|Sample_A|1|discharge|3.0||0|
|Sample_A|1|discharge|2.5||18|

科学来源需另外注明参比和比容量基准。Na变体用已确认的Charge/Discharge Na Content列替换容量列，不从此示例换算。

## 容量换算的授权边界

明确要求计算 Na 坐标时，读 [na-conversion.md](../na-conversion.md)。逐分支确认质量归一基准、固定化学式单位/M来源、Na电量归属假设、容量差的符号、Q_ref 和 Δx 偏移或绝对 x_ref。默认第一点或以charge名称推断参考态均不允许。转换返回新坐标和来源记录，再独立整理为标准绘图输入，不改写用户源表。
