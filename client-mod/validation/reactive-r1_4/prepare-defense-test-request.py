#!/usr/bin/env python3
"""Prepare one new independent TEST arm JSON only; no HTTP, credentials or game input.
Freshness is the operator's explicit attestation, not a file-age or physical-release proof.
Native admission alone decides current screen/owner/input/release eligibility.
"""
from pathlib import Path
import argparse
import json
import re
import uuid

SUPPORTED_TYPES = tuple('minecraft:' + name for name in (
    'skeleton', 'stray', 'bogged', 'zombie', 'husk', 'drowned', 'spider',
    'cave_spider', 'magma_cube', 'slime', 'blaze', 'phantom'))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def context_uuid(value):
    require(isinstance(value, str), 'context_uuid_string_required')
    require(str(uuid.UUID(value)) == value, 'context_uuid_must_be_canonical')
    return value


def parse_target_types(value):
    values = [item.strip() for item in value.split(',')]
    if not (1 <= len(values) <= len(SUPPORTED_TYPES) and len(set(values)) == len(values)
            and all(item in SUPPORTED_TYPES for item in values)):
        raise argparse.ArgumentTypeError(f'Use 1-{len(SUPPORTED_TYPES)} distinct exact supported minecraft registry IDs; no aliases or Enderman')
    return values


def prepare(state, weapon_slot, *, use_shield=True, interrupt_actions=False, target_types=None):
    require(isinstance(state, dict), 'state_object_required')
    require(state.get('private_singleplayer') is True, 'private_singleplayer_required')
    player = state.get('player')
    require(isinstance(player, dict) and player.get('alive') is True, 'alive_player_required')
    require(isinstance(weapon_slot, int) and not isinstance(weapon_slot, bool)
            and 0 <= weapon_slot <= 8, 'weapon_slot_0_to_8')
    require(isinstance(use_shield, bool) and isinstance(interrupt_actions, bool), 'boolean_settings_required')
    values = list(SUPPORTED_TYPES) if target_types is None else target_types
    require(isinstance(values, list) and 1 <= len(values) <= len(SUPPORTED_TYPES)
            and all(isinstance(item, str) and item in SUPPORTED_TYPES for item in values)
            and len(set(values)) == len(values), 'exact_supported_target_types_required')
    world, action = state.get('world'), state.get('client_action')
    require(isinstance(world, dict) and isinstance(action, dict), 'fresh_context_objects_required')
    dimension = world.get('dimension')
    require(isinstance(dimension, str) and re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9/._-]+', dimension), 'actual_dimension_id_required')
    # No gear/full-health, position/route, old effect-outcome or artificial release gate.
    # Preparing is not admission: the native manager must still prove current physical release.
    return {
        'arm_id': str(uuid.uuid4()),
        'expected_world_generation': context_uuid(world.get('world_generation')),
        'expected_player_uuid': context_uuid(player.get('uuid')),
        'expected_action_session': context_uuid(action.get('action_session')),
        'expected_dimension': dimension,
        'weapon_slot': weapon_slot,
        'use_shield': use_shield,
        'interrupt_actions': interrupt_actions,
        'target_types': list(values),
        'episode_timeout_ms': 60000,
        'quiet_ticks': 30,
        'low_health': 6,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('state', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--weapon-slot', type=int, choices=range(9), required=True)
    parser.add_argument('--independent-test-world-confirmed', action='store_true', required=True)
    parser.add_argument('--fresh-state-confirmed', action='store_true', required=True)
    parser.add_argument('--use-shield', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--interrupt-actions', action='store_true', default=False,
                        help='Explicitly authorize native interruption; omission is false')
    parser.add_argument('--target-types', type=parse_target_types, default=None)
    args = parser.parse_args()
    request = prepare(json.loads(Path(args.state).read_text()), args.weapon_slot,
                      use_shield=args.use_shield, interrupt_actions=args.interrupt_actions,
                      target_types=args.target_types)
    with Path(args.output).open('x') as output:
        json.dump(request, output, indent=2, allow_nan=False)
        output.write('\n')
    print('PREPARED ONLY; not sent. Native admission still required. arm_id=' + request['arm_id'])


if __name__ == '__main__':
    main()
