"""Visual style layer: canvas, typography, axes, ticks, colors, legend, markers.

Everything here answers "how does it look".  It reads only the *resolved*
visual configuration (see :mod:`plotting_core.config`) and never touches data
semantics such as which cycle belongs to which colour.
"""

from . import axes, colors, layout, legend, ticks, typography  # noqa: F401

__all__ = ["axes", "colors", "layout", "legend", "ticks", "typography"]
