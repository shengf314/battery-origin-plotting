"""Natural native major-increment selection.

Origin renders the tick marks and numeric strings.  This module only chooses a
reasonable increment when a template requests ``major_interval: auto``.
"""

import math
from typing import Dict, List, Optional


def _tick_values(low: float, high: float, step: float) -> List[float]:
    start = math.ceil(low / step - 1e-10)
    end = math.floor(high / step + 1e-10)
    if end - start > 10000:
        raise ValueError("Too many explicit ticks")
    return [i * step for i in range(start, end + 1)]


def nice_ticks(low: float, high: float, interval: Optional[float] = "auto",
               target: int = 5) -> Dict[str, object]:
    """Choose a natural interval inside existing bounds, without changing bounds."""
    if not math.isfinite(low) or not math.isfinite(high) or low >= high:
        raise ValueError("Need finite, nondegenerate axis bounds")
    if interval != "auto":
        if isinstance(interval, bool) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("Invalid explicit interval")
        return dict(interval=interval, ticks=_tick_values(low, high, interval))
    exponent = math.floor(math.log10((high - low) / max(target - 1, 1)))
    candidates = []
    for e in range(exponent - 1, exponent + 2):
        for base in (1, 2, 2.5, 5):
            step = base * 10 ** e
            ticks = _tick_values(low, high, step)
            candidates.append((not 4 <= len(ticks) <= 6, abs(len(ticks) - target), step, ticks))
    _, _, step, ticks = min(candidates, key=lambda c: c[:3])
    return dict(interval=step, ticks=ticks)
