"""Compatibility facade for the pure visual helpers.  DEPRECATED - prefer plotting_core.

The implementations moved into ``plotting_core`` when the per-task scripts were
replaced by the Publication Plot Rendering Pipeline.  The public names and
signatures stay unchanged, so existing callers, references and tests keep
working:

===========================  =========================================
function                     module
===========================  =========================================
cycle_colors                 plotting_core.style.colors
nice_ticks                   plotting_core.style.ticks
resolve_axes                 plotting_core.style.axes
grouped_legend               plotting_core.style.legend
series_plan                  plotting_core.plot_types
filename_sample, sample_names  plotting_core.ingest.naming
===========================  =========================================

Regression scripts and audit artifacts are archived outside the installed
skill. This facade remains for existing callers; it has no runtime dependency
on those tests. New code must import from ``plotting_core``; do not add
functions here.
"""

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from plotting_core.ingest.naming import filename_sample, sample_names  # noqa: E402,F401
from plotting_core.plot_types import series_plan  # noqa: E402,F401
from plotting_core.style.axes import resolve_axes  # noqa: E402,F401
from plotting_core.style.colors import (  # noqa: E402,F401
    assign_sample_colors,
    cycle_colors,
    hex_to_rgb,
    palette,
    rgb_to_hex,
)
from plotting_core.style.legend import grouped_legend  # noqa: E402,F401
from plotting_core.style.ticks import nice_ticks  # noqa: E402,F401

__all__ = ["assign_sample_colors", "cycle_colors", "filename_sample", "grouped_legend",
           "hex_to_rgb", "nice_ticks", "palette", "resolve_axes", "rgb_to_hex",
           "sample_names", "series_plan"]
