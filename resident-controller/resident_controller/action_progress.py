"""Read-only projection of an already accepted native action poll. No transport."""
from copy import deepcopy
import math
import uuid

MAX_AGE_SECONDS = .8
COMBAT_FIELDS = frozenset(('combat_loop_schema_version','target_uuid','target_entity_id','target_type',
    'initial_player_health','initial_target_health','player_health','target_health','attack_dispatches',
    'target_health_decreases_observed','target_health_lost_observed','player_health_lost_observed',
    'shield_blocking_ticks_observed','blocking','shield_use_ticks','safety_interrupt_reason',
    'target_dead_observed','requested_min_health','effective_min_health'))

def active_progress(task, session_id, action_session, now):
    if task is None or task.capability_unknown or task.capability_cancel_attempted:
        return None
    receipt = task.last_action_result
    captured = task.last_action_observed_monotonic
    if (type(captured) not in (int,float) or not math.isfinite(captured)
            or not 0 <= now-captured <= MAX_AGE_SECONDS or not isinstance(receipt,dict)
            or receipt.get('status') != 'running' or receipt.get('action_id') != task.action_id
            or not task.action_id or receipt.get('action_session') != action_session
            or receipt.get('action') != task.command.get('action')
            or type(receipt.get('ticks')) is not int or receipt['ticks'] < 0):
        return None
    scope=task.command.get('scoped_native_preflight')
    if (not isinstance(scope,dict) or scope.get('version') != 'scoped-native-preflight/1'
            or not isinstance(scope.get('owner_id'),str) or not scope['owner_id']
            or type(scope.get('owner_generation')) is not int or scope['owner_generation'] <= 0
            or not isinstance(scope.get('job_id'),str) or not scope['job_id']
            or scope.get('profile') != 'combat-local-observed-v1'
            or type(scope.get('defense_epoch')) is not int or scope['defense_epoch'] < 0
            or task.command.get('action') != 'combat_entity'):
        return None
    try:
        expected_id=uuid.uuid5(uuid.UUID(session_id),task.command['request_id'] + ':' + str(task.step_number)).hex
    except (ValueError,KeyError,TypeError,AttributeError):
        return None
    if expected_id != task.action_id:
        return None
    result=receipt.get('result')
    if not isinstance(result,dict):return None
    combat=result.get('combat')
    if not isinstance(combat,dict):return None
    for key in ('target_uuid','target_type','target_entity_id'):
        value=task.command.get(key)
        if (key == 'target_entity_id' and (type(value) is not int or value < 0)
                or key != 'target_entity_id' and (not isinstance(value,str) or not value)
                or type(combat.get(key)) is not type(value) or combat[key] != value):
            return None
    # Exact allowlist excludes inventory, credentials, arbitrary native payloads.
    evidence={k:deepcopy(v) for k,v in combat.items() if k in COMBAT_FIELDS
              and (v is None or type(v) in (bool,int,str) or type(v) is float and math.isfinite(v))}
    return {'schema_version':1,'resident_session':session_id,'request_id':task.command['request_id'],
        'action_id':task.action_id,'action_session':action_session,'action':receipt['action'],
        'status':'running','native_action_ticks':receipt['ticks'],
        'observed_monotonic':captured,'observed_unix':task.last_action_observed_unix,
        'freshness_limit_seconds':MAX_AGE_SECONDS,'age_seconds':now-captured,
        'owner_id':scope['owner_id'],'owner_generation':scope['owner_generation'],
        'job_id':scope['job_id'],'profile':scope['profile'],'defense_epoch':scope['defense_epoch'],
        'combat':evidence,'diagnostic_only':True,'dispatch_authority':False}
