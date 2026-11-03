"""Keep existing native axis-title frames inside their physical page.

This does not replace the axis title, change text/typography or resize the page.
Existing title frames are placed via documented left/top and page attachment;
the calling review workflow chooses whether this placement is requested.
"""
from .native_legend import read_legend_bounds

def fit_native_axis_titles(backend,plan,config,area,inset_mm=1.0):
    result=[]
    for side,name in (('bottom','xb'),('left','yl'),('right','yr')):
        axis=plan.layers[0].axes.get(side) if plan.layers else None
        if axis is None or not axis.label:continue
        # Native special titles can inherit axis-scale attachment whose frame
        # coordinates change on export/reload. Keep the same special object and
        # explicitly attach its reviewed physical placement to the page.
        original_attach=backend.value(name+'.attach')
        backend.run('%s.attach=1;'%name,expect=False)
        before=read_legend_bounds(backend,config,area,name)
        box=before['physical_page_mm'];page=before['native_page']
        pw,ph=area['page_width_mm'],area['page_height_mm']
        if box['width_mm']>pw-2*inset_mm or box['height_mm']>ph-2*inset_mm:
            raise ValueError('%s native title is larger than the page; no font/page change is authorized'%name)
        if side=='bottom':
            left=area['left_mm']+area['width_mm']/2-box['width_mm']/2
            top=ph-inset_mm-box['height_mm']
        else:
            left=inset_mm if side=='left' else pw-inset_mm-box['width_mm']
            top=area['top_mm']+area['height_mm']/2-box['height_mm']/2
        changed=abs(left-box['left_mm'])>0.05 or abs(top-box['top_mm'])>0.05
        if changed:
            backend.run('%s.left=%.12g; %s.top=%.12g;'%(name,left/pw*page['width'],name,top/ph*page['height']),expect=False)
        after=read_legend_bounds(backend,config,area,name)
        b=after['physical_page_mm']
        fits=(b['left_mm']>=-.05 and b['top_mm']>=-.05 and b['right_mm']<=pw+.05 and b['bottom_mm']<=ph+.05)
        if not fits:raise ValueError('%s native title placement did not stay inside physical page'%name)
        result.append({'object':name,'text':backend.text(name+'.text$'),'changed':changed,'original_attachment':original_attach,'attachment':backend.value(name+'.attach'),'inside_page':fits,'before':before,'after':after,'font':backend.value(name+'.font'),'size_pt':backend.value(name+'.fsize')})
    return result
