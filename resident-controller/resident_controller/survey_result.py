"""Finite, original-command-selected mailbox envelope for historical surveys.

This contract changes transport capacity, never freshness or execution authority.
Untrusted receipt contents cannot select the larger read limit.
"""
from copy import deepcopy
import hashlib
import json

VERSION = 'historical-survey-result/1'
MAX_BYTES = 16 * 1024 * 1024
MAX_CELLS = 33 * 33 * 17
KEYS = frozenset({'op', 'terrain', 'radius', 'vertical', 'entity_radius',
                  'capability_observation', 'capability_survey'})


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def command_binding(command):
    if type(command) is not dict or set(command) != KEYS:
        raise ValueError('survey_result_command_schema')
    if (command['op'] != 'observe' or command['terrain'] is not True
            or command['capability_observation'] is not True or command['capability_survey'] is not True
            or type(command['radius']) is not int or not 1 <= command['radius'] <= 16
            or type(command['vertical']) is not int or not 2 <= command['vertical'] <= 8
            or type(command['entity_radius']) is not int or not 1 <= command['entity_radius'] <= 128
            or (2 * command['radius'] + 1) ** 2 * (2 * command['vertical'] + 1) > MAX_CELLS):
        raise ValueError('survey_result_command_bounds')
    return hashlib.sha256(encode(command)).hexdigest()


def original_command(command):
    """Resident envelope fields are not part of the immutable read options."""
    return {k: deepcopy(v) for k, v in command.items()
            if k not in ('request_id', 'session_id', 'submitted_at')}


def finish_receipt(command, receipt):
    binding = command_binding(original_command(command))
    value = deepcopy(receipt)
    value['survey_result'] = {'version': VERSION, 'command_sha256': binding,
                              'maximum_bytes': MAX_BYTES, 'execution_authority': False}
    raw = encode(value)
    if len(raw) > MAX_BYTES:
        # Read-only refusal retains exact identity and measured original size.
        # It never publishes a truncated payload as a complete observation.
        value = {k: value[k] for k in ('request_id', 'session_id', 'finished_at')}
        value.update(status='failed', reason='survey_response_capacity_exhausted',
                     survey_result={'version': VERSION, 'command_sha256': binding,
                         'maximum_bytes': MAX_BYTES, 'execution_authority': False},
                     survey_diagnostic={'encoded_bytes': len(raw),
                         'encoded_sha256': hashlib.sha256(raw).hexdigest(), 'payload_returned': False})
    return value


def validate(receipt, command, request_id, session_id):
    digest = command_binding(command)
    if (type(receipt) is not dict or receipt.get('request_id') != request_id
            or receipt.get('session_id') != session_id
            or receipt.get('status') not in ('succeeded', 'failed', 'cancelled', 'uncertain')):
        raise ValueError('survey_result_identity')
    proof = receipt.get('survey_result')
    if (type(proof) is not dict or set(proof) != {'version', 'command_sha256', 'maximum_bytes', 'execution_authority'}
            or proof['version'] != VERSION or proof['command_sha256'] != digest
            or type(proof['maximum_bytes']) is not int or proof['maximum_bytes'] != MAX_BYTES
            or proof['execution_authority'] is not False):
        raise ValueError('survey_result_contract')
    if receipt['status'] == 'succeeded':
        payload = receipt.get('result')
        terrain = payload.get('terrain') if type(payload) is dict else None
        cells = terrain.get('cells') if type(terrain) is dict else None
        expected = (2 * command['radius'] + 1) ** 2 * (2 * command['vertical'] + 1)
        if (type(terrain) is not dict or terrain.get('complete') is not True
                or terrain.get('historical_survey') is not True
                or type(terrain.get('radius')) is not int or terrain['radius'] != command['radius']
                or type(terrain.get('vertical')) is not int or terrain['vertical'] != command['vertical']
                or type(cells) is not list or len(cells) != expected):
            raise ValueError('survey_result_payload_bounds')
    return receipt
