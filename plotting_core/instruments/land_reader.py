"""Read LAND .cex data through the installed manufacturer's read library.

No vendor binary or third-party reverse-engineered decoder is bundled. Reads
one stable copy, retains every native record/step/cycle, and never starts LAND
control software, changes settings, recomputes statistics, or writes the source.
The tested 64-bit ABI is GetDllVersion()==0x30306 (LANDCex file 7.4.7.6).
"""

import ctypes
import hashlib
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import threading

READER_VERSION = "land-native-1"
SUPPORTED_EXTENSIONS = (".cex",)
SDK_API_VERSION = 0x30306
_LOCK = threading.RLock()

RECORD_COLUMNS = {
    "native_record_number": (0x4001, ""),
    "test_time_s": (0x4002, ""),
    "step_time_s": (0x4003, ""),
    "current_mA": (0x4004, "mA"),
    "capacity_mAh": (0x4005, "mAh"),
    "specific_capacity_mAh_g": (0x4006, "mAh/g"),
    "voltage_V": (0x4008, "V"),
    "energy_mWh": (0x4009, "mWh"),
}
STEP_COLUMNS = {
    "step_native_id": (0x2001, ""), "mode": (0x2002, ""),
    "duration_s": (0x2003, ""), "capacity_mAh": (0x2004, "mAh"),
    "specific_capacity_mAh_g": (0x2005, "mAh/g"),
    "start_voltage_V": (0x200A, "V"), "end_voltage_V": (0x200B, "V"),
    "start_current_mA": (0x200F, "mA"), "end_current_mA": (0x2010, "mA"),
}
CYCLE_COLUMNS = {
    "cycle_native_id": (0x1000, ""), "charge_capacity_mAh": (0x1001, "mAh"),
    "discharge_capacity_mAh": (0x1002, "mAh"),
    "charge_specific_capacity_mAh_g": (0x1003, "mAh/g"),
    "discharge_specific_capacity_mAh_g": (0x1004, "mAh/g"),
    "ce_percent": (0x1005, "%"),
    "charge_time_s": (0x101A, ""), "discharge_time_s": (0x101B, ""),
}


class LandReadError(ValueError):
    """Unavailable reader or unsupported/ambiguous native input; no guessing."""


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_land_dll(options=None):
    """Find an already installed x64 reader; never download/register a DLL."""
    options = options or {}
    explicit = options.get("dll_path") or os.environ.get("LAND_CEX_DLL")
    candidates = []
    if explicit:
        value = Path(explicit)
        if not value.is_absolute() or not value.is_file():
            raise LandReadError("LAND dll_path/LAND_CEX_DLL must name an existing absolute LANDCex_x64.dll")
        return str(value.resolve())
    if os.name == "nt":
        import winreg
        key_name = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(root, key_name, 0, winreg.KEY_READ | view) as uninstall:
                        for index in range(winreg.QueryInfoKey(uninstall)[0]):
                            name = winreg.EnumKey(uninstall, index)
                            try:
                                with winreg.OpenKey(uninstall, name) as item:
                                    display = str(winreg.QueryValueEx(item, "DisplayName")[0]).lower()
                                    if not any(token in display for token in ("land", "lanhe", "蓝电")):
                                        continue
                                    for field in ("InstallLocation", "DisplayIcon", "UninstallString"):
                                        try:
                                            raw = str(winreg.QueryValueEx(item, field)[0]).strip().strip('"')
                                            if field != "InstallLocation":
                                                raw = raw.split('",')[0].split(",0")[0].strip('"')
                                            directory = Path(raw)
                                            if directory.suffix.lower() in (".exe", ".ico"):
                                                directory = directory.parent
                                            candidates.append(directory / "LANDCex_x64.dll")
                                        except OSError:
                                            pass
                            except OSError:
                                pass
                except OSError:
                    pass
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            for name in ("LAND", "LANHE", "LAND Battery Testing System"):
                candidates.append(Path(os.environ[variable]) / name / "LANDCex_x64.dll")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise LandReadError("Installed LANDCex_x64.dll not found; provide options.dll_path or LAND_CEX_DLL. No global installation is performed.")


class _Api:
    def __init__(self, path):
        if os.name != "nt" or struct.calcsize("P") != 8:
            raise LandReadError("LAND native import requires 64-bit Windows Python and the installed x64 reader")
        self.path = str(path)
        self.dll = ctypes.WinDLL(self.path)
        self.version = self.bind("GetDllVersion", [], ctypes.c_uint32)()
        if self.version != SDK_API_VERSION:
            raise LandReadError("Unverified LAND reader ABI 0x%x; tested ABI is 0x%x" % (self.version, SDK_API_VERSION))
        ptr, integer = ctypes.c_void_p, ctypes.c_int
        self.load = self.bind("LoadData", [ctypes.c_char_p, integer], ptr)
        self.free = self.bind("FreeData", [ptr], None)
        self.silent = self.bind("EnableSilentForLoadData", [ctypes.c_bool], ctypes.c_bool)
        self.rows = self.bind("GetRows", [ptr, integer], integer)
        self.data = self.bind("GetDataAsDouble", [ptr, integer, integer], ctypes.c_double)
        self.mass = self.bind("GetActMaterialMass", [ptr, ptr], ctypes.c_float)
        self.nominal = self.bind("GetNominalStdCap", [ptr, integer], ctypes.c_float)
        self.unit = self.bind("GetUnitNameOfColumn", [ptr, integer, ptr], ctypes.c_bool)
        self.description = self.bind("GetDescriptionOfColumn", [integer, ptr], ctypes.c_bool)
        self.mode_description = self.bind("GetDescriptionOfMode", [ctypes.c_ubyte, ptr], ctypes.c_bool)
        self.first = self.bind("GetFirstRecOfStep", [ptr, integer], integer)
        self.last = self.bind("GetLastRecOfStep", [ptr, integer], integer)
        self.cycle = self.bind("GetCycleFromStep", [ptr, integer], integer)
        self.branch_bounds = {}
        for branch, word in (("charge", "Charge"), ("discharge", "Disch")):
            self.branch_bounds[branch] = tuple(self.bind("Get%s%sStepOfCycle" % (edge, word), [ptr, integer], integer)
                                              for edge in ("First", "Last"))
        self.clear = ctypes.OleDLL("oleaut32").VariantClear
        self.clear.argtypes, self.clear.restype = [ptr], ctypes.c_long

    def bind(self, name, arguments, result):
        try:
            function = getattr(self.dll, name)
        except AttributeError:
            raise LandReadError("Installed LAND reader lacks required function: " + name)
        function.argtypes, function.restype = arguments, result
        return function

    def text(self, function, *arguments):
        # VARIANT is 24 bytes on Windows x64; BSTR pointer is at byte offset 8.
        value = ctypes.create_string_buffer(24)
        try:
            ok = function(*(list(arguments) + [ctypes.byref(value)]))
            kind = ctypes.c_ushort.from_buffer(value).value
            pointer = ctypes.c_void_p.from_buffer(value, 8).value
            return ctypes.wstring_at(pointer) if ok and kind == 8 and pointer else ""
        finally:
            self.clear(ctypes.byref(value))


def _integer(value, context):
    if value is None or not math.isfinite(value) or value != int(value):
        raise LandReadError("%s is not an integral native identifier: %r" % (context, value))
    return int(value)


def _read_loaded(api, handle, filename, digest, options):
    counts = dict(records=api.rows(handle, 0x4001), steps=api.rows(handle, 0x2001), cycles=api.rows(handle, 0x1000))
    if counts["records"] <= 0 or counts["steps"] <= 0 or counts["cycles"] <= 0:
        raise LandReadError("LAND data has no native records/steps/cycles; workflow/settings files are not measurement data")
    limit = options.get("max_records", 5000000)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise LandReadError("max_records must be a positive integer; records are never truncated")
    if counts["records"] > limit:
        raise LandReadError("LAND record count exceeds configured max_records; increase the explicit limit, no rows were dropped")
    catalog = {}
    for group, columns in (("records", RECORD_COLUMNS), ("steps", STEP_COLUMNS), ("cycles", CYCLE_COLUMNS)):
        for name, (code, expected_unit) in columns.items():
            count = api.rows(handle, code)
            unit = api.text(api.unit, handle, code)
            if count != counts[group]:
                raise LandReadError("LAND native column 0x%x row count differs (%s)" % (code, name))
            if expected_unit and unit != expected_unit:
                raise LandReadError("LAND native column %s unit %r does not match verified unit %r; no conversion is guessed" % (name, unit, expected_unit))
            catalog["%s.%s" % (group, name)] = dict(id=code, native_unit=unit,
                native_description=api.text(api.description, code), rows=count)
    issues = []
    def value(code, index, location):
        number = float(api.data(handle, code, index))
        if not math.isfinite(number):
            issues.append(dict(kind="nonfinite_native_value", location=location, column_id=code, row_index=index))
            return None
        return number
    cycles = []
    for index in range(counts["cycles"]):
        row = {name: value(code, index, "cycles") for name, (code, _) in CYCLE_COLUMNS.items()}
        native_id = _integer(row["cycle_native_id"], "cycle ID")
        row.update(cycle=native_id + 1, cycle_sdk_index=index, source_row_index=index)
        for branch, (first, last) in api.branch_bounds.items():
            low, high = first(handle, index), last(handle, index)
            row[branch + "_first_step"] = low
            row[branch + "_last_step"] = high
            row[branch + "_present"] = low >= 0 and high >= low
        row["completion_status"] = "not_inferred_from_presence"
        cycles.append(row)
    record_steps = [None] * counts["records"]
    steps = []
    for index in range(counts["steps"]):
        row = {name: value(code, index, "steps") for name, (code, _) in STEP_COLUMNS.items()}
        mode = _integer(row["mode"], "step mode")
        native_cycle_index = api.cycle(handle, index)
        if not 0 <= native_cycle_index < len(cycles):
            raise LandReadError("LAND step has no valid native cycle: %d" % index)
        first, last = api.first(handle, index), api.last(handle, index)
        branch = "rest" if mode == 0x70 else "unknown"
        candidates = [name for name in ("charge", "discharge")
                      if cycles[native_cycle_index][name + "_present"] and
                      cycles[native_cycle_index][name + "_first_step"] <= index <= cycles[native_cycle_index][name + "_last_step"]]
        if mode != 0x70 and len(candidates) == 1:
            branch = candidates[0]
        row.update(step=index, cycle=cycles[native_cycle_index]["cycle"], cycle_sdk_index=native_cycle_index,
                   cycle_native_id=cycles[native_cycle_index]["cycle_native_id"], branch=branch,
                   branch_source="manufacturer GetFirst/LastCharge/DischStepOfCycle; explicit native rest mode 0x70",
                   first_record=first, last_record=last, mode=mode,
                   mode_text=api.text(api.mode_description, mode), source_row_index=index,
                   capacity_basis="step_total")
        if branch == "unknown":
            issues.append(dict(kind="unknown_native_step_branch", step=index, mode=mode, cycle=row["cycle"]))
        if first == -1 and last == -1:
            row["has_records"] = False
        elif not 0 <= first <= last < counts["records"]:
            raise LandReadError("Invalid LAND native step record boundaries: step %d" % index)
        else:
            row["has_records"] = True
            for record_index in range(first, last + 1):
                if record_steps[record_index] is not None:
                    raise LandReadError("Overlapping LAND step record boundaries; no duplicate assignment is allowed")
                record_steps[record_index] = index
        steps.append(row)
    records = []
    for index, step_index in enumerate(record_steps):
        row = {name: value(code, index, "records") for name, (code, _) in RECORD_COLUMNS.items()}
        row.update(record_index=index, source_row_index=index)
        if step_index is None:
            row.update(step=None, cycle=None, cycle_native_id=None, cycle_sdk_index=None, branch="unknown", mode=None)
            issues.append(dict(kind="unassigned_native_record", record_index=index))
        else:
            step = steps[step_index]
            row.update(step=step_index, cycle=step["cycle"], cycle_native_id=step["cycle_native_id"],
                       cycle_sdk_index=step["cycle_sdk_index"], branch=step["branch"], mode=step["mode"])
        records.append(row)
    mass = float(api.mass(handle, None))
    if not math.isfinite(mass) or mass <= 0:
        issues.append(dict(kind="missing_positive_active_mass", native_value=mass if math.isfinite(mass) else None))
        mass = None
    nominal = float(api.nominal(handle, -1))
    branch_endpoint_errors = []
    step_endpoint_errors = []
    step_delta_errors = []
    multistep_branches = 0
    for cycle in cycles:
        for branch in ("charge", "discharge"):
            members = [step for step in steps if step["cycle"] == cycle["cycle"] and
                       step["branch"] == branch and step["has_records"]]
            if not members:
                continue
            if len(members) > 1:
                multistep_branches += 1
            endpoint = records[members[-1]["last_record"]]["capacity_mAh"]
            expected = cycle[branch + "_capacity_mAh"]
            branch_endpoint_errors.append((endpoint, expected))
            for step in members:
                first_q = records[step["first_record"]]["capacity_mAh"]
                last_q = records[step["last_record"]]["capacity_mAh"]
                step_endpoint_errors.append((last_q, step["capacity_mAh"]))
                step_delta_errors.append((None if last_q is None or first_q is None else last_q - first_q,
                                          step["capacity_mAh"]))
    def agrees(pairs):
        return bool(pairs) and all(a is not None and b is not None and math.isclose(a, b, rel_tol=2e-6, abs_tol=1e-8)
                                   for a, b in pairs)
    if agrees(branch_endpoint_errors) and agrees(step_delta_errors):
        capacity_basis = "cycle_branch_cumulative"
    elif agrees(step_endpoint_errors):
        capacity_basis = "step_cumulative"
    else:
        capacity_basis = "native_unknown"
        issues.append(dict(kind="unresolved_native_record_capacity_basis"))
    return dict(vendor="land", format="cex", source=dict(file=str(filename), sha256=digest),
                metadata=dict(reader=READER_VERSION, method="installed_manufacturer_native_read_api",
                    dll_path=api.path, dll_sha256=_sha(api.path), sdk_api_version="0x%06x" % api.version,
                    file_magic_hex=filename.read_bytes()[:4].hex(), file_version_hex=filename.read_bytes()[4:8].hex(),
                    mass_g=mass, mass_basis="active_material", mass_source="LAND GetActMaterialMass; instrument-stored entry, not an independent mass measurement",
                    nominal_capacity_native=nominal if math.isfinite(nominal) else None,
                    nominal_capacity_unit="not_verified; not used to infer C rate",
                    capacity_basis=capacity_basis, cycle_capacity_basis="native_cycle_branch_summary",
                    capacity_basis_evidence=dict(native_branch_endpoints_match=agrees(branch_endpoint_errors),
                        native_step_deltas_match=agrees(step_delta_errors), native_step_endpoints_match=agrees(step_endpoint_errors),
                        multistep_branches_checked=multistep_branches,
                        method="compare unchanged record endpoints with native cycle/step summary values; no accumulation is applied"),
                    cycle_number_offset=1, cycle_number_source="native cycle ID column 0x1000 plus 1; native ID and SDK row index retained",
                    record_index_source="zero-based SDK GetDataAsDouble row address; native_record_number column retained separately",
                    branch_source="manufacturer cycle branch-step boundaries; not current sign",
                    time_unit="s", time_unit_source="verified installed SDK GetDataAsDouble elapsed-time behavior; native unit string is empty",
                    raw_record_count=counts["records"], raw_step_count=counts["steps"], raw_cycle_count=counts["cycles"],
                    steps_never_concatenated=True, cycle_completion_not_inferred=True, scientific_truth_verified=False,
                    column_catalog=catalog),
                records=records, steps=steps, cycles=cycles,
                units=dict(voltage_V="V", current_mA="mA", capacity_mAh="mAh", specific_capacity_mAh_g="mAh/g",
                           test_time_s="s", step_time_s="s", energy_mWh="mWh", ce_percent="%", mass_g="g"),
                issues=issues)


def read_land(path, options=None):
    """Return exact native tables from one stable CEX snapshot.

    options: dll_path (or LAND_CEX_DLL), snapshot_directory (optional persistent
    task output), max_records (rejects rather than truncates). Source remains
    read-only. No sample identity, nominal C rate, stage or branch connection is
    inferred from filenames or current. A .res file is not assumed to be CEX.
    """
    options = dict(options or {})
    unknown = set(options) - {"dll_path", "snapshot_directory", "max_records"}
    if unknown:
        raise LandReadError("Unknown LAND reader option(s): " + ", ".join(sorted(unknown)))
    source = Path(path)
    if not source.is_absolute() or not source.is_file():
        raise LandReadError("LAND source must be an existing absolute file")
    source = source.resolve()
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise LandReadError("This LAND reader supports native .cex only; .res/settings files are not relabeled")
    header = source.read_bytes()[:64]
    if len(header) < 64 or header[:4] != b"\x10\x11\x09\x88":
        raise LandReadError("Source is not a recognized LAND CEX header")
    before = _sha(source)
    retained = options.get("snapshot_directory")
    temporary = None
    if retained is None:
        temporary = tempfile.TemporaryDirectory(prefix="battery_origin_land_")
        directory = Path(temporary.name)
    else:
        directory = Path(retained)
        if not directory.is_absolute():
            raise LandReadError("snapshot_directory must be absolute and outside the source directory")
        directory = directory.resolve()
        if directory == source.parent:
            raise LandReadError("Snapshot output cannot write into the source directory")
        directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / (before[:16] + ".cex")
    try:
        if snapshot.exists():
            if _sha(snapshot) != before:
                raise LandReadError("Existing LAND snapshot has different bytes; no overwrite")
        else:
            shutil.copyfile(str(source), str(snapshot))
        if _sha(snapshot) != before or _sha(source) != before:
            raise LandReadError("LAND source changed while snapshot was copied; retry from a stable saved file")
        try:
            encoded = str(snapshot).encode("gbk", errors="strict")
        except UnicodeEncodeError:
            raise LandReadError("Installed LAND reader expects an ANSI/GBK path; choose an ASCII/GBK snapshot directory")
        with _LOCK:
            api = _Api(find_land_dll(options))
            old_silent = api.silent(True)
            handle = None
            try:
                handle = api.load(encoded, 0)
                if not handle:
                    raise LandReadError("Installed LAND reader rejected this CEX; no binary guessing or source repair occurs")
                result = _read_loaded(api, handle, snapshot, before, options)
            finally:
                if handle:
                    api.free(handle)
                api.silent(old_silent)
        if _sha(snapshot) != before:
            raise LandReadError("LAND snapshot changed while native data was read")
        result["source"].update(file=str(source), snapshot_sha256=before,
                                snapshot_file=str(snapshot) if retained is not None else None,
                                snapshot_retained=retained is not None,
                                source_stable_during_snapshot=True,
                                source_still_same_after_read=_sha(source) == before)
        if not result["source"]["source_still_same_after_read"]:
            result["issues"].append(dict(kind="source_updated_after_stable_snapshot", snapshot_sha256=before))
        return result
    finally:
        if temporary is not None:
            temporary.cleanup()
