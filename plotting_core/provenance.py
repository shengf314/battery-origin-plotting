"""Summarise declaration completeness without certifying supplied scientific values.

This module is deliberately independent of graph adapters and Origin. Its only
states are ``declared`` and ``unknown``; declared means a record was supplied.
"""


def _string(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() != "unknown"


def _status(value, kind):
    if _string(value):
        return "declared"
    if isinstance(value, dict) and value.get("status") == "declared":
        key = "name" if kind == "method" else "value"
        if _string(value.get(key)):
            return "declared"
    return "unknown"


def traceability_summary(data):
    """Return JSON-safe statuses, declarations and gaps; never mutate ``data``.

    ``data.source['traceability_gaps']`` may carry adapter-specific gap records
    with path/kind/reason. Full supplied records remain in source/series metadata.
    Missing method parameters are gaps, not a requirement to reanalyse results.
    """
    source = getattr(data, "source", {}) or {}
    if not isinstance(source, dict):
        source = {}
    semantics = source.get("semantics") or {}
    if not isinstance(semantics, dict):
        semantics = {}
    declarations, gaps = [], []
    seen = set()

    def gap(path, kind, reason):
        key = (path, kind, reason)
        if key not in seen:
            seen.add(key)
            gaps.append({"path": path, "kind": kind, "reason": reason})

    def declare(path, kind, value, record=None):
        status = _status(value, kind)
        entry = {"path": path, "kind": kind, "status": status}
        declarations.append(entry)
        if status == "unknown":
            reason = value.get("reason") if isinstance(value, dict) else None
            gap(path, kind, reason if _string(reason) else "No known historical %s record was supplied" % kind)
        if kind == "method":
            parameters = value.get("parameters") if isinstance(value, dict) else None
            if parameters is None and isinstance(record, dict):
                parameters = record.get("parameters")
            entry["parameters_status"] = "declared" if isinstance(parameters, dict) and bool(parameters) else "unknown"
            if entry["parameters_status"] == "unknown":
                gap(path + ".parameters", "parameters", "Historical method parameters were not supplied")

    declare("source.file", "source", source.get("file"))
    preprocessing = semantics.get("preprocessing")
    if isinstance(preprocessing, dict):
        declare("semantics.preprocessing.source", "source", preprocessing.get("source"))
        if "method" in preprocessing:
            declare("semantics.preprocessing.method", "method", preprocessing["method"], preprocessing)
        for key, record in sorted(preprocessing.items()):
            if not isinstance(record, dict) or key in ("source", "method", "parameters"):
                continue
            path = "semantics.preprocessing." + str(key)
            if "source" in record:
                declare(path + ".source", "source", record["source"])
            if "method" in record:
                declare(path + ".method", "method", record["method"], record)
    for key in ("radiation", "na_content"):
        record = semantics.get(key)
        if isinstance(record, dict) and "source" in record:
            declare("semantics.%s.source" % key, "source", record["source"])
    axes = [semantics.get(key) for key in ("x", "y")]
    uses_na = source.get("x_representation") == "na_content" or any(
        isinstance(axis, dict) and axis.get("quantity") in ("sodium_content", "na_content", "delta_na_content")
        for axis in axes)
    if uses_na:
        na = semantics.get("na_content")
        # Existing GCD contracts use reference/source; processed XY also declares
        # an explicit definition. Absence remains visible for legacy coordinates.
        if not isinstance(na, dict):
            gap("semantics.na_content", "coordinate_definition", "Supplied Na coordinates have no definition/reference provenance record")
        else:
            required = ("definition", "reference") if source.get("x_representation") != "na_content" else ("reference",)
            for key in required:
                if not _string(na.get(key)):
                    gap("semantics.na_content." + key, "coordinate_definition", "The Na %s is unknown" % key)
    for item in getattr(data, "series", []) or []:
        metadata = getattr(item, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        path = "series[%r]" % getattr(item, "series_id", "unknown")
        declare(path + ".source", "source", metadata.get("source", source.get("file")))
        if "method" in metadata or metadata.get("role") in ("processed", "derived", "fit", "background", "component"):
            declare(path + ".method", "method", metadata.get("method"), metadata)
    extra_gaps = source.get("traceability_gaps") or []
    if isinstance(extra_gaps, list):
        for entry in extra_gaps:
            if isinstance(entry, dict):
                gap(str(entry.get("path", "source")), str(entry.get("kind", "declaration")),
                    str(entry.get("reason", "An adapter-specific scientific declaration is unknown")))
    return {"status": "unknown" if gaps else "declared",
            "scientific_truth_verified": False,
            "scope": "declaration completeness only; supplied values are not scientifically verified",
            "declarations": declarations, "gaps": gaps}
