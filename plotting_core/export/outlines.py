"""Text -> vector glyph outlines, through the reusable PowerShell asset.

The confirmed Origin 2024 defect is an overline drawn on exported text objects
that contain superscript characters.  Instead of writing a new script per task,
the pipeline renders such text once, as outlines, and places the result in the
overlay (see :mod:`plotting_core.export.overlay`).
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List

from ..config import SKILL_ROOT

SCRIPT = SKILL_ROOT / "scripts" / "render_text_outlines.ps1"


def render(items: Iterable[Dict], *, font_family: str, work_dir, request_name="text_outlines.request.json",
           result_name="text_outlines.result.json") -> Dict[str, Dict]:
    """Return ``{name: {path_d, width_pt, height_pt}}`` for the requested items."""
    wanted: List[Dict] = []
    seen = set()
    for item in items:
        key = (item["name"], item["text"], float(item["size_pt"]), float(item.get("rotation_deg") or 0))
        if key in seen:
            continue
        seen.add(key)
        wanted.append({"name": item["name"], "text": item["text"],
                       "size_pt": float(item["size_pt"]),
                       "rotation_deg": float(item.get("rotation_deg") or 0)})
    if not wanted:
        return {}
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    request_path = work / request_name
    result_path = work / result_name
    request_path.write_text(json.dumps({"font": font_family, "items": wanted,
                                        "out_json": str(result_path)},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
    if not SCRIPT.exists():
        raise FileNotFoundError("text outline asset missing: %s" % SCRIPT)
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-Request", str(request_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0 or not result_path.exists():
        raise RuntimeError("text outline generation failed: %s%s"
                           % (completed.stderr.decode("utf-8", "replace"),
                              completed.stdout.decode("utf-8", "replace")))
    payload = json.loads(result_path.read_text(encoding="utf-8-sig"))
    out = {}
    for item in payload.get("items", []):
        out[item["name"]] = {"path_d": item["path_d"],
                             "width_pt": float(item["width_pt"]),
                             "height_pt": float(item["height_pt"]),
                             "text": item["text"]}
    missing = [item["name"] for item in wanted if item["name"] not in out]
    if missing:
        raise RuntimeError("text outline generation returned no glyphs for %s"
                           % ", ".join(missing))
    return out
