# Battery Origin Plotting

把标准 Excel 数据绘制为 **Origin 原生、可编辑的电池科研图**，并保留数据来源、逐点回读和验收记录。既可作为 Codex skill 使用，也可直接调用 Python 命令行。

A reusable agent skill and Python pipeline for editable, native Origin figures from battery Excel data. Windows + a separately installed, licensed Origin application are required for rendering. Offline input validation does not start Origin.

[下载 v1.0.1](https://github.com/shengf314/battery-origin-plotting/releases/tag/v1.0.1) · [完整技能说明](SKILL.md) · [输入规范](references/input-schema.md) · [支持边界](references/capability-status.md) · [MIT License](LICENSE)

## 支持什么

| 图族 | 输入与功能 |
| --- | --- |
| GCD | 比容量–电压、已有 Na/Δx–电压、指定圈次与样品 |
| 循环性能 | 已有放电比容量与 CE；原生双 Y 轴，可启用 CE 上置布局 |
| 倍率性能 | 圈级容量与明确 C-rate；自动识别连续阶段，恢复倍率单独标注 |
| EIS | 已有阻抗 XY；明确 Im/−Im 符号，保留原顺序 |
| GITT | 已给 D 或 log10 D 结果；不从电压响应反演 D |
| XRD | 已有谱与参考点；明确公式的逐谱归一化 |
| ICP | 已有组成/比例；明确单位、溶液基准和分母的摩尔比例计算 |

简单公式处理仅包括 Na 容量等效换算、已扣背景 XRD 归一化、ICP 摩尔比例。XPS、dQ/dV、求导、平滑、拟合、分峰、背景拟合和模型反演不在本技能范围。

每次完整任务交付 `.opju`、`.svg`、`.png`、`plot_spec.json`、`README.md`、`export_check.json`。曲线、轴、图例和标注均为 Origin 原生对象。所有输入只读，原始点序和数值保留。

## 环境

- **绘图**：Windows、已安装并授权的 Origin，且 `Origin.Application` COM 可用。开发机历史实测为 Origin 2024；其他版本须在自己的机器上验证。
- **Python**：源码保持 3.7 兼容；开发机历史实测为 Python 3.7.1。公开版对现代 Python 提供依赖声明和离线 CI，离线通过不等同于完整 Origin 兼容性。
- **Python 依赖**：PyYAML、Windows 上的 pywin32。Excel 读取使用标准库，无需安装 Excel 或 openpyxl。
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
使用 $battery-origin-plotting，先检查这份 Excel 的字段、单位和科学语义，再画原生可编辑的倍率图。保留全部点和恢复倍率阶段，输出到我指定的任务目录。
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

## 五分钟跑通合成示例

从 skill 根目录执行。任务目录放在技能目录外；下面使用用户临时目录中的新文件夹，源文件不会被覆盖。

```powershell
$demoDir = Join-Path $env:TEMP ('battery-origin-demo-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_example.py --output-dir $demoDir
$specPath = Join-Path $demoDir 'plot_spec.json'
.\.venv\Scripts\python.exe -X utf8 -m plotting_core.cli check --spec $specPath
```

`check` 只读校验、构建绘图计划；无需启动 Origin。示例为两个合成样品、每样品 30 圈，共六个倍率阶段，最后一个 0.1 C 是独立恢复阶段。

Windows 与 Origin 环境就绪后，实际绘图：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m plotting_core.cli render --spec $specPath --qa-level 3
```

成果位于 `$demoDir\outputs\rate_input_synthetic_example\`。实际打开 PNG/SVG 检查文字、图例、曲线与标注，再按 [完整验收](references/acceptance.md) 记录图像审阅。输入、逐点数据、原生结构、可编辑性和图像五项全部通过，才可称为 `accepted=true`；自动运行结束不自动等于完整验收。

## 使用自己的数据

在副本中填入真实数据，按图族提供单位、样品、分支/圈次、来源和必要科学参照。spec 中的输入文件、spec 本身与输出根目录使用绝对路径。工作表选择、表头映射和单位规则见对应契约，不能把任意仪器导出表直接当作标准表。

- GCD / 循环 / 倍率：[输入契约](references/input-schema.md)，[倍率模板](references/rate-capability.md)。
- EIS / GITT / XRD / ICP：[已有 XY 结果输入](references/processed-input.md)，再读对应 [图族规则](references/families/)。
- 明确的简单公式：[处理命令](references/processing-cli.md)、[Na 换算](references/na-conversion.md)、[XRD 处理](references/origin-processing.md)、[ICP 计算](references/icp-calculation.md)。

公开版提供的是可配置的视觉预设：0.5 pt 数据线、常规字重、朝外刻度、柔和配色、循环/倍率 5.8 pt 全点符号。它们不是读者已确认的个人偏好。任务参数可通过模板或 spec overrides 明确配置；质量基准、化学式、Na 参照、XRD 背景状态和 ICP 分母须由当前数据与用户声明确定。

## 验证与已知限制

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

公开仓库 CI 只验证离线可移植性、输入预检与示例，不在 GitHub 托管 runner 上运行 Origin。历史实机能力与当前限制见 [能力状态](references/capability-status.md)。不同 Origin 版本、COM 接口、字体及显示设置仍需本机保存重开和图像验证。

不支持 XRD sticks/独立参考层、ICP 误差棒桥接、GITT 参数反演或 EIS 拟合。对源表中的缺值、重复、无缓存公式或身份歧义会报告并暂停相关计算，不自动补值或更改数据。

## 目录与许可

`SKILL.md` 是 agent 入口；`plotting_core/` 是执行引擎；`references/` 放契约和操作规则；`templates/` 放视觉预设；`scripts/` 放示例准备与预览工具；`examples/` 放合成工作簿和 spec 模板。

本项目代码和文档使用 [MIT License](LICENSE)。Origin、第三方软件和依赖遵循各自许可。原子量数值表注明 [CIAAW 来源](https://www.ciaaw.org/abridged-atomic-weights.htm)；详细来源保留在表的元数据中。
