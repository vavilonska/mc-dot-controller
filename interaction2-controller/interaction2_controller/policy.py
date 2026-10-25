"""Reviewed exact PLAN targets; ordinary risks remain, no jump qualification."""
import copy
import math
from .legacy import Refused
from .schema import integer,finite,fingerprint
from interaction_controller.policy import context,blocks
from short_input_controller.policy import local_gate as frozen_nonjump_gate

TOOL_SLOT=2
TOOL_ITEM='minecraft:stone_pickaxe'
HOTBAR_KEYS={'slot','item_id','count','damage','max_damage','stack_fingerprint'}


def hotbar(obs):
    raw=obs.get('hotbar')
    if not isinstance(raw,list) or len(raw)!=9 or not integer(obs.get('selected_slot'),0,8):raise Refused('live nine-slot hotbar required')
    slots={}
    for entry in raw:
        if not isinstance(entry,dict) or set(entry)!=HOTBAR_KEYS or not integer(entry['slot'],0,8) or entry['slot'] in slots:raise Refused('closed v2 hotbar entry required')
        if not isinstance(entry['item_id'],str) or not integer(entry['count'],0,99) or not integer(entry['damage'],0,2147483647) or not integer(entry['max_damage'],0,2147483647) or not fingerprint(entry['stack_fingerprint']):raise Refused('observed hotbar metadata invalid')
        slots[entry['slot']]=entry
    return slots


def tool(entry,expected):
    if entry['slot']!=TOOL_SLOT or entry['item_id']!=TOOL_ITEM or entry['count']!=1 or entry['stack_fingerprint']!=expected:raise Refused('exact planned slot/item/stack required')
    remaining=entry['max_damage']-entry['damage']
    if entry['max_damage']<=0 or remaining<1:raise Refused('observed remaining durability required')
    return remaining


def gate(obs,req,owner,history,plan):
    pose=context(obs,req,owner)
    plan.bind(obs)
    if not any(abs(pose['y']-t['feet_y'])<=.05 for t in plan.data['targets']):raise Refused('reviewed PLAN feet level required')
    risk={'plan_sha256':plan.sha256,'gameplay_risk':'ordinary_damage_and_incomplete_break_are_gameplay','physical_settlement':'not_observed'}
    if req['kind']=='move':
        if req['jump_first'] is not False:raise Refused('v2 maintenance does not authorize jump')
        blocks(obs) # Validate the bounded new observation, not a global terrain closure.
        reduced=copy.deepcopy(obs);reduced['local_blocks']=[c for c in obs['local_blocks'] if c['dy']<=2]
        risk['movement']=frozen_nonjump_gate(reduced,req,owner)
        return risk
    if req['kind']=='look':
        if abs((req['yaw']-pose['yaw']+180)%360-180)>90 or abs(req['pitch']-pose['pitch'])>90:raise Refused('one look delta exceeds90')
        return risk
    slots=hotbar(obs)
    if req['kind']=='select_hotbar':
        if req['slot']!=TOOL_SLOT:raise Refused('planned hotbar slot required')
        risk['observed_tool_remaining']=tool(slots[TOOL_SLOT],req['stack_fingerprint'])
        return risk
    target=(req['x'],req['y'],req['z'])
    planned=plan.target(*target,req['face'])
    if req['block_id']!=planned['block_id'] or req['y']<planned['min_break_y'] or abs(pose['y']-planned['feet_y'])>.05 or req['y']<math.floor(pose['y'])+1:raise Refused('outside reviewed target/material/feet bounds')
    if obs.get('on_ground') is not True or any(abs(v)>.1 for v in obs['velocity'].values()):raise Refused('grounded low-velocity break context required')
    if obs['selected_slot']!=TOOL_SLOT:raise Refused('planned tool must be selected')
    risk['observed_tool_remaining']=tool(slots[TOOL_SLOT],req['stack_fingerprint'])
    cell=blocks(obs).get(target)
    if cell is None or not cell['loaded'] or cell['id']!=planned['block_id'] or cell['fluid']!='minecraft:empty':raise Refused('fresh exact target state required')
    ray=obs.get('ray')
    if not isinstance(ray,dict) or set(ray)!={'kind','x','y','z','face','point','block_id'} or ray['kind']!='block' or (ray['x'],ray['y'],ray['z'])!=target or ray['face']!=planned['face'] or ray['block_id']!=planned['block_id']:raise Refused('actual current target ray required')
    if not isinstance(ray['point'],dict) or set(ray['point'])!={'x','y','z'} or any(not finite(v,-3e7,3e7) for v in ray['point'].values()):raise Refused('actual hit point required')
    return risk
