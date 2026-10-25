"""Closed interaction schema and profile-separated canonical binary digest."""
import hashlib
import math
import re
import struct
from .legacy import legacy, Refused
from .legacy import PROFILE as NEW_PROFILE, V1_PROFILE, v1_schema

COMMON={'schema_version','profile','kind','id','session','owner_id','owner_generation','world_generation','player_uuid','ttl_ms','observation_id','plan_version','plan_sha256'}
ARGS={'move':{'forward','strafe','samples','jump_first'},'look':{'yaw','pitch'},'select_hotbar':{'slot','stack_fingerprint'},'break_block':{'x','y','z','face','block_id','stack_fingerprint','max_calls'}}
STATUS_KEYS=(legacy.STATUS_KEYS-{'requested_samples','applied_samples'})|{'kind','requested_calls','applied_calls','plan_version','plan_sha256'}
OBS_KEYS=legacy.OBSERVATION_KEYS|{'player_bbox','selected_slot','hotbar','ray'}
FACES={'UP','DOWN','NORTH','SOUTH','EAST','WEST'}


def finite(value,low,high):return type(value) in (int,float) and math.isfinite(value) and low<=value<=high

def integer(value,low,high):return type(value) is int and low<=value<=high

def fingerprint(value):return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None


def request_valid(req):
    if not isinstance(req,dict) or req.get('kind') not in ARGS or set(req)!=COMMON|ARGS[req['kind']]:raise Refused('closed interaction request required')
    if type(req['schema_version']) is not int or req['schema_version']!=1 or req['profile']!=NEW_PROFILE:raise Refused('interaction profile mismatch')
    for key in ('id','session','owner_id','player_uuid','observation_id'):legacy.uuid(req[key])
    if not isinstance(req['world_generation'],str) or not re.fullmatch('[A-Za-z0-9._:-]{1,128}',req['world_generation']):raise Refused('world identity invalid')
    if not integer(req['owner_generation'],1,9007199254740991) or not integer(req['ttl_ms'],100,2000):raise Refused('generation or finite deadline invalid')
    if type(req['plan_version']) is not int or req['plan_version']!=1 or not fingerprint(req['plan_sha256']):raise Refused('bound PLAN version/hash required')
    kind=req['kind']
    if kind=='move':
        if not finite(req['forward'],-1,1) or not finite(req['strafe'],-1,1) or not integer(req['samples'],1,8) or req['jump_first'] is not False:raise Refused('move bounds invalid')
    elif kind=='look':
        if not finite(req['yaw'],-180,180) or req['yaw']==180 or not finite(req['pitch'],-90,90):raise Refused('absolute look angle invalid')
    elif kind=='select_hotbar':
        if not integer(req['slot'],0,8) or not fingerprint(req['stack_fingerprint']):raise Refused('hotbar stack binding invalid')
    elif kind=='break_block':
        if any(not integer(req[k],-30000000,30000000) for k in ('x','y','z')) or req['face'] not in FACES or req['block_id'] not in ('minecraft:cobblestone','minecraft:nether_wart_block') or not fingerprint(req['stack_fingerprint']) or not integer(req['max_calls'],1,32):raise Refused('single block target invalid')


def requested_calls(req):
    return req['samples'] if req['kind']=='move' else req['max_calls'] if req['kind']=='break_block' else 1


def payload_digest(req):
    def text(value):
        raw=value.encode('ascii');return struct.pack('>H',len(raw))+raw
    raw=text(req['profile'])+text(req['kind'])
    raw+=b''.join(text(req[k]) for k in ('id','session','owner_id'))+struct.pack('>q',req['owner_generation'])
    raw+=text(req['world_generation'])+text(req['player_uuid'])+struct.pack('>i',req['ttl_ms'])+text(req['observation_id'])+struct.pack('>i',req['plan_version'])+text(req['plan_sha256'])
    kind=req['kind']
    if kind=='move':raw+=struct.pack('>ddi?',float(req['forward']) or 0.,float(req['strafe']) or 0.,req['samples'],req['jump_first'])
    elif kind=='look':raw+=struct.pack('>dd',float(req['yaw']) or 0.,float(req['pitch']) or 0.)
    elif kind=='select_hotbar':raw+=struct.pack('>i',req['slot'])+text(req['stack_fingerprint'])
    else:raw+=struct.pack('>iii',req['x'],req['y'],req['z'])+text(req['face'])+text(req['block_id'])+text(req['stack_fingerprint'])+struct.pack('>i',req['max_calls'])
    return hashlib.sha256(raw).hexdigest()


def receipt_valid(r,req):
    if req['profile']==legacy.PROFILE:return legacy.Controller._validate_receipt(r,req)
    if req['profile']==V1_PROFILE:return v1_schema.receipt_valid(r,req)
    if not isinstance(r,dict) or set(r)!=STATUS_KEYS or type(r['schema_version']) is not int or r['schema_version']!=1 or r['profile']!=NEW_PROFILE or r['kind']!=req['kind']:raise Refused('closed interaction receipt mismatch')
    if any(type(r[k]) is not type(req[k]) or r[k]!=req[k] for k in set(legacy.IDENTITY)|{'plan_version','plan_sha256'}):raise Refused('original identity mismatch')
    if not integer(r['requested_calls'],1,32) or r['requested_calls']!=requested_calls(req) or not integer(r['applied_calls'],0,r['requested_calls']):raise Refused('native call count mismatch')
    if not fingerprint(r['payload_digest']) or r['payload_digest']!=payload_digest(req):raise Refused('whole payload digest mismatch')
    if r['state'] not in ('QUEUED','ACTIVE','STOPPING','SETTLED','UNKNOWN') or r['protocol_state']!=r['state']:raise Refused('invalid protocol state')
    if any(type(r[k]) is not bool for k in ('input_invalidated','release_proven','settled','unknown_lock','protocol_terminal')) or not integer(r['cancellation_generation'],0,9007199254740991):raise Refused('invalid certainty fields')
    if not isinstance(r['reason'],str) or r['settlement_state']!='not_observed':raise Refused('physical settlement cannot be asserted')
    outcomes=('not_observed','target_unchanged','target_changed') if req['kind']=='break_block' else ('not_assessed',)
    if r['gameplay_outcome'] not in outcomes:raise Refused('invalid gameplay outcome')
    if r['effect_state'] not in ('not_started','calls_completed','unknown') or r['release_state'] not in ('not_needed','pending','proven','unknown'):raise Refused('invalid effect dimensions')
    if r['state']=='QUEUED' and r['applied_calls']!=0:raise Refused('queued call contradiction')
    if r['state']=='SETTLED':
        if not all(r[k] for k in ('input_invalidated','release_proven','settled','protocol_terminal')) or r['release_state'] not in ('proven','not_needed') or r['effect_state']=='unknown':raise Refused('contradictory terminal')
    elif r['settled'] or r['protocol_terminal']:raise Refused('nonterminal closure contradiction')
    if r['effect_state']=='not_started' and r['applied_calls']!=0:raise Refused('effect count contradiction')
    if r['effect_state']=='calls_completed' and r['applied_calls']==0:raise Refused('effect count contradiction')
    if r['release_state']=='not_needed' and (r['applied_calls']!=0 or r['effect_state'] not in (('unknown','not_started') if r['state']=='UNKNOWN' else ('not_started',))):raise Refused('no-effect release contradiction')
