# 原生绘图验收

`check` 只执行输入校验和计划，未启动 Origin。`dry_run`、单元测试或截图不能代替保存重开后的工程检查。

完整验收包含 input、data、native_structure、editability、image 五项，每项记录 status、method、evidence、reasons。status 为 pass/fail/not_run/blocked。`automatic_checks_passed` 与 `accepted` 分开；兼容字段 `ok` 不等同完整验收。

## 实际运行

在 PlotSpec 中使用 `verification: {"level": 3, "reopen_project": true, "editability_probe": true}`。

数据检查回读每个点及顺序；结构检查回读真实 XY 列范围、点数、Y/Y2、原生 plot type、单位、科学来源记录、轴方向/尺度及图例。标题预期独立来自绘图计划中的变量和单位，只接受当前配置明确要求的Origin原生格式；当前常规体不接受继承的旧加粗包装。标题、刻度数字、图例及全部原生标注均需核对bold=false；数据连线核对实际0.5pt，可见主次刻度核对向外mask及半长度。显式轴范围按请求核对；自动轴范围按渲染时在保存前捕获的 native_axis_contract 核对，不能用数据极值冒充预期显示范围，缺少独立契约时检查失败。倍率额外回读阶段标签 text、attach 和中心坐标。图形对象位置经像素保存，采用不足一个屏幕像素的坐标容差，不能把此容差用于数值数据检查。

编辑性探针仅编辑 `<任务>/verification/editability_probe.opju`：每个 Y 侧的曲线颜色、X 轴标题、原生图例以及存在时的科学标注。保存后重新打开，确认改动持久化且全部数据/绑定仍一致，再恢复最终工程；最终 OPJU 的 SHA256 必须保持不变。这证明原生接口操作，不宣称做过手工 GUI 编辑。

完成实际 PNG/SVG 检查后，从技能目录运行：

```powershell
python -X utf8 -m plotting_core.cli review --task-dir <任务绝对路径> --status pass --reviewer <审阅者> --note <观察记录> --evidence <实际PNG绝对路径> --require-accepted
```

有裁切、误连、文字遮挡或系列不可辨时记录 fail 与具体位置；不能只因自动检查通过而记录 pass。

## 来源与重试

`scientific_traceability.status=declared` 只表示声明已供应；`scientific_truth_verified` 始终为 false。已提供处理结果可带明确 unknown 方法记录；关键单位、符号、Na 定义、科学角色或连接边界未知仍按输入契约阻塞。

图像审阅和渲染证据分别绑定实际 OPJU/SVG/PNG 的 SHA256。任何成果改动都需要重新渲染/验收；新图像审阅不能恢复旧原生自动证据。render 在输入预检前归档旧报告/审阅并建立新 run_id 与 running 状态；输入、渲染或导出失败均记录 failed/accepted=false。dry-run 同样不能继续显示旧 accepted，check 保持只读。失败证据在本次 .tmp/<run_id>/ 与 failure.json，成功仅清理本次临时目录。README 与 export_check 自动同步，科学系列/点数与额外原生 marker 对象分开统计。

render/review 的 --require-accepted 为自动调用方提供严格退出码：五项未全通过返回3；输入/计划错误返回2，运行错误返回1。默认命令保留旧退出行为供兼容，不能据默认 exit=0 推断 accepted。

Origin 接口依据（2026-10-08 核查）：[原生文本对象属性](https://docs.originlab.com/labtalk/ref/graphic-objs/)、[居中标签](https://docs.originlab.com/labtalk/ref/label-cmd/)、[曲线属性写入](https://docs.originlab.com/labtalk/ref/options_for_dataplots/)、[曲线属性回读](https://docs.originlab.com/labtalk/ref/get-cmd/)。科学点值无容差比较沿用统一后端，不从导出图反推数值。
