"""Sample palette assignment and the confirmed per-cycle shading rule."""

from typing import Dict, Iterable, List, Optional, Sequence


def palette(config: Dict) -> List[str]:
    colors = (config.get("colors") or {}).get("sample_palette")
    if not colors:
        return []
    return [str(c) for c in colors]


def assign_sample_colors(samples: Sequence[str], config: Dict,
                         existing: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Assign palette colours in the given sample order; never cycle the palette."""
    colors = palette(config)
    mapping = dict(existing or {})
    used = set(mapping.values())
    for name in samples:
        if name in mapping:
            continue
        for color in colors:
            if color not in used:
                mapping[name] = color
                used.add(color)
                break
        else:
            raise ValueError(
                "sample palette is exhausted: %d sample(s) configured, %d requested; "
                "the palette must be extended explicitly, no rainbow is generated"
                % (len(colors), len(samples)))
    return mapping


def hex_to_rgb(color: str) -> tuple:
    value = str(color).strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("expected #RRGGBB colour, got %r" % color)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb: Iterable[float]) -> str:
    return "#%02X%02X%02X" % tuple(int(round(min(255.0, max(0.0, v)))) for v in rgb)


def cycle_colors(sample_color: str, cycles: Iterable[int], config: Dict) -> Dict[int, tuple]:
    """Map cycle number to interpolated RGB; data order is never changed.

    RGB = sample_RGB + (white - sample_RGB) * lightest_white_mix * t, where
    ``t`` is the relative position of the cycle inside the selected range.
    """
    rule = (config.get("colors") or {}).get("cycle_shading_rule") or {}
    if (rule.get("darkest_color"), rule.get("interpolation"), rule.get("color_space")) != (
            "sample_color", "linear", "RGB"):
        raise ValueError("Unsupported shading rule")
    mix = rule.get("lightest_white_mix")
    if mix is None or not 0 <= float(mix) <= 1:
        raise ValueError("Invalid white mix")
    mix = float(mix)
    rgb = hex_to_rgb(sample_color)
    cycle_list = list(cycles)
    if not cycle_list:
        return {}
    low, high = min(cycle_list), max(cycle_list)
    return {
        cycle: tuple(v + (255 - v) * mix * ((cycle - low) / (high - low) if high != low else 0)
                     for v in rgb)
        for cycle in cycle_list
    }
