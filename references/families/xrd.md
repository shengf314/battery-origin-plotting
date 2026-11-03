# XRD已提供谱与参考系列

下文只保留绘图契约与结构示例。私人历史工程未随公开包分发，不作为运行前提或本次科学确认。

`plot_type: xrd`、`data.kind: excel_processed_series`、`semantics.variant: provided_spectrum`。只绘制已提供的2θ–intensity和参考点；不扣背景、归一化、纵移、换波长或定相。需要逐谱明确公式归一化时，先走独立 [XRD 处理](../origin-processing.md)，method 须由当前任务明确选择；此绘图入口不自动处理。公共表/来源/连接严格契约见 [processed-input.md](../processed-input.md)。

## 标准字段、单位、尺度与来源

|项目|要求|
|---|---|
|字段|SeriesID、Sample、X、Y；Role/Condition可在列或metadata，独立实验/条件另ID|
|X|`two_theta`、unit=`degree`；显式scale linear/log10、direction ascending/descending；当前不接q/d-spacing|
|Y|`intensity`；unit counts、counts/s、cps、a.u.或%；与全部共享此轴系列的实际值一致|
|辐射|`semantics.radiation`有已知正wavelength、unit、source，不默认Cu Kα或任意λ|
|处理记录|preprocessing.normalization/offset各有boolean applied；true须已有method/parameters/source，不执行处理|
|参考|独立SeriesID、role=reference、reference_id/source/legend；提供实际X/Y点，不凭卡号造峰|

**规范依据：** [Rigaku powder XRD](https://rigaku.com/resources/techniques/powder-x-ray-diffraction)的2θ–intensity与Bragg条件说明λ影响角位置； [ICDD参考数据库](https://estore.icdd.com/pdf-5/)条目有不同来源。实验与参考λ/身份需可比，缺辐射信息不能凭常见配置补值；绘图不执行λ换算或物相鉴定。scale=log10遇零/负强度报不兼容，不删点/平移以通过。


## 样品、边界、图例和处理身份

测量、已处理谱、参考各ID/role/source明确；processed须method，reference须reference_id。fit/background/component 不接入；已有扣背景处理记录是实验谱来源，不是要绘制背景模型。连续scan按原提供行序，不按2θ排序；不同condition/role不跨线，断块用明确Segment。图例表示样品/条件与reference身份，不靠颜色猜层。

样品身份、图例与源列若冲突，应停止并核对当前来源；不能根据曲线外观修正样品。

方法未知可以如实记录结果来源/method unknown进行整理；normalization.applied/offset.applied是否发生未知时，不填false绕过契约。若已知处理发生但参数未知，保留未知记录并集中确认是否可执行，不补方法/参数。未知样品映射、λ、量纲仍是决定性缺口。

## 原生Origin步骤、错误与QA

1. 校验标准谱表和λ/处理状态/参考身份，report一次列出缺信息、重复、连接块冲突及所有源行；只筛选整条系列。
2. 每个区间写任务X/Y列和source/role/unit注释，按connection创建一层原生系列、科学axis title/legend。沿用现有模板； [Origin add_plot](https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GLayer.html)明确plot源， [range notation](https://docs.originlab.com/labtalk/guide/range-notation/)用于读回，不采用旧sparkline失败range。
3. 保存重开检查所有谱/参考的真实XY源和逐点值/顺序，axis direction/scale、角色/图例、λ与已有处理记录；确认没有自动归一化/offset/背景扣除。峰形或card文字不替代身份验收，实机状态由执行报告给出。

**集中追问：** 样品/condition冲突、辐射λ/unit/source、强度单位/是否已有normalization/offset、参考实际点及reference_id、连续scan区间。缺参考点不阻止明确实验谱整理，但不生成reference；缺决定性语义不开始绘图。

## 中文调用与最小标准表

“用已经整理的Sample_A XRD表绘图，X是2θ degree，Y是counts；波长采用仪器记录，未做归一化和纵移，不做相鉴定。”

|SeriesID|Sample|X|Y|Role|
|---|---|---:|---:|---|
|Sample_A_scan|Sample_A|20.0|120|measurement|
|Sample_A_scan|Sample_A|20.1|180|measurement|

合成结构示例，非历史谱或真实λ。配套X=`two_theta/degree/linear/ascending`、Y=`intensity/counts/linear/ascending`；radiation填真实正wavelength/unit/source；preprocessing=raw/source，示例明确normalization.applied=false、offset.applied=false；series_metadata.Sample_A_scan为role=measurement、legend/source、connection=line。若真实源的applied状态未知，不能沿用示例false。参考另ID、role=reference、reference_id/source、connection=scatter，保持提供位置及强度。

参考系列额外声明reference_kind=supplied_curve/peak_positions。peak_positions仅接受scatter，禁止把离散峰连成连续谱；该表示不等于已实现原生棒线或独立参考层。
