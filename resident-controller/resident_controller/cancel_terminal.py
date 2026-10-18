"""Exact already-terminal cancel race evidence; no cancel, release or replay authority."""
from copy import deepcopy
import hashlib
import json
import re
import uuid

REASON = 'exact_cancel_original_already_terminal'
COMMAND = {'op', 'owner_id', 'expected_defense_epoch', 'expected_intent_id', 'expected_action_session'}
CONTEXT = {'world_generation', 'dimension', 'player_uuid', 'action_session'}
FIELDS = {'schema_version', 'stage', 'request_id', 'gateway_session', 'command', 'command_sha256',
          'context', 'resident_session', 'original_queue_request_id', 'original_result_sha256',
          'native_action_id', 'native_status', 'cancel_dispatched', 'input_release_confirmed',
          'semantic_postcondition_confirmed'}
RECEIPT = {'status', 'reason', 'gameplay_effect_confirmed', 'exact_cancel_terminal',
           'request_id', 'session_id', 'queue_request_id', 'queue_session_id'}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def identifier(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) is not None

def valid_command(command):
    return (type(command) is dict and set(command) == COMMAND and command['op'] == 'capability_cancel'
        and type(command['owner_id']) is str and re.fullmatch(r'[0-9a-f]{32}', command['owner_id']) is not None
        and type(command['expected_defense_epoch']) is int and 0 <= command['expected_defense_epoch'] < 2**53
        and identifier(command['expected_intent_id']) and type(command['expected_action_session']) is str
        and 0 < len(command['expected_action_session']) <= 256)

def normalized(original, intent_id, gateway_session, queue_id):
    return {**deepcopy(original), 'request_id': intent_id, 'session_id': gateway_session,
            'queue_request_id': queue_id, 'queue_session_id': original.get('session_id')}

def native_of(original):
    nested = original.get('result')
    native = nested.get('action') if type(nested) is dict else None
    return native if type(native) is dict else original.get('action')

def unsafe(value):
    if type(value) is not dict:
        return False
    if any(k in value and value[k] is not False for k in
           ('requires_handoff', 'unknown_outcome', 'post_uncertain', 'uncertain', 'input_release_unconfirmed',
            'unknown_outcome_quarantined', 'automation_blocked')):
        return True
    policy = value.get('resident_policy')
    return policy is not None and (type(policy) is not dict
        or policy.get('requires_handoff') is not False or policy.get('input_release_unconfirmed') is not False)

def make_proof(command, request_id, gateway_session, context, original):
    native = native_of(original)
    return {'schema_version': 1, 'stage': 'original_terminal_before_cancel_dispatch',
        'request_id': request_id, 'gateway_session': gateway_session, 'command': deepcopy(command),
        'command_sha256': digest(command), 'context': deepcopy(context),
        'resident_session': original['queue_session_id'], 'original_queue_request_id': original['queue_request_id'],
        'original_result_sha256': digest(original), 'native_action_id': native['action_id'],
        'native_status': native['status'], 'cancel_dispatched': False, 'input_release_confirmed': True,
        'semantic_postcondition_confirmed': False}

def validate(receipt, command, request_id, gateway_session, *, original=None, context=None):
    """Closed acknowledgement; Runtime additionally binds the exact original bytes/context."""
    try:
        if (not valid_command(command) or not identifier(request_id) or type(gateway_session) is not str
                or not 0 < len(gateway_session) <= 256 or type(receipt) is not dict or set(receipt) != RECEIPT
                or receipt['request_id'] != request_id or receipt['session_id'] != gateway_session
                or receipt['status'] != 'succeeded' or receipt['reason'] != REASON
                or receipt['gameplay_effect_confirmed'] is not False
                or receipt['queue_request_id'] is not None or receipt['queue_session_id'] is not None):
            return False
        p = receipt['exact_cancel_terminal']
        if (type(p) is not dict or set(p) != FIELDS or type(p['schema_version']) is not int or p['schema_version'] != 1
                or p['stage'] != 'original_terminal_before_cancel_dispatch' or p['request_id'] != request_id
                or p['gateway_session'] != gateway_session or not valid_command(p['command']) or p['command'] != command
                or p['command_sha256'] != digest(command) or type(p['context']) is not dict or set(p['context']) != CONTEXT
                or not all(type(v) is str and 0 < len(v) <= 256 for v in p['context'].values())
                or p['context']['action_session'] != command['expected_action_session']
                or not identifier(p['original_queue_request_id']) or type(p['resident_session']) is not str
                or p['native_action_id'] != uuid.uuid5(uuid.UUID(p['resident_session']), p['original_queue_request_id'] + ':1').hex
                or type(p['original_result_sha256']) is not str or re.fullmatch(r'[0-9a-f]{64}', p['original_result_sha256']) is None
                or p['native_status'] not in ('succeeded', 'failed', 'cancelled')
                or p['cancel_dispatched'] is not False or p['input_release_confirmed'] is not True
                or p['semantic_postcondition_confirmed'] is not False):
            return False
        if context is not None and p['context'] != context:
            return False
        if original is not None:
            n = native_of(original)
            return (type(original) is dict and original.get('request_id') == command['expected_intent_id']
                and original.get('session_id') == gateway_session and original.get('queue_session_id') == p['resident_session']
                and original.get('queue_request_id') == p['original_queue_request_id']
                and original.get('status') in ('succeeded', 'failed', 'cancelled')
                and digest(original) == p['original_result_sha256'] and type(n) is dict
                and not any(unsafe(v) for v in (original, original.get('result'), n, n.get('result')))
                and type(n.get('action_schema_version')) is int and n['action_schema_version'] == 1
                and n.get('action_id') == p['native_action_id'] and n.get('action_session') == command['expected_action_session']
                and n.get('status') == p['native_status'] and n.get('result', {}).get('input_release_confirmed') is True)
        return True
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False
