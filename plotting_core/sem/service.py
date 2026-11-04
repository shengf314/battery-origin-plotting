"""Task-owned SEM snapshots and native Adobe output, separate from curve plots."""
import copy
import datetime
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path


def _hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):
            digest.update(block)
    return digest.hexdigest()


def _write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def check_sem(document):
    from .plan import prepare_sem
    return prepare_sem(document)


def _invalid_plan(document,error):
    report=dict(ready=False,stage='request_or_plan',adobe_executed=False,errors=[str(error)])
    # Only record a failed attempt when its independent task destination can be
    # established safely without relying on the invalid scientific parameters.
    try:
        if not isinstance(document,dict):return report
        name=document.get('task_name')
        if not isinstance(name,str) or not name or name in ('.','..') or re.search(r'[\\/:*?"<>|]',name):return report
        output=Path(document.get('output_root',''));source=Path(document.get('source',{}).get('file',''))
        if not output.is_absolute() or not source.is_absolute():return report
        output,source=output.resolve(),source.resolve()
        skill=Path(__file__).resolve().parents[2]
        if any(target==skill or skill in target.parents or target==source.parent or source.parent in target.parents
               for target in (output,(output/name).resolve())):return report
        root=output/name;attempt=datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:8]
        directory=root/'attempts'/attempt;directory.mkdir(parents=True,exist_ok=False)
        report.update(attempt_id=attempt,task_dir=str(directory))
        _write(directory/'sem_check.json',report)
        _write(root/'current_sem.json',dict(ready=False,stage=report['stage'],attempt_id=attempt,report=str(directory/'sem_check.json')))
    except (TypeError,ValueError,OSError,AttributeError):
        pass
    return report


def execute_sem(document):
    # Plan validation precedes any output directory creation, including source
    # directory protection. A failure does not inherit a previous accepted AI.
    try:
        plan=check_sem(document)
    except Exception as exc:
        return _invalid_plan(document,exc)
    root=Path(document['output_root']).resolve()/document['task_name']
    attempt=datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:8]
    directory=root/'attempts'/attempt
    directory.mkdir(parents=True,exist_ok=False)
    report=dict(ready=False,stage='snapshot',attempt_id=attempt,task_dir=str(directory),
                source_modified=False,reference_opened_in_illustrator=False,errors=[])
    _write(root/'current_sem.json',dict(ready=False,stage='running',attempt_id=attempt,report=str(directory/'sem_check.json')))
    try:
        _write(directory/'sem_request.json',document)
        original=Path(plan['source']['file'])
        source_dir=directory/'source';source_dir.mkdir()
        snapshot=source_dir/original.name
        shutil.copy2(str(original),str(snapshot))
        if _hash(original)!=plan['source']['sha256'] or _hash(snapshot)!=plan['source']['sha256']:
            raise ValueError('SEM source changed while copying; no image or ruler is accepted')
        plan=copy.deepcopy(plan)
        plan['source']['original_file']=str(original)
        plan['source']['file']=str(snapshot)
        # Illustrator can import some grayscale TIFF metadata as an unintended
        # soft mask. Use an opaque RGB transport with verified identical pixels;
        # retain the original TIFF and its calibration identity separately.
        from .image_bridge import prepare_transport
        plan['transport']=prepare_transport(str(snapshot),directory/'transport')
        if plan['transport']['source_sha256']!=plan['source']['sha256']:
            raise ValueError('SEM transport refers to a different source snapshot')
        _write(directory/'sem_plan.json',plan)
        from .illustrator import render_sem
        report['stage']='native_illustrator'
        native=render_sem(plan,directory)
        report.update(ready=native['ready'],stage='native_ai_saved_and_reopened',
                      native=native,ai_file=native['ai_file'],source_sha256=plan['source']['sha256'],
                      source_unchanged=_hash(original)==plan['source']['sha256'],
                      image_editing='native clipping only; full original raster embedded; no intensity processing')
        if not report['source_unchanged']:
            report['ready']=False
            raise ValueError('Original SEM source changed during rendering; review the captured snapshot identity')
        return report
    except Exception as exc:
        report.update(ready=False,stage='failed',exception_type=type(exc).__name__)
        report['errors'].append(str(exc))
        return report
    finally:
        _write(directory/'sem_check.json',report)
        _write(root/'current_sem.json',dict(ready=report['ready'],stage=report['stage'],attempt_id=attempt,report=str(directory/'sem_check.json')))
