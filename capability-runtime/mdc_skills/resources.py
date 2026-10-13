"""Bounded resource selection, real mining and separate observed pickup evidence."""
from __future__ import annotations

import math

from .core import SkillError, require
from . import inventory, reach

AIR = {'minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'}


def find(runtime, block_ids, *, limit=32):
    require(isinstance(block_ids, (list, tuple, set, frozenset)) and block_ids
            and all(isinstance(x, str) and x.startswith('minecraft:') for x in block_ids),
            'explicit_resource_block_ids_required')
    require(type(limit) is int and 1 <= limit <= 128, 'invalid_resource_limit')
    observation = runtime.observe(terrain=True)
    terrain = observation.terrain
    require(isinstance(terrain, dict) and terrain.get('complete') is True, 'complete_terrain_required')
    found = [cell for cell in terrain.get('cells', []) if cell.get('status') == 'loaded'
             and cell.get('known') is True and cell.get('id_truncated') is False
             and cell.get('id') in block_ids]
    found.sort(key=lambda c: sum((c[k] + .5 - observation.player[k]) ** 2 for k in ('x', 'y', 'z')))
    return runtime.result('resources.find', [observation], resources=found[:limit],
                          matched_total=len(found), truncated=len(found) > limit,
                          scope='currently_loaded_local_terrain')


def mine(runtime, target, *, expected_item_id=None, hotbar_slot=None, require_drops=False):
    """Mine one explicitly observed block. This result never claims item pickup."""
    target = reach.coordinate(target)
    before = runtime.observe(terrain=True)
    cell = reach.block_at(before, target)
    require(cell['id'] not in AIR, 'resource_block_already_absent')
    if expected_item_id is not None:
        require(cell['id'] == expected_item_id, 'resource_target_id_mismatch')
    require(cell.get('fluid') == 'minecraft:empty' and cell.get('hazards') == [],
            'resource_target_fluid_or_hazard')
    # Mining a supporting floor or a cell directly above the player can create
    # unplanned falls/cave-ins; unsupported geological stability stays blocked.
    feet = {k: math.floor(before.player[k]) for k in ('x', 'y', 'z')}
    require(not (target['x'] == feet['x'] and target['z'] == feet['z']
                 and target['y'] <= feet['y'] + 2), 'resource_unsafe_player_column')
    for dx, dy, dz in reach.FACES.values():
        neighbor = reach.block_at(before, {'x': target['x'] + dx, 'y': target['y'] + dy, 'z': target['z'] + dz})
        require(neighbor.get('fluid') == 'minecraft:empty' and neighbor.get('hazards') == [],
                'resource_adjacent_fluid_or_hazard')
    above = reach.block_at(before, {**target, 'y': target['y'] + 1})
    require(above.get('id') not in {'minecraft:sand', 'minecraft:red_sand', 'minecraft:gravel',
                                  'minecraft:anvil', 'minecraft:chipped_anvil', 'minecraft:damaged_anvil'}
            and not above.get('id', '').endswith('_concrete_powder')
            and above.get('fluid') == 'minecraft:empty', 'resource_falling_or_fluid_above')
    command = {'op': 'action', 'action': 'break_block', 'target': target,
               'expected_block_id': cell['id'], 'expected_block_properties': cell['properties'],
               'require_correct_tool': bool(require_drops), 'timeout_ms': 20000}
    if hotbar_slot is not None:
        require(type(hotbar_slot) is int and 0 <= hotbar_slot <= 8, 'invalid_hotbar_slot')
        command['hotbar_slot'] = hotbar_slot
    def verified(old, new):
        try:
            return reach.block_at(new, target)['id'] in AIR
        except SkillError:
            return False
    return runtime.execute('resources.mine', command, verified, before=before)


def _drops(observation, item_id):
    nearby = observation.state.get('nearby', {})
    require(nearby.get('truncated') is False, 'complete_nearby_entities_required')
    entities = nearby.get('entities')
    require(isinstance(entities, list), 'nearby_entity_observation_required')
    return [row for row in entities if row.get('type') == 'minecraft:item'
            and row.get('alive') is True and row.get('item', {}).get('id') == item_id
            and row['item'].get('count', 0) > 0 and row.get('uuid')]


def collect(runtime, item_id, *, minimum=1, max_targets=8, max_steps=64):
    return _collect(runtime, item_id, minimum=minimum, max_targets=max_targets, max_steps=max_steps)


def _collect(runtime, item_id, *, minimum=1, max_targets=8, max_steps=64, baseline=None):
    require(isinstance(item_id, str) and item_id.startswith('minecraft:'), 'item_id_required')
    require(type(minimum) is int and 1 <= minimum <= 64, 'invalid_pickup_amount')
    require(type(max_targets) is int and 1 <= max_targets <= 16, 'invalid_pickup_budget')
    first = runtime.observe(terrain=True)
    if baseline is not None:
        require(baseline.context == first.context and baseline.tick <= first.tick,
                'pickup_baseline_context_changed')
        # Runtime.result verifies this acquisition's ownership and immutable snapshot.
        runtime.result('resources.pickup_baseline', [baseline, first], baseline_only=True)
    start_count = inventory.count(first if baseline is None else baseline, item_id)
    observations = [first]
    outcomes = []
    attempted = set()
    for _ in range(max_targets + 1):
        current = observations[-1]
        acquired = inventory.count(current, item_id) - start_count
        if acquired >= minimum:
            # Two later increasing-tick observations confirm the inventory delta.
            stable, previous_tick = 0, current.tick
            for _sample in range(8):
                runtime.sleeper(.05)
                sample = runtime.observe()
                observations.append(sample)
                if sample.tick > previous_tick and inventory.count(sample, item_id) - start_count >= minimum:
                    stable += 1
                else:
                    stable = 0
                previous_tick = sample.tick
                if stable >= 2:
                    break
            require(stable >= 2, 'pickup_inventory_delta_not_stable')
            result = runtime.result('resources.collect', observations, item_id=item_id,
                                  inventory_delta=acquired, requested_minimum=minimum,
                                  evidence_kind='client_observed_inventory_increase',
                                  causal_drop_attribution=False)
            return inventory._combine(*outcomes, result) if outcomes else result
        if len(attempted) >= max_targets:
            break
        # Inventory capacity is established against exact observed item components.
        drops = _drops(current, item_id)
        candidates = [d for d in drops if d['uuid'] not in attempted]
        require(candidates, 'matching_observed_drops_missing_or_budget_exhausted')
        target = min(candidates, key=lambda d: sum((d[k] - current.player[k]) ** 2 for k in ('x', 'y', 'z')))
        stack = target['item']
        capacity = sum((row.get('max_stack_size', 0) - row.get('count', 0))
                       for row in inventory.items(current) if inventory._same(row, stack, count=False))
        capacity += sum(stack.get('max_stack_size', 0) for row in inventory.items(current)
                        if row.get('empty') is True)
        require(capacity >= minimum - acquired, 'inventory_pickup_capacity_insufficient')
        attempted.add(target['uuid'])
        # Use the existing loaded safe-ground A*, never teleport to the item or
        # treat a disappearing entity as successful collection.
        goal = {k: math.floor(target[k]) for k in ('x', 'y', 'z')}
        movement = reach.navigate(runtime, goal, max_steps=max_steps)
        reached = runtime.require_success(movement)
        outcomes.append(movement)
        observations.append(reached)
        # Read-only bounded wait covers vanilla pickup delay even when already
        # centered on the drop. Never replay this movement or infer pickup from loss.
        last_tick = reached.tick
        for _sample in range(32):
            runtime.sleeper(.05)
            sample = runtime.observe(terrain=True)
            observations.append(sample)
            if sample.tick > last_tick and inventory.count(sample, item_id) - start_count >= minimum:
                break
            last_tick = max(last_tick, sample.tick)
    raise SkillError('pickup_inventory_delta_not_observed')


def mine_and_collect(runtime, target, item_id, *, minimum=1, hotbar_slot=None,
                     max_targets=8, max_steps=64):
    before = runtime.observe(terrain=True)
    mined = mine(runtime, target, hotbar_slot=hotbar_slot, require_drops=True)
    runtime.require_success(mined)
    result = _collect(runtime, item_id, minimum=minimum, max_targets=max_targets,
                      max_steps=max_steps, baseline=before)
    # Collection explicitly owns its independent inventory evidence. The vanished
    # block alone is never promoted to a drop/loot claim.
    return inventory._combine(mined, result)
