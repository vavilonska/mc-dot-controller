"""Narrow encounter pause acknowledgement; screen installation is not pause proof."""
from __future__ import annotations

from copy import deepcopy
import re
from .encounter_contract import UUID, validate_encounter_receipt

FIELDS = {'pause_schema_version', 'expected_action_session', 'expected_world_generation',
          'expected_player_uuid', 'expected_action_id'}
META = {'op', 'request_id', 'session_id', 'submitted_at'}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def validate_pause_request(body):
    require(type(body) is dict and set(body) == FIELDS, 'invalid_encounter_pause_body')
    require(type(body['pause_schema_version']) is int and body['pause_schema_version'] == 1,
            'invalid_encounter_pause_schema')
    for key in ('expected_action_session', 'expected_world_generation', 'expected_player_uuid'):
        require(isinstance(body[key], str) and UUID.fullmatch(body[key]) is not None,
                'invalid_encounter_pause_identity')
    action_id = body['expected_action_id']
    require(isinstance(action_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', action_id) is not None,
            'invalid_encounter_pause_action_id')
    return deepcopy(body)


def pause_body(command, session_id, action_session):
    require(type(command) is dict and command.get('op') == 'encounter_pause'
            and set(command) <= META | {'body', 'expected_resident_session'}, 'invalid_encounter_pause_command')
    require(command.get('session_id', session_id) == session_id
            and command.get('expected_resident_session') == session_id, 'encounter_pause_resident_changed')
    body = validate_pause_request(command.get('body'))
    require(body['expected_action_session'] == action_session, 'encounter_pause_session_changed')
    return body


def validate_pause_receipt(value, body, encounter_request=None):
    require(type(value) is dict and value.get('ok') is True
            and value.get('protocol') == 'mineclient-bridge'
            and type(value.get('schema_version')) is int and value['schema_version'] == 2
            and type(value.get('pause_schema_version')) is int and value['pause_schema_version'] == 1
            and value.get('action') == 'ensure_paused'
            and value.get('pause_requested') is True
            and value.get('pause_screen_installed') is True
            and value.get('pause_effect_confirmed') is False
            and value.get('server_confirmed') is False, 'invalid_encounter_pause_acknowledgement')
    for name in ('already_pause_screen', 'client_paused_observed', 'expected_action_present'):
        require(type(value.get(name)) is bool, 'invalid_encounter_pause_boolean')
    for actual, expected in (('action_session', 'expected_action_session'),
                             ('world_generation', 'expected_world_generation'),
                             ('player_uuid', 'expected_player_uuid'),
                             ('expected_action_id', 'expected_action_id')):
        require(value.get(actual) == body[expected], 'encounter_pause_acknowledgement_identity_mismatch')
    require('client_action' in value and 'input_release_confirmed' in value,
            'encounter_pause_missing_action_evidence')
    action = value['client_action']
    if not value['expected_action_present']:
        require(action is None and value['input_release_confirmed'] is None,
                'encounter_pause_fabricated_missing_action')
        return deepcopy(value)
    require(type(action) is dict and action.get('ok') is True
            and type(action.get('action_schema_version')) is int and action['action_schema_version'] == 1
            and action.get('action_id') == body['expected_action_id']
            and action.get('action_session') == body['expected_action_session']
            and action.get('action') == 'combat_entity'
            and action.get('status') in ('succeeded', 'failed', 'cancelled')
            and action.get('server_confirmed') is False
            and type(action.get('result')) is dict
            and action['result'].get('world_generation') == body['expected_world_generation'],
            'encounter_pause_invalid_bound_action')
    release = action['result'].get('input_release_confirmed')
    require(type(release) is bool and value['input_release_confirmed'] is release,
            'encounter_pause_release_mismatch')
    if encounter_request is not None:
        validate_encounter_receipt(action, encounter_request)
    else:
        # Without the original request this is context-bound evidence only.
        # The harness must still compare exact target/scope to its immutable binding.
        encounter = action['result'].get('combat', {}).get('encounter')
        require(type(encounter) is dict and encounter.get('encounter_mode') == 'two_zombie_retreat_v1'
                and encounter.get('risk_remaining') is True and encounter.get('safety_assured') is False,
                'encounter_pause_non_encounter_action')
    return deepcopy(value)
