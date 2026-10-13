"""A bounded, observation-driven End expedition through ordinary guarded actions.

This is an executable goal, not a list of caller-chosen targets or a rehearsal
route. It never claims worldwide crystal absence, death from disappearance,
loot from an attack receipt, or safety from a teleport receipt. A durable step
boundary covers composite helpers; an interrupted step is never replayed.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
from itertools import product
import json
import math
import re
import time

from .core import Outcome, SkillError, atomic_write, require
from . import dimensions, inventory, production, reach, resources, threats

ID = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
FULL_BLOCKS = frozenset(('minecraft:cobblestone', 'minecraft:stone', 'minecraft:end_stone',
                         'minecraft:stone_bricks', 'minecraft:oak_planks', 'minecraft:purpur_block'))
SWORDS = tuple('minecraft:' + tier + '_sword' for tier in ('netherite', 'diamond', 'iron', 'stone'))
PICKS = tuple('minecraft:' + tier + '_pickaxe' for tier in ('netherite', 'diamond', 'iron', 'stone'))
PHASES = frozenset(('prepare', 'crystals', 'dragon', 'gateway', 'outer', 'craft', 'complete'))
CARDINAL = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _coord(value):
    return {k: math.floor(value[k]) for k in ('x', 'y', 'z')}


def _point(value):
    return tuple(value[k] for k in ('x', 'y', 'z'))


def _horizontal(a, b):
    return math.hypot(a['x'] - b['x'], a['z'] - b['z'])


def _key(value):
    return ','.join(str(value[k]) for k in ('x', 'y', 'z'))


def _cell(observation, position):
    try:
        return reach.block_at(observation, position)
    except SkillError:
        return None


def _dry(cell):
    return (cell is not None and cell.get('collision_known') is True
            and cell.get('fluid') == 'minecraft:empty' and cell.get('fluid_truncated') is False
            and cell.get('hazards') == [])


def _clear(observation, position):
    cell = _cell(observation, position)
    return (_dry(cell) and cell.get('id') in dimensions.AIR
            and cell.get('collision_empty') is True)


def _standable(observation, position):
    floor = _cell(observation, {**position, 'y': position['y'] - 1})
    return (_dry(floor) and floor.get('full_top_support') is True
            and floor.get('collision_empty') is False
            and floor.get('collision_bounds') == [0, 0, 0, 1, 1, 1]
            and _clear(observation, position)
            and _clear(observation, {**position, 'y': position['y'] + 1}))


def observed_routes(observation, *, max_nodes=2048):
    """Cardinal routes on fresh complete geometry, including single-block steps.

    This only selects currently observed destinations. The mobility helper must
    re-observe and native input must recheck the actual swept geometry.
    """
    require(observation.terrain is not None and observation.terrain.get('complete') is True,
            'complete_terrain_required')
    require(observation.terrain.get('world_generation') == observation.context[0]
            and observation.terrain.get('dimension') == observation.context[1], 'terrain_context_mismatch')
    indexed = {}
    for cell in observation.terrain.get('cells', []):
        key = tuple(cell.get(k) for k in ('x', 'y', 'z'))
        require(key not in indexed, 'duplicate_terrain_cell')
        if (cell.get('status') == 'loaded' and cell.get('known') is True
                and cell.get('id_truncated') is False and cell.get('properties_truncated') is False
                and isinstance(cell.get('properties'), dict)):
            indexed[key] = cell
    def at(position):
        return indexed.get(_point(position))
    def clear(position):
        cell = at(position)
        return _dry(cell) and cell.get('id') in dimensions.AIR and cell.get('collision_empty') is True
    def standable(position):
        floor = at({**position, 'y': position['y'] - 1})
        return (_dry(floor) and floor.get('full_top_support') is True
                and floor.get('collision_empty') is False
                and floor.get('collision_bounds') == [0, 0, 0, 1, 1, 1]
                and clear(position) and clear({**position, 'y': position['y'] + 1}))
    start = _coord(observation.player)
    require(standable(start), 'expedition_start_not_observed_dry_supported')
    origin = _key(start)
    routes, pending = {origin: [start]}, deque([start])
    while pending and len(routes) < max_nodes:
        source = pending.popleft()
        for dx, dz in CARDINAL:
            for dy in (0, 1, -1):
                target = dict(x=source['x'] + dx, y=source['y'] + dy, z=source['z'] + dz)
                key = _key(target)
                if key in routes or not standable(target):
                    continue
                if dy == 1 and not clear({**source, 'y': source['y'] + 2}):
                    continue
                if dy != 0 and not clear({**target, 'y': max(source['y'], target['y']) + 1}):
                    continue
                routes[key] = routes[_key(source)] + [target]
                pending.append(target)
                break
    return routes


def choose_frontier(observation, visited, *, toward=None):
    """Pick a reachable observed progress cell; never invent an unexplored route."""
    routes = observed_routes(observation)
    current = _coord(observation.player)
    options = []
    for key, route in routes.items():
        candidate = route[-1]
        if len(route) <= 1 or len(route) > 17:
            continue
        visits = visited.get(key, 0)
        if toward is not None:
            # New cells may detour around a solid tower, but loops get expensive.
            distance = _horizontal(candidate, toward)
            if distance > _horizontal(current, toward) + 3 or visits > 1:
                continue
            score = distance + .2 * abs(candidate['y'] - toward.get('y', candidate['y'])) + 4 * visits
        else:
            if visits:
                continue
            score = -_horizontal(current, candidate)
        options.append((score, len(route), key, candidate))
    require(options, 'no_fresh_reachable_exploration_frontier')
    return min(options)[-1]


def _safe_exposure(observation, minimum, *, pumpkin=True):
    require(dimensions._dimension(observation) == dimensions.END, 'expedition_requires_end')
    threats._health(observation, minimum)
    if pumpkin:
        require(inventory._inventory_item(observation, 39).get('id') == 'minecraft:carved_pumpkin',
                'enderman_gaze_protection_pumpkin_required')
    require(observation.player.get('effects_truncated') is False, 'complete_effect_observation_required')
    require(not any(e.get('id') in ('minecraft:levitation', 'minecraft:blindness', 'minecraft:darkness',
                                       'minecraft:poison', 'minecraft:wither')
                    for e in observation.player.get('effects', [])), 'unsafe_end_effect_requires_recovery')
    for entity in threats.entities(observation):
        if entity.get('alive') is not True:
            continue
        if entity.get('type') == 'minecraft:enderman':
            # Pumpkin prevents gaze provocation, but cannot make already angry
            # Endermen safe. Unknown anger is not silently treated as calm.
            require(type(entity.get('aggressive')) is bool, 'enderman_anger_observation_required')
            require(entity['aggressive'] is False, 'angry_enderman_requires_separate_defense')
        if entity.get('type') == 'minecraft:area_effect_cloud':
            require(math.dist(threats.position(observation.player), threats.position(entity)) >= 10,
                    'dragon_effect_cloud_near_station')


def _rest_station(sample):
    """Conservative read-only admission for eating/regeneration, never surrounded."""
    try:
        _safe_exposure(sample, 8)
        if not _standable(sample, _coord(sample.player)): return False
        for entity in threats.entities(sample):
            if entity.get('alive') is not True: continue
            kind = entity.get('type', '')
            distance = math.dist(threats.position(sample.player), threats.position(entity))
            if kind == 'minecraft:enderman': continue  # Already checked calm + pumpkin.
            if kind == 'minecraft:area_effect_cloud' and distance < 24: return False
            projectile = ('.projectile.' in entity.get('class', '') or kind in (
                'minecraft:shulker_bullet', 'minecraft:dragon_fireball', 'minecraft:fireball',
                'minecraft:small_fireball', 'minecraft:arrow', 'minecraft:spectral_arrow',
                'minecraft:wither_skull', 'minecraft:trident'))
            if projectile and distance < 48: return False
            if threats._number(entity.get('health')) and entity['health'] > 0:
                if distance < (48 if kind == 'minecraft:ender_dragon' else 32): return False
        return True
    except SkillError:
        return False


def _restore_health(runner, sample, target=18):
    """Eat actual food and wait for two later healthy samples at a safe station."""
    require(_rest_station(sample), 'safe_unthreatened_regeneration_station_required')
    data = runner.data
    recovery = data.setdefault('health_recovery', {'started_unix': time.time(),
        'origin': {k: sample.player[k] for k in ('x', 'y', 'z')},
        'last_health': sample.player['health'], 'target': target, 'samples': []})
    require(recovery['target'] == target, 'health_recovery_target_changed')
    stable, previous_tick = 0, sample.tick
    while True:
        require(time.time() - recovery['started_unix'] <= 90, 'health_regeneration_original_wait_budget_exhausted')
        require(_rest_station(sample), 'regeneration_station_became_unsafe')
        require(math.dist(threats.position(sample.player), _point(recovery['origin'])) <= .5,
                'regeneration_station_moved')
        require(sample.player['health'] >= recovery['last_health'], 'damage_during_health_regeneration')
        recovery['last_health'] = sample.player['health']
        require(type(sample.player.get('food')) is int, 'regeneration_hunger_observation_required')
        if sample.player['health'] >= target and sample.tick > previous_tick:
            stable += 1
        else:
            stable = 0
        if stable >= 2:
            data['last_health_recovery'] = {'target': target, 'observed_health': sample.player['health'],
                'sample_ids': recovery['samples'][-3:], 'server_confirmed': False}
            del data['health_recovery']
            runner.save()
            return sample
        previous_tick = sample.tick
        if sample.player['food'] < 18:
            foods = [s for s in inventory.items(sample) if s.get('id') in inventory.FOODS and s.get('count', 0) > 0]
            require(foods, 'observed_food_required_for_health_regeneration')
            food = min(foods, key=lambda s: s['slot'])['id']
            runner.step('safe_ground_food_consumption', lambda: inventory.consume(runner, food))
        else:
            runner.sleeper(.2)
        sample = runner.observe(terrain=True, radius=4, vertical=4, entity_radius=128)
        recovery['samples'].append(sample.request_id)
        runner.save()


def _loadout(observation, boxes, block_id):
    counts = {item: inventory.count(observation, item) for item in
              (block_id, 'minecraft:bow', 'minecraft:arrow', 'minecraft:spectral_arrow',
               'minecraft:tipped_arrow', 'minecraft:ender_pearl', 'minecraft:crafting_table',
               'minecraft:carved_pumpkin', 'minecraft:chest') + SWORDS + PICKS}
    missing = []
    if not counts['minecraft:bow']: missing.append('bow')
    if sum(counts[k] for k in ('minecraft:arrow', 'minecraft:spectral_arrow', 'minecraft:tipped_arrow')) < 32:
        missing.append('at_least_32_arrows')
    if not counts['minecraft:ender_pearl']: missing.append('ender_pearl')
    if not counts['minecraft:crafting_table']: missing.append('portable_crafting_table')
    if counts[block_id] < 32: missing.append('at_least_32_building_blocks_more_needed_for_towers_and_bridges')
    pumpkin = inventory._inventory_item(observation, 39).get('id') == 'minecraft:carved_pumpkin'
    if not pumpkin and not counts['minecraft:carved_pumpkin']: missing.append('carved_pumpkin')
    sword = next((item for item in SWORDS if counts[item]), None)
    pickaxe = next((item for item in PICKS if counts[item]), None)
    if sword is None: missing.append('stone_or_better_sword')
    if pickaxe is None: missing.append('stone_or_better_pickaxe')
    accepted_planks = set(production.CRAFT_RECIPES['chest'].ingredients['P'])
    planks = sum(s['count'] for s in inventory.items(observation) if s.get('id') in accepted_planks)
    if counts['minecraft:chest'] + planks // 8 < boxes: missing.append('chests_or_eight_planks_each')
    if sum(s.get('empty') is True for s in inventory.items(observation)) < 2:
        missing.append('two_free_inventory_slots_for_pickup_and_production')
    return missing, sword, pickaxe


def _path(runtime, job_id):
    require(isinstance(job_id, str) and ID.fullmatch(job_id), 'invalid_expedition_job_id')
    return runtime.journal_directory / ('end-expedition-' + job_id + '.json')


def _read(path):
    require(path.exists() and not path.is_symlink() and path.stat().st_size <= 4 * 1024 * 1024,
            'invalid_expedition_checkpoint_path')
    data = json.loads(path.read_text())
    require(data.get('schema_version') == 1 and data.get('phase') in PHASES
            and isinstance(data.get('settings'), dict) and isinstance(data.get('request_ids'), list)
            and isinstance(data.get('actions_reserved'), int), 'invalid_expedition_checkpoint')
    return data


def expedition_status(runtime, job_id):
    """Read durable progress only; history is not fresh authorization or victory."""
    data = _read(_path(runtime, job_id))
    return {**deepcopy(data), 'historical_only': True, 'server_confirmed': False}


class _Runner:
    """Expose Runtime while reserving every mutation inside an atomic goal step."""
    def __init__(self, runtime, path, data):
        self.runtime, self.path, self.data = runtime, path, data
        self.last = None

    def __getattr__(self, key):
        return getattr(self.runtime, key)

    def save(self):
        atomic_write(self.path, self.data)

    def check(self):
        now = time.time()
        require(now >= self.data['last_wall_clock'], 'expedition_clock_regressed')
        self.data['last_wall_clock'] = now
        require(now < self.data['deadline_unix'], 'expedition_original_deadline_exhausted')
        require(not self.runtime.has_unresolved_execution, 'expedition_unresolved_execution_no_replay')

    def observe(self, **kwargs):
        self.check()
        sample = self.runtime.observe(**kwargs)
        require(list(sample.context) == self.data['context'], 'expedition_context_changed')
        self.last = sample
        return sample

    def snapshot(self):
        sample = self.observe(terrain=True, radius=4, vertical=4, entity_radius=128)
        if self.data['phase'] != 'prepare' and sample.player.get('health', 0) < 18 and _rest_station(sample):
            # Keep the original return reserve before spending time resting high above ground.
            raised = [self.data.get(k) for k in ('dragon_tower', 'shulker_tower')]
            if self.data.get('crystal_work'): raised.append(self.data['crystal_work'])
            if self.data.get('gateway') and self.data['gateway'].get('stage') in ('ascend', 'pearl'):
                raised.append(self.data['gateway'])
            outer = self.effective_remaining_budget() if callable(getattr(self, 'effective_remaining_budget', None)) else None
            deadline = min(self.data['deadline_unix'], outer['deadline_unix'] if outer else self.data['deadline_unix'])
            remaining_actions = min(self.data['settings']['max_actions'] - self.data['actions_reserved'],
                                    outer['remaining_actions'] if outer else self.data['settings']['max_actions'])
            can_wait = all(not _return_reserve_low(self, t)
                and deadline - time.time() > t['reserve']['return_seconds'] + 95
                and remaining_actions > t['reserve']['return_actions'] + 64
                for t in raised if t and t.get('reserve'))
            if can_wait: sample = _restore_health(self, sample)
        _safe_exposure(sample, self.data['settings']['min_health'], pumpkin=self.data['phase'] != 'prepare')
        self.data['last_observed_tick'] = sample.tick
        here = _coord(sample.player)
        visits = self.data['visited'].get(_key(here), 0)
        self.data['visited'][_key(here)] = visits + 1
        require(len(self.data['visited']) <= 8192, 'expedition_visit_budget_exhausted')
        self.save()
        return sample

    def execute(self, skill, command, verify, **kwargs):
        self.check()
        data, settings = self.data, self.data['settings']
        require(data['inflight'] is not None, 'expedition_mutation_requires_durable_step')
        require(data['actions_reserved'] < settings['max_actions'], 'expedition_action_budget_exhausted')
        require(time.time() + command.get('timeout_ms', 15000) / 1000 < data['deadline_unix'],
                'expedition_action_exceeds_original_deadline')
        cost = 0.
        if command.get('action') == 'follow_path':
            previous = threats.position(kwargs['before'].player)
            for point in command.get('waypoints', []):
                nxt = threats.position(point)
                cost += math.dist(previous, nxt)
                previous = nxt
        elif ((command.get('action') == 'place_block' and command.get('jump'))
              or command.get('capability_descent') is True):
            cost = 1.
        require(data['walk_reserved'] + cost <= settings['max_walk_distance'],
                'expedition_walk_budget_exhausted')
        data['actions_reserved'] += 1
        data['walk_reserved'] += cost
        copied = deepcopy(command)
        if data['phase'] != 'prepare' and copied.get('action') not in ('click_slot', 'close_menu', 'select_hotbar'):
            copied['require_pumpkin'] = True
        data['inflight']['last_command_sha256'] = hashlib.sha256(
            json.dumps(copied, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        data['inflight']['reserved_actions'] += 1
        self.save()  # Before even entering the transport.
        result = self.runtime.execute(skill, copied, verify, **kwargs)
        data['request_ids'] = list(dict.fromkeys(data['request_ids'] + list(result.request_ids)))
        data['inflight'].update(last_status=result.status, last_reason=result.reason,
                                last_request_ids=list(result.request_ids))
        self.save()
        return result

    def step(self, label, function, update=None, *, known_no_effect=None):
        require(self.data['inflight'] is None, 'interrupted_expedition_step_no_replay')
        self.data['inflight'] = {'label': label, 'status': 'running', 'reserved_actions': 0,
                                 'phase': self.data['phase'], 'started_unix': time.time()}
        self.save()
        result = function()
        require(isinstance(result, Outcome), 'expedition_step_outcome_required')
        self.data['request_ids'] = list(dict.fromkeys(self.data['request_ids'] + list(result.request_ids)))
        self.data['inflight'].update(status=result.status, reason=result.reason,
                                     request_ids=list(result.request_ids))
        self.save()
        native = result.evidence.get('native', {})
        details = native.get('result', {})
        if (not result.ok and known_no_effect is not None and result.status == 'failed'
                and native.get('action') == 'gateway_pearl' and native.get('status') == 'failed'
                and details.get('dispatched') is False and details.get('input_release_confirmed') is True
                and not self.runtime.has_unresolved_execution):
            known_no_effect(result)
            self.data['inflight'] = None
            self.save()
            self.last = result.last_observation
            return self.last  # Caller can only return to its reserved base; never rethrow.
        self.require_success(result)
        if update is not None:
            update(result)
        self.data['inflight'] = None
        self.data['completed_steps'] += 1
        self.save()
        self.last = result.last_observation
        return result.last_observation

    def select(self, item, slot):
        return self.step('select_' + item, lambda: inventory.ensure_hotbar(self, item, hotbar_slot=slot))

    def move(self, goal, *, label='observed_approach'):
        from . import mobility
        return self.step(label, lambda: mobility.navigate_loaded(self, goal, max_segments=16,
                        min_health=self.data['settings']['min_health']))

    def frontier(self, sample, toward=None):
        require(self.data['search_steps'] < self.data['settings']['max_search_steps'],
                'expedition_search_budget_exhausted')
        goal = choose_frontier(sample, self.data['visited'], toward=toward)
        self.data['search_steps'] += 1
        self.save()
        return self.move(goal, label='fresh_frontier_approach' if toward else 'fresh_frontier_search')

    def up(self):
        from . import mobility
        settings = self.data['settings']
        return self.step('one_observed_pillar_ascent', lambda: mobility.pillar_up(self,
            block_id=settings['block_id'], hotbar_slot=3, min_health=settings['min_health']))

    def down(self):
        from . import mobility
        self.select(self.data['pickaxe'], 2)
        settings = self.data['settings']
        return self.step('one_owned_pillar_descent', lambda: mobility.pillar_down(self,
            expected_block_id=settings['block_id'], hotbar_slot=self.last.player['selected_slot'],
            min_health=settings['min_health']))

    def bridge(self, direction, update=None):
        from . import mobility
        settings = self.data['settings']
        return self.step('one_observed_bridge_step', lambda: mobility.bridge_step(self,
            direction=direction, block_id=settings['block_id'], hotbar_slot=3,
            min_health=settings['min_health']), update)


def _remember_targets(runner, sample):
    data = runner.data
    for entity in threats.entities(sample):
        kind = entity.get('type')
        if kind == 'minecraft:end_crystal' and entity.get('alive') is True:
            ident = threats._identity(entity)
            previous = data['crystals'].get(entity['uuid'])
            require(previous is None or previous['entity_id'] == ident[0], 'crystal_identity_replaced')
            if previous is None:
                require(len(data['crystals']) < data['settings']['max_crystals'], 'observed_crystal_budget_exhausted')
                data['crystals'][entity['uuid']] = {'uuid': entity['uuid'], 'entity_id': ident[0],
                    'position': {k: entity[k] for k in ('x', 'y', 'z')}, 'removed': False}
        elif kind == 'minecraft:ender_dragon':
            threats._identity(entity)
            if data['dragon'] is None:
                require(entity.get('alive') is True and entity.get('health', 0) > 0,
                        'local_living_dragon_required_before_gateway')
                data['dragon'] = {'uuid': entity['uuid'], 'entity_id': entity['entity_id'],
                                  'initial_health': entity['health'], 'dead_observed': False}
            else:
                require(entity['uuid'] == data['dragon']['uuid'] and entity['entity_id'] == data['dragon']['entity_id'],
                        'expedition_dragon_identity_changed')
    runner.save()


def _base_candidates(sample, target, distance=3):
    routes = observed_routes(sample)
    result = []
    for dx, dz in CARDINAL:
        x, z = math.floor(target['x']) + dx * distance, math.floor(target['z']) + dz * distance
        for route in routes.values():
            candidate = route[-1]
            if candidate['x'] == x and candidate['z'] == z:
                result.append((len(route), abs(candidate['y'] - sample.player['y']),
                               _key(candidate), candidate, {'x': dx, 'z': dz}))
    return sorted(result)



# These are local access limits, not permission to enlarge expedition budgets.
CRYSTAL_ACCESS_RADIUS = 8
CRYSTAL_MAX_BRIDGE = 12
CRYSTAL_MAX_BARS = 3
# reach._arrived accepts a .23-block horizontal *radial* error, not .23 on
# each axis. Add .02 numerical slack so every admitted arrival remains >=14.
CRYSTAL_FIRING_CENTER_CLEARANCE = 14.25


def _crystal_cells(sample):
    """Index only complete, context-bound geometry; unknown cells stay absent."""
    terrain = sample.terrain
    require(isinstance(terrain, dict) and terrain.get('complete') is True,
            'complete_terrain_required')
    world = sample.state.get('world', {})
    require(terrain.get('world_generation') == sample.context[0] == world.get('world_generation')
            and terrain.get('dimension') == sample.context[1] == world.get('dimension'),
            'terrain_context_mismatch')
    cells, seen = {}, set()
    for cell in terrain.get('cells', []):
        key = tuple(cell.get(k) for k in ('x', 'y', 'z'))
        require(key not in seen, 'duplicate_terrain_cell')
        seen.add(key)
        if (cell.get('status') == 'loaded' and cell.get('known') is True
                and cell.get('id_truncated') is False and cell.get('properties_truncated') is False
                and isinstance(cell.get('properties'), dict)):
            cells[key] = cell
    return cells


def _crystal_air(cells, point):
    cell = cells.get(tuple(point))
    return _dry(cell) and cell.get('id') in dimensions.AIR and cell.get('collision_empty') is True


def _crystal_access_candidates(sample, target):
    """Enumerate actual reachable exterior columns, not four presumed radii.

    The current slice proves access and initial ascent only. Each later slice is
    independently admitted before the next step; no missing upper cells are air.
    """
    cells, routes = _crystal_cells(sample), observed_routes(sample)
    center, height = _coord(target), math.floor(target['y'])
    choices = []
    for route in routes.values():
        base = route[-1]
        dx, dz = base['x'] - center['x'], base['z'] - center['z']
        if not (2 <= max(abs(dx), abs(dz)) and math.hypot(dx, dz) <= CRYSTAL_ACCESS_RADIUS
                and min(abs(dx), abs(dz)) <= 2 and len(route) <= 17
                and 0 <= height - base['y'] <= 64):
            continue
        if not all(_crystal_air(cells, (base['x'], base['y'] + dy, base['z'])) for dy in range(4)):
            continue
        # Reject any obstruction already visible above this column, even when
        # the intervening higher slices have not been observed yet.
        if any(not _crystal_air(cells, key) for key in cells
               if key[0] == base['x'] and key[2] == base['z'] and base['y'] <= key[1] <= height + 3):
            continue
        direction = {'x': (1 if dx > 0 else -1) if abs(dx) >= abs(dz) else 0,
                     'z': (1 if dz > 0 else -1) if abs(dz) > abs(dx) else 0}
        firing, length = dict(base, y=height), 0
        while _horizontal({'x': firing['x'] + .5, 'z': firing['z'] + .5}, target) < CRYSTAL_FIRING_CENTER_CLEARANCE:
            firing['x'] += direction['x']; firing['z'] += direction['z']; length += 1
        if length > CRYSTAL_MAX_BRIDGE:
            continue
        plan = {'base': dict(base), 'direction': direction, 'height': height,
                'firing': firing, 'bridge_length': length, 'approach_route': route,
                'target': {'uuid': target['uuid'], 'entity_id': target['entity_id'],
                           'position': {k: target[k] for k in ('x', 'y', 'z')}},
                'source': {'request_id': sample.request_id, 'tick': sample.tick,
                           'context': list(sample.context)},
                'scope': 'observed_base_and_initial_ascent_only'}
        choices.append((math.hypot(dx, dz), len(route), _key(base), plan))
    return [entry[-1] for entry in sorted(choices)]


def _crystal_ray_cells(start, end):
    """Exact voxel-boundary supercover, including ambiguous edge neighbors."""
    crossings = {0., 1.}
    for axis in range(3):
        delta = end[axis] - start[axis]
        if abs(delta) <= 1e-12:
            continue
        for boundary in range(math.floor(min(start[axis], end[axis])),
                              math.ceil(max(start[axis], end[axis])) + 1):
            t = (boundary - start[axis]) / delta
            if 0 < t < 1:
                crossings.add(t)
    ordered = sorted(crossings)
    cells = set()
    for t in [(a+b)/2 for a, b in zip(ordered, ordered[1:])] + ordered[1:-1]:
        indices = []
        for axis in range(3):
            value = start[axis] + (end[axis] - start[axis]) * t
            low = math.floor(value)
            indices.append((low-1, low) if abs(value-low) <= 1e-9 else (low,))
        cells.update(product(*indices))
    return cells


def _crystal_cage_plan(sample, target, work):
    """Observed final cage aperture plus an actually reachable next bar.

    Match native lower-angle bow planning over the target-side four blocks.
    This does not certify the distant corridor: native repeats its full loaded
    trajectory/collateral guards immediately before drawing and release.
    """
    cells = _crystal_cells(sample)
    bounds = target.get('bounding_box', {})
    low, high = threats.position(bounds.get('min')), threats.position(bounds.get('max'))
    require(all(low[i] < high[i] for i in range(3)), 'crystal_bounds_required')
    point = tuple((low[i] + high[i]) / 2 for i in range(3))
    eye = threats.position(sample.player.get('eye_position'))
    eye_height = eye[1] - sample.player['y']
    require(1 <= eye_height <= 2, 'crystal_standing_eye_required')
    firing = work['firing']
    start = (firing['x'] + .5, firing['y'] + eye_height, firing['z'] + .5)
    delta = tuple(point[i] - start[i] for i in range(3))
    flat = math.hypot(delta[0], delta[2])
    require(0 < flat <= 32 and math.dist(start, point) <= 32, 'crystal_planned_shot_range')
    disc = 81 - .05 * (.05 * flat * flat + 18 * delta[1])
    require(disc >= 0, 'crystal_planned_trajectory_unavailable')
    elevation = math.atan((9 - math.sqrt(disc)) / (.05 * flat))
    duration = flat / (3 * math.cos(elevation))
    previous, touched = start, set()
    for index in range(1, 25):
        tick = duration * index / 24
        run = 3 * math.cos(elevation) * tick
        current = (start[0] + delta[0] / flat * run,
                   start[1] + 3 * math.sin(elevation) * tick - .025 * tick * tick,
                   start[2] + delta[2] / flat * run)
        for key in _crystal_ray_cells(previous, current):
            if math.hypot(key[0] + .5 - target['x'], key[2] + .5 - target['z']) <= 4:
                touched.add(key)
        previous = current
    bars = []
    for key in sorted(touched):
        cell = cells.get(key)
        require(_dry(cell), 'crystal_cage_lane_unknown_or_hazardous')
        if _crystal_air(cells, key):
            continue
        require(cell.get('id') == 'minecraft:iron_bars'
                and math.dist(threats.position(target), tuple(v + .5 for v in key)) <= 4,
                'crystal_cage_lane_unsupported_obstruction')
        bars.append(dict(zip(('x', 'y', 'z'), key)))
    # An offset exterior column can see a neighboring cage bar before the
    # aperture bar. Include only those actual iron-bar ray occluders, in the
    # same original three-block budget; never excavate unrelated terrain.
    pending = list(bars)
    planned = {_point(bar) for bar in bars}
    while pending:
        bar = pending.pop()
        aim = tuple(bar[k] + .5 for k in ('x', 'y', 'z'))
        for key in sorted(_crystal_ray_cells(eye, aim)):
            cell = cells.get(key)
            if (key not in planned and _dry(cell) and cell.get('id') == 'minecraft:iron_bars'
                    and math.dist(threats.position(target), tuple(v + .5 for v in key)) <= 4):
                added = dict(zip(('x', 'y', 'z'), key))
                bars.append(added); pending.append(added); planned.add(key)
                require(len(bars) + len(work['bars_mined']) <= CRYSTAL_MAX_BARS,
                        'crystal_cage_bar_budget_exhausted')
    require(len(bars) + len(work['bars_mined']) <= CRYSTAL_MAX_BARS, 'crystal_cage_bar_budget_exhausted')
    if not bars:
        return {'bars': [], 'next_bar': None, 'request_id': sample.request_id, 'tick': sample.tick}
    interaction_range = sample.player.get('block_interaction_range')
    require(threats._number(interaction_range) and 0 < interaction_range <= 64,
            'crystal_cage_reach_observation_required')
    reachable = []
    feet = _coord(sample.player)
    for bar in bars:
        key, aim = _point(bar), tuple(bar[k] + .5 for k in ('x', 'y', 'z'))
        # resources.mine uses radius four and needs every neighboring cell.
        neighbors = [tuple(key[i] + d[i] for i in range(3)) for d in reach.FACES.values()]
        above = cells.get((key[0], key[1] + 1, key[2]), {})
        # Match resources.mine's read-only falling/fluid-above admission here,
        # where refusal can still choose the reserved return before any action.
        falling_above = (above.get('id') in {'minecraft:sand', 'minecraft:red_sand', 'minecraft:gravel',
                            'minecraft:anvil', 'minecraft:chipped_anvil', 'minecraft:damaged_anvil'}
                         or above.get('id', '').endswith('_concrete_powder'))
        if (falling_above or above.get('fluid') != 'minecraft:empty'
                or math.dist(eye, aim) > min(interaction_range, 4.5) - .05
                or any(abs(bar[k] - feet[k]) > 3 for k in ('x', 'y', 'z'))
                or not all(_dry(cells.get(n)) for n in neighbors)
                or not all(p == key or _crystal_air(cells, p) for p in _crystal_ray_cells(eye, aim))):
            continue
        reachable.append((math.dist(eye, aim), _key(bar), bar))
    require(reachable, 'crystal_cage_no_observed_reachable_bar')
    return {'bars': bars, 'next_bar': min(reachable)[-1],
            'request_id': sample.request_id, 'tick': sample.tick}


def _reserve_crystal_access(runner, sample, plan):
    reserve = _reserve_tower(runner, sample, plan['base'], plan['height'], plan['bridge_length'])
    # Reserve local approach as well as the return traversal; preserve original
    # tower overhead, and never lower either the outer or inner budget gate.
    approach = len(plan['approach_route']) - 1
    extra_actions = approach + CRYSTAL_MAX_BARS
    extra_seconds = 3 * approach + 20 * CRYSTAL_MAX_BARS
    height, bridge = reserve['height'], reserve['bridge_length']
    total_actions = 6 * height + 5 * bridge + 24 + extra_actions
    total_seconds = 25 * height + 15 * bridge + 120 + extra_seconds
    total_walk = 2 * height + 2 * bridge + 8 + 2 * approach
    data = runner.data
    outer = runner.effective_remaining_budget() if callable(getattr(runner, 'effective_remaining_budget', None)) else None
    require(data['settings']['max_actions'] - data['actions_reserved'] >= total_actions,
            'crystal_access_and_return_action_reserve_required')
    require(data['deadline_unix'] - time.time() >= total_seconds,
            'crystal_access_and_return_deadline_reserve_required')
    require(data['settings']['max_walk_distance'] - data['walk_reserved'] >= total_walk,
            'crystal_access_and_return_walk_reserve_required')
    if outer:
        require(outer['remaining_actions'] >= total_actions, 'crystal_outer_scheduler_action_reserve_required')
        require(outer['deadline_unix'] - time.time() >= total_seconds, 'crystal_outer_scheduler_deadline_reserve_required')
    return {**reserve, 'return_actions': reserve['return_actions'] + bridge,
            'return_seconds': reserve['return_seconds'] + 10 * bridge,
            'approach_steps': approach, 'cage_blocks': CRYSTAL_MAX_BARS}


def _reserve_tower(runner, sample, base, top, bridge_length=0):
    """Reserve ascent AND an ordinary return before leaving observed ground."""
    height = max(0, top - base['y'])
    blocks = height + bridge_length + 2
    settings, data = runner.data['settings'], runner.data
    require(inventory.count(sample, settings['block_id']) >= blocks,
            'tower_full_ascent_bridge_material_reserve_required')
    tools = [s for s in inventory.items(sample) if s.get('id') == data['pickaxe']]
    selected_tool = next((t for t in tools if 0 <= t.get('slot', -1) <= 8), tools[0] if tools else {})
    require(type(selected_tool.get('max_damage')) is int and type(selected_tool.get('damage')) is int
            and selected_tool['max_damage'] - selected_tool['damage'] > height + 4,
            'tower_descent_pickaxe_durability_reserve_required')
    actions = 6 * height + 5 * bridge_length + 24
    seconds = 25 * height + 15 * bridge_length + 120
    walk = 2 * height + 2 * bridge_length + 8
    outer = runner.effective_remaining_budget() if callable(getattr(runner, 'effective_remaining_budget', None)) else None
    if outer is not None:
        require(type(outer.get('remaining_actions')) is int and outer['remaining_actions'] >= actions,
                'tower_outer_scheduler_action_reserve_required')
        require(type(outer.get('deadline_unix')) in (int, float) and outer['deadline_unix'] - time.time() >= seconds,
                'tower_outer_scheduler_deadline_reserve_required')
    require(settings['max_actions'] - data['actions_reserved'] >= actions,
            'tower_ascent_and_return_action_reserve_required')
    require(data['deadline_unix'] - time.time() >= seconds,
            'tower_ascent_and_return_deadline_reserve_required')
    require(settings['max_walk_distance'] - data['walk_reserved'] >= walk,
            'tower_ascent_and_return_walk_reserve_required')
    return {'height': height, 'bridge_length': bridge_length, 'blocks': blocks,
            'return_actions': 3 * height + 8, 'return_seconds': 20 * height + 60,
            'return_walk': height + bridge_length + 4}


def deflect_shulker_bullet(runtime, bullet_uuid, *, min_health=12):
    """Strike one actually observed bullet; prove later local removal without damage.

    This is projectile interception, never a living-entity kill claim. A missing
    bullet before admission is not accepted as an attack result.
    """
    before = runtime.observe(entity_radius=16)
    threats._health(before, min_health)
    bullet = threats.entity(before, bullet_uuid)
    require(bullet.get('type') == 'minecraft:shulker_bullet' and bullet.get('alive') is True,
            'live_exact_shulker_bullet_required')
    eye = threats.position(before.player.get('eye_position', {}))
    require(math.dist(eye, threats.position(bullet)) <= 2.8, 'shulker_bullet_not_in_interception_reach')
    origin = threats.position(before.player)
    target_cell = _coord(bullet)
    dimensions._chunk_loaded(before, target_cell)
    command = threats._command(before, 'attack_entity', bullet, 1000)
    command.update(min_health=min_health, require_pumpkin=True)
    def verified(_, after):
        dimensions._chunk_loaded(after, target_cell)
        return (threats._same_target(bullet, after) is None
                and math.dist(origin, threats.position(after.player)) <= .5
                and after.player.get('health') >= before.player['health'])
    result = runtime.execute('expedition.deflect_shulker_bullet', command, verified,
                             before=before, max_samples=12, stable_samples=2)
    if not result.ok: return result
    return Outcome(result.status, result.reason, result.request_ids, {**result.evidence,
        'bullet_uuid': bullet_uuid, 'local_projectile_removal_observed': True,
        'living_entity_kill_claimed': False, 'removal_attributed_to_action': False}, result.last_observation)


def _return_reserve_low(runner, tower):
    reserve, data = tower['reserve'], runner.data
    actions = data['settings']['max_actions'] - data['actions_reserved']
    seconds = data['deadline_unix'] - time.time()
    outer = runner.effective_remaining_budget() if callable(getattr(runner, 'effective_remaining_budget', None)) else None
    if outer is not None:
        actions = min(actions, outer['remaining_actions'])
        seconds = min(seconds, outer['deadline_unix'] - time.time())
    return (actions <= reserve['return_actions'] or seconds <= reserve['return_seconds']
            or data['settings']['max_walk_distance'] - data['walk_reserved'] <= reserve['return_walk'])


def _abort_owned_tower_if_low(runner, sample, key):
    tower = runner.data.get(key)
    if tower is None: return False
    if _return_reserve_low(runner, tower):
        tower['abort_reason'] = key + '_stopped_with_return_reserve'
    if not tower.get('abort_reason'): return False
    _return_owned_tower(runner, sample, key)
    require(runner.data.get(key) is not None, tower['abort_reason'])
    return True


def _return_owned_tower(runner, sample, key):
    tower = runner.data.get(key)
    if tower is None: return False
    base = tower['base']
    require(_coord(sample.player)['x'] == base['x'] and _coord(sample.player)['z'] == base['z'],
            'owned_tower_column_changed_no_guessed_descent')
    if sample.player['y'] > base['y'] + .15:
        runner.down()
    else:
        require(abs(sample.player['y'] - base['y']) <= .15, 'owned_tower_base_height_changed')
        runner.data[key] = None
        runner.save()
    return True


def _crystal_step(runner, sample):
    data, settings = runner.data, runner.data['settings']
    work = data['crystal_work']
    if work is None:
        visible = [entity for entity in threats.entities(sample) if entity.get('type') == 'minecraft:end_crystal'
                   and entity.get('alive') is True and not data['crystals'][entity['uuid']]['removed']]
        if not visible:
            # This is deliberately NOT an all-crystals-clear condition. Actual
            # dragon damage/death is still necessary, and discovery keeps running.
            data['phase'] = 'dragon'
            runner.save()
            return
        target = min(visible, key=lambda e: (_horizontal(sample.player, e), e['uuid']))
        work = {'uuid': target['uuid'], 'entity_id': target['entity_id'], 'stage': 'approach',
                'base': None, 'direction': None, 'bridge_cells': [], 'bars_mined': []}
        data['crystal_work'] = work
        runner.save()
    target = threats.entity(sample, work['uuid'], required=False)
    if work['stage'] not in ('return', 'descend'):
        require(target is not None and target.get('alive') is True, 'selected_crystal_no_longer_observed_no_inferred_removal')
        require(target['entity_id'] == work['entity_id'], 'selected_crystal_identity_changed')
        if work.get('access_plan'):
            require(_point(target) == _point(work['access_plan']['target']['position']),
                    'selected_crystal_position_changed')
    if work['stage'] in ('reach_base', 'ascend', 'cage', 'bridge', 'shoot'):
        require('firing' in work and 'access_plan' in work,
                'crystal_access_plan_required_no_legacy_replay')
    if work['stage'] == 'approach':
        candidates = _crystal_access_candidates(sample, target)
        if not candidates:
            require(_horizontal(sample.player, target) > CRYSTAL_ACCESS_RADIUS,
                    'crystal_no_observed_safe_access_base')
            runner.frontier(sample, target)
            return
        arrows = sum(inventory.count(sample, item) for item in ('minecraft:arrow', 'minecraft:spectral_arrow', 'minecraft:tipped_arrow'))
        bows = [s for s in inventory.items(sample) if s.get('id') == 'minecraft:bow']
        require(arrows > 0 and any(type(s.get('max_damage')) is int and type(s.get('damage')) is int
                and s['max_damage'] - s['damage'] > 0 for s in bows), 'crystal_tower_bow_and_arrow_reserve_required')
        failures = []
        for plan in candidates:
            try:
                reserve = _reserve_crystal_access(runner, sample, plan)
                break
            except SkillError as exc:
                failures.append(exc)
        else:
            raise failures[0]
        work.update(base=plan['base'], direction=plan['direction'], height=plan['height'],
                    firing=plan['firing'], access_plan=plan, stage='reach_base', reserve=reserve)
        runner.save()
    if work['stage'] == 'reach_base':
        runner.move(work['base'], label='reach_observed_crystal_tower_base')
        work['stage'] = 'ascend'
        runner.save()
        return
    reserve = work.get('reserve', {})
    if work['stage'] in ('ascend', 'cage', 'bridge', 'shoot') and reserve:
        actions_left = settings['max_actions'] - data['actions_reserved']
        seconds_left = data['deadline_unix'] - time.time()
        outer = runner.effective_remaining_budget() if callable(getattr(runner, 'effective_remaining_budget', None)) else None
        if outer is not None:
            actions_left = min(actions_left, outer['remaining_actions'])
            seconds_left = min(seconds_left, outer['deadline_unix'] - time.time())
        walk_left = settings['max_walk_distance'] - data['walk_reserved']
        if (actions_left <= reserve['return_actions'] or seconds_left <= reserve['return_seconds']
                or walk_left <= reserve['return_walk']):
            work['abort_reason'] = 'crystal_work_stopped_with_return_reserve'
            if work['stage'] == 'ascend':
                work['height'], work['stage'] = math.floor(sample.player['y']), 'descend'
            else:
                work['stage'] = 'return'
            runner.save()
    if work['stage'] == 'ascend':
        require(_coord(sample.player)['x'] == work['base']['x'] and _coord(sample.player)['z'] == work['base']['z'],
                'crystal_tower_column_changed')
        require(work['height'] - work['base']['y'] <= 64, 'crystal_tower_height_budget_64')
        if sample.player['y'] < work['height'] - .15:
            feet = _coord(sample.player)
            if not (_standable(sample, feet) and all(_clear(sample, dict(feet, y=feet['y'] + dy))
                                                     for dy in (1, 2, 3))):
                work.update(height=feet['y'], stage='descend',
                            abort_reason='crystal_ascent_observed_obstruction_or_unknown')
                runner.save()
                return
            runner.up()
            return
        require(abs(sample.player['y'] - work['height']) <= .15, 'crystal_top_height_changed')
        work['stage'] = 'cage'
        runner.save()
    if work['stage'] == 'cage':
        require('firing' in work, 'crystal_access_plan_required_no_legacy_replay')
        # Wider read-only access inspection; mutation helpers still acquire their
        # own radius-four samples, including current native reach and ray checks.
        fresh = runner.observe(terrain=True, radius=8, vertical=4, entity_radius=128)
        _safe_exposure(fresh, settings['min_health'])
        live_target = threats.entity(fresh, work['uuid'])
        require(live_target.get('alive') is True and live_target['entity_id'] == work['entity_id'],
                'selected_crystal_identity_changed')
        require(_point(live_target) == _point(work['access_plan']['target']['position']),
                'selected_crystal_position_changed')
        require(_coord(fresh.player) == dict(work['base'], y=work['height'])
                and _standable(fresh, _coord(fresh.player)), 'crystal_cage_station_changed')
        try:
            lane = _crystal_cage_plan(fresh, live_target, work)
        except SkillError as exc:
            work.update(stage='return', abort_reason=exc.reason)
            runner.save()
            return
        work['last_cage_plan'] = lane
        runner.save()
        if lane['next_bar'] is not None:
            bar = lane['next_bar']
            runner.select(data['pickaxe'], 2)
            runner.step('open_fresh_observed_crystal_cage', lambda: dimensions.open_crystal_cage(
                runner, work['uuid'], [bar], max_blocks=1, hotbar_slot=runner.last.player['selected_slot']),
                lambda result: work['bars_mined'].append(bar))
            return  # Re-observe the actual aperture before selecting another bar.
        work['stage'] = 'bridge'
        runner.save()
        return
    if work['stage'] == 'bridge':
        require('firing' in work, 'crystal_access_plan_required_no_legacy_replay')
        feet, direction = _coord(sample.player), work['direction']
        expected = dict(work['base'], y=work['height'])
        for axis in ('x', 'z'):
            expected[axis] += len(work['bridge_cells']) * direction[axis]
        require(feet == expected, 'crystal_bridge_owned_corridor_changed')
        if feet != work['firing']:
            require(len(work['bridge_cells']) < work['reserve']['bridge_length'],
                    'crystal_bridge_original_length_exhausted')
            destination = dict(feet, x=feet['x'] + direction['x'], z=feet['z'] + direction['z'])
            if not (_standable(sample, feet) and all(_clear(sample, dict(destination, y=destination['y'] + dy))
                                                    for dy in (-1, 0, 1))):
                work.update(stage='return', abort_reason='crystal_bridge_observed_obstruction_or_unknown')
                runner.save()
                return
            runner.bridge(direction, lambda result: work['bridge_cells'].append(_coord(result.last_observation.player)))
            return
        work['stage'] = 'shoot'
        runner.save()
    if work['stage'] == 'shoot':
        # Recheck on every fresh shoot-stage entry, including after collateral
        # waits. This is a known pre-shot refusal, never a post-dispatch retry.
        if _horizontal(sample.player, target) < 14:
            work.update(stage='return', abort_reason='crystal_planned_blast_clearance_changed')
            runner.save()
            return
        # Wait rather than start drawing into an already observed blast collateral
        # situation. Any newly appearing danger still stops the native action.
        collateral = [e for e in threats.entities(sample) if e.get('alive') is True
            and e.get('uuid') != target['uuid'] and threats._number(e.get('health'))
            and math.dist(threats.position(e), threats.position(target)) < 12]
        if collateral:
            runner.sleeper(.1)
            return
        def removed(result):
            data['crystals'][work['uuid']]['removed'] = True
            data['crystals'][work['uuid']]['removal_request_ids'] = list(result.request_ids)
            work['stage'] = 'return'
        runner.step('shoot_crystal_verify_loaded_area_removal', lambda: dimensions.remove_crystal(
            runner, work['uuid'], hotbar_slot=0, min_health=settings['min_health']), removed)
        return
    if work['stage'] == 'return':
        goal = dict(work['base'], y=work['height'])
        runner.move(goal, label='retrace_observed_crystal_bridge')
        work['stage'] = 'descend'
        runner.save()
        return
    if work['stage'] == 'descend':
        require(_coord(sample.player)['x'] == work['base']['x']
                and _coord(sample.player)['z'] == work['base']['z'],
                'crystal_tower_return_column_changed_no_guessed_descent')
        if sample.player['y'] > work['base']['y'] + .15:
            runner.down()
            return
        require(abs(sample.player['y'] - work['base']['y']) <= .15, 'crystal_tower_return_height_changed')
        data['crystal_work'] = None
        runner.save()
        require(work.get('abort_reason') is None, work.get('abort_reason', 'crystal_return_completed'))


def _head(dragon):
    values = [part for part in dragon.get('dragon_parts', []) if part.get('name') == 'head']
    require(len(values) == 1, 'observed_dragon_head_required')
    bounds = values[0].get('bounding_box', {})
    low, high = threats.position(bounds.get('min', {})), threats.position(bounds.get('max', {}))
    return {k: (low[i] + high[i]) / 2 for i, k in enumerate(('x', 'y', 'z'))}


def _combat_stand(sample, point, reach_distance=2.8):
    eye = threats.position(sample.player.get('eye_position', {}))
    eye_height = eye[1] - sample.player['y']
    choices = []
    for route in observed_routes(sample).values():
        candidate = route[-1]
        hypothetical = (candidate['x'] + .5, candidate['y'] + eye_height, candidate['z'] + .5)
        distance = math.dist(hypothetical, _point(point))
        if distance <= reach_distance:
            choices.append((len(route), distance, _key(candidate), candidate))
    return min(choices)[-1] if choices else None


def _dragon_step(runner, sample):
    data, settings = runner.data, runner.data['settings']
    if _abort_owned_tower_if_low(runner, sample, 'dragon_tower'): return
    visible_crystals = [e for e in threats.entities(sample) if e.get('type') == 'minecraft:end_crystal'
                        and e.get('alive') is True and not data['crystals'][e['uuid']]['removed']]
    if visible_crystals:
        if _return_owned_tower(runner, sample, 'dragon_tower'): return
        data['phase'] = 'crystals'
        runner.save()
        return
    if data['dragon'] is None:
        runner.frontier(sample)
        return
    target = threats.entity(sample, data['dragon']['uuid'], required=False)
    if data.get('dragon_tower') and (target is None or target.get('phase_id') not in (6, 7)
            or threats._dead(target) or _horizontal(sample.player, _head(target)) > 4):
        _return_owned_tower(runner, sample, 'dragon_tower')
        return
    if target is None:
        # Move/search with the last actually observed geography, never declare a
        # kill when the dragon left the observation radius or was unloaded.
        runner.frontier(sample)
        return
    require(target['entity_id'] == data['dragon']['entity_id'], 'dragon_identity_changed')
    if threats._dead(target):
        require(data['dragon_damage'], 'dragon_death_without_local_damage_history_blocks_gateway')
        data['dragon'].update(dead_observed=True, death_tick=sample.tick,
                              death_position={k: target[k] for k in ('x', 'y', 'z')})
        data['phase'] = 'gateway'
        data['visited'] = {}
        runner.save()
        return
    if target.get('phase_id') not in (6, 7):
        runner.sleeper(.2)
        return
    point = _head(target)
    eye = threats.position(sample.player.get('eye_position', {}))
    if math.dist(eye, _point(point)) > 2.8:
        stand = _combat_stand(sample, point)
        if stand is not None:
            runner.move(stand, label='approach_observed_perched_dragon_head')
        elif _horizontal(sample.player, point) <= 2.5 and point['y'] - eye[1] > 2:
            require(point['y'] - eye[1] <= 6, 'perched_dragon_head_vertical_reach_unsupported')
            if not data.get('dragon_tower'):
                base = _coord(sample.player)
                top = base['y'] + math.ceil(point['y'] - eye[1] - 1)
                reserve = _reserve_tower(runner, sample, base, top)
                data['dragon_tower'] = {'base': base, 'reserve': reserve}
                runner.save()
            runner.up()
        else:
            runner.frontier(sample, point)
        return
    require(len(data['dragon_damage']) < settings['max_dragon_strikes'], 'dragon_strike_budget_exhausted')
    runner.select(data['sword'], 1)
    def damaged(result):
        require(result.evidence.get('observed_health_loss', 0) > 0, 'dragon_damage_evidence_required')
        data['dragon_damage'].append({k: deepcopy(result.evidence.get(k)) for k in
            ('target_uuid', 'target_initial_health', 'target_observed_health', 'observed_health_loss',
             'target_dead_observed', 'native_action_id')})
        if result.evidence.get('target_dead_observed') is True:
            after_target = threats.entity(result.last_observation, data['dragon']['uuid'])
            require(threats._dead(after_target), 'actual_dragon_death_observation_required')
            data['dragon'].update(dead_observed=True, death_tick=result.last_observation.tick,
                death_position={k: after_target[k] for k in ('x', 'y', 'z')})
            data['phase'], data['visited'] = 'gateway', {}
    runner.step('perched_dragon_strike_actual_health_delta', lambda: threats.strike(runner,
        target['uuid'], min_health=settings['min_health'], expected_dragon_phase=target['phase_id']), damaged)


def _gateways(sample):
    nearby = sample.state.get('nearby', {})
    rows = nearby.get('end_gateways')
    require(nearby.get('end_gateways_truncated') is False and isinstance(rows, list),
            'complete_loaded_gateway_observation_required')
    require(len(rows) <= 128, 'loaded_gateway_observation_budget')
    result = []
    for row in rows:
        require(row.get('id') == 'minecraft:end_gateway' and row.get('loaded') is True
                and isinstance(row.get('properties'), dict),
                'gateway_must_be_loaded_observed_block_entity')
        result.append(reach.coordinate(row))
    return result


def _gateway_step(runner, sample):
    from . import mobility
    data = runner.data
    require(data['dragon'] is not None and data['dragon'].get('dead_observed') is True
            and data['dragon_damage'], 'local_actual_dragon_completion_required_before_gateway')
    if _return_owned_tower(runner, sample, 'dragon_tower'): return
    # The pearl costs up to five health. Restore the reserve on observed ground,
    # using actual food and observed regeneration; never merely lower the guard.
    if data['gateway'] is None and sample.player['health'] <= data['settings']['min_health'] + 5:
        require(_rest_station(sample), 'gateway_safe_unthreatened_regeneration_station_required')
        health_wait = data.setdefault('gateway_health_wait', {'started': time.time(), 'minimum_seen': sample.player['health']})
        require(sample.player['health'] >= health_wait['minimum_seen'], 'gateway_health_recovery_damage_observed')
        require(time.time() - health_wait['started'] <= 90, 'gateway_health_reserve_not_recovered_within_budget')
        require(type(sample.player.get('food')) is int, 'gateway_recovery_hunger_observation_required')
        if sample.player['food'] < 18:
            foods = [s for s in inventory.items(sample) if s.get('id') in inventory.FOODS and s.get('count', 0) > 0]
            require(foods, 'gateway_health_recovery_food_required')
            food = sorted(foods, key=lambda s: s['slot'])[0]['id']
            runner.step('eat_observed_food_for_gateway_health_reserve', lambda: inventory.consume(runner, food))
        else:
            runner.sleeper(.2)
        runner.save()
        return
    work = data['gateway']
    if work is not None and work.get('stage') in ('ascend', 'pearl') and _return_reserve_low(runner, work):
        work.update(stage='return_after_no_shot', abort_reason='gateway_stopped_with_return_reserve')
        runner.save()
    if work is not None and work.get('stage') == 'return_after_no_shot':
        base = work['base']
        require(_coord(sample.player)['x'] == base['x'] and _coord(sample.player)['z'] == base['z'],
                'gateway_return_column_changed')
        if sample.player['y'] > base['y'] + .15:
            runner.down()
            return
        require(abs(sample.player['y'] - base['y']) <= .15, 'gateway_return_base_height_changed')
        work['stage'] = 'returned_no_retry'
        runner.save()
        raise SkillError(work['abort_reason'])
    require(work is None or work.get('stage') != 'returned_no_retry', 'gateway_no_shot_returned_no_automatic_retry')
    gateways = _gateways(sample)
    anchor = data['dragon']['death_position']
    central = [g for g in gateways if _horizontal(g, anchor) < 512]
    if data['gateway'] is None:
        if not central:
            runner.frontier(sample)
            return
        target = min(central, key=lambda g: (_horizontal(sample.player, g), _key(g)))
        data['gateway'] = {'target': target, 'base': None, 'stage': 'approach'}
        runner.save()
    work = data['gateway']
    target = work['target']
    require(target in gateways, 'chosen_gateway_no_longer_loaded_observed')
    if work['stage'] == 'approach':
        bases = _base_candidates(sample, target)
        if not bases:
            runner.frontier(sample, target)
            return
        require(sample.player['health'] > data['settings']['min_health'] + 5,
                'gateway_prethrow_health_must_cover_five_damage_and_landing_reserve')
        reserve = _reserve_tower(runner, sample, bases[0][3], target['y'] - 1)
        work.update(base=bases[0][3], stage='reach_base', reserve=reserve)
        runner.save()
    if work['stage'] == 'reach_base':
        runner.move(work['base'], label='reach_observed_gateway_approach')
        work['stage'] = 'ascend'
        runner.save()
        return
    if work['stage'] == 'ascend':
        if sample.player['y'] < target['y'] - 1 - .15:
            require(target['y'] - sample.player['y'] <= 32, 'gateway_tower_height_budget_32')
            runner.up()
            return
        require(abs(sample.player['y'] - (target['y'] - 1)) <= 2, 'gateway_aim_height_unsupported')
        work['stage'] = 'pearl'
        runner.save()
    if work['stage'] == 'pearl':
        require(sample.player['health'] > data['settings']['min_health'] + 5,
                'gateway_prethrow_health_must_cover_five_damage_and_landing_reserve')
        def crossed(result):
            after = result.last_observation
            require(_horizontal(after.player, anchor) >= 512, 'gateway_landing_not_observed_outer_end')
            data['outer_origin'] = {k: after.player[k] for k in ('x', 'y', 'z')}
            data['gateway']['crossing_request_ids'] = list(result.request_ids)
            data['phase'], data['visited'] = 'outer', {}
        def no_shot(result):
            work.update(stage='return_after_no_shot', abort_reason='gateway_known_no_shot:' + result.reason,
                        no_shot_request_ids=list(result.request_ids))
        runner.step('ordinary_gateway_pearl_verify_outer_landing', lambda: mobility.gateway_pearl(runner,
            target, hotbar_slot=4, min_health=data['settings']['min_health']), crossed, known_no_effect=no_shot)


def _outer_step(runner, sample):
    data, settings = runner.data, runner.data['settings']
    require(data['dragon'].get('dead_observed') is True and data['gateway'].get('crossing_request_ids')
            and data['outer_origin'] is not None, 'dragon_gateway_prerequisites_required_for_outer_end')
    eye = threats.position(sample.player.get('eye_position', {}))
    bullets = [e for e in threats.entities(sample) if e.get('type') == 'minecraft:shulker_bullet'
               and e.get('alive') is True and math.dist(threats.position(e), threats.position(sample.player)) < 12]
    if bullets:
        bullet = min(bullets, key=lambda e: math.dist(eye, threats.position(e)))
        if math.dist(eye, threats.position(bullet)) > 2.8:
            runner.sleeper(.05)
            return
        runner.select(data['sword'], 1)
        runner.step('intercept_exact_observed_shulker_bullet', lambda: deflect_shulker_bullet(
            runner, bullet['uuid'], min_health=settings['min_health']))
        return
    if _abort_owned_tower_if_low(runner, sample, 'shulker_tower'): return
    if data.get('shulker_tower'):
        current = threats.entity(sample, data['shulker_target'], required=False) if data['shulker_target'] else None
        if current is None or threats._dead(current) or _horizontal(sample.player, current) > 32:
            _return_owned_tower(runner, sample, 'shulker_tower')
            return
    if data.get('shulker_tower') and sample.player['y'] < data['shulker_tower']['top'] - .15:
        runner.up()
        return
    needed = 2 * settings['boxes']
    shell_count = inventory.count(sample, 'minecraft:shulker_shell')
    if shell_count - data['initial_shells'] >= needed and data['shulkers_dead']:
        data['phase'] = 'craft'
        runner.save()
        return
    # Actual dropped item entities have priority. Inventory progress is always
    # counted independently, including automatic pickup during the approach.
    drops = resources._drops(sample, 'minecraft:shulker_shell')
    if drops:
        drop = min(drops, key=lambda e: math.dist(threats.position(sample.player), threats.position(e)))
        if math.dist(threats.position(sample.player), threats.position(drop)) <= 3:
            runner.step('collect_observed_shulker_shell_inventory_delta', lambda: resources.collect(
                runner, 'minecraft:shulker_shell', minimum=1, max_targets=4))
        else:
            runner.frontier(sample, drop)
        return
    target_uuid = data['shulker_target']
    if target_uuid is None:
        candidates = [e for e in threats.entities(sample) if e.get('type') == 'minecraft:shulker'
            and e.get('alive') is True and e.get('uuid') not in data['shulkers_dead']]
        if candidates:
            target = min(candidates, key=lambda e: (abs(e['y'] - sample.player['y']),
                _horizontal(sample.player, e), e['uuid']))
            threats._identity(target)
            data['shulker_target'], data['shulker_entity_id'] = target['uuid'], target['entity_id']
            runner.save()
            target_uuid = target['uuid']
        else:
            try:
                runner.frontier(sample)
            except SkillError as exc:
                if exc.reason != 'no_fresh_reachable_exploration_frontier': raise
                # A one-cell bridge is allowed only into freshly observed clear
                # cells. It cannot turn unknown terrain into assumed air.
                here = _coord(sample.player)
                choices = []
                for dx, dz in CARDINAL:
                    dest = dict(x=here['x'] + dx, y=here['y'], z=here['z'] + dz)
                    floor = _cell(sample, dict(dest, y=dest['y'] - 1))
                    if (_clear(sample, dest) and _clear(sample, dict(dest, y=dest['y'] + 1))
                            and _dry(floor) and floor['id'] in dimensions.AIR
                            and data['visited'].get(_key(dest), 0) == 0):
                        choices.append((_key(dest), {'x': dx, 'z': dz}))
                require(choices, 'outer_end_no_observed_safe_route_or_bridge')
                runner.bridge(min(choices)[1])
            return
    target = threats.entity(sample, target_uuid, required=False)
    require(target is not None, 'selected_shulker_missing_is_not_death')
    require(target['entity_id'] == data['shulker_entity_id'], 'selected_shulker_identity_changed')
    if threats._dead(target):
        require(any(d['target_uuid'] == target_uuid for d in data['shulker_damage']),
                'shulker_death_requires_local_damage_history')
        data['shulkers_dead'].append(target_uuid)
        data['shulker_target'] = None
        runner.save()
        return
    point = {k: target[k] for k in ('x', 'y', 'z')}
    point['y'] += .5
    eye = threats.position(sample.player.get('eye_position', {}))
    distance = math.dist(eye, _point(point))
    require(type(target.get('line_of_sight')) is bool and type(target.get('shell_open')) is bool,
            'shulker_visibility_and_shell_observation_required')
    # Shoot from outside the shulker's near-threat radius, leaving room to
    # intercept its projectile without the shooter becoming melee collateral.
    # Closed shells are arrow-immune: a closed shell never admits a bow action.
    ranged_ready = 12 <= distance <= 24 and target['line_of_sight'] is True
    if not ranged_ready:
        if data.get('shulker_tower'):
            _return_owned_tower(runner, sample, 'shulker_tower')
            return
        if 10 <= _horizontal(sample.player, target) <= 18 and point['y'] - eye[1] > 15:
            height = math.ceil(point['y'] - eye[1] - 8)
            require(height <= 32, 'shulker_ascent_height_budget_32')
            base = _coord(sample.player)
            reserve = _reserve_tower(runner, sample, base, base['y'] + height)
            data['shulker_tower'] = {'base': base, 'top': base['y'] + height, 'reserve': reserve}
            runner.save()
            runner.up()
            return
        routes = observed_routes(sample)
        options = []
        for route in routes.values():
            candidate = route[-1]
            if len(route) <= 1 or data['visited'].get(_key(candidate), 0) > 1: continue
            hypothetical = (candidate['x'] + .5, candidate['y'] + eye[1] - sample.player['y'], candidate['z'] + .5)
            shot_distance = math.dist(hypothetical, _point(point))
            if shot_distance >= 10:
                options.append((abs(shot_distance - 16) + 4 * data['visited'].get(_key(candidate), 0),
                                len(route), _key(candidate), candidate))
        require(options, 'no_observed_safe_shulker_firing_approach')
        runner.move(min(options)[-1], label='reach_observed_shulker_ranged_station')
        return
    if target['shell_open'] is False:
        runner.sleeper(.1)
        return
    require(len(data['shulker_damage']) < settings['max_shulker_strikes'], 'shulker_strike_budget_exhausted')
    runner.select('minecraft:bow', 0)
    def damaged(result):
        require(result.evidence.get('observed_health_loss', 0) > 0, 'shulker_damage_evidence_required')
        data['shulker_damage'].append({k: deepcopy(result.evidence.get(k)) for k in
            ('target_uuid', 'target_initial_health', 'target_observed_health', 'observed_health_loss', 'target_dead_observed')})
        if result.evidence.get('target_dead_observed') is True:
            data['shulkers_dead'].append(target_uuid)
            data['shulker_target'] = None
    runner.step('shulker_strike_actual_health_delta', lambda: threats.strike(runner,
        target_uuid, ranged=True, min_health=settings['min_health']), damaged)


def _place_table(runner, sample):
    rows = []
    for cell in sample.terrain.get('cells', []):
        if cell.get('id') == 'minecraft:crafting_table':
            position = reach.coordinate(cell)
            if _horizontal(sample.player, position) <= 3 and abs(sample.player['y'] - position['y']) <= 1:
                rows.append(position)
    if rows:
        return min(rows, key=_key)
    runner.select('minecraft:crafting_table', 5)
    before = runner.observe(terrain=True, radius=4, vertical=4, entity_radius=128)
    start = _coord(before.player)
    choices = []
    for dx, dz in CARDINAL:
        position = dict(x=start['x'] + dx, y=start['y'], z=start['z'] + dz)
        if _standable(before, position): choices.append(position)
    require(choices, 'no_observed_safe_crafting_table_support')
    position = min(choices, key=_key)
    support = dict(position, y=position['y'] - 1)
    floor, old = reach.block_at(before, support), reach.block_at(before, position)
    initial = inventory.count(before, 'minecraft:crafting_table')
    command = {'op': 'action', 'action': 'place_block', 'support': support, 'face': 'up',
        'hotbar_slot': before.player['selected_slot'], 'jump': False, 'sneak': False, 'timeout_ms': 5000,
        'expected_support_id': floor['id'], 'expected_support_properties': floor['properties'],
        'expected_target_id': old['id'], 'expected_target_properties': old['properties'],
        'expected_block_id': 'minecraft:crafting_table', 'expected_block_properties': {}}
    def verified(_, after):
        cell = _cell(after, position)
        return (cell is not None and cell['id'] == 'minecraft:crafting_table'
                and inventory.count(after, 'minecraft:crafting_table') == initial - 1)
    runner.step('place_carried_crafting_table', lambda: runner.execute('expedition.place_crafting_table',
                 command, verified, before=before))
    return position


def _craft_step(runner, sample):
    data, settings = runner.data, runner.data['settings']
    require(data['dragon'].get('dead_observed') is True and data['shulkers_dead'],
            'actual_dragon_and_shulker_death_required_before_craft')
    table = _place_table(runner, sample)
    station = {'position': table, 'block_id': 'minecraft:crafting_table', 'face': 'up'}
    live = runner.observe(allow_menu=True)
    chest_missing = max(0, settings['boxes'] - inventory.count(live, 'minecraft:chest'))
    if chest_missing:
        runner.step('craft_observed_chest_ingredients', lambda: production.craft(runner, 'chest',
            batches=chest_missing, station=station, max_actions=512))
        runner.step('close_chest_crafting_menu', lambda: reach.close_menu(runner))
    def crafted(result):
        require(inventory.count(result.last_observation, 'minecraft:shulker_box') - data['initial_boxes']
                >= settings['boxes'], 'shulkerbox_inventory_delta_required')
        data['phase'] = 'complete'
        data['box_craft_request_ids'] = list(result.request_ids)
    runner.step('craft_shulkerbox_inventory_delta', lambda: production.craft(runner, 'shulker_box',
        batches=settings['boxes'], station=station, max_actions=512), crafted)
    runner.step('close_completed_shulkerbox_menu', lambda: reach.close_menu(runner))


def end_expedition(runtime, *, job_id, boxes=1, max_actions=4096, max_seconds=7200,
                   max_walk_distance=8192, max_search_steps=512, max_crystals=16,
                   max_dragon_strikes=256, max_shulker_strikes=64,
                   block_id='minecraft:cobblestone', min_health=12, resume=False):
    """Dragon → observed gateway → outer End → actual shells → crafted shulkerbox.

    The caller supplies one goal and budgets, never per-step coordinates/UUIDs.
    Loaded frontier routing, tower/cage/bridge planning and target selection are
    automatic. A missing prerequisite or unsafe route stops with exact evidence.
    `resume=True` only revalidates an idle checkpoint. Any interrupted composite
    action, failed/unknown action, changed context or exhausted budget stays shut.
    """
    limits = dict(boxes=(boxes, 1, 8), max_actions=(max_actions, 1, 8192),
        max_seconds=(max_seconds, 1, 86400), max_walk_distance=(max_walk_distance, 1, 65536),
        max_search_steps=(max_search_steps, 1, 4096), max_crystals=(max_crystals, 1, 32),
        max_dragon_strikes=(max_dragon_strikes, 1, 512), max_shulker_strikes=(max_shulker_strikes, 1, 512))
    for name, (value, low, high) in limits.items():
        require(type(value) is int and low <= value <= high, 'invalid_expedition_' + name)
    require(block_id in FULL_BLOCKS and type(resume) is bool, 'invalid_expedition_material_or_resume')
    require(type(min_health) in (int, float) and math.isfinite(min_health) and 12 <= min_health < 15,
            'expedition_health_reserve_12_to_less15_for_pearl_damage')
    settings = {name: value[0] for name, value in limits.items()}
    settings.update(block_id=block_id, min_health=min_health)
    path = _path(runtime, job_id)
    with runtime._mutex:
        runtime._open()
        require(not runtime.has_unresolved_execution, 'expedition_unresolved_execution_no_replay')
        now = time.time()
        if path.exists():
            data = _read(path)
            require(data['settings'] == settings, 'expedition_settings_cannot_change_or_reset_budgets')
            require(data['inflight'] is None, 'interrupted_expedition_step_no_replay')
            require(data.get('status') != 'unknown', 'unknown_expedition_no_replay')
            require(data.get('owner') == runtime._owner or resume or data['phase'] == 'complete',
                    'expedition_restart_requires_explicit_revalidation')
            require(now >= data['last_wall_clock'], 'expedition_clock_regressed')
            data['owner'] = runtime._owner
        else:
            before = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=128)
            require(dimensions._dimension(before) == dimensions.END, 'expedition_requires_end')
            require(threats._number(before.player.get('max_health'))
                    and before.player['max_health'] > min_health + 5,
                    'observed_max_health_cannot_cover_pearl_and_landing_reserve')
            data = {'schema_version': 1, 'job_id': job_id, 'settings': settings, 'owner': runtime._owner,
                'context': list(before.context), 'phase': 'prepare', 'status': 'active', 'inflight': None,
                'created_unix': now, 'deadline_unix': now + max_seconds, 'last_wall_clock': now,
                'actions_reserved': 0, 'walk_reserved': 0., 'search_steps': 0, 'completed_steps': 0,
                'request_ids': [], 'visited': {}, 'crystals': {}, 'crystal_work': None, 'dragon': None,
                'dragon_damage': [], 'gateway': None, 'outer_origin': None, 'shulker_target': None,
                'shulker_entity_id': None, 'shulkers_dead': [], 'shulker_damage': [],
                'initial_shells': inventory.count(before, 'minecraft:shulker_shell'),
                'initial_boxes': inventory.count(before, 'minecraft:shulker_box')}
            atomic_write(path, data)
        runner = _Runner(runtime, path, data)
        try:
            while True:
                sample = runner.snapshot()
                if data['phase'] == 'complete':
                    require(inventory.count(sample, 'minecraft:shulker_box') - data['initial_boxes'] >= boxes,
                            'completed_shulkerbox_inventory_changed_no_recraft')
                    require(data['dragon']['dead_observed'] and data['dragon_damage']
                            and data['gateway']['crossing_request_ids'] and data['shulkers_dead']
                            and data.get('box_craft_request_ids'), 'expedition_completion_evidence_chain_missing')
                    data['status'] = 'complete'
                    runner.save()
                    return runtime.result('expedition.end_expedition', [sample],
                        action_request_ids=data['request_ids'], phase='complete', job_id=job_id,
                        dragon_dead_observed=True, dragon_uuid=data['dragon']['uuid'],
                        dragon_damage_samples=data['dragon_damage'], all_world_crystals_absent=False,
                        gateway_traversal_observed=True, outer_end_landing=data['outer_origin'],
                        shulkers_dead=data['shulkers_dead'], shulker_damage_samples=data['shulker_damage'],
                        shulkerboxes_acquired=boxes, actions_reserved=data['actions_reserved'],
                        walk_reserved=data['walk_reserved'], gameplay_acceptance='requires_live_validation')
                if data['phase'] == 'prepare':
                    missing, sword, pickaxe = _loadout(sample, boxes, block_id)
                    require(not missing, 'expedition_missing_prerequisites:' + ','.join(missing))
                    data.update(sword=sword, pickaxe=pickaxe)
                    runner.step('equip_enderman_gaze_protection', lambda: inventory.equip(runner,
                        'minecraft:carved_pumpkin', slot='head'))
                    data['phase'] = 'crystals'
                    runner.save()
                    continue
                _remember_targets(runner, sample)
                if data['phase'] == 'crystals': _crystal_step(runner, sample)
                elif data['phase'] == 'dragon': _dragon_step(runner, sample)
                elif data['phase'] == 'gateway': _gateway_step(runner, sample)
                elif data['phase'] == 'outer': _outer_step(runner, sample)
                elif data['phase'] == 'craft': _craft_step(runner, sample)
        except SkillError as exc:
            data.update(status=exc.status, reason=exc.reason)
            if data['inflight'] is not None and data['inflight']['reserved_actions'] == 0 and not runtime.has_unresolved_execution:
                data['inflight'] = None  # Proven no native submission; nothing can be replayed.
            if data['inflight'] is not None:
                data['inflight'].update(status=exc.status, reason=exc.reason)
            runner.save()
            return Outcome(exc.status, exc.reason, tuple(data['request_ids']),
                {'phase': data['phase'], 'job_id': job_id, 'goal_completed': False,
                 'dragon_dead_observed': bool(data.get('dragon', {}).get('dead_observed')) if data.get('dragon') else False,
                 'all_world_crystals_absent': False, 'server_confirmed': False,
                 'actions_reserved': data['actions_reserved'], 'walk_reserved': data['walk_reserved'],
                 'risk_remaining': True, 'interrupted_step_requires_no_replay': data['inflight'] is not None}, runner.last)
        except Exception as exc:
            data.update(status='unknown' if runtime.has_unresolved_execution or data['inflight'] else 'blocked',
                        reason='expedition_exception:' + type(exc).__name__)
            runner.save()
            return Outcome(data['status'], data['reason'], tuple(data['request_ids']),
                           {'phase': data['phase'], 'goal_completed': False, 'server_confirmed': False,
                            'risk_remaining': True}, runner.last)
