"""Normalised plotting data: what the plot types consume, independent of Excel."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class NormalizedSeries:
    """One series, in original Excel row order."""

    sample: str
    points: List[Tuple[float, float]]
    cycle: Optional[int] = None
    branch: Optional[str] = None
    metric: Optional[str] = None
    first_row: Optional[int] = None
    last_row: Optional[int] = None
    approved_skips: List[int] = field(default_factory=list)
    explicit_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def series_id(self) -> str:
        if self.explicit_id:
            return self.explicit_id
        parts = [self.sample]
        if self.cycle is not None:
            parts.append("C%s" % self.cycle)
        if self.branch:
            parts.append(self.branch)
        if self.metric:
            parts.append(self.metric)
        return "_".join(str(part) for part in parts)

    def bounds(self) -> Dict[str, List[float]]:
        if not self.points:
            return {"x": [], "y": []}
        xs = [point[0] for point in self.points]
        ys = [point[1] for point in self.points]
        return {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)]}


@dataclass
class NormalizedData:
    """Everything the plot types need, plus the provenance of those numbers."""

    plot_type: str
    series: List[NormalizedSeries] = field(default_factory=list)
    sample_order: List[str] = field(default_factory=list)
    axes: Tuple[str, str] = ("x", "y")
    axis_labels: Dict[str, str] = field(default_factory=dict)
    excluded: Dict[str, int] = field(default_factory=dict)
    source: Dict[str, Any] = field(default_factory=dict)

    def series_for(self, sample: str, metric: Optional[str] = None) -> List[NormalizedSeries]:
        out = [item for item in self.series if item.sample == sample]
        if metric is not None:
            out = [item for item in out if item.metric == metric]
        return out

    def cycles(self) -> List[int]:
        return sorted({item.cycle for item in self.series if item.cycle is not None})

    def data_bounds(self, axis: str) -> Tuple[float, float]:
        index = 0 if axis == "x" else 1
        values = [point[index] for item in self.series for point in item.points]
        if not values:
            raise ValueError("no plotting points were produced")
        return (min(values), max(values))

    def summary(self) -> Dict[str, Any]:
        cycles = self.cycles()
        return {
            "plot_type": self.plot_type,
            "series": len(self.series),
            "samples": list(self.sample_order),
            "cycles": cycles,
            "points": sum(len(item.points) for item in self.series),
            "excluded": dict(self.excluded),
            "source": self.source,
        }
