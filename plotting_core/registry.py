"""Plot-type registry: the single place that knows which plot types exist.

Every other module (``models``, ``config``, ``ingest``, ``plot_types``) asks this
registry instead of hard-coding family names.  A future domain skill (CV, EIS,
XRD) registers its ``ingest`` loader and its plan builder here; nothing else in
the generic layers has to change.

The modules are imported lazily, so the registry stays free of import cycles.
"""

import importlib
from typing import Dict, Tuple

# Excluded even when a legacy template or archived PlotSpec still names them.
RETIRED_PLOT_TYPES = ("dqdv", "xps")

# name -> {"ingest": dotted module (relative to this package), "plan": dotted module,
#          "domain": domain label, "data_kinds": input dialects this family accepts}
REGISTERED: Dict[str, Dict[str, str]] = {
    "gcd": {"ingest": "domains.electrochemistry.gcd.ingest",
            "plan": "domains.electrochemistry.gcd.plan",
            "domain": "electrochemistry",
            "data_kinds": ("excel_long",)},
    "cycle_performance": {"ingest": "domains.electrochemistry.cycle_performance.ingest",
                          "plan": "domains.electrochemistry.cycle_performance.plan",
                          "domain": "electrochemistry",
                          "data_kinds": ("excel_cycle_summary",)},
    "rate_capability": {"ingest": "domains.electrochemistry.rate_capability.ingest",
                        "plan": "domains.electrochemistry.rate_capability.plan",
                        "domain": "electrochemistry",
                        "data_kinds": ("excel_cycle_summary",)},
    "eis": {"ingest": "domains.electrochemistry.eis.ingest",
            "plan": "domains.electrochemistry.eis.plan", "domain": "electrochemistry",
            "data_kinds": ("excel_processed_series",)},
    "gitt": {"ingest": "domains.electrochemistry.gitt.ingest",
             "plan": "domains.electrochemistry.gitt.plan", "domain": "electrochemistry",
             "data_kinds": ("excel_processed_series",)},
    "xrd": {"ingest": "domains.characterization.xrd.ingest",
            "plan": "domains.characterization.xrd.plan", "domain": "characterization",
            "data_kinds": ("excel_processed_series",)},
    "icp": {"ingest": "domains.characterization.icp.ingest",
            "plan": "domains.characterization.icp.plan", "domain": "characterization",
            "data_kinds": ("excel_processed_series",)},
}

_CACHE: Dict[str, object] = {}

def names() -> Tuple[str, ...]:
    """Registered plot-type names, in registration order."""
    return tuple(REGISTERED.keys())


def is_registered(name: str) -> bool:
    return str(name) in REGISTERED


def domain_of(name: str) -> str:
    return _entry(name)["domain"]


def describe() -> Dict[str, Dict[str, str]]:
    return {key: dict(value) for key, value in REGISTERED.items()}


def data_kinds(name: str) -> Tuple[str, ...]:
    """Input dialects (``data.kind``) the family declares it can read."""
    return tuple(_entry(name).get("data_kinds") or ())


def all_data_kinds() -> Tuple[str, ...]:
    """Every declared dialect, in registration order (display/compatibility)."""
    out = []
    for name in names():
        for kind in data_kinds(name):
            if kind not in out:
                out.append(kind)
    return tuple(out)


def families_for_data_kind(kind: str) -> Tuple[str, ...]:
    return tuple(name for name in names() if kind in data_kinds(name))


def validate_data_kind(plot_type: str, kind: str) -> None:
    """Reject a dialect the family does not declare."""
    allowed = data_kinds(plot_type)
    if kind not in allowed:
        raise ValueError("%s does not accept data.kind %r (it reads %s)"
                         % (plot_type, kind,
                            ", ".join(allowed) if allowed else "no declared dialect"))


def ingest_module(name: str):
    """The input-contract module of a plot type (``load(spec, workbook, report)``)."""
    return _module(name, "ingest")


def plan_module(name: str):
    """The plan module of a plot type (``build_plan(spec, config, data)``)."""
    return _module(name, "plan")


def _entry(name: str) -> Dict[str, str]:
    if str(name) in RETIRED_PLOT_TYPES:
        raise ValueError("%s is outside battery-origin-plotting scope: this skill draws Excel values "
                         "and explicitly defined simple formulas; dQ/dV and XPS figures are excluded" % name)
    try:
        return REGISTERED[str(name)]
    except KeyError:
        raise ValueError("unsupported plot type: %s (registered: %s)"
                         % (name, ", ".join(names())))


def _module(name: str, kind: str):
    entry = _entry(name)
    key = "%s:%s" % (kind, entry[kind])
    if key not in _CACHE:
        _CACHE[key] = importlib.import_module("." + entry[kind], __package__)
    return _CACHE[key]
