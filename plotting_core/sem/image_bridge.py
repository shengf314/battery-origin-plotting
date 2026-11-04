"""Isolated lossless SEM image transport and saved-AI pixel verification."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

SKILL_ROOT=Path(__file__).resolve().parents[2]
NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0)


def _sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):
            digest.update(block)
    return digest.hexdigest()


def _inside(path,root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _python():
    explicit=os.environ.get('SEM_IMAGE_PYTHON')
    if explicit:
        candidates=[Path(explicit)]
    else:
        candidates=[Path(sys.executable),Path(os.environ.get('USERPROFILE',str(Path.home())))/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe']
    diagnostics=[]
    env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1'
    for candidate in candidates:
        if not candidate.is_absolute() or not candidate.is_file():
            diagnostics.append(str(candidate)+': not an installed absolute interpreter')
            continue
        try:
            process=subprocess.run([str(candidate),'-B','-X','utf8','-c',
                'import json,sys,PIL,pypdf;print(json.dumps({"python":sys.version,"pillow":PIL.__version__,"pypdf":pypdf.__version__}))'],
                cwd=str(SKILL_ROOT),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                encoding='utf-8',errors='replace',timeout=15,creationflags=NO_WINDOW)
            if process.returncode==0:
                return candidate,json.loads(process.stdout)
            diagnostics.append(str(candidate)+': '+process.stderr[-600:].strip())
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            diagnostics.append(str(candidate)+': '+str(exc))
    raise RuntimeError('SEM pixel validation needs an installed Python with Pillow and pypdf; '
        'set SEM_IMAGE_PYTHON or use the existing Codex bundled runtime. No dependencies are installed automatically. '+ '; '.join(diagnostics))


def _execute(operation,source_path,directory,ai_path=None):
    source,output=Path(source_path),Path(directory)
    if not source.is_absolute() or not source.is_file() or not output.is_absolute():
        raise ValueError('SEM pixel helper source and output directory must use absolute existing-source paths')
    source,output=source.resolve(),output.resolve()
    if _inside(output,source.parent) or _inside(output,SKILL_ROOT):
        raise ValueError('SEM pixel helper outputs must stay outside source and skill directories')
    python,environment=_python()
    run=output/('image_'+operation+'_'+uuid.uuid4().hex[:12])
    run.mkdir(parents=True,exist_ok=False)
    request=dict(schema_version=1,operation=operation,source_file=str(source),source_sha256=_sha(source))
    if operation=='prepare':
        request['transport_file']=str(run/'sem_lossless_rgb.png')
    else:
        ai=Path(ai_path)
        if not ai.is_absolute() or not ai.is_file():
            raise ValueError('Saved AI pixel verification needs an existing absolute file')
        request.update(ai_file=str(ai.resolve()),ai_sha256=_sha(ai))
    request_path=run/'request.json';report_path=run/'report.json'
    request_path.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    command=[str(python),'-B','-X','utf8',str(Path(__file__).with_name('image_worker.py')),
             '--request',str(request_path),'--report',str(report_path)]
    env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1'
    try:
        process=subprocess.run(command,cwd=str(SKILL_ROOT),env=env,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,encoding='utf-8',errors='replace',timeout=120,creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Owned SEM image worker exceeded 120 seconds; no pixel pass is inferred') from exc
    (run/'worker_stdout.txt').write_text(process.stdout,encoding='utf-8')
    (run/'worker_stderr.txt').write_text(process.stderr,encoding='utf-8')
    if not report_path.is_file():
        raise RuntimeError('SEM image worker produced no report: '+process.stderr[-1000:])
    result=json.loads(report_path.read_text(encoding='utf-8-sig'))
    result.update(report_file=str(report_path),request_file=str(request_path),worker_python=str(python),environment=environment)
    if _sha(source)!=request['source_sha256']:
        raise RuntimeError('SEM source changed during pixel processing; reject this attempt')
    if process.returncode!=0:
        raise RuntimeError('SEM image worker failed: '+result.get('error',process.stderr[-1000:])+'; report='+str(report_path))
    return result


def prepare_transport(source_path,directory):
    """Create an unresampled, alpha-free RGB PNG with exact source samples."""
    result=_execute('prepare',source_path,directory)
    if not result.get('ok') or not result.get('pixel_verified'):
        raise RuntimeError('Lossless SEM transport verification did not pass')
    return result


def verify_ai_pixels(ai_path,source_path,directory):
    """Compare full PDF image samples and actual alpha, independently of opacity."""
    return _execute('verify',source_path,directory,ai_path)
