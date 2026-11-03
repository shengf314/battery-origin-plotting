"""Locate the Node runtime used by the export-inspection assets.

Nothing here is bound to one machine.  The resolution order is:

1. explicit environment overrides - ``CODEX_NODE`` / ``NODE_EXE`` for the binary,
   ``CODEX_NODE_MODULES`` for the modules directory;
2. ``node`` (or ``node.exe``) on ``PATH``; packages in the skill's
   local ``node_modules`` directory, installed with ``npm install``;
3. the bundled Codex runtimes, searched under ``CODEX_RUNTIMES_DIR``,
   ``%LOCALAPPDATA%/OpenAI/Codex/runtimes`` and
   ``%USERPROFILE%/.cache/codex-runtimes``, each with an optional version
   directory (``<root>/<name>/dependencies/node/...``).

A discovered modules directory is only accepted when it actually contains
``sharp``, which the SVG preview and the PNG inspection need; a runtime that
cannot do the job is reported instead of half working.
"""

import glob
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REQUIRED_MODULE = "sharp"
DISCOVERY_ENV_KEYS = ("CODEX_RUNTIMES_DIR", "CODEX_RUNTIME_DIR")


def candidate_roots(env: Dict[str, str] = None) -> List[Path]:
    """Directories that may hold a bundled runtime, in priority order."""
    variables = dict(os.environ if env is None else env)
    roots: List[Path] = []
    for key in DISCOVERY_ENV_KEYS:
        value = variables.get(key)
        if value:
            roots.append(Path(value))
    local = variables.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "OpenAI" / "Codex" / "runtimes")
    profile = variables.get("USERPROFILE")
    if profile:
        roots.append(Path(profile) / ".cache" / "codex-runtimes")
    ordered: List[Path] = []
    for root in roots:
        if root not in ordered:
            ordered.append(root)
    return ordered


def _runtime_dirs(roots: List[Path]) -> List[Path]:
    """Each candidate runtime directory: the root itself and one level below it."""
    directories: List[Path] = []
    for root in roots:
        directories.append(root)
        directories.extend(Path(match) for match in sorted(glob.glob(str(root / "*"))))
    return directories


def find_node(env: Dict[str, str] = None) -> Optional[str]:
    variables = dict(os.environ if env is None else env)
    for key in ("CODEX_NODE", "NODE_EXE"):
        value = variables.get(key)
        if value and Path(value).exists():
            return value
    found = shutil.which("node") or shutil.which("node.exe")
    if found:
        return found
    for directory in _runtime_dirs(candidate_roots(variables)):
        for relative in ("dependencies/node/bin/node.exe", "dependencies/node/node.exe",
                         "dependencies/node/bin/node", "dependencies/node/node"):
            candidate = directory / relative
            if candidate.exists():
                return str(candidate)
    return None


def find_node_modules(env: Dict[str, str] = None, skill_root=None) -> Optional[str]:
    variables = dict(os.environ if env is None else env)
    explicit = variables.get("CODEX_NODE_MODULES")
    if explicit:
        candidate = Path(explicit)
        return str(candidate) if (candidate / REQUIRED_MODULE / "package.json").is_file() else None
    # A normal "npm install" in the downloaded skill must work without Codex's
    # private runtime bundles or machine-specific environment variables.
    local = Path(skill_root) if skill_root is not None else Path(__file__).resolve().parents[2]
    candidate = local / "node_modules"
    if (candidate / REQUIRED_MODULE / "package.json").is_file():
        return str(candidate)
    for directory in _runtime_dirs(candidate_roots(variables)):
        candidate = directory / "dependencies/node/node_modules"
        if (candidate / REQUIRED_MODULE).exists():
            return str(candidate)
    return None


def node_executable() -> Optional[str]:
    return find_node()


def node_modules() -> Optional[str]:
    return find_node_modules()


def describe() -> Dict[str, object]:
    """Diagnostics for troubleshooting and for the delivery documents."""
    roots = candidate_roots()
    return {"node": find_node(), "node_modules": find_node_modules(),
            "roots_searched": [str(root) for root in roots],
            "required_module": REQUIRED_MODULE}


def require(env=None, skill_root=None) -> Tuple[str, str]:
    """Return ``(node, node_modules)`` or raise with an actionable message."""
    node = find_node(env)
    modules = find_node_modules(env, skill_root=skill_root)
    if node and modules:
        return node, modules
    detail = describe()
    raise RuntimeError(
        "the JavaScript runtime used for SVG preview / PNG inspection was not found "
        "(node=%s, node_modules=%s); set CODEX_NODE and CODEX_NODE_MODULES to the "
        "runtime, or install Node and run npm install in the skill root "
        "(required module: '%s'). Searched: %s"
        % (detail["node"], detail["node_modules"], REQUIRED_MODULE,
           ", ".join(detail["roots_searched"]) or "<no candidate root>"))
