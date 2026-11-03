"""Compatibility forwarder: the Cycle Performance plan builder moved to the domain.

Canonical module: :mod:`plotting_core.domains.electrochemistry.cycle_performance.plan`.
"""

from ..domains.electrochemistry.cycle_performance.plan import (build_plan,  # noqa: F401
                                                               qa_checks, readme_lines)

__all__ = ["build_plan", "qa_checks", "readme_lines"]
