"""Owned source snapshots -> vendor readers -> existing standard plotting input."""
import copy
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

VENDORS = {'land': ('.cex',), 'neware': ('.nda', '.ndax')}
READERS = {'land': ('land_reader', 'read_land'), 'neware': ('neware_reader', 'read_neware')}
SKILL_ROOT = Path(__file__).resolve().parents[2]


class UnsafeInstrumentOutput(ValueError):
    """Do not create a failure report in a protected input/skill directory."""


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def read_json(path):
    result = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('Request must be a JSON object')
    return result


def detect_vendor(path, vendor='auto'):
    suffix = Path(path).suffix.lower()
    selected = [name for name, extensions in VENDORS.items() if suffix in extensions]
    if vendor == 'auto':
        if len(selected) != 1:
            raise ValueError('Choose measured LAND .cex or NEWARE .nda/.ndax data; legacy .res and protocol-only files are not verified inputs')
        return selected[0]
    if vendor not in VENDORS or suffix not in VENDORS[vendor]:
        raise ValueError('Vendor and project extension conflict; no fallback parser is selected')
    return vendor


def _destination(output_root):
    path = Path(output_root)
    if not path.is_absolute():
        raise ValueError('Instrument output_root must be an absolute independent task directory')
    path = path.resolve()
    if path == SKILL_ROOT or SKILL_ROOT in path.parents:
        raise UnsafeInstrumentOutput('Instrument import outputs must be outside the installed skill')
    return path


def _check_output_source_separation(root, request):
    # Check before creating even a failure report: the source directory is
    # read-only, not just the source file. Invalid requests are validated later.
    sources = request.get('sources', []) if isinstance(request, dict) else []
    if not isinstance(sources, list):
        return
    for item in sources:
        value = item.get('file') if isinstance(item, dict) else None
        if not isinstance(value, str) or not value:
            continue
        source = Path(value)
        if not source.is_absolute():
            continue
        source = source.resolve()
        if root == source.parent or source.parent in root.parents:
            raise UnsafeInstrumentOutput('Choose an independent output_root outside the source measurement directory')


def _source(request):
    if not isinstance(request, dict):
        raise ValueError('Each instrument source must be an object')
    path = Path(request.get('file', ''))
    if not path.is_absolute() or not path.is_file():
        raise ValueError('Each source.file must be an existing absolute measurement file')
    return path.resolve()


def _snapshot(source, directory, number):
    before = file_hash(source)
    target = directory / 'sources' / ('source_%02d%s' % (number, source.suffix.lower()))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(target))
    copied, after = file_hash(target), file_hash(source)
    if before != copied or before != after:
        raise ValueError('Source changed during snapshot; obtain a consistent saved project and retry: ' + str(source))
    return target, dict(file=str(source), sha256=before, snapshot_file=str(target),
                        snapshot_sha256=copied, captured_at=datetime.datetime.utcnow().isoformat()+'Z')


def _read(path, vendor, options):
    # Vendor DLLs and optional modern parsers are isolated from this process.
    # A decoder failure cannot leave the import pointer claiming old success.
    output=path.parent/('decoded_'+path.stem+'.json')
    command=[sys.executable,'-B','-X','utf8','-m','plotting_core.instruments.worker',
             '--vendor',vendor,'--file',str(path),'--options',json.dumps(options or {},ensure_ascii=False),
             '--output',str(output)]
    try:
        process=subprocess.run(command,cwd=str(SKILL_ROOT),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                               encoding='utf-8',errors='replace',timeout=300,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Owned instrument decoder exceeded 300 seconds and was stopped; source snapshot and attempt remain for diagnosis') from exc
    path.with_suffix(path.suffix+'.worker.stdout.txt').write_text(process.stdout,encoding='utf-8')
    path.with_suffix(path.suffix+'.worker.stderr.txt').write_text(process.stderr,encoding='utf-8')
    if process.returncode!=0 or not output.is_file():
        raise RuntimeError('Instrument decoder failed (exit %s): %s' % (process.returncode,process.stderr[-2000:]))
    result=read_json(output)
    if not isinstance(result, dict) or not isinstance(result.get('records'), list):
        raise ValueError('Vendor reader did not return an explicit native record list')
    return result


def _request_sources(request, inspection):
    if not isinstance(request, dict) or request.get('schema_version') != 1 or isinstance(request.get('schema_version'), bool):
        raise ValueError('schema_version=1 is required')
    allowed = {'schema_version','plot_type','sources','cycles','branches','task_name','source'}
    if set(request)-allowed:
        raise ValueError('Unknown instrument request fields: '+', '.join(sorted(set(request)-allowed)))
    sources = request.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('sources must be a nonempty list of measured projects')
    source_keys = {'file','vendor','sample','mass_g','mass_source',
                   'rates_by_cycle','rate_source','reader_options'}
    for item in sources:
        _source(item)
        if set(item)-source_keys:
            raise ValueError('Unknown source fields: '+', '.join(sorted(set(item)-source_keys)))
        if not isinstance(item.get('reader_options', {}), dict):
            raise ValueError('reader_options must be an explicit object')
        detect_vendor(item['file'], item.get('vendor','auto'))
    if not inspection and request.get('plot_type') not in ('gcd','cycle_performance','rate_capability'):
        raise ValueError('Instrument import supports GCD, cycle performance and rate capability; other plot families retain their existing inputs')
    return sources


def run_import(request, output_root, *, inspection=False, render=False, readers=None):
    """Create one auditable attempt; never mutate a source or a user application.

    A live source can advance after capture. All results bind the consistent
    snapshot hash, with a distinct current-source hash recorded for disclosure.
    """
    root = _destination(output_root)
    _check_output_source_separation(root, request)
    attempt = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:8]
    directory = root/'attempts'/attempt
    directory.mkdir(parents=True,exist_ok=False)
    outcome = dict(ready=False,stage='validate_request',attempt_id=attempt,task_dir=str(directory),
                   mode='inspect' if inspection else 'prepare',questions=[],errors=[],
                   origin_executed=False,source_files_written=False,import_accepted=False,
                   scientific_truth_verified=False)
    write_json(directory/'import_check.json',outcome)
    write_json(root/'current_import.json',dict(attempt_id=attempt,ready=False,
               stage='running',import_accepted=False,report=str(directory/'import_check.json')))
    try:
        write_json(directory/'request.json',request)
        sources = _request_sources(request,inspection)
        identities = [str(_source(item)) for item in sources]
        if len(set(identities)) != len(identities):
            raise ValueError('The same source file was selected more than once; no deduplication is performed')
        datasets, snapshots, seen = [], [], {}
        for index,item in enumerate(sources,1):
            source = _source(item)
            outcome['stage']='snapshot_source_%d'%index
            snapshot,identity=_snapshot(source,directory,index)
            if identity['sha256'] in seen:
                raise ValueError('Duplicate source SHA256 selected: %s and %s; no test is silently dropped' % (seen[identity['sha256']],source))
            seen[identity['sha256']]=str(source)
            vendor=detect_vendor(source,item.get('vendor','auto'))
            outcome['stage']='read_%s_%d'%(vendor,index)
            options=copy.deepcopy(item.get('reader_options') or {})
            if options.get('include_records',True) is not True:
                raise ValueError('Instrument import requires every native record; metadata-only decode is not a plotting input')
            for key in ('snapshot_directory','records_output'):
                if key in options:
                    option_path=Path(options[key])
                    if not option_path.is_absolute() or directory.resolve() not in option_path.resolve().parents:
                        raise ValueError('Reader output option %s must remain inside this import attempt' % key)
            if readers is None:
                dataset=_read(snapshot,vendor,options)
            else:
                dataset=readers[vendor](str(snapshot),options=options)
            if file_hash(snapshot)!=identity['snapshot_sha256']:
                raise RuntimeError('Vendor reader modified its source snapshot; import is rejected')
            if not isinstance(dataset,dict) or not isinstance(dataset.get('records'),list):
                raise ValueError('Native reader must return records without silent filtering')
            identity['current_source_sha256']=file_hash(source)
            identity['source_advanced_after_snapshot']=identity['current_source_sha256']!=identity['sha256']
            dataset['original_source']=identity
            dataset.setdefault('vendor',vendor)
            dataset['decoder_source_identity']=copy.deepcopy(dataset.get('source') or {})
            dataset.setdefault('source',{}).update(snapshot_file=str(snapshot),snapshot_sha256=identity['snapshot_sha256'],
                                                   snapshot_retained=True,snapshot_owner='instrument_import_service')
            raw=directory/('native_%02d.json'%index)
            write_json(raw,dataset)
            snapshots.append(dict(vendor=vendor,source=identity,raw_file=str(raw),raw_sha256=file_hash(raw),
                                  records=len(dataset['records']),steps=len(dataset.get('steps',[])),
                                  cycles=len(dataset.get('cycles',[])),metadata=dataset.get('metadata',{}),
                                  issues=dataset.get('issues',[])))
            datasets.append(dataset)
        outcome['native_sources']=snapshots
        if inspection:
            outcome.update(ready=True,stage='native_records_extracted',remaining_stages=['target selection and scientific input validation','standard plotting input','Origin rendering and figure acceptance'])
        else:
            from .standardize import standardize
            outcome['stage']='standardize'
            bridge=standardize(request,datasets,directory/'standard')
            outcome['standardization']=bridge
            outcome['questions']=bridge.get('questions',[])
            outcome['errors']=bridge.get('errors',[])
            if not bridge.get('ready'):
                outcome['stage']='blocked'
                return outcome
            outcome.update(ready=True,stage='standard_input_verified',import_accepted=True,
                           plot_spec=bridge['plot_spec'])
            if render:
                from ..models import PlotSpec
                from ..pipeline import render_plot
                outcome['origin_execution_attempted']=True
                outcome['origin_executed']=None
                render_spec=PlotSpec.from_file(bridge['plot_spec'])
                outcome['render_task_dir']=str(Path(render_spec.output_root)/render_spec.task_name)
                rendered=render_plot(render_spec,qa_level=3)
                outcome.update(stage='imported_and_rendered',origin_executed=True,
                               render=dict(task_dir=rendered.task_dir,accepted=rendered.accepted,
                                           automatic_checks_passed=rendered.export_report.get('automatic_checks_passed'),
                                           files=rendered.files))
            outcome['remaining_stages']=(['Origin render, saved-binding and editability verification','actual image inspection'] if not render else ['actual image inspection and hash-bound review'])
        return outcome
    except Exception as exc:
        outcome.update(ready=False,stage='failed',exception_type=type(exc).__name__)
        if outcome.get('origin_execution_attempted'):
            state=Path(outcome['render_task_dir'])/'run_state.json'
            if state.is_file():
                outcome['origin_executed']=read_json(state).get('origin_executed')
        outcome['errors'].append(str(exc))
        return outcome
    finally:
        write_json(directory/'import_check.json',outcome)
        write_json(root/'current_import.json',dict(attempt_id=attempt,ready=outcome['ready'],
                    stage=outcome['stage'],import_accepted=outcome['import_accepted'],
                    report=str(directory/'import_check.json')))


def record_request_failure(output_root, error, request_path=None):
    root=_destination(output_root)
    attempt=datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:8]
    directory=root/'attempts'/attempt
    directory.mkdir(parents=True,exist_ok=False)
    report=dict(ready=False,stage='request',attempt_id=attempt,task_dir=str(directory),
                request_path=request_path,errors=[str(error)],questions=[],import_accepted=False,
                origin_executed=False,source_files_written=False)
    write_json(directory/'import_check.json',report)
    write_json(root/'current_import.json',dict(attempt_id=attempt,ready=False,stage='request',
               import_accepted=False,report=str(directory/'import_check.json')))
    return report
