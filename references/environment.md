# 运行环境与 Origin 会话

从 skill 根目录按 [README](../README.md) 安装 Python 与 Node 依赖。渲染需要 Windows 和另行授权的 Origin；开发机历史实测为 Python 3.7.1、Origin 2024，不据此保证其他组合的全部 COM 行为。现代 Python 离线兼容性由公开 CI 检查。Excel 正式读取采用标准库 zip/XML，无需 Excel 或 openpyxl。

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
