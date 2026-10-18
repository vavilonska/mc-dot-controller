"""Closed local pre-install refusal evidence; never execution or release authority."""
from copy import deepcopy
import hashlib
import json
import math
import re

REASON = 'capability_admission_not_idle'
CHECKS = ('no_coordination_owner', 'no_owner', 'watching', 'no_started_target',
          'read_only_rpc', 'no_ranged_move', 'no_environment_action',
          'observation_present', 'observation_fresh', 'idle_predicate')
COMMAND_FIELDS = {'op', 'owner_id', 'expected_defense_epoch', 'expected_context', 'duration_ms'}
CONTEXT_FIELDS = {'world_generation', 'dimension', 'player_uuid', 'action_session'}
PROOF_FIELDS = {'schema_version', 'stage', 'request_id', 'gateway_session', 'command',
                'command_sha256', 'lease_installed', 'resident_queue_submitted',
                'effects_none_proven', 'readiness'}
RECEIPT_FIELDS = {'status', 'reason', 'gameplay_effect_confirmed', 'capability_lease',
                  'acquisition_refusal', 'request_id', 'session_id',
                  'queue_request_id', 'queue_session_id'}

def digest(command):
    return hashlib.sha256(json.dumps(command, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()

def valid_command(command):
    return (type(command) is dict and set(command) == COMMAND_FIELDS
        and command['op'] in ('capability_acquire', 'external_stop_acquire')
        and type(command['owner_id']) is str and re.fullmatch(r'[0-9a-f]{32}', command['owner_id']) is not None
        and type(command['expected_defense_epoch']) is int and 0 <= command['expected_defense_epoch'] < 2**53
        and type(command['duration_ms']) is int and 100 <= command['duration_ms'] <= 86400000
        and type(command['expected_context']) is dict and set(command['expected_context']) == CONTEXT_FIELDS
        and all(type(v) is str and 0 < len(v) <= 256 for v in command['expected_context'].values()))

def valid_readiness(value):
    if (type(value) is not dict or set(value) != {'checks', 'observation_age_ms', 'max_observation_age_ms'}
            or type(value['max_observation_age_ms']) is not int or value['max_observation_age_ms'] != 800
            or type(value['checks']) is not dict or set(value['checks']) != set(CHECKS)):
        return False
    checks = value['checks']
    if not all(v is None or type(v) is bool for v in checks.values()) or False not in checks.values():
        return False
    # These are the original short-circuit checks, not a refreshed observation.
    failed = False
    for name in CHECKS:
        item = checks[name]
        if failed:
            if item is not None: return False
        elif item is False: failed = True
        elif item is not True: return False
    age = value['observation_age_ms']
    return (age is None if checks['observation_fresh'] is None else
            type(age) in (int, float) and math.isfinite(age)
            and checks['observation_fresh'] == (0 <= age <= 800))

def make_proof(command, request_id, gateway_session, readiness):
    return {'schema_version': 1, 'stage': 'pre_lease_install', 'request_id': request_id,
            'gateway_session': gateway_session, 'command': deepcopy(command),
            'command_sha256': digest(command), 'lease_installed': False,
            'resident_queue_submitted': False, 'effects_none_proven': True,
            'readiness': deepcopy(readiness)}

def validate(receipt, command, request_id, gateway_session):
    """Validate the same exact evidence independently at client and Runtime seams."""
    try:
        if (not valid_command(command) or type(request_id) is not str
                or re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id) is None
                or type(gateway_session) is not str or not 0 < len(gateway_session) <= 256
                or type(receipt) is not dict or set(receipt) != RECEIPT_FIELDS
                or receipt['request_id'] != request_id or receipt['session_id'] != gateway_session
                or receipt['queue_request_id'] is not None or receipt['queue_session_id'] is not None
                or receipt['status'] != 'failed' or receipt['reason'] != REASON
                or receipt['gameplay_effect_confirmed'] is not False or receipt['capability_lease'] is not None):
            return False
        proof = receipt['acquisition_refusal']
        return (type(proof) is dict and set(proof) == PROOF_FIELDS
            and type(proof['schema_version']) is int and proof['schema_version'] == 1
            and proof['stage'] == 'pre_lease_install' and proof['request_id'] == request_id
            and proof['gateway_session'] == gateway_session and valid_command(proof['command'])
            and proof['command'] == command and proof['command_sha256'] == digest(command)
            and proof['lease_installed'] is False and proof['resident_queue_submitted'] is False
            and proof['effects_none_proven'] is True and valid_readiness(proof['readiness']))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
