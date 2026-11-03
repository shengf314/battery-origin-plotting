# 提供的元素比与组成散点

下文只保留绘图契约与结构示例。私人历史工程未随公开包分发，不作为运行前提或本次科学确认。

当前 `plot_type: icp`、`data.kind: excel_processed_series`，variant仅 `element_ratio` 或 `normalized_composition`。按已提供ratio/composition绘制元素分类散点；不画bar、不画浓度、不加error bars、不从浓度重算配比/化学式。严格字段/边界见 [processed-input.md](../processed-input.md)。

## 字段、量名、单位与组

|项目|当前要求|
|---|---|
|标准表|SeriesID、Sample、X、Y、Element（每行必需）|
|X|`element_index`、unit=`1`；正整数，Element与index一一一致；native tick label显示元素|
|元素比Y|variant=element_ratio；quantity=`element_ratio`、unit=`1`；明确分母/定义|
|组成Y|variant=normalized_composition；quantity=`atomic_fraction/molar_fraction/mass_fraction`、unit=`1`或`%`；分别范围0–1/0–100，不自动乘100|
|来源|preprocessing.composition有basis/method/source；每ID有role/legend/source/connection；processed/derived需method|
|connection / axes|每ID只能scatter，不连接元素；X/Y显式scale和direction，不照搬历史bar样式；log10遇零/负报不兼容|


**规范依据：** [EPA6010D](https://www.epa.gov/sites/production/files/2015-12/documents/6010d.pdf)§12的浓度→固体含量需要稀释/体积/质量，§9.7区分制样重复与分析重复； [NIST不确定度](https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-appendix-law-propagation-uncertainty)区分统计与Type B来源。当前不运行这些换算/不确定度过程。收到浓度/SD/SE/error字段不能忽略科学信息并继续当ratio；集中报告为本入口不支持，保留可整理资料。

## 样品、边界、legend与processing roles

不同sample/condition/独立观测另SeriesID；每个元素是独立类别点而非连续谱。metadata legend表达样品+ratio/组成basis；不按颜色猜身份。原表有重复观测不得平均/去重；提供明确独立ID或Segment。scatter数据确需穿插可显式row_layout=interleaved，仍保留每组提供顺序/源行。

方法未知可写method="unknown：已有元素比的上游方法未记录"并给来源，明确ratio/组成身份和basis仍必需。分母/质量或摩尔基准未知时允许整理未知清单，不能把basis写随意占位就宣称科学含义通过。不给未声明的闭合关系强制归一，也不以state=raw掩盖已有归一化结果。

## Origin步骤、错误与QA

1. 校验元素索引一一映射、所有Y与ratio/组成basis、无支持外的浓度/error要求；缺值/文本数值/重复/范围冲突一次列源行。Na缺测先报告，不填零或静默跳过。
2. 为每个系列/区间写独立任务X/Y列及Element/role/unit/source元数据，创建一层原生scatter和元素tick labels；不连线、不创建bar/error。[Origin add_plot](https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GLayer.html)定义显式源列与error源，但API能表达不等于本入口已支持其全部功能。
3. 保存重开核对index→Element原生tick、sample/legend、每个点的值/顺序/源行、unit=1/%且无乘除、scatter类型和绑定。零值与缺测分别检查；不以类别条形图外观验证当前散点入口。实机状态由执行报告给出。

**集中追问：** ICP名称对应真实测量技术还是已提供配比、样品/元素身份、ratio分母或composition basis、fraction/percent、已有归一化方法/来源、Na缺测、重复层次、浓度/error需求。未知方法记录不扩展实现范围。

## 中文调用与最小标准表

“用已给Sample_A元素摩尔分数画分类散点，Mn/Ni/Li索引按表，Y是0–1分数；不画柱、不转换百分数、不加误差棒。”

|SeriesID|Sample|X|Y|Element|
|---|---|---:|---:|---|
|Sample_A_molar_fraction|Sample_A|1|0.60|Mn|
|Sample_A_molar_fraction|Sample_A|2|0.20|Ni|
|Sample_A_molar_fraction|Sample_A|3|0.20|Li|

非历史结构示例。variant=normalized_composition；X=`element_index/1/linear/ascending`、Y=`molar_fraction/1/linear/ascending`；preprocessing=provided_results/source、composition.basis明确“所列元素的提供摩尔分数分母”、method/source为已有记录；metadata role=derived、legend/source/method、connection=scatter。真实basis需具体确认，示例0.60/0.20/0.20不授权闭合归一化。元素比改variant=element_ratio、Y=element_ratio/unit1，并给明确ratio分母，不改原值。
