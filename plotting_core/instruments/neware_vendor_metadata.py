"""Read explicitly labelled active-material mass using one validated NEWARE exporter.

Optional Windows-only metadata adapter. It neither replaces the raw decoder's
records/cycles nor interprets undocumented XML mass units. The installed vendor
components are copied into a new task-owned directory; no component is bundled,
registered or installed by this module. Only the tested NDC v2/type1 and exporter
build below are enabled. The caller must pass a task snapshot and task output.
"""
import csv
import ctypes
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


class NewareMetadataError(ValueError):
    """Metadata is unavailable; preserve raw extraction and ask for reliable mass."""


VALIDATED_COMPONENTS = {
    'BTSDAExReport.exe': 'b9f52e48bb1bd52e218987ec2379fb13a4ff6073a8243f383acd19823a5f3797',
    'Common.dll': '4c3bc66387cb02fff2b5af2e9d677a2e2847944e929a95bb131215601ee5b324',
    'BTSDALib.dll': '4b4f312a760c49dd9b97026c3a6131754b5881a12445f25fb5c0c2a672f8206e',
    'NdcReader.dll': '78e42ea754d0126776c02cbba9dd5ff4e2b1087cea1fa475fb769cf4f6a6d3d0',
}
VALIDATED_EXPORTER_VERSION = '8.0.0.43 (2022.12.26)'
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_XML = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _known_folder(number):
    buf = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, number, None, 0, buf) != 0:
        return None
    return Path(buf.value) if buf.value else None


def _shortcut_candidates():
    """Read existing vendor shortcuts; CreateShortcut is never followed by Save."""
    links = []
    for number in (0x10, 0x19, 0x0B, 0x17):  # user/public desktop, user/common start menu
        root = _known_folder(number)
        if root is None or not root.is_dir():
            continue
        for current, dirs, files in os.walk(str(root)):
            depth = len(Path(current).relative_to(root).parts)
            if depth >= 3:
                dirs[:] = []
            for name in files:
                if name.lower().endswith('.lnk') and re.search('btsda|btsclient|neware|新威', name, re.I):
                    links.append(str(Path(current) / name))
    if not links:
        return []
    env = dict(os.environ)
    env['BATTERY_PLOTTING_SHORTCUTS'] = json.dumps(links, ensure_ascii=False)
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
               "$paths=ConvertFrom-Json $env:BATTERY_PLOTTING_SHORTCUTS; "
               "$shell=New-Object -ComObject WScript.Shell; "
               "try { @($paths | ForEach-Object {$shell.CreateShortcut([string]$_).TargetPath}) | ConvertTo-Json -Compress } "
               "finally {[void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)}")
    try:
        raw = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                      env=env, timeout=15, creationflags=_NO_WINDOW)
        targets = json.loads(raw.decode('utf-8-sig').strip())
        if isinstance(targets, str):
            targets = [targets]
        return [Path(target).parent / 'BTSDAExReport.exe' for target in targets if target]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def _find_exporter(explicit):
    candidates = []
    if explicit is not None:
        path = Path(explicit)
        if not path.is_absolute():
            raise NewareMetadataError('exporter_path must be absolute')
        candidates.append(path)
    else:
        for key in ('NEWARE_EXPORTER_EXE', 'NEWARE_BTSDA_EXPORTER'):
            if os.environ.get(key):
                candidates.append(Path(os.environ[key]))
        located = shutil.which('BTSDAExReport.exe')
        if located:
            candidates.append(Path(located))
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for keyname in (r'Software\Microsoft\Windows\CurrentVersion\App Paths\BTSDA.exe',
                                r'Software\Microsoft\Windows\CurrentVersion\App Paths\BTSDAExReport.exe'):
                    try:
                        with winreg.OpenKey(hive, keyname) as key:
                            target = winreg.QueryValueEx(key, '')[0]
                        candidates.append(Path(target).parent / 'BTSDAExReport.exe')
                    except OSError:
                        pass
        except ImportError:
            pass
        candidates.extend(_shortcut_candidates())
    for path in candidates:
        if not path.is_absolute() or not path.is_file() or path.name.casefold() != 'btsdaexreport.exe':
            continue
        path = path.resolve()
        if all((path.parent / name).is_file() and _sha(path.parent / name) == digest
               for name, digest in VALIDATED_COMPONENTS.items()):
            return path
    raise NewareMetadataError('No validated BTSDAExReport 8.0.0.43 runtime found; '
                              'set exporter_path or NEWARE_EXPORTER_EXE to the installed exporter. '
                              'Other builds are not run automatically.')


def _reject_live_sessions():
    try:
        raw = subprocess.check_output(['tasklist.exe', '/FO', 'CSV', '/NH'],
                                      timeout=15, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NewareMetadataError('Cannot establish independent NEWARE offline session: %s' % exc)
    names = {row[0].lower() for row in csv.reader(io.StringIO(raw.decode('mbcs', errors='replace'))) if row}
    if names.intersection({'btsda.exe', 'btsdaexreport.exe', 'bts.exe', 'btsclient.exe'}):
        raise NewareMetadataError('An existing BTS/BTSDA/exporter session is running; '
                                  'metadata export skipped without disturbing it')


def _metadata_config(text):
    """Only the copied report selector changes; cycle/unit/scientific settings stay."""
    settings = {'HasUnit': 'True', 'HasChlInfo': 'True', 'HasCycle': 'False',
                'HasStep': 'False', 'HasRecord': 'False', 'HasCurve': 'False',
                'HasAux': 'False', 'HasLog': 'False', 'HasFree': 'False',
                'UnitTableName': 'unit', 'ChlInfoTableName': 'test'}
    found = re.search(r'(?ms)^\[CustomReport\]\s*\n(.*?)(?=^\[|\Z)', text)
    if found is None:
        raise NewareMetadataError('Existing vendor profile lacks the validated CustomReport section')
    section = found.group(0)
    for key, value in settings.items():
        pattern = r'(?m)^' + re.escape(key) + r'=[^\r\n]*'
        if not re.search(pattern, section):
            raise NewareMetadataError('Vendor profile is missing report selector ' + key)
        section = re.sub(pattern, key + '=' + value, section)
    return text[:found.start()] + section + text[found.end():]


def _column_index(reference):
    number = 0
    for char in re.sub(r'\d', '', reference):
        number = number * 26 + ord(char.upper()) - 64
    return number


def _extract_labelled_mass(report):
    with zipfile.ZipFile(str(report)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 32 * 1024 * 1024:
            raise NewareMetadataError('Metadata-only report unexpectedly exceeds 32MiB uncompressed')
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        sheets = workbook.find('s:sheets', _XML)
        if sheets is None or {sheet.get('name') for sheet in sheets} != {'unit', 'test'}:
            raise NewareMetadataError('Metadata export unexpectedly contains data/cycle/derived tables')
        relationships = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        by_id = {item.get('Id'): item.get('Target') for item in relationships}
        target = None
        for sheet in sheets:
            if sheet.get('name') == 'test':
                rid = sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                target = by_id[rid]
        if not target or '..' in Path(target).parts:
            raise NewareMetadataError('Invalid metadata test-sheet relationship')
        member = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(item.itertext()) for item in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        worksheet = ET.fromstring(archive.read(member))
        evidence = []
        for row in worksheet.findall('s:sheetData/s:row', _XML):
            values = []
            for cell in row:
                ref = cell.get('r', '')
                node = cell.find('s:v', _XML)
                value = node.text if node is not None else ''
                if cell.get('t') == 's':
                    value = strings[int(value)]
                elif cell.get('t') == 'inlineStr':
                    value = ''.join(cell.find('s:is', _XML).itertext())
                if value:
                    values.append((ref, value.strip()))
            values.sort(key=lambda item: _column_index(item[0]))
            for index, (ref, label) in enumerate(values):
                if label.casefold() not in {'活性物质', 'active material', 'active mass', 'active material mass'}:
                    continue
                if index + 1 >= len(values):
                    raise NewareMetadataError('Active-material label has no adjacent value')
                value_ref, display = values[index + 1]
                match = re.fullmatch(r'\s*([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(kg|g|mg|[uµμ]g|ng)\s*', display)
                if match is None:
                    raise NewareMetadataError('Active-material mass lacks an explicit supported unit: ' + display)
                number = float(match.group(1))
                factor = {'kg': 1000., 'g': 1., 'mg': 1e-3, 'ug': 1e-6,
                          'µg': 1e-6, 'μg': 1e-6, 'ng': 1e-9}[match.group(2)]
                mass = number * factor
                if not math.isfinite(mass) or mass <= 0:
                    raise NewareMetadataError('Active-material mass must be positive and finite')
                evidence.append({'sheet': 'test', 'label_cell': ref, 'label': label,
                                 'value_cell': value_ref, 'display_value': display, 'mass_g': mass})
        if len(evidence) != 1:
            raise NewareMetadataError('Expected exactly one explicitly labelled active-material mass; found %s' % len(evidence))
        return evidence[0]


def extract_active_mass(path, output_directory, exporter_path=None):
    """Return mass/provenance from a metadata-only report, or raise diagnostics.

    Pass an immutable task snapshot and task-owned output_directory. This function
    never falls back to undocumented mass fields, user profile edits or GUI work.
    Runtime detection uses explicit path, environment, app-path registry or an
    existing BTSDA shortcut. A running NEWARE session causes a clean refusal.
    """
    if os.name != 'nt':
        raise NewareMetadataError('NEWARE vendor metadata adapter requires Windows')
    source, output = Path(path), Path(output_directory)
    if not source.is_absolute() or not output.is_absolute():
        raise NewareMetadataError('Source snapshot and metadata output must use absolute paths')
    source, output = source.resolve(), output.resolve()
    if not source.is_file() or source.suffix.lower() != '.ndax':
        raise NewareMetadataError('Vendor metadata adapter currently accepts only NDAX NDC v2/type1')
    with zipfile.ZipFile(str(source)) as archive:
        with archive.open('data.ndc') as stream:
            header = stream.read(3)
        if len(header) != 3 or header[0] != 1 or header[2] != 2 or any(
                name in archive.namelist() for name in ('data_runInfo.ndc', 'data_step.ndc')):
            raise NewareMetadataError('Metadata exporter is validated only for non-sparse NDC v2/type1')
    exporter = _find_exporter(exporter_path)
    documents = _known_folder(0x05)
    if documents is None:
        raise NewareMetadataError('Cannot locate existing Windows Documents NEWARE profile')
    profile = (documents / 'NEWARE' / 'BTSClient').resolve()
    profile_config = profile / 'BTSDAConfig.iconf'
    if not profile_config.is_file():
        raise NewareMetadataError('Existing NEWARE BTSDAConfig.iconf profile is unavailable')
    if _inside(output, source.parent) or _inside(source, output) or any(
            _inside(output, protected) for protected in (exporter.parent, profile, Path(__file__).resolve().parents[2])):
        raise NewareMetadataError('Metadata output must be a separate task directory outside source/runtime/profile/skill')
    _reject_live_sessions()
    before_source, before_config = _sha(source), _sha(profile_config)
    config_text = _metadata_config(profile_config.read_text(encoding='utf-16'))
    run = output / ('metadata_' + uuid.uuid4().hex[:12])
    run.mkdir(parents=True, exist_ok=False)
    runtime, public = run / 'runtime', run / 'public_profile'
    runtime.mkdir()
    config_copy = public / 'Documents' / 'NEWARE' / 'BtsClient'
    config_copy.mkdir(parents=True)
    temp = run / 'temp'
    temp.mkdir()
    report = run / 'vendor_metadata.xlsx'
    manifest = {'ready': False, 'source_snapshot': str(source), 'source_sha256': before_source,
                'exporter_path': str(exporter), 'exporter_file_version': VALIDATED_EXPORTER_VERSION,
                'exporter_sha256': _sha(exporter), 'original_profile': str(profile_config),
                'original_profile_sha256_before': before_config,
                'metadata_only': True, 'native_records_or_cycles_replaced': False}
    started = time.time()
    process = None
    try:
        copied_bytes = 0
        for item in exporter.parent.iterdir():
            if item.is_file() and (item.suffix.lower() in ('.dll', '.ini') or item.name == exporter.name):
                shutil.copy2(str(item), str(runtime / item.name))
                copied_bytes += item.stat().st_size
        for name, digest in VALIDATED_COMPONENTS.items():
            if _sha(runtime / name) != digest:
                raise NewareMetadataError('Copied vendor component hash changed: ' + name)
        for item in profile.iterdir():
            if item.is_file() and item.suffix.lower() in ('.ini', '.iconf'):
                shutil.copy2(str(item), str(config_copy / item.name))
        (config_copy / profile_config.name).write_text(config_text, encoding='utf-16')
        (config_copy / 'BTSConfigLoc').write_text('[BTS]\nConfigPublic=1\n', encoding='ascii')
        snapshot = run / 'source.ndax'
        shutil.copy2(str(source), str(snapshot))
        if _sha(snapshot) != before_source or _sha(source) != before_source:
            raise NewareMetadataError('Source advanced during metadata snapshot; no mass is accepted')
        env = dict(os.environ)
        env.update(PUBLIC=str(public), TEMP=str(temp), TMP=str(temp))
        command = [str(runtime / exporter.name), 'export', 'custom', str(snapshot), str(report)]
        manifest.update(command=command, copied_runtime_bytes=copied_bytes,
                        isolated_public=str(public), report_file=str(report),
                        report_selectors={'HasUnit': True, 'HasChlInfo': True, 'HasCycle': False,
                                          'HasStep': False, 'HasRecord': False, 'HasCurve': False,
                                          'HasAux': False, 'HasLog': False, 'HasFree': False},
                        isolated_config_sha256=_sha(config_copy / profile_config.name))
        (run / 'metadata_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        process = subprocess.Popen(command, cwd=str(runtime), env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        try:
            stdout, stderr = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()  # only the exact child created above
            stdout, stderr = process.communicate()
            raise NewareMetadataError('Independent NEWARE metadata export timed out after 120 seconds')
        (run / 'export_stdout.txt').write_bytes(stdout)
        (run / 'export_stderr.txt').write_bytes(stderr)
        manifest.update(process_id=process.pid, returncode=process.returncode)
        if process.returncode != 0 or not report.is_file() or report.stat().st_size == 0:
            raise NewareMetadataError('Manufacturer metadata export did not produce a valid report')
        if _sha(source) != before_source or _sha(profile_config) != before_config:
            raise NewareMetadataError('Source or original profile changed during metadata export; result rejected')
        evidence = _extract_labelled_mass(report)
        result = {'mass_g': evidence['mass_g'], 'mass_basis': 'active_material',
                  'mass_source': 'NEWARE BTSDAExReport %s; %s; test!%s=%s; test!%s=%s' % (
                      VALIDATED_EXPORTER_VERSION, str(report), evidence['label_cell'], evidence['label'],
                      evidence['value_cell'], evidence['display_value']),
                  'source_sha256': before_source, 'source_snapshot_file': str(source),
                  'exporter_path': str(exporter), 'exporter_file_version': VALIDATED_EXPORTER_VERSION,
                  'exporter_sha256': manifest['exporter_sha256'],
                  'vendor_metadata_file': str(report), 'vendor_metadata_sha256': _sha(report),
                  'cell_evidence': evidence, 'metadata_manifest_file': str(run / 'metadata_manifest.json'),
                  'native_records_or_cycles_replaced': False}
        manifest.update(ready=True, result=result)
        return result
    except Exception as exc:
        manifest['error'] = '%s: %s' % (type(exc).__name__, exc)
        if isinstance(exc, NewareMetadataError):
            raise
        raise NewareMetadataError(str(exc)) from exc
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        # Delete only directories created in this exact unique run. Keep small
        # report/log/provenance artifacts, rather than retaining 70MB per import.
        for temporary in (runtime, public, temp):
            resolved = temporary.resolve()
            if resolved.parent != run.resolve() or temporary.name not in {'runtime', 'public_profile', 'temp'}:
                manifest['cleanup_error'] = 'Temporary path escaped the owned metadata run'
                continue
            if temporary == runtime and (temporary / 'LogData').is_dir():
                try:
                    shutil.copytree(str(temporary / 'LogData'), str(run / 'exporter_logs'))
                except OSError as exc:
                    manifest['log_copy_error'] = str(exc)
            try:
                shutil.rmtree(str(temporary))
            except OSError as exc:
                manifest['cleanup_error'] = str(exc)
        manifest['temporary_runtime_retained'] = runtime.exists()
        manifest['temporary_profile_retained'] = public.exists()
        manifest['elapsed_s'] = round(time.time() - started, 3)
        for field, original in (('source_sha256_after', source), ('original_profile_sha256_after', profile_config)):
            try:
                manifest[field] = _sha(original)
            except OSError as exc:
                manifest[field] = None
                manifest[field + '_error'] = str(exc)
        (run / 'metadata_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
