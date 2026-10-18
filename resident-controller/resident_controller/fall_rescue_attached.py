"""Exact-action rescue authorization inside the existing serialized owner task.

No new writer, native-action retry, automatic old-job resume, or global cleanup.
"""
from copy import deepcopy
import hashlib
import json
import time
import uuid
from .transport import BridgeError

VERSION = 'native-fall-rescue-attached-policy/1'
RESERVE_MS = 10000
MAX_STATUS_POLLS = 128
PUBLIC_CAPABILITIES = frozenset({'navigate_local','navigate_step_down','navigate_route_local','engage'})
PROFILES = frozenset({'movement-flat-observed-v2', 'movement-step-down-observed-v1',
    'movement-local-segment-observed-v1', 'movement-local-segment-spatial-stop-v1',
    'movement-local-segment-spatial-stop-v2', 'combat-local-observed-v1'})
POLICY = {'schema_version': 1, 'water_bucket': True}


def exact(a, b):
    return json.dumps(a, sort_keys=True, separators=(',', ':'), allow_nan=False) == json.dumps(b, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_envelope(command):
    envelope = command.get('fall_rescue_policy')
    if envelope is None:
        return None
    scope = command.get('scoped_native_preflight')
    fields = {'version','owner_id','owner_generation','job_id','defense_epoch','ttl_ms','rescue_reserve_ms','authorization_deadline_monotonic_ms'}
    if (type(envelope) is not dict or set(envelope) != fields or envelope.get('version') != VERSION
            or type(scope) is not dict or scope.get('profile') not in PROFILES
            or command.get('action') not in ('follow_path','combat_entity')
            or any(k in command for k in ('encounter_mode','encounter_scope','encounter_pause_on_terminal'))
            or any(not exact(envelope.get(k), scope.get(k)) for k in ('owner_id','owner_generation','job_id','defense_epoch'))
            or type(envelope.get('ttl_ms')) is not int or type(command.get('timeout_ms')) is not int
            or envelope['ttl_ms'] != command['timeout_ms'] + RESERVE_MS
            or envelope.get('rescue_reserve_ms') != RESERVE_MS or type(envelope['rescue_reserve_ms']) is not int
            or not 10050 <= envelope['ttl_ms'] <= 70000
            or type(envelope.get('authorization_deadline_monotonic_ms')) is not int
            or not 1 <= envelope['authorization_deadline_monotonic_ms'] <= 2**53-1
            or command.get('expected_dimension') not in ('minecraft:overworld','minecraft:the_end')):
        raise ValueError('fall_rescue_attached_policy_invalid')
    return envelope


def binding_for(command, request_id, session):
    envelope = validate_envelope(command)
    if envelope is None:
        return None
    return {'schema_version': 1, 'arm_id': uuid.uuid5(uuid.UUID(session), request_id + ':fall-rescue').hex,
        'action_id': uuid.uuid5(uuid.UUID(session), request_id + ':1').hex, 'resident_session': session,
        'request_id': request_id, 'owner_id': envelope['owner_id'], 'owner_generation': envelope['owner_generation'],
        'job_id': envelope['job_id'], 'defense_epoch': envelope['defense_epoch'], 'ttl_ms': envelope['ttl_ms'],
        'authorization_deadline_monotonic_ms': envelope['authorization_deadline_monotonic_ms'],
        'context': {k: command['expected_' + k] for k in ('world_generation','dimension','player_uuid','action_session')}}


def validate_binding(command, session):
    expected = binding_for(command, command['request_id'], session)
    if not exact(command.get('fall_rescue_binding'), expected):
        raise ValueError('fall_rescue_gateway_binding_changed')
    return expected


def validate_status(value, binding, *, armed=None, previous=None):
    from .fall_rescue_status import validate as strict
    try:
        value = strict(value, arm_id=binding['arm_id'], owner_id=binding['owner_id'], context=binding['context'],
            ttl_ms=binding['ttl_ms'], previous=previous, permitted_action_id=binding['action_id'])
        if value['arm_revision'] != 1 or armed is not None and value['armed'] is not armed:
            raise ValueError('fall_rescue_attached_revision_or_state_changed')
    except (ValueError,KeyError,TypeError) as exc:
        raise BridgeError(str(exc),uncertain=True) from exc
    return value


def seal(task, status, outcome='unknown_interrupted'):
    value = {'schema_version': 1, 'binding': deepcopy(task.fall_rescue['binding']),
        'native_status': deepcopy(status), 'original_action': deepcopy(task.last_action_result),
        'original_outcome': outcome, 'no_auto_resume': True,
        'confirmation_basis': 'correlated_native_integrated_server_observations_not_original_action_success'}
    return {**value, 'sha256': digest(value)}


def verify_seal(value, command, request_id, resident_session):
    if type(value) is not dict or set(value) != {'schema_version','binding','native_status','original_action',
            'original_outcome','no_auto_resume','confirmation_basis','sha256'}:
        raise ValueError('fall_rescue_seal_fields_invalid')
    body = {k: v for k, v in value.items() if k != 'sha256'}
    expected = binding_for(command, request_id, resident_session)
    if (value['sha256'] != digest(body) or not exact(value['binding'], expected)
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['original_outcome'] not in ('unknown_interrupted','unknown_unresolved') or value['no_auto_resume'] is not True
            or value['confirmation_basis'] != 'correlated_native_integrated_server_observations_not_original_action_success'):
        raise ValueError('fall_rescue_seal_binding_invalid')
    validate_status(value['native_status'], expected)
    action = value['original_action']
    if action is not None and (type(action) is not dict or action.get('action_id') != expected['action_id']
            or action.get('action_session') != expected['context']['action_session']
            or action.get('action') != command['action'] or type(action.get('action_schema_version')) is not int
            or action['action_schema_version'] != 1 or action.get('status') not in ('running','succeeded','failed','cancelled')):
        raise ValueError('fall_rescue_original_action_changed')
    if value['original_outcome']=='unknown_interrupted' and (type(action) is not dict
            or action.get('status') != 'cancelled'
            or any(action.get('result',{}).get(k) is not True for k in ('preempted_by_native_fall_rescue','unknown_outcome','requires_handoff','no_auto_resume','input_release_confirmed'))
            or value['native_status']['input_owned'] or value['native_status']['armed']
            or (value['native_status'].get('last_episode') or {}).get('interrupted_action',{}).get('action') != command['action']):
        raise ValueError('fall_rescue_original_preemption_unconfirmed')
    return deepcopy(value)



def verify_cleanup(value, binding, action_name, result=None):
    """Separate known disarm evidence; never a settlement of an UNKNOWN seal."""
    from .action_safety import native_release_unconfirmed, native_handoff_required
    if (type(value) is not dict or set(value) != {'schema_version','binding','native_status','original_action'}
            or type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or type(binding) is not dict or not exact(value['binding'], binding)):
        raise ValueError('fall_rescue_cleanup_binding_invalid')
    try:
        status = validate_status(value['native_status'], binding, armed=False)
    except BridgeError as exc:
        raise ValueError('fall_rescue_cleanup_status_invalid') from exc
    action = value['original_action']
    if (any(status[k] is not False for k in ('input_owned','automation_blocked','unknown_outcome_quarantined'))
            or type(action) is not dict or type(action.get('action_schema_version')) is not int
            or action['action_schema_version'] != 1 or action.get('action_id') != binding['action_id']
            or action.get('action_session') != binding['context']['action_session']
            or action.get('action') != action_name or action.get('status') not in ('succeeded','failed','cancelled')
            or type(action.get('result')) is not dict or action['result'].get('input_release_confirmed') is not True
            or any(k in action['result'] and action['result'][k] is not False
                   for k in ('unknown_outcome','requires_handoff','preempted_by_native_fall_rescue','requires_reconciliation_before_retry','post_uncertain','uncertain','input_release_unconfirmed','partial_effects'))
            or 'effect_outcome' in action['result'] and action['result']['effect_outcome'] not in ('known','none_proven')
            or any(k in action and action[k] is not False for k in ('unknown_outcome','requires_handoff','post_uncertain','uncertain','input_release_unconfirmed'))
            or native_release_unconfirmed(action) or native_handoff_required(action)):
        raise ValueError('fall_rescue_cleanup_terminal_unconfirmed')
    if result is not None:
        if type(result) is not dict:
            raise ValueError('fall_rescue_cleanup_original_receipt_changed')
        nested = result.get('result')
        actual = result.get('action') or (nested.get('action') if type(nested) is dict else None)
        if (result.get('status') not in ('succeeded','failed','cancelled')
                or any(k in result and result[k] is not False for k in ('unknown_outcome','requires_handoff','input_release_unconfirmed','post_uncertain','uncertain'))
                or not exact(actual, action)):
            raise ValueError('fall_rescue_cleanup_original_receipt_changed')
    return deepcopy(value)


def retain_cleanup(resident, task, value):
    state = task.fall_rescue
    proof = {'schema_version':1, 'binding':deepcopy(state['binding']),
             'native_status':deepcopy(value), 'original_action':deepcopy(task.last_action_result)}
    proof = verify_cleanup(proof, state['binding'], task.command['action'])
    if not owner_current(resident,task,explicit_stop=True):
        raise BridgeError('fall_rescue_cleanup_owner_changed',uncertain=True)
    task.fall_rescue_cleanup = proof


def owner_current(resident,task,*,explicit_stop=False):
    state=task.fall_rescue
    try:
        return (resident.active is task and resident.session_id==state['binding']['resident_session']
            and (not resident.paused or explicit_stop and resident.reason in ('fall_rescue_control_outcome_unknown','fall_rescue_original_outcome_unknown')) and task.step_number==1 and task.action_id==state['binding']['action_id']
            and (resident.bridge_identity or {}).get('action_session')==state['binding']['context']['action_session']
            and exact(task.command,state['original_command']))
    except (ValueError,KeyError,TypeError):
        return False


def arm(resident, task):
    binding = validate_binding(task.command, resident.session_id)
    if binding is None:
        return
    if (resident.active is not task or task.step_number != 1 or task.action_id != binding['action_id']
            or resident.paused or resident.pending or getattr(resident,'_fall_rescue_owner',None) is not None
            or resident.combat.active or resident.combat.held or resident.aim.active
            or int(time.monotonic()*1000) + binding['ttl_ms'] > binding['authorization_deadline_monotonic_ms']
            or binding['context']['action_session'] != (resident.bridge_identity or {}).get('action_session')):
        raise ValueError('fall_rescue_attached_owner_not_ready')
    task.fall_rescue = {'binding': binding, 'arm_attempted': True, 'disarm_attempted': False,
        'deadline': time.monotonic() + binding['ttl_ms']/1000, 'waiting': False, 'last_status': None, 'status_polls': 0, 'original_command': deepcopy(task.command), 'unknown_published': False}
    body = {'fall_rescue_schema_version':1, 'arm_id':binding['arm_id'], 'owner_id':binding['owner_id'],
        'expected_action_session':binding['context']['action_session'],
        'expected_world_generation':binding['context']['world_generation'],
        'expected_player_uuid':binding['context']['player_uuid'], 'ttl_ms':binding['ttl_ms'], 'max_episodes':1,
        'permitted_action_ids':[binding['action_id']]}
    value = resident.bridge.request('POST','/control/fall-rescue/arm',body)
    task.fall_rescue['last_status'] = validate_status(value,binding,armed=True)
    if task.fall_rescue['last_status']['episodes_used'] != 0:
        raise BridgeError('fall_rescue_episode_started_before_original_admission',uncertain=True)
    if not owner_current(resident,task) or time.monotonic() >= task.fall_rescue['deadline']:
        raise BridgeError('fall_rescue_owner_changed_during_arm',uncertain=True)


def status(resident, task):
    state = task.fall_rescue
    if not owner_current(resident,task):
        raise BridgeError('fall_rescue_original_task_changed',uncertain=True)
    if state['status_polls'] >= MAX_STATUS_POLLS or time.monotonic() > state['deadline'] + 1:
        raise BridgeError('fall_rescue_status_budget_exhausted',uncertain=True)
    state['status_polls'] += 1
    value = resident.bridge.request('GET','/control/fall-rescue/status')
    value = validate_status(value,state['binding'],previous=state['last_status'])
    if not owner_current(resident,task):
        raise BridgeError('fall_rescue_original_task_changed',uncertain=True)
    state['last_status'] = value
    return value


def disarm(resident, task, *, explicit_stop=False):
    state = task.fall_rescue
    if not state or state['disarm_attempted'] or not owner_current(resident,task,explicit_stop=explicit_stop):
        raise BridgeError('fall_rescue_disarm_owner_or_attempt_changed',uncertain=True)
    state['disarm_attempted'] = True  # Commit before the single write; never retry unknown.
    b = state['binding']
    value = resident.bridge.request('POST','/control/fall-rescue/disarm',
        {'fall_rescue_schema_version':1,'arm_id':b['arm_id'],'owner_id':b['owner_id']})
    value = validate_status(value,b,armed=False,previous=state['last_status'])
    if value['input_owned'] or value['automation_blocked'] and not value['unknown_outcome_quarantined'] or not owner_current(resident,task,explicit_stop=explicit_stop):
        raise BridgeError('fall_rescue_disarm_release_unconfirmed',uncertain=True)
    state['last_status'] = value
    return value


def terminal(resident, task, result):
    """True means retain the original task or finish it unknown; no recipe continuation."""
    if not task.fall_rescue:
        return False
    task.last_action_result = deepcopy(result)
    value = status(resident,task)
    episode = value.get('episode') or value.get('last_episode') or {}
    interrupted = result.get('result',{}).get('preempted_by_native_fall_rescue') is True
    involved = interrupted or episode.get('dispatch_attempted') is True or value['input_owned'] or value['unknown_outcome_quarantined']
    if involved:
        task.fall_rescue['waiting'] = True
        return settle(resident,task,value)
    # Normal terminal, no rescue effect: revoke before generic terminal handling.
    value = disarm(resident,task)
    if value['unknown_outcome_quarantined']:
        task.fall_rescue['waiting'] = True
        return settle(resident,task,value)
    retain_cleanup(resident,task,value)
    task.fall_rescue = None
    return False


def settle(resident, task, value=None):
    value = status(resident,task) if value is None else value
    if value['input_owned']:
        task.wake_at = time.monotonic() + .1
        return True
    if (value['armed'] or not (value.get('last_episode') or {}).get('interrupted_action')
            or (task.last_action_result or {}).get('result',{}).get('preempted_by_native_fall_rescue') is not True):
        raise BridgeError('fall_rescue_original_preemption_not_settled',uncertain=True)
    # Native episode has released its own control. Original action remains unknown.
    evidence = seal(task,value)
    if not owner_current(resident,task):
        raise BridgeError('fall_rescue_original_owner_changed_before_finish',uncertain=True)
    resident.paused,resident.reason = True,'fall_rescue_original_outcome_unknown'
    task.capability_unknown=True
    task.fall_rescue['unknown_published']=True
    resident.finish(task.fall_rescue['original_command'],'uncertain',reason='native_fall_rescue_interrupted_original',
        action=task.last_action_result,action_id=task.action_id,fall_rescue=evidence,unknown_outcome=True,no_auto_resume=True,
        input_release_unconfirmed=False,resident_policy={'schema_version':1,'requires_handoff':True,'input_release_unconfirmed':False})
    if resident.active is task:
        resident.active=None
    resident.publish()
    return True


def advance_waiting(resident, task):
    if not task or not task.fall_rescue or not task.fall_rescue['waiting']:
        return False
    if time.monotonic() < task.wake_at:
        return True
    try:
        settle(resident,task)
    except (BridgeError,ValueError,KeyError,TypeError) as exc:
        unknown(resident,task,exc)
    return True


def unknown(resident, task, exc):
    """Retain the original uncertainty; never finish or cancel a replacement task."""
    task.capability_unknown=True
    state=task.fall_rescue
    if state is None or state['unknown_published']:return
    state['unknown_published']=True
    if resident.active is task:
        resident.paused,resident.reason=True,'fall_rescue_control_outcome_unknown'
    value=state.get('last_status')
    fields={'fall_rescue':seal(task,value,'unknown_unresolved')} if value is not None else {}
    resident.finish(state['original_command'],'uncertain',reason='fall_rescue_attached_unknown',action=task.last_action_result,
        action_id=state['binding']['action_id'],unknown_outcome=True,no_auto_resume=True,
        resident_policy={'schema_version':1,'requires_handoff':True,'input_release_unconfirmed':True},
        input_release_unconfirmed=True,**fields)
    resident.publish()


def cancel_exact(resident,task,command,*,explicit_stop=False):
    """Explicit stop: disarm the exact known guard before the exact ordinary cancel."""
    try:
        value=disarm(resident,task,explicit_stop=explicit_stop)
        native=task.last_action_result
        if type(native) is not dict or native.get('status') not in ('succeeded','failed','cancelled'):
            native=resident.bridge.request('POST','/control/action/cancel',
                {'action_id':command['expected_action_id'],'expected_action_session':command['expected_action_session']})
        if (not owner_current(resident,task,explicit_stop=explicit_stop) or type(native) is not dict
                or native.get('action_id')!=command['expected_action_id']
                or native.get('action_session')!=command['expected_action_session']
                or native.get('action_schema_version')!=1 or native.get('status') not in ('succeeded','failed','cancelled')
                or native.get('result',{}).get('input_release_confirmed') is not True):
            raise BridgeError('fall_rescue_exact_cancel_unconfirmed',uncertain=True)
        task.last_action_result=deepcopy(native)
        interrupted=native.get('result',{}).get('preempted_by_native_fall_rescue') is True
        proof={'schema_version':1,'original_request_id':task.command['request_id'],'action_id':command['expected_action_id'],
            'action_session':command['expected_action_session'],'admitted':True,'input_release_confirmed':True,
            'native_status':native['status'],'fall_rescue_disarmed':True}
        if task.fall_rescue['unknown_published']:
            # A later explicit stop has its own receipt. Never overwrite the first unknown original.
            resident.finish(command,'succeeded',exact_cancel=proof,result=native,fall_rescue_stop=deepcopy(value),
                original_outcome='unknown',no_auto_resume=True,resident_policy=resident.observation_policy())
            return
        if interrupted or value['unknown_outcome_quarantined']:
            settle(resident,task,value)
        else:
            retain_cleanup(resident,task,value)
            task.fall_rescue=None
            resident.finish(task.command,native['status'],reason=native.get('reason',native['status']),action=native,
                            exact_cancel=proof,postcondition_observed=False,fall_rescue_cleanup=deepcopy(task.fall_rescue_cleanup))
            if resident.active is task:resident.active=None
            resident.publish()
        resident.finish(command,'succeeded',exact_cancel=proof,result=native)
    except (BridgeError,ValueError,KeyError,TypeError) as exc:
        unknown(resident,task,exc)
        raise BridgeError('fall_rescue_explicit_stop_unconfirmed',uncertain=True) from exc


def lifecycle_command(resident,command):
    """Intercept legacy lifecycle takeover before it can erase the attached original."""
    task=resident.active
    attached=task is not None and getattr(task,'fall_rescue',None) is not None
    held=resident.paused and resident.reason in ('fall_rescue_control_outcome_unknown','fall_rescue_original_outcome_unknown')
    if not attached and not held:return False
    operation=command.get('op')
    if operation in ('observe','scan_status','capability_cancel_exact'):return False
    stopping=(operation in ('cancel','shutdown') or operation=='direct' and command.get('endpoint')=='release-all' and command.get('body')=={})
    if command.get('watchdog_observation_fallback') is True:stopping=False
    if not stopping or not attached:
        resident.finish(command,'failed',reason='fall_rescue_original_requires_exact_stop_or_adjudication',
            original_outcome='unknown',no_auto_resume=True,resident_policy=resident.observation_policy())
        if operation=='shutdown':resident.running=False
        return True
    state=task.fall_rescue
    exact_command={**command,'expected_request_id':state['original_command']['request_id'],
        'expected_resident_session':state['binding']['resident_session'],
        'expected_action_session':state['binding']['context']['action_session'],
        'expected_action_id':state['binding']['action_id']}
    try:
        if task.capability_cancel_attempted:raise BridgeError('fall_rescue_stop_already_attempted',uncertain=True)
        task.capability_cancel_attempted=True
        cancel_exact(resident,task,exact_command,explicit_stop=True)
    except (BridgeError,ValueError,KeyError,TypeError) as exc:
        unknown(resident,task,exc)
        resident.finish(command,'uncertain',reason='fall_rescue_explicit_stop_unconfirmed',
            original_outcome='unknown',no_auto_resume=True,resident_policy=resident.observation_policy())
    if operation=='shutdown':resident.running=False
    return True


def unexpected_interrupt(resident,task,reason):
    error=BridgeError('fall_rescue_bound_stop_required',uncertain=True)
    error.attached_fall_owner=True
    unknown(resident,task,error)
    raise error
