"""Origin backend: drives the Origin programmatic interface (LabTalk via COM).

Only this module knows *how* the drawing program is driven.  It receives a
backend-agnostic :class:`~plotting_core.models.RenderingPlan` plus the resolved
visual configuration, and produces the Origin project, the SVG and the 600 dpi
PNG.  Every geometry decision comes from the plan and the configuration, so no
figure-specific code has to be written per task.
"""

import time
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .. import export as export_pkg
from ..models import RenderingPlan, SeriesSpec
from ..export import writer as export_writer
from ..style import layout as layout_style
from ..style import typography
from . import axis as origin_axis, labtalk


class OriginNotAvailable(RuntimeError):
    """Raised when the Origin COM interface cannot be started."""


class OriginBackend:
    """A dedicated, hidden Origin instance used for one figure."""

    name = "origin"

    def __init__(self, visible: bool = False, connect_timeout: float = 120.0):
        self.visible = visible
        self.connect_timeout = connect_timeout
        self.app = None
        self.graph_name: Optional[str] = None
        self.book_name: Optional[str] = None
        self.log: List[str] = []
        self.owned_pids: List[int] = []
        self.width_overrides_failed = False

    # ------------------------------------------------------------- lifecycle
    def connect(self) -> None:
        self._pids_before = _origin_pids()
        try:
            import win32com.client
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise OriginNotAvailable("pywin32 is required to drive Origin: %s" % exc)
        try:
            self.app = win32com.client.DispatchEx("Origin.Application")
        except Exception as exc:  # pragma: no cover - environment dependent
            raise OriginNotAvailable(
                "the Origin COM interface could not be started (%s); Origin has to be "
                "installed and able to run outside the sandbox" % exc)
        for _ in range(20):
            self.owned_pids = [pid for pid in _origin_pids()
                               if pid not in self._pids_before]
            if self.owned_pids:
                break
            time.sleep(0.5)
        self.app.Visible = 1 if self.visible else 0
        deadline = time.time() + self.connect_timeout
        while time.time() < deadline:
            try:
                # A COM call can return false while Origin is still starting,
                # without raising. Require a round-trip before mutating pages.
                ready = self.app.Execute("originSkillReady=314159;")
                if ready and self.app.LTVar("originSkillReady") == 314159:
                    break
                time.sleep(1.0)
            except Exception:
                time.sleep(1.0)
        else:
            raise OriginNotAvailable("Origin did not become responsive")

    def disconnect(self) -> None:
        if self.app is None:
            return
        try:
            self.app.IsModified = False
            self.app.Exit()
        except Exception:
            pass
        self.app = None
        time.sleep(0.5)
        # Do not force-kill PID differences: another application could launch
        # Origin during startup. Exit only the COM session created by DispatchEx.
        self.owned_pids = []

    def run(self, statement: str, expect: bool = True) -> bool:
        """Execute a LabTalk statement and record it in the backend log."""
        if self.app is None:
            raise OriginNotAvailable("Origin session is not connected")
        result = self.app.Execute(statement)
        self.log.append(statement)
        if expect and result in (0, False):
            raise RuntimeError("LabTalk statement failed: %s" % statement)
        return bool(result)

    def value(self, expression: str) -> float:
        return self.app.LTVar(expression)

    def text(self, expression: str) -> str:
        return self.app.LTStr(expression)

    # ---------------------------------------------------------------- render
    def render(self, plan: RenderingPlan, config: Dict, work_dir, *,
               export_svg: bool = True, export_png: bool = True, dpi: int = 600,
               save_project: bool = True, project_path: Optional[str] = None) -> Dict:
        """Draw the plan, export the requested formats and verify the structure."""
        work = Path(work_dir).resolve()
        work.mkdir(parents=True, exist_ok=True)
        self.run("newbook;")
        self.book_name = self.text("%H")
        self.run("wks.ncols=%d;" % max(2 * len(plan.series), 2))
        transfer = self._write_series(plan.series)
        self._write_category_labels(plan)
        axis_formatter = origin_axis.AxisFormatter(self, config)
        self._create_graph(plan, config)
        axis_formatter.prepare_structure(plan)
        plots = self._plot_series(plan, config)
        self._apply_reference_axis_ranges(plan, config)
        self._resolve_line_width(plan, config, work)
        axis_ranges = axis_formatter.read_ranges(plan)
        ticks = axis_formatter.plan_intervals(axis_ranges, plan)
        self._tick_plan = ticks
        area, margins = self._apply_geometry(plan, config)
        self._area_mm = area
        native_axis = axis_formatter.apply(plan, ticks)
        native_labels = self._insert_native_labels(plan, config)
        if plan.page.get('native_axis_title_fit'):
            from .native_axis_titles import fit_native_axis_titles
            self._title_fit_state = fit_native_axis_titles(self, plan, config, area)
        self._apply_native_legend(plan, config)
        from .native_arrows import insert_native_arrows
        native_arrows = insert_native_arrows(self, plan, config, area)
        from .native_axis_contract import capture_axis_contract, verify_axis_contract
        # Capture after all native configuration, before the first save. This
        # records automatic display padding without confusing it with data bounds.
        native_axis = axis_formatter.inspect(plan)
        self._axis_contract = capture_axis_contract(plan, config, native_axis)
        configured_axes = verify_axis_contract(plan, config, native_axis, self._axis_contract)
        if not configured_axes["ok"]:
            raise RuntimeError("configured scientific/native axes differ: %s" % configured_axes["issues"])
        # The earlier range read supplies tick planning. Report the final display
        # endpoints as well, including explicit AxisSpec bounds and reversal.
        axis_ranges = {}
        for key, states in native_axis["layers"].items():
            axis_ranges[key] = {axis: [states[side]["from"], states[side]["to"]]
                                for axis, side in (("x", "bottom"), ("y", "left"))
                                if side in states}
            if axis_formatter.uses_native_dual_y(plan) and key == "left":
                axis_ranges[key]["y2"] = [states["right"]["from"], states["right"]["to"]]
        exports = self._export(plan, config, export_svg, export_png, dpi, save_project,
                               work, project_path)
        # Optional provenance metadata cannot fail an otherwise valid science
        # render. Static inspection never starts another Origin/Node process.
        environment = getattr(self, "_environment_diagnostics", None)
        if environment is None:
            try:
                from ..doctor import collect_diagnostics
                environment = collect_diagnostics(probe_runtime=False)
            except Exception as exc:
                environment = {"status": "metadata_unavailable", "diagnostic": str(exc),
                               "scope": "optional static diagnostics; no capability assertion"}
            self._environment_diagnostics = environment
        return {
            "graph": self.graph_name,
            "session": {"progid": "Origin.Application", "dedicated": True,
                        "pids_before": list(self._pids_before), "new_pids_observed": list(self.owned_pids)},
            "book": self.book_name,
            "plots": plots,
            "worksheet_transfer": transfer,
            "axis_ranges": axis_ranges,
            "ticks": ticks,
            "native_axis": native_axis,
            "native_axis_contract": self._axis_contract,
            "environment": environment,
            "native_export_paths": getattr(self, "_native_export_paths_info", None),
            "native_legend": getattr(self, "_legend_state", None),
            "area_mm": area,
            "margins_mm": margins,
            "overlay": {"object_count": 0, "objects": [],
                        "policy": "disabled: all content is native Origin"},
            "native_labels": native_labels,
            "native_arrows": native_arrows,
            "native_axis_title_fit": getattr(self, '_title_fit_state', None),
            "exports": exports,
        }

    # -------------------------------------------------------------- internal
    def _write_category_labels(self, plan: RenderingPlan) -> None:
        """Keep supplied category identities in an editable label column."""
        for layer in plan.layers:
            for axis in layer.axes.values():
                if not axis.tick_labels:
                    continue
                if not axis.ticks or len(axis.ticks) != len(axis.tick_labels):
                    raise ValueError("category tick labels require an explicit one-to-one index mapping")
                if any(v != int(v) or v < 1 or v > 10000 for v in axis.ticks):
                    raise ValueError("category indices must be positive integers <=10000")
                index = 2 * len(plan.series) + 1
                self.run("win -a %s; wks.ncols=%d; wks.col%d.format=2;" %
                         (self.book_name, index, index))
                values = [[""] for _ in range(int(max(axis.ticks)))]
                for number, text in zip(axis.ticks, axis.tick_labels):
                    values[int(number) - 1] = [str(text)]
                self.app.PutWorksheet("[%s]Sheet1" % self.book_name, values, 0, index - 1)
                axis.label_dataset = "%s_%s" % (self.book_name, _column_letter(index))

    def _write_series(self, series: Sequence[SeriesSpec]) -> List[Dict]:
        transferred = []
        for index, item in enumerate(series):
            if not item.points:
                raise ValueError("series %s has no points" % item.series_id)
            payload = [[float(x), float(y)] for x, y in item.points]
            self.app.PutWorksheet("[%s]Sheet1" % self.book_name, payload, 0, 2 * index)
            if item.metadata:
                sheet = self.app.FindWorksheet("[%s]Sheet1" % self.book_name)
                for ci, key, dtype in ((2 * index, "x", 3), (2 * index + 1, "y", 0)):
                    axis = item.metadata.get(key) or {}
                    column = sheet.Columns(ci)
                    column.LongName = axis.get("quantity", key)
                    column.Units = axis.get("unit", "")
                    column.Type = dtype
                import json
                provenance = json.dumps(item.metadata, ensure_ascii=False, separators=(",", ":"))
                sheet.Columns(2 * index + 1).Comments = provenance
            transferred.append({"series": item.series_id, "column": 2 * index + 1,
                                "points": len(payload)})
        return transferred

    def _create_graph(self, plan: RenderingPlan, config: Dict) -> None:
        layers = len(plan.layers) if plan.layers else 1
        block = config.get("plot_type") or {}
        template = block.get("graph_template") or "origin"
        if not template.startswith('"'):
            template = '"%s"' % template if " " in template else template
        if not self.run("win -t plot %s %s;" % (template, plan.graph_name), expect=False):
            # a task may reference a template that exists only on another machine
            self.log.append("NOTE: graph template %s is unavailable; falling back to "
                            "'origin'" % template)
            plan.notes = list(plan.notes) + [
                "graph template %s was not found in this Origin installation; the "
                "default 'origin' template was used instead" % template]
            plan.page["graph_template_used"] = "origin"
            self.run("win -t plot origin %s;" % plan.graph_name)
        else:
            plan.page["graph_template_used"] = template.strip('"')
        self.graph_name = self.text("%H")
        if layers > 1:
            raise RuntimeError("the current supported families must declare one native Origin "
                               "layer; linked righty layers are not a dual-Y fallback")

    def _plot_series(self, plan: RenderingPlan, config: Dict) -> int:
        """Create the plots, then style the plot that was just created.

        The colour is passed to ``plotxy`` (per-series).  Before applying the
        width/dash/symbol and Y-side properties, explicitly select the newly
        created data plot: selecting a layer alone does not update ``%C``.
        """
        count = 0
        plot_counts: Dict[int, int] = {}
        for index, item in enumerate(plan.series):
            layer = (item.layer + 1) if plan.layers else 1
            if item.y_axis not in ("left", "right"):
                raise ValueError("series %s has unsupported y_axis %r"
                                 % (item.series_id, item.y_axis))
            if item.y_axis == "right" and not origin_axis.AxisFormatter.uses_native_dual_y(plan):
                raise ValueError("series %s requests right Y without native_dual_y capability"
                                 % item.series_id)
            first, last = 2 * index + 1, 2 * index + 2
            has_symbol = bool(item.style.symbol_shape and
                              str(item.style.symbol_shape).lower() != "none")
            plot_type = ({"line": 200, "scatter": 201, "line_points": 202}.get(item.plot_kind)
                         if item.plot_kind else None)
            if item.plot_kind and plot_type is None:
                raise ValueError("unsupported native plot_kind %r" % item.plot_kind)
            if plot_type is None:
                plot_type = 201 if item.role == "native_marker" else (202 if has_symbol else 200)
            color = (" color:=%s" % labtalk.color(item.color)) if item.color else ""
            self.run("plotxy iy:=[%s]Sheet1!(%d,%d) plot:=%d legend:=0 rescale:=0%s "
                     "ogl:=[%s]%d!;"
                     % (self.book_name, first, last, plot_type, color,
                        self.graph_name, layer))
            # ``ogl`` can create the plot in a non-active window.  Activate the
            # exact graph, layer, and ordinal plot before resolving ``%C``.  This
            # is essential for native Y/Y2 binding: without ``layer.plot`` Origin
            # may retain the prior selected curve.
            plot_counts[layer] = plot_counts.get(layer, 0) + 1
            self.run("win -a %s; layer -s %d; layer.plot=%d;"
                     % (self.graph_name, layer, plot_counts[layer]))
            # Set both sides explicitly.  A graph template can retain the last
            # active Y-side selection, so relying on the default for left-Y plots
            # may silently put capacity on Y2.  -ay 1/2 are Origin's native
            # Plot Details > Display > Plot Data on Left/Right Y settings.
            self.run("set %%C -ay %d;" % (2 if item.y_axis == "right" else 1))
            statements = []
            # `%C` names the plot just created.  Applying `set` to worksheet
            # columns is accepted by some Origin releases but does not change the
            # graph's symbol properties; the current plot reference is portable.
            dataset = "%C"
            if has_symbol:
                if item.style.symbol_size_pt:
                    # Origin documents and the native set/get probe confirm pt.
                    statements.append(("set %s -z %g;" %
                                       (dataset, item.style.symbol_size_pt),
                                       False))
                if item.style.symbol_shape:
                    statements.append(("set %s -k %d;"
                                       % (dataset, _symbol_code(item.style.symbol_shape)), False))
                # -e is a source row limit, not symbol edge width. Edge width
                # requires a separately verified Scale by Symbol Size setting;
                # keep the native template edge rather than guessing its unit.
                if (item.style.symbol_fill or "").lower() == "open":
                    # ``-kf`` controls the Symbol tab's interior (1 = open).
                    # ``-qf`` would instead target a data-label font and leaves
                    # an ostensibly open marker filled.
                    statements.append(("set %s -kf 1;" % dataset, False))
                elif (item.style.symbol_fill or "").lower() == "filled":
                    statements.append(("set %s -kf 0;" % dataset, False))
            # Scatter and auxiliary marker plots never acquire a connecting line.
            # Scientific line widths are resolved in the plan, not guessed here.
            if item.role != "native_marker" and item.plot_kind != "scatter" and item.style.line_width_pt is not None:
                statements.append(("set %s -wp %g;"
                                   % (dataset, item.style.line_width_pt),
                                   False))
                statements.append(("set %s -d 0;" % dataset, False))
            for statement, expect in statements:
                ok = self.run(statement, expect=expect)
                if not ok:
                    self.width_overrides_failed = True
                    self.log.append("NOTE: statement ignored by this Origin build: %s"
                                    % statement)
            count += 1
        # every plot was created with rescale:=0, so rescale each layer once at the
        # end (this is also where the display point limit is applied).  Rescaling has
        # to be done per layer: `layer -a` only scales the active one.
        for index in range(1, (len(plan.layers) if plan.layers else 1) + 1):
            self.run("layer -s %d; layer -a;" % index)
        self.run("layer -s 1;")
        max_points = (config.get("plot_type") or {}).get("max_display_points")
        if max_points is not None:
            self.run("layer.maxpts=%s; page.maxpts=%s;" % (int(max_points), int(max_points)))
            self.log.append("display point limit set to %s per plot" % max_points)
        else:
            self.log.append("display point limit left at the Origin default")
        return count

    def verify_project(self, path, plan: RenderingPlan, config: Dict,
                       axis_contract: Optional[Dict] = None) -> Dict:
        """Reopen only our saved project and verify native plots, columns and axes."""
        import re
        self.app.IsModified = False
        self.app.NewProject()
        if not self.app.Load(str(path)):
            raise RuntimeError("saved Origin project could not be reopened")
        issues, entries = [], []
        graphs = [page for page in self.app.GraphPages if page.Name == self.graph_name]
        if len(graphs) != 1:
            return {"ok": False, "issues": ["saved graph missing or ambiguous"], "series": []}
        self.run("win -a %s;" % self.graph_name)
        actual_count = sum(len(list(layer.DataPlots)) for layer in graphs[0].Layers)
        if actual_count != len(plan.series):
            issues.append("reopened native plot count %d != planned %d" % (actual_count, len(plan.series)))
        ordinals = {}
        for index, item in enumerate(plan.series):
            layer = item.layer + 1
            ordinals[layer] = ordinals.get(layer, 0) + 1
            ordinal = ordinals[layer]
            self.run("win -a %s; layer -s %d; layer.plot=%d;" % (self.graph_name, layer, ordinal))
            self.run('range -wx verifyX=%d; range -wy verifyY=%d; verifyXR$="%%(verifyX)"; '
                     'verifyYR$="%%(verifyY)"; verifyN=verifyY.GetSize(); get %%C -ay verifySide;'
                     % (ordinal, ordinal))
            x_range, y_range = self.text("verifyXR$"), self.text("verifyYR$")
            expected_x = "[%s]Sheet1!%s" % (self.book_name, _column_letter(2 * index + 1))
            expected_y = "[%s]Sheet1!%s" % (self.book_name, _column_letter(2 * index + 2))
            points = self.read_series(index, item)
            side = int(self.value("verifySide"))
            expected_side = 2 if item.y_axis == "right" else 1
            kind = int(self.value("layer.plot%d.pid" % ordinal))
            expected_kind = {"line": 200, "scatter": 201, "line_points": 202}.get(item.plot_kind)
            entry = {"series_id": item.series_id, "x_range": x_range, "y_range": y_range,
                     "expected_x": expected_x, "expected_y": expected_y,
                     "point_count": int(self.value("verifyN")), "y_side": side,
                     "expected_y_side": expected_side, "plot_type": kind,
                     "points_equal": points == [(float(x), float(y)) for x, y in item.points]}
            # Origin appends a quoted LongName to a short-name range when column
            # metadata is present. Compare the full book/sheet/column identity;
            # allow only that documented display suffix, never a subrange.
            canonical_x = re.sub(r'"[^\"]*"$', '', x_range)
            canonical_y = re.sub(r'"[^\"]*"$', '', y_range)
            entry["canonical_x"] = canonical_x
            entry["canonical_y"] = canonical_y
            if canonical_x != expected_x or canonical_y != expected_y:
                issues.append("%s reopened XY binding differs" % item.series_id)
            if entry["point_count"] != item.n_points or not entry["points_equal"]:
                issues.append("%s reopened data/point count differs" % item.series_id)
            if side != expected_side:
                issues.append("%s reopened Y/Y2 side differs" % item.series_id)
            if expected_kind is not None and kind != expected_kind:
                issues.append("%s native connection type differs" % item.series_id)
            # Units are checked after saved-project reload, not inferred from
            # template text or an Execute return code.
            import math
            native_style = {}
            if item.style.line_width_pt is not None and item.role != "native_marker":
                self.run("get %C -wp verifyLinePt;")
                native_style["line_width_pt"] = self.value("verifyLinePt")
                if not math.isclose(native_style["line_width_pt"], item.style.line_width_pt,
                                    rel_tol=1e-9, abs_tol=1e-9):
                    issues.append("%s reopened native line width differs" % item.series_id)
            if item.style.symbol_shape and str(item.style.symbol_shape).lower() != "none":
                self.run("get %C -z verifySymbolPt; get %C -k verifySymbolShape; get %C -kf verifySymbolFill;")
                native_style.update(symbol_size_pt=self.value("verifySymbolPt"),
                                    symbol_shape=int(self.value("verifySymbolShape")),
                                    symbol_fill=int(self.value("verifySymbolFill")))
                if item.style.symbol_size_pt is not None and not math.isclose(
                        native_style["symbol_size_pt"], item.style.symbol_size_pt,
                        rel_tol=1e-9, abs_tol=1e-9):
                    issues.append("%s reopened native symbol size differs" % item.series_id)
                if native_style["symbol_shape"] != _symbol_code(item.style.symbol_shape):
                    issues.append("%s reopened native symbol shape differs" % item.series_id)
                expected_fill = {"filled": 0, "open": 1}.get(str(item.style.symbol_fill).lower())
                if expected_fill is not None and native_style["symbol_fill"] != expected_fill:
                    issues.append("%s reopened native symbol fill differs" % item.series_id)
            entry["native_style"] = native_style
            if item.metadata:
                sheet = self.app.FindWorksheet("[%s]Sheet1" % self.book_name)
                entry["column_semantics"] = {}
                for ci, key in ((2 * index, "x"), (2 * index + 1, "y")):
                    col = sheet.Columns(ci)
                    expected = item.metadata.get(key) or {}
                    entry["column_semantics"][key] = {"quantity": col.LongName, "unit": col.Units}
                    if col.LongName != expected.get("quantity", key) or col.Units != expected.get("unit", ""):
                        issues.append("%s reopened column quantity/unit differs" % item.series_id)
                import json
                try:
                    stored_metadata = json.loads(sheet.Columns(2 * index + 1).Comments)
                    expected_metadata = json.loads(json.dumps(item.metadata, ensure_ascii=False))
                    entry["provenance_equal"] = stored_metadata == expected_metadata
                except (TypeError, ValueError):
                    entry["provenance_equal"] = False
                if not entry["provenance_equal"]:
                    issues.append("%s reopened scientific provenance differs" % item.series_id)
            entries.append(entry)
        self.run("win -a %s; layer -s 1;" % self.graph_name)
        axes = origin_axis.AxisFormatter(self, config).inspect(plan)
        from .native_axis_contract import verify_axis_contract
        axis_check = verify_axis_contract(plan, config, axes,
                                          axis_contract if axis_contract is not None else
                                          getattr(self, "_axis_contract", None))
        issues.extend(axis_check["issues"])
        legend_state = None
        if getattr(self, "_legend_text", None) is not None:
            actual_legend = self.text("%s.text$" % self._legend_object)
            from . import native_text
            # Scientific linked rows stay independently planned. Origin's native
            # bold setter serializes an explicit wrapper on each line; only that
            # configured transformation is permitted in this comparison.
            expected_lines = native_text.expected_text_lines(
                self._legend_text, typography.legend_bold(config))
            legend_state = {"object": self._legend_object, "text": actual_legend,
                            "expected": self._legend_text,
                            "expected_native_lines": expected_lines,
                            "equal": native_text.text_lines(actual_legend) == expected_lines}
            if not legend_state["equal"]:
                issues.append("reopened native legend differs from the scientific plan")
            from .native_legend import read_legend_bounds
            bounds = read_legend_bounds(self, config, self._area_mm, self._legend_object)
            legend_state["bounds"] = bounds
            expected_bounds = getattr(self, "_legend_state", None)
            if expected_bounds:
                # Native frame coordinates are rounded in page pixels.
                actual_box, expected_box = bounds["normalized_box"], expected_bounds["normalized_box"]
                tolerance = max(0.1 / self._area_mm["width_mm"], 0.1 / self._area_mm["height_mm"])
                legend_state["position_equal"] = all(abs(a-b) <= tolerance for a,b in zip(actual_box, expected_box))
                if not legend_state["position_equal"]:
                    issues.append("reopened native legend bounding box differs")
            box = bounds["normalized_box"]
            if bounds.get("attachment") != 0 or box[0] < -0.002 or box[1] < -0.002 or box[2] > 1.002 or box[3] > 1.002:
                issues.append("reopened native legend is not attached to/contained in the layer frame")
        for layer_idx, lp in enumerate(plan.layers):
            self.run("layer -s %d;" % (layer_idx + 1))
            actual = axes["layers"].get("left" if layer_idx == 0 else "right", {})
            for side, axis in lp.axes.items():
                state = actual.get(side) or {}
                interval = origin_axis.AxisFormatter._interval_for(layer_idx+1, state.get("native_axis"), getattr(self, "_tick_plan", {}))
                if interval is not None:
                    wanted_count = interval.get("minor_tick_count")
                    if wanted_count is not None and state.get("minor_tick_count") != wanted_count:
                        issues.append("reopened %s minor tick count differs" % side)
                    if wanted_count is not None and state.get("minor_positions"):
                        issues.append("reopened %s retained custom minor tick positions" % side)
                    minor_visible = bool(interval.get("minor_ticks")) and axis.show_ticks
                    actual_mask = int(state.get("tick_mask") or 0)
                    direction = axis.tick_direction or (config.get("axes") or {}).get("tick_direction") or "in"
                    major_mask, minor_mask = origin_axis.TICK_MASKS[direction]
                    expected_mask = (major_mask if axis.show_ticks and (config.get("axes") or {}).get("major_tick", True) else 0) | (minor_mask if minor_visible else 0)
                    if actual_mask != expected_mask:
                        issues.append("reopened %s major/minor tick direction/visibility differs" % side)
                    if axis.tick_length_pt is not None:
                        minor_length = (config.get("axes") or {}).get("minor_tick_length")
                        if minor_length is None:
                            minor_length = axis.tick_length_pt / 2.0
                        if abs(state.get("major_tick_length", -1)-axis.tick_length_pt)>1e-8 or abs(state.get("minor_tick_length", -1)-minor_length)>1e-8:
                            issues.append("reopened %s major/minor tick length differs" % side)
                if axis.scale_type and state.get("scale_type") != (2 if axis.scale_type == "log10" else 1):
                    issues.append("reopened %s scale differs" % side)
                if axis.direction == "descending" and not state.get("from", 0) > state.get("to", 0):
                    issues.append("reopened %s direction differs" % side)
                if axis.scale_type and axis.direction == "ascending" and not state.get("from", 0) < state.get("to", 0):
                    issues.append("reopened %s direction differs" % side)
                if axis.label_dataset and state.get("label_type") != 2:
                    issues.append("reopened %s lost native categorical tick labels" % side)
                if axis.label_dataset:
                    sheet = self.app.FindWorksheet("[%s]Sheet1" % self.book_name)
                    labels = list(sheet.Columns(2 * len(plan.series)).GetData(5, 0, int(max(axis.ticks)) - 1))
                    expected_labels = [""] * int(max(axis.ticks))
                    for number, text in zip(axis.ticks, axis.tick_labels):
                        expected_labels[int(number) - 1] = str(text)
                    state["category_labels"] = labels
                    state["category_labels_equal"] = labels == expected_labels
                    native_axis = state.get("native_axis")
                    state["category_binding"] = self.text("layer.%s.labelText$" % native_axis)
                    expected_binding = "[%s]Sheet1!%s" % (self.book_name, _column_letter(2 * len(plan.series) + 1))
                    state["expected_category_binding"] = expected_binding
                    if labels != expected_labels or state["category_binding"] not in (axis.label_dataset, expected_binding):
                        issues.append("reopened %s categorical label data/binding differs" % side)
        native_labels = self._verify_native_labels(plan, config)
        issues.extend(native_labels["issues"])
        from .native_arrows import verify_native_arrows
        arrows = verify_native_arrows(self, plan, config, self._area_mm, getattr(self, '_arrow_state', None))
        issues.extend(arrows['issues'])
        return {"ok": not issues, "issues": issues, "series": entries, "native_axis": axes,
                "native_axis_contract_check": axis_check,
                "native_legend": legend_state,
                "native_arrows": arrows,
                "native_labels": native_labels,
                "native_plot_count": actual_count, "opened_path": str(path),
                "method": "isolated COM reload + native XY ranges, pid, Y-side and exact worksheet readback"}

    def probe_editability(self, path, plan, config, evidence_dir):
        from .editability import probe
        return probe(self, path, plan, config, evidence_dir)

    def _verify_native_labels(self, plan, config):
        """Check scientific stage text, attachment and center after reload.

        Origin stores text-frame coordinates through screen pixels. Allow less
        than one screen pixel in the readback, rather than inventing exact data
        precision for a graphical object.
        """
        self.run("win -a %s; layer -s 1;" % self.graph_name)
        area = layout_style.plot_area(config)
        x_span = abs(self.value("layer.x.to") - self.value("layer.x.from"))
        y_span = abs(self.value("layer.y.to") - self.value("layer.y.from"))
        tx = max(1e-8, x_span * 25.4 / (max(area["width_mm"], 1) * 96) * 0.75)
        ty = max(1e-8, y_span * 25.4 / (max(area["height_mm"], 1) * 96) * 0.75)
        issues, entries = [], []
        from . import native_text
        wanted_bold = typography.annotation_bold(config)
        for label in plan.labels:
            if label.render != "native" or label.role.startswith("axis_title") or not label.position:
                continue
            x, y = label.position
            if label.anchor == "x_scale_y_fraction":
                y = self.value("layer.y.from") + y * (self.value("layer.y.to") - self.value("layer.y.from"))
            actual = {"name": label.name, "text": self.text("%s.text$" % label.name),
                      "x": self.value("%s.x" % label.name), "y": self.value("%s.y" % label.name),
                      "attach": self.value("%s.attach" % label.name),
                      "expected": {"text": label.text, "x": x, "y": y},
                      "tolerance": {"x": tx, "y": ty, "basis": "0.75 screen pixel at 96 dpi"}}
            actual["typography"] = (native_text.read_native_text_bold(self, label.name, expected=wanted_bold)
                                    if wanted_bold is not None else None)
            actual["equal"] = (native_text.text_lines(actual["text"]) == native_text.expected_text_lines(label.text, wanted_bold) and actual["attach"] == 2 and
                               abs(actual["x"] - x) <= tx and abs(actual["y"] - y) <= ty)
            if not actual["equal"]:
                issues.append("reopened native annotation %s text/attachment/center differs" % label.name)
            entries.append(actual)
        return {"ok": not issues, "issues": issues, "labels": entries}

    def _apply_geometry(self, plan: RenderingPlan, config: Dict) -> Tuple[Dict[str, float], Dict[str, float]]:
        canvas = layout_style.canvas(config)
        configured = layout_style.margins(config)
        # Axis labels and titles are Origin objects, so their layout is resolved by
        # Origin rather than by pre-computing page coordinates or text outlines.
        margins = dict(configured)
        # A native right-Y title needs room beyond its tick labels.  The legacy
        # 4 mm margin was sufficient only while that title was drawn as an
        # external overlay; it clips Origin's editable ``yr`` object.  The
        # configured margin policy permits enlarging margins without shrinking
        # fonts, so reserve the same practical title clearance used for Y axes.
        if origin_axis.AxisFormatter.uses_native_dual_y(plan):
            margins["right"] = max(float(margins["right"]), 12.0)
        area = {
            "left_mm": margins["left"],
            "top_mm": margins["top"],
            "width_mm": canvas["width_mm"] - margins["left"] - margins["right"],
            "height_mm": canvas["height_mm"] - margins["top"] - margins["bottom"],
            "page_width_mm": canvas["width_mm"],
            "page_height_mm": canvas["height_mm"],
        }
        if area["width_mm"] <= 10 or area["height_mm"] <= 10:
            raise ValueError("the required margins leave no plot area; the visual "
                             "template must be revised")
        self.run("page.kar=0; page.width=%f/25.4*page.resx; page.height=%f/25.4*page.resy;"
                 % (canvas["width_mm"], canvas["height_mm"]))
        self.run("page.basecolor=color(white); page.aa=1;")
        for index in range(1, (len(plan.layers) if plan.layers else 1) + 1):
            self.run("layer -s %d; layer.fixed=1; layer.factor=1; layer.unit=4; "
                     "layer.left=%f; layer.top=%f; layer.width=%f; layer.height=%f;"
                     % (index, area["left_mm"], area["top_mm"], area["width_mm"],
                        area["height_mm"]))
        return area, margins

    def _apply_native_legend(self, plan: RenderingPlan, config: Dict) -> None:
        """Create one editable Origin legend entry per logical data series."""
        if plan.legend.mode != "entries" or not plan.legend.entries:
            return
        plot_numbers: Dict[int, int] = {}
        plot_refs = {}
        rows: List[str] = []
        for item in plan.series:
            layer = item.layer + 1
            plot_numbers[layer] = plot_numbers.get(layer, 0) + 1
            ref = "\\l(%d)" % plot_numbers[layer] if layer == 1 else "\\l(%d.%d)" % (layer, plot_numbers[layer])
            plot_refs[item.series_id] = ref
            if item.series_id in plan.legend.excluded_series or not item.legend_entry:
                continue
            rows.append("%s %s" % (ref, _labtalk_string(item.legend_entry)))
        grouped_rows = plan.legend.grouped.get("rows") or []
        if grouped_rows:
            rows = []
            headers = plan.legend.grouped.get("headers") or []
            if headers:
                rows.append(" / ".join(_labtalk_string(str(text)) for text in headers))
            for entry in grouped_rows:
                ids = entry["series_ids"]
                if not ids or any(sid not in plot_refs for sid in ids):
                    raise ValueError("native legend row refers to an absent planned series")
                rows.append("%s %s" % (" ".join(plot_refs[sid] for sid in ids), _labtalk_string(entry["label"])))
        if not rows:
            return
        self.run("layer -s 1;", expect=False)
        # `legend.text$` is a native text object.  Origin keeps the line/symbol
        # samples linked to the actual plots, so edits remain in the .opju file.
        self._legend_text = "\\n".join(rows)
        self._semantic_legend_text = self._legend_text
        self._legend_object = "ScientificLegend"
        # Origin's special 'Legend' object can regenerate default plot rows at
        # export despite its stored text. The official manual requires renaming
        # custom legends to retain customizations. A native linked text legend
        # with a distinct name keeps exactly the planned scientific objects.
        self.run('label -r legend;', expect=False)
        self.run('label -p 50 50 -j 0 -sl -sa -n %s "%s";' % (self._legend_object, self._legend_text))
        actual = self.text("%s.text$" % self._legend_object)
        if actual.replace("\\n", "\n").replace("\r\n", "\n").strip() != self._legend_text.replace("\\n", "\n").strip():
            raise RuntimeError("native legend text assignment did not match the scientific plan")
        self.run("%s.font=font(%s); %s.fsize=%s;" %
                 (self._legend_object, typography.font_family(config), self._legend_object, typography.legend_size_pt(config)),
                 expect=False)
        from .native_legend import place_legend
        self._legend_state = place_legend(self, plan, config, self._area_mm, self._legend_object)

    def _insert_native_labels(self, plan: RenderingPlan, config: Dict) -> List[Dict]:
        """Add non-axis annotations as editable Origin text labels.

        Axis titles are handled by ``_apply_native_axis_titles``.  Rate-stage labels
        and future native labels are ordinary Origin label objects, never SVGs.
        """
        inserted = []
        from . import native_text
        for label in plan.labels:
            if label.role.startswith("axis_title") or not label.text or not label.position:
                continue
            self.run("layer -s 1;", expect=False)
            x, y = label.position
            if label.anchor == "x_scale_y_fraction":
                y_from = self.value("layer.y.from")
                y_to = self.value("layer.y.to")
                y = y_from + float(y) * (y_to - y_from)
            self.run('label -j 1 -n %s "%s";' % (label.name, _labtalk_string(label.text)))
            self.run('%s.attach=2; %s.x=%s; %s.y=%s; %s.font=font(%s); %s.fsize=%s; %s.angle=%s;'
                     % (label.name, label.name, x, label.name, y, label.name,
                          typography.font_family(config), label.name, label.size_pt,
                          label.name, label.rotation_deg), expect=False)
            weight = native_text.apply_native_text_bold(self, label.name, typography.annotation_bold(config))
            # Font/angle changes can preserve the text-frame corner and move
            # its center. Place the final-sized native object last.
            self.run('%s.x=%s; %s.y=%s;' % (label.name, x, label.name, y), expect=False)
            inserted.append({"name": label.name, "role": label.role, "native": True, "typography": weight})
        return inserted

    def _export(self, plan: RenderingPlan, config: Dict, export_svg: bool,
                export_png: bool, dpi: int, save_project: bool, work: Path,
                project_path: Optional[str] = None) -> Dict:
        """Export through the shared writer: it owns naming, paths and checks."""
        directory = work / "_exports"
        self.run("win -a %s;" % self.graph_name)
        canvas = layout_style.canvas(config)
        project = None
        if save_project:
            # saved straight to its final location: Origin keeps the project file
            # open, so it cannot be moved afterwards
            project = (str(Path(project_path).resolve()) if project_path
                       else str(directory / ("%s.opju" % plan.graph_name)))
        from .native_export_paths import NativeExportPaths, assert_project_path
        assert_project_path(project)
        targets = export_writer.plan_targets(work, plan.graph_name, svg=export_svg,
                                             png=export_png, project=project)
        routing = NativeExportPaths(targets["files"], plan.graph_name, directory / "native_export_paths.json")
        try:
            with routing:
                native_directory = routing.directory
                if "png" in targets["files"]:
                    self.run('expGraph type:=png path:="%s" filename:="%s" %s '
                             'tr2.PNG.dotsperinch:=%d tr2.PNG.bitsperpixel:="24-bit Color";'
                             % (labtalk.quoted(native_directory),
                                plan.graph_name, _export_common(canvas["width_mm"]), int(dpi)))
                if "svg" in targets["files"]:
                    self.run('expGraph type:=svg path:="%s" filename:="%s" %s;'
                             % (labtalk.quoted(native_directory), plan.graph_name,
                                _export_common(canvas["width_mm"])))
                if "opju" in targets["files"]:
                    self.app.Save(targets["files"]["opju"])
        finally:
            self._native_export_paths_info = routing.document
            self.log.append("native export path mapping and byte-identity evidence: %s" % routing.evidence_path)
        return export_writer.confirm(targets)

    def read_series(self, index: int, item: SeriesSpec) -> List[Tuple[float, float]]:
        """Read one transferred series back from the worksheet (QA Level 3).

        This is the mechanical half of the point-by-point check; the comparison
        itself lives in :mod:`plotting_core.qa.pointwise`.
        """
        values = self.app.GetWorksheet("[%s]Sheet1" % self.book_name, 0, 2 * index,
                                       len(item.points) - 1, 2 * index + 1)
        return [(float(row[0]), float(row[1])) for row in values]

    def _resolve_line_width(self, plan: RenderingPlan, config: Dict, work: Path) -> None:
        """Record that line width is native; an SVG fallback is deliberately banned."""
        curves = plan.page.get("line_overlay") or []
        if not curves:
            plan.page["line_width_source"] = "native Origin plot style"
            return
        expected = curves[0].get("width_pt")
        probe = work / "_width_probe"
        probe.mkdir(parents=True, exist_ok=True)
        try:
            self.run('win -a %s;' % self.graph_name)
            self.run('expGraph type:=svg path:="%s" filename:="width_probe" '
                     'overwrite:=replace tr.Margin:=2 tr.SpeedMode:=2 tr1.unit:=1 '
                     'tr1.width:=%g;'
                     % (labtalk.quoted(str(probe)),
                        layout_style.canvas(config)["width_mm"] / 10.0))
            style = export_pkg.validate.measure_curve_style(
                str(probe / "width_probe.svg"))
        except Exception as exc:
            plan.notes = list(plan.notes) + [
                "line width probe failed (%s); retained the native Origin plot style"
                % exc]
            return
        unit_pt = 85.0 / 1005.0 * 72.0 / 25.4
        units = style.get("width_units") or {}
        if not units:
            return
        drawn_units = float(sorted(units.items(), key=lambda item: -item[1])[0][0])
        measured = round(drawn_units * unit_pt, 2)
        plan.page["line_width_probe_pt"] = measured
        # Origin writes stroke widths as whole page units, so a 0.8 pt line shows up
        # as 3 units (0.719 pt); compare in units with a tolerance below one unit.
        expected_units = (float(expected) / unit_pt) if expected else None
        if expected_units and abs(drawn_units - expected_units) <= 0.75:
            plan.page["line_width_source"] = "origin plot style (verified)"
            plan.notes = list(plan.notes) + [
                "Origin drew the configured %.2f pt line width (%d page units); the "
                "project and export share one native drawing"
                % (float(expected), int(round(drawn_units)))]
        else:
            plan.page["line_width_source"] = "native Origin plot style (unverified width)"
            plan.notes = list(plan.notes) + [
                "Origin drew %.2f pt instead of the configured %.2f pt; kept the "
                "editable native Origin line rather than adding an SVG overlay"
                % (measured, float(expected) if expected else 0.0)]
            if (config.get("plot_type") or {}).get("graph_template"):
                plan.notes = list(plan.notes) + [
                    "the requested graph template %r did not deliver the width (it may "
                    "be missing from this Origin installation)"
                    % (config["plot_type"]["graph_template"],)]

    def _apply_reference_axis_ranges(self, plan: RenderingPlan, config: Dict) -> None:
        """Keep Origin's confirmed auto-range padding when a custom template is used.

        A graph template also carries the axis rescale settings of the graph it was
        saved from, so the confirmed padding would change with it.  The layer
        geometry stays the template's job, but the axis ranges are taken from what the
        default ``origin`` template produces for the same data extent - measured in a
        throwaway Origin session, so nothing extra lands in the saved project.

        Axis ranges are never authored (the template keeps every ``*_axis_range``
        null), so this data-adaptive range is the default and only a spec that
        explicitly sets ``backend.restore_default_axis_ranges: false`` keeps the
        ranges stored inside the graph template.
        """
        blocks = config.get("plot_type") or {}
        template = blocks.get("graph_template")
        if not template or str(template).strip().lower() in ("origin", ""):
            return
        policy = config.get("backend") or {}
        if policy.get("restore_default_axis_ranges") is False:
            return
        bounds = plan.page.get("layer_bounds") or {}
        if not bounds:
            return
        reference = OriginBackend(visible=False)
        try:
            reference.connect()
            ranges = reference._default_template_ranges(plan, config)
        except Exception as exc:
            plan.notes = list(plan.notes) + [
                "the reference axis ranges could not be measured (%s); the graph "
                "template's own axis settings are kept" % exc]
            return
        finally:
            reference.disconnect()
        statements = []
        native_dual_y = origin_axis.AxisFormatter.uses_native_dual_y(plan)
        for index in range(1, (len(plan.layers) if plan.layers else 1) + 1):
            key = "left" if index == 1 else "right"
            values = ranges.get(key)
            if not values:
                continue
            statements.append("layer -s %d;" % index)
            statements.append("layer.x.from=%r; layer.x.to=%r;" % tuple(values["x"]))
            statements.append("layer.y.from=%r; layer.y.to=%r;" % tuple(values["y"]))
            if native_dual_y and index == 1 and values.get("y2"):
                statements.append("layer.y2.from=%r; layer.y2.to=%r;" % tuple(values["y2"]))
        if statements:
            self.run(" ".join(statements))
            plan.page["axis_range_source"] = "default-template auto range (measured)"
            plan.notes = list(plan.notes) + [
                "axis ranges taken from the default template's auto range so the "
                "confirmed padding is unchanged by the graph template"]

    def _default_template_ranges(self, plan: RenderingPlan, config: Dict,
                                 ) -> Dict:
        """Auto ranges the plain ``origin`` template produces for the same data.

        Origin's auto range depends on the data itself, not only on its extent, so the
        reference pass plots the real series into a throwaway session.
        """
        layers = len(plan.layers) if plan.layers else 1
        if layers > 1:
            raise RuntimeError("range reference does not create linked righty layers")
        self.run("newbook;")
        book = self.text("%H")
        for index, item in enumerate(plan.data_series):
            payload = [[float(x), float(y)] for x, y in item.points]
            self.app.PutWorksheet("[%s]Sheet1" % book, payload, 0, 2 * index)
        self.run("win -t plot origin RangeReference;")
        graph = self.text("%H")
        origin_axis.AxisFormatter(self, config).prepare_structure(plan)
        plot_counts: Dict[int, int] = {}
        for index, item in enumerate(plan.data_series, start=1):
            layer = (item.layer + 1) if plan.layers else 1
            self.run('plotxy iy:=[%s]Sheet1!(%d,%d) plot:=200 legend:=0 rescale:=0 '
                     'ogl:=[%s]%d!;'
                     % (book, 2 * index - 1, 2 * index, graph, layer))
            plot_counts[layer] = plot_counts.get(layer, 0) + 1
            self.run("win -a %s; layer -s %d; layer.plot=%d;"
                     % (graph, layer, plot_counts[layer]))
            # Mirror the production plot path: assign both Y sides explicitly
            # before measuring automatic ranges, otherwise a saved template state
            # can swap the reference Y/Y2 ranges.
            self.run("set %%C -ay %d;" % (2 if item.y_axis == "right" else 1))
        ranges = {}
        for index in range(1, layers + 1):
            self.run("layer -s %d; layer -a;" % index)
            values = {
                "x": [self.value("layer.x.from"), self.value("layer.x.to")],
                "y": [self.value("layer.y.from"), self.value("layer.y.to")],
            }
            if origin_axis.AxisFormatter.uses_native_dual_y(plan) and index == 1:
                values["y2"] = [self.value("layer.y2.from"), self.value("layer.y2.to")]
            ranges["left" if index == 1 else "right"] = values
        return ranges

SYMBOL_CODES = {"circle": 2, "square": 3, "triangle": 4, "diamond": 6, "none": 0}


def _column_letter(index: int) -> str:
    """1-based worksheet column index to its LabTalk letter (1 -> A, 27 -> AA)."""
    if index < 1:
        raise ValueError("column index must be >= 1")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _labtalk_string(value: str) -> str:
    """Escape user-facing text for a LabTalk double-quoted string."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def _symbol_code(shape: str) -> int:
    """Origin's LabTalk symbol code for the configured marker shape."""
    key = str(shape).strip().lower()
    if key not in SYMBOL_CODES:
        raise ValueError("unsupported symbol shape: %r" % shape)
    return SYMBOL_CODES[key]


def _origin_pids() -> List[int]:
    """PIDs of running Origin instances, so only our own instance is stopped."""
    try:
        completed = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Origin64.exe",
                                    "/FO", "CSV", "/NH"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return []
    pids = []
    for line in completed.stdout.decode("utf-8", "replace").splitlines():
        fields = [field.strip('"') for field in line.split('","')]
        if len(fields) >= 2 and fields[0].lower().startswith("origin"):
            try:
                pids.append(int(fields[1]))
            except ValueError:
                continue
    return pids


def _right_axis_shows_labels(plan: RenderingPlan) -> bool:
    """Whether any layer draws tick labels on its right axis (read from the plan)."""
    for layer in (plan.layers or []):
        spec = layer.axes.get("right")
        if spec is not None and spec.show_tick_labels:
            return True
    return False


def _export_common(canvas_width_mm: float) -> str:
    """The export options every format shares (canvas width in centimetres)."""
    return ("overwrite:=replace tr.Margin:=2 tr.SpeedMode:=2 tr1.unit:=1 "
            "tr1.width:=%g" % (canvas_width_mm / 10.0))
