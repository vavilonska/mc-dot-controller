"""Closed owner-chain control for a standalone, bounded native fall guard.

No action takeover is admitted here. Concurrent ordinary-job protection is a
separate future policy, not permission inferred from an owner identifier.
"""
from copy import deepcopy
import re
from .transport import BridgeError

VERSION = 'native-fall-rescue-owner-guard/1'
LEASE_MS = 5000
CONTEXT = ('world_generation', 'dimension', 'player_uuid', 'action_session')


def validate(command, *, resident=False):
    metadata = {'request_id', 'session_id', 'submitted_at'} if resident else set()
    fields = {'op', 'operation', 'arm_id', 'control_owner', 'expected_context'}
    operation = command.get('operation')
    if operation in ('arm', 'renew'):
        fields.add('ttl_ms')
    if operation == 'renew':
        fields.add('expected_arm_revision')
    if resident:
        fields.add('expected_resident_session')
    if (type(command) is not dict or set(command) - metadata != fields
            or command.get('op') != 'fall_rescue_control'
            or operation not in ('arm', 'renew', 'disarm', 'status')
            or not isinstance(command.get('arm_id'), str)
            or re.fullmatch(r'[0-9a-f]{32}', command['arm_id']) is None):
        raise ValueError('invalid_fall_rescue_control')
    owner = command.get('control_owner')
    if (type(owner) is not dict or set(owner) != {'owner_id', 'owner_generation', 'job_id'}
            or not isinstance(owner.get('owner_id'), str)
            or re.fullmatch(r'[0-9a-f]{32}', owner['owner_id']) is None
            or type(owner.get('owner_generation')) is not int or not 1 <= owner['owner_generation'] <= 2**53-1
            or not isinstance(owner.get('job_id'), str) or not 1 <= len(owner['job_id']) <= 80):
        raise ValueError('fall_rescue_owner_proof_required')
    context = command.get('expected_context')
    if (type(context) is not dict or set(context) != set(CONTEXT)
            or any(not isinstance(context[k], str) or not 0 < len(context[k]) <= 128 for k in CONTEXT)
            or context['dimension'] not in ('minecraft:overworld', 'minecraft:the_end')):
        raise ValueError('fall_rescue_context_required')
    if operation in ('arm', 'renew') and (type(command['ttl_ms']) is not int or command['ttl_ms'] != LEASE_MS):
        raise ValueError('fall_rescue_owner_heartbeat_lease_required')
    if operation == 'renew' and (type(command['expected_arm_revision']) is not int or command['expected_arm_revision'] < 1):
        raise ValueError('fall_rescue_revision_required')
    return owner, context


def native_body(command):
    owner, context = validate(command, resident=True)
    operation = command['operation']
    body = {'fall_rescue_schema_version': 1, 'arm_id': command['arm_id'], 'owner_id': owner['owner_id']}
    if operation == 'arm':
        body.update(expected_action_session=context['action_session'], expected_world_generation=context['world_generation'],
                    expected_player_uuid=context['player_uuid'], ttl_ms=command['ttl_ms'], max_episodes=1,
                    permitted_action_ids=[])
    elif operation == 'renew':
        body.update(ttl_ms=command['ttl_ms'], expected_arm_revision=command['expected_arm_revision'])
    return body


def validate_status(value, command, previous=None):
    from .fall_rescue_status import validate as validate_evidence
    owner, context = validate(command, resident=True)
    value = validate_evidence(value, arm_id=command['arm_id'], owner_id=owner['owner_id'],
                             context=context, ttl_ms=LEASE_MS, previous=previous)
    operation = command['operation']
    if operation == 'arm' and (not value['armed'] or value['arm_revision'] != 1 or value['episodes_used'] != 0):
        raise ValueError('fall_rescue_native_arm_unconfirmed')
    if operation == 'renew' and (not value['armed'] or value['arm_revision'] != command['expected_arm_revision'] + 1):
        raise ValueError('fall_rescue_native_renew_unconfirmed')
    if operation in ('status','disarm') and previous is not None and value['arm_revision'] != previous['arm_revision']:
        raise ValueError('fall_rescue_native_revision_changed')
    if operation == 'disarm' and (value['armed'] or value['input_owned'] or value['automation_blocked']):
        raise ValueError('fall_rescue_native_disarm_unconfirmed')
    if value['unknown_outcome_quarantined']:
        raise ValueError('fall_rescue_native_outcome_quarantined')
    return value


def _status_command(command):
    value = deepcopy(command);value['operation'] = 'status'
    value.pop('ttl_ms', None);value.pop('expected_arm_revision', None)
    return value


def renewal_stop_proof(command):
    return {'schema_version':1,'operation':'renew','http_status':409,'error':'fall_rescue_not_armed',
            'renewal_applied':False,'request':native_body(command)}


def validate_renewal_stop(value, command, previous, proof):
    # This does not relax ordinary renewal validation. Only a separately reported
    # exact pre-effect refusal can take this read-only stopped-state path.
    from .fall_rescue_attached import exact
    if (command.get('operation') != 'renew' or not exact(proof, renewal_stop_proof(command))
            or previous is None or previous.get('armed') is not True
            or previous.get('arm_revision') != command['expected_arm_revision']
            or previous.get('episodes_used') != 0):
        raise ValueError('fall_rescue_stopped_renewal_refusal_unconfirmed')
    value = validate_status(value, _status_command(command), previous)
    if (value['armed'] or value['input_owned'] or value['automation_blocked']
            or value['unknown_outcome_quarantined'] or value['episodes_used'] != 0
            or value['remaining_ms'] != 0 or value['status'] != 'disarmed'
            or value['reason'] != 'user_screen_or_pause'
            or 'episode' in value or 'last_episode' in value):
        raise ValueError('fall_rescue_stopped_renewal_status_unconfirmed')
    return value


def validate_control_receipt(result, command, previous):
    if 'fall_rescue_renewal_stop' in result:
        return validate_renewal_stop(result.get('result'), command, previous, result['fall_rescue_renewal_stop'])
    return validate_status(result.get('result'), command, previous)


def execute(resident, command):
    owner, context = validate(command, resident=True)
    if command['expected_resident_session'] != resident.session_id:
        raise ValueError('fall_rescue_resident_changed')
    policy = resident.observation_policy()
    if (getattr(resident, 'running', True) is not True or resident.paused or policy['requires_handoff'] or policy['input_release_unconfirmed']
            or resident.active is not None or resident.pending or resident.combat.active or resident.combat.held
            or resident.aim.active):
        raise ValueError('fall_rescue_existing_owner_unknown_or_busy')
    bound = {'owner': owner, 'context': context, 'arm_id': command['arm_id']}
    existing = getattr(resident, '_fall_rescue_owner', None)
    operation = command['operation']
    if (operation == 'arm' and existing is not None) or (operation != 'arm' and existing != bound):
        raise ValueError('fall_rescue_original_owner_required')
    if context['action_session'] != (resident.bridge_identity or {}).get('action_session'):
        raise ValueError('fall_rescue_native_session_changed')
    if operation == 'arm':
        # This owner is installed before the POST. Any ambiguous outcome preserves it.
        resident._fall_rescue_owner = deepcopy(bound)
        resident._fall_rescue_status = None
    original_owner = getattr(resident, '_fall_rescue_owner', None)
    original_status = getattr(resident, '_fall_rescue_status', None)
    prior_status = deepcopy(original_status)
    original_command = deepcopy(command)
    original_bridge = resident.bridge
    original_identity = deepcopy(resident.bridge_identity)
    def same_owner():
        from .fall_rescue_attached import exact
        try:
            return (resident._fall_rescue_owner is original_owner and exact(original_owner, bound)
                and resident._fall_rescue_status is original_status and exact(original_status, prior_status)
                and exact(command, original_command) and resident.bridge is original_bridge
                and exact(resident.bridge_identity, original_identity)
                and resident.session_id == command['expected_resident_session'])
        except (ValueError, TypeError):
            return False
    def current():
        policy_now = resident.observation_policy()
        return (same_owner() and getattr(resident, 'running', True) is True and not resident.paused and not policy_now['requires_handoff']
            and not policy_now['input_release_unconfirmed'] and resident.active is None and not resident.pending
            and not resident.combat.active and not resident.combat.held and not resident.aim.active)
    stop_proof = None
    try:
        try:
            result = resident.bridge.request('GET' if operation == 'status' else 'POST',
                '/control/fall-rescue/' + operation, None if operation == 'status' else native_body(command))
        except BridgeError as exc:
            from .fall_rescue_attached import exact
            if (operation != 'renew' or exc.status != 409 or exc.uncertain is not False
                    or exc.code != 'fall_rescue_not_armed'
                    or not exact(getattr(exc,'fall_rescue_refusal',None),renewal_stop_proof(command))):
                raise
            if not current():raise BridgeError('fall_rescue_owner_changed_before_stopped_status',uncertain=True)
            # Exactly one same-original read, no repeated renewal or arm. The
            # ordinary exact disarm/neutral cleanup protocol still runs later.
            result = resident.bridge.request('GET','/control/fall-rescue/status')
            stop_proof = deepcopy(exc.fall_rescue_refusal)
            value = validate_renewal_stop(result, command, prior_status, stop_proof)
        else:
            value = validate_status(result, command, prior_status)
        if not current():raise BridgeError('fall_rescue_owner_changed_after_control',uncertain=True)
        resident._fall_rescue_status = deepcopy(value)
    except (BridgeError, ValueError, KeyError, TypeError) as exc:
        if same_owner():
            resident.paused, resident.reason = True, 'fall_rescue_control_outcome_unknown'
        raise BridgeError(str(exc), uncertain=True) from exc
    if operation == 'disarm':
        resident._fall_rescue_owner = None
    fields = {'fall_rescue_renewal_stop':stop_proof} if stop_proof is not None else {}
    resident.finish(command, 'succeeded', reason='fall_rescue_renew_refused_stopped' if stop_proof is not None else 'fall_rescue_' + operation + '_observed',
                    result=value, control_owner=deepcopy(owner), resident_policy=policy,
                    gameplay_effect_confirmed=False, **fields)
