"""Copy a bundled synthetic workbook and emit a spec with absolute local paths.

Run from the skill root:
    python -X utf8 scripts/prepare_example.py --output-dir <new-task-directory>
This preparation uses only the standard library and does not start Origin.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


def prepare_example(output_dir, plot_type="gcd"):
    if plot_type not in ("gcd", "cycle_performance", "rate_capability"):
        raise ValueError("Choose gcd, cycle_performance or experimental rate_capability")
    destination = Path(output_dir).expanduser().resolve()
    # Keep task outputs outside the installed skill.
    try:
        destination.relative_to(SKILL_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("Choose an output directory outside the installed skill")
    destination.mkdir(parents=True, exist_ok=True)
    workbook = destination / (plot_type + "_input_example.xlsx")
    spec_path = destination / "plot_spec.json"
    if workbook.exists() or spec_path.exists():
        raise FileExistsError("Example files already exist; choose a new output directory")
    if plot_type == "rate_capability":
        source_spec = json.loads((SKILL_ROOT / "examples" / "plot_spec.json").read_text(encoding="utf-8"))
        shutil.copyfile(str(SKILL_ROOT / "examples" / "rate_input_example.xlsx"), str(workbook))
    else:
        if str(SKILL_ROOT) not in sys.path:
            sys.path.insert(0, str(SKILL_ROOT))
        from plotting_core.domains.processing.standard_export import write_standard_xlsx
        sample = "A_synthetic_example"
        source_spec = {
            "spec_version": 1, "plot_type": plot_type,
            "task_name": plot_type + "_input_synthetic_example",
            "data": {
                "kind": "excel_long" if plot_type == "gcd" else "excel_cycle_summary",
                "sheet": "Sheet1",
                "notes": ["Synthetic supplied values only; not experimental observations."]},
            "samples": [{"name": sample}], "backend": {"name": "origin"},
            "verification": {"level": 3, "reopen_project": True, "editability_probe": True}}
        if plot_type == "gcd":
            headers = ["Sample", "Cycle", "Branch", "Voltage(V)",
                       "Charge Specific Capacity(mAh/g)", "Discharge Specific Capacity(mAh/g)"]
            rows = [[sample, 1, "charge", voltage, capacity, None]
                    for capacity, voltage in ((0., 2.5), (30., 3.), (60., 4.))]
            rows += [[sample, 1, "discharge", voltage, None, capacity]
                     for capacity, voltage in ((0., 4.), (25., 3.), (50., 2.5))]
            source_spec["selection"] = {"mode": "all", "x_representation": "specific_capacity",
                                        "axis_binding": "capacity_voltage"}
            source_spec["labels"] = {"y": "Voltage (V)"}
        else:
            headers = ["Sample", "Cycle", "Discharge Specific Capacity(mAh/g)",
                       "Coulombic Efficiency(%)"]
            rows = [[sample, cycle, 100. - cycle, 98. + cycle / 10.]
                    for cycle in range(1, 6)]
            source_spec["data"]["semantics"] = {"ce_unit": "percent"}
            source_spec["overrides"] = {"plot_type": {"native_layout": {
                "enabled": True, "mode": "separated_bands"}}}
            source_spec["legend"] = {"mode": "entries", "layout": "paired_samples",
                                     "position": "bottom_left"}
        write_standard_xlsx(workbook, headers, rows)
    source_spec["data"]["file"] = str(workbook)
    source_spec["output_root"] = str(destination / "outputs")
    spec_path.write_text(json.dumps(source_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return spec_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--plot-type", choices=("gcd", "cycle_performance", "rate_capability"),
                        default="gcd", help="GCD is the stable default; rate_capability is experimental")
    args = parser.parse_args()
    print(str(prepare_example(args.output_dir, args.plot_type)))


if __name__ == "__main__":
    main()
