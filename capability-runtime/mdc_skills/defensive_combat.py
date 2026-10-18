"""One bounded native shield-only or evade episode. No offense, retry or resume."""
from copy import deepcopy
import math
from .core import Outcome,require
from . import threats

PROFILE='combat-defensive-local-v1'

def _same_policy(actual,expected):
    return (type(actual) is dict and set(actual)==set(expected)
        and all(type(actual.get(k)) is type(expected[k]) and actual[k]==expected[k] for k in ('schema_version','mode','window_ms'))
        and all(threats._number(actual.get(k)) and actual[k]==expected[k] for k in ('max_distance','minimum_separation_gain')))

def verified(native,policy,ident,uid,kind):
    if type(native) is not dict:return False
    if ('protocol' in native or 'schema_version' in native) and (native.get('protocol')!='mineclient-bridge'
            or type(native.get('schema_version')) is not int or native['schema_version']!=2):return False
    result=native.get('result')
    if type(result) is not dict or type(result.get('combat')) is not dict:return False
    combat=result['combat']
    return (native.get('status')=='succeeded' and combat.get('defensive_completed') is True
            and _same_policy(combat.get('defensive_policy'),policy) and type(combat.get('attack_dispatches')) is int
            and combat['attack_dispatches']==0 and combat.get('offensive_effects_allowed') is False
            and combat.get('physical_safe') is False and combat.get('risk_remaining') is True
            and combat.get('target_uuid')==uid and type(combat.get('target_entity_id')) is int and combat['target_entity_id']==ident and combat.get('target_type')==kind
            and (type(combat.get('defensive_blocking_samples')) is int and combat['defensive_blocking_samples']>=3
                if policy['mode']=='shield_only' else threats._number(combat.get('defensive_separation_gain'))
                    and combat['defensive_separation_gain']>=policy['minimum_separation_gain']))

def _run(runtime,target_uuid,mode,window_ms,max_distance,minimum_separation_gain):
    require(type(window_ms) is int and 300<=window_ms<=2500,'defensive_window_300_to_2500ms')
    require(threats._number(max_distance) and threats._number(minimum_separation_gain),'defensive_finite_bounds')
    require((mode=='shield_only' and max_distance==0 and minimum_separation_gain==0)
        or (mode=='immediate_evade' and 1<=max_distance<=4 and .1<=minimum_separation_gain<=2 and minimum_separation_gain<max_distance),
        'defensive_distance_or_gain_bounds')
    before=runtime.observe(entity_radius=16)
    player=before.player
    require(threats._number(player.get('health')) and player['health']>0 and player.get('alive') is True,
        'defensive_living_player_required')
    require(player.get('on_ground') is True and all(type(player.get(k)) is bool and not player[k] for k in threats.ENVIRONMENT_FLAGS),
        'defensive_grounded_dry_required')
    target=threats.entity(before,target_uuid)
    require(target.get('type') in threats.NATIVE_COMBAT_TYPES and target.get('alive') is True
        and threats._number(target.get('health')) and target['health']>0,'defensive_supported_living_target_required')
    require(math.dist(threats.position(player),threats.position(target))<=12,'defensive_target_range_12')
    if mode=='shield_only':
        shield=player.get('offhand',{})
        require(shield.get('id')=='minecraft:shield' and shield.get('count')==1 and isinstance(shield.get('item_fingerprint'),str),
            'defensive_exact_offhand_shield_required')
    ident,uid,kind=threats._identity(target)
    policy={'schema_version':1,'mode':mode,'window_ms':window_ms,'max_distance':max_distance,
        'minimum_separation_gain':minimum_separation_gain}
    command={'op':'action','action':'combat_entity','target_entity_id':ident,'target_uuid':uid,'target_type':kind,
        'timeout_ms':window_ms+250,'approach':False,'shield':mode=='shield_only','min_health':14,'defensive_policy':policy}
    def checked(_,after):
        return verified(after.state.get('client_action',{}),policy,ident,uid,kind)
    result=runtime.execute('defensive.'+mode,command,checked,before=before,max_samples=12)
    return Outcome(result.status,result.reason,result.request_ids,{**result.evidence,'defensive_policy':deepcopy(policy),
        'offensive_effects_allowed':False,'risk_remaining':True,'physical_safe':False,'ordinary_resume_allowed':False},result.last_observation)

def defend_local(runtime,target_uuid,*,window_ms=1000):
    return _run(runtime,target_uuid,'shield_only',window_ms,0,0)

def evade_local(runtime,target_uuid,*,window_ms=2500,max_distance=4,minimum_separation_gain=.5):
    return _run(runtime,target_uuid,'immediate_evade',window_ms,max_distance,minimum_separation_gain)
