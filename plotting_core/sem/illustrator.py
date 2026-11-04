"""Native Illustrator composition and reopen checks; no foreground input."""
import copy
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time


def _hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):
            digest.update(block)
    return digest.hexdigest()


SERIALIZE = r'''
function encode(v) {
 if(v===null || v===undefined)return "null";
 if(typeof v==="string")return '"'+v.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t')+'"';
 if(typeof v==="number" || typeof v==="boolean")return String(v);
 var a=[],i;
 if(v instanceof Array){for(i=0;i<v.length;i++)a.push(encode(v[i]));return '['+a.join(',')+']';}
 for(i in v){if(v.hasOwnProperty(i))a.push(encode(i)+':'+encode(v[i]));}return '{'+a.join(',')+'}';
}
function rgb(a){var c=new RGBColor();c.red=a[0];c.green=a[1];c.blue=a[2];return c;}
function color(c){return c.typename==='RGBColor'?[c.red,c.green,c.blue]:[String(c.typename)];}
function bounds(p){return [p.geometricBounds[0],p.geometricBounds[1],p.geometricBounds[2],p.geometricBounds[3]];}
function docState(){var a=[];for(var i=0;i<app.documents.length;i++)a.push({name:app.documents[i].name,saved:app.documents[i].saved});return a;}
'''


CREATE = r'''
(function(){
COMMON
 var p=PLAN, output=new File(DESTINATION), doc=null, prior=app.userInteractionLevel;
 var before=docState(), result={before_documents:before};
 try {
  app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
  if(output.exists)throw new Error('AI output already exists; no overwrite');
  // Resolve fonts first. A missing font must not silently alter the result.
  var scaleFont=app.textFonts.getByName(p.style.scale_font);
  var panelFont=app.textFonts.getByName(p.style.panel_font);
  doc=app.documents.add(DocumentColorSpace.RGB,p.panel.width_pt,p.panel.height_pt);
  var imageLayer=doc.layers[0];imageLayer.name='SEM image - full source and editable crop';
  var image=doc.placedItems.add();image.file=new File(p.transport.file);image.name='SEM_FULL_SOURCE';
  image.width=p.placed_full_image.width_pt;image.height=p.placed_full_image.height_pt;
  image.position=[p.placed_full_image.left_pt,p.placed_full_image.top_pt];
  image.embed();
  if(doc.rasterItems.length!==1)throw new Error('Native embedding did not create one raster item (actual '+doc.rasterItems.length+')');
  var raster=doc.rasterItems[0];raster.name='SEM_FULL_SOURCE';raster.note=encode({source:p.source,transport:p.transport});
  var group=imageLayer.groupItems.add();group.name='SEM_CROP';
  group.note=encode({source:p.source,calibration:p.calibration,crop_px:p.crop_px,image_region_px:p.image_region_px});
  raster.move(group,ElementPlacement.PLACEATEND);
  var clip=group.pathItems.rectangle(p.clip.top_pt,p.clip.left_pt,p.clip.width_pt,p.clip.height_pt);
  clip.name='SEM_CLIP';clip.stroked=false;clip.filled=false;clip.clipping=true;
  clip.zOrder(ZOrderMethod.BRINGTOFRONT);group.clipped=true;
  var marks=doc.layers.add();marks.name='SEM scale and editable labels';
  var bar=marks.pathItems.rectangle(p.scale_bar.top_pt,p.scale_bar.left_pt,p.scale_bar.width_pt,p.scale_bar.height_pt);
  bar.name='SEM_SCALE_BAR';bar.stroked=false;bar.filled=true;bar.fillColor=rgb(p.style.bar_color_rgb);
  bar.note=encode({calibration:p.calibration,length:p.scale_bar.length,unit:p.scale_bar.unit,width_pt:p.scale_bar.width_pt});
  var text=marks.textFrames.add();text.name='SEM_SCALE_LABEL';text.contents=p.scale_bar.label;
  text.textRange.characterAttributes.textFont=scaleFont;text.textRange.characterAttributes.size=p.style.scale_font_size_pt;
  text.textRange.characterAttributes.fillColor=rgb(p.style.text_color_rgb);
  text.left=p.scale_bar.label_left_pt;text.top=p.scale_bar.label_bottom_pt+text.height;
  if(p.panel_label.text){
   var panel=marks.textFrames.add();panel.name='SEM_PANEL_LABEL';panel.contents=p.panel_label.text;
   panel.textRange.characterAttributes.textFont=panelFont;panel.textRange.characterAttributes.size=p.style.panel_font_size_pt;
   panel.textRange.characterAttributes.fillColor=rgb(p.style.text_color_rgb);
   panel.left=p.panel_label.left_pt;panel.top=p.panel_label.top_pt;
  }
  var options=new IllustratorSaveOptions();options.pdfCompatible=true;options.embedLinkedFiles=true;options.compressed=true;
  doc.saveAs(output,options);
  result.saved_file=output.fsName;result.raster_bounds=bounds(raster);result.clip_bounds=bounds(clip);result.bar_bounds=bounds(bar);
  result.documents_during=app.documents.length;
  doc.close(SaveOptions.DONOTSAVECHANGES);doc=null;
  result.after_documents=docState();result.ok=true;
  return encode(result);
 } finally {if(doc){doc.close(SaveOptions.DONOTSAVECHANGES);}app.userInteractionLevel=prior;}
})()
'''


INSPECT = r'''
(function(){
COMMON
 var file=new File(DESTINATION),doc=null,prior=app.userInteractionLevel,result={before_documents:docState()};
 try {
  app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
  doc=app.open(file);
  result.layers=[];for(var i=0;i<doc.layers.length;i++)result.layers.push(doc.layers[i].name);
  result.artboard=doc.artboards[0].artboardRect;result.rasters=[];result.paths=[];result.text=[];
  result.placed_count=doc.placedItems.length;
  for(var i=0;i<doc.rasterItems.length;i++){var r=doc.rasterItems[i];result.rasters.push({name:r.name,embedded:r.embedded,bounds:bounds(r),note:r.note,opacity:r.opacity,color_space:String(r.imageColorSpace)});}
  for(var i=0;i<doc.pathItems.length;i++){var r=doc.pathItems[i];result.paths.push({name:r.name,bounds:bounds(r),clipping:r.clipping,filled:r.filled,stroked:r.stroked,fill_color:r.filled?color(r.fillColor):null});}
  for(var i=0;i<doc.textFrames.length;i++){var r=doc.textFrames[i];result.text.push({name:r.name,text:r.contents,font:r.textRange.characterAttributes.textFont.name,size_pt:r.textRange.characterAttributes.size,bounds:bounds(r),fill_color:color(r.textRange.characterAttributes.fillColor)});}
  result.groups=[];for(var i=0;i<doc.groupItems.length;i++){var g=doc.groupItems[i];result.groups.push({name:g.name,clipped:g.clipped,note:g.note});}
  doc.close(SaveOptions.DONOTSAVECHANGES);doc=null;result.after_documents=docState();return encode(result);
 } finally {if(doc){doc.close(SaveOptions.DONOTSAVECHANGES);}app.userInteractionLevel=prior;}
})()
'''


def _script(template, destination, plan=None):
    result=template.replace('COMMON',SERIALIZE).replace('DESTINATION',json.dumps(Path(destination).as_posix(),ensure_ascii=True))
    if plan is not None:
        result=result.replace('PLAN',json.dumps(plan,ensure_ascii=True,allow_nan=False))
    return result


def _near(actual,expected,tolerance=.02):
    return len(actual)==len(expected) and all(abs(a-b)<=tolerance for a,b in zip(actual,expected))


def verify_native(plan, state):
    checks={}
    width,height=plan['panel']['width_pt'],plan['panel']['height_pt']
    checks['artboard']=_near(state['artboard'],[0,height,width,0])
    checks['self_contained_raster']=len(state['rasters'])==1 and state['placed_count']==0 and state['rasters'][0]['embedded']
    if len(state['rasters'])==1:
        raster=state['rasters'][0];full=plan['placed_full_image']
        checks['full_image_bounds']=_near(raster['bounds'],[full['left_pt'],full['top_pt'],full['left_pt']+full['width_pt'],full['top_pt']-full['height_pt']])
        checks['raster_source_identity']=json.loads(raster['note'])==dict(source=plan['source'],transport=plan['transport'])
        checks['raster_opacity']=raster['opacity']==100
    paths={p['name']:p for p in state['paths']}
    clip=paths.get('SEM_CLIP',{})
    checks['native_clip']=clip.get('clipping') is True and _near(clip.get('bounds',[]),[0,height,width,0])
    checks['clipped_group']=len(state['groups'])==1 and state['groups'][0]['clipped']
    bar=paths.get('SEM_SCALE_BAR',{});expected=plan['scale_bar']
    checks['native_bar_length']=_near(bar.get('bounds',[]),[expected['left_pt'],expected['top_pt'],expected['left_pt']+expected['width_pt'],expected['bottom_pt']])
    checks['solid_bar']=bar.get('filled') is True and bar.get('stroked') is False
    checks['bar_color']=bar.get('fill_color')==plan['style']['bar_color_rgb']
    text={t['name']:t for t in state['text']}
    label=text.get('SEM_SCALE_LABEL',{})
    checks['scale_label']=label.get('text')==expected['label'] and label.get('font')==plan['style']['scale_font'] and abs(label.get('size_pt',0)-plan['style']['scale_font_size_pt'])<.001
    checks['scale_text_color']=label.get('fill_color')==plan['style']['text_color_rgb']
    if plan['panel_label']['text']:
        panel=text.get('SEM_PANEL_LABEL',{})
        checks['panel_label']=panel.get('text')==plan['panel_label']['text'] and panel.get('font')==plan['style']['panel_font']
    checks['existing_documents_preserved']=state['before_documents']==state['after_documents']
    return dict(ok=all(checks.values()),checks=checks)


def render_sem(plan, directory):
    """Create, close and reload one owned native AI; do not activate its window."""
    if os.name!='nt':
        raise RuntimeError('Native Illustrator output requires Windows and installed Illustrator')
    import win32com.client
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    target=directory/(plan['task_name']+'.ai')
    if target.exists():
        raise ValueError('AI destination already exists; no overwrite')
    before_hash=_hash(plan['source']['file'])
    if before_hash!=plan['source']['sha256']:
        raise ValueError('Source image bytes changed after SEM planning')
    if _hash(plan['transport']['file'])!=plan['transport']['sha256'] or plan['transport']['source_sha256']!=before_hash:
        raise ValueError('Opaque SEM transport/source identity changed after preparation')
    app=win32com.client.Dispatch('Illustrator.Application')
    report=dict(ready=False,adobe_version=str(app.Version),backend='Illustrator COM/ExtendScript',
                reference_opened_in_illustrator=False,ui_input_used=False,source_modified=False,
                application_visible=bool(app.Visible),headless_guaranteed=False)
    create=_script(CREATE,target,plan);inspect=_script(INSPECT,target)
    (directory/'create_sem.jsx').write_text(create,encoding='utf-8')
    (directory/'inspect_sem.jsx').write_text(inspect,encoding='utf-8')
    foreground=[]; stop=threading.Event()
    user32=ctypes.windll.user32;user32.GetForegroundWindow.restype=ctypes.c_void_p
    def sample_foreground():
        while not stop.is_set():
            foreground.append(int(user32.GetForegroundWindow() or 0));stop.wait(.02)
    monitor=threading.Thread(target=sample_foreground);monitor.daemon=True;monitor.start()
    try:
        report['create']=json.loads(app.DoJavaScript(create))
        report['reopened']=json.loads(app.DoJavaScript(inspect))
        report['native_verification']=verify_native(plan,report['reopened'])
        from .image_bridge import verify_ai_pixels
        report['pixel_verification']=verify_ai_pixels(str(target),plan['source']['file'],directory/'pixel_verification')
        report['source_unchanged']=_hash(plan['source']['file'])==before_hash
        report['ready']=report['native_verification']['ok'] and report['pixel_verification']['ok'] and report['source_unchanged']
        report.update(ai_file=str(target),ai_sha256=_hash(target))
        if not report['ready']:
            raise RuntimeError('Native SEM saved-object verification did not pass')
        return report
    except Exception as exc:
        report.update(ready=False,error=str(exc))
        raise
    finally:
        stop.set();monitor.join(1)
        report['foreground_observation']=dict(samples=len(foreground),window_changed=len(set(foreground))>1,
                                               input_or_activation_calls=False,
                                               scope='foreground may also change due to user input; not an absolute headless guarantee')
        (directory/'sem_render_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
