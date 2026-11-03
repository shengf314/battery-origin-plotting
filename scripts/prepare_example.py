"""Copy a bundled synthetic workbook and emit a spec with absolute local paths.

Run from the skill root:
    python -X utf8 scripts/prepare_example.py --output-dir <new-task-directory>
This preparation uses only the standard library and does not start Origin.
"""

import argparse
import json
import shutil
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


def prepare_example(output_dir):
    destination = Path(output_dir).expanduser().resolve()
    # Keep task outputs outside the installed skill.
    try:
        destination.relative_to(SKILL_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("Choose an output directory outside the installed skill")
    destination.mkdir(parents=True, exist_ok=True)
    workbook = destination / "rate_input_example.xlsx"
    spec_path = destination / "plot_spec.json"
    if workbook.exists() or spec_path.exists():
        raise FileExistsError("Example files already exist; choose a new output directory")
    source_spec = json.loads((SKILL_ROOT / "examples" / "plot_spec.json").read_text(encoding="utf-8"))
    source_spec["data"]["file"] = str(workbook)
    source_spec["output_root"] = str(destination / "outputs")
    shutil.copyfile(str(SKILL_ROOT / "examples" / "rate_input_example.xlsx"), str(workbook))
    spec_path.write_text(json.dumps(source_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return spec_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(str(prepare_example(args.output_dir)))


if __name__ == "__main__":
    main()
