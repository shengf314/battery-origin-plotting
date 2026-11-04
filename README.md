# Battery Origin Plotting

当前稳定支持 **GCD、容量/库仑效率（CE）双 Y 图、SEM 单图裁剪与标尺/Illustrator AI 交付**。标准表曲线使用 Origin 原生可编辑对象；SEM 使用独立 Illustrator 流程。保留数据来源与验收记录，可作为 Codex skill 或 Python 命令行使用。

Stable scope: GCD, capacity/CE dual-Y Origin plots, and calibrated single-panel SEM crops with editable Illustrator AI. Other plot families, formula processing and LAND/NEWARE imports are experimental. Windows and the corresponding licensed desktop application are required for rendering.

[下载最新稳定版](https://github.com/shengf314/battery-origin-plotting/releases/latest) · [完整技能说明](SKILL.md) · [输入规范](references/input-schema.md) · [支持边界](references/capability-status.md) · [MIT License](LICENSE)

## 支持状态（2026-11-04）

| 状态 | 功能 | 当前范围 |
| --- | --- | --- |
| **稳定** | **GCD** | 标准表中的比容量–电压、已有 Na/Δx 坐标、明确样品/圈次/分支 |
| **稳定** | **容量/CE 双 Y** | 已有放电比容量与 CE；原生左右 Y，可启用 CE 上置、配对图例及两个轴归属箭头 |
| **稳定** | **SEM 单图** | 原标尺逐图标定、等比裁剪、独立矢量标尺/活文字、真实可编辑 Illustrator AI |
| 测试阶段 | 倍率、EIS、GITT、XRD、ICP | 保留已有入口供试用与回归，不作为稳定支持宣传 |
| 测试阶段 | Na 换算、XRD 归一化、ICP 摩尔比例 | 参数、方法与科学参照须明确；GCD 的稳定标签不覆盖这些计算 |
| 测试阶段 | LAND/NEWARE 原始工程 | 仅受选 CEX/NDA/NDAX 布局；读取/标准化成功不等于完整原生成图验收 |

稳定范围以维护者当前确认的上述三项为准。代码存在、离线测试通过或历史个别样例通过，都不自动升级为稳定支持；每次科研交付仍须完成对应验收。

简单公式处理仅包括 Na 容量等效换算、已扣背景 XRD 归一化、ICP 摩尔比例。XPS、dQ/dV、求导、平滑、拟合、分峰、背景拟合和模型反演不在本技能范围。

曲线任务交付 `.opju`、`.svg`、`.png`、`plot_spec.json`、`README.md`、`export_check.json`，对象均为 Origin 原生可编辑结构。SEM 交付真实自包含、PDF 兼容 `.ai` 及标定/几何/像素与原生回读记录。源数据只读；SEM 以原生蒙版保留完整源像素，不增强或修补形貌。

## 环境

- **绘图**：Windows、已安装并授权的 Origin，且 `Origin.Application` COM 可用。开发机历史实测为 Origin 2024；其他版本须在自己的机器上验证。
- **Python**：源码保持 3.7 兼容；开发机历史实测为 Python 3.7.1。公开版对现代 Python 提供依赖声明和离线 CI，离线通过不等同于完整 Origin 兼容性。
- **Python 依赖**：PyYAML、Windows 上的 pywin32。Excel 读取使用标准库，无需安装 Excel 或 openpyxl。
- **SEM**：Windows + 已安装、授权的 Illustrator，ArialMT 字体，以及含 Pillow/pypdf 的现代 Python 像素 worker；不需要 Origin。使用 `requirements-sem.txt` 安装可选依赖，必要时设置 `SEM_IMAGE_PYTHON`。
- **预览与图片检查**：Node.js 20+、Sharp、Playwright、Microsoft Edge。预览使用 Playwright 的 `msedge` 通道；`npm install` 不会替你安装 Edge。

Origin 软件、授权、私人参考工程、个人实验数据及历史审计文件不随仓库分发。附带的 Excel 为合成演示数据。

## 下载与安装

### 作为 Codex skill

可在 Codex 中请求：

```text
$skill-installer 安装 https://github.com/shengf314/battery-origin-plotting 中的 skill，技能名 battery-origin-plotting。
```

也可下载 Release ZIP，解压后将含 `SKILL.md` 的文件夹命名为 `battery-origin-plotting`，放到用户 skill 目录。按当前 [OpenAI 官方技能文档](https://learn.chatgpt.com/docs/build-skills)，用户目录为 `~/.agents/skills/`，项目目录为 `.agents/skills/`。如果自己的客户端已有其他技能目录配置，使用该配置；只需安装一份。

PowerShell 手动安装示例（需要 Git；目标目录须不存在）：

```powershell
$skillDir = Join-Path $env:USERPROFILE '.agents\skills\battery-origin-plotting'
New-Item -ItemType Directory -Force -Path (Split-Path $skillDir -Parent) | Out-Null
git clone https://github.com/shengf314/battery-origin-plotting.git $skillDir
Set-Location -LiteralPath $skillDir
```

技能文件安装后，还须在该目录安装下面的运行依赖。如果客户端没有出现新技能，重启客户端。日常调用示例：

```text
使用 $battery-origin-plotting，先检查这份 Excel 的字段、单位和科学语义，再画原生可编辑的 GCD 或容量/CE 双 Y 图；SEM 则核实原标尺后生成可编辑 AI。输出到我指定的任务目录。
```

### 安装运行依赖

从仓库或已安装 skill 的根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
.\.venv\Scripts\python.exe -X utf8 -m plotting_core.doctor
```

直接使用脚本时继续调用上述虚拟环境中的 Python；让 agent 执行时也告知它该解释器路径。`doctor` 检查模块、Origin COM 注册、Node/Sharp/Playwright 的发现情况；它不启动 Origin，不能证明完整绘图能力。环境有缺口时先按 [环境说明](references/environment.md) 修复。

SEM 的像素 worker 请使用现代 Python（例如 3.11）。在该环境执行 `python -m pip install -r requirements-sem.txt`，再将 `SEM_IMAGE_PYTHON` 指向它的 python.exe；图头/几何和 Adobe 父流程可继续使用原来的解释器。Illustrator 与指定字体须另行安装，见 [SEM 契约](references/sem-illustrator.md)。

## 五分钟跑通稳定 GCD 的合成示例

从 skill 根目录执行。任务目录放在技能目录外；下面使用用户临时目录中的新文件夹，源文件不会被覆盖。

```powershell
$demoDir = Join-Path $env:TEMP ('battery-origin-demo-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_example.py --output-dir $demoDir
$specPath = Join-Path $demoDir 'plot_spec.json'
.\.venv\Scripts\python.exe -X utf8 -m plotting_core.cli check --spec $specPath
```

`check` 只读校验、构建绘图计划；无需启动 Origin。默认示例为一个合成样品的充/放电 GCD，共 6 点，不代表真实材料或实验。

准备脚本还可用 `--plot-type cycle_performance` 生成容量/CE 双 Y 示例。原倍率合成示例保留，需显式传 `--plot-type rate_capability`，其状态为测试阶段。

Windows 与 Origin 环境就绪后，实际绘图：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m plotting_core.cli render --spec $specPath --qa-level 3
```

成果位于 `$demoDir\outputs\gcd_input_synthetic_example\`。实际打开 PNG/SVG 检查文字、图例、曲线与标注，再按 [完整验收](references/acceptance.md) 记录图像审阅。输入、逐点数据、原生结构、可编辑性和图像五项全部通过，才可称为 `accepted=true`；自动运行结束不自动等于完整验收。

## 使用自己的数据

在副本中填入真实数据，按图族提供单位、样品、分支/圈次、来源和必要科学参照。spec 中的输入文件、spec 本身与输出根目录使用绝对路径。工作表选择、表头映射和单位规则见对应契约，不能把任意仪器导出表直接当作标准表。

- GCD / 循环 / 倍率：[输入契约](references/input-schema.md)，[倍率模板](references/rate-capability.md)。
- 稳定 SEM 单图：[SEM 契约](references/sem-illustrator.md)、[视觉预设](templates/sem_visual_profile.json)。用 `python -m plotting_core.sem_cli check/render --spec <绝对路径>`；标定和 ROI 均须按本图重新核实。
- EIS / GITT / XRD / ICP：[已有 XY 结果输入](references/processed-input.md)，再读对应 [图族规则](references/families/)。
- 明确的简单公式：[处理命令](references/processing-cli.md)、[Na 换算](references/na-conversion.md)、[XRD 处理](references/origin-processing.md)、[ICP 计算](references/icp-calculation.md)。

公开版提供的是可配置的视觉预设：0.5 pt 数据线、常规字重、朝外刻度、柔和配色、循环/倍率 5.8 pt 全点符号。它们不是读者已确认的个人偏好。任务参数可通过模板或 spec overrides 明确配置；质量基准、化学式、Na 参照、XRD 背景状态和 ICP 分母须由当前数据与用户声明确定。

## 验证与已知限制

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

公开仓库 CI 只验证离线输入、几何、像素桥接和维护流程，不在 GitHub 托管 runner 上运行 Origin 或 Illustrator，也不改变上述稳定/测试划分。软件版本、COM、字体和显示设置仍需本机保存重开及图像验证，见 [能力状态](references/capability-status.md)。

不支持 XRD sticks/独立参考层、ICP 误差棒桥接、GITT 参数反演或 EIS 拟合。对源表中的缺值、重复、无缓存公式或身份歧义会报告并暂停相关计算，不自动补值或更改数据。

## 本地更新与新版本发布

维护入口为 `scripts/publish_public.ps1`，提供 Check、Sync、Release、Status 四个操作。增量同步会保留公开版调整，在临时副本中检查后提交；推送新版本标签会由 GitHub 完成三版本测试、ZIP 打包、校验文件和 Release 发布。完整步骤、初始化与失败恢复见 [维护发布指南](references/maintenance.md)。

## 目录与许可

`SKILL.md` 是 agent 入口；`plotting_core/` 是执行引擎；`references/` 放契约和操作规则；`templates/` 放视觉预设；`scripts/` 放示例准备与预览工具；`examples/` 放合成工作簿和 spec 模板。

原创代码和文档使用 [MIT License](LICENSE)。NEWARE 字节布局/缩放的适配部分保留上游 BSD-3-Clause 许可，见 [第三方说明](THIRD_PARTY_NOTICES.md)。Origin、Illustrator、厂商组件和依赖遵循各自许可；厂商二进制不随包分发。原子量表注明 [CIAAW 来源](https://www.ciaaw.org/abridged-atomic-weights.htm)。
