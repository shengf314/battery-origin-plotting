"""Plot types: "what is drawn" - series construction, legend semantics, structure."""

from typing import Dict, List

from .. import registry
from ..ingest.normalize import NormalizedData
from ..models import PlotSpec, RenderingPlan
from . import cycle_performance, gcd, markers

# Compatibility view of the registry (same modules, looked up by name).
PLOT_TYPE_MODULES = {name: registry.plan_module(name) for name in registry.names()}

__all__ = ["build_plan", "cycle_performance", "gcd", "markers", "series_plan"]


def build_plan(spec: PlotSpec, config: Dict, data: NormalizedData) -> RenderingPlan:
    """Dispatch to the plan module the registry holds for this plot type."""
    return registry.plan_module(spec.plot_type).build_plan(spec, config, data)


def series_plan(family: str, points: List, config: Dict) -> Dict[str, List[int]]:
    """Compatibility helper: full line data plus marker display indices.

    A plot type may declare its own policy (``series_plan`` in its plan module);
    otherwise the shared marker-interval policy is used.  GCD declares that it
    never reads the marker interval, so the policy cannot leak across families.
    """
    if not registry.is_registered(family):
        raise ValueError("Unsupported plot family")
    module = registry.plan_module(family)
    own_policy = getattr(module, "series_plan", None)
    if own_policy is not None:
        return own_policy(points, config)
    return markers.marker_plan(points, config)


def readme_lines(plan: RenderingPlan, config: Dict) -> List[str]:
    """Visual-rule bullets of one figure for the task README.

    The plot type owns the wording, so the document layer never asks which family
    it is writing about.  A family that has not declared the hook yet is reported
    as such instead of falling back to another family's text.
    """
    module = registry.plan_module(plan.plot_type)
    builder = getattr(module, "readme_lines", None)
    if builder is None:
        return ["- 视觉说明：图族 %s 尚未声明 README 片段，请在它的计划模块里实现 "
                "readme_lines()。" % plan.plot_type]
    return [str(line) for line in builder(plan, config)]
