# 标准 Excel 输入契约

本页仍是 A 绘图层的正式三族契约。用户提供受支持 LAND CEX／NEWARE NDA、NDAX 时，先走 [仪器工程预处理](instrument-projects.md) 自动生成本契约所需标准 XLSX/PlotSpec，用户不必手动导出。它不改变本页 `data.kind`，也不使 A reader 自行分析仪器原始记录。

## 通用校验顺序

GCD 使用点级长表；Cycle Performance 与 Rate Capability 复用圈级 excel_cycle_summary 方言，不将不同粒度混入万能工作表。通用流程为 Sheet 检查 → 表头映射 → Sample / Cycle 校验 → 图族结构校验 → 意图筛选 → 实际所需数值及重复检查。所有操作只读，临时绘图数据另存。

本契约只定义输入语义和验证，不规定最终轴标题、单位显示格式或视觉样式。

## Sheet1-only

默认只读取名称为 Sheet1 的工作表，但先检查所有工作表（含隐藏表）是否有实际内容：

| 状态 | 处理 |
| --- | --- |
| Sheet1 有有效数据，其他表无实际内容 | 继续 |
| Sheet1 有数据，任何其他表有实际内容 | 列出表名，停止绘图并请求处理确认 |
| Sheet1 为空或不存在，其他表有内容 | 停止询问，不自动切换 |
| 所有表均为空，或只有表头无数据 | 报告无可绘制数据，停止 |

text、数值（包括 0）、公式、公式结果及有效表格数据都算内容。公式即使返回空字符串也算内容；读取公式本体与缓存结果分别判断，不能仅用 data_only 视图判空。单纯格式、边框、颜色、样式、格式化空白区域及残留 formatting 不算内容，不以 used range 的大小代替内容检测。

表头应为 Sheet1 第一行，后续为数据行。发现前置说明、合并表头或无法确定表头行时询问，不自动猜表头。完全没有值或公式的行不构成数据点；其他行保留 Excel 实际行号，不能压缩行号后报告。其他 Sheet 的处理只有用户明确确认后才能例外执行，记录选择。

## 表头语义归一化

可忽略大小写、首尾空格及已识别语义名称/单位中的格式间隔。先识别完整语义名称，再识别已知单位后缀；不盲目删除任意括号、斜线或字符。

| Canonical field | 明确别名 |
| --- | --- |
| Sample | 样品 |
| Cycle | Cycle Number、循环圈数 |
| Rate | C-rate、C rate、倍率 |
| Branch | 充放电分支 |
| Voltage | 电压 |
| Charge Specific Capacity | 充电比容量 |
| Discharge Specific Capacity | 放电比容量 |
| Charge Na Content | 充电钠含量 |
| Discharge Na Content | 放电钠含量 |
| Coulombic Efficiency | 库仑效率 |

Voltage、Voltage(V)、Voltage / V、电压(V)、电压 / V 视为同一语义。Discharge Specific Capacity(mAh/g)、Discharge Specific Capacity / mAh g-1、放电比容量(mAh·g⁻¹) 视为同一语义；Charge Specific Capacity 同理。括号、斜线、spacing、常见 Unicode 上下标及上述等价单位格式可归一化。

Capacity 不能映射成 Specific Capacity，Q 不能猜容量物理量，E 不能猜 Voltage。未知或有歧义且可能承担所需字段的表头须确认。多个列映射到同一所需语义时停止，不能择一、合并或覆盖。明确无关的额外字段可以不参与绘图，并记录未使用字段。

只归一化单位格式，不转换单位或数值尺度。不同单位、无单位但尺度不明、Na Content 定义不明须询问。库仑效率的比例数与百分数不能根据数值大小推断，也不能自动乘除；Excel 百分比显示与底层值不一致时须确认应传入 Origin 的数值表示。输入单位示例不是最终坐标轴格式。

## Sample：各图族共用

- 无 Sample 列：整份文件视为一个样品。
- 有列但所有数据行均为空（空白文本 trim 后为空也计为空）：视为一个样品。
- 所有数据行均有有效 Sample：按名称分组，trim 首尾空格，例如 `NFM ` → `NFM`。
- 部分数据行为空：输入异常，报告行号并停止请求修正/确认，不 forward-fill、不猜所属样品。

无名称的单样品可用内部单样品标识，但不能把自动生成的标识写入 legend。已确定单样品且无 Sample 列时，允许按 domains/electrochemistry/naming.py 从文件名剥离已知测试后缀（如 GCD、cycle、eis、rate 及已识别圈数/倍率）获取候选展示名；不能把此候选当作已核实的样品身份；有列但全空时请用户提供展示名。若用户说明或输入结构明确显示多样品却没有 Sample 列，停止要求明确样品对应关系，不根据文件名或列顺序分配身份。不得根据数值轨迹猜测多样品。Sample 标识大小写不同时，如合并与否影响样品身份，询问后处理；不把表头的大小写容忍规则用于猜样品身份。

## Cycle：各图族共用

每个数据行必须具有 Cycle。空值必须停止请求修正或确认，不继承上一行、不 forward-fill、不通过相邻数据推断。

接受有限、整数值的数值或纯数字形式，例如 1、2、10、1.0、2.0；可无歧义归一为整数。拒绝布尔值、日期、非整数、无穷值和 NaN。`Cycle 1`、`1st`、`First`、`第1圈` 不能自动解析，须确认/修正。不自行给 Cycle 重新编号。

## GCD schema：point-level long-format

| Canonical field | 要求 |
| --- | --- |
| Sample | 可选，按通用规则 |
| Cycle | 必须 |
| Branch | 必须 |
| Voltage | 所选绘图点必须 |
| Charge Specific Capacity | 比容量图的 charge 点必须 |
| Discharge Specific Capacity | 比容量图的 discharge 点必须 |
| Charge Na Content | Na Content 图的 charge 点必须 |
| Discharge Na Content | Na Content 图的 discharge 点必须 |

列出全部 canonical 字段不意味着每次绘图都必须有所有数值列；仅当前表示及实际分支对应的列必须存在。不得因为未使用的 Na Content/容量列缺失而阻止另一表示绘图。

### Branch 枚举

trim 并忽略大小写后仅接受：

| Canonical value | 明确别名 |
| --- | --- |
| charge | Charge、charge、Chg、充电 |
| discharge | Discharge、discharge、DChg、放电 |

空值或未定义值必须停止确认/修正，包括 `充电1`、`Rest`、`CC Charge`、`CV Charge`、`CC Discharge`、`上行`、`下行`、`脱钠`、`嵌钠`。不能根据电流正负、容量列是否非零、轨迹方向或 Na Content 判断 Branch。

### Branch-based column selection

| 表示 | Branch | X | Y |
| --- | --- | --- | --- |
| specific_capacity | charge | Charge Specific Capacity | Voltage |
| specific_capacity | discharge | Discharge Specific Capacity | Voltage |
| na_content | charge | Charge Na Content | Voltage |
| na_content | discharge | Discharge Na Content | Voltage |

Branch 是选择 X 列的唯一依据。非当前 Branch 列完全不参与读取、数值验证、容量判断、QC、重复判定或绘图点创建，其 0、blank、NaN 均忽略。当前不使用的另一种 X 表示也不检查。

按 Sample + Cycle + Branch 分组，组内点顺序必须与 Excel 原始行顺序一致。禁止按 Voltage、Capacity、Na Content 或升降序排序。分组不是重新排序轨迹；不能将两分支拼接成一条跨分支连接线。

所选 Sample + Cycle 缺少任一预期分支时先报告并确认是否只画已有分支，不补造数据。

## Cycle Performance schema：cycle-level summary

| Canonical field | 要求 |
| --- | --- |
| Sample | 可选，按通用规则 |
| Cycle | 必须，作为 X |
| Discharge Specific Capacity | 所选行必须，作为左 Y |
| Coulombic Efficiency | 所选行必须，作为右 Y |

不需要 Branch、Voltage、Charge Specific Capacity、Charge Na Content 或 Discharge Na Content。两个 Y 均使用 symbol + connecting line。

每个 Sample + Cycle 应对应一条汇总记录；出现多条时报告并确认，禁止平均、合并、任选一条或自动去重。保留输入顺序；若循环顺序非单调，说明连接线会按该顺序绘制并询问，不自行排序。这是输入顺序确认，不开展科研数据 QC。

## 所需数值验证与公式

只验证意图筛选后实际使用的 numeric fields。GCD 每个点只检查 Voltage 和当前 Branch 对应的 X；Cycle Performance 检查两个指标。结构字段的缺失不能用这一规则绕过。

- blank / NaN：报告字段、缺失数量、Sample、Cycle、Branch（如适用）、Excel 行号；即使仅一个点也暂停，询问是否允许 skip affected points。
- `--`、`error`、`2.5 V`、`N/A`、`invalid` 等文本：输入异常，不 strip text、不提取数字、不替换为 NaN 或 0。数值字段中的文本编码数字也不能擅自转型；Cycle 仅适用其明确的归一化规则。
- 无穷值、布尔值、日期或 Excel 错误值：不是有效绘图数值，报告确认/修正。有限数值 0 不视为缺失，不凭大小或正负判断科研合理性。
- 公式：读取缓存值，不重算或修改源文件；缓存缺失、错误、外部引用依赖或无法确认有效时请求用户提供已计算并保存的标准文件，不猜结果。可用缓存不能证明其最新，交付时记录使用了缓存。

跳点必须有用户对具体数据及影响范围的明确确认，记录获准行号和系列。GCD 跳过点可能导致相邻有效点连接；Cycle Performance 一项指标缺失不代表另一项无效。若跳过后的连接还是留断点存在歧义，先询问，不能擅自决定。获准后无有效点的系列必须报告，不静默消失。

## Duplicate policy

禁止自动 deduplicate。对实际使用的字段和结构标识检测明显完全重复的记录，排除溯源行号；相同 X/Y 不代表可以删除。发现可能重复时列出涉及行号，提示“检测到可能重复的数据”并询问是否保留继续，保持原数据和顺序。

GCD 检查不得为比较整行而读取非当前 Branch 列或其他无关数值列；相关字段相同仅报告“可能重复”，不能断言原始整行完全相同。圈级图族要求 Sample + Cycle 唯一；重复直接阻断，不支持选择保留第一条、最后一条、平均或自动去重。GCD 的重复点仍按其原规则处理。

## Rate Capability schema：cycle-level summary

`plot_type: rate_capability`，`data.kind: excel_cycle_summary`。此 A reader 只画标准表的放电比容量，不读取 CE、Charge Capacity，不从原始 GCD 提取数据；受支持工程的原生数据整理由独立预处理完成。

| 字段 | 要求 |
| --- | --- |
| Cycle | 必需，有限整数语义 |
| Rate | 必需，工作簿中显式给出 C-rate |
| Discharge Specific Capacity | 必需，有限数值；复用公共容量字段 |
| Sample | 可选；完整列自动识别，部分为空阻断，全空须给单样品展示名 |

Rate 接受 `0.1C`、`0.1 C`、`0.2C`、`0.5C`、`1C`、`2C`、`5C` 及 `C/10`、`C/5`、`C/2` 等明确正倍率；C 大小写与前后空格不影响语义。内部以精确有理数串表示 canonical value（如 `1/10`），有限小数显示为 `0.1 C`；非终止小数保留精确分数形式（如 `C/3`），不使用浮点容差合并倍率。无单位数字、零/负数、`low/medium/high/slow/fast/rate1/rate2/step1/step2` 均拒绝，不根据 Cycle 或电流猜倍率。

按 Sample 分组，在内存副本按 Cycle 排序；连续记录的 canonical Rate 相等时构成一个阶段。中间 Cycle 有空缺时不补点，阶段仍按现有记录的连续 run 定义；显式请求的缺失 Cycle 必须阻断。末尾恢复初始倍率单独成段，不按唯一倍率 groupby 聚合。

多个所选 Sample 的整个 `(canonical Rate, start_cycle, end_cycle)` 序列必须一致；仅倍率顺序相同而切换 Cycle 不同也拒绝，错误列出所有样品程序。每 Sample/Cycle 一条记录，重复即阻断。

`selection.cycles` 可指定 all/single/selected/range；`samples: [{"name": "SFM"}]` 筛选样品。空 samples 表示采用全部已有样品（调用前须从用户意图确定）；请求不存在的样品或圈数不静默忽略。不支持在 `samples[].cycles` 中另设程序。

Rate 错误报告列、源行号、原值及原因；经 InputContractError 走 CLI exit code 2。归一化 source.rate_rows 保留 Cycle、源行号和 Rate 规范化结果，容量点与行号一一对应。工作簿只读；公式只读已有缓存，缺缓存阻断，不重算。

实现入口：`domains/electrochemistry/cycle_summary.py` 公共输入契约，以及 `rate_capability/ingest.py` / `plan.py` 的领域扩展。实际验证边界见 [能力状态](capability-status.md)，不要把文档要求当成所有旧路径都已自动执行的证据。


## 2026-10-08 科学逻辑兼容补充

本页保留原有三图族契约；新系列方言见 [processed-input.md](processed-input.md)。历史 OPJU 检查不等于正式测量工程支持；仪器格式仅限 [已实现的工程预处理](instrument-projects.md) 及其版本边界。

GCD可显式selection.axis_binding=voltage_capacity同时交换数据与物理量标题；默认capacity_voltage不变。data.semantics.x/y可声明scale(linear/log10)、direction(ascending/descending)、quantity、unit及科学label；声明必须匹配实际绑定，log10含非正值阻塞。Na显式语义需要na_content.source/reference；delta_na_content需明确Delta-x轴标题，不计算或变号。分支返回后重新出现会阻塞，旧入口不自动拆解通用Segment。

CE默认percent兼容旧输入；data.semantics.ce_unit=fraction保留小数值并使用fraction标题，不乘100。显式%表头与fraction矛盾、mV电压与旧V契约矛盾、绝对mAh容量与mAh/g契约矛盾均阻塞；无单位旧标准表头仍按原契约解释。
