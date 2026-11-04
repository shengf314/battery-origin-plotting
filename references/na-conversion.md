# 比容量–电压到 Δx / 绝对 Na 含量的独立流程

当前状态：**测试阶段**。稳定 GCD 绘图不等于本公式处理已列为稳定支持。

本流程接收已经读入内存的比容量–电压点数据，按明确的方法、质量基准、化学式单位和参照换算，返回新的坐标与溯源记录。它与绘图入口分开：`render`、GCD ingest 和其他图族均不会自动调用。本模块不直接解析仪器工程；受选工程需先经 [测试阶段预处理](instrument-projects.md) 生成标准 GCD，仍须当次化学式和参照声明。不会改写原工程、原 Excel、原始点或样式。历史开发验证不构成当前用户的科学确认；新输入的质量基准和参照须明确提供，验证边界见 [能力状态](capability-status.md)。

## 公式与来源

设 Q 和 Q_ref 都用 **同一声明质量基准** 的 mAh g⁻¹，M 为该质量基准所对应参考活性材料的摩尔质量（g mol⁻¹，每摩尔声明的化学式单位），n 是每个 Na 对应的电子数，s 为用户明确的 +1 / −1 关系：

```text
Q_active_difference = (Q - Q_ref) / f
local_delta = Q_active_difference × M × 3.6 / (F × n) × s
Δx = Δx_at_Q_ref + local_delta       # delta_x 模式，偏移也必须明确
x = x_ref + local_delta             # absolute_x 模式
```

3.6 将 mAh 换成 C。若容量本来按活性材料质量归一化，f = 1；若按电极复合物质量归一化，f 必须由用户明确提供为 m_active / m_composite。Q_ref 也在原质量基准下，不能只校正 Q 或把已按活性质量归一化的容量再次除以活性比例。

F = N_A e。代码使用 NIST 2022 CODATA 表中的精确定义输入 N_A = 6.02214076×10²³ mol⁻¹、e = 1.602176634×10⁻¹⁹ C，二者相乘在 Python 双精度中约为 **96485.33212331001 C mol⁻¹**；其来源及浮点求值方式写入输出溯源。[NIST 2022 CODATA 完整常数表](https://physics.nist.gov/cuu/Constants/Table/allascii.txt)

Wei 等的原始研究将已测比容量按 3.6MC/F 换算为每化学式单位的 Na 储存当量，见正文第 215 页。本流程将该电量守恒关系写为相对 Q_ref 的带符号差量，并仅接受用户声明的 **化学计量 Na 插层、每 Na 一个电子** 适用假设；论文里的具体材料或验证结果不会自动套用到用户样品。[Wei et al., *iScience* 6, 212–221 (2018), DOI 10.1016/j.isci.2018.07.020](https://doi.org/10.1016/j.isci.2018.07.020)，[作者机构公开全文](https://escholarship.org/content/qt014453h5/qt014453h5_noSplash_d02717461102950314fa52509ee29a43.pdf)

## 计算前需明确的记录

|记录|要求与作用|
|---|---|
|method / output|method = faraday_stoichiometry；output = delta_x 或 absolute_x|
|series_id / source|本次独立系列的 ID 与提供数据的位置；一次调用对应一个明确系列|
|capacity_unit / voltage_unit|明确 mAh g-1 / V；不从标题猜单位，不在此处理其他单位|
|mass_normalization.basis / source|active_material 或 electrode_composite，以及实际质量归一基准的来源。公开版要求明确提供实际质量基准及来源；缺失时 preflight 阻塞，不沿用作者历史确认|
|active_fraction|仅复合物基准换算时必需；value 为 0 < f ≤ 1，basis 明确 active_material_mass/electrode_composite_mass，并记录 source。活性材料基准即使保留历史配比记录，也不会重复校正|
|material.formula / formula_source|用户提供样品的数字化学式及其来源；按有版本来源的CIAAW2024质量表解析计数并计算M，不从材料简称猜组成，也不要求用户手输M|
|formula_unit_basis / molar_mass_method|固定的参考化学式单位计数基准；molar_mass_method=ciaaw2024_formula 时保留元素计数、质量贡献和表版本/hash。M 应与称量所对应的参考活性材料和所用化学式单位相符，不能把换算后的逐点 Na 含量再用于动态改M。旧显式supplied M仍可作为独立接口的历史声明，但共享GCD新流程使用分子式计算值|
|assumptions.reaction / electrons_per_na / source|stoichiometric_na_intercalation、n = 1 及用户对材料适用条件的依据；其他储钠模型不通过此方法|
|parasitic_charge|unknown / assumed_negligible / externally_corrected；后两者还要 parasitic_charge_source，记录假设依据或外部已校正结果的位置|
|direction_sign / delta_convention / source|显式 s = +1 或 −1，采用 x_minus_reference_x 约定，及该有符号关系的来源。charge/discharge 标签不决定 s|
|reference_capacity_mAh_g / reference_source|必须明确 Q_ref 及其状态、来源；不会默认第一点或默认零容量|
|reference_x / reference_x_source|绝对 x 模式额外必需：与 Q_ref 同一状态、同一化学式单位的已知 x_ref 及其依据。不会从名义化学式、循环号或charge/discharge名称自动推断|
|reference_delta_x / reference_delta_x_source|Δx 模式额外必需：在本分支 Q_ref 状态相对于共同参照的已知 Δx 偏移与来源。即使偏移为0也须明确；放电不默认从0开始|

缺少这些科学决定时，`validate_na_conversion` 将问题集中放入 ValidationReport。无参照状态时需先询问用户；本函数只返回问题供调用方展示，不自行虚构参照。多个循环、分支或独立区间须分别提供各自的有符号关系与参照，不能依靠循环编号自动传播绝对 x。

`local_delta` 是相对本分支 Q_ref 的变化；delta_x 输出先叠加该状态在共同 Δx 参照下的已知偏移。absolute_x 输出叠加该状态的绝对 x_ref。这两种偏移的物理意义不同，不能把工作表里已有的负 Δx 偏移直接当成绝对 Na 含量。

若寄生电量未知，计算结果标为 **在所声明假设下的容量等效 Na 变化/含量估计**，同时保留 charge_attribution 缺口。该模块不扣除 SEI、电解液反应或其他非 Na 电量，也不把容量反算等同于独立组成测定。即使记录齐全且 status=declared，scientific_truth_verified 仍为 false。参数和用户对科学决定的确认记录完整写入 provenance，便于后来核查。

不自设 x 的物理上下界，不裁剪负值或大于某个经验值的结果；若结果超出用户预期，应回看参照、方向、质量基准和适用假设。非有限输入/算术溢出会阻塞整个结果，不遗漏单点。原点序、每点电压及额外来源行/样品等字段保持原样。

## 独立 Python 调用示例

以下点数据和化学式都是合成示例，不是任何用户的真实材料或已审核实验数据。M由示例式按CIAAW2024计算；实际调用时先替换为用户提供、核对过的记录。

```python
from plotting_core.domains.electrochemistry.gcd.na_conversion import (
    validate_na_conversion, convert_na_coordinates,
)

point_data = [
    {"capacity_mAh_g": 0.0, "voltage_V": 3.0, "source_row": 2},
    {"capacity_mAh_g": 50.0, "voltage_V": 4.0, "source_row": 3},
]
declaration = {
    "method": "faraday_stoichiometry",
    "output": "delta_x",  # absolute_x 另需 relation.reference_x / reference_x_source
    "series_id": "synthetic_C1_charge",
    "source": "synthetic supplied capacity-voltage points",
    "capacity_unit": "mAh g-1", "voltage_unit": "V",
    "mass_normalization": {
        "basis": "active_material", "source": "synthetic active-mass record",
    },
    "material": {
        "formula": "NaMnO2",
        "formula_source": "synthetic fixture",
        "formula_unit_basis": "fixed formula-unit count of reference active material",
        "molar_mass_method": "ciaaw2024_formula",
    },
    "assumptions": {
        "reaction": "stoichiometric_na_intercalation",
        "electrons_per_na": 1,
        "source": "synthetic explicitly supplied assumption",
        "parasitic_charge": "unknown",
    },
    "relation": {
        "direction_sign": -1,  # 已明确容量增加对应 Na 减少，不能只靠charge标签
        "delta_convention": "x_minus_reference_x",
        "source": "synthetic signed relation record",
        "reference_capacity_mAh_g": 0.0,
        "reference_source": "synthetic reference state",
        "reference_delta_x": 0.0,
        "reference_delta_x_source": "synthetic explicitly declared common delta origin",
    },
}

dry = validate_na_conversion(point_data, declaration)
# dry 不计算Na坐标；查看 dry['ready'] 和 dry['report']['questions']。
# 真实数据/质量基准/关系/参照经用户确认后，记录这一次已有确认即可。
approval = {
    "user_approved": True,
    "reviewed_input_sha256": dry["input_sha256"],
    "evidence": "synthetic test confirmation; actual experiments not yet reviewed",
}
if dry["ready"]:
    result = convert_na_coordinates(point_data, declaration, approval)
    # result['points'] 是新记录；result['xy_points'] 是 (Δx或x, V) 原序坐标。
    # result['provenance'] 保留公式、F、完整声明、确认记录和输入hash。
```

approval 参数记录已经完成的具体科学确认，不触发新的权限审批。用户确认实际输入及参照后即可直接调用；输入或声明变动需对应新的核对记录，hash 用于避免把旧确认错误套到另一组数据。

独立函数不自动回写或投入 `render`。后续绘图时，使用结果新表或明确的内存转换层，并把转换provenance完整附上。正式处理入口及标准结果导出见[处理命令](processing-cli.md)；正式GCD输入方言和原生样式沿用现有契约。

## 分子式计算M与同一GCD输入接口

`plotting_core.domains.chemistry.formula_mass.calculate_formula_mass` 解析数字整数/小数计量、嵌套圆括号及中点水合物，例如 `Na0.67Mn0.8Ni0.1Ti0.1O2`、`Na3V2(PO4)3`、`CuSO4·5H2O`。用户提供哪一个参考化学式单位，就按该单位逐元素求和，不归一到另一个化学式或把名义Na改成容量算得的Na。输出包括原式、element_counts、每个元素的质量贡献、M及表版本/source/hash。

Unicode下标数字会明确规范为对应ASCII数字，并同时保留原式。`CuSO4.5H2O`这类ASCII点既可能表示小数计量又可能表示水合物，需改用明确中点或括号；带数字前导系数的中点段只直接支持明确的H2O水合段，其他加合物先确认计数方式，避免把`·13C`误当13个C而遗漏同位素歧义。`ready`表示这一次分子式本身可解析；若复用已有ValidationReport，还须检查该报告是否另有阻塞问题。

质量表采用 **CIAAW Abridged Standard Atomic Weights 2024**，含官方给出标准质量的84个元素，同时保留公布精度文本和不确定度；2024修订的Zr、Gd、Lu已包括。这里得到的是普通材料标准原子量对应的常规摩尔质量值，不是指定同位素的精确质量，也未独立核实样品组成。x/δ等变量、同位素标记、电荷、未知/大小写错误元素以及官方未给标准质量的元素，会集中询问，M返回空值；不会套旧表93.49或95.89。[CIAAW2024官方简表](https://www.ciaaw.org/abridged-atomic-weights.htm)

共享工作流 `gcd.na_workflow.preflight_gcd_na(data, settings)` 接收**现有GCD入口产出的 NormalizedData**，没有新增Na专用原始表格式。先按现有标准GCD长表读入比容量–电压，再按sample/cycle/branch定位系列；容量在X或Y由现有capacity_voltage/voltage_capacity绑定确定。preflight只计算公式M并检查来源和参照，不计算Na坐标。

当前任务明确授权相应分支身份后，同圈放电起点接到**同样品、同圈充电的最后有效数值点所算Δx或x**，保留该点的原坐标、索引、exact source row及计算后坐标；不会选最大容量、另一样品或另一圈。计算内部先解决charge依赖，即使输入系列先列discharge，输出仍保持原系列和点的顺序。绝对x每圈charge缺已知x_ref仍提问；不默认跨圈累积。充电初始Δx、Q_ref及其来源仍需明确，示例里的共同0不能充当绝对x。

每个放电分支还需在`reference_state="same_cycle_discharge_start"`及`reference_source`中明确首个提供点就是该圈实际放电起点；Q_ref须等于这个点的原始比容量。该容量可为非零，流程只使用Q−Q_ref而不改写原容量。若提供的是截断区间、起点身份未知，或Q_ref不一致，preflight集中提问并阻塞，不能把charge终点强行赋给另一容量状态。

```python
from plotting_core.domains.electrochemistry.gcd.na_workflow import (
    preflight_gcd_na, convert_gcd_na,
)

# gcd_data 是现有 load_normalized_data(gcd_spec) 返回的标准GCD对象。
# 以下全部是合成声明，仅演示配置；实际样品式尚待用户提供。
settings = {
    "output": "delta_x",
    "samples": {"A": {
        "formula": "Na0.67Mn0.8Ni0.1Ti0.1O2",
        "formula_source": "synthetic supplied formula",
        "assumptions": {
            "reaction": "stoichiometric_na_intercalation", "electrons_per_na": 1,
            "source": "synthetic declared applicability", "parasitic_charge": "unknown",
        },
        "mass_normalization": {"basis": "active_material", "source": "synthetic explicit mass basis"},
    }},
    "per_series": {
        "A_C1_charge": {
            "direction_sign": -1, "source": "synthetic signed relation",
            "reference_capacity_mAh_g": 0.0, "reference_source": "synthetic Q reference state",
            "reference_delta_x": 0.0, "reference_delta_x_source": "synthetic common initial delta origin",
        },
        "A_C1_discharge": {
            "direction_sign": 1, "source": "synthetic signed relation",
            "reference_capacity_mAh_g": 0.0, "reference_source": "synthetic discharge-start Q state",
            "reference_state": "same_cycle_discharge_start",  # 确认首个提供点为实际放电起点
            # Δx或绝对x偏移由同sample同cyclecharge末点取，不重复填写旧舍入偏移。
        },
    },
}
dry = preflight_gcd_na(gcd_data, settings)
# 实际数据/公式/科学参照核对完成后记录既有确认；这里未批准真实Na数据。
confirmation = {"user_approved": True, "reviewed_input_sha256": dry["input_sha256"],
                "evidence": "synthetic confirmation; actual formulas/references pending"}
if dry["ready"]:
    na_data = convert_gcd_na(gcd_data, settings, confirmation)
    # na_data是新的标准GCD对象；gcd_data及Excel不变，所有转换记录保留在metadata/source。
```

若已有手填的放电偏移与同圈charge精确终点矛盾，流程会报告冲突，不能静默覆盖。处理非有限点、重复的sample/cycle/branch身份或缺charge来源时，整个转换阻塞；不会删点来制造连续曲线。

## 公开版科学参照

公开包不附带私人换算工作表或旧偏移。示例化学式、容量和参照不能替代当前任务声明。公开版要求明确提供质量基准及来源，缺失时阻塞。

放电接精确充电末点须满足同样品、同圈/配对组及分支起点身份声明；不得把人工配对组号当成实测圈次。负 Δx 或放电末段正值保持计算原值，不裁零、不取绝对值。绝对 x 另需明确 x_ref。
