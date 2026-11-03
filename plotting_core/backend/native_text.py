"""Origin native text font state through documented Page/selected interfaces.

Graphic Objects documents ``s.bold``; it does not document ``xb.bold``.
Page ``-s Name`` selects one object; Page ``-s`` clears the selection. Text,
font family, font size, SVG and images are never rewritten by this adapter.
"""

import math
import re
from typing import Dict, Optional


def text_lines(value: str):
    """Canonicalize only Origin's line-separator serialization, keeping markup."""
    return str(value).replace("\\n", "\n").replace("\r\n", "\n").strip().split("\n")


def expected_text_lines(semantic_text: str, bold: Optional[bool] = None):
    """Derive exact expected native text from independently planned content.

    Origin 2024's selected-bold setter serializes each line as ``\\b(line)``.
    Accept exactly that expected wrapper when bold is explicitly true. Never
    strip arbitrary formatting or derive the scientific expectation from a read.
    """
    if bold is not None and not isinstance(bold, bool):
        raise ValueError("expected native text bold must be a boolean or null")
    lines = text_lines(semantic_text)
    return ["\\b(%s)" % line for line in lines] if bold is True else lines


def read_native_text_bold(origin, name: str, expected: Optional[bool] = None) -> Dict:
    """Read actual named-object bold; clear selection even on a failed read."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ValueError("native text object name must be a LabTalk identifier")
    if expected is not None and not isinstance(expected, bool):
        raise ValueError("expected native text bold must be a boolean or null")
    if origin.value("%s.type" % name) != 0:
        raise RuntimeError("Origin object %s is not a readable native text object" % name)
    origin.run("page -s %s;" % name)
    try:
        value = float(origin.value("s.bold"))
        if not math.isfinite(value) or value not in (0.0, 1.0):
            raise RuntimeError("Origin returned invalid %s selected bold state: %r" % (name, value))
        font = float(origin.value("%s.font" % name))
        size = float(origin.value("%s.fsize" % name))
        if not math.isfinite(font) or not math.isfinite(size) or size <= 0:
            raise RuntimeError("Origin returned invalid %s font family/point size" % name)
        state = {"object": name, "bold": bool(value), "native_bold": value,
                 "font": font, "font_size_pt": size,
                 "method": "page -s named object + selected s.bold"}
        if expected is not None:
            state.update(expected_bold=expected, bold_equal=bool(value) == expected)
            if not state["bold_equal"]:
                raise RuntimeError("native %s bold differs: expected %d, read %d" %
                                   (name, int(expected), int(value)))
        return state
    finally:
        origin.run("page -s;", expect=False)


def apply_native_text_bold(origin, name: str, value: Optional[bool]) -> Optional[Dict]:
    """Apply only configured native bold and verify font/point size preservation."""
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("native text bold must be a boolean or null")
    before = read_native_text_bold(origin, name)
    origin.run("page -s %s;" % name)
    try:
        origin.run("s.bold=%d;" % int(value))
    finally:
        origin.run("page -s;", expect=False)
    after = read_native_text_bold(origin, name, expected=value)
    if after["font"] != before["font"] or after["font_size_pt"] != before["font_size_pt"]:
        raise RuntimeError("native bold changed %s font family or point size" % name)
    return after
