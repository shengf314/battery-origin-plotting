# 运行环境与 Origin 会话

从 skill 根目录按 [README](../README.md) 安装 Python 与 Node 依赖。渲染需要 Windows 和另行授权的 Origin；开发机历史实测为 Python 3.7.1、Origin 2024，不据此保证其他组合的全部 COM 行为。现代 Python 离线兼容性由公开 CI 检查。Excel 正式读取采用标准库 zip/XML，无需 Excel 或 openpyxl。

## SEM / Illustrator 环境

SEM 单图分支需要 Windows 和已安装、授权且支持 COM/ExtendScript 的 Illustrator，以及可用的 ArialMT 字体。SEM 不需要 Origin。图头/几何与 Adobe 父流程保持 Python 3.7 兼容；完整像素桥接另需安装 Pillow 和 pypdf 的现代 Python，可在 Python 3.11 环境安装 requirements-sem.txt，再用 SEM_IMAGE_PYTHON 指向该解释器。当前解释器满足依赖时也可直接使用。不会自动下载依赖或改变 Adobe 安全设置。

后台执行不激活窗口或模拟点击，但桌面 Adobe 仍会在内存中创建和载入本次文档；不能保证所有版本真正 headless。单图像素范围与限制见 [SEM 契约](sem-illustrator.md)。

## 测试阶段的仪器读取环境

受选 NDA/NDAX 布局使用标准库，不运行 NewareNDA 的排序/去重等便利 API。LAND CEX 另需已经安装的匹配 64 位 LANDCex_x64.dll（当前代码仅接受已核查 ABI 0x30306）；用 LAND_CEX_DLL 或来源项 reader_options.dll_path 指定。NEWARE 可选质量提取需匹配的 BTSDAExReport.exe 及依赖；用 NEWARE_EXPORTER_EXE 或 reader_options.exporter_path 指定。组件缺失或版本/单位不明时报告缺口，不猜质量。

厂商组件不随包分发，也不自动安装或注册。读取在一致快照和隔离 worker 中执行；解析/元数据导出仍处于测试阶段。细节见 [工程输入](instrument-projects.md)。

## Node 与图片工具

在 skill 根目录执行 npm install，安装 package-lock.json 记录的 Sharp 与 Playwright。Node 通过 PATH 或 CODEX_NODE / NODE_EXE 查找；包优先通过 CODEX_NODE_MODULES，随后 skill 根目录的 node_modules，再查已有 Codex runtime。无需拥有作者的私人运行环境。

SVG 预览通过 Playwright 的 msedge 通道启动 Microsoft Edge；系统须另行安装 Edge。PNG 检查使用 Sharp。不能加载时报告真实缺口，不跳过图片验收来声称 accepted。环境变量覆盖路径必须指向实际存在的可执行文件或包目录。

## 诊断

```powershell
python -X utf8 -m plotting_core.doctor
python -X utf8 -m plotting_core.doctor --static
```

使用虚拟环境时将 python 替换为相应解释器。doctor 检查 YAML/pywin32 发现、Origin COM 注册和注册 exe、视觉模板、Node、Sharp、Playwright 包路径。默认执行限时 Node/Sharp 加载；--static 不启动子进程。诊断不启动 Origin、不打开工程，也不运行完整浏览器预览；COM 注册或包存在不能替代实机能力验证。

## 原生会话与路径

后端用 DispatchEx("Origin.Application") 建立独立会话，不回落到 ApplicationSI、不连接用户活动工程；只退出本次持有的 app。输入只读；历史工程核查在任务副本中进行，不重放历史公式或保存回源。

从 skill 根目录运行模块，输入/spec/output_root 使用绝对路径。任务、审计和输出放在技能目录外；可设置 PYTHONDONTWRITEBYTECODE=1 避免字节码缓存。桌面沙箱的 COM 与外部目录权限以当前环境为准。

深路径 PNG/SVG 原生导出可能失败，后端用本次拥有的短 Temp 目录导出，再按原字节复制并比较 SHA256；不编辑图片。240 UTF-16 字符是保守路由阈值、259 是最终工程保存 guard，不是所有 Origin 版本的官方极限。最终 OPJU 路径过长应缩短任务路径。

Y/Y2、源列绑定、轴方向/尺度、原生图例与导出仍须通过实际渲染、保存重开、逐点回读与图像检查验证。已有模板缺失时不得用覆盖层替代原生对象。
