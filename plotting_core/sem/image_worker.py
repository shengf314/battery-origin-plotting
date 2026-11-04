"""Pillow/pypdf-only pixel helper; launched by the Python-3.7-compatible bridge."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image
from pypdf import PdfReader


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):
            digest.update(block)
    return digest.hexdigest()


def source_rgb(path):
    source=Image.open(path)
    if getattr(source,'n_frames',1)!=1:
        raise ValueError('SEM image transport accepts one frame; no frame is silently selected')
    source.load()
    bits=source.tag_v2.get(258) if hasattr(source,'tag_v2') else None
    if bits is not None:
        bits=bits if isinstance(bits,(tuple,list)) else [bits]
        if any(int(value)!=8 for value in bits):
            raise ValueError('SEM image transport accepts only 8bit samples; no implicit bit-depth conversion')
    if source.format=='PNG':
        header=Path(path).read_bytes()[:26]
        if header[:8]==b'\x89PNG\r\n\x1a\n' and header[24]!=8:
            raise ValueError('SEM PNG samples must be 8bit; no implicit bit-depth conversion')
    if source.mode not in ('L','RGB','RGBA'):
        raise ValueError('SEM image transport accepts L/RGB/RGBA8 only, not '+source.mode)
    orientation=source.getexif().get(274,1)
    if int(orientation)!=1:
        raise ValueError('SEM orientation metadata must be resolved explicitly before unrotated pixel transport')
    if source.mode=='RGBA' or source.info.get('transparency') is not None:
        alpha=source.convert('RGBA').getchannel('A')
        if alpha.getextrema()!=(255,255):
            raise ValueError('SEM source contains non-opaque pixels; no transparency is silently flattened')
    if source.mode=='L' and source.info.get('icc_profile'):
        raise ValueError('Grayscale ICC interpretation needs an explicit color-management method; no profile conversion is inferred')
    rgb=source.convert('RGB')
    # Construct a clean pixel container. No source LUT, alpha, DPI, crop or
    # intensity adjustment is copied into Illustrator's import path.
    clean=Image.frombytes('RGB',source.size,rgb.tobytes())
    profile=source.info.get('icc_profile') if source.mode in ('RGB','RGBA') else None
    return source,clean,profile


def prepare(request):
    source_path=Path(request['source_file'])
    source,rgb,profile=source_rgb(source_path)
    target=Path(request['transport_file'])
    if target.exists():
        raise FileExistsError('SEM lossless transport must be a new file')
    save_options={'icc_profile':profile} if profile else {}
    rgb.save(target,format='PNG',**save_options)
    with Image.open(target) as reopened:
        reopened.load()
        valid=(reopened.mode=='RGB' and reopened.size==source.size and reopened.tobytes()==rgb.tobytes()
               and 'A' not in reopened.getbands() and reopened.info.get('transparency') is None)
    if not valid:
        raise RuntimeError('Lossless RGB transport lost source samples or introduced transparency')
    return dict(ok=True,file=str(target),sha256=sha(target),source_file=str(source_path),
        source_sha256=request['source_sha256'],width_px=source.width,height_px=source.height,mode='RGB',
        source_mode=source.mode,pixel_verified=True,alpha='none; all output pixels fully opaque',
        conversion='Lossless source L-to-three-equal-RGB-channels or unchanged RGB samples; no resampling, crop, enhancement or intensity change',
        icc_profile_preserved=bool(profile),source_lut_or_print_dpi_used=False)


def verify(request):
    source_path=Path(request['source_file'])
    source,expected,_=source_rgb(source_path)
    expected_bytes=expected.tobytes()
    ai_path=Path(request['ai_file'])
    reader=PdfReader(ai_path)
    evidence=[]
    for page_index,page in enumerate(reader.pages):
        for key in page.images.keys():
            image=page.images[key]
            decoded=image.image;decoded.load()
            item=dict(page=page_index+1,key=str(key),width_px=decoded.width,height_px=decoded.height,
                      mode=decoded.mode,dimensions_match=decoded.size==source.size,
                      rgb_samples_equal=False,fully_opaque=False,pixel_exact=False)
            if item['dimensions_match']:
                actual=decoded.convert('RGB')
                item['rgb_samples_equal']=actual.tobytes()==expected_bytes
                if 'A' in decoded.getbands():
                    extrema=decoded.getchannel('A').getextrema()
                    item['alpha_range']=list(extrema)
                    item['fully_opaque']=extrema==(255,255)
                elif decoded.info.get('transparency') is not None:
                    extrema=decoded.convert('RGBA').getchannel('A').getextrema()
                    item['alpha_range']=list(extrema)
                    item['fully_opaque']=extrema==(255,255)
                else:
                    item['fully_opaque']=True
                    item['alpha_range']=[255,255]
                item['pixel_exact']=item['rgb_samples_equal'] and item['fully_opaque']
            evidence.append(item)
    matching=[item for item in evidence if item['dimensions_match']]
    checks=dict(source_sha256_matches=sha(source_path)==request['source_sha256'],
                ai_sha256_matches=sha(ai_path)==request['ai_sha256'],
                full_source_dimensions_found=bool(matching),
                full_source_rgb_samples_equal=bool(matching) and all(item['rgb_samples_equal'] for item in matching),
                full_source_pixels_fully_opaque=bool(matching) and all(item['fully_opaque'] for item in matching),
                full_source_pixel_exact=bool(matching) and all(item['pixel_exact'] for item in matching))
    return dict(ok=all(checks.values()),checks=checks,images=evidence,source_file=str(source_path),
                source_sha256=request['source_sha256'],ai_file=str(ai_path),ai_sha256=request['ai_sha256'],
                source_size_px=list(source.size),source_mode=source.mode,
                method='Decode embedded PDF image samples; L source maps to equal RGB channels; require actual alpha255, not object opacity alone',
                screenshot_used_for_pixel_verification=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True)
    parser.add_argument('--report',required=True)
    args=parser.parse_args()
    report=dict(ok=False)
    try:
        request=json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
        if request.get('schema_version')!=1 or request.get('operation') not in ('prepare','verify'):
            raise ValueError('Invalid SEM image worker request')
        if sha(request['source_file'])!=request['source_sha256']:
            raise ValueError('SEM source hash differs from pixel-helper request')
        report=prepare(request) if request['operation']=='prepare' else verify(request)
        if sha(request['source_file'])!=request['source_sha256']:
            raise ValueError('SEM source changed during lossless processing')
        return 0
    except Exception as exc:
        report=dict(ok=False,error_type=type(exc).__name__,error=str(exc))
        return 2
    finally:
        Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    sys.exit(main())
