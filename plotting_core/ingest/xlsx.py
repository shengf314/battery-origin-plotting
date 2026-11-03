"""Read-only, streaming access to the standard Excel input.

Implemented with ``zipfile`` + ``xml.etree`` so that a workbook with hundreds of
thousands of rows can be read without loading it into memory, and without any
library recalculating or rewriting the file.
"""

import re
from typing import Dict, Iterator, List, Optional, Tuple
from xml.etree.ElementTree import fromstring, iterparse
from zipfile import ZipFile

MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

CELL_REF = re.compile(r"([A-Z]+)(\d+)")


class Cell:
    """One worksheet cell: cached value plus how it was obtained."""

    __slots__ = ("value", "text", "formula", "cached")

    def __init__(self, value=None, text=None, formula=False, cached=True):
        self.value = value
        self.text = text
        self.formula = formula
        self.cached = cached

    @property
    def is_empty(self) -> bool:
        return self.value is None and not (self.text or "").strip()

    def __repr__(self):  # pragma: no cover - debugging helper
        return "Cell(%r, formula=%s, cached=%s)" % (self.value, self.formula, self.cached)


class Workbook:
    """Minimal xlsx reader: sheet inventory, header row and row streaming."""

    def __init__(self, path: str):
        self.path = str(path)
        self._zip = ZipFile(self.path)
        self._shared = self._read_shared_strings()
        self._sheets = self._read_sheet_index()

    # ------------------------------------------------------------------ sheets
    def _read_shared_strings(self) -> List[str]:
        if "xl/sharedStrings.xml" not in self._zip.namelist():
            return []
        root = fromstring(self._zip.read("xl/sharedStrings.xml"))
        return ["".join(item.itertext()) for item in root]

    def _read_sheet_index(self) -> List[Dict[str, str]]:
        workbook = fromstring(self._zip.read("xl/workbook.xml"))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in self._zip.namelist():
            rel_root = fromstring(self._zip.read("xl/_rels/workbook.xml.rels"))
            for rel in rel_root.findall(PKG_REL_NS + "Relationship"):
                rels[rel.get("Id")] = rel.get("Target")
        sheets = []
        for node in workbook.findall(MAIN_NS + "sheets/" + MAIN_NS + "sheet"):
            target = rels.get(node.get(REL_NS + "id"), "")
            if target:
                if target.startswith("/"):
                    target = target.lstrip("/")          # absolute part name
                elif not target.startswith("xl/"):
                    target = "xl/" + target              # relative to the workbook part
            sheets.append({
                "name": node.get("name"),
                "state": node.get("state") or "visible",
                "path": target,
                "sheet_id": node.get("sheetId"),
            })
        return sheets

    def sheet_names(self) -> List[str]:
        return [sheet["name"] for sheet in self._sheets]

    def sheet(self, name: str) -> Dict[str, str]:
        for sheet in self._sheets:
            if sheet["name"] == name:
                return sheet
        raise KeyError("worksheet not found: %s" % name)

    # -------------------------------------------------------------------- rows
    def _cell_value(self, cell) -> Cell:
        kind = cell.get("t")
        formula = cell.find(MAIN_NS + "f") is not None
        value_node = cell.find(MAIN_NS + "v")
        inline = cell.find(MAIN_NS + "is")
        if inline is not None:
            return Cell(text="".join(inline.itertext()), formula=formula)
        if value_node is None:
            return Cell(None, formula=formula, cached=not formula)
        raw = value_node.text
        if kind == "s":
            try:
                text = self._shared[int(raw)]
            except (TypeError, ValueError, IndexError):
                return Cell(None, formula=formula, cached=False)
            return Cell(text=text, formula=formula)
        if kind in ("str", "inlineStr"):
            return Cell(text=raw, formula=formula)
        if kind in ("e",):
            return Cell(text=raw, formula=formula)
        if kind == "b":
            return Cell(value=None, text=raw, formula=formula)
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return Cell(text=raw, formula=formula)
        return Cell(value=number, formula=formula)

    def rows(self, name: str, *, max_rows: Optional[int] = None,
             start_row: int = 1) -> Iterator[Tuple[int, Dict[str, Cell]]]:
        """Yield ``(row_number, {column_letter: Cell})`` in file order."""
        sheet = self.sheet(name)
        with self._zip.open(sheet["path"]) as handle:
            context = iterparse(handle, events=("end",))
            root = None
            emitted = 0
            for _, element in context:
                if root is None:
                    root = element
                if element.tag != MAIN_NS + "row":
                    continue
                row_number = int(element.get("r") or 0)
                if row_number >= start_row:
                    cells = {}
                    for cell in element:
                        if cell.tag != MAIN_NS + "c":
                            continue
                        ref = cell.get("r") or ""
                        match = CELL_REF.match(ref)
                        if match:
                            cells[match.group(1)] = self._cell_value(cell)
                    yield row_number, cells
                    emitted += 1
                    if max_rows is not None and emitted >= max_rows:
                        return
                element.clear()
                if root is not None:
                    root.clear()

    def has_content(self, name: str, probe_rows: int = 200) -> bool:
        """True when the sheet holds any value, text or formula."""
        for _, cells in self.rows(name, max_rows=probe_rows):
            for cell in cells.values():
                if cell.formula or not cell.is_empty:
                    return True
        return False

    def header(self, name: str, row_number: int = 1) -> Dict[str, str]:
        """Return ``{column_letter: header text}`` for the header row."""
        for number, cells in self.rows(name, start_row=row_number, max_rows=1):
            if number != row_number:
                continue
            return {
                letter: (cell.text if cell.text is not None else
                         ("" if cell.value is None else repr(cell.value)))
                for letter, cell in sorted(cells.items(), key=lambda kv: _column_index(kv[0]))
            }
        return {}

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "Workbook":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _column_index(letter: str) -> int:
    index = 0
    for char in letter:
        index = index * 26 + (ord(char) - 64)
    return index
