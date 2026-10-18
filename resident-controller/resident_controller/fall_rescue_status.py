"""Strict bounded native v1 status and monotonic one-episode evidence."""
from copy import deepcopy
import math
import re

BASIS = 'correlated_readonly_integrated_server_state_after_pre_dispatch_baseline'
FLAGS = ('dispatch_attempted','packet_send_fence_passed','client_prediction_water','server_water_observed',
         'server_bucket_transition_observed','server_landed_alive_observed','rescue_confirmed')
BASE = {'fall_rescue_schema_version','status','reason','armed','input_owned','automation_blocked',
        'unknown_outcome_quarantined','arm_revision','episodes_used','no_auto_resume','remaining_ms',
        'arm_id','owner_id','action_session','world_generation','player_uuid'}
EPISODE = {'episode_id','outcome','age_ticks','hotbar_slot',*FLAGS,'confirmation_basis','baseline_server_tick','water_target'}

def check(ok, reason='fall_rescue_native_evidence_invalid'):
    if not ok: raise ValueError(reason)

def integer(v, low, high): return type(v) is int and low <= v <= high

def episode(value): return value['episode'] if 'episode' in value else value.get('last_episode')

def validate(value, *, arm_id, owner_id, context, ttl_ms, previous=None, permitted_action_id=None):
    from .fall_rescue_wire import payload
    value=payload(value)
    check(type(value) is dict and BASE <= set(value) <= BASE | {'last_client_observation','episode','last_episode','superseded_callback_failure'})
    check(integer(value['fall_rescue_schema_version'],1,1) and value['status'] in ('armed','rescuing','disarmed','quarantined'))
    check(type(value['reason']) is str and re.fullmatch(r'[a-z0-9_]{1,128}',value['reason']) is not None)
    check(value['arm_id']==arm_id and value['owner_id']==owner_id and all(value[k]==context[k] for k in ('action_session','world_generation','player_uuid')))
    check(all(type(value[k]) is bool for k in ('armed','input_owned','automation_blocked','unknown_outcome_quarantined','no_auto_resume')) and value['no_auto_resume'])
    check(integer(value['arm_revision'],1,2147483647) and integer(value['episodes_used'],0,1) and integer(value['remaining_ms'],0,ttl_ms))
    check(value['armed'] or value['remaining_ms']==0)
    check(value['status'] in ('armed','rescuing') if value['armed'] else value['status'] in ('disarmed','quarantined'))
    check(not (value['input_owned'] or value['unknown_outcome_quarantined']) or value['automation_blocked'])
    check(not value['unknown_outcome_quarantined'] or value['status']=='quarantined')
    check(not ('episode' in value and 'last_episode' in value))
    present='episode' in value or 'last_episode' in value
    check(present==(value['episodes_used']==1))
    e=episode(value)
    check(not present or type(e) is dict and bool(e))
    check(value['input_owned']==('episode' in value) and (not value['input_owned'] or value['armed']))
    if e is not None:
        check(type(e) is dict and EPISODE <= set(e) <= EPISODE | {'interaction_result','interrupted_action'})
        check(e['episode_id']==arm_id+':1' and type(e['outcome']) is str and re.fullmatch(r'[a-z0-9_]{1,128}',e['outcome']) is not None)
        check(integer(e['age_ticks'],0,1000) and integer(e['hotbar_slot'],0,8) and integer(e['baseline_server_tick'],-1,2147483647))
        check(all(type(e[k]) is bool for k in FLAGS) and e['confirmation_basis']==BASIS)
        check(e.get('interaction_result') in (None,'success','success_no_item_used','consume','consume_partial','pass','fail'))
        t=e['water_target'];check(type(t) is dict and set(t)=={'x','y','z'} and all(integer(t[k],-30000000,30000000) for k in t))
        check(not any(e[k] for k in FLAGS[1:]) or e['dispatch_attempted'])
        check(not e['server_landed_alive_observed'] or e['server_water_observed'] and e['server_bucket_transition_observed'])
        proved=e['server_water_observed'] and e['server_bucket_transition_observed'] and e['server_landed_alive_observed']
        check(e['rescue_confirmed']==proved and (e['outcome']=='server_placement_and_landing_observed')==proved)
        check(not proved or e['packet_send_fence_passed'] and e['baseline_server_tick']>=0)
        if 'interrupted_action' in e:
            prior=e['interrupted_action']
            check(type(prior) is dict)
            if prior:
                check(set(prior)=={'action_id','action','effect_outcome','no_auto_resume','requires_reconciliation_before_retry'}
                    and permitted_action_id is not None and prior['action_id']==permitted_action_id
                    and prior['action'] in ('follow_path','recover_environment','combat_entity','use_item','attack_entity','shoot_entity','select_hotbar')
                    and prior['effect_outcome']=='unknown_interrupted' and prior['no_auto_resume'] is True
                    and prior['requires_reconciliation_before_retry'] is True)
    if 'last_client_observation' in value:
        obs=value['last_client_observation']
        check(type(obs) is dict and set(obs)=={'client_tick','health','fall_distance','velocity_y','velocity_x','velocity_z','on_ground'})
        check(integer(obs['client_tick'],0,2147483647) and type(obs['on_ground']) is bool)
        check(all(type(obs[k]) in (int,float) and math.isfinite(obs[k]) and abs(obs[k])<=1e9 for k in ('health','fall_distance','velocity_y','velocity_x','velocity_z')))
    if 'superseded_callback_failure' in value:
        diagnostic=value['superseded_callback_failure']
        keys={'schema_version','arm_id','operation_revision','reason','diagnostic_only','original_outcome','dispatch_attempted','replacement_touched'}
        check(type(diagnostic) is dict and keys <= set(diagnostic) <= keys|{'episode_id'})
        check(integer(diagnostic['schema_version'],1,1) and integer(diagnostic['operation_revision'],0,2**53-1))
        check(type(diagnostic['arm_id']) is str and 0<len(diagnostic['arm_id'])<=128)
        check(type(diagnostic['reason']) is str and re.fullmatch(r'[a-z0-9_]{1,128}',diagnostic['reason']) is not None)
        check(diagnostic['diagnostic_only'] is True and diagnostic['replacement_touched'] is False
            and diagnostic['original_outcome']=='unknown_superseded_callback' and type(diagnostic['dispatch_attempted']) is bool)
        if 'episode_id' in diagnostic:
            check(type(diagnostic['episode_id']) is str and diagnostic['episode_id'].startswith(diagnostic['arm_id']+':')
                and diagnostic['episode_id'][len(diagnostic['arm_id'])+1:] in {str(i) for i in range(1,17)})
        # Old diagnostic data cannot settle, revive, or otherwise authorize the current owner.
    if previous is not None:
        check(value['arm_revision']>=previous['arm_revision'] and value['episodes_used']>=previous['episodes_used'],'fall_rescue_evidence_regressed')
        check(previous['armed'] or not value['armed'],'fall_rescue_authorization_resurrected')
        check(not previous['unknown_outcome_quarantined'] or value['unknown_outcome_quarantined'],'fall_rescue_quarantine_regressed')
        old=episode(previous)
        if old is not None:
            check(e is not None and e['episode_id']==old['episode_id'] and e['hotbar_slot']==old['hotbar_slot'] and e['age_ticks']>=old['age_ticks'],'fall_rescue_episode_regressed')
            check(all(not old[k] or e[k] for k in FLAGS),'fall_rescue_evidence_regressed')
            check('last_episode' not in previous or 'last_episode' in value,'fall_rescue_episode_resurrected')
            if old['dispatch_attempted']:
                check(e['water_target']==old['water_target'] and e['baseline_server_tick']==old['baseline_server_tick'],'fall_rescue_effect_binding_changed')
        oldobs=previous.get('last_client_observation')
        if oldobs is not None:
            check('last_client_observation' in value and value['last_client_observation']['client_tick']>=oldobs['client_tick'],'fall_rescue_observation_regressed')
    return deepcopy(value)
