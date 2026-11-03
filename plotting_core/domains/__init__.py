"""Domain packages: the science each figure family belongs to.

``core`` (the modules at the package root: models, config, pipeline, style,
export, backend, qa) knows nothing about cycles, branches or metrics.  Everything
that does lives under :mod:`plotting_core.domains`, so a new family - or a whole
new technique such as XRD - is added here and registered in
:mod:`plotting_core.registry`, without touching the generic layers.
"""
