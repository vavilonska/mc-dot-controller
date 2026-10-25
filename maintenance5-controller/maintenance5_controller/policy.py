"""Finite reviewed maintenance operations; no retries, route planning or game safety claim."""
import copy
import math
from .legacy import Refused,PROFILE
from .schema import finite
from .geometry import observation_geometry,box_values,required,clear_body,support,intersects,witness_valid,TNT_FACTS,primed_valid
from interaction_controller.policy import context
from interaction2_controller.policy import hotbar
from navigation4_controller import policy as navigation_policy

TOOL='minecraft:stone_pickaxe'
MATERIAL='minecraft:andesite'
def stack(slots,slot,fingerprint):
    item=TOOL if slot==2 else MATERIAL if slot==3 else None
    e=slots.get(slot)
    if item is None or e is None or e['item_id']!=item or e['count']<1 or e['stack_fingerprint']!=fingerprint:raise Refused('exact approved slot/item/stack required')
    if slot==2 and (e['count']!=1 or e['max_damage']<=0 or e['max_damage']-e['damage']<1):raise Refused('observed pickaxe durability required')
    return e

def gate(obs,req,owner,history,plan):
    hazard=primed_valid(obs)
    if not hazard['complete'] or hazard['overflow'] or hazard['count']!=0:raise Refused('planned construction stops on current local primed TNT or incomplete evidence')
    pose=context(obs,req,owner);plan.bind(obs);stage=plan.stage(req['stage_id']);witness_valid(obs)
    context_history=[r for r in history.values() if r['request'].get('profile')==PROFILE and all(r['request'].get(k)==req[k] for k in ('session','world_generation','player_uuid'))]
    if 'target' in stage:
        if req['kind'] not in ('move','look'):raise Refused('navigation stage permits only move/look')
        if req['kind']=='move' and req['jump_first'] and any(r['request'].get('kind')=='move' and r['request'].get('jump_first') is True and r['request'].get('stage_id')==req['stage_id'] for r in context_history):raise Refused('same native context jump stage already consumed, across PLANs')
        # Delegate unchanged v4 geometric gate; map only history discriminator, not stored records.
        mapped={str(i):{'request':dict(r['request'],profile=navigation_policy.PROFILE,plan_sha256=plan.sha256)} for i,r in enumerate(context_history)}
        return navigation_policy.gate(obs,req,owner,mapped,plan)
    if req['kind']=='move':raise Refused('worksite does not authorize movement')
    if obs.get('sprinting') is not False or obs.get('on_ground') is not True or any(abs(v)>.1 for v in obs['velocity'].values()):raise Refused('grounded low-velocity non-sprinting worksite required')
    bbox=box_values(obs.get('player_bbox'));b=stage['source_bounds']
    if abs(bbox[1]-pose['y'])>1e-5 or abs((bbox[0]+bbox[3])/2-pose['x'])>1e-5 or abs((bbox[2]+bbox[5])/2-pose['z'])>1e-5 or any(bbox[i+3]-bbox[i]>4 for i in range(3)):raise Refused('actual current bbox mismatch')
    if not (b['min_x']<=bbox[0]<bbox[3]<=b['max_x'] and b['min_z']<=bbox[2]<bbox[5]<=b['max_z'] and b['min_y']<=pose['y']<=b['max_y']):raise Refused('whole source footprint outside reviewed worksite')
    cells,boxes=observation_geometry(obs)
    if not obs['collision_boxes_complete']:raise Refused('complete local current body geometry required')
    required(cells,[bbox[0],bbox[1]-1,bbox[2],bbox[3],bbox[4],bbox[5]]);clear_body(bbox,boxes);support(bbox,boxes,bbox[1]-1,bbox[1],contact=True)
    nearby=obs.get('nearby_living')
    if not isinstance(nearby,list) or len(nearby)>32 or obs.get('nearby_truncated') is not False:raise Refused('bounded nearby evidence required')
    for e in nearby:
        if not isinstance(e,dict) or set(e)!={'id','type','x','y','z','alive'} or type(e['alive']) is not bool or not isinstance(e['type'],str) or any(not finite(e[k],-3e7,3e7) for k in 'xyz'):raise Refused('closed nearby record required')
        if e['alive'] and abs(e['x']-pose['x'])<.8 and abs(e['z']-pose['z'])<.8 and abs(e['y']-pose['y'])<2:raise Refused('immediate living overlap risk')
    used=[r for r in context_history if r['request'].get('stage_id')==req['stage_id'] and r['request']['kind']==req['kind']]
    risk={'plan_sha256':plan.sha256,'stage_id':stage['id'],'gameplay_risk':'ordinary_damage_collision_and_incomplete_maintenance','physical_settlement':'not_observed','target_result':'not_assessed','nearby_living_count':len(nearby)}
    if req['kind']=='look':
        if len(used)>=stage['max_looks'] or abs((req['yaw']-pose['yaw']+180)%360-180)>90 or abs(req['pitch']-pose['pitch'])>90:raise Refused('worksite look budget or delta exceeded')
        return risk
    slots=hotbar(obs)
    if req['kind']=='select_hotbar':
        if len(used)>=stage['max_selects']:raise Refused('worksite selection intent budget consumed')
        stack(slots,req['slot'],req['stack_fingerprint']);return risk
    plan.target(req)
    if any(r['request']['kind']==req['kind'] and all(r['request'][k]==req[k] for k in 'xyz') for r in context_history):raise Refused('exact target already consumed one intent in this native context, across PLANs')
    target=[req['x'],req['y'],req['z'],req['x']+1,req['y']+1,req['z']+1]
    if intersects(target,bbox):raise Refused('target intersects actual current body')
    # Never remove current footing, even if another sampled surface might temporarily support it.
    if req['kind']=='break_block' and bbox[1]-1-1e-7<=target[4]<=bbox[1]+1e-7 and min(target[3],bbox[3])>max(target[0],bbox[0])+1e-7 and min(target[5],bbox[5])>max(target[2],bbox[2])+1e-7:raise Refused('current footprint support cannot be broken')
    slot=2 if req['kind']=='break_block' else 3
    if obs['selected_slot']!=slot:raise Refused('exact approved tool/material slot must be selected')
    stack(slots,slot,req['stack_fingerprint']);w=obs['ray_target_witness'];ray=obs['ray']
    if not isinstance(w,dict) or not w['loaded'] or not w['complete'] or w['fluid']!='minecraft:empty' or not isinstance(ray,dict) or ray.get('kind')!='block':raise Refused('complete current actual-ray target witness required')
    expected={k:req[k] if req['kind']=='break_block' else req['anchor_'+k] for k in 'xyz'}
    expected_id=req['block_id'] if req['kind']=='break_block' else req['anchor_block_id']
    if any(w[k]!=expected[k] for k in 'xyz') or w['id']!=expected_id or ray.get('face')!=req['face']:raise Refused('actual ray must match exact requested target/face')
    point=ray.get('point')
    if not isinstance(point,dict) or set(point)!={'x','y','z'} or any(not finite(point[k],-3e7,3e7) for k in 'xyz'):raise Refused('finite actual hit point required')
    if req['kind']=='break_block':
        if req['block_id']=='minecraft:tnt' and any(w[k] is not False for k in TNT_FACTS):raise Refused('stable unpowered unheated current TNT witness required')
    else:
        c=cells.get(tuple(req[k] for k in 'xyz'))
        if c is None or not c['loaded'] or c['id']!='minecraft:air' or c['fluid']!='minecraft:empty' or c['collision_boxes']!=[]:raise Refused('exact known air restoration destination required')
        if any(abs(point[k]-req['hit_'+k])>1e-4 for k in 'xyz'):raise Refused('actual anchor hit differs from reviewed point')
    return risk
