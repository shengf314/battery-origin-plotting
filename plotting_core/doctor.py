"""Bounded environment diagnostics without creating an Origin session.

``python -m plotting_core.doctor`` prints JSON only. It does not scan projects,
write into the skill or expose environment variables. The backend calls the
static variant; the CLI can additionally load Node/sharp in a short subprocess.
"""

import argparse
import ctypes
import importlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _distribution_version(name):
    for module_name in ("importlib.metadata", "importlib_metadata"):
        try:
            metadata = importlib.import_module(module_name)
            return metadata.version(name)
        except (ImportError, LookupError, AttributeError):
            pass
    return None


def _module(name, distribution=None):
    try:
        spec = importlib.util.find_spec(name)
        return {"available": spec is not None, "path": spec.origin if spec else None,
                "discovery": "import specification; native library load not exercised",
                "distribution_version": _distribution_version(distribution) if spec and distribution else None}
    except (ImportError, AttributeError, ValueError) as exc:
        return {"available": False, "path": None, "diagnostic": str(exc)}


def _file_version(path):
    """Windows executable fixed version data, using only the standard library."""
    if os.name != "nt":
        return {"status": "not_available", "reason": "Windows version resources require Windows"}
    try:
        from ctypes import wintypes

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [(name, wintypes.DWORD) for name in
                        ("signature", "struct_version", "file_ms", "file_ls", "product_ms", "product_ls",
                         "flags_mask", "flags", "os", "type", "subtype", "date_ms", "date_ls")]

        dll = ctypes.WinDLL("version", use_last_error=True)
        dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        dll.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        dll.GetFileVersionInfoW.restype = wintypes.BOOL
        dll.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                      ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        dll.VerQueryValueW.restype = wintypes.BOOL
        handle = wintypes.DWORD()
        size = dll.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
        if not size:
            return {"status": "not_available", "reason": "executable has no readable fixed version resource"}
        buffer = ctypes.create_string_buffer(size)
        if not dll.GetFileVersionInfoW(str(path), 0, size, buffer):
            raise OSError(ctypes.get_last_error(), "GetFileVersionInfoW failed")
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not dll.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            raise OSError(ctypes.get_last_error(), "VerQueryValueW failed")
        info = ctypes.cast(pointer, ctypes.POINTER(FixedFileInfo)).contents
        if info.signature != 0xFEEF04BD:
            return {"status": "not_available", "reason": "invalid fixed version resource signature"}

        def dotted(ms, ls):
            return "%d.%d.%d.%d" % (ms >> 16, ms & 0xffff, ls >> 16, ls & 0xffff)

        return {"status": "read", "file_version": dotted(info.file_ms, info.file_ls),
                "product_version": dotted(info.product_ms, info.product_ls),
                "source": "registered executable Windows fixed file version resource",
                "interpretation": "raw executable version/build; no inferred Origin release label"}
    except (OSError, AttributeError, ValueError) as exc:
        return {"status": "not_available", "diagnostic": str(exc)}


def _registered_executable(command):
    # Parse only the executable prefix; never run the registry command line.
    match = re.match(r'^\s*(?:"([^"]+\.exe)"|(.+?\.exe))(?:\s|$)', str(command), re.IGNORECASE)
    return (match.group(1) or match.group(2)) if match else None


def _origin_registration():
    result = {"progid": "Origin.Application", "registered": False, "views": [],
              "live_origin_started": False, "capability_status": "not_live_probed"}
    if os.name != "nt":
        result["reason"] = "Windows COM registry is unavailable on this platform"
        return result
    try:
        import winreg
    except ImportError:
        result["reason"] = "winreg is unavailable"
        return result
    for name, flag in (("64bit", winreg.KEY_WOW64_64KEY), ("32bit", winreg.KEY_WOW64_32KEY)):
        record = {"view": name, "registered": False}
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Origin.Application\CLSID", 0,
                                winreg.KEY_READ | flag) as key:
                clsid = winreg.QueryValueEx(key, None)[0]
            record.update(registered=True, clsid=str(clsid))
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"CLSID\%s\LocalServer32" % clsid, 0,
                                winreg.KEY_READ | flag) as key:
                command = winreg.QueryValueEx(key, None)[0]
            executable = _registered_executable(command)
            record.update(executable=executable, executable_exists=bool(executable and Path(executable).is_file()))
            if record["executable_exists"]:
                record["version_resource"] = _file_version(executable)
        except OSError as exc:
            record["diagnostic"] = "COM registry value unavailable (%s)" % exc
        result["views"].append(record)
    result["registered"] = any(record["registered"] for record in result["views"])
    result["registered_executable_available"] = any(record.get("executable_exists") for record in result["views"])
    return result


def _node_runtime(node_path=None, node_modules=None, probe_runtime=False):
    from .export import runtime
    discovered_node = node_path if node_path else runtime.find_node()
    selected = Path(discovered_node) if discovered_node and Path(discovered_node).is_file() else None
    source = "explicit argument" if node_path else "shared export runtime discovery"
    discovered_modules = node_modules if node_modules else runtime.find_node_modules()
    package_roots = [Path(discovered_modules)] if discovered_modules else []
    sharp_dir = next((root / "sharp" for root in package_roots if (root / "sharp" / "package.json").is_file()), None)
    sharp_version, package_error = None, None
    if sharp_dir:
        try:
            package_file = sharp_dir / "package.json"
            if package_file.stat().st_size > 1024 * 1024:
                raise ValueError("sharp package metadata exceeds bounded read size")
            sharp_version = json.loads(package_file.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError) as exc:
            package_error = str(exc)
    result = {"node": {"available": selected is not None, "path": str(selected) if selected else None, "source": source},
              "sharp": {"package_present": sharp_dir is not None,
                        "path": str(sharp_dir) if sharp_dir else None, "package_version": sharp_version},
              "load_probe": {"status": "not_run", "reason": "static discovery only"}}
    playwright_dir = next((root / "playwright" for root in package_roots
                           if (root / "playwright" / "package.json").is_file()), None)
    result["playwright"] = {"package_present": playwright_dir is not None,
                            "path": str(playwright_dir) if playwright_dir else None,
                            "browser_channel": "msedge"}
    if package_error:
        result["sharp"]["diagnostic"] = package_error
    if probe_runtime and selected:
        try:
            if sharp_dir:
                code = "process.stdout.write(JSON.stringify({node:process.version,sharp:require(process.argv[1]).versions.sharp}))"
                command = [str(selected), "-e", code, str(sharp_dir)]
            else:
                command = [str(selected), "--version"]
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       universal_newlines=True, timeout=10)
            result["load_probe"] = {"status": "passed" if completed.returncode == 0 else "failed",
                                    "exit_code": completed.returncode,
                                    "scope": "Node version + sharp require" if sharp_dir else "Node version only",
                                    "output": completed.stdout.strip()[:2000],
                                    "diagnostic": completed.stderr.strip()[:2000] or None}
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["load_probe"] = {"status": "failed", "diagnostic": str(exc)}
    elif probe_runtime:
        result["load_probe"] = {"status": "not_available", "reason": "Node executable unavailable"}
    return result


def collect_diagnostics(*, template_path=None, node_path=None, node_modules=None, probe_runtime=False):
    """Return facts about bounded prerequisites; do not create files or Origin."""
    template = Path(template_path) if template_path else Path(__file__).resolve().parents[1] / "templates" / "publication_visual_template.yaml"
    yaml = _module("yaml", "PyYAML")
    pywin32 = {"modules": {name: _module(name) for name in ("win32com", "win32api")},
               "distribution_version": _distribution_version("pywin32")}
    pywin32["available"] = all(value["available"] for value in pywin32["modules"].values())
    origin = _origin_registration()
    required = {"python_at_least_3_7": sys.version_info >= (3, 7), "yaml_available": yaml["available"],
                "pywin32_available": pywin32["available"], "origin_com_registered": origin["registered"],
                "origin_registered_executable_available": origin.get("registered_executable_available", False),
                "visual_template_present": template.is_file()}
    return {"schema_version": 1, "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "bounded diagnostics; no Origin session, project reads, skill writes or environment dump",
            "python": {"executable": sys.executable, "version": platform.python_version(), "platform": sys.platform},
            "yaml": yaml, "pywin32": pywin32, "origin": origin,
            "visual_template": {"path": str(template), "present": template.is_file()},
            "image_runtime": _node_runtime(node_path, node_modules, probe_runtime),
            "static_prerequisites": required, "static_prerequisites_ok": all(required.values()),
            "origin_live_capabilities": {"status": "not_probed", "native_independent_y2": "requires live readback",
                                         "native_plot_binding": "requires save/reopen verification",
                                         "native_export": "requires real export and image inspection"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded plotting runtime diagnostics; never starts Origin")
    parser.add_argument("--static", action="store_true", help="skip the short Node/sharp load probe")
    parser.add_argument("--template", help="explicit visual template path")
    parser.add_argument("--node", help="explicit Node executable path")
    parser.add_argument("--node-modules", help="explicit Node package root")
    args = parser.parse_args(argv)
    result = collect_diagnostics(template_path=args.template, node_path=args.node,
                                 node_modules=args.node_modules, probe_runtime=not args.static)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["static_prerequisites_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
