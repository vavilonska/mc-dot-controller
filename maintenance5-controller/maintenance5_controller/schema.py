"""Closed interaction schema and profile-separated canonical binary digest."""
import hashlib
import math
import re
import struct
from .legacy import legacy, Refused
from .legacy import PROFILE as NEW_PROFILE, V4_PROFILE, v4_schema

COMMON={'schema_version','profile','kind','id','session','owner_id','owner_generation','world_generation','player_uuid','ttl_ms','observation_id','plan_version','plan_sha256','stage_id'}
ARGS={'move':{'forward','strafe','samples','jump_first'},'look':{'yaw','pitch'},'select_hotbar':{'slot','stack_fingerprint'},'break_block':{'x','y','z','face','block_id','stack_fingerprint','max_calls'},'place_block':{'x','y','z','anchor_x','anchor_y','anchor_z','anchor_block_id','face','hit_x','hit_y','hit_z','item_id','stack_fingerprint'}}
STATUS_KEYS=(legacy.STATUS_KEYS-{'requested_samples','applied_samples'})|{'kind','requested_calls','applied_calls','plan_version','plan_sha256','stage_id','observation_refusal'}
OBS_KEYS=legacy.OBSERVATION_KEYS|{'player_bbox','selected_slot','hotbar','ray','observation_refusal','collision_boxes_complete','step_height','sprinting','ray_target_witness','local_primed_tnt','latest_target_witness','eye_position'}
FACES={'UP','DOWN','NORTH','SOUTH','EAST','WEST'}


def finite(value,low,high):return type(value) in (int,float) and math.isfinite(value) and low<=value<=high

def integer(value,low,high):return type(value) is int and low<=value<=high

def fingerprint(value):return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None


def refusal_valid(value,observe=False):
    if value is None:return
    stages={'observe'} if observe else {'admit','first_interaction_tick','first_input'}
    if not isinstance(value,dict) or set(value)!={'stage','age_ns','tick_delta','predicate_mask'} or value['stage'] not in stages:raise Refused('closed observation refusal required')
    age,ticks,mask=value['age_ns'],value['tick_delta'],value['predicate_mask']
    if age is None or ticks is None:
        if age is None and ticks is None and value['stage']=='admit' and type(mask) is int and mask in (-1,-2):return
        raise Refused('observation refusal null mismatch')
    if not integer(age,-9223372036854775808,9223372036854775807) or not integer(ticks,-9223372036854775808,9223372036854775807) or type(mask) is not int or mask not in (0,1,3,7,15,31,63,127):raise Refused('bounded observation refusal invalid')
    # Prefix contains only predicates actually passed before the failed predicate.
    if (mask==0 and age>=0 or mask==1 and not (age>=0 and age>2000000000) or mask>=3 and not 0<=age<=2000000000 or mask==3 and ticks>=0 or mask==7 and ticks<=40 or mask>=7 and ticks<0 or mask>=15 and ticks>40):raise Refused('observation refusal predicate contradiction')


def request_valid(req):
    if not isinstance(req,dict) or req.get('kind') not in ARGS or set(req)!=COMMON|ARGS[req['kind']]:raise Refused('closed interaction request required')
    if type(req['schema_version']) is not int or req['schema_version']!=1 or req['profile']!=NEW_PROFILE:raise Refused('interaction profile mismatch')
    for key in ('id','session','owner_id','player_uuid','observation_id'):legacy.uuid(req[key])
    if not isinstance(req['world_generation'],str) or not re.fullmatch('[A-Za-z0-9._:-]{1,128}',req['world_generation']):raise Refused('world identity invalid')
    if not integer(req['owner_generation'],1,9007199254740991) or not integer(req['ttl_ms'],100,2000):raise Refused('generation or finite deadline invalid')
    if type(req['plan_version']) is not int or req['plan_version']!=3 or not fingerprint(req['plan_sha256']):raise Refused('bound PLAN version/hash required')
    if not isinstance(req['stage_id'],str) or not re.fullmatch('[A-Za-z0-9._:-]{1,64}',req['stage_id']):raise Refused('bounded stage identity required')
    kind=req['kind']
    if kind=='move':
        if not finite(req['forward'],-1,1) or not finite(req['strafe'],-1,1) or not integer(req['samples'],1,8) or type(req['jump_first']) is not bool:raise Refused('move bounds invalid')
    elif kind=='look':
        if not finite(req['yaw'],-180,180) or req['yaw']==180 or not finite(req['pitch'],-90,90):raise Refused('absolute look angle invalid')

    elif kind=='select_hotbar':
        if type(req['slot']) is not int or req['slot'] not in (2,3) or not fingerprint(req['stack_fingerprint']):raise Refused('selected stack binding invalid')
    elif kind=='break_block':
        if any(not integer(req[k],-30000000,30000000) for k in ('x','z')) or not integer(req['y'],-2048,2048) or req['face'] not in FACES or req['block_id'] not in BREAK_BLOCKS or not fingerprint(req['stack_fingerprint']) or not integer(req['max_calls'],1,32) or req['block_id']=='minecraft:tnt' and req['max_calls']!=1:raise Refused('bounded exact maintenance break required')
    elif kind=='place_block':
        if any(not integer(req[k],-30000000,30000000) for k in ('x','z','anchor_x','anchor_z')) or any(not integer(req[k],-2048,2048) for k in ('y','anchor_y')) or req['face'] not in FACES or req['anchor_block_id'] not in ANCHOR_BLOCKS or req['item_id']!='minecraft:andesite' or not fingerprint(req['stack_fingerprint']) or any(not finite(req['hit_'+k],-30000000,30000000) for k in 'xyz'):raise Refused('bounded exact MAIN_HAND placement required')
        placement_geometry(req)

BREAK_BLOCKS={'minecraft:tnt','minecraft:cut_sandstone','minecraft:chiseled_sandstone'}
ANCHOR_BLOCKS={'minecraft:stone','minecraft:sandstone','minecraft:cut_sandstone','minecraft:chiseled_sandstone','minecraft:andesite'}
FACE_OFFSET={'UP':(0,1,0),'DOWN':(0,-1,0),'NORTH':(0,0,-1),'SOUTH':(0,0,1),'WEST':(-1,0,0),'EAST':(1,0,0)}
def placement_geometry(req):
    off=FACE_OFFSET[req['face']]
    if any(req[k]!=req['anchor_'+k]+off[i] for i,k in enumerate('xyz')):raise Refused('placement target must be adjacent to exact anchor face')
    for i,k in enumerate('xyz'):
        d=req['hit_'+k]-req['anchor_'+k]
        if not -1e-4<=d<=1+1e-4 or off[i] and abs(d-(1 if off[i]>0 else 0))>1e-4:raise Refused('placement hit must lie on exact anchor face')

def requested_calls(req):
    return req['samples'] if req['kind']=='move' else req['max_calls'] if req['kind']=='break_block' else 1


def payload_digest(req):
    def text(value):
        raw=value.encode('ascii');return struct.pack('>H',len(raw))+raw
    raw=text(req['profile'])+text(req['kind'])
    raw+=b''.join(text(req[k]) for k in ('id','session','owner_id'))+struct.pack('>q',req['owner_generation'])
    raw+=text(req['world_generation'])+text(req['player_uuid'])+struct.pack('>i',req['ttl_ms'])+text(req['observation_id'])+struct.pack('>i',req['plan_version'])+text(req['plan_sha256'])+text(req['stage_id'])
    kind=req['kind']
    if kind=='move':raw+=struct.pack('>ddi?',float(req['forward']) or 0.,float(req['strafe']) or 0.,req['samples'],req['jump_first'])
    elif kind=='look':raw+=struct.pack('>dd',float(req['yaw']) or 0.,float(req['pitch']) or 0.)
    elif kind=='select_hotbar':raw+=struct.pack('>i',req['slot'])+text(req['stack_fingerprint'])
    elif kind=='break_block':raw+=struct.pack('>iii',req['x'],req['y'],req['z'])+text(req['face'])+text(req['block_id'])+text(req['stack_fingerprint'])+struct.pack('>i',req['max_calls'])
    elif kind=='place_block':raw+=struct.pack('>iiiiii',*(req[k] for k in ('x','y','z','anchor_x','anchor_y','anchor_z')))+text(req['anchor_block_id'])+text(req['face'])+struct.pack('>ddd',*(float(req['hit_'+k]) or 0. for k in 'xyz'))+text(req['item_id'])+text(req['stack_fingerprint'])
    return hashlib.sha256(raw).hexdigest()


def receipt_valid(r,req):
    if req['profile']!=NEW_PROFILE:return v4_schema.receipt_valid(r,req)
    if not isinstance(r,dict) or set(r)!=STATUS_KEYS or type(r['schema_version']) is not int or r['schema_version']!=1 or r['profile']!=NEW_PROFILE or r['kind']!=req['kind']:raise Refused('closed interaction receipt mismatch')
    refusal_valid(r['observation_refusal'])
    diag=r['observation_refusal']
    if r['state']=='SETTLED' and r['reason']=='observation_stale_or_moved' and diag is None:raise Refused('known observation refusal diagnostic missing')
    if diag is not None and (r['applied_calls']!=0 or diag['stage']=='first_input' and req['kind']!='move' or diag['stage']=='first_interaction_tick' and req['kind']=='move'):raise Refused('observation refusal effect/stage contradiction')
    if any(type(r[k]) is not type(req[k]) or r[k]!=req[k] for k in set(legacy.IDENTITY)|{'plan_version','plan_sha256','stage_id'}):raise Refused('original identity mismatch')
    if not integer(r['requested_calls'],1,32) or r['requested_calls']!=requested_calls(req) or not integer(r['applied_calls'],0,r['requested_calls']):raise Refused('native call count mismatch')
    if not fingerprint(r['payload_digest']) or r['payload_digest']!=payload_digest(req):raise Refused('whole payload digest mismatch')
    if r['state'] not in ('QUEUED','ACTIVE','STOPPING','SETTLED','UNKNOWN') or r['protocol_state']!=r['state']:raise Refused('invalid protocol state')
    if any(type(r[k]) is not bool for k in ('input_invalidated','release_proven','settled','unknown_lock','protocol_terminal')) or not integer(r['cancellation_generation'],0,9007199254740991):raise Refused('invalid certainty fields')
    if not isinstance(r['reason'],str) or r['settlement_state']!='not_observed':raise Refused('physical settlement cannot be asserted')
    outcomes={'not_assessed'}
    if req['kind']=='break_block':outcomes={'not_observed','target_unchanged','target_changed'}
    elif req['kind']=='place_block':outcomes={'not_observed'}|{'place_'+result+'_target_'+target for result in ('success','success_no_item_used','consume','consume_partial','pass','fail') for target in ('placed','unchanged','other')}
    if r['gameplay_outcome'] not in outcomes:raise Refused('invalid gameplay outcome')
    if req['kind']=='place_block' and r['state']=='SETTLED' and r['gameplay_outcome']!='not_observed' and r['applied_calls']!=1:raise Refused('known returned placement must count its one native call')
    if r['effect_state'] not in ('not_started','calls_completed','unknown') or r['release_state'] not in ('not_needed','pending','proven','unknown'):raise Refused('invalid effect dimensions')
    if r['state']=='QUEUED' and r['applied_calls']!=0:raise Refused('queued call contradiction')
    if r['state']=='SETTLED':
        if not all(r[k] for k in ('input_invalidated','release_proven','settled','protocol_terminal')) or r['release_state'] not in ('proven','not_needed') or r['effect_state']=='unknown':raise Refused('contradictory terminal')
    elif r['settled'] or r['protocol_terminal']:raise Refused('nonterminal closure contradiction')
    if r['effect_state']=='not_started' and r['applied_calls']!=0:raise Refused('effect count contradiction')
    if r['effect_state']=='calls_completed' and r['applied_calls']==0:raise Refused('effect count contradiction')
    if r['release_state']=='not_needed' and (r['applied_calls']!=0 or r['effect_state'] not in (('unknown','not_started') if r['state']=='UNKNOWN' else ('not_started',))):raise Refused('no-effect release contradiction')
