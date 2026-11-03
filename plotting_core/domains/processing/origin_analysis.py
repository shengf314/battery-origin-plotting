"""Explicit per-spectrum XRD formula plans, separate from rendering.

No import or render call performs analysis. Call execute with authorization on an
already connected dedicated OriginBackend only after scientific choices are set.
"""

import copy
import hashlib
import json
import math
import re
from pathlib import Path

from ...ingest.report import ValidationReport

DOCS = {"normalize": "https://docs.originlab.com/x-function/ref/normalize/"}


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _seal(plan):
    plan["plan_sha256"] = _fingerprint(plan)
    return plan


def _source(data, report):
    source = copy.deepcopy(data.source)
    filename = source.get("resolved_file") or source.get("file")
    digest = source.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        report.question("Processing requires the reader's source SHA256.")
    if not filename or not Path(filename).is_absolute() or not Path(filename).is_file():
        report.question("Processing requires an existing absolute source file path.")
    elif digest and hashlib.sha256(Path(filename).read_bytes()).hexdigest() != digest:
        report.error("The source file changed since normalized input was read.")
    source["resolved_file"] = str(filename) if filename else None
    return source


def _points(item, report, minimum):
    points = []
    for index, point in enumerate(item.points):
        if (len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v) for v in point)):
            report.error("%s point %d is not a finite numeric XY pair; no dropping is allowed."
                         % (item.series_id, index + 1))
        else:
            points.append([float(point[0]), float(point[1])])
    if len(points) < minimum:
        report.question("%s needs at least %d supplied points." % (item.series_id, minimum))
    if item.approved_skips:
        report.question("%s contains approved skipped rows; confirm a new complete processing input."
                        % item.series_id)
    return points


def build_xrd_normalization_plan(data, request):
    """Normalize each supplied background-subtracted spectrum by an explicit rule."""
    report = ValidationReport()
    request = copy.deepcopy(request or {})
    if not isinstance(request, dict):
        raise ValueError("XRD normalization request must be an object")
    unknown = set(request) - {"method", "background_subtracted", "background_source", "pdf_reference"}
    if unknown:
        report.error("Unsupported XRD normalization request field(s): %s" % sorted(unknown))
    source = _source(data, report)
    if data.plot_type != "xrd":
        report.question("XRD normalization requires supplied XRD normalized input, not an unrelated series.")
    method = request.get("method")
    if method not in ("max", "range", "range100"):
        report.question("Choose XRD normalization: max (Y/Ymax), range ([0,1]), or range100 ([0,100]).")
    if request.get("background_subtracted") is not True or not isinstance(request.get("background_source"), str) or not request["background_source"].strip():
        report.question("Confirm these spectra are already background-subtracted and give the processing/source record.")
    reference = request.get("pdf_reference")
    if not isinstance(reference, dict) or not isinstance(reference.get("requested"), bool):
        report.question("State whether a PDF diffraction reference is requested for this task.")
    elif reference["requested"]:
        if (reference.get("confirmed") is not True or not all(isinstance(reference.get(key), str) and reference[key].strip()
                                                             for key in ("reference_id", "source"))):
            report.question("Confirm this task's PDF reference identity and source; historical IDs are not auto-reused.")
    series = []
    for item in data.series:
        metadata = copy.deepcopy(item.metadata)
        if metadata.get("role") not in ("measurement", "processed"):
            report.question("%s is not a measured/background-subtracted spectrum; reference/fit/background roles must not be normalized here." % item.series_id)
        x, y = metadata.get("x") or {}, metadata.get("y") or {}
        if x.get("quantity") != "two_theta" or x.get("unit") != "degree" or y.get("quantity") != "intensity":
            report.question("%s requires explicit two_theta/degree and intensity semantics." % item.series_id)
        if (metadata.get("preprocessing") or {}).get("offset", {}).get("applied") is True:
            report.question("%s already has a vertical offset; normalization must use an unshifted supplied spectrum." % item.series_id)
        points = _points(item, report, 2)
        values = [p[1] for p in points]
        if values and method == "max" and max(values) <= 0:
            report.question("%s requires a positive nonzero maximum for max normalization." % item.series_id)
        if values and method in ("range", "range100") and min(values) == max(values):
            report.question("%s is constant; range normalization would divide by zero." % item.series_id)
        series.append(dict(series_id=item.series_id, sample=item.sample, cycle=item.cycle, branch=item.branch,
                           points=points, metadata=metadata, source_rows=metadata.get("source_rows"),
                           first_row=item.first_row, last_row=item.last_row, method=method))
    if not series:
        report.question("No XRD spectra were supplied.")
    report.raise_if_blocking("Origin XRD normalization")
    return _seal(dict(schema_version=1, operation="xrd_normalization", source=source, request=request,
                      x_unit="degree", result_y_unit="%" if method == "range100" else "1",
                      series=series, docs=copy.deepcopy(DOCS),
                      policy="explicit analysis only; preserve raw background-subtracted input; normalize each series independently"))


def _read_xy(backend, book, xcol, ycol, expected):
    backend.run("range processingY=[%s]Sheet1!col(%d); processingN=processingY.GetSize();" % (book, ycol))
    count = int(backend.value("processingN"))
    if count != expected:
        raise RuntimeError("Origin processing output point count %d != supplied %d; no dropping is allowed." % (count, expected))
    rows = backend.app.GetWorksheet("[%s]Sheet1" % book, 0, xcol - 1, expected - 1, ycol - 1)
    if len(rows) != expected:
        raise RuntimeError("Origin processing readback has a missing row.")
    try:
        points = [[float(row[0]), float(row[1])] for row in rows]
    except (TypeError, ValueError, IndexError) as exc:
        raise RuntimeError("Origin processing output includes a missing/non-numeric result; raw columns are retained.") from exc
    if any(not math.isfinite(v) for point in points for v in point):
        raise RuntimeError("Origin processing output includes nonfinite values; no filtering or dropping is allowed.")
    return points


def _put_xy(backend, book, xcol, points):
    backend.app.PutWorksheet("[%s]Sheet1" % book, points, 0, xcol - 1)


def _metadata(backend, book, xcol, ycol, xname, yname, xunit, yunit, record):
    sheet = backend.app.FindWorksheet("[%s]Sheet1" % book)
    for col, name, unit, dtype in ((xcol - 1, xname, xunit, 3), (ycol - 1, yname, yunit, 0)):
        column = sheet.Columns(col)
        column.LongName, column.Units, column.Type = name, unit, dtype
        column.Comments = json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def execute(backend, plan, *, authorized=False):
    """Apply one sealed XRD formula in a caller-owned independent Origin session.

    Old derivative/smoothing plans are unsupported, even when previously sealed
    and authorized. Reject operations before any backend access or native write.
    The caller owns connection, saving, reopening and graph acceptance.
    """
    if not isinstance(plan, dict) or plan.get("operation") != "xrd_normalization":
        raise ValueError("Only explicit XRD formula normalization is supported; rebuild an in-scope plan.")
    if authorized is not True:
        raise PermissionError("Explicit processing authorization is required before Origin normalization.")
    payload = copy.deepcopy(plan)
    digest = payload.pop("plan_sha256", None)
    if digest != _fingerprint(payload):
        raise ValueError("Processing plan changed; rebuild and reconfirm the XRD formula plan.")
    method = payload.get("request", {}).get("method")
    if method not in ("max", "range", "range100") or any(
            series.get("method") != method or any(key in series for key in ("smoothing", "post_smoothing"))
            for series in payload.get("series", [])):
        raise ValueError("Only max/range/range100 per-spectrum formulas are supported.")
    source = payload["source"]
    filename = source["resolved_file"]
    if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Source hash changed before Origin processing; rebuild from the source.")
    if backend.app is None:
        raise RuntimeError("The caller must connect a dedicated OriginBackend before processing.")
    backend.run("newbook;")
    book = backend.text("%H")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", book):
        raise RuntimeError("Origin returned an unsafe worksheet short name.")
    backend.run("wks.ncols=%d;" % (4 * len(payload["series"])))
    results, executed_commands = [], []
    for index, series in enumerate(payload["series"]):
        first = index * 4 + 1
        raw = copy.deepcopy(series["points"])
        count = len(raw)
        _put_xy(backend, book, first, raw)
        provenance = dict(operation=payload["operation"], source=source, plan_sha256=digest,
                          series_id=series["series_id"], sample=series["sample"], cycle=series.get("cycle"),
                          branch=series.get("branch"), source_rows=series.get("source_rows"),
                          first_row=series.get("first_row"), last_row=series.get("last_row"),
                          method=method, request=payload["request"], docs=payload["docs"],
                          origin_parameters=dict(method=method, scope="per_series"))
        raw_yunit = (series.get("metadata", {}).get("y") or {}).get("unit", "")
        _metadata(backend, book, first, first + 1, "two_theta", "intensity",
                  payload["x_unit"], raw_yunit, dict(provenance, stage="raw_input"))
        output_x, output_y = first + 2, first + 3
        iy = "[%s]Sheet1!(%d,%d)" % (book, first, first + 1)
        oy = "[%s]Sheet1!(%d,%d)" % (book, output_x, output_y)
        command = "normalize iy:=%s method:=%s oy:=%s;" % (iy, method, oy)
        backend.run(command)
        executed_commands.append(command)
        result = _read_xy(backend, book, output_x, output_y, count)
        if [p[0] for p in result] != [p[0] for p in raw]:
            raise RuntimeError("Origin normalization changed the physical X values/order; no acceptance.")
        values = [point[1] for point in raw]
        if method == "max":
            expected_y = [value / max(values) for value in values]
        else:
            minimum, span = min(values), max(values) - min(values)
            factor = 100. if method == "range100" else 1.
            expected_y = [(value - minimum) / span * factor for value in values]
        if any(not math.isclose(point[1], expected, rel_tol=1e-10, abs_tol=1e-12)
               for point, expected in zip(result, expected_y)):
            raise RuntimeError("Origin normalization differs from the declared per-spectrum formula.")
        _metadata(backend, book, output_x, output_y, "two_theta", "normalized_intensity",
                  payload["x_unit"], payload["result_y_unit"],
                  dict(provenance, stage="native_result", origin_command=command))
        raw_after = _read_xy(backend, book, first, first + 1, count)
        if raw_after != raw:
            raise RuntimeError("Origin normalization modified supplied input columns.")
        results.append(dict(series_id=series["series_id"], points=result, raw_points=raw_after,
                            columns=dict(raw_x=first, raw_y=first + 1, result_x=output_x, result_y=output_y),
                            metadata=provenance))
    if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != source["sha256"]:
        raise RuntimeError("Source file changed during Origin normalization.")
    return dict(origin_executed=True, data_verified=True, book=book, source=source, plan_sha256=digest,
                commands=executed_commands, series=results, saved_project_verified=False,
                notes=["Caller must save/reopen and verify the processing workbook before scientific use; no graph was rendered."])
