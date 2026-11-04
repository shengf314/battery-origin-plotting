# 独立 B 命令与标准输入桥接

当前状态：**测试阶段**。保留入口供试用和回归，不计入当前稳定支持；见 [能力状态](capability-status.md)。

从技能根目录调用 `python -X utf8 -m plotting_core.processing_cli`。这是明确简单公式的处理入口，仅 gcd_na、xrd_normalization、icp_molar_ratios；A 的 `plotting_core.cli render` 仍只画已有数据，不因图族名称触发计算。参数不足先用 plan/preflight，复用已经确认的偏好和具体任务声明；不从示例补 Na 参照或 ICP 分母。

用户提供 LAND CEX／NEWARE NDA、NDAX 时，先用独立 [instrument_cli 预处理](instrument-projects.md) 自动读取并生成既有标准输入；它不是本命令的新 operation，也不扩展 A 的 `data.kind`。Na 可继续采用该流程生成的标准 GCD 作为本命令输入。

```powershell
python -X utf8 -m plotting_core.processing_cli plan --request <绝对路径_request.json> --output <绝对路径_preflight.json>
python -X utf8 -m plotting_core.processing_cli execute --request <绝对路径_request.json> --confirmation <绝对路径_confirmation.json> --output-root <独立任务输出目录>
```

`preflight` 是 `plan` 的等价名称。它复用现有 reader 和独立 API，不启动 Origin、不写源文件：Na 会计算式量并检查参照；ICP API 将校验与候选算术合并，因此预检明确记录已进行候选算术，但不发布比例作为正式结果。XRD 仅生成带 hash 的 Origin 处理计划。

## 请求与科学确认记录

请求保留旧审核原型的五个字段：

```json
{
  "schema_version": 1,
  "operation": "gcd_na",
  "input": {"plot_spec": "D:/任务/原有GCD_plot_spec.json"},
  "settings": {"output": "delta_x", "samples": {}, "per_series": {}},
  "source": "当次输入、科学含义和处理方法的来源记录"
}
```

|operation|input|settings / 详细约束|
|---|---|---|
|gcd_na|plot_spec：原有 gcd/excel_long 容量输入|output、samples、per_series，见 [Na 换算](na-conversion.md)|
|xrd_normalization|plot_spec：原有 xrd/excel_processed_series 输入|method、background_subtracted、background_source、pdf_reference，见 Origin 处理|
|icp_molar_ratios|records 或 table：已有独立 ICP API 的明确记录／列映射对象|denominator；可显式 element_map、replicate_design，见 [ICP 计算](icp-calculation.md)|

每项的科学校验直接复用既有领域 API。未知字段不被吞掉。JSON 记录不是 A 的新正式输入格式；不新增 data.kind，本 B 命令不负责仪器文件解析。

execute 的 confirmation 记录**已经给出的科学确认**，不要求用户再次批准已明确的内容：

```json
{
  "user_approved": true,
  "evidence": "本次对话确认、已有审核记录或明确授权与参数来源的定位",
  "reviewed_request_sha256": "plan/preflight 输出的 request_sha256"
}
```

hash 覆盖请求、PlotSpec 和源表 hash；输入、公式、参照或参数变化时旧记录不匹配。agent 只能据已有真实确认生成此记录；不得将缺失信息改成默认值再声称已确认。绝对路径请求/来源只读，输出必须在技能和源文件目录以外的独立任务目录。

## execute 的成果与验收

每次执行创建 `attempts/<UTC时间_随机ID>/`，保留 request、confirmation、preflight、processing_result、实际 Origin 命令和独立 `processing.opju`。XRD 明确归一化公式复用 Origin API；Na/ICP 计算复用原 Python API，再把原始输入和结果写入不同的 Origin 原生列。ICP 各记录保留自己的浓度单位，不将不同单位合并为一个共同单位。

会话由 OriginBackend 的 DispatchEx 独立创建，退出后新建另一会话 Load 保存的工程。逐列核对：实际点数、每个值和顺序、X/Y 指定、LongName、Units、完整 Comments 来源记录。失败时尽可能保存 owned 会话的 `processing_failed.opju`；不连接或修改用户已有 Origin。

`processing_check.json` 的 `processing_accepted=true` 只表示 B 保存工程与标准数据桥接通过；不代表图像或科学方法真实性已经通过。`current_processing.json` 始终指向最新尝试，失败也更新为 false，旧成功成果仍完整保留。

保存回读成功后，桥接写出 `standard_result.xlsx` 和 `plot_spec.json`，立即用原有 A reader 读回并逐点比较：

- Na：仍用 gcd/excel_long、充放电各自 Na 列、明确 Na/Δx 语义；容量与电压绑定方向保持。保留原 spec 的图例格式和 data.notes，例如人工 `Pair 1` 不改写成实测 `Cycle 1`。直接读原标准表恢复每个实际来源行，连同原有附加来源列、结果行和 charge 末点参照存入 `source_result_mapping.json`；不由首末行补造内部行号。Na 原生 provenance 引用该映射文件和 SHA256。
- XRD：xrd/excel_processed_series；B 原生结果单位为 1（max/range）或 %（range100），A 沿现有谱图契约以 a.u. 表示无量纲归一化强度，不再改数值。保留原波长和方向；PDF 仅保留本次确认记录，不从编号自动构造参考数据。
- ICP：icp/excel_processed_series 的无量纲 element_ratio，元素索引保持一一映射，不连线、不补测未提供元素。不同独立制样不平均成一条记录。

不支持把请求了重复统计的不确定性丢掉后继续绘图：独立 ICP API 仍可计算统计；本 end-to-end bridge 在已有 replicate_summary 时明确阻塞，因为 A 尚未实现误差棒。本命令仅三项 operation；不提供求导、平滑、分峰、拟合、背景处理、GITT D 计算，也不承担独立工程预处理的读取职责。

若本次已明确需要图，可加 `--render`：它在 B 验证后调用原有 A pipeline，并另存原生图工程。生成的 PlotSpec 明确包含 `verification.level=3`、`reopen_project=true`、`editability_probe=true`，因此自动检查包括逐点数据回读、保存重开和在工程副本执行真实原生对象编辑并重开；仅传 QA level 3 不会自动启用编辑探针。也可直接用生成的 PlotSpec 调用 A render。实际查看 PNG/SVG 后仍需完成已有 hash 绑定 image review，不能以 `processing_accepted`、单元测试或 dry-run 代替 A 的完整五项验收。
