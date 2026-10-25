"""Narrow sidecar admission for a grounded edge step back onto real support.

Native/JAR and original source files remain unchanged. A copied Python gate uses
one scoped support predicate; every other original admission check is unchanged.
No invented collision boxes, modified observation, or unsupported input is used.
"""
import math,types
from navigation4_controller.geometry import (EPS,box_values,observation_geometry,required,clear_body,support,translated)
from navigation4_controller import policy as nav
from survival6_controller import policy as survival
from survival6_controller.legacy import Refused
from live_session_runner import actual_geometry as original_actual_geometry
from grounded_contact import area,partial,inward_project

SUPPORT_REFUSAL='whole footprint lacks bounded local support'
GEOMETRY_REFUSALS={SUPPORT_REFUSAL,'no actual current support contact',
 'actual body intersects sampled solid','required local cell missing/fluid/TNT',
 'whole current footprint outside reviewed source corridor',
 'local target displacement/drop bound exceeded','target above actual native step height',
 'grounded slow complete current geometry required'}

def source(o):
    if o.get('on_ground') is not True or o.get('collision_boxes_complete') is not True or o.get('sprinting') is not False:
        raise Refused('edge requires true grounded current geometry')
    p=o['pose'];b=box_values(o['player_bbox']);cells,boxes=observation_geometry(o)
    if any(abs(v)>.1 for v in o['velocity'].values()):raise Refused('edge requires slow current motion')
    if abs(b[1]-p['y'])>1e-5 or abs((b[0]+b[3])/2-p['x'])>1e-5 or abs((b[2]+b[5])/2-p['z'])>1e-5:
        raise Refused('edge actual bbox/pose mismatch')
    required(cells,[b[0],b[1]-1,b[2],b[3],b[4],b[5]]);clear_body(b,boxes)
    contact=area(b,boxes)
    if contact<=EPS:raise Refused('no actual current support contact')
    return p,b,cells,boxes,contact

def actual_geometry(o):
    try:return original_actual_geometry(o)
    except Refused as e:
        if str(e)!=SUPPORT_REFUSAL:raise
        source(o)  # True grounded partial contact may be observed, not yet moved.

def inward_target(o):
    """An optional visible cardinal retreat, not a command or arrival claim."""
    p,b,cells,boxes,_=source(o)
    if not partial(b,boxes):return None
    # Enough residual to avoid the ordinary .25m arrived tolerance. Prefer the
    # first supported short cardinal direction; no invented geometry or jump.
    for distance in (.4,.6):
        for dx,dz in ((-1,0),(0,-1),(0,1),(1,0)):
            target=dict(x=p['x']+dx*distance,y=p['y'],z=p['z']+dz*distance)
            try:inward_project(p,b,cells,boxes,target)
            except Refused:continue
            return target
    return None


def clone(function,**replacements):
    return types.FunctionType(function.__code__,dict(function.__globals__,**replacements),
                              function.__name__,function.__defaults__,function.__closure__)

def gate(o,q,owner,history,plan):
    try:return survival.gate(o,q,owner,history,plan)
    except Refused as e:
        if str(e)!=SUPPORT_REFUSAL:raise
    p,b,cells,boxes,contact=source(o);stage=plan.stage(q['stage_id']);target=stage['target']
    distance=math.hypot(target['x']-p['x'],target['z']-p['z'])
    if (q['kind']!='move' or q['jump_first'] or abs(target['y']-p['y'])>1e-5
        or not .01<distance<=.75 or q['samples']>4
        or math.hypot(q['forward'],q['strafe'])>.500001):
        raise Refused('edge recovery requires short same-height inward step')
    landing=inward_project(p,b,cells,boxes,target)
    def inward_support(box,seen,low,high,contact=False):
        try:return support(box,seen,low,high,contact)
        except Refused as e:
            if str(e)!=SUPPORT_REFUSAL:raise
            if abs(box[1]-b[1])>1e-5 or area(box,seen)+EPS<area(b,boxes):raise
            # Landing remains the original whole-footprint requirement above.
            if all(abs(box[k]-landing[k])<1e-7 for k in range(6)):raise
    nav_gate=clone(nav.gate,support=inward_support)
    patched=types.SimpleNamespace(PROFILE=nav.PROFILE,gate=nav_gate)
    result=clone(survival.gate,navigation_policy=patched)(o,q,owner,history,plan)
    return dict(result,edge_recovery='grounded_partial_contact_inward_to_full_support')

def install(controller):
    # Instance-local copy of C8.start: only its gate reference differs. Capacity,
    # durable PENDING, one-use dispatch and UNKNOWN handling are the original code.
    start=controller.start
    controller.start=types.MethodType(clone(start.__func__,gate=gate),controller)
    return controller
