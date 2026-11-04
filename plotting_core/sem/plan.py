"""Geometric plan for calibrated SEM raster+native Illustrator clip/bar/text."""
import math
from .contract import normalize,rectangle,finite,UNITS


def center_crop(image_region,aspect_ratio):
    """Largest centered rectangle; no particle/morphology selection is inferred."""
    box=rectangle(image_region,'image_region')
    aspect=finite(aspect_ratio,'aspect_ratio',True)
    width,height=box[2]-box[0],box[3]-box[1]
    if width/height>aspect:
        new_width=height*aspect
        return [(box[0]+box[2]-new_width)/2.,box[1],(box[0]+box[2]+new_width)/2.,box[3]]
    new_height=width/aspect
    return [box[0],(box[1]+box[3]-new_height)/2.,box[2],(box[1]+box[3]+new_height)/2.]


def prepare_sem(document):
    plan=normalize(document)
    source,crop,panel,style=plan['source'],plan['crop_px'],plan['panel'],plan['style']
    width,height=panel['width_pt'],panel['height_pt']
    factor=plan['image_scale_pt_per_px']
    plan['coordinate_system']=dict(source_pixels='zero-based top-left x-right/y-down; crop right and bottom exclusive',
        adobe='artboard [0,height_pt,width_pt,0]; x-right/y-up; positions are absolute artboard coordinates')
    plan['placed_full_image']=dict(left_pt=-crop[0]*factor,top_pt=height+crop[1]*factor,
        width_pt=source['width_px']*factor,height_pt=source['height_px']*factor,
        scale_x_pt_per_px=factor,scale_y_pt_per_px=factor,
        original_pixels_preserved=True,embedded=True)
    plan['clip']=dict(left_pt=0.,top_pt=height,width_pt=width,height_pt=height)
    bar=plan['scale_bar']
    bar_width=bar['length_um']/plan['calibration']['um_per_px']*factor
    left,bottom,thickness=style['bar_left_pt'],style['bar_bottom_pt'],style['bar_height_pt']
    label_bottom=bottom+thickness+style['label_gap_pt']
    if left+bar_width>width or bottom+thickness>height:
        raise ValueError('Calibrated scale bar does not fit inside the panel; choose an explicit suitable length or placement')
    if label_bottom+style['scale_font_size_pt']>height:
        raise ValueError('Scale label does not fit vertically inside the panel')
    if style['panel_left_pt']>=width or style['panel_top_pt']+style['panel_font_size_pt']>height:
        raise ValueError('Panel label placement does not fit inside the panel')
    display_unit={'um':'μm','µm':'μm','μm':'μm'}.get(bar['unit'],bar['unit'])
    bar.update(left_pt=left,bottom_pt=bottom,top_pt=bottom+thickness,width_pt=bar_width,height_pt=thickness,
               label=format(bar['length'],'.12g')+' '+display_unit,label_left_pt=left,label_bottom_pt=label_bottom)
    plan['panel_label']=dict(text=style['panel_label'],left_pt=style['panel_left_pt'],top_pt=height-style['panel_top_pt'])
    plan['policy']=dict(raster_processing='none',original_pixels_retained=True,crop_method='native rectangular clipping mask',
        geometric_transform='isotropic scale and translation only',calibration_basis='explicit verified source scale endpoints; not DPI or magnification',
        scale_and_labels='separate editable vector rectangle and live text',scientific_identity_inferred=False)
    return plan
