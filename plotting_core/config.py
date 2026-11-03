"""Visual configuration loading and priority resolution.

``templates/publication_visual_template.yaml`` stays the single source of the
confirmed visual parameters.  This module only *combines* configuration levels;
it never invents a value for a parameter that is not configured.

Priority (low to high)::

    1. template ``global`` / shared blocks      (canvas, axes, labels, colors, ...)
    2. template plot-type block                 (gcd.*, cycle_performance.*,
                                                 *.axes_override)
    3. spec ``overrides``                       (task-specific, recorded in plot_spec.json)

``None`` always means "not configured" and is skipped, so a null override never
erases a configured value (the documented legacy behaviour).
"""

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from . import registry

SKILL_ROOT = Path(__file__).resolve().parents[1]


def skill_path(*parts: str) -> Path:
    """Resolve a path inside the skill directory."""
    return SKILL_ROOT.joinpath(*parts)


def load_template(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the publication visual template (YAML)."""
    import yaml

    resolved = Path(path) if path else skill_path("templates", "publication_visual_template.yaml")
    if not resolved.is_absolute():
        candidate = skill_path(str(resolved))
        resolved = candidate if candidate.exists() else Path(path)
    if not resolved.exists():
        raise FileNotFoundError("visual template not found: %s" % resolved)
    with open(str(resolved), "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle.read())
    return data or {}


def merge(base: Any, override: Any) -> Any:
    """Recursive merge where ``None`` means 'not configured' and keeps ``base``."""
    if override is None:
        return deepcopy(base)
    if isinstance(base, dict) and isinstance(override, dict):
        result = deepcopy(base)
        for key, value in override.items():
            if value is None:
                continue
            result[key] = merge(result.get(key), value)
        return result
    return deepcopy(override)


def _require(template: Dict[str, Any], path: str) -> Any:
    node = template
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def resolve_axes(template: Dict[str, Any], family: str) -> Dict[str, Any]:
    """Shared ``axes`` plus the plot-type ``axes_override`` (non-null wins)."""
    if not registry.is_registered(family):
        raise ValueError("Unsupported plot family: %s" % family)
    shared = template.get("axes") or {}
    local = (template.get(family) or {}).get("axes_override") or {}
    merged = {key: value for key, value in shared.items() if value is not None}
    for key, value in local.items():
        if value is not None:
            merged[key] = value
    return merged


def resolve_config(template: Dict[str, Any], plot_type: str,
                   overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge the three configuration levels into the effective configuration."""
    if not registry.is_registered(plot_type):
        raise ValueError("Unsupported plot type: %s" % plot_type)
    plot_block = deepcopy(template.get(plot_type) or {})
    capabilities = list(plot_block.get("capabilities") or [])
    resolved = {
        key: deepcopy(value)
        for key, value in template.items()
        if key not in registry.names() and key not in registry.RETIRED_PLOT_TYPES
    }
    resolved["axes"] = resolve_axes(template, plot_type)
    resolved["plot_type"] = plot_block
    resolved["plot_type_name"] = plot_type
    resolved["capabilities"] = capabilities
    # A native single-layer double-Y graph is an opt-in capability.  Its
    # structural axis defaults are not merged into ordinary single-Y families.
    if "native_dual_y" in capabilities:
        dual_y = deepcopy(template.get("dual_y") or {})
        if not dual_y:
            raise ValueError("%s declares native_dual_y but template.dual_y is missing"
                             % plot_type)
        resolved["dual_y"] = dual_y
        resolved["axes"] = merge(resolved["axes"], dual_y.get("axes_override") or {})
    resolved = merge(resolved, overrides or {})
    _validate_config(resolved)
    return resolved


def _validate_config(config: Dict[str, Any]) -> None:
    """Fail loudly and early on configurations the pipeline cannot honour."""
    canvas = config.get("canvas") or {}
    for key in ("width", "height"):
        if not canvas.get(key):
            raise ValueError("canvas.%s is not configured" % key)
    margins = canvas.get("margins") or {}
    for key in ("left", "right", "top", "bottom"):
        if margins.get(key) is None:
            raise ValueError("canvas.margins.%s is not configured" % key)
    units = config.get("units") or {}
    for key in ("font_size", "line_width", "symbol_size", "canvas_size", "margin"):
        if not units.get(key):
            raise ValueError("units.%s is not configured" % key)
    labels = config.get("labels") or {}
    if labels.get("axis_title_font_size") is None:
        raise ValueError("labels.axis_title_font_size is not configured")
    if labels.get("tick_label_font_size") is None:
        raise ValueError("labels.tick_label_font_size is not configured")


def configured(config: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Read a dotted path from the resolved configuration."""
    value = _require(config, path)
    return default if value is None else value


def units(config: Dict[str, Any]) -> Dict[str, Any]:
    return config.get("units") or {}


def export_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Effective export settings (new fields win over the legacy ones)."""
    export = config.get("export") or {}
    primary = export.get("primary_format") or export.get("format") or "svg"
    secondary = export.get("secondary_format") or "png"
    dpi = export.get("raster_dpi") or export.get("dpi") or 600
    return {
        "primary_format": primary,
        "secondary_format": secondary,
        "raster_dpi": dpi,
        "background": export.get("background") or "white",
        "transparent_background": bool(export.get("transparent_background")),
        "preserve_vector": export.get("preserve_vector", True),
        "embed_fonts": export.get("embed_fonts", True),
        "save_editable_source": export.get("save_editable_source", True),
    }
