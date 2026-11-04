# 蓝电／新威测量工程输入

当前状态：**测试阶段**。保留入口供试用和回归，不计入当前稳定支持；见 [能力状态](capability-status.md)。

本入口可直接接收受选蓝电或新威工程，经独立预处理生成既有标准表；它仍处于测试阶段，不能因下游 GCD/双 Y 稳定就推断所有原始格式稳定。源工程只读，不控制设备或修改测试程序。

## 格式与证据边界

扩展名用于选择 reader，实际接受与否由文件头、版本、布局及完整性检查决定。以下状态分别描述读取证据，不能代替标准化、Origin 保存重开或图像验收。

|厂商／布局|实际证据|当前处理边界|
|---|---|---|
|LAND .cex；已核查 ABI 0x30306|已有读取和对照实现；私人样例不随包公开|仅已安装匹配 64 位厂商 DLL；其他 ABI 不猜签名；读取成功不等于本次绘图输入完整|
|LAND `.res`|本轮未实现及验证|拒绝；不得换扩展名或借 `.cex` 的证据声称支持|
|NEWARE .ndax，data.ndc v2/type1|已有原生读取和厂商元数据对照实现；私人样例不随包公开|质量单位/基准和原生循环语义须逐案核对；不重建循环掩盖歧义|
|NEWARE `.ndax`，NDC v5/type1|代码与合成布局／缩放测试|尚无用户真实 v5 工程验证；不把合成测试当真实格式验收|
|NEWARE `.nda` v29 与 v130 的已实现布局|公开真实 fixture 的记录数及字段对照|公开样例读取证据，不等同于本用户所有 NDA 的方法和质量确认|
|NDA v130 的 88 字节记录布局|公开 fixture 可读取记录，但缺少可用原生 Cycle|保留缺失身份；当前绘图标准化阻塞，不按充放电或行号重建循环|
|NDAX 稀疏／分文件 v11/14/16/17，以及其他未实现版本|未实现可靠无补值读取|拒绝，不插值、不积分补容量、不丢尾部后继续。需要另行验证读取方案；不要求用户先做手工 Excel 作为正常流程|

蓝电这里指 [武汉蓝电](https://www.whland.com/)。本机 DLL 提供单位字符串与原生计数，是本次 CEX 的接口证据；厂商 [LANDdt 说明书下载页](https://www.whland.com/dom/down_list.php?channel_id=25514445&username=landiandianzi)说明循环→工步→记录结构及显示单位可配置，因此不能把界面当前显示单位当二进制固定单位。新威受选布局的字节位置和缩放参考 [d-cogswell/NewareNDA](https://github.com/d-cogswell/NewareNDA) 的 2026.6.11 实现；BSD-3-Clause 许可随 reader 保留。它是格式实现依据，不充当科学方法或厂商原生导出验证。本技能不调用该项目可能排序、去重、重建循环或插值的便利处理。

## 命令与请求

从本技能根目录运行，所有输入、请求和输出根目录使用绝对路径。输出根目录必须独立于源测量目录及技能目录。

```powershell
python -X utf8 -m plotting_core.instrument_cli inspect --input "D:/测量数据/样品A.cex" --vendor auto --output-root "D:/绘图任务/样品A工程检查"
python -X utf8 -m plotting_core.instrument_cli prepare --request "D:/绘图任务/GCD_request.json" --output-root "D:/绘图任务/样品A_GCD"
python -X utf8 -m plotting_core.instrument_cli prepare --request "D:/绘图任务/GCD_request.json" --output-root "D:/绘图任务/样品A_GCD_出图" --render
```

`inspect` 不启动 Origin，不要求先提供质量或样品标签；它创建一致快照并返回读取结果，供后续选择和确认。多文件检查也可用 `--request`。`prepare` 必须用请求明确绘图任务，`--input` 与 `--request` 二选一。`--vendor` 仅供单文件 `--input`；JSON 的每项来源使用自己的 `vendor`。

最小 GCD 请求示例（路径及样品标签必须替换为当次真实输入／用户明确身份）：

```json
{
  "schema_version": 1,
  "plot_type": "gcd",
  "sources": [
    {
      "file": "D:/测量数据/样品A.cex",
      "vendor": "land",
      "sample": "样品A_测试1"
    }
  ],
  "cycles": [1],
  "branches": ["charge", "discharge"],
  "task_name": "样品A_首圈GCD",
  "source": "当次用户指定的样品A测试1，选择工程原生第1圈的充放电"
}
```

|字段|要求与含义|
|---|---|
|`schema_version`|整数 `1`|
|`plot_type`|`gcd`、`cycle_performance` 或 `rate_capability`|
|`sources`|非空数组；每项 `file` 为绝对测量文件路径，`vendor` 为 `auto/land/neware`，`sample` 为明确、不同测试间唯一的标签。不能从文件名猜化学式、合并续测或平均|
|`mass_g`、`mass_source`|来源项的可选字段；需要由绝对容量计算比容量而原生质量不足时，提供正数、以 g 为单位的活性材料质量和实际来源。冲突不能靠添加标志静默覆盖|
|`rates_by_cycle`、`rate_source`|来源项的可选字段；以实际输出 Cycle 为键的显式映射，如 `{"1":"0.1 C","2":"0.1 C","3":"0.2 C"}`，并记录测试程序／用户确认位置。示例不构成当前样品倍率程序|
|`reader_options`|可选对象。LAND 可显式给本机 `dll_path`。新威 worker 默认 `metadata_export=true`，可用 `exporter_path` 指定已安装且匹配的 BTSDAExReport；`metadata_export=false` 关闭可选质量导出。正常绘图不设置截断读取或 `include_records=false`。reader 输出路径必须属于本次 attempt，不能写源目录|
|`cycles`|`"all"` 或非空、不重复的整数数组，选的是 reader 声明的原生 Cycle 身份；不表示“前 N 个物理充放电对”。省略时为 `"all"`，不存在的圈必须报告|
|`branches`|`charge/discharge` 的非空不重复数组，省略为两者。循环需两支；倍率需放电；GCD 可明确选单支|
|`task_name`|明确的单个安全目录名称；不含路径分隔符|
|`source`|本次输入、身份及选择的来源说明，不能用通用示例替代真实确认|

不传未实现选项。JSON 请求及 CLI 的未知字段会报错；质量覆盖、软件循环重建、时间拼接、降采样和自动倍率推断不是此入口的功能。

## 字段、简单公式与分组

原生读取保留原始记录序号与源顺序、工步、循环计数、工步状态／支路、V、mA、mAh、时间字段和文件版本／SHA256。界面序号、二进制原始计数及向用户显示的 Cycle 如果存在偏移，必须由 reader 元数据声明并保留原值；Python 行号不能冒充实验循环号。新威工步时间不是累计测试时间，缺少后者时保留空值，不虚构。

GCD 标准化输出既有 `gcd/excel_long`：Sample、Cycle、Branch、电压及各自充放电比容量；每个选择的活性点保留原序和精确来源映射。新入口默认 `labels.y="Voltage (V)"`，不继承旧模板的 Na 参比假设；已明确参比时在最终 PlotSpec 的 `labels.y` 或正式语义标签中填写，并记录依据。不能从材料名称猜参比。

循环与倍率输出既有 `excel_cycle_summary`，不是让 A reader 分析仪器记录。优先使用有明确语义的原生循环汇总；新威 reader 的 cycle 表是按无歧义原生计数分组后，对原生工步累计末点明确求和的派生结果，记录 `sum_of_native_step_endpoints`，不称为厂家原生 summary。没有可用表时，仅在满足单一连续工步等实现条件下使用原生累计容量末点，记录方法，不积分、扣起点或重建循环。新生成循环 spec 默认启用既有 CE 上置、配对图例和两个轴归属箭头，旧 Excel spec 保持原行为。

允许的本入口简单公式仅在来源明确时执行并记录：绝对容量除以活性材料质量得到 mAh/g；循环未提供原生 CE 时，以同一圈的放电／充电容量×100 得到百分数。原生已有比容量或 CE 时优先保留，并与可用绝对容量／质量交叉核对；不能按大小猜单位、反号或覆盖冲突。

### 必须拦截的科学歧义

- **质量**：质量基准须由当前明确声明或可信厂商字段及单位确定。LAND `GetActMaterialMass` 的明确单位和来源可复用，已有明确声明时不重复询问；这不证明仪器录入值必然正确。新威 `BatteryMass/SCQ` 等无可靠单位／基准的字段保留，不猜 mg/g；受选 NDAX v2 可自动通过本机已验证的厂家离线组件仅导出 unit/test 元数据，唯一定位“活性物质”及带明确单位的正数，记录报表单元格、SHA 和对应源 SHA。未找到组件、版本未验证、存在 BTS/BTSDA 会话或标签／单位歧义时保留具体诊断，不干扰已有会话；仍缺质量才集中询问 `mass_g` 及来源。NDA 质量候选不能自动当已确认活性质量。
- **工步容量**：单工步累计与整圈同支累计不同。真实 LAND CEX 的相邻放电工步已使用整圈同支累计坐标，不能再加前一步容量。多个 step-cumulative 工步、容量下降／重置、同支路被静置或其他支路隔断后返回，当前既有 GCD 无独立 Segment，不自动相加、移轴或连线。
- **循环身份**：一个原生计数若包含多组物理充放电，保留原计数和工步并阻塞需要完整圈定义的标准化；不能直接相加成高容量，也不能静默重编号。
- **倍率**：只采用已验证的原生 `rate_c`，或实际 Cycle→Rate 映射及 `rate_source`。不从电流、文件名、质量、名义容量候选或固定阶段数猜倍率。恢复到早期 Rate 仍为新的连续阶段，标签中点规则复用既有 [倍率规范](rate-capability.md)。
- **异常与缺失**：缺失／重复原生记录号、断号／回退、单位冲突、未知分支、所选支路缺失、重复 Q/V、缺值及不完整末圈按当前契约阻塞，不静默删点、去重、补支路或保留第一条／最后一条。所选之外与 rest 记录仍保留在原生提取结果中，并记录未用于绘图的原因和计数。
- **多文件**：同文件、同 SHA 的重复选择拒绝；同一 Sample 的多文件不自动拼接续测。先保留各自测试身份，不因名称相近而当独立重复或平均。

Na 图继续复用 [Na 换算](na-conversion.md) 的独立 `gcd_na` 流程，以本入口已验证的标准 GCD 为输入；新图仍需化学式、容量／Na 参照、起点及配对声明。不能仅因工程可读就默认绝对 x、跨圈累计或重置放电起点。XRD/ICP 等其余图族保留各自现有输入，不借电化学 reader 宣称仪器原始文件支持。

## 安全读取、输出与验收

每次尝试在外部 `output-root/attempts/<UTC时间_随机ID>/` 中保留请求、一致快照及原始 SHA、读取后快照 SHA、当前源 SHA、完整原生 JSON 和 worker 日志。快照过程中源变化就拒绝；源在一致快照之后继续写入时披露 `source_advanced_after_snapshot`，本次结果只对应快照。厂商 DLL 在独立子进程读取，失败不能继承旧成功。不控制电池测试设备、不修改厂商软件设置、不注册全局 DLL。

新威可选质量导出只接受已验证的 BTSDAExReport 8.0.0.43 及匹配 Common/BTSDALib/NdcReader 组件；不随技能分发原厂二进制。自动定位支持 `NEWARE_EXPORTER_EXE`、PATH、注册表和现有快捷方式。运行时复制组件及配置到独立任务目录，PUBLIC/TEMP/TMP 只对该子进程改向；仅在配置副本选择 unit/test，禁用 cycle/step/record/curve 等表。保存小型报表／日志／来源 manifest，清理本次临时组件。不会用厂家重建循环或舍入后的容量替换完整原生记录，也不导入便捷导数列。

通过标准化后才发布 `standard/standard_input.xlsx`、`plot_spec.json`、`instrument_manifest.json`；manifest 保留源 hash、原生记录／工步到标准行的映射、单位／质量／CE／Rate 方法，以及选择与未绘记录计数。写出后复用原 A reader/plan 逐点核对。失败不发布可用标准输入，保留集中问题，最新 `current_import.json` 也更新为失败状态。

`import_check.json` 的 `ready`／`import_accepted` 只表示该阶段通过；`inspect` 成功仅为可读，不能声称已接受绘图。`prepare --render` 调用现有原生 Origin pipeline；最终可编辑性、保存重开回读绑定／全部值和图像状态，继续按 [渲染流程](rendering-pipeline.md) 与 [验收](acceptance.md) 分项记录。未做实际图像检查时必须保留未验状态，不能以读取或自动检查成功宣称完整 accepted。

科学确认、自动读取／算术核对、Origin 实机和实际图像验收必须分别表述。`scientific_truth_verified=false` 不因读通工程或公式测试通过而改为 true。版本、字段或关键语义不足时先完成可读快照与核查，再集中询问本次决定性缺口，继续不依赖它的任务。

可直接使用的中文调用：

- “用这份蓝电 CEX 画第 1、5、10 圈 GCD，样品名为 S1；直接读取工程，不用我导出 Excel。先检查原生工步和容量基准。”
- “读取这三份新威 NDAX，样品／测试标签分别是 A、B、C，画放电比容量与 CE 循环图；质量采用我附的活性质量表和来源。若工程循环计数有歧义先列出。”
- “直接读取新威工程画倍率，逐圈 Rate 采用这份测试程序映射。按连续阶段识别恢复倍率并居中标签；缺失或矛盾的圈先报告。”
- “先读取这份蓝电工程并生成标准 GCD 输入，再按我给的化学式和 Δx 参照走现有 Na 公式；保留工程原始记录与计算映射。”
