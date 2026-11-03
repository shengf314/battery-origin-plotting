"""Stable intermediate data structures of the rendering pipeline.

These objects are the contract between data preparation, the plot-type logic
("what to draw"), the resolved visual style ("how it looks") and the drawing
backend ("how the program is driven").  They are deliberately small and
JSON-serialisable so that a task only has to produce a ``plot_spec.json``
instead of a new Python/PowerShell/JS script.

Priority of visual parameters (resolved in :mod:`plotting_core.config`):

    template global  <  template plot-type block  <  spec overrides

A value of ``None`` means "not configured" and never erases a configured value.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import copy
import json

from . import registry

# Display copy of the registered plot types; validation always asks the registry
# so a newly registered family is accepted without editing this module.
PLOT_TYPES = registry.names()
# Union of the dialects the registered families declare (see registry.data_kinds).
DATA_KINDS = registry.all_data_kinds()


def _clean(mapping: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drop ``None`` leaves so that "unconfigured" stays distinguishable."""
    if mapping is not None and not isinstance(mapping, dict):
        raise ValueError("PlotSpec object fields must be JSON objects, got %s" % type(mapping).__name__)
    if not mapping:
        return {}
    out = {}
    for key, value in mapping.items():
        if isinstance(value, dict):
            value = _clean(value)
        if value is not None:
            out[key] = value
    return out


@dataclass
class DataSource:
    """Where the plotting data comes from and how its columns are interpreted."""

    kind: str
    file: str
    sheet: Optional[str] = None
    field_map: Dict[str, str] = field(default_factory=dict)
    value_map: Dict[str, Dict[str, str]] = field(default_factory=dict)
    exclude_values: Dict[str, List[str]] = field(default_factory=dict)
    sample_column: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    semantics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "file": self.file,
            "sheet": self.sheet,
            "field_map": copy.deepcopy(self.field_map),
            "value_map": copy.deepcopy(self.value_map),
            "exclude_values": copy.deepcopy(self.exclude_values),
            "sample_column": self.sample_column,
            "notes": list(self.notes),
            "semantics": copy.deepcopy(self.semantics),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any],
                  plot_type: Optional[str] = None) -> "DataSource":
        if not isinstance(data, dict):
            raise ValueError("PlotSpec data must be a JSON object")
        kind = data.get("kind")
        if plot_type is None:
            # No family in scope: any declared dialect is acceptable.
            if kind not in DATA_KINDS:
                raise ValueError("data.kind must be one of %s" % (DATA_KINDS,))
        else:
            registry.validate_data_kind(plot_type, kind)
        if not data.get("file"):
            raise ValueError("data.file is required")
        return cls(
            kind=kind,
            file=str(data["file"]),
            sheet=data.get("sheet"),
            field_map=dict(data.get("field_map") or {}),
            value_map={k: dict(v) for k, v in (data.get("value_map") or {}).items()},
            exclude_values={k: list(v) for k, v in (data.get("exclude_values") or {}).items()},
            sample_column=data.get("sample_column"),
            notes=list(data.get("notes") or []),
            semantics=copy.deepcopy(data.get("semantics") or {}),
        )


@dataclass
class SeriesStyle:
    """Resolved per-series drawing style (values already in template units)."""

    line_width_pt: Optional[float] = None
    line_style: Optional[str] = None
    symbol_shape: Optional[str] = None
    symbol_size_pt: Optional[float] = None
    symbol_fill: Optional[str] = None
    symbol_edge_width_pt: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_width_pt": self.line_width_pt,
            "line_style": self.line_style,
            "symbol_shape": self.symbol_shape,
            "symbol_size_pt": self.symbol_size_pt,
            "symbol_fill": self.symbol_fill,
            "symbol_edge_width_pt": self.symbol_edge_width_pt,
        }


@dataclass
class SeriesSpec:
    """One logical XY series: what to draw, in original data order."""

    series_id: str
    points: List[Tuple[float, float]]
    sample: str
    cycle: Optional[int] = None
    branch: Optional[str] = None
    metric: Optional[str] = None
    color: Optional[str] = None          # '#RRGGBB', None = not configured
    style: SeriesStyle = field(default_factory=SeriesStyle)
    layer: int = 0
    y_axis: str = "left"                 # 'left' | 'right'; native Y/Y2 binding
    role: str = "data"                   # 'data' | 'native_marker' (both Origin plots)
    legend_entry: Optional[str] = None   # None = excluded from the legend
    marker_indices: List[int] = field(default_factory=list)
    plot_kind: Optional[str] = None      # explicit line/scatter/line_points; None keeps legacy
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_points(self) -> int:
        return len(self.points)

    def bounds(self) -> Dict[str, List[float]]:
        if not self.points:
            return {"x": [], "y": []}
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)]}

    def summary(self) -> Dict[str, Any]:
        return {
            "series_id": self.series_id,
            "sample": self.sample,
            "cycle": self.cycle,
            "branch": self.branch,
            "metric": self.metric,
            "role": self.role,
            "layer": self.layer,
            "y_axis": self.y_axis,
            "points": self.n_points,
            "markers": len(self.marker_indices),
            "color": self.color,
            "legend_entry": self.legend_entry,
            "first_point": list(self.points[0]) if self.points else None,
            "last_point": list(self.points[-1]) if self.points else None,
            "bounds": self.bounds(),
            "plot_kind": self.plot_kind,
            "metadata": copy.deepcopy(self.metadata),
        }


@dataclass
class AxisSpec:
    key: str
    label: Optional[str] = None
    from_: Optional[float] = None
    to: Optional[float] = None
    ticks: Optional[List[float]] = None
    tick_labels: Optional[List[str]] = None
    show_axis: bool = True
    show_ticks: bool = True
    show_tick_labels: bool = True
    tick_direction: Optional[str] = None
    tick_length_pt: Optional[float] = None
    thickness_pt: Optional[float] = None
    color: Optional[str] = None
    scale_type: Optional[str] = None     # scientific semantics, overrides style's linear default
    direction: str = "ascending"         # data order is never changed by this display setting
    label_dataset: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "from": self.from_,
            "to": self.to,
            "ticks": self.ticks,
            "tick_labels": self.tick_labels,
            "show_axis": self.show_axis,
            "show_ticks": self.show_ticks,
            "show_tick_labels": self.show_tick_labels,
            "tick_direction": self.tick_direction,
            "tick_length_pt": self.tick_length_pt,
            "thickness_pt": self.thickness_pt,
            "color": self.color,
            "scale_type": self.scale_type,
            "direction": self.direction,
            "label_dataset": self.label_dataset,
        }


@dataclass
class LabelSpec:
    """A text element placed by the pipeline (axis title, legend text, ...)."""

    name: str
    text: str
    size_pt: float
    rotation_deg: float = 0.0
    anchor: str = "layer_fraction"        # also 'layer_scale' | 'x_scale_y_fraction'
    position: Optional[Tuple[float, float]] = None
    align: str = "center_center"          # horizontal_vertical alignment of the box
    gap_mm: Optional[float] = None        # alternative placement relative to the layer
    role: str = "label"
    render: str = "outline"               # 'outline' | 'native'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "text": self.text,
            "size_pt": self.size_pt,
            "rotation_deg": self.rotation_deg,
            "anchor": self.anchor,
            "position": list(self.position) if self.position else None,
            "align": self.align,
            "gap_mm": self.gap_mm,
            "role": self.role,
            "render": self.render,
        }


@dataclass
class LegendSpec:
    """Legend semantics selected by the plot type / task."""

    mode: str = "entries"                 # 'entries' | 'grouped' | 'cycle_gradient_bar'
    entries: List[str] = field(default_factory=list)
    grouped: Dict[str, Any] = field(default_factory=dict)
    bar: Dict[str, Any] = field(default_factory=dict)
    excluded_series: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "entries": list(self.entries),
            "grouped": copy.deepcopy(self.grouped),
            "bar": copy.deepcopy(self.bar),
            "excluded_series": list(self.excluded_series),
        }


@dataclass
class PlotSpec:
    """Complete, self-contained description of one figure to render."""

    task_name: str
    plot_type: str
    data: DataSource
    style_template: str
    selection: Dict[str, Any] = field(default_factory=dict)
    samples: List[Dict[str, Any]] = field(default_factory=list)
    labels: Dict[str, Any] = field(default_factory=dict)
    legend: Dict[str, Any] = field(default_factory=dict)
    axis_set: Optional[str] = None
    overrides: Dict[str, Any] = field(default_factory=dict)
    approvals: List[str] = field(default_factory=list)
    backend: Dict[str, Any] = field(default_factory=dict)
    export: Dict[str, Any] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)
    output_root: str = "outputs"
    spec_version: int = 1

    # ---------------------------------------------------------------- helpers
    @property
    def backend_name(self) -> str:
        return str(self.backend.get("name") or "origin")

    def axis_label_overrides(self) -> Dict[str, str]:
        return {k: v for k, v in (self.labels or {}).items() if isinstance(v, str)}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec_version": self.spec_version,
            "task_name": self.task_name,
            "plot_type": self.plot_type,
            "output_root": self.output_root,
            "data": self.data.to_dict(),
            "selection": copy.deepcopy(self.selection),
            "samples": copy.deepcopy(self.samples),
            "labels": copy.deepcopy(self.labels),
            "legend": copy.deepcopy(self.legend),
            "axis_set": self.axis_set,
            "overrides": copy.deepcopy(self.overrides),
            "approvals": list(self.approvals),
            "style_template": self.style_template,
            "backend": copy.deepcopy(self.backend),
            "export": copy.deepcopy(self.export),
            "verification": copy.deepcopy(self.verification),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlotSpec":
        if not isinstance(data, dict):
            raise ValueError("PlotSpec must be a JSON object")
        for key in ("selection", "labels", "legend", "overrides", "backend", "export", "verification"):
            if key in data and data[key] is not None and not isinstance(data[key], dict):
                raise ValueError("PlotSpec.%s must be a JSON object" % key)
        plot_type = data.get("plot_type")
        if not registry.is_registered(plot_type):
            raise ValueError("plot_type must be one of %s" % (registry.names(),))
        if not data.get("task_name"):
            raise ValueError("task_name is required")
        spec = cls(
            task_name=str(data["task_name"]),
            plot_type=plot_type,
            data=DataSource.from_dict(data.get("data") or {}, plot_type=plot_type),
            style_template=str(data.get("style_template")
                               or "templates/publication_visual_template.yaml"),
            selection=_clean(data.get("selection") or {}),
            samples=list(data.get("samples") or []),
            labels=_clean(data.get("labels") or {}),
            legend=_clean(data.get("legend") or {}),
            axis_set=(str(data["axis_set"]) if data.get("axis_set") else None),
            overrides=_clean(data.get("overrides") or {}),
            approvals=[str(a) for a in (data.get("approvals") or [])],
            backend=_clean(data.get("backend") or {}),
            export=_clean(data.get("export") or {}),
            verification=_clean(data.get("verification") or {}),
            output_root=str(data.get("output_root") or "outputs"),
            spec_version=int(data.get("spec_version") or 1),
        )
        return spec

    @classmethod
    def from_json(cls, text: str) -> "PlotSpec":
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_file(cls, path: str) -> "PlotSpec":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_json(handle.read())


@dataclass
class LayerPlan:
    """One Origin graph layer: its axes and the series drawn on it."""

    index: int
    series_ids: List[str] = field(default_factory=list)
    axes: Dict[str, AxisSpec] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "series_ids": list(self.series_ids),
            "axes": {k: v.to_dict() for k, v in self.axes.items()},
        }


@dataclass
class RenderingPlan:
    """Backend-agnostic description produced by a plot type."""

    plot_type: str
    graph_name: str
    series: List[SeriesSpec] = field(default_factory=list)
    layers: List[LayerPlan] = field(default_factory=list)
    labels: List[LabelSpec] = field(default_factory=list)
    legend: LegendSpec = field(default_factory=LegendSpec)
    page: Dict[str, Any] = field(default_factory=dict)
    worksheet: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @property
    def data_series(self) -> List[SeriesSpec]:
        return [s for s in self.series if s.role == "data"]

    def total_points(self) -> int:
        return sum(s.n_points for s in self.series)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plot_type": self.plot_type,
            "graph_name": self.graph_name,
            "page": copy.deepcopy(self.page),
            "worksheet": copy.deepcopy(self.worksheet),
            "legend": self.legend.to_dict(),
            "layers": [layer.to_dict() for layer in self.layers],
            "labels": [label.to_dict() for label in self.labels],
            "series": [s.summary() for s in self.series],
            "total_points": self.total_points(),
            "notes": list(self.notes),
        }


def series_from_pairs(series_id: str, pairs: Sequence[Sequence[float]], **kwargs: Any) -> SeriesSpec:
    """Small helper: build a SeriesSpec from plain ``(x, y)`` pairs."""
    return SeriesSpec(series_id=series_id,
                      points=[(float(p[0]), float(p[1])) for p in pairs],
                      **kwargs)
