"""Publication Plot Rendering Pipeline for battery GCD / Cycle Performance figures.

Stable entry point::

    from plotting_core import PlotSpec, render_plot

    spec = PlotSpec.from_json('plot_spec.json')
    result = render_plot(spec)

The pipeline separates three responsibilities that used to be mixed inside
per-task scripts:

* ``plot_types``  - what is drawn (series, grouping, legend semantics)
* ``style``       - how it looks (canvas, typography, axes, ticks, colors)
* ``backend``     - how the drawing program is driven (Origin LabTalk/COM)

``pipeline.py`` runs them in a fixed order and ``export`` verifies the result.
"""

__version__ = "1.0.0"

from .models import (  # noqa: F401
    AxisSpec,
    DataSource,
    LabelSpec,
    LegendSpec,
    PlotSpec,
    RenderingPlan,
    SeriesSpec,
    SeriesStyle,
)
from .pipeline import RenderResult, render_plot  # noqa: F401
from .ingest.report import InputContractError, ValidationReport  # noqa: F401

__all__ = [
    "AxisSpec",
    "DataSource",
    "InputContractError",
    "LabelSpec",
    "LegendSpec",
    "PlotSpec",
    "RenderResult",
    "RenderingPlan",
    "SeriesSpec",
    "SeriesStyle",
    "ValidationReport",
    "render_plot",
]
