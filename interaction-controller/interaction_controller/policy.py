"""Two live-ray cobblestone targets and one qualified local ascent, not a planner."""
import copy
import math
from .legacy import Refused
from short_input_controller.policy import local_gate as frozen_move_gate
from .schema import finite,integer,fingerprint

TARGETS={(-636,60,33),(-636,61,34)}
AIR={'minecraft:air','minecraft:cave_air','minecraft:void_air'}
SUPPORT_BRICKS={'minecraft:nether_bricks'}


def context(obs,req,owner):
    if obs.get('ready') is not True or obs.get('unknown_lock') is not False or obs.get('active_id') is not None or obs.get('bound_owner_id')!=owner:raise Refused('original native owner/context unavailable')
    if any(type(obs.get(k)) is not type(req[k]) or obs.get(k)!=req[k] for k in ('session','world_generation','player_uuid','owner_generation','observation_id')):raise Refused('fresh observation identity mismatch')
    if obs.get('alive') is not True or obs.get('paused') is not False or obs.get('screen_open') is not False:raise Refused('ordinary active gameplay context required')
    pose,velocity=obs.get('pose'),obs.get('velocity')
    if not isinstance(pose,dict) or set(pose)!={'x','y','z','yaw','pitch'} or any(not finite(v,-3e7,3e7) for v in pose.values()):raise Refused('finite live pose required')
    if not isinstance(velocity,dict) or set(velocity)!={'x','y','z'} or any(not finite(v,-100,100) for v in velocity.values()):raise Refused('finite local velocity required')
    return pose


def blocks(obs):
    raw=obs.get('local_blocks')
    if not isinstance(raw,list) or len(raw)!=150:raise Refused('150 bounded live local cells required')
    pose=obs['pose'];origin=tuple(math.floor(pose[k]) for k in ('x','y','z'));result={}
    for cell in raw:
        if not isinstance(cell,dict) or set(cell)!={'dx','dy','dz','loaded','id','collision','fluid'}:raise Refused('closed local cell required')
        dx,dy,dz=cell['dx'],cell['dy'],cell['dz']
        if not integer(dx,-2,2) or not integer(dz,-2,2) or not integer(dy,-2,3):raise Refused('local cell range invalid')
        key=(origin[0]+dx,origin[1]+dy,origin[2]+dz)
        if key in result or type(cell['loaded']) is not bool:raise Refused('duplicate local cell or loaded flag')
        if cell['loaded'] and (type(cell['collision']) is not bool or not isinstance(cell['id'],str) or not isinstance(cell['fluid'],str)):raise Refused('loaded local cell flags invalid')
        if not cell['loaded'] and any(cell[k] is not None for k in ('id','collision','fluid')):raise Refused('unloaded cell must be null')
        result[key]=cell
    return result


def clear(cells,key):
    cell=cells.get(key)
    return cell is not None and cell['loaded'] and not cell['collision'] and cell['fluid']=='minecraft:empty' and cell['id'] in AIR


def hotbar(obs):
    entries=obs.get('hotbar')
    if not isinstance(entries,list) or len(entries)!=9 or not integer(obs.get('selected_slot'),0,8):raise Refused('live nine-slot hotbar required')
    by_slot={}
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!={'slot','item_id','count','damage','stack_fingerprint'} or not integer(entry['slot'],0,8) or entry['slot'] in by_slot:raise Refused('hotbar entry invalid')
        if not isinstance(entry['item_id'],str) or not integer(entry['count'],0,99) or not integer(entry['damage'],0,2147483647) or not fingerprint(entry['stack_fingerprint']):raise Refused('hotbar binding invalid')
        by_slot[entry['slot']]=entry
    return by_slot


def pickaxe(entry,expected):
    if entry['slot']!=2 or entry['item_id']!='minecraft:stone_pickaxe' or entry['count']!=1 or not 104<=entry['damage']<=106 or entry['stack_fingerprint']!=expected:raise Refused('exact planned hotbar stone pickaxe required')


def gate(obs,req,owner,history):
    pose=context(obs,req,owner)
    kind=req['kind']
    risk={'gameplay_risk':'ordinary_damage_and_incomplete_break_are_gameplay','scope':'two_cobblestones_and_one_local_ascent'}
    if kind=='look':
        delta=(req['yaw']-pose['yaw']+180)%360-180
        if abs(delta)>90 or abs(req['pitch']-pose['pitch'])>90:raise Refused('one look delta exceeds bound')
        return risk
    if kind=='select_hotbar':
        if req['slot']!=2:raise Refused('only planned hotbar slot2 may be selected')
        pickaxe(hotbar(obs)[2],req['stack_fingerprint']);return risk
    cells=blocks(obs)
    if kind=='break_block':
        target=(req['x'],req['y'],req['z'])
        if target not in TARGETS or req['y']<=59:raise Refused('outside exact two-block excavation plan')
        if obs.get('on_ground') is not True or any(abs(v)>.1 for v in obs['velocity'].values()):raise Refused('stationary grounded break context required')
        if obs['selected_slot']!=2:raise Refused('planned pickaxe must already be selected')
        pickaxe(hotbar(obs)[2],req['stack_fingerprint'])
        cell=cells.get(target)
        if cell is None or not cell['loaded'] or cell['id']!=req['block_id'] or cell['fluid']!='minecraft:empty':raise Refused('fresh target material mismatch')
        ray=obs.get('ray')
        if not isinstance(ray,dict) or set(ray)!={'kind','x','y','z','face','point','block_id'} or ray['kind']!='block' or (ray['x'],ray['y'],ray['z'])!=target or ray['face']!=req['face'] or ray['block_id']!=req['block_id']:raise Refused('actual current block ray and face must match')
        if not isinstance(ray['point'],dict) or set(ray['point'])!={'x','y','z'} or any(not finite(v,-3e7,3e7) for v in ray['point'].values()):raise Refused('actual hit point required')
        return risk
    if not req['jump_first']:
        subset=copy.deepcopy(obs);subset['local_blocks']=[c for c in obs['local_blocks'] if c['dy']<=2]
        risk['movement']=frozen_move_gate(subset,req,owner)
        return risk
    if any(record['request'].get('profile')==req['profile'] and record['request'].get('kind')=='move' and record['request'].get('jump_first') and record['request'].get('session')==req['session'] and record['request'].get('world_generation')==req['world_generation'] for record in history.values()):raise Refused('one ascent intent already exists in this native world binding; no replacement jump')
    bbox=obs.get('player_bbox')
    names={'min_x','min_y','min_z','max_x','max_y','max_z'}
    if not isinstance(bbox,dict) or set(bbox)!=names or any(not finite(v,-3e7,3e7) for v in bbox.values()):raise Refused('live full player bounding box required')
    if abs(bbox['min_y']-pose['y'])>.01 or abs((bbox['min_x']+bbox['max_x'])/2-pose['x'])>.01 or abs((bbox['min_z']+bbox['max_z'])/2-pose['z'])>.01:raise Refused('bbox must describe the live pose')
    if not (-636<=bbox['min_x']<bbox['max_x']<=-635 and 34<=bbox['min_z']<bbox['max_z']<=35 and abs(bbox['min_y']-59)<=.05 and 1.75<=bbox['max_y']-bbox['min_y']<=1.85):raise Refused('entire player must fit inside source opening before jump')
    if obs.get('on_ground') is not True or any(abs(v)>.1 for v in obs['velocity'].values()):raise Refused('grounded low-velocity jump origin required')
    yaw=math.radians(pose['yaw']);dx=req['strafe']*math.cos(yaw)-req['forward']*math.sin(yaw);dz=req['forward']*math.cos(yaw)+req['strafe']*math.sin(yaw)
    if not 0<req['forward']<=1 or abs(req['strafe'])>1e-9 or abs(dx)>.02 or dz>=-.05:raise Refused('ascent must face the adjacent northern step')
    if not clear(cells,(-636,59,34)):raise Refused('fresh source body cell must be clear')
    for z in (32,33,34):
        for y in (60,61,62):
            if not clear(cells,(-636,y,z)):raise Refused('fresh full jump head/body clearance required')
    source=cells.get((-636,58,34))
    for z in (32,33):
        support=cells.get((-636,59,z))
        if support is None or not support['loaded'] or not support['collision'] or support['fluid']!='minecraft:empty' or support['id'] not in SUPPORT_BRICKS:raise Refused('live adjacent landing brick support required')
    if source is None or not source['loaded'] or not source['collision'] or source['fluid']!='minecraft:empty':raise Refused('live source support required')
    risk['jump_qualification']='one source-z34-feet59 to target-z33-feet60 attempt; landing not guaranteed'
    return risk
