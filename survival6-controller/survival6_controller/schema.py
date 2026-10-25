"""V6-only closed wire; old profiles keep original validators and digest bytes."""
import hashlib,re,struct
from .legacy import PROFILE as NEW_PROFILE,legacy,Refused,original_schema
from maintenance5_controller.schema import finite,integer,fingerprint,refusal_valid
COMMON=original_schema.COMMON
ARGS={'move':{'forward','strafe','samples','jump_first'},'look':{'yaw','pitch'},'select_hotbar':{'slot','stack_fingerprint'},'attack_blaze':{'target_entity_id','target_uuid','target_type','stack_fingerprint'},'consume_bread':{'stack_fingerprint','max_use_ticks'}}
STATUS_KEYS=original_schema.STATUS_KEYS
OBS_KEYS=(original_schema.OBS_KEYS-{'ray_target_witness','latest_target_witness','eye_position'})|{'survival'}
USE_RESULTS={'success','success_no_item_used','consume','consume_partial','pass','fail'}
def request_valid(req):
 if not isinstance(req,dict)or req.get('kind')not in ARGS or set(req)!=COMMON|ARGS[req['kind']]:raise Refused('closed v6 request required')
 if type(req['schema_version'])is not int or req['schema_version']!=1 or req['profile']!=NEW_PROFILE:raise Refused('v6 profile mismatch')
 for k in ('id','session','owner_id','player_uuid','observation_id'):legacy.uuid(req[k])
 if not isinstance(req['world_generation'],str)or not re.fullmatch('[A-Za-z0-9._:-]{1,128}',req['world_generation']):raise Refused('world identity invalid')
 kind=req['kind']
 if not integer(req['owner_generation'],1,9007199254740991)or not integer(req['ttl_ms'],100,4000 if kind=='consume_bread'else 2000):raise Refused('generation or absolute TTL bound invalid')
 if type(req['plan_version'])is not int or req['plan_version']!=4 or not fingerprint(req['plan_sha256']):raise Refused('PLAN4 hash required')
 if not isinstance(req['stage_id'],str)or not re.fullmatch('[A-Za-z0-9._:-]{1,64}',req['stage_id']):raise Refused('bounded stage ID required')
 if kind=='move':
  if not finite(req['forward'],-1,1)or not finite(req['strafe'],-1,1)or not integer(req['samples'],1,8)or type(req['jump_first'])is not bool:raise Refused('finite input bounds invalid')
 elif kind=='look':
  if not finite(req['yaw'],-180,180)or req['yaw']==180 or not finite(req['pitch'],-90,90):raise Refused('absolute look bounds invalid')
 else:
  if not fingerprint(req['stack_fingerprint']):raise Refused('current full stack required')
  if kind=='select_hotbar' and (type(req['slot'])is not int or req['slot']not in(1,8)):raise Refused('only bread or iron axe selection permitted')
  if kind=='attack_blaze':
   legacy.uuid(req['target_uuid'])
   if not integer(req['target_entity_id'],-2147483648,2147483647)or req['target_type']!='minecraft:blaze':raise Refused('exact current Blaze identity required')
  if kind=='consume_bread' and not integer(req['max_use_ticks'],1,40):raise Refused('bounded bread use required')
def requested_calls(req):return req['samples'] if req['kind']=='move'else 1
def payload_digest(req):
 def text(value):
  raw=value.encode('ascii');return struct.pack('>H',len(raw))+raw
 raw=text(req['profile'])+text(req['kind'])
 raw+=b''.join(text(req[k])for k in('id','session','owner_id'))+struct.pack('>q',req['owner_generation'])
 raw+=text(req['world_generation'])+text(req['player_uuid'])+struct.pack('>i',req['ttl_ms'])+text(req['observation_id'])+struct.pack('>i',req['plan_version'])+text(req['plan_sha256'])+text(req['stage_id'])
 kind=req['kind']
 if kind=='move':raw+=struct.pack('>ddi?',float(req['forward'])or 0.,float(req['strafe'])or 0.,req['samples'],req['jump_first'])
 elif kind=='look':raw+=struct.pack('>dd',float(req['yaw'])or 0.,float(req['pitch'])or 0.)
 elif kind=='select_hotbar':raw+=struct.pack('>i',req['slot'])+text(req['stack_fingerprint'])
 elif kind=='attack_blaze':raw+=struct.pack('>i',req['target_entity_id'])+text(req['target_uuid'])+text(req['target_type'])+text(req['stack_fingerprint'])
 elif kind=='consume_bread':raw+=text(req['stack_fingerprint'])+struct.pack('>i',req['max_use_ticks'])
 return hashlib.sha256(raw).hexdigest()

def receipt_valid(r,req):
    if req['profile']!=NEW_PROFILE:return original_schema.receipt_valid(r,req)
    if not isinstance(r,dict) or set(r)!=STATUS_KEYS or type(r['schema_version']) is not int or r['schema_version']!=1 or r['profile']!=NEW_PROFILE or r['kind']!=req['kind']:raise Refused('closed interaction receipt mismatch')
    refusal_valid(r['observation_refusal'])
    diag=r['observation_refusal']
    if r['state']=='SETTLED' and r['reason']=='observation_stale_or_moved' and diag is None:raise Refused('known observation refusal diagnostic missing')
    if diag is not None and (r['applied_calls']!=0 or diag['stage']=='first_input' and req['kind']!='move' or diag['stage']=='first_interaction_tick' and req['kind']=='move'):raise Refused('observation refusal effect/stage contradiction')
    if any(type(r[k]) is not type(req[k]) or r[k]!=req[k] for k in set(legacy.IDENTITY)|{'plan_version','plan_sha256','stage_id'}):raise Refused('original identity mismatch')
    if not integer(r['requested_calls'],1,8) or r['requested_calls']!=requested_calls(req) or not integer(r['applied_calls'],0,r['requested_calls']):raise Refused('native call count mismatch')
    if not fingerprint(r['payload_digest']) or r['payload_digest']!=payload_digest(req):raise Refused('whole payload digest mismatch')
    if r['state'] not in ('QUEUED','ACTIVE','STOPPING','SETTLED','UNKNOWN') or r['protocol_state']!=r['state']:raise Refused('invalid protocol state')
    if any(type(r[k]) is not bool for k in ('input_invalidated','release_proven','settled','unknown_lock','protocol_terminal')) or not integer(r['cancellation_generation'],0,9007199254740991):raise Refused('invalid certainty fields')
    if not isinstance(r['reason'],str) or r['settlement_state']!='not_observed':raise Refused('physical settlement cannot be asserted')
    outcomes={'not_assessed'}
    if req['kind']=='attack_blaze':outcomes={'not_observed','attack_returned_observe_outcome'}
    elif req['kind']=='consume_bread':outcomes={'not_observed'}|{'use_'+x for x in USE_RESULTS}
    if r['gameplay_outcome'] not in outcomes:raise Refused('invalid gameplay outcome')
    if req['kind'] in ('attack_blaze','consume_bread') and r['state']=='SETTLED' and r['gameplay_outcome']!='not_observed' and r['applied_calls']!=1:raise Refused('known returned operation must count one top-level call')
    if r['effect_state'] not in ('not_started','calls_completed','unknown') or r['release_state'] not in ('not_needed','pending','proven','unknown'):raise Refused('invalid effect dimensions')
    if r['state']=='QUEUED' and r['applied_calls']!=0:raise Refused('queued call contradiction')
    if r['state']=='SETTLED':
        if not all(r[k] for k in ('input_invalidated','release_proven','settled','protocol_terminal')) or r['release_state'] not in ('proven','not_needed') or r['effect_state']=='unknown':raise Refused('contradictory terminal')
    elif r['settled'] or r['protocol_terminal']:raise Refused('nonterminal closure contradiction')
    if r['effect_state']=='not_started' and r['applied_calls']!=0:raise Refused('effect count contradiction')
    if r['effect_state']=='calls_completed' and r['applied_calls']==0:raise Refused('effect count contradiction')
    if r['release_state']=='not_needed' and (r['applied_calls']!=0 or r['effect_state'] not in (('unknown','not_started') if r['state']=='UNKNOWN' else ('not_started',))):raise Refused('no-effect release contradiction')
