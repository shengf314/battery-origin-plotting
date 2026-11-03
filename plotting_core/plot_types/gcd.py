"""Compatibility forwarder: the GCD plan builder moved to the domain package.

Canonical module: :mod:`plotting_core.domains.electrochemistry.gcd.plan`.
"""

from ..domains.electrochemistry.gcd.plan import (DEFAULT_BAR,  # noqa: F401
                                                 DEFAULT_ENTRY_FORMAT, build_plan,
                                                 qa_checks, readme_lines, series_plan)

__all__ = ["DEFAULT_BAR", "DEFAULT_ENTRY_FORMAT", "build_plan", "qa_checks",
           "readme_lines", "series_plan"]
