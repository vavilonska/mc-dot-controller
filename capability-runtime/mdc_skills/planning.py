"""Observation-driven local target/recipe/station selection for goal scheduling.

This planner only chooses among currently loaded, bounded, checked facts. It
never guesses unseen resources/stations, treats a plan as execution, or retries
a failed/unknown step on another target. Callers set concrete bounded goals.
"""
from collections import Counter
from dataclasses import replace
import math
from .core import require
from . import reach, inventory, resources, production, mobility


def _approach(observation, cell, runtime):
    """Choose the shortest observed dry flat route to a reachable top-face stand."""
    grid, stamp = reach._grid(observation)
    start = reach.Block(*(math.floor(observation.player[k]) for k in ('x', 'y', 'z')))
    eye = observation.player.get('eye_position', {})
    height = eye.get('y', math.nan) - observation.player['y']
    distance = observation.player.get('block_interaction_range')
    require(type(distance) in (int, float) and math.isfinite(distance) and 0 < distance <= 6,
            'ordinary_block_reach_required')
    require(math.isfinite(height) and 0 < height <= 2, 'observed_eye_height_required')
    target = (cell['x'] + .5, cell['y'] + 1, cell['z'] + .5)
    grid.require_fresh(stamp,runtime.clock())
    paths=mobility.loaded_paths(grid,start,max_steps=64)
    options = []
    for candidate, route in paths.items():
        if abs(candidate.x-cell['x'])>2 or abs(candidate.z-cell['z'])>2:
            continue
        if math.dist((candidate.x+.5,candidate.y+height,candidate.z+.5),target)>distance:
            continue
        options.append((len(route)-1,candidate.x,candidate.z,candidate))
    # Current pose can already reach the target even when its block center is not
    # an adjacent candidate. The native renderer pick still verifies true LOS.
    if all(type(eye.get(k)) in (float, int) and math.isfinite(eye[k]) for k in ('x', 'y', 'z')):
        if math.dist(tuple(eye[k] for k in ('x', 'y', 'z')), target) <= distance:
            options.append((0, start.x, start.z, start))
    if not options: return None
    chosen = min(options)[-1]
    return {'goal': {'x': chosen.x, 'y': chosen.y, 'z': chosen.z}, 'route_steps': min(options)[0]}


def discover_workstations(runtime, *, station_ids=None):
    ids = tuple(station_ids or production.STATIONS)
    require(ids and all(i in production.STATIONS for i in ids), 'supported_station_ids_required')
    before = runtime.observe(terrain=True)
    require(before.terrain.get('complete') is True, 'complete_station_search_required')
    candidates = []
    for cell in before.terrain['cells']:
        if cell.get('id') not in ids: continue
        exact = reach.block_at(before, {k: cell[k] for k in ('x', 'y', 'z')})
        approach = _approach(before, exact, runtime)
        if approach is not None:
            candidates.append({'position': {k: exact[k] for k in ('x', 'y', 'z')},
                'block_id': exact['id'], 'face': 'up', 'approach': approach})
    candidates.sort(key=lambda c: (c['approach']['route_steps'], c['block_id'], tuple(c['position'].values())))
    return runtime.result('planning.discover_workstations', (before,), stations=candidates,
                          search_scope='complete_loaded_local_terrain', unseen_stations_known=False)


def _station(runtime, allowed):
    result = discover_workstations(runtime, station_ids=allowed)
    candidates = result.evidence['stations']
    require(candidates, 'no_reachable_workstation_in_observed_area')
    selected = candidates[0]
    ids = list(result.request_ids)
    if selected['approach']['route_steps'] > 0:
        movement = mobility.navigate_loaded(runtime, selected['approach']['goal'], max_steps=64)
        runtime.require_success(movement)
        ids.extend(movement.request_ids)
    return {k: selected[k] for k in ('position', 'block_id', 'face')}, ids


def craft_nearby(runtime, recipe_name, *, batches=1, max_actions=1024):
    name = recipe_name.removeprefix('minecraft:') if isinstance(recipe_name, str) else None
    name = {'iron_bucket': 'bucket', 'sticks': 'stick', 'torches': 'torch'}.get(name, name)
    require(name in production.CRAFT_RECIPES, 'supported_recipe_required')
    recipe = production.CRAFT_RECIPES[name]
    needs_table = len(recipe.pattern) > 2 or max(map(len, recipe.pattern)) > 2 or name in production.BASE_RECIPES and name not in ('stick', 'torch', 'crafting_table')
    station, prior_ids = _station(runtime, ('minecraft:crafting_table',)) if needs_table else (None, [])
    result = production.craft(runtime, name, batches=batches, station=station, max_actions=max_actions)
    runtime.require_success(result)
    return replace(result, request_ids=tuple(dict.fromkeys(prior_ids + list(result.request_ids))))


def smelt_nearby(runtime, input_id, *, count=1, fuel_id=None, max_actions=1024, wait_seconds=360):
    require(input_id in production.SMELTING_RECIPES, 'supported_smelting_recipe_required')
    recipe = production.SMELTING_RECIPES[input_id]
    before = runtime.observe()
    counts = Counter({row['id']: 0 for row in inventory.items(before)})
    for row in inventory.items(before): counts[row['id']] += row['count']
    if fuel_id is None:
        suitable = [(math.ceil(count * recipe.furnace_ticks / duration), item) for item, duration in production.FUELS.items()
                    if counts[item] >= math.ceil(count * recipe.furnace_ticks / duration)]
        require(suitable, 'no_sufficient_observed_supported_fuel')
        fuel_id = min(suitable)[1]
    station, prior_ids = _station(runtime, recipe.stations)
    result = production.smelt(runtime, input_id, count=count, fuel_id=fuel_id, station=station,
                            max_actions=max_actions, wait_seconds=wait_seconds)
    return replace(result, request_ids=tuple(dict.fromkeys(prior_ids + list(result.request_ids))))


RESOURCE_BLOCKS = {
    'minecraft:coal': ('minecraft:coal_ore', 'minecraft:deepslate_coal_ore'),
    'minecraft:raw_iron': ('minecraft:iron_ore', 'minecraft:deepslate_iron_ore'),
    'minecraft:raw_copper': ('minecraft:copper_ore', 'minecraft:deepslate_copper_ore'),
    'minecraft:raw_gold': ('minecraft:gold_ore', 'minecraft:deepslate_gold_ore'),
    'minecraft:cobblestone': ('minecraft:stone', 'minecraft:cobblestone'),
    'minecraft:cobbled_deepslate': ('minecraft:deepslate', 'minecraft:cobbled_deepslate'),
    'minecraft:dirt': ('minecraft:dirt', 'minecraft:grass_block'),
    'minecraft:sand': ('minecraft:sand',),
}
for _wood in ('oak', 'spruce', 'birch', 'jungle', 'acacia', 'dark_oak', 'mangrove', 'cherry'):
    RESOURCE_BLOCKS['minecraft:' + _wood + '_log'] = ('minecraft:' + _wood + '_log',)


def acquire_nearby(runtime, item_id, *, count=1, max_blocks=8, excluded_positions=()):
    require(item_id in RESOURCE_BLOCKS, 'unsupported_local_resource_goal')
    require(isinstance(excluded_positions,(list,tuple)) and len(excluded_positions)<=32768,'bounded_excluded_positions_required')
    excluded={tuple(reach.coordinate(p)[k] for k in ('x','y','z')) for p in excluded_positions}
    require(type(count) is int and 1 <= count <= 2304 and type(max_blocks) is int and 1 <= max_blocks <= 32,
            'bounded_resource_goal_required')
    observations, ids = [], []
    for _ in range(max_blocks + 1):
        observed = runtime.observe(terrain=True)
        observations.append(observed)
        if inventory.count(observed, item_id) >= count:
            return runtime.result('planning.acquire_nearby', observations, item_id=item_id,
                                  requested_total=count, action_request_ids=ids)
        require(len(observations) <= max_blocks, 'local_resource_block_budget_exhausted')
        cells = [c for c in observed.terrain.get('cells', []) if c.get('id') in RESOURCE_BLOCKS[item_id]
                 and c.get('y', -10000) >= math.floor(observed.player['y'])
                 and not (c.get('x') == math.floor(observed.player['x']) and c.get('z') == math.floor(observed.player['z']))
                 and tuple(c.get(k) for k in ('x','y','z')) not in excluded]
        candidates = []
        for cell in cells:
            exact = reach.block_at(observed, {k: cell[k] for k in ('x', 'y', 'z')})
            approach = _approach(observed, exact, runtime)
            if approach is not None: candidates.append((approach['route_steps'], exact, approach))
        require(candidates, 'no_reachable_resource_in_observed_area')
        _, target, approach = min(candidates, key=lambda v: v[0])
        if approach['route_steps']:
            movement = mobility.navigate_loaded(runtime, approach['goal'], max_steps=64)
            runtime.require_success(movement)
            ids.extend(movement.request_ids)
        tools = inventory.items(runtime.observe())
        suffix = '_axe' if item_id.endswith('_log') else '_shovel' if item_id in ('minecraft:dirt', 'minecraft:sand') else '_pickaxe'
        choices = [row for row in tools if row['id'].endswith(suffix) and row.get('count', 0) > 0]
        if choices:
            # Prefer the highest known ordinary tier; native correct-tool/drop
            # checks remain authoritative (components such as Silk Touch matter).
            tiers = {'wooden': 0, 'golden': 0, 'stone': 1, 'iron': 2, 'diamond': 3, 'netherite': 4}
            tool = max(choices, key=lambda r: tiers.get(r['id'].split(':')[-1].split('_')[0], -1))
            selection = inventory.ensure_hotbar(runtime, tool['id'])
            runtime.require_success(selection)
            ids.extend(selection.request_ids)
        elif suffix == '_pickaxe':
            require(False, 'observed_pickaxe_required_for_resource')
        result = resources.mine_and_collect(runtime, {k: target[k] for k in ('x', 'y', 'z')}, item_id, minimum=1)
        runtime.require_success(result)
        ids.extend(result.request_ids)
