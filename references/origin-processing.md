# XRD 简单公式的独立 Origin 处理

当前状态：**测试阶段**。保留入口供试用和回归，不计入当前稳定支持；见 [能力状态](capability-status.md)。

本入口只处理已扣背景 XRD 谱的明确归一化公式，不进行背景选择、扣背景、选峰、平滑、拟合、定相或模型反演。优先用 [独立 B 命令](processing-cli.md)，operation=xrd_normalization；A 的 render 不自动处理。Na 与 ICP 的简单公式分别见 [Na 换算](na-conversion.md) 与 [ICP 计算](icp-calculation.md)。

## 已确认流程与输入

用户明确选择逐谱最大值归一化时，agent 填 `method=max`，最高峰为 1；当前任务尚未确定方法时先确认。输入须来自 xrd/excel_processed_series，X=two_theta/degree，Y=intensity，波长及单位来源明确。只处理 measurement/processed 实验谱；参考峰或其他角色不混入归一化。背景已扣且有记录/来源，谱未纵移；已平移输入应先提供未平移的既有谱，不能在此推测偏移还原。

```python
from plotting_core.domains.processing.origin_analysis import (
    build_xrd_normalization_plan, execute)

plan = build_xrd_normalization_plan(data, {
    "method": "max",
    "background_subtracted": True,
    "background_source": "已有扣背景记录路径或标识",
    "pdf_reference": {"requested": False},
})
# backend 为调用方创建的独立 Origin 会话。
result = execute(backend, plan, authorized=True)
```

build 返回已校验计划和 plan_sha256，不启动 Origin。来源绝对路径及 SHA256 在生成计划、执行前后核对；缺授权、计划变动或源 hash 变化时阻塞。底层 execute 不连接/退出 Origin、不渲染和保存；正式 B 命令负责会话、处理工程保存重开及标准表桥接。返回结果本身不表示完整交付验收通过。

## 明确公式与参考身份

|method|逐谱公式|条件与单位|
|---|---|---|
|max|Y/max(Y)|最大值有限且>0；结果无量纲，明确选择 max 时采用|
|range|(Y−min(Y))/(max(Y)−min(Y))|非恒定谱；结果0–1|
|range100|100×(Y−min(Y))/(max(Y)−min(Y))|非恒定谱；结果0–100，单位%|

range/range100 只在任务明确要求时使用，不能覆盖既有 max 偏好；其代码分支不等于实机均验证。每条谱独立调用 Origin `normalize iy:=... method:=... oy:=...`，原谱与结果写不同原生 XY 列，X、点序和点数不变。公式来源：[Origin Normalize API](https://docs.originlab.com/x-function/ref/normalize/)。

每次需要 PDF 衍射参考时确认当前编号、物相及来源：pdf_reference 需 requested=true、confirmed=true、reference_id、source；未请求时明确 requested=false。本 API 不读取卡片、不定相、不凭编号造峰，也不自动添加参考线。后续 A 只画已给参考点。

## 保存与验收

完整记录 raw/result 列、逐点值、单位、分组、公式方法、参数、实际命令和来源 hash。结果必须点数一致、全部有限、X 未变；重新读原始列确认原值未改。正式流程保存 processing.opju，关闭后新独立会话重开并逐列比较，再导出既有 A 标准表。失败保留现场，不删除异常点制造通过。

处理与图像验收分开：processing_accepted 不代表 A 五项验收或历史方法已核实。合成 max 案例已有实际 Origin 保存重开及原生图验证；range/range100 的实机状态见 [能力状态](capability-status.md)，不能由接口测试替代。
