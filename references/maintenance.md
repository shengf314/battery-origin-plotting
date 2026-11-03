# 本地更新、同步与版本发布

本机安装版是日常修改来源；独立的公开仓库保留可分发文档、安装依赖、测试与脱敏调整。维护脚本保存上一次已审阅的本地源快照，按文件进行 [Git 三方合并](https://git-scm.com/docs/git-merge-file)，保留不重叠的公开版调整。重叠修改会报告文件名，需先在公开版中处理。

本机维护仓库的默认位置为用户目录下的 `.codex/skill-publishing/battery-origin-plotting`，安装版默认来自 `CODEX_HOME/skills/battery-origin-plotting`；未设置 CODEX_HOME 时使用用户目录下的 `.codex/skills/battery-origin-plotting`。可通过 PowerShell 参数覆盖路径。

## 日常操作

在 PowerShell 中设置一次本次窗口的入口变量：

```powershell
$publisher = Join-Path $env:USERPROFILE '.codex\skills\battery-origin-plotting\scripts\publish_public.ps1'
```

| 操作 | 命令 | 结果 |
| --- | --- | --- |
| 预览并检查 | `& $publisher -Action Check` | 列出拟同步文件，在临时副本中执行检查，不改变公开仓库及同步基线 |
| 同步 | `& $publisher -Action Sync` | 合并、检查、提交并推送 main；不创建 Release |
| 发版 | `& $publisher -Action Release -Version 1.1.1 -NotesFile $notesPath` | 先同步，再更新版本、提交、推送版本标签；由 GitHub 完成测试和发布 |
| 发版预演 | `& $publisher -Action Release -Version 1.1.1 -NotesFile $notesPath -DryRun` | 本地合并和测试，输出候选 ZIP 与校验文件；不提交、不推送、不创建标签 |
| 查看结果 | `& $publisher -Action Status` | 最近 Actions 和最新稳定版链接 |

脚本使用当前可执行的 `python`、`git`、`gh`。Python 需安装公开仓库 requirements.txt 中的依赖，GitHub CLI 须已登录并有仓库写权限。需要指定解释器时加 `-Python <解释器绝对路径>`。桌面沙箱对 Git、凭证读取和仓库写入的授权以当前环境为准。

也可以直接在公开仓库根目录使用：

```powershell
python -X utf8 scripts/maintain.py sync --dry-run
python -X utf8 scripts/maintain.py sync --push
python -X utf8 scripts/maintain.py release --version 1.1.1 --notes-file $notesPath
python -X utf8 scripts/maintain.py release --version 1.1.1 --notes-file $notesPath --dry-run
```

版本号按 X.Y.Z 填写，不加 v。普通修复/文档调整递增 patch，新增兼容能力递增 minor，破坏输入契约的更改递增 major。每次必须高于当前 package.json 的版本；已存在的版本标签不能覆盖。

发版预演的 ZIP 放在维护仓库的 dist/preview-v版本号-随机标识/ 下，只存在本机并由 Git 忽略。预演不推进同步基线；正式 Git archive 的元数据不同，最终发布包的 SHA256 以 Release 附件为准。

## 准备发布说明

`-NotesFile` 接收 UTF-8 Markdown 文件。以下示例放在临时目录，发布时会复制为仓库内的 `releases/v版本号.md`：

```powershell
$notesPath = Join-Path $env:TEMP 'battery-origin-release-notes.md'
$notes = @'
修复：在这里写清楚本次变化、适用图族和触发条件。

验证：写明已完成的输入预检、离线测试及实际做过的 Origin 检查。
只有离线测试时，按实际范围记录。
'@
[IO.File]::WriteAllText($notesPath, $notes, [Text.UTF8Encoding]::new($false))
& $publisher -Action Release -Version 1.1.1 -NotesFile $notesPath
```

`release` 会核对版本和说明、同步本地更新、验证临时公开包，更新 package.json / package-lock.json / 能力状态版本，提交说明，再推送 main 和注释标签。版本标签触发 [release.yml](../.github/workflows/release.yml)，复用 [离线检查工作流](../.github/workflows/check.yml)。三个 Python 版本全部通过后才构建版本 ZIP、SHA256SUMS.txt 并发布 GitHub Release；打包时再次核对标签、清单版本和说明文件。

该流程使用 GitHub Actions 自带的 GITHUB_TOKEN，发布任务仅申请仓库 contents 写权限，无需额外保存个人访问令牌。工作流复用与发布 CLI 的依据分别见 [GitHub 文档](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows) 和 [gh release create](https://cli.github.com/manual/gh_release_create)。

## 同步范围与公开版调整

自动合并 SKILL.md、requirements.txt 以及 plotting_core / references / templates / scripts / examples 中的文本资源。README、许可证、Node 依赖清单、Actions、agents 元数据和公开测试由公开仓库维护，本地同名文件不覆盖它们。本地发布入口及本地维护说明也不参与源合并。

私人 Origin 工程、XLSX/CSV 实验数据、数据库、运行产物、缓存、依赖目录和安装版 Git 历史不进入自动同步。公开合成 XLSX 在公开仓库单独维护，不能用本地实验工作簿替换。新增文本会检查常见个人绝对路径、凭证、冲突标记、Python 语法、文档链接和清单版本，并执行公开测试。

本地源文件始终只读；合并检查在临时公开副本中进行，通过后才更新公开工作树。源快照和源路径只保存在公开仓库的 `.git/skill-publisher/baseline.json`，由 Git 排除并且不进入 ZIP。该快照属于私人维护状态，不上传、不随普通 clone 复制；保留它才能延续本机增量同步。

## 初始化与人工处理

本机已配置的维护仓库无需重新初始化。换电脑或重建 checkout 时：

1. 克隆本仓库到上述维护位置，安装 Python 依赖并登录 gh。
2. 检查当前安装版与公开版的差异，将应公开的改动移入公开仓库并完成提交。
3. 在公开仓库中运行下列命令，记录“此本地源对应这个已审阅公开提交”。记录基线表示所有待处理源改动都已核对，不能用来跳过冲突。

```powershell
$reviewedCommit = git rev-parse HEAD
python -X utf8 scripts/maintain.py record-baseline --reviewed-commit $reviewedCommit
```

使用不同安装目录时，同时传 `--source <技能目录绝对路径>`。维护仓库的 origin 必须指向本项目；脚本只在 main 工作，推送前 fetch 并仅允许快进，不会 reset、强制推送或改写历史。

遇到冲突时，脚本保留现有公开文件，只报告待人工处理的文件名。把对应源改动移入公开文件、解决语义和隐私问题、执行 `python scripts/maintain.py check` 并提交后，再按上面的命令记录已审阅基线；然后执行 Sync 推送。

## 失败恢复

- 检查失败：修复本地输入或公开版中报告的问题，再运行 Check。检查失败不推进基线。
- 工作树已有修改：先审阅并提交，不会自动丢弃你的改动。
- 提交后推送失败：本地提交和快照已保存，恢复网络/登录后重跑 Sync 即可；若远端分叉，先处理公开仓库的分叉。
- 发版提交已推送但标签推送失败：检查本地标签与提交，直接重试 `git push origin refs/tags/v版本号`。不要复用 Release 命令重复增加同一个版本。
- GitHub 检查失败：在 Actions 查看日志；临时 runner 故障可重跑失败任务。需要改代码时发布更高版本，不改写已推送标签。
- 发布附件步骤中断：先检查是否留下草稿 Release 和哪些附件已上传；处理草稿后重试任务。已有正式 Release 不覆盖。

这些维护检查验证的是公开包、同步行为和离线输入流程。实际科研图仍按 [完整验收](acceptance.md) 完成 Origin 保存重开、逐点回读、编辑性与图像检查。
