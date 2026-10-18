"""Closed exact-original authority adjudication; never semantic outcome promotion."""
from copy import deepcopy
import re
from .fall_rescue_status import validate as validate_status

VERSION='native-fall-rescue-original-adjudication/1'
ACK='release_authority_keep_original_effects_unknown_no_resume'
ROOT='/control/fall-rescue/adjudication'
NATIVE_KEYS={'adjudication_schema_version','adjudication_id','arm_id','owner_id','episode_id','original_action_id',
    'original_receipt_sha256','expected_action_session','expected_world_generation','expected_player_uuid',
    'expected_arbiter_revision','acknowledgment'}
BINDING_KEYS={'schema_version','arm_id','action_id','resident_session','request_id','owner_id','owner_generation',
    'job_id','defense_epoch','ttl_ms','authorization_deadline_monotonic_ms','context'}
SELECTOR_KEYS={'original_intent_id','original_request_id','resident_session','owner_id','owner_generation','job_id',
    'original_defense_epoch','expected_context','original_receipt_sha256'}

def require(ok,reason='fall_adjudication_binding_or_evidence_invalid'):
    if not ok:raise ValueError(reason)

def identifier(v):return type(v) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',v) is not None

def sha(v):return type(v) is str and re.fullmatch(r'[0-9a-f]{64}',v) is not None

def integer(v,lo=0,hi=2**53-1):return type(v) is int and lo<=v<=hi

def native_request(body):
    require(type(body) is dict and set(body)==NATIVE_KEYS)
    require(integer(body['adjudication_schema_version'],1,1) and identifier(body['adjudication_id'])
        and body['acknowledgment']==ACK and sha(body['original_receipt_sha256'])
        and integer(body['expected_arbiter_revision'],0,2**53-2))
    require(all(type(body[k]) is str and 0<len(body[k])<=128 for k in
        ('arm_id','owner_id','episode_id','original_action_id','expected_action_session','expected_world_generation','expected_player_uuid')))
    return deepcopy(body)

def selector(value):
    require(type(value) is dict and set(value)==SELECTOR_KEYS)
    require(all(identifier(value[k]) for k in ('original_intent_id','original_request_id','resident_session','owner_id','job_id')))
    require(integer(value['owner_generation'],1) and integer(value['original_defense_epoch']) and sha(value['original_receipt_sha256']))
    c=value['expected_context'];require(type(c) is dict and set(c)=={'world_generation','dimension','player_uuid','action_session'})
    require(all(type(x) is str and 0<len(x)<=128 for x in c.values()) and c['dimension'] in ('minecraft:overworld','minecraft:the_end'))
    return deepcopy(value)

def original(receipt,selected):
    """Validate a retained Resident receipt without reconstructing or replaying its action."""
    from .fall_rescue_attached import verify_seal,VERSION as ATTACHED,RESERVE_MS,exact
    s=selector(selected)
    require(type(receipt) is dict and receipt.get('status')=='uncertain'
        and receipt.get('reason')=='native_fall_rescue_interrupted_original'
        and receipt.get('input_release_unconfirmed') is False and receipt.get('no_auto_resume') is True
        and receipt.get('unknown_outcome') is True)
    require(receipt.get('request_id')==s['original_request_id'] and receipt.get('session_id')==s['resident_session'])
    seal=receipt.get('fall_rescue');require(type(seal) is dict and seal.get('sha256')==s['original_receipt_sha256'])
    b=seal.get('binding');require(type(b) is dict and set(b)==BINDING_KEYS)
    require(b.get('owner_id')==s['owner_id'] and b.get('owner_generation')==s['owner_generation']
        and b.get('job_id')==s['job_id'] and b.get('defense_epoch')==s['original_defense_epoch']
        and exact(b.get('context'),s['expected_context']))
    action=seal.get('original_action');require(type(action) is dict and action.get('action') in ('follow_path','combat_entity'))
    # The original immutable receipt seals the exact queue/owner/action identity.
    # This minimal shape is used solely to validate that seal, never to dispatch.
    profile='combat-local-observed-v1' if action['action']=='combat_entity' else 'movement-flat-observed-v2'
    command={'action':action['action'],'timeout_ms':b['ttl_ms']-RESERVE_MS,
        'scoped_native_preflight':{'profile':profile,**{k:b[k] for k in ('owner_id','owner_generation','job_id','defense_epoch')}},
        **{'expected_'+k:v for k,v in b['context'].items()},
        'fall_rescue_policy':{'version':ATTACHED,**{k:b[k] for k in ('owner_id','owner_generation','job_id','defense_epoch')},
            'ttl_ms':b['ttl_ms'],'rescue_reserve_ms':RESERVE_MS,'authorization_deadline_monotonic_ms':b['authorization_deadline_monotonic_ms']}}
    checked=verify_seal(seal,command,s['original_request_id'],s['resident_session'])
    n=checked['native_status'];require(checked['original_outcome']=='unknown_interrupted' and not n['armed'] and not n['input_owned']
        and n['unknown_outcome_quarantined'] and n['last_episode']['rescue_confirmed'],
        'fall_adjudication_requires_ended_confirmed_rescue')
    return checked

def inspection(value,sealed,*,released):
    from .fall_rescue_wire import payload
    value=payload(value)
    from .fall_rescue_attached import exact
    require(type(value) is dict and set(value)=={'adjudication_schema_version','arbiter_revision','current_neutral_context_proven','native_status'})
    require(integer(value['adjudication_schema_version'],1,1) and integer(value['arbiter_revision'])
        and value['current_neutral_context_proven'] is True,'fall_adjudication_current_neutral_context_unproven')
    b=sealed['binding'];n=validate_status(value['native_status'],arm_id=b['arm_id'],owner_id=b['owner_id'],context=b['context'],
        ttl_ms=b['ttl_ms'],permitted_action_id=b['action_id'])
    require(not n['armed'] and not n['input_owned'] and n['arm_revision']==1 and n['episodes_used']==1
        and n['unknown_outcome_quarantined'] is (not released) and n['automation_blocked'] is (not released)
        and exact(n.get('last_episode'),sealed['native_status']['last_episode']))
    return deepcopy(value)

def request_for(adjudication_id,sealed,view):
    b=sealed['binding'];inspection(view,sealed,released=False)
    return native_request({'adjudication_schema_version':1,'adjudication_id':adjudication_id,'arm_id':b['arm_id'],'owner_id':b['owner_id'],
        'episode_id':sealed['native_status']['last_episode']['episode_id'],'original_action_id':b['action_id'],
        'original_receipt_sha256':sealed['sha256'],**{'expected_'+k:b['context'][k] for k in ('action_session','world_generation','player_uuid')},
        'expected_arbiter_revision':view['arbiter_revision'],'acknowledgment':ACK})

def native_result(value,body,sealed):
    from .fall_rescue_wire import payload
    value=payload(value)
    native_request(body)
    b=sealed['binding']
    require(all(body[k]==expected for k,expected in {
        'arm_id':b['arm_id'],'owner_id':b['owner_id'],'episode_id':sealed['native_status']['last_episode']['episode_id'],
        'original_action_id':b['action_id'],'original_receipt_sha256':sealed['sha256'],
        **{'expected_'+k:b['context'][k] for k in ('action_session','world_generation','player_uuid')}}.items()),
        'fall_adjudication_native_body_original_binding_changed')
    require(type(value) is dict and set(value)=={'adjudication_schema_version','receipt','inspection'}
        and integer(value['adjudication_schema_version'],1,1))
    p=value['receipt'];expected={'adjudication_schema_version':1,'adjudication_id':body['adjudication_id'],
        'status':'authority_released_original_unknown',**{k:body[k] for k in ('arm_id','owner_id','episode_id','original_action_id','original_receipt_sha256')},
        **{k:body['expected_'+k] for k in ('action_session','world_generation','player_uuid')},
        'arbiter_revision_before':body['expected_arbiter_revision'],'arbiter_revision_after':body['expected_arbiter_revision']+1,
        'acknowledgment':ACK,'original_effects':'unknown','input_neutral_observed':True,'rescue_ended':True,
        'authority_released':True,'no_auto_resume':True,'physical_safety_guaranteed':False}
    from .fall_rescue_attached import exact
    require(exact(p,expected),'fall_adjudication_original_receipt_unconfirmed')
    view=inspection(value['inspection'],sealed,released=True)
    require(view['arbiter_revision']>=p['arbiter_revision_after'])
    return deepcopy(value)

class NativeWriteNotAttempted(ValueError):
    native_write_never_attempted=True

def no_write_result(value,identity,selected):
    from .fall_rescue_attached import exact
    return (type(value) is dict and value.get('status') in ('failed','uncertain')
        and exact(value.get('fall_adjudication_attempt'),{'schema_version':1,'adjudication_id':identity,
            'selector':selected,'native_write_attempted':False,'original_effects':'unknown','authority_released':False}))
