"""One explicit nearby plain drop, one bounded native movement, independent pickup proof."""
from copy import deepcopy
import math
import re

from .core import Outcome, require
from . import inventory, scoped_mobility

PROFILE = 'collect-local-observed-v1'
# Finite vanilla Item/BlockItem vocabulary; native default-component and 64-stack
# checks still apply independently to every admitted target.
ITEMS = frozenset('minecraft:' + name for name in (
    'stone', 'cobblestone', 'dirt', 'coal', 'stick', 'iron_nugget',
    'oak_log', 'spruce_log', 'birch_log', 'jungle_log', 'acacia_log', 'dark_oak_log', 'mangrove_log',
    'oak_planks', 'spruce_planks', 'birch_planks', 'jungle_planks', 'acacia_planks', 'dark_oak_planks', 'mangrove_planks',
    'raw_iron', 'charcoal', 'crafting_table', 'furnace', 'apple', 'bread',
    'beef', 'cooked_beef', 'porkchop', 'cooked_porkchop', 'chicken', 'cooked_chicken',
    'mutton', 'cooked_mutton', 'baked_potato',
))
_UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


def _typed_count(observation, stack):
    rows = inventory.items(observation)
    require(len(rows) == 36 and {r.get('slot') for r in rows} == set(range(36)),
            'collect_complete_ordinary_inventory_required')
    total = 0
    for row in rows:
        require(type(row.get('count')) is int and 0 <= row['count'] <= 64,
                'collect_invalid_inventory_count')
        if row.get('id') == stack['id']:
            require(row.get('identity_complete') is True and
                    isinstance(row.get('component_fingerprint'), str), 'collect_inventory_identity_incomplete')
            if row['component_fingerprint'] == stack['component_fingerprint']:
                total += row['count']
    return total


def _select(before, target_uuid, item_id, minimum):
    nearby = before.state.get('nearby', {})
    require(nearby.get('truncated') is False and isinstance(nearby.get('entities'), list),
            'collect_complete_nearby_required')
    matches = [r for r in nearby['entities'] if r.get('uuid') == target_uuid]
    require(len(matches) == 1, 'collect_target_missing_or_ambiguous')
    target = matches[0]
    require(target.get('type') == 'minecraft:item' and
            target.get('class') == 'net.minecraft.world.entity.item.ItemEntity' and target.get('alive') is True,
            'collect_target_type_changed')
    require(type(target.get('entity_id')) is int and -(2**31) <= target['entity_id'] < 2**31,
            'collect_target_entity_id_required')
    stack = target.get('item', {})
    require(stack.get('id') == item_id and stack.get('empty') is False and
            stack.get('identity_complete') is True and type(stack.get('count')) is int and
            minimum <= stack['count'] <= 64 and stack.get('max_stack_size') == 64 and
            all(isinstance(stack.get(k), str) and re.fullmatch(_UUID, stack[k])
                for k in ('item_fingerprint', 'component_fingerprint')), 'collect_exact_stack_required')
    require(all(type(target.get(k)) in (int, float) and math.isfinite(target[k]) for k in ('x','y','z')),
            'collect_target_position_required')
    goal = {k: math.floor(target[k]) for k in ('x', 'y', 'z')}
    points = scoped_mobility._points(before.player, goal)
    capacity = sum(64 if row.get('empty') is True else 64-row['count']
                   if row.get('id') == item_id and row.get('component_fingerprint') == stack['component_fingerprint']
                   else 0 for row in inventory.items(before))
    # The whole exact stack must fit, even when a smaller minimum was requested.
    require(capacity >= stack['count'], 'collect_entire_stack_capacity_required')
    intent = {'uuid': target_uuid, 'entity_id': target['entity_id'], 'item_id': item_id,
              **{k: stack[k] for k in ('count','item_fingerprint','component_fingerprint')},
              **{k: target[k] for k in ('x','y','z')}}
    return stack, intent, points


def collect_local(runtime, target_uuid, item_id, *, minimum=1, min_health=12, control=None):
    require(getattr(runtime, '_job_scoped_profiles', {}).get('follow_path') == PROFILE,
            'collect_profile_not_negotiated')
    require(isinstance(target_uuid, str) and re.fullmatch(_UUID, target_uuid), 'collect_target_uuid_required')
    require(item_id in ITEMS, 'collect_simple_item_unsupported')
    require(type(minimum) is int and 1 <= minimum <= 64, 'collect_invalid_minimum')
    require(type(min_health) in (int,float) and math.isfinite(min_health) and 8 <= min_health <= 20,
            'collect_invalid_min_health')
    if control is not None: control.checkpoint()
    before = runtime.observe(terrain=False, entity_radius=8)
    require(before.context[1] == 'minecraft:overworld', 'collect_overworld_required')
    # Validate inventory coverage before using its capacity or count.
    target_rows = [r for r in before.state.get('nearby', {}).get('entities', [])
                   if isinstance(r, dict) and r.get('uuid') == target_uuid]
    require(len(target_rows) == 1 and isinstance(target_rows[0].get('item'), dict), 'collect_target_missing_or_ambiguous')
    start = _typed_count(before, target_rows[0]['item'])
    stack, target, points = _select(before, target_uuid, item_id, minimum)
    command = {'op':'action', 'action':'follow_path', 'waypoints':points, 'capability_route':True,
               'timeout_ms':8000, 'min_health':min_health, 'pickup_target':target}
    movement = runtime.execute('resources.collect_local_motion', command,
        lambda old,new: scoped_mobility._settled_goal(new, points[-1]), before=before,
        max_samples=16, stable_samples=2)
    stage = {'status':movement.status, 'reason':movement.reason,
             'request_ids':list(movement.request_ids), 'evidence':deepcopy(movement.evidence)}
    # Runtime already verified exact native receipt identity and neutral-input release.
    # Only target-absence cancellation can proceed to observational inventory proof.
    eligible = movement.ok or (movement.status == 'cancelled' and
                movement.reason == 'scoped_collect_target_absent' and
                movement.evidence.get('native', {}).get('status') == 'cancelled' and
                movement.evidence.get('native', {}).get('result', {}).get('input_release_confirmed') is True)
    if not eligible:
        return Outcome(movement.status, movement.reason, movement.request_ids,
                       {**movement.evidence, 'movement':stage, 'causal_drop_attribution':False,
                        'inventory_acquisition_confirmed':False, 'automatic_replay_allowed':False},
                       movement.last_observation)
    native_id = movement.evidence.get('native_action_id') or movement.evidence.get('native',{}).get('action_id')
    require(isinstance(native_id,str) and native_id, 'collect_native_identity_missing')
    observations = [before]
    last_tick, stable, deltas = before.tick, 0, []
    for _ in range(16):
        if control is not None: control.checkpoint()
        runtime.sleeper(.05)
        sample = runtime.observe(terrain=False, entity_radius=8)
        observations.append(sample)
        require(sample.context == before.context, 'collect_context_changed')
        action = sample.state.get('client_action',{})
        require(action.get('action_id') == native_id and action.get('action_session') == before.context[3],
                'collect_native_action_replaced')
        delta = _typed_count(sample, stack) - start
        if len(observations) > 2 and sample.tick > last_tick and minimum <= delta <= stack['count']:
            stable += 1
            deltas.append(delta)
        else:
            stable, deltas = 0, []
        last_tick = max(last_tick, sample.tick)
        if stable >= 2 and deltas[-1] == deltas[-2]:
            proof = runtime.result('resources.collect_local', observations, item_id=item_id,
                target_uuid=target_uuid, component_fingerprint=stack['component_fingerprint'],
                inventory_delta=delta, requested_minimum=minimum, stable_game_times=[o.tick for o in observations[-2:]],
                evidence_kind='client_observed_stable_typed_inventory_increase',
                inventory_acquisition_confirmed=True, causal_drop_attribution=False,
                movement=stage, profile=PROFILE, automatic_replay_allowed=False)
            return Outcome(proof.status, 'typed_inventory_acquisition_observed',
                tuple(dict.fromkeys((*movement.request_ids,*proof.request_ids))), proof.evidence, sample)
    return Outcome('failed', 'collect_typed_inventory_delta_not_observed',
        tuple(dict.fromkeys((*movement.request_ids,*(o.request_id for o in observations)))),
        {'movement':stage, 'inventory_acquisition_confirmed':False, 'causal_drop_attribution':False,
         'last_typed_inventory_delta':delta, 'automatic_replay_allowed':False, 'server_confirmed':False}, observations[-1])
