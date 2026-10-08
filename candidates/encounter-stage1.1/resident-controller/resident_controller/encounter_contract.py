"""Strict opt-in encounter wire contract; no transport or gameplay operations.

This receipt proves only bounded client-observed clearance for the same two
living zombies. Risk and handoff remain explicit even after that observation.
Legacy action bodies without encounter fields are intentionally untouched.
"""
from __future__ import annotations

import copy
import math
import re

MODE = 'two_zombie_retreat_v1'
OUTCOME_SCOPE = 'two_scoped_living_zombies_beyond_8_for_3_samples'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')
META = {'op', 'session_id', 'request_id', 'submitted_at'}
FIELDS = {'action_id', 'action', 'timeout_ms', 'expected_world_generation',
          'expected_player_uuid', 'expected_action_session', 'expected_navigation_epoch',
          'expected_origin', 'target_entity_id', 'target_uuid', 'target_type',
          'approach', 'shield', 'encounter_mode', 'encounter_scope', 'encounter_pause_on_terminal'}
IDENTITY_FIELDS = {'entity_id', 'uuid', 'type'}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _uuid(value):
    return isinstance(value, str) and UUID.fullmatch(value) is not None


def _integer(value, minimum=0, maximum=2147483647):
    return type(value) is int and minimum <= value <= maximum


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _identity(value):
    _require(type(value) is dict and set(value) == IDENTITY_FIELDS,
             'encounter_scope_identity_fields')
    _require(_integer(value['entity_id']) and _uuid(value['uuid'])
             and value['type'] == 'minecraft:zombie', 'encounter_scope_identity_invalid')


def _scope(value):
    _require(type(value) is list and len(value) == 2, 'encounter_scope_requires_two')
    for entity in value:
        _identity(entity)
    _require(value[0]['entity_id'] != value[1]['entity_id']
             and value[0]['uuid'] != value[1]['uuid'], 'encounter_scope_identity_duplicate')


def validate_encounter_request(body):
    """Return an immutable-by-copy contract, or None for untouched legacy input."""
    if not any(field in body for field in ('encounter_mode', 'encounter_scope', 'encounter_pause_on_terminal')):
        return None
    _require(body.get('action') == 'combat_entity', 'encounter_requires_combat_entity')
    _require(body.get('encounter_mode') == MODE, 'encounter_mode_invalid')
    _require(set(body) <= FIELDS, 'encounter_unknown_or_forbidden_field')
    if 'encounter_pause_on_terminal' in body:
        _require(type(body['encounter_pause_on_terminal']) is bool,
                 'encounter_pause_on_terminal_requires_boolean')
    _require(body.get('approach') is False and body.get('shield') is False,
             'encounter_requires_approach_false_shield_false')
    _require(body.get('target_type') == 'minecraft:zombie'
             and _integer(body.get('target_entity_id')) and _uuid(body.get('target_uuid')),
             'encounter_target_identity_invalid')
    for field in ('expected_world_generation', 'expected_player_uuid', 'expected_action_session'):
        _require(_uuid(body.get(field)), 'encounter_' + field + '_invalid')
    _require(_integer(body.get('timeout_ms', 15000), 50, 30000), 'encounter_timeout_invalid')
    _require(('expected_origin' in body) == ('expected_navigation_epoch' in body),
             'encounter_navigation_binding_pair_required')
    if 'expected_origin' in body:
        origin = body['expected_origin']
        _require(_integer(body['expected_navigation_epoch'], 0, 9007199254740991)
                 and type(origin) is dict and set(origin) == {'x', 'y', 'z'}
                 and all(_finite(v) and abs(v) <= 29999900 for v in origin.values()),
                 'encounter_navigation_binding_invalid')
    _scope(body.get('encounter_scope'))
    target = {'entity_id': body['target_entity_id'], 'uuid': body['target_uuid'],
              'type': body['target_type']}
    _require(target in body['encounter_scope'], 'encounter_scope_target_missing')
    return copy.deepcopy(body)


def validate_encounter_command(command):
    if not any(field in command for field in ('encounter_mode', 'encounter_scope', 'encounter_pause_on_terminal')):
        return None
    _require(command.get('op') == 'action', 'encounter_requires_action_operation')
    return validate_encounter_request({k: v for k, v in command.items() if k not in META})


def _validate_terminal_pause(result):
    pause = result.get('encounter_terminal_pause')
    _require(type(pause) is dict and type(pause.get('hook_schema_version')) is int
             and pause['hook_schema_version'] == 1
             and pause.get('requested') is True and pause.get('attempted') is True
             and type(pause.get('pause_call_attempted')) is bool
             and pause.get('outcome') in ('screen_installed', 'rejected', 'unconfirmed')
             and pause.get('pause_effect_confirmed') is False
             and pause.get('server_confirmed') is False,
             'encounter_receipt_terminal_pause_invalid')
    for field in ('pause_screen_installed', 'already_pause_screen', 'client_paused_observed'):
        _require(field in pause and (pause[field] is None or type(pause[field]) is bool),
                 'encounter_receipt_terminal_pause_observation_invalid')
    _require(type(result.get('input_release_confirmed')) is bool
             and type(pause.get('input_release_confirmed')) is bool
             and pause['input_release_confirmed'] is result['input_release_confirmed'],
             'encounter_receipt_terminal_pause_release_mismatch')
    if pause['outcome'] == 'screen_installed':
        _require(pause['pause_call_attempted'] is True and pause['pause_screen_installed'] is True,
                 'encounter_receipt_terminal_pause_installation_unproved')
    for field in ('error_type', 'reason'):
        if field in pause:
            _require(isinstance(pause[field], str), 'encounter_receipt_terminal_pause_diagnostic_invalid')


def validate_encounter_receipt(receipt, request):
    """Validate running and terminal proof against the exact original request.

    The three-sample counter is a native-client claim, not an independently
    reproduced simulation or a promise of present/future safety.
    """
    if request is None:
        return
    _require(type(receipt) is dict and receipt.get('action') == 'combat_entity'
             and type(receipt.get('action_schema_version')) is int
             and receipt['action_schema_version'] == 1
             and receipt.get('ok') is True and receipt.get('server_confirmed') is False,
             'encounter_receipt_action_invalid')
    result = receipt.get('result')
    _require(type(result) is dict and result.get('world_generation') == request['expected_world_generation']
             and receipt.get('action_session') == request['expected_action_session'],
             'encounter_receipt_context_mismatch')
    combat = result.get('combat') if type(result) is dict else None
    encounter = combat.get('encounter') if type(combat) is dict else None
    _require(type(encounter) is dict, 'encounter_receipt_missing')
    # The echo confirms the original opt-in, not that a pause has taken effect.
    # Absent/false requests retain compatibility with receipts predating this flag.
    if 'encounter_pause_on_terminal' in encounter:
        _require(type(encounter['encounter_pause_on_terminal']) is bool,
                 'encounter_receipt_pause_on_terminal_invalid')
    _require((encounter.get('encounter_pause_on_terminal') is True)
             == (request.get('encounter_pause_on_terminal') is True),
             'encounter_receipt_pause_on_terminal_mismatch')
    _require(type(encounter.get('encounter_schema_version')) is int
             and encounter['encounter_schema_version'] == 1
             and encounter.get('encounter_mode') == MODE
             and encounter.get('encounter_scope') == request['encounter_scope'],
             'encounter_receipt_scope_mismatch')
    # Revalidate types: Python True == 1 must never substitute for an entity ID.
    _scope(encounter.get('encounter_scope'))
    _require(encounter.get('offense_disabled') is True
             and encounter.get('risk_remaining') is True
             and encounter.get('requires_handoff') is True
             and encounter.get('safety_assured') is False,
             'encounter_receipt_risk_or_offense_invalid')
    _require(combat.get('attack_completed') is False
             and type(combat.get('attack_dispatches')) is int and combat['attack_dispatches'] == 0
             and combat.get('target_dead_observed') is False
             and combat.get('hits_confirmed') is False
             and combat.get('server_confirmed') is False
             and combat.get('safety_assured') is False and combat.get('risk_remaining') is True,
             'encounter_receipt_combat_claim_invalid')
    _require(combat.get('target_entity_id') == request['target_entity_id']
             and type(combat.get('target_entity_id')) is int
             and combat.get('target_uuid') == request['target_uuid']
             and combat.get('target_type') == request['target_type'],
             'encounter_receipt_target_mismatch')
    _require('outcome_scope' in encounter, 'encounter_receipt_outcome_missing')
    _require(_integer(encounter.get('clearance_observations'), 0, 3)
             and _finite(encounter.get('danger_radius')) and encounter['danger_radius'] == 8,
             'encounter_receipt_observation_bounds_invalid')
    status = receipt.get('status')
    _require(status in ('running', 'succeeded', 'failed', 'cancelled'),
             'encounter_receipt_status_invalid')
    if status == 'running':
        _require(encounter.get('outcome_scope') is None, 'encounter_receipt_premature_outcome')
        return
    if request.get('encounter_pause_on_terminal') is True:
        _validate_terminal_pause(result)
    _require(encounter.get('terminal_status') == status
             and encounter.get('terminal_reason') == receipt.get('reason')
             and isinstance(receipt.get('reason'), str) and bool(receipt['reason']),
             'encounter_receipt_terminal_mismatch')
    if status != 'succeeded':
        _require(encounter.get('outcome_scope') is None, 'encounter_receipt_failure_outcome_invalid')
        return
    _require(receipt.get('reason') == 'encounter_clearance_observed'
             and encounter.get('outcome_scope') == OUTCOME_SCOPE
             and encounter['clearance_observations'] == 3
             and result.get('input_release_confirmed') is True,
             'encounter_receipt_success_not_proved')
    threats = encounter.get('scoped_living_threats')
    _require(type(threats) is list and len(threats) == 2,
             'encounter_receipt_living_scope_missing')
    for actual, expected in zip(threats, request['encounter_scope']):
        _require(type(actual) is dict and set(actual) == IDENTITY_FIELDS | {'known', 'alive', 'clearance'},
                 'encounter_receipt_living_fields_invalid')
        identity = {key: actual[key] for key in IDENTITY_FIELDS}
        _identity(identity)
        _require(identity == expected and actual.get('known') is True and actual.get('alive') is True
                 and _finite(actual.get('clearance')) and actual['clearance'] > 8,
                 'encounter_receipt_living_clearance_invalid')
