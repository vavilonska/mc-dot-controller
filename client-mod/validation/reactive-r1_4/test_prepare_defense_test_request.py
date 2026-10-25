#!/usr/bin/env python3
"""Offline tests of the actual preparer and CLI; no HTTP, credential or game access."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
sys.dont_write_bytecode = True
W = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('defense_preparer', W / 'prepare-defense-test-request.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BASE = {
    'private_singleplayer': True,
    'player': {'alive': True, 'uuid': '00000000-0000-0000-0000-000000000002'},
    'world': {'world_generation': '00000000-0000-0000-0000-000000000001', 'dimension': 'minecraft:the_nether'},
    'client_action': {'action_session': '00000000-0000-0000-0000-000000000003'},
}
FIELDS = {'arm_id', 'expected_world_generation', 'expected_player_uuid', 'expected_action_session',
          'expected_dimension', 'weapon_slot', 'use_shield', 'interrupt_actions', 'target_types',
          'episode_timeout_ms', 'quiet_ticks', 'low_health'}
checks = []


def case(name, accepted=True, state=None, slot=0, **kwargs):
    state = copy.deepcopy(BASE if state is None else state)
    before = copy.deepcopy(state)
    try:
        result = module.prepare(state, slot, **kwargs)
    except (ValueError, TypeError, KeyError):
        assert not accepted, name
    else:
        assert accepted, name
        assert set(result) == FIELDS and str(uuid.UUID(result['arm_id'])) == result['arm_id']
        assert result['expected_world_generation'] == state['world']['world_generation']
        assert result['expected_player_uuid'] == state['player']['uuid']
        assert result['expected_action_session'] == state['client_action']['action_session']
        assert result['expected_dimension'] == state['world']['dimension']
        assert result['weapon_slot'] == slot
        assert result['episode_timeout_ms'] == 60000 and result['quiet_ticks'] == 30 and result['low_health'] == 6
        assert result['use_shield'] == kwargs.get('use_shield', True)
        assert result['interrupt_actions'] == kwargs.get('interrupt_actions', False)
        assert result['target_types'] == kwargs.get('target_types', list(module.SUPPORTED_TYPES))
    assert state == before, name + ': mutated input or old history'
    checks.append(name)


case('minimal_context_no_gear_position_route_or_old_release_required')
for slot in range(9):
    case('weapon_slot_' + str(slot), slot=slot)
for slot in (-1, 9, True, '0', .5, None):
    case('bad_slot_' + repr(slot), False, slot=slot)
for name in module.SUPPORTED_TYPES:
    case('exact_type_' + name, target_types=[name])
case('all_12_reverse_order', target_types=list(reversed(module.SUPPORTED_TYPES)))
for bad in ([], ['husk'], ['minecraft:Skeleton'], ['minecraft:enderman'], ['minecraft:*'],
            ['minecraft:skeleton', 'minecraft:skeleton'], list(module.SUPPORTED_TYPES) + ['minecraft:skeleton'],
            ['minecraft:player'], [1], [True], [{}], [['minecraft:husk']], 'minecraft:husk'):
    case('invalid_types_' + repr(bad), False, target_types=bad)
for shield in (True, False):
    for interrupt in (True, False):
        case('settings_' + repr((shield, interrupt)), use_shield=shield, interrupt_actions=interrupt)
for key in ('use_shield', 'interrupt_actions'):
    for value in ('true', 1, None):
        case('not_bool_' + key + repr(value), False, **{key: value})
for name, mutate in (
    ('not_private', lambda s: s.update(private_singleplayer=False)),
    ('malformed_private', lambda s: s.update(private_singleplayer='true')),
    ('dead', lambda s: s['player'].update(alive=False)),
    ('malformed_alive', lambda s: s['player'].update(alive=1)),
    ('bad_world_uuid', lambda s: s['world'].update(world_generation='old-world')),
    ('bad_player_uuid', lambda s: s['player'].update(uuid=None)),
    ('bad_session_uuid', lambda s: s['client_action'].update(action_session='')),
    ('noncanonical_uuid', lambda s: s['client_action'].update(action_session='00000000000000000000000000000003')),
    ('empty_dimension', lambda s: s['world'].update(dimension='')),
    ('wildcard_dimension', lambda s: s['world'].update(dimension='minecraft:*')),
    ('missing_world', lambda s: s.pop('world')),
    ('missing_session_object', lambda s: s.pop('client_action')),
):
    state = copy.deepcopy(BASE)
    mutate(state)
    case(name, False, state=state)
# These are prepare-only successes, NOT native admission or physical-release claims.
for name, mutate in (
    ('low_health_no_armor_no_shield', lambda s: s['player'].update(health=2, armor=[], offhand={})),
    ('empty_selected_slot', lambda s: s['player'].update(selected_slot=0, hotbar=[])),
    ('screen_open_native_must_decide', lambda s: s.update(screen_open=True, paused=True)),
    ('active_inputs_native_must_decide', lambda s: s.update(held_inputs={'neutral': False})),
    ('running_action_native_must_decide', lambda s: s['client_action'].update(status='running', input_owner='action')),
    ('known_failed_release', lambda s: s['client_action'].update(status='failed', result={'input_release_confirmed': True})),
    ('effect_unknown_released_retained', lambda s: s['client_action'].update(status='failed', result={'unknown_outcome': True, 'requires_handoff': True, 'input_release_confirmed': True})),
    ('release_unknown_native_must_reject_if_unproven', lambda s: s['client_action'].update(status='failed', result={'unknown_outcome': True, 'input_release_confirmed': False})),
):
    state = copy.deepcopy(BASE)
    mutate(state)
    case(name, state=state)

FLAGS = ['--independent-test-world-confirmed', '--fresh-state-confirmed']
with tempfile.TemporaryDirectory(prefix='MDC-DEFENSE-PREPARER-') as directory:
    root = Path(directory)
    state = root / 'state.json'
    out = root / 'arm.json'
    state.write_text(json.dumps(BASE))
    command = [sys.executable, str(W / 'prepare-defense-test-request.py'), '--state', str(state),
               '--output', str(out), '--weapon-slot', '0']
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    for flag in FLAGS:
        run = subprocess.run(command + [x for x in FLAGS if x != flag], capture_output=True, text=True, env=env)
        assert run.returncode != 0 and not out.exists()
        checks.append('required_flag_' + flag)
    run = subprocess.run(command + FLAGS, capture_output=True, text=True, env=env)
    assert run.returncode == 0, run.stderr
    first = json.loads(out.read_text())
    assert first['interrupt_actions'] is False and first['use_shield'] is True
    assert first['target_types'] == list(module.SUPPORTED_TYPES) and set(first) == FIELDS
    checks.append('CLI_default_12_keys_11_types_no_silent_interrupt')
    original = out.read_bytes()
    run = subprocess.run(command + FLAGS, capture_output=True, text=True, env=env)
    assert run.returncode != 0 and out.read_bytes() == original
    checks.append('exclusive_output_no_overwrite')
    second = root / 'explicit.json'
    command[command.index(str(out))] = str(second)
    run = subprocess.run(command + FLAGS + ['--interrupt-actions', '--no-use-shield', '--target-types', 'minecraft:husk,minecraft:skeleton'], capture_output=True, text=True, env=env)
    assert run.returncode == 0, run.stderr
    explicit = json.loads(second.read_text())
    assert explicit['interrupt_actions'] is True and explicit['use_shield'] is False
    assert explicit['target_types'] == ['minecraft:husk', 'minecraft:skeleton'] and explicit['arm_id'] != first['arm_id']
    checks.append('CLI_explicit_interrupt_and_no_shield_new_arm_id')
    command[command.index(str(second))] = str(root / 'rejected.json')
    for invalid in ('minecraft:enderman', 'skeleton', 'minecraft:husk,minecraft:husk', ''):
        run = subprocess.run(command + FLAGS + ['--target-types', invalid], capture_output=True, text=True, env=env)
        assert run.returncode != 0 and not (root / 'rejected.json').exists()
        checks.append('CLI_reject_target_' + repr(invalid))
print(f'Defense request preparer PASS {len(checks)} offline scenarios; actual helper/CLI; prepare-only, native admission and live combat NOT_RUN; no HTTP/token/game.')
