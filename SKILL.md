---
name: battery-origin-plotting
description: Create editable native Origin figures from standardized Excel and explicit simple formulas, including Na capacity conversion, XRD normalization and ICP molar ratios. Excludes XPS, dQ/dV and workflows requiring differentiation, smoothing, fitting or model inversion.
---

# Battery Origin Plotting

将中文需求整理成标准 Excel、明确科学语义及 PlotSpec，生成 Origin 原生可编辑图。范围为**直接绘制表中数值，或用已明确的简单公式计算后绘制**。XPS 和 dQ/dV 整个图族不属于本技能，已有分峰或导数结果也不路由进来；不将求导、平滑、分峰、拟合、模型反演列为待补参数或后续优化目标。

先区分 **A：已有数值绘图** 与 **B：简单公式处理**。区分 [公开版默认与当前声明](references/workflow-preferences.md)，当前科学信息不全时先完成读表与预检，再集中询问影响结果的缺口；复用当前用户已有的明确确认；作者历史偏好不构成新用户的科学声明。实际验证边界见 [能力状态](references/capability-status.md)。

## A：已有数值的原生绘图

|plot_type|data.kind|按需读取|
|---|---|---|
|gcd：容量或已提供 Na/Δx–电压|excel_long|[原有输入](references/input-schema.md)、[GCD](references/families/gcd.md)|
|cycle_performance：容量与 CE|excel_cycle_summary|原有输入、[循环/倍率](references/families/cycle-rate.md)、[CE 上置布局](references/native-cycle-layout.md)|
|rate_capability：倍率容量|excel_cycle_summary|原有输入、[阶段与输入模板](references/rate-capability.md)|
|eis：明确的阻抗 XY 表|excel_processed_series|[系列输入](references/processed-input.md)、[EIS](references/families/eis.md)|
|gitt：已给 D/log10 D 结果表|excel_processed_series|系列输入、[GITT](references/families/gitt.md)|
|xrd：已给谱和参考点|excel_processed_series|系列输入、[XRD](references/families/xrd.md)|
|icp：已给比例/组成|excel_processed_series|系列输入、[ICP](references/families/icp.md)|

registry 仅以上七族。A 保留原值和顺序；EIS 只画明确的实测阻抗及参考数据；不接拟合/背景/组分曲线。GITT 只画已给 D 或 log10 D，不从电压响应求 D，不识别脉冲或补选模型。A 不因图族名称自动计算；B 结果需桥接成以上既有输入方言。

## B：明确的简单公式

|operation|处理内容|按需读取|
|---|---|---|
|gcd_na|已知数字化学式逐元素求 M；同一 GCD 比容量按 Faraday 电量关系与明确参照算 Δx/绝对 x|[Na 换算](references/na-conversion.md)|
|xrd_normalization|已扣背景、未纵移谱逐条用明确公式归一化；明确选择 method=max 时为 Y/max(Y)|[XRD 处理](references/origin-processing.md)|
|icp_molar_ratios|明确单位、元素、共同溶液基准下换算物质的量，再除以明确分母|[ICP 计算](references/icp-calculation.md)|

通过 [独立 B 命令](references/processing-cli.md) preflight → 记录已有科学确认与请求 hash → execute；需要图时加 --render。Na 新输入必须明确参照，绝对 x 不能从名义化学式自动选 x_ref；同组放电接精确充电末点也必须满足起点身份声明。ICP 不猜单位/分母，不将 ND 置零。简单公式也保留方法、参数、来源、原始列与结果列；不改源表。系列角色仅 measurement/processed/derived/reference，不将拟合、背景模型、峰组分改名为普通数据绕过范围。

## 约束与执行

- 明确变量/单位、X/Y/Y2、方向/尺度、样品/循环/分支/区间/角色和图例对象。保留每点及原顺序，不擅自删异常值、补值、去重、降采样、插值、反号或重算公式；重复、无缓存公式、缺值及连接歧义须报告。
- 倍率按连续 Rate 阶段识别，不将恢复倍率合并到早期阶段；标签 X 居中、阶段数量来自输入。CE 旧输入默认百分数，fraction 声明不自动乘100；已有 log10 D 使用线性 Y，禁止重复取对数。
- 公开版默认视觉预设（可按当前任务配置）：所有数据曲线0.5pt，坐标轴标题、刻度数字、图例、阶段标签及其他文字全部常规体，可见主次刻度向外。沿用 [视觉模板](templates/publication_visual_template.yaml) 的柔和莫兰迪配色、字号、字体家族、5.8pt全点符号和普通画布；轴框/刻度宽保持1.0pt，主长3pt、次长一半，线性轴每主间隔一个次刻度。图例按科学对象及原生边界避让，详见 [点线](references/native-point-line.md)、[刻度/图例](references/native-ticks-legend.md)。任务采用默认循环布局时，显式启用CE上置、下方配对图例和两种指标各一个原生箭头；不改变科学分组或旧输入格式。
- 曲线、轴、图例、标注均为 Origin 原生可编辑对象；不叠图片或矢量覆盖，不修改导出物掩盖 Origin 问题。原生无法可靠修复的导出现象须如实记录，不修改图片掩盖问题。
- 输入与历史源目录只读；用任务副本与 DispatchEx 独立 Origin 会话，不连接用户工程、不执行历史公式、不保存回源。输入/spec/output_root 使用绝对路径，审计和运行成果放外部任务目录。

从技能根目录调用：

```powershell
python -X utf8 -m plotting_core.cli check --spec <绝对路径_plot_spec.json>
python -X utf8 -m plotting_core.cli render --spec <绝对路径_plot_spec.json> --qa-level 3
```

首次运行或接口失败时用 `python -X utf8 -m plotting_core.doctor`，见 [环境诊断](references/environment.md)。check 只检查输入和计划；按 [渲染流程](references/rendering-pipeline.md) 实际写入、导出、保存重开并回读绑定/逐点值/单位/角色/轴/图例。按 [完整验收](references/acceptance.md) 在工程副本执行 editability_probe 并实际查看图像；accepted 必须 input/data/native_structure/editability/image 五项通过。交付 OPJU、SVG、PNG、plot_spec.json、README.md、export_check.json。失败与 dry-run 不继承旧 accepted；合成测试不证明真实实验身份或方法。需要严格交付退出码时加 --require-accepted。

公开版安装、依赖与无需 Origin 的合成预检见 [README](README.md)。科学参数必须由当前数据和用户声明确定，模板预设不能替代确认。

维护者同步本地更新或发布新版本时，读取 [维护发布指南](references/maintenance.md)，使用增量同步与标签发布入口。
