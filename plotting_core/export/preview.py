"""Render an exported SVG for the post-export visual check."""

import json
import subprocess
from pathlib import Path
from typing import Dict

from ..config import SKILL_ROOT
from . import runtime

RENDERER = SKILL_ROOT / "scripts" / "render_preview.cjs"


def render(svg_path: str, out_path: str, width_px: int, height_px: int) -> Dict:
    if not RENDERER.exists():
        raise RuntimeError("the SVG preview asset is missing: %s" % RENDERER)
    node, modules = runtime.require()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [node, str(RENDERER), str(svg_path), str(out_path), str(width_px),
         str(height_px), modules],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise RuntimeError("SVG preview rendering failed: %s"
                           % completed.stderr.decode("utf-8", "replace"))
    return json.loads(completed.stdout.decode("utf-8"))
