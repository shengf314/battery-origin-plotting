"""Task workspace: deliverables in the task directory, work files in ``.tmp``."""

import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

# Deliverables every task must produce.  A run may record more (for example the
# SVG preview or a family-specific table); ``missing_core()`` reports what a run
# failed to deliver, so a new figure family never has to edit this list.
CORE_DELIVERABLES = ("opju", "svg", "png", "plot_spec.json", "export_check.json",
                     "README.md")


class TaskWorkspace:
    """Owns the directory layout and the cleanup policy.

    ``<output_root>/<task>/`` keeps only the task results; everything the render
    needs on the way (transferred worksheets, Origin export intermediates,
    previews, backend logs) lives in ``<task>/.tmp/`` and is removed after a
    successful run.  A failed run keeps ``.tmp`` for debugging.
    """

    def __init__(self, output_root: str, task_name: str):
        self.root = Path(output_root)
        self.task_name = task_name
        self.task_dir = self.root / task_name
        self.tmp_dir = self.task_dir / ".tmp"
        self._files: "OrderedDict[str, str]" = OrderedDict()

    def prepare(self) -> None:
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def start_attempt(self, run_id: str) -> None:
        """Keep failed intermediate evidence separate from a later attempt."""
        if not run_id or Path(run_id).name != run_id or run_id in (".", ".."):
            raise ValueError("run_id must be one nonempty path component")
        self.tmp_dir = self.task_dir / ".tmp" / run_id
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def stage(self, key: str, source: str, *, suffix: str = None) -> Path:
        """Move an exported file into the task directory under its final name."""
        source_path = Path(source)
        if not source_path.exists():
            raise FileNotFoundError("expected export missing: %s" % source)
        target = self.task_dir / (self.task_name + (suffix or source_path.suffix))
        if source_path.resolve() != target.resolve():
            shutil.move(str(source_path), str(target))
        return target

    def write(self, name: str, text: str) -> Path:
        target = self.task_dir / name
        target.write_text(text, encoding="utf-8")
        return target

    def record(self, key: str, path) -> Path:
        """Register one delivered artifact under its contract key."""
        target = Path(path)
        self._files[str(key)] = str(target)
        return target

    def files(self) -> Dict[str, str]:
        """Delivered artifacts in the order they were recorded."""
        return OrderedDict(self._files)

    def describe(self, files: Dict[str, str] = None) -> Dict[str, Dict]:
        """Per-key existence/size summary of the delivered artifacts."""
        described: Dict[str, Dict] = {}
        for key, value in (files or self._files).items():
            target = Path(value)
            described[key] = {"path": str(target), "exists": target.exists(),
                              "bytes": target.stat().st_size if target.exists() else 0}
        return described

    def missing_core(self, files: Dict[str, str] = None) -> List[str]:
        """Core deliverables this run has not recorded."""
        recorded = files if files is not None else self._files
        return [key for key in CORE_DELIVERABLES if key not in recorded]

    def clean_tmp(self) -> None:
        if self.tmp_dir.exists():
            self.tmp_dir.resolve().relative_to((self.task_dir / ".tmp").resolve())
            shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def contents(self) -> List[str]:
        return sorted(path.name for path in self.task_dir.iterdir())
