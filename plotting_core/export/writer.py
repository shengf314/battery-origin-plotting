"""Unified export interface: naming, paths, formats and existence confirmation.

One place decides *which files* an export run produces and *where* they live, so
no plot type and no backend call site re-implements naming, the 600 dpi raster
option or the "did the file actually appear" check.  The backend keeps only the
mechanical statements that ask the drawing program to write the planned targets.
"""

from pathlib import Path
from typing import Dict, Optional

from ..config import export_settings

FORMATS = ("svg", "png", "opju")
DEFAULT_MINIMUM_BYTES = 1024


def plan_targets(work_dir, graph_name: str, *, svg: bool = True, png: bool = True,
                 project: Optional[str] = None) -> Dict:
    """Resolve the export targets of one figure.

    ``svg``/``png`` go to ``<work_dir>/_exports/``; the editable project is saved
    straight to its final location (Origin keeps the project open, so it cannot be
    moved afterwards).
    """
    directory = Path(work_dir) / "_exports"
    directory.mkdir(parents=True, exist_ok=True)
    files: Dict[str, str] = {}
    if png:
        files["png"] = str(directory / ("%s.png" % graph_name))
    if svg:
        files["svg"] = str(directory / ("%s.svg" % graph_name))
    if project:
        target = Path(project).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        files["opju"] = str(target)
    return {"directory": str(directory), "files": files}


def confirm(targets: Dict, *, minimum_bytes: int = DEFAULT_MINIMUM_BYTES) -> Dict[str, str]:
    """Fail loudly unless every planned export exists and carries content."""
    exports = dict((targets or {}).get("files") or {})
    missing = [key for key, path in exports.items() if not Path(path).exists()]
    if missing:
        raise RuntimeError("export file(s) were not written: %s"
                           % ", ".join("%s (%s)" % (key, exports[key]) for key in missing))
    empty = [key for key, path in exports.items()
             if Path(path).stat().st_size < minimum_bytes]
    if empty:
        raise RuntimeError("export file(s) are suspiciously small: %s"
                           % ", ".join("%s (%s)" % (key, exports[key]) for key in empty))
    return exports


def request_settings(config: Dict) -> Dict:
    """Effective export settings with the confirmed defaults (SVG + 600 dpi PNG)."""
    return export_settings(config)


def describe(exports: Dict[str, str]) -> Dict[str, Dict]:
    """Per-format existence/size summary for the delivery documents."""
    described: Dict[str, Dict] = {}
    for key, path in (exports or {}).items():
        target = Path(path)
        described[key] = {"path": str(target), "exists": target.exists(),
                          "bytes": target.stat().st_size if target.exists() else 0}
    return described
