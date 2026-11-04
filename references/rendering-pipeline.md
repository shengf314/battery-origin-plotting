# Origin 原生渲染流程

## 架构与边界

`models.PlotSpec` → `registry` → `domains/<领域>/<图族>/{ingest,plan}.py` → `RenderingPlan` → `backend.origin` → `export.writer` → `qa`。

若用户给受支持的蓝电／新威测量工程，先走 `instrument_cli` → `instruments.service` 的一致快照／隔离 reader → `instruments.standardize` → 既有标准 XLSX/PlotSpec；详细请求与科学阻塞见 [工程输入](instrument-projects.md)。标准化复用原有 reader/prepare，逐点验证后发布，再从上段 `models.PlotSpec` 进入原流程。通用后端不解析仪器格式，不增加 `data.kind`。仅 `prepare --render` 会在预处理通过后启动 Origin；`inspect` 和未加 render 的 prepare 不代表原生图已验证。

registry 声明可读的数据方言；未注册图族或跨方言输入先拒绝。旧转发层保留兼容性。EIS、GITT、XRD、ICP 四种系列路由由独立领域模块接入，共用严格的 `domains/processed_xy` 契约。科学分组、方向、尺度、角色与来源由计划声明，通用后端不判断具体图族或执行科学处理。

`style/`读取当前视觉模板。只在用户明确授权的范围使用参考工程的已读参数，不从截图推断线宽或把混合设置推广成统一样式；2026-11-03取舍见 [视觉配置](visual-application.md)。所有可见内容都是Origin原生曲线、轴、legend或文字。旧export目录中的overlay工具不参与正式native pipeline，不得作为失败兜底。

## 固定执行顺序

1. 解析 spec并识别任务目录。不可解析为PlotSpec的JSON不虚构输出路径；可识别任务后进入下步。
2. `render`先记录本次attempt/run_id并归档旧状态，使旧图像验收失效；随后加载有效配置、只读输入，核对源文件SHA256读前读后不变。图族ingest校验字段、单位、缺失/重复、分组、请求选择与科学处理记录，保留源行号。CLI仍输出报告，输入/计划失败也留下本次失败状态。
3. 图族plan构造系列、图层、X/Y/Y2、方向/尺度、原生legend与标注。`check`只将计划打印到stdout，到此结束，不创建render尝试或宣称实机验证；`render`在prepare成功后写`.tmp/<run_id>/plan.json`。
4. `DispatchEx("Origin.Application")` 启动独立会话，检测单层独立 Y/Y2 能力。写每系列独立 XY 列；新系列将物理量、单位与来源 JSON 写入列元数据。分类标签独立写为原生文本数据列。
5. 按计划创建 native line/scatter/line+symbol、绑定 Y/Y2；在 rescale 前设置声明的科学尺度，再设置方向与刻度。保留输入点顺序，不插值或求导。
6. 应用当前视觉配置：数据连线0.5pt，标题/数字/图例/标注常规体，可见刻度向外；创建native legend/注释并回读原生结构。正式绘图任务导出SVG、600dpi PNG，保存OPJU。
7. 默认重开保存工程并逐系列回读：实际XY数据集必须匹配计划；GetSize、完整点对、Y轴附着、plot type、列物理量/单位、尺度/方向及分类标签类型均须通过。显式显示范围独立比较计划端点，自动范围比较本次完成配置后捕获的显示契约；原生轴标题全文与计划科学文字/单位比较，仅接受已明确声明的Origin格式序列化。失败加入验收issues。
8. 执行 L1/L2/L3 QA 和导出验收，写 README、plot_spec、export_check。最后退出仅由本次创建的会话，不通过全局进程差集 kill Origin。

## 验证、失败与交付

L1 检查系列/结构；L2 比较统计、点数和实际绑定轴范围；L3 比较全部 XY 值。新图族科学角色保存在 metadata 中，普通数据系列仍参与全部 QA，不因 reference/derived 角色绕过点数校验。

`verification.reopen_project` 默认 true；验证任务保持启用。用 false 跳过重开时不得宣称保存工程已经验证。单位与方向校验不是美观检查；图像还需检查是否有误连、错轴、图例对象不明确和标签遗漏。

`verification.editability_probe: true` 在任务工程副本实际编辑原生对象、保存重开并恢复最终工程，详见 [五项验收](acceptance.md)。`accepted` 还要求实际图像审阅，`ok` 继续表示机械运行兼容性。图像审阅绑定成果 hash；重试立即使旧成功失效，失败保留证据。科学来源完整性记录不证明已提供数据的科学正确性。

核心交付清单由`workspace.CORE_DELIVERABLES`定义：OPJU、SVG、PNG、plot_spec.json、README.md、export_check.json。可识别任务的输入或计划失败写本次attempt失败状态，不再沿用旧accepted；旧科研产物及报告保留作历史证据。后端连接、渲染、保存或重开异常保留已有计划和failure.json（阶段、错误、后端命令与恢复说明）；QA问题写入export_check.json。源文件不动。重试修复领域/后端通用模块，不新造任务补丁，不降低验收标准。

## 参数和调用

PlotSpec 的具体字段见 [原有输入](input-schema.md) 或 [已处理系列输入](processed-input.md)。从 skill 根目录执行：

```powershell
python -X utf8 -m plotting_core.cli check --spec <绝对路径.json>
python -X utf8 -m plotting_core.cli render --spec <绝对路径.json> --qa-level 3
```

`data.file` 和 `output_root` 均使用绝对路径；模板继续使用既有 `templates/publication_visual_template.yaml`，任务不补充新视觉默认值。

需要退出码同时代表完整交付时可加`--require-accepted`；默认退出码保持旧机械执行兼容性。`review`实际看图后更新验收和README审阅状态，技术完整验收与用户审美/材料身份确认仍分别记录。

原生图例采用独立命名的ScientificLegend文本对象和\l(N)图元引用，防止Origin专用Legend对象在导出时再生未计划的自动条目；字体字号与45/8的既有百分比位置数值保持。重开核对图例全文；来源：[Origin自定义图例维护](https://docs.originlab.com/origin-help/legend-manualcontrol/)、[Label命令](https://docs.originlab.com/labtalk/ref/label-cmd/)。分类图同时核对原生文本列全部标签及实际绑定；数据集别名Book_Col只在对应同一book/sheet/column时视为一致。
