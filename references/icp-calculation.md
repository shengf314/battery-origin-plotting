# ICP 原始结果到元素摩尔比例（独立计算接口）

用户已授权：以后提供 ICP 原始数据，由 skill 识别实际元素并计算；元素不限于历史 Na/Mn/Ni/Li/Ti。本接口支持**明确单位、样品和元素的测量结果记录**，或显式映射的标准长表。可通过 [独立 B 命令与桥接](processing-cli.md) 做 preflight/execute，保存并重开核对处理工程，然后导出 A 既有 `icp/excel_processed_series` 的元素比例输入继续原生绘图。记录／列映射接口不代表仪器原始格式解析；当前未提供真实原始表及其比例分母，合成验算不代表真实样品方法已确认。

## 科学定义与单位

质量浓度为组分质量/混合物体积，物质的量浓度为组分物质的量/混合物体积；同一被测元素的摩尔质量 `M = m/n`，因此 `c_mol/L = c_g/L / M_g/mol`。这里的质量浓度必须以**元素本身**计，不把氧化物浓度当元素质量浓度。[IUPAC 质量浓度](https://goldbook.iupac.org/terms/view/M03713)、[IUPAC 物质的量浓度](https://goldbook.iupac.org/terms/view/A00295)、[NIST SI 第8章，摩尔质量](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-8)

| 输入单位 | 统一到 g/L 或 mol/L 的乘数 | 下一步 |
|---|---:|---|
| g/L、mg/L、ug/L、ng/L | 1、10⁻³、10⁻⁶、10⁻⁹ g/L | 除以该元素的 M（g/mol） |
| mol/L、mmol/L、umol/L、nmol/L | 1、10⁻³、10⁻⁶、10⁻⁹ mol/L | 已是物质的量浓度，不再除 M |

`µ`、`μ` 作为 micro 前缀统一为 ASCII `u`；`/l` 可明确解释为 `/L`。不把 ppm、ppb、质量百分数、mg/kg、无单位数字自动解释为 mg/L。[NIST SI 第4章，前缀表](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-4-two-classes-si-units-and-si-prefixes)

元素识别共用 `plotting_core.domains.chemistry.formula_mass.atomic_weight()` 与同目录 `atomic_weights_ciaaw2024_abridged.json`。仅认大小写正确的元素符号，或用户明确的 `element_map`；不猜测 `CO` 是 Co，不解析同位素/化合物为元素。版本、官方来源、表 SHA256、采用值均进入 provenance。表中没有标准原子量的元素须另行确认，不能拿同位素质量数代替。这里使用常规天然材料的标准原子量数值作为 g/mol，不证明真实样品同位素组成。

## API 与输入

```python
from plotting_core.domains.chemistry.icp_calculation import calculate_icp_ratios

raw = [
    {"sample": "synthetic A", "element": "Fe", "concentration": 55.845, "unit": "mg/L"},
    {"sample": "synthetic A", "element": "Cu", "concentration": 63.546, "unit": "mg/L"},
]
result = calculate_icp_ratios(
    raw,
    denominator={"type": "element", "element": "Cu"},
    source={"kind": "synthetic verification; no experimental sample"},
)
# 同一示例 Fe/Cu = 1；raw 不变，新结果位于 result["ratios"]。
```

必需字段为 `sample`、`element`、`concentration`、`unit`；可提供 `dilution_factor`、`replicate`、`qualifier`、`aliquot`。浓度约定为测得溶液中元素浓度；总稀释因子乘数把结果放到其共同样品基准。已扣 blank 或已做稀释校正的资料应说明方法并整理为明确输入，不能再次盲目应用校正。

标准长表必须提供 `rows` 与 `column_map`，不自行识别仪器文件：

```python
table = {
    "column_map": {
        "sample": "Sample", "element": "Element",
        "concentration": "Concentration (mg/L)", "replicate": "Preparation",
    },
    "rows": [
        {"Sample": "synthetic A", "Element": "Fe", "Concentration (mg/L)": 55.845, "Preparation": "1"},
        {"Sample": "synthetic A", "Element": "Cu", "Concentration (mg/L)": 63.546, "Preparation": "1"},
    ],
}
```

浓度表头末尾支持 `(mg/L)` 或 `[mg/L]`；也可显式映射 `unit` 列。若行单位与表头冲突，集中报告，不自动重解释。原表、字段映射和别名映射保存在 provenance。

## 分母、稀释与缺失值

分母必须明确选择一种：

- `{"type": "element", "element": "Cu"}`：Cu 为 1，输出 `n(E)/n(Cu)`。
- `{"type": "sum", "elements": ["Fe", "Cu"]}`：输出 `n(E)/(n(Fe)+n(Cu))`。只有指定集合中的元素相加为1；集合外元素仍可有比值，不把它称为全样品原子分数或补全化学式。

在同一 `sample/replicate` 的共同溶液基准上，浓度比等于物质的量比；所有元素共同的稀释因子可取消。未提供任何稀释因子时，只记“共同未知因子取消”，不声称已得到原样品绝对浓度；如果给了因子，必须每个元素均明确，不同因子逐项应用。不同 aliquot 需要明确共同样品当量/体积，本接口先阻塞，不假定只乘稀释因子就已可比较。

空值、ND、`<LOD`、`<0.2`、非有限值、负值、单位缺失、元素歧义、重复 `sample/replicate/element`、缺分母元素及零分母全部集中在 `report.questions/duplicates`。真实量化的零可保留为零；ND 不改0，不扣 blank，不补 O 或 Na，不自动形成某个目标化学式。`ready=False` 时 `ratios/replicate_summary` 为空，`normalized_results` 仅供核对阻塞原因。

## 重复与误差

默认保留各个 replicate 的比值，不自动添加误差。只有实际存在至少两个明确不同的独立制样重复，且提供如下设计，才先逐重复计算比值，再算均值和误差：

```python
replicate_design = {
    "kind": "independent_preparations",
    "source": "用户提供的独立制样重复记录",
    "method": "sample_sd",  # 或 standard_error
}
```

`sample_sd` 使用 n−1 的样本标准差；`standard_error` 为 SD/√n。每个独立重复必须覆盖相同元素集合，不用同一次测量的多条波长/重复扫描冒充制样重复，不以提供 SD/SE 字段代替实际独立记录。这是重复间的统计量，未加入校准、回收、空白、原子量、体积等 Type B 不确定度，也不表示完整测量不确定度。[NIST TN1297 附录A，独立观测的均值与标准误差](https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-appendix-law-propagation-uncertainty)

输出包括每行单位换算、采用原子量、比例分母、稀释策略、原输入副本及独立重复方法。`scientific_truth_verified=False` 始终保留；计算正确不能替代样品身份、消解充分性、校准、检出限和方法确认。A 的 `element_ratio` 入口仍只读已整理结果；[B 桥接](processing-cli.md) 会输出这种现有格式，不扩大正式 data.kind，也不自动读取未来的 ICP 仪器原始文件。

桥接的 Y 轴显示结果中的**规范化分母**和其实际 normalization，例如 `Cu=1` 或 `sum(Fe, Cu)=1`；不从浓度大小或目标化学式猜分母。来源映射的 `source_record_indices` 是 supplied JSON records／显式 table.rows 的1起始记录序号，与每个 ratio.source_row 对应。原 Excel 行号未知时 `source_rows=null`，不把记录索引冒称文件行号。独立重复统计仍由计算 API 支持，但 A 尚无误差棒时，完整 B→A bridge 对这种不确定性明确阻塞，不忽略后继续画图。
