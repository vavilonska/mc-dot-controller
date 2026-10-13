"""Frozen pure gate-claim contract for offline ledger reconciliation only.

Extracted from the reviewed candidate gate_off_probe module. No observation,
transport, dispatch or Resident route is included.
"""
import uuid
from encounter_contract import validate_encounter_request


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def probe_body(command, resident_session):
    fields = {'op', 'probe_schema_version', 'expected_resident_session',
              'expected_action_session', 'expected_world_generation', 'expected_player_uuid'}
    require(set(command) - {'request_id', 'session_id', 'submitted_at'} == fields
            and command['op'] == 'encounter_gate_off_probe'
            and type(command['probe_schema_version']) is int and command['probe_schema_version'] == 1,
            'gate_probe_fields')
    require(command['expected_resident_session'] == resident_session, 'gate_probe_resident_changed')
    namespace = uuid.UUID(resident_session)
    scope = [{'uuid': str(uuid.uuid5(namespace, command['request_id'] + ':unspawned:' + str(i))),
              'entity_id': 2147483646 + i, 'type': 'minecraft:zombie'} for i in range(2)]
    body = dict(action='combat_entity', action_id=uuid.uuid5(namespace, command['request_id'] + ':gate-off').hex,
        timeout_ms=15000, expected_action_session=command['expected_action_session'],
        expected_world_generation=command['expected_world_generation'],
        expected_player_uuid=command['expected_player_uuid'], target_uuid=scope[0]['uuid'],
        target_entity_id=scope[0]['entity_id'], target_type='minecraft:zombie',
        approach=False, shield=False, encounter_mode='two_zombie_retreat_v1', encounter_scope=scope)
    require(validate_encounter_request(body) is not None, 'gate_probe_request_invalid')
    return body


def ownership(value):
    status, state = value['status'], value['state']
    return {'status_action': status['client_action'], 'state_action': state['client_action'],
            'held_mappings': status['held_mappings'], 'mouse': status['mouse'],
            'held_keys': status['input_isolation']['held_keys'],
            'guarded_movement': status['guarded_movement'], 'guarded_turn': status['guarded_turn'],
            'position': [state['player'].get(k) for k in ('x', 'y', 'z', 'health')],
            'game_time': state['world'].get('game_time')}
