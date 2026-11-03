"""Sample naming: the Sample column first, filename fallback only when approved."""

import re
from typing import Dict, Iterable, Optional, Sequence

_SUFFIX = re.compile(
    r"(?:[_ -]+)(?P<suffix>"
    r"cycle[_ -]?performance|rate[_ -]?performance|dq[_ -]?dv|"
    r"gcd|cycling|cycle|cv|eis|rate|"
    r"\d+cycles|cycle\d+|"
    r"\d+(?:\.\d+)?(?:degc|°c|c)|c(?:[_/-]?)\d+(?:\.\d+)?"
    r")$", re.IGNORECASE)


def filename_sample(filename: str, *, single_sample: bool,
                    ambiguous_suffixes: Iterable[str] = ()) -> Dict:
    """Return a candidate name from a filename; never infer row groups."""
    if not single_sample:
        return dict(status="needs_confirmation", name=None, removed=[])
    stem = re.sub(r"\.(?:xlsx|xlsm|xls|csv)$", "", filename.strip(), flags=re.I)
    removed = []
    ambiguous = {s.casefold() for s in ambiguous_suffixes}
    while True:
        match = _SUFFIX.search(stem)
        if match is None:
            break
        if match.group("suffix").casefold() in ambiguous:
            return dict(status="needs_confirmation", name=None, removed=removed)
        removed.append(match.group("suffix"))
        stem = stem[:match.start()].rstrip()
    if not stem or re.fullmatch(r"[\W\d_]+", stem):
        return dict(status="needs_confirmation", name=None, removed=removed)
    return dict(status="candidate", name=stem, removed=removed)


def sample_names(sample_values: Optional[Sequence], *, filename: str,
                 single_sample: bool) -> Dict:
    """``None`` means the column is absent; an empty existing column needs a name."""
    if sample_values is None:
        return filename_sample(filename, single_sample=single_sample)
    values = [str(value).strip() if value is not None else "" for value in sample_values]
    if not values or not all(values):
        return dict(status="needs_confirmation", name=None, removed=[])
    return dict(status="sample_column", names=list(dict.fromkeys(values)))


def display_name(spec_sample: Optional[str], report, *, filename: str,
                 single_sample: bool, ambiguous_suffixes: Iterable[str] = ()) -> str:
    """Resolve the display name of a single-sample input."""
    if spec_sample:
        return spec_sample
    resolved = filename_sample(filename, single_sample=single_sample,
                               ambiguous_suffixes=ambiguous_suffixes)
    if resolved["status"] != "candidate":
        report.question("the sample display name cannot be derived from the filename "
                        "%r; provide it explicitly" % filename)
        return "sample"
    return resolved["name"]
