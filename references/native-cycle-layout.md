# 循环双轴图：CE 上置、下方图例与原生归属箭头

2026-10-08 用户确认：全部 CE 显示在全部放电比容量上方，两种数据之间留白；底部留图例；通过显示范围降低曲线的视觉倾斜；每种指标只用一个箭头指向所属 Y 轴。适用于已有圈级容量/CE 的 `cycle_performance`，不从 GCD 重新算容量/CE。

## 启用与数据边界

任务选择 CE 上置布局时，agent 明确填入下述 override；旧 spec 不填则保留旧行为，不静默迁移。

```json
{
  "legend": {"mode": "entries", "layout": "paired_samples", "position": "bottom_left"},
  "overrides": {"plot_type": {"native_layout": {"enabled": true, "mode": "separated_bands"}}}
}
```

只调整显示范围与原生对象位置。全部源点、圈次、点序、样品身份、百分数/小数单位及左右轴绑定保持。包括 CE>100 的已有值也纳入极值；不为图形水平而平滑、截点或改值。percent 与 fraction 使用实际存储数值分别算范围，不做乘/除 100。

## 范围与留白

`domains/electrochemistry/cycle_performance/native_layout.py` 从所有容量/CE 原始点计算整体极值。自动目标为容量处于图层高度约 0.42–0.66，CE 处于约 0.76–0.85；边界取整后重新验证，必要时仅细化自动范围的取整。精确位置依数据、显式范围与符号直径而定，不能把某次的 20–160/20–120 当成通用科学范围。

用户给定 `left_y_axis_range`、`right_y_axis_range` 或 `x_axis_range` 时优先保留。范围必须包含所有值，CE 最低符号边缘必须高于容量最高符号边缘，净间距默认至少为两侧符号半径之和。可明确给 `native_layout.min_gap_mm`；不足时阻塞，不弱化约束。常量指标需明确非退化范围；目前仅支持递增线性 X/Y/Y2。

X 自动补充容纳端部符号的显示留白，不新增圈次或测量点。实际图层宽度需要扣除通用 Origin 后端为 Y2 标题保留的 margin。保存重开后由图族 QA 对实际轴、层高和原生图例边界重新核对；图例顶部须位于容量最低符号边缘下方。需要人工看导出图确认文字、符号和箭头无碰撞。

## 原生箭头与图例

计划只声明两个 `axis_indicator`：`discharge_capacity → left`、`coulombic_efficiency → right`，与样品数无关。箭头不作为 data series，也不代替真正 Y2 绑定。`backend/native_arrows.py` 通过 named `Draw -lm` 创建两个可编辑 Line 对象，以图层比例转为左轴尺度坐标，声明的 target_axis 代表归属含义。

LabTalk `arrowBeginShape=1` 为无头、`arrowEndShape=2` 为实心头。本机 Origin 2024 已实际核验，不能套用 Origin C 内部 AHS 枚举。Execute 成功也不足以证明生效，必须回读对象类型、附着、单端头、尺寸与端点，再看实际图像。新箭头线宽沿用本次曲线线宽，头长/头宽分别取箭头总长的 1/3、1/4，在计划中显式记录；不改已有曲线样式。

参考：[Origin Draw 命令](https://docs.originlab.com/labtalk/ref/draw-cmd/)、[Origin 对象教程](https://docs.originlab.com/labtalk/tutorials/tutorial-objs/)。官方 graphic-object 属性页与主枚举的起始值存在差异，运行以实际回读和主枚举为准，不能因页面上的 0/1 描述默许无箭头的线通过。

图例每个样品一行，容量实心/CE空心两个原生链接。未核实样品名时用中性列名，不根据颜色或参考图猜 Sample_A/样品身份。保持率和电压/C-rate 条件只在有真实定义/来源时添加，不能照抄参考图数字。已有轴标题只修改和移动其原生对象；不加矢量/图片覆盖，也不修改导出 PNG/SVG。

## 验收与调用

输入 → 计划 → Origin → 保存重开：逐点核对完整原值、单位、圈次、样品/指标/Y侧、真实符号尺寸、实际轴范围、上下数据包络净间距、图例边界及两个箭头端点。可编辑性探针在工程副本分别移动两个箭头的尾端，保存重开确认；最终工程 hash 必须不变。自动检查与人工图像检查均完成后再记录完整验收；用户审美审核另列状态。

中文调用：“用这份圈级表绘制循环容量和 CE。按已确认布局把全部 CE 放在容量上方、底部留配对图例，加两个原生箭头指向左右 Y 轴。保留全部数值和当前点线尺寸。”

2026-11-03最新视觉规则为全部文字常规体、容量/CE连线0.5pt、可见刻度朝外，覆盖此前加粗与1.1pt连线；圆点5.8pt、填充区别、全点、字号、画布、颜色和上述双轴布局保持。箭头仍沿用当前曲线线宽。不能用轴压缩暗示数据稳定性没有变化，曲线真实趋势仍按原值呈现。
