"""Independent Y display bands for unchanged capacity/CE cycle values."""
import math
from ....ingest.report import InputContractError

CAPACITY='discharge_capacity'
CE='coulombic_efficiency'
PT_MM=25.4/72.

def _nice_step(value):
    exponent=math.floor(math.log10(value))
    for factor in (1.,2.,2.5,5.,10.):
        step=factor*10.**exponent
        if step>=value*(1-1e-12):return step

def band_range(values,band,refinement=0):
    low,high=min(values),max(values)
    if low==high:
        raise InputContractError('Constant cycle metric needs an explicit nondegenerate axis range for separated-band layout')
    span=(high-low)/(band[1]-band[0])
    first=low-band[0]*span
    step=_nice_step(span/7.)/(10.**refinement)
    return [math.floor(first/step+1e-12)*step,
            math.ceil((first+span)/step-1e-12)*step]

def _values(plan,metric):
    return [y for s in plan.data_series if s.metric==metric for x,y in s.points]

def _radius(plan,metric):
    return max([float(s.style.symbol_size_pt or 0)*PT_MM/2.
                for s in plan.series if s.metric==metric and s.style.symbol_shape not in (None,'none')]+[0.])

def _band(values,bounds):
    if (not isinstance(bounds,(list,tuple)) or len(bounds)!=2 or
        any(isinstance(v,bool) or not math.isfinite(float(v)) for v in bounds) or bounds[0]>=bounds[1]):
        raise InputContractError('Separated cycle layout requires finite ascending axis ranges')
    if min(values)<bounds[0] or max(values)>bounds[1]:
        raise InputContractError('Separated cycle axis ranges must contain every supplied value')
    return [(min(values)-bounds[0])/(bounds[1]-bounds[0]),
            (max(values)-bounds[0])/(bounds[1]-bounds[0])]

def measure_bands(plan,ranges,area,min_gap_mm=None):
    capacity,ce=_values(plan,CAPACITY),_values(plan,CE)
    cb,eb=_band(capacity,ranges['y']),_band(ce,ranges['y_right'])
    cr,er=_radius(plan,CAPACITY),_radius(plan,CE)
    height=area['height_mm']
    gap=(eb[0]-cb[1])*height-cr-er
    required=max(cr+er,0.) if min_gap_mm is None else float(min_gap_mm)
    return {'capacity_extrema':[min(capacity),max(capacity)],'ce_extrema':[min(ce),max(ce)],
            'capacity_center_band':cb,'ce_center_band':eb,
            'capacity_symbol_radius_mm':cr,'ce_symbol_radius_mm':er,
            'center_gap_mm':(eb[0]-cb[1])*height,'net_gap_mm':gap,'required_net_gap_mm':required,
            'bottom_free_height_mm':cb[0]*height-cr,
            'capacity_vertical_span_fraction':cb[1]-cb[0],'ce_vertical_span_fraction':eb[1]-eb[0],
            'all_ce_above_all_capacity':gap>0,'gap_sufficient':gap>0 and gap>=required-1e-8,
            'point_counts':{CAPACITY:len(capacity),CE:len(ce)},'ranges':dict(ranges)}

def apply_layout(plan,config):
    rule=(config.get('plot_type') or {}).get('native_layout') or {}
    if not rule.get('enabled'):return plan
    if rule.get('mode','separated_bands')!='separated_bands':
        raise InputContractError('Unknown cycle native_layout mode')
    for layer in plan.layers:
        for side in ('bottom','left','right'):
            axis=layer.axes.get(side)
            if axis and (axis.direction!='ascending' or axis.scale_type not in (None,'linear')):
                raise InputContractError('Separated cycle layout currently requires ascending linear X/Y/Y2')
    legend=config.setdefault('legend',{})
    if legend.get('position','auto') not in ('auto','bottom_left','bottom_right'):
        raise InputContractError('Separated cycle layout reserves its lower region for a bottom legend')
    if legend.get('position','auto')=='auto':legend['position']='bottom_left'
    area=dict(plan.page['area'])
    # Same native Y2-title margin reservation as OriginBackend._apply_geometry.
    area['width_mm']=area['page_width_mm']-area['left_mm']-max(12.,float((config.get('canvas',{}).get('margins') or {}).get('right',0)))
    ranges=dict(plan.page.get('axis_ranges_override') or {})
    automatic_y='y' not in ranges
    automatic_y2='y_right' not in ranges
    if 'y' not in ranges:ranges['y']=band_range(_values(plan,CAPACITY),(.42,.66))
    if 'y_right' not in ranges:ranges['y_right']=band_range(_values(plan,CE),(.76,.85))
    xs=[x for s in plan.data_series for x,y in s.points]
    if 'x' not in ranges:
        radius=max(_radius(plan,CAPACITY),_radius(plan,CE))
        if area['width_mm']<=2*radius:raise InputContractError('Cycle symbols cannot fit the native layer width')
        # Display padding only. The supplied cycle numbers stay unchanged.
        span=max(xs)-min(xs)
        if not span:span=1.
        padding=(radius/area['width_mm']*span)/(1-2*radius/area['width_mm'])
        padding=max(padding,span*.01)
        ranges['x']=[math.floor(min(xs)-padding),math.ceil(max(xs)+padding)]
    _band(xs,ranges['x'])
    gap=rule.get('min_gap_mm')
    if gap is not None and (isinstance(gap,bool) or not math.isfinite(float(gap)) or float(gap)<0):
        raise InputContractError('Cycle min_gap_mm must be finite and nonnegative')
    geometry=measure_bands(plan,ranges,area,gap)
    refinement=0
    while not geometry['gap_sufficient'] and (automatic_y or automatic_y2) and refinement<5:
        refinement+=1
        if automatic_y:ranges['y']=band_range(_values(plan,CAPACITY),(.42,.66),refinement)
        if automatic_y2:ranges['y_right']=band_range(_values(plan,CE),(.76,.85),refinement)
        geometry=measure_bands(plan,ranges,area,gap)
    if not geometry['gap_sufficient']:
        raise InputContractError('Provided cycle axis ranges do not leave sufficient CE/capacity separation')
    plan.page['axis_ranges_override']=ranges
    plan.page['native_axis_title_fit']=True
    plan.page['native_cycle_layout']=dict(geometry,mode='separated_bands',legend_reserve='below_capacity',
        supplied_values_unchanged=True,data_transformation=False,range_rounding_refinement=refinement)
    capacity_head_y=geometry['capacity_center_band'][0]-geometry['capacity_symbol_radius_mm']/area['height_mm']-.055
    ce_tail_y=geometry['ce_center_band'][1]+geometry['ce_symbol_radius_mm']/area['height_mm']+.035
    if capacity_head_y<.015 or ce_tail_y+.05>.985:
        raise InputContractError('Native cycle arrow geometry cannot fit without changing the requested axis ranges')
    # Size only the newly requested arrows. Preserve every existing data style.
    arrow_length_pt=math.hypot(.057*area['width_mm'],.05*area['height_mm'])/PT_MM
    arrow_style=dict(line_width_pt=max(s.style.line_width_pt or .5 for s in plan.data_series),
                     head_length_pt=arrow_length_pt/3.,head_width_pt=arrow_length_pt/4.)
    plan.page['native_arrows']=[
      dict(name='CapacityAxisArrow',layer=0,role='axis_indicator',metric=CAPACITY,target_axis='left',
           coordinate_system='layer_fraction',attachment=2,tail=[.075,capacity_head_y+.05],head=[.018,capacity_head_y],style=dict(arrow_style)),
      dict(name='CEAxisArrow',layer=0,role='axis_indicator',metric=CE,target_axis='right',
           coordinate_system='layer_fraction',attachment=2,tail=[.925,ce_tail_y],head=[.982,ce_tail_y+.05],style=dict(arrow_style))]
    return plan

def verify_layout(plan,axes,area,legend_state=None):
    if not plan.page.get('native_cycle_layout'):return {'ok':True,'issues':[],'enabled':False}
    native=axes['layers']['left']
    ranges={key:[native[side]['from'],native[side]['to']] for key,side in (('x','bottom'),('y','left'),('y_right','right'))}
    state=measure_bands(plan,ranges,area,plan.page['native_cycle_layout']['required_net_gap_mm'])
    issues=[]
    if not state['gap_sufficient']:issues.append('Saved native CE/capacity symbol envelopes do not have the declared separation')
    if legend_state:
        box=legend_state['physical_page_mm']
        lowest_capacity=area['top_mm']+area['height_mm']-state['bottom_free_height_mm']
        state['legend_to_capacity_gap_mm']=box['top_mm']-lowest_capacity
        state['legend_below_capacity']=state['legend_to_capacity_gap_mm']>=-.1
        if not state['legend_below_capacity']:issues.append('Native cycle legend extends into the capacity envelope')
    return dict(state,ok=not issues,issues=issues,enabled=True)
