"""Opt-in same-host owner envelope. No mailbox/client creation and no authority minting.

The cooperative sole watchdog writer pins this envelope from an ORIGINAL completed
capture. The resident checks it again immediately before its first native POST.
It is not authentication against another process with the same queue permissions.
"""
from copy import deepcopy
import hashlib
import json
import math
import time
import uuid

FIELDS = frozenset({'schema_version', 'owner_session', 'resident_session', 'run_id',
                    'process_id', 'action_session', 'world_generation', 'player_uuid',
                    'dimension', 'navigation_epoch', 'defense_epoch', 'origin',
                    'source_id', 'source_tick', 'source_nano', 'captured_mono', 'expires_mono',
                    'request_id', 'native_action_id', 'command_sha256'})
META = frozenset({'op', 'request_id', 'session_id', 'submitted_at', '_coordination'})


def digest_command(command):
    body = {k: v for k, v in command.items() if k not in META}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def native_action_id(session_id, request_id):
    return uuid.uuid5(uuid.UUID(session_id), request_id + ':1').hex


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def envelope(command, *, now=None):
    if '_coordination' not in command:
        return None
    e = command['_coordination']
    _require(type(e) is dict and set(e) == FIELDS and type(e['schema_version']) is int
             and e['schema_version'] == 1, 'coordination_invalid_envelope')
    for key in ('owner_session', 'resident_session', 'run_id', 'action_session',
                'world_generation', 'player_uuid', 'dimension', 'source_id', 'request_id',
                'native_action_id', 'command_sha256', 'source_nano'):
        _require(type(e[key]) is str and 1 <= len(e[key]) <= 100, 'coordination_invalid_identity')
    for key in ('process_id', 'navigation_epoch', 'defense_epoch', 'source_tick'):
        _require(type(e[key]) is int and 0 <= e[key] <= 2**53 - 1, 'coordination_invalid_epoch')
    import re
    _require(re.fullmatch(r'-?(0|[1-9][0-9]{0,18})', e['source_nano']) is not None
             and -(2**63) <= int(e['source_nano']) <= 2**63-1, 'coordination_invalid_native_clock')
    origin = e['origin']
    _require(type(origin) is dict and set(origin) == {'x', 'y', 'z'}
             and all(type(v) in (int, float) and math.isfinite(v) for v in origin.values()),
             'coordination_invalid_origin')
    for key in ('captured_mono', 'expires_mono'):
        _require(type(e[key]) in (int, float) and math.isfinite(e[key]) and e[key] >= 0,
                 'coordination_invalid_clock')
    now = time.monotonic() if now is None else now
    _require(e['captured_mono'] <= now < e['expires_mono'] <= e['captured_mono'] + .8,
             'coordination_original_capture_expired')
    _require(command.get('op') == 'action' and command.get('action') in ('follow_path', 'combat_entity'),
             'coordination_action_not_supported')
    _require(command.get('request_id', e['request_id']) == e['request_id']
             and command.get('session_id', e['resident_session']) == e['resident_session']
             and native_action_id(e['resident_session'], e['request_id']) == e['native_action_id'],
             'coordination_request_identity_changed')
    _require(command.get('coordination_step') == {'schema_version': 1, 'source_tick': e['source_tick'],
                                                'source_nano': e['source_nano']}, 'coordination_native_sample_changed')
    _require(digest_command(command) == e['command_sha256'], 'coordination_body_changed')
    expected = {'expected_world_generation': e['world_generation'],
                'expected_action_session': e['action_session'], 'expected_player_uuid': e['player_uuid'],
                'expected_navigation_epoch': e['navigation_epoch'], 'expected_origin': e['origin']}
    _require(all(command.get(k) == v and type(command.get(k)) is type(v) for k, v in expected.items()),
             'coordination_binding_changed')
    return deepcopy(e)


def check_resident(command, resident, *, before_post=False, task=None):
    e = envelope(command)
    if e is None:
        return None
    _require(resident.session_id == e['resident_session'], 'coordination_resident_replaced')
    identity = resident.bridge_identity or {}
    _require(all(identity.get(k) == e[k] and type(identity.get(k)) is type(e[k])
                 for k in ('run_id', 'process_id', 'action_session')),
             'coordination_process_replaced')
    policy = resident.observation_policy()
    _require(type(policy) is dict and type(policy.get('schema_version')) is int
             and policy['schema_version'] == 1
             and type(policy.get('requires_handoff')) is bool
             and type(policy.get('input_release_unconfirmed')) is bool,
             'coordination_policy_unconfirmed')
    _require(not policy['requires_handoff'] and not policy['input_release_unconfirmed']
             and not resident.paused and not resident.combat.active and not resident.combat.held
             and not resident.aim.active and not resident.pending,
             'coordination_owner_unavailable')
    _require(resident.active is None if task is None else
             resident.active is task and task.command is command,
             'coordination_owner_unavailable')
    if before_post:
        # The action session, world, player and navigation pair are additionally
        # checked atomically by native ClientActions. A fresh state NEVER rebases e.
        state = resident.last_status or {}
        _require(type(state.get('coordination_step_protocol')) is int
                 and state['coordination_step_protocol'] == 1, 'coordination_native_contract_required')
        _require(state.get('client_action', {}).get('status') in ('idle', 'succeeded', 'failed', 'cancelled'),
                 'coordination_native_owner_unavailable')
        _require(state.get('world', {}).get('world_generation') == e['world_generation'],
                 'coordination_world_changed')
    return e
