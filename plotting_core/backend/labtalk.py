"""Small helpers that build LabTalk statements."""

from typing import Iterable, Sequence


def quoted(path: str) -> str:
    """Path as LabTalk expects it: plain backslashes inside double quotes."""
    return str(path).rstrip("\\")


def color(rgb_hex: str) -> str:
    value = str(rgb_hex).lstrip("#")
    if len(value) != 6:
        raise ValueError("expected #RRGGBB, got %r" % rgb_hex)
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return "color(%d,%d,%d)" % (red, green, blue)


def width_value(width_pt: float) -> int:
    """Origin's documented ``set %C -w`` unit: points multiplied by 500."""
    if width_pt is None:
        raise ValueError("line width is not configured")
    return int(round(float(width_pt) * 500))


def number_list(values: Sequence[float]) -> str:
    parts = []
    for value in values:
        text = ("%.10f" % float(value)).rstrip("0").rstrip(".")
        parts.append("0" if text in ("", "-0") else text)
    return " ".join(parts)


def text_list(values: Iterable[str]) -> str:
    return " ".join(str(value) for value in values)
