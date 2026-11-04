"""Explicit SEM calibration/crop contract; header reads never modify pixels."""
import hashlib
import io
import math
import re
import struct
from pathlib import Path

SKILL_ROOT=Path(__file__).resolve().parents[2]
UNITS={'nm':.001,'um':1.,'µm':1.,'μm':1.,'mm':1000.}
STYLE_KEYS={'bar_height_pt','bar_left_pt','bar_bottom_pt','label_gap_pt',
            'scale_font','scale_font_size_pt','panel_font','panel_font_size_pt',
            'panel_left_pt','panel_top_pt','bar_color_rgb','text_color_rgb','panel_label'}


def finite(value,label,positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(label+' must be a finite number')
    value=float(value)
    if positive and value<=0:
        raise ValueError(label+' must be positive')
    return value


def keys(value,allowed,label,required=()):
    if not isinstance(value,dict):
        raise ValueError(label+' must be an object')
    extra=set(value)-set(allowed)
    missing=set(required)-set(value)
    if extra: raise ValueError(label+' has unsupported fields: '+', '.join(sorted(extra)))
    if missing: raise ValueError(label+' lacks fields: '+', '.join(sorted(missing)))


def text(value,label):
    if not isinstance(value,str) or not value.strip():
        raise ValueError(label+' must be explicit nonempty text')
    return value


def point(value,label):
    if not isinstance(value,(list,tuple)) or len(value)!=2:
        raise ValueError(label+' must contain two source-pixel coordinates')
    return [finite(v,label) for v in value]


def rectangle(value,label):
    if not isinstance(value,(list,tuple)) or len(value)!=4:
        raise ValueError(label+' must contain [left,top,right,bottom] in source pixels')
    box=[finite(v,label) for v in value]
    if box[0]>=box[2] or box[1]>=box[3]:
        raise ValueError(label+' must have positive width and height')
    return box


def inside(box,outer):
    return box[0]>=outer[0] and box[1]>=outer[1] and box[2]<=outer[2] and box[3]<=outer[3]


def unit(value,label):
    if not isinstance(value,str) or value not in UNITS:
        raise ValueError(label+' must explicitly be nm, um/µm/μm or mm')
    return value,UNITS[value]


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''): h.update(block)
    return h.hexdigest()


def _read(f,count):
    value=f.read(count)
    if len(value)!=count: raise ValueError('Truncated image header')
    return value


def _tiff(f,require_size=True):
    """Read ordinary TIFF IFD dimensions/orientation, not raster samples."""
    f.seek(0); header=_read(f,8)
    endian='<' if header[:2]==b'II' else '>' if header[:2]==b'MM' else None
    if endian is None or struct.unpack(endian+'H',header[2:4])[0]!=42:
        raise ValueError('Only ordinary TIFF is supported; BigTIFF/unknown headers need a verified reader')
    offset=struct.unpack(endian+'I',header[4:8])[0]
    f.seek(offset); count=struct.unpack(endian+'H',_read(f,2))[0]
    if count>4096: raise ValueError('Unreasonable TIFF IFD count')
    values={}
    for _ in range(count):
        entry=_read(f,12)
        tag,kind,n=struct.unpack(endian+'HHI',entry[:8])
        if tag in (256,257,274) and n==1 and kind in (3,4):
            if tag in values: raise ValueError('Ambiguous duplicate TIFF dimension/orientation tag')
            values[tag]=struct.unpack(endian+('H' if kind==3 else 'I'),entry[8:10 if kind==3 else 12])[0]
    next_ifd=struct.unpack(endian+'I',_read(f,4))[0]
    if require_size and next_ifd:
        raise ValueError('Multi-frame TIFF needs an explicit frame workflow; no frame is silently selected')
    orientation=values.get(274,1)
    if orientation!=1:
        raise ValueError('Image orientation must be top-left (1); automatic orientation changes would invalidate pixel calibration')
    if require_size and (256 not in values or 257 not in values):
        raise ValueError('TIFF dimensions are missing or not supported scalar tags')
    return values.get(256),values.get(257),orientation


def image_info(path):
    """Determine dimensions from TIFF/PNG/JPEG; decode/raster acceptance is separate."""
    path=Path(path)
    with path.open('rb') as f:
        signature=f.read(8)
        if signature[:2] in (b'II',b'MM'):
            if path.suffix.lower() not in ('.tif','.tiff'): raise ValueError('TIFF header and extension conflict')
            width,height,orientation=_tiff(f)
            kind='TIFF'
        elif signature==b'\x89PNG\r\n\x1a\n':
            if path.suffix.lower()!='.png': raise ValueError('PNG header and extension conflict')
            length,tag=struct.unpack('>I4s',_read(f,8))
            if tag!=b'IHDR' or length!=13: raise ValueError('Invalid PNG IHDR')
            width,height=struct.unpack('>II',_read(f,13)[:8]);_read(f,4)
            orientation=1;kind='PNG'
            while True:
                raw=f.read(8)
                if len(raw)!=8: raise ValueError('PNG lacks an intact IEND')
                length,tag=struct.unpack('>I4s',raw)
                if tag==b'acTL': raise ValueError('Animated PNG is not a single SEM frame')
                if tag==b'eXIf':
                    if length>1048576: raise ValueError('Oversized PNG EXIF metadata')
                    _tiff(io.BytesIO(_read(f,length)),False)
                else: f.seek(length,1)
                _read(f,4)
                if tag==b'IEND': break
        elif signature[:2]==b'\xff\xd8':
            if path.suffix.lower() not in ('.jpg','.jpeg'): raise ValueError('JPEG header and extension conflict')
            f.seek(2);width=height=None;orientation=1;kind='JPEG'
            sof={0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF}
            while True:
                if _read(f,1)!=b'\xff': raise ValueError('Invalid JPEG marker sequence')
                marker=_read(f,1)[0]
                while marker==0xFF: marker=_read(f,1)[0]
                if marker in (0xD9,0xDA): break
                if marker==0x01 or 0xD0<=marker<=0xD7: continue
                length=struct.unpack('>H',_read(f,2))[0]-2
                if length<0: raise ValueError('Invalid JPEG marker length')
                segment=_read(f,length)
                if marker in sof:
                    if len(segment)<5: raise ValueError('Truncated JPEG dimensions')
                    height,width=struct.unpack('>HH',segment[1:5])
                elif marker==0xE1 and segment.startswith(b'Exif\0\0'):
                    _tiff(io.BytesIO(segment[6:]),False)
                elif marker==0xE2 and segment.startswith(b'MPF\0'):
                    raise ValueError('Multi-picture JPEG needs an explicit frame workflow')
            if width is None or height is None: raise ValueError('JPEG has no supported SOF dimensions')
        else:
            raise ValueError('SEM source must have a supported TIFF, PNG or JPEG header')
    if not width or not height: raise ValueError('Image dimensions must be positive')
    return dict(format=kind,width_px=int(width),height_px=int(height),orientation=orientation,
                validation_scope='header dimensions and orientation; no pixel decoding or image alteration')


def normalize(document):
    allowed={'schema_version','task_name','output_root','source','calibration','image_region_px','crop_px','panel','scale_bar','style'}
    keys(document,allowed,'SEM request',allowed)
    if not isinstance(document['schema_version'],int) or isinstance(document['schema_version'],bool) or document['schema_version']!=1: raise ValueError('schema_version must be integer 1')
    task=text(document['task_name'],'task_name')
    if task in ('.','..') or re.search(r'[<>:"/\\|?*\x00-\x1f]',task) or task.endswith((' ','.')) or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',task,re.I):
        raise ValueError('task_name must be a safe single directory name')
    keys(document['source'],{'file'},'source',{'file'})
    source=Path(text(document['source']['file'],'source.file'))
    if not source.is_absolute() or not source.is_file(): raise ValueError('source.file must be an existing absolute image path')
    source=source.resolve()
    output=Path(text(document['output_root'],'output_root'))
    if not output.is_absolute(): raise ValueError('output_root must be an absolute independent task directory')
    output=output.resolve()
    if output.exists() and not output.is_dir(): raise ValueError('output_root is not a directory')
    for target in (output,output/task):
        if target==source.parent or source.parent in target.parents or target==SKILL_ROOT or SKILL_ROOT in target.parents:
            raise ValueError('SEM output must remain outside source-image and installed-skill directories')
    info=image_info(source)
    full=[0.,0.,float(info['width_px']),float(info['height_px'])]
    region=rectangle(document['image_region_px'],'image_region_px')
    crop=rectangle(document['crop_px'],'crop_px')
    if not inside(region,full): raise ValueError('image_region_px escapes original source pixels')
    if not inside(crop,region): raise ValueError('crop_px must stay inside the verified SEM image region; do not include the instrument footer')
    calibration=document['calibration']
    keys(calibration,{'length','unit','start_px','end_px','source'},'calibration',{'length','unit','start_px','end_px','source'})
    length=finite(calibration['length'],'calibration.length',True)
    original_unit,factor=unit(calibration['unit'],'calibration.unit')
    start,end=point(calibration['start_px'],'calibration.start_px'),point(calibration['end_px'],'calibration.end_px')
    for endpoint in (start,end):
        if not (0<=endpoint[0]<info['width_px'] and 0<=endpoint[1]<info['height_px']): raise ValueError('Calibration endpoints must lie in the full source image, including its original scale footer')
    span=math.hypot(end[0]-start[0],end[1]-start[1])
    if span<=0: raise ValueError('Calibration endpoints must be distinct')
    provenance=text(calibration['source'],'calibration.source')
    if provenance.strip().lower() in ('unknown','未知','待确认','未确定'): raise ValueError('Calibration source remains unconfirmed')
    panel=document['panel'];keys(panel,{'width_pt','height_pt'},'panel',{'width_pt','height_pt'})
    width,height=finite(panel['width_pt'],'panel.width_pt',True),finite(panel['height_pt'],'panel.height_pt',True)
    sx,sy=width/(crop[2]-crop[0]),height/(crop[3]-crop[1])
    finite(sx,'image scale',True);finite(sy,'image scale',True)
    if not math.isclose(sx,sy,rel_tol=1e-7,abs_tol=1e-10): raise ValueError('Panel and crop aspect ratios differ; SEM images must not be stretched')
    scale=document['scale_bar'];keys(scale,{'length','unit'},'scale_bar',{'length','unit'})
    scale_length=finite(scale['length'],'scale_bar.length',True)
    scale_unit,scale_factor=unit(scale['unit'],'scale_bar.unit')
    keys(document['style'],STYLE_KEYS,'style',STYLE_KEYS-{'panel_label'})
    style=dict(document['style'])
    for name in ('bar_height_pt','scale_font_size_pt','panel_font_size_pt'):
        style[name]=finite(style[name],'style.'+name,True)
    for name in ('bar_left_pt','bar_bottom_pt','label_gap_pt','panel_left_pt','panel_top_pt'):
        style[name]=finite(style[name],'style.'+name)
        if style[name]<0: raise ValueError('style.'+name+' must not be negative')
    for name in ('scale_font','panel_font'): text(style[name],'style.'+name)
    for name in ('bar_color_rgb','text_color_rgb'):
        color=style[name]
        if not isinstance(color,(list,tuple)) or len(color)!=3: raise ValueError('style.'+name+' must have three RGB values')
        style[name]=[finite(value,'style.'+name) for value in color]
        if any(value<0 or value>255 for value in style[name]): raise ValueError('style.'+name+' must be within 0..255')
    style.setdefault('panel_label','')
    if not isinstance(style['panel_label'],str): raise ValueError('style.panel_label must be text (empty is permitted)')
    return dict(schema_version=1,task_name=task,output_root=str(output),
                source=dict(info,file=str(source),sha256=sha256(source)),image_region_px=region,crop_px=crop,
                calibration=dict(length=length,unit=original_unit,start_px=start,end_px=end,source=provenance,
                                 pixel_span=span,length_um=finite(length*factor,'calibration length in um',True),um_per_px=finite(length*factor/span,'um per pixel',True)),
                panel=dict(width_pt=width,height_pt=height),scale_bar=dict(length=scale_length,unit=scale_unit,length_um=finite(scale_length*scale_factor,'scale-bar length in um',True)),
                style=style,image_scale_pt_per_px=sx)
