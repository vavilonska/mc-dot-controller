"""Observation-selected, bounded mob encounters and real inventory resource goals.

No UUID/coordinate supplied by a caller is needed. Selection is only from complete
fresh observations, movement only from loaded dry geometry, and native target
actions recheck the species policy on every callback. An attack receipt is never
a kill; a kill is never loot. Every unsuccessful/unknown action stops the goal.
"""
from __future__ import annotations

import math
from itertools import product
from .core import Outcome, SkillError, require
from . import inventory, mobility, reach, resources, threats
from .danger_policy import DANGER_TYPES, PROJECTILE_TYPES, danger_clearance, observed_calm_enderman

SPECIES = frozenset('minecraft:' + name for name in
                    ('enderman', 'blaze', 'creeper', 'spider', 'cave_spider'))
MOB_DROPS = {'minecraft:ender_pearl': 'minecraft:enderman',
             'minecraft:blaze_rod': 'minecraft:blaze',
             'minecraft:gunpowder': 'minecraft:creeper',
             'minecraft:string': 'minecraft:spider'}
# Danger classification is wider than the explicitly supported hunt species.
_HOSTILES = DANGER_TYPES
_PROJECTILES = PROJECTILE_TYPES
_TIER = {'wooden': 0, 'golden': 0, 'stone': 1, 'iron': 2, 'diamond': 3, 'netherite': 4}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _species(value):
    require(value in SPECIES, 'unsupported_mob_goal_species')
    return value


def _rows(observation):
    rows = threats.entities(observation)
    require(all(isinstance(e, dict) for e in rows), 'invalid_mob_entity_snapshot')
    require(len({e.get('uuid') for e in rows}) == len(rows)
            and len({e.get('entity_id') for e in rows}) == len(rows),
            'duplicate_mob_entity_identity')
    for row in rows:
        threats._identity(row)
        threats.position(row)
        require(type(row.get('alive')) is bool, 'mob_entity_liveness_required')
    return rows


def _target(observation, identity):
    rows = [row for row in _rows(observation) if row['uuid'] == identity[1]]
    require(len(rows) == 1, 'mob_target_missing_not_death')
    require(threats._identity(rows[0]) == identity, 'mob_target_identity_changed')
    return rows[0]


def _living(row):
    return row.get('alive') is True and _number(row.get('health')) and row['health'] > 0


def _effects(observation):
    p = observation.player
    require(p.get('effects_truncated') is False and isinstance(p.get('effects'), list),
            'complete_mob_effects_required')
    for effect in p['effects']:
        require(isinstance(effect, dict) and isinstance(effect.get('id'), str)
                and type(effect.get('duration_ticks')) is int, 'mob_effect_duration_required')
    return p['effects']


def _effect(observation, item_id, minimum=1):
    return any(effect['id'] == item_id
               and (effect['duration_ticks'] == -1 or effect['duration_ticks'] >= minimum)
               for effect in _effects(observation))


def _pumpkin(observation):
    return any(s.get('slot') == 'head' and s.get('id') == 'minecraft:carved_pumpkin'
               and s.get('count', 0) > 0 for s in observation.player.get('armor', []))


def _safety(observation, minimum, target=None):
    threats._health(observation, minimum)
    require(observation.state.get('screen_open') is False, 'mob_goal_requires_closed_menu')
    require(not _effect(observation, 'minecraft:levitation'), 'mob_levitation_stop')
    for row in _rows(observation):
        if row.get('alive') is not True or row is target:
            continue
        distance = math.dist(threats.position(observation.player), threats.position(row))
        calm = observed_calm_enderman(observation, row, pumpkin=_pumpkin(observation))
        danger = danger_clearance(row, calm_enderman=calm)
        if danger is not None:
            minimum, exclusive, reason = danger
            require(distance > minimum if exclusive else distance >= minimum, reason)


def _minimum_distance(target, observation):
    if target['type'] == 'minecraft:creeper':
        state = target.get('creeper', {})
        require(type(state.get('powered')) is bool, 'creeper_power_state_required')
        return 16 if state['powered'] else 12
    if target['type'] == 'minecraft:blaze':
        return 12 if _effect(observation, 'minecraft:fire_resistance', 60) else 16
    return 8


def _species_policy(observation, target, *, station=True):
    kind = target['type']
    if kind == 'minecraft:enderman':
        if station:
            shelter = observation.player.get('enderman_shelter', {})
            feet = mobility._feet(observation)
            require(shelter.get('schema_version') == 1 and shelter.get('safe') is True
                    and shelter.get('roof_y') == feet.y + 2,
                    'native_enderman_two_block_roof_required')
            require(_roof(observation, feet), 'observed_enderman_roof_required')
            require(reach._arrived(observation.player, _center(feet)),
                    'enderman_centered_shelter_required')
        return {'enderman_shelter_required': True}
    if kind == 'minecraft:creeper':
        state = target.get('creeper', {})
        require(state.get('ignited') is False and state.get('swell_ticks') == 0
                and type(state.get('swell_direction')) is int and state['swell_direction'] <= 0
                and state.get('fuse_ticks') == 30 and state.get('explosion_radius') == 3,
                'creeper_active_or_unknown_fuse_stop')
        flags = {'creeper_safety_required': True}
    elif kind == 'minecraft:blaze':
        state = target.get('blaze', {})
        require(type(state.get('charged')) is bool, 'blaze_charge_state_required')
        if _effect(observation, 'minecraft:fire_resistance', 60):
            flags = {'fire_resistance_required': True, 'blaze_safety_mode': 'fire_resistance'}
        else:
            shield = observation.player.get('offhand', {})
            require(shield.get('id') == 'minecraft:shield' and shield.get('count') == 1
                    and bool(shield.get('item_fingerprint')), 'blaze_observed_offhand_shield_required')
            require(type(shield.get('max_damage')) is int and type(shield.get('damage')) is int
                    and shield['max_damage'] - shield['damage'] >= 64,
                    'blaze_shield_durability_reserve')
            require(observation.player.get('health', 0) > 18, 'blaze_shield_window_health_reserve')
            require(all(row is target or row.get('alive') is not True or row['type'] not in _HOSTILES
                        or math.dist(threats.position(row), threats.position(observation.player)) >= 32
                        for row in _rows(observation)), 'blaze_shield_window_isolated_target_required')
            require(all(row['type'] != 'minecraft:small_fireball'
                        or math.dist(threats.position(row), threats.position(observation.player)) > 32
                        for row in _rows(observation) if row.get('alive') is True),
                    'blaze_fireball_shield_window_stop')
            flags = {'blaze_safety_mode': 'shield_window', 'expected_offhand_item': shield}
    elif kind == 'minecraft:cave_spider':
        require(not _effect(observation, 'minecraft:poison'), 'cave_spider_poison_stop')
        flags = {'poison_guard_required': True}
    else:
        return {}
    if station:
        require(_minimum_distance(target, observation) <= math.dist(threats.position(observation.player),
                threats.position(target)) <= 30, 'mob_safe_ranged_station_required')
    return flags


def _center(block):
    return {'x': block.x + .5, 'y': block.y, 'z': block.z + .5}


def _segment_distance(point, start, end):
    """Minimum clearance over the entire short segment, including centering."""
    delta = tuple(b - a for a, b in zip(start, end))
    length_squared = sum(value * value for value in delta)
    along = (sum((p - a) * d for p, a, d in zip(point, start, delta)) / length_squared
             if length_squared else 0)
    along = max(0, min(1, along))
    return math.dist(point, tuple(a + along * d for a, d in zip(start, delta)))


def _roof(observation, feet):
    """A full dry 3x3 ceiling exactly two blocks above an ordinary player stand.

    This is the two-block-height shelter strategy, not a teleport-proof claim or
    an unsupported pillar-height heuristic. Native independently rechecks it.
    """
    try:
        grid, _ = reach._grid(observation)
        if not grid.standable(feet):
            return False
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                cell = reach.block_at(observation, mobility._xyz(feet.offset(x=dx, y=2, z=dz)))
                if (cell.get('collision_known') is not True
                        or cell.get('collision_bounds') != [0, 0, 0, 1, 1, 1]
                        or cell.get('fluid') != 'minecraft:empty' or cell.get('hazards') != []):
                    return False
        return True
    except (SkillError, reach.TerrainError, KeyError, TypeError, ValueError):
        return False


def _covered_enderman_melee_line(observation, target, now):
    """Conservative current torso corridor, only for covered Enderman melee.

    Vanilla's entity line_of_sight is eye-to-eye. A two-high player roof can
    block a tall Enderman's eyes while the native melee aim (current AABB
    center) remains visible. This does not change that eye-LOS observation or
    substitute a hit: native still repeats shelter, exact pick and reach.
    Nonempty/unknown cells, including partial shapes, are conservatively
    rejected rather than approximating their collision by a bounding box.
    """
    require(target.get('type') == 'minecraft:enderman'
            and target.get('line_of_sight') is False,
            'observed_mob_line_of_sight_required')
    require(any(row is target for row in _rows(observation)), 'mob_target_not_current_observation')
    require(observation.terrain is observation.raw.get('terrain'),
            'enderman_melee_original_terrain_required')
    shelter = observation.player.get('enderman_shelter', {})
    require(type(shelter.get('schema_version')) is int and shelter['schema_version'] == 1
            and shelter.get('safe') is True, 'native_enderman_two_block_roof_required')
    try:
        grid, stamp = reach._grid(observation)
        grid.require_fresh(stamp, now, max_age_ticks=5, max_wall_age=.8)
        require(type(grid.radius) is int and 0 <= grid.radius <= 64
                and type(grid.vertical) is int and 0 <= grid.vertical <= 64
                and len(grid.cells) == (2 * grid.radius + 1) ** 2 * (2 * grid.vertical + 1)
                and all(grid.contains(at) for at in grid.cells),
                'enderman_melee_complete_terrain_required')
    except (reach.TerrainError, KeyError, TypeError, ValueError):
        raise SkillError('enderman_melee_terrain_unavailable') from None
    eye = threats.position(observation.player.get('eye_position'))
    box = target.get('bounding_box')
    require(isinstance(box, dict), 'enderman_melee_bounds_required')
    low, high = threats.position(box.get('min')), threats.position(box.get('max'))
    position = threats.position(target)
    # Only canonical adult geometry; scaled/malformed bounds do not acquire
    # a general-purpose permission to ignore LOS. Values come from this frame.
    dimensions = (.6000000238418579, 2.9000000953674316, .6000000238418579)
    require(all(abs(b - a - size) <= 1e-6 for a, b, size in zip(low, high, dimensions))
            and abs(low[1] - position[1]) <= 1e-6
            and all(abs((low[i] + high[i]) / 2 - position[i]) <= 1e-6 for i in (0, 2)),
            'enderman_melee_adult_bounds_required')
    aim = tuple((a + b) / 2 for a, b in zip(low, high))
    delta = tuple(b - a for a, b in zip(eye, aim))
    # The aimed segment must enter the uninflated observed AABB in native
    # melee range. Native renderer picking is the final exact hit authority.
    enter = 0.
    for a, d, lo, hi in zip(eye, delta, low, high):
        if d:
            enter = max(enter, min((lo - a) / d, (hi - a) / d))
        else:
            require(lo <= a <= hi, 'enderman_melee_bounds_required')
    distance = math.dist(eye, aim) * enter
    reach_distance = observation.player.get('entity_interaction_range')
    require(_number(reach_distance) and 0 < reach_distance
            and 0 <= enter <= 1 and distance <= min(3., reach_distance),
            'enderman_melee_observed_reach_required')
    # Split at every voxel boundary, including both sides of ambiguous edges.
    # Checking each open interval and boundary proves full segment coverage;
    # no sparse point-sampling or synthetic collision metadata is involved.
    crossings = {0., 1.}
    for a, b, d in zip(eye, aim, delta):
        if d:
            for boundary in range(math.floor(min(a, b)), math.ceil(max(a, b)) + 1):
                fraction = (boundary - a) / d
                if 0 < fraction < 1:
                    crossings.add(fraction)
    ordered = sorted(crossings)
    samples = ordered + [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]
    for fraction in samples:
        indices = []
        for a, d in zip(eye, delta):
            value = a + d * fraction
            index = math.floor(value)
            indices.append((index - 1, index) if abs(value - index) <= 1e-9 else (index,))
        for xyz in product(*indices):
            at = reach.Block(*xyz)
            require(grid.contains(at) and grid.clear(at), 'enderman_melee_torso_corridor_not_clear')
            cell = reach.block_at(observation, dict(zip(('x', 'y', 'z'), xyz)))
            require(cell.get('collision_bounds') in (None, []),
                    'enderman_melee_torso_corridor_not_clear')


def _box_distance(point, target):
    box = target.get('bounding_box', {})
    low, high = threats.position(box.get('min')), threats.position(box.get('max'))
    require(all(a <= b for a, b in zip(low, high)), 'mob_target_bounds_invalid')
    return math.sqrt(sum(max(a - p, 0, p - b) ** 2 for p, a, b in zip(point, low, high)))


def _native_target_action(before, after, target, action_name):
    action = after.state.get('client_action', {})
    proof = action.get('result', {}).get('target_action', {})
    bound = (action.get('status') == 'succeeded' and action.get('action') == action_name
            and isinstance(action.get('action_id'), str) and bool(action['action_id'])
            and action['action_id'] != before.state.get('client_action', {}).get('action_id')
            and action.get('action_session') == before.context[3] == after.context[3]
            and before.context == after.context
            and proof.get('target_uuid') == target['uuid']
            and proof.get('target_entity_id') == target['entity_id']
            and proof.get('target_type') == target['type']
            and type(proof.get('observation_tick')) is int
            and before.tick <= proof['observation_tick'] < after.tick)
    return proof if bound else {}


def _native_death(before, after, target, action_name):
    """Exact native death witness, never disappearance or historical receipt.

    Runtime also binds the fsynced request and two later same-action samples.
    """
    proof = _native_target_action(before, after, target, action_name)
    return (_number(proof.get('target_initial_health')) and proof['target_initial_health'] > 0
            and _number(proof.get('target_min_observed_health')) and proof['target_min_observed_health'] <= 0
            and proof.get('target_dead_observed') is True)


def _shield_window_completed(before, after, target):
    proof = _native_target_action(before, after, target, 'shoot_entity')
    return (proof.get('shield_window') is True and proof.get('pre_cover_saw_charge') is True
            and proof.get('pre_cover_complete') is True and proof.get('shield_raised') is True
            and proof.get('shield_released') is True and proof.get('shield_blocking_observed') is True
            and type(proof.get('cover_ticks')) is int and proof['cover_ticks'] >= 20
            and proof.get('risk_remaining') is False)


class _Bounded:
    """Chained admission budget: includes equipment, navigation, attacks and pickup."""
    def __init__(self, runtime, max_actions, timeout_seconds):
        require(type(max_actions) is int and 1 <= max_actions <= 4096, 'invalid_mob_action_budget')
        require(_number(timeout_seconds) and 1 <= timeout_seconds <= 3600, 'invalid_mob_deadline')
        self.runtime = runtime
        self.last_clock = runtime.clock()
        self.deadline = self.last_clock + timeout_seconds
        self.remaining = max_actions
        self.ids, self.observations = [], []
        self.context, self.failure = None, None
        self.walk_remaining = None

    def __getattr__(self, name):
        return getattr(self.runtime, name)

    def check(self):
        if self.failure is not None:
            self.require_success(self.failure)
        now = self.runtime.clock()
        require(_number(now) and now >= self.last_clock, 'mob_clock_regressed')
        self.last_clock = now
        require(now < self.deadline, 'mob_goal_deadline_exceeded')
        return self.deadline - now

    def observe(self, *args, **kwargs):
        self.check()
        result = self.runtime.observe(*args, **kwargs)
        self.check()
        if self.context is None:
            self.context = result.context
        require(result.context == self.context, 'mob_goal_context_changed')
        self.observations.append(result)
        return result

    def execute(self, skill, command, verify, **kwargs):
        left = self.check()
        require(self.remaining > 0, 'mob_action_budget_exhausted')
        require(left >= .05, 'mob_goal_deadline_exceeded')
        self.remaining -= 1
        command = dict(command)
        command['timeout_ms'] = min(command.get('timeout_ms', 5000), int(left * 1000))
        if command.get('action') == 'follow_path' and self.walk_remaining is not None:
            points = command.get('waypoints', [])
            require(points and kwargs.get('before') is not None, 'mob_owned_path_origin_required')
            previous = threats.position(kwargs['before'].player)
            distance = 0.0
            for point in points:
                current = threats.position(point)
                distance += math.dist(previous, current)
                previous = current
            require(distance <= self.walk_remaining + 1e-9, 'mob_walk_budget_exhausted')
            self.walk_remaining = max(0.0, self.walk_remaining - distance)
        result = self.runtime.execute(skill, command, verify, **kwargs)
        self.ids.extend(result.request_ids)
        if result.last_observation is not None:
            self.observations.append(result.last_observation)
        if not result.ok:
            self.failure = result
        return result

    def sleeper(self, seconds):
        self.runtime.sleeper(min(seconds, self.check()))
        self.check()

    def require_success(self, result):
        if not result.ok:
            self.failure = result
            raise SkillError(result.reason, status=result.status,
                             request_id=result.request_ids[0] if result.request_ids else None)
        return result.last_observation

    def result(self, skill, observations=(), **evidence):
        self.check()
        result = self.runtime.result(skill, observations, **evidence)
        return Outcome(result.status, result.reason,
                       tuple(dict.fromkeys(self.ids + list(result.request_ids))),
                       result.evidence, result.last_observation)

    def stopped(self, error):
        if self.failure is not None:
            result = self.failure
            return Outcome(result.status, result.reason,
                           tuple(dict.fromkeys(self.ids + list(result.request_ids))),
                           {**result.evidence, 'goal_completed': False, 'server_confirmed': False},
                           result.last_observation)
        ids = self.ids + ([error.request_id] if error.request_id else [])
        return Outcome(error.status, error.reason, tuple(dict.fromkeys(ids)),
                       {'goal_completed': False, 'server_confirmed': False},
                       self.observations[-1] if self.observations else None)


class _Hunt:
    def __init__(self, runtime, max_actions, timeout_seconds, max_search_steps,
                 max_walk_distance, min_health):
        require(type(max_search_steps) is int and 0 <= max_search_steps <= 256,
                'invalid_mob_search_budget')
        require(type(max_walk_distance) is int and 0 <= max_walk_distance <= 4096,
                'invalid_mob_walk_budget')
        require(_number(min_health) and 12 <= min_health <= 20, 'invalid_mob_health_reserve')
        self.rt = _Bounded(runtime, max_actions, timeout_seconds)
        self.rt.walk_remaining = max_walk_distance
        self.searches, self.min_health = max_search_steps, min_health
        self.visited, self.finished = set(), set()

    def observe(self):
        value = self.rt.observe(terrain=True, radius=4, vertical=4, entity_radius=48)
        _rows(value)
        return value

    def _move(self, observation, route, target=None):
        steps = max(1, len(route) - 1)
        # All routes are short. Re-observe/replan before the next segment.
        require(steps <= 2, 'mob_movement_segment_too_long')
        _safety(observation, self.min_health, target)
        threats._require_combat_capability(observation, 'encounter_route_guard_schema_version')
        guard = {'schema_version': 1}
        minimum = self.min_health
        if target is not None:
            _species(target['type'])
            ident, uid, kind = threats._identity(target)
            guard.update(target_entity_id=ident, target_uuid=uid, target_type=kind)
            if kind == 'minecraft:enderman':
                require(observed_calm_enderman(observation, target, pumpkin=_pumpkin(observation)),
                        'enderman_approach_requires_fresh_native_calm')
            policy = _species_policy(observation, target, station=False)
            minimum = threats._effective_min_health(self.min_health, kind,
                shield_window=policy.get('blaze_safety_mode') == 'shield_window')
            threats._health(observation, minimum)
        points = [threats.position(observation.player)] + [threats.position(_center(point)) for point in route]
        for row in _rows(observation):
            if row is target or row.get('alive') is not True:
                continue
            calm = observed_calm_enderman(observation, row, pumpkin=_pumpkin(observation))
            danger = danger_clearance(row, calm_enderman=calm)
            if danger is not None:
                clearance, exclusive, _ = danger
                for start, end in zip(points, points[1:]):
                    distance = _segment_distance(threats.position(row), start, end)
                    require(distance > clearance if exclusive else distance >= clearance,
                            'mob_route_approaches_non_target_threat')
        flags = {'min_health': minimum, 'encounter_route_guard': guard,
                 'require_pumpkin': observation.context[1] == 'minecraft:the_end'}
        if flags['require_pumpkin']:
            require(_pumpkin(observation), 'end_mob_hunt_pumpkin_required')
        end = _center(route[-1])
        outcome = self.rt.execute('combat_goals.position', mobility._path_command(route, flags),
            lambda old, new: reach._arrived(new.player, end), before=observation)
        self.rt.require_success(outcome)
        self.visited.update(route)

    def search(self, observation, species):
        require(self.searches > 0, 'mob_loaded_search_budget_exhausted')
        _safety(observation, self.min_health)
        grid, stamp = reach._grid(observation)
        grid.require_fresh(stamp, self.rt.clock())
        start = mobility._feet(observation)
        paths = mobility.loaded_paths(grid, start, max_steps=2)
        self.visited.add(start)
        candidates = [p for p in paths if p not in self.visited]
        require(candidates, 'mob_no_unvisited_safe_loaded_frontier')
        # No hidden structure coordinates or guaranteed spawning claims.
        goal = max(candidates, key=lambda p: (len(paths[p]), p.x, p.z, p.y))
        self.searches -= 1
        self._move(observation, paths[goal])

    def select(self, observation, species):
        candidates = [row for row in _rows(observation) if row['type'] == species
                      and _living(row) and threats._identity(row) not in self.finished]
        return min(candidates, key=lambda row: (math.dist(threats.position(observation.player),
                   threats.position(row)), row['uuid'])) if candidates else None

    def weapon(self, observation, species):
        if species in ('minecraft:blaze', 'minecraft:creeper', 'minecraft:cave_spider'):
            require(inventory.count(observation, 'minecraft:arrow') > 0
                    or inventory.count(observation, 'minecraft:spectral_arrow') > 0,
                    'observed_bow_ammunition_required')
            weapon = 'minecraft:bow'
            if species == 'minecraft:blaze' and not _effect(observation, 'minecraft:fire_resistance', 60):
                if observation.player.get('offhand', {}).get('id') != 'minecraft:shield':
                    require(inventory.count(observation, 'minecraft:shield') > 0,
                            'blaze_owned_shield_or_fire_resistance_required')
                    self.rt.require_success(inventory.equip(self.rt, 'minecraft:shield', slot='offhand'))
        else:
            rows = [row for row in inventory.items(observation) if row.get('count', 0) > 0
                    and row.get('id', '').startswith('minecraft:')
                    and row['id'].endswith(('_sword', '_axe'))
                    and row['id'].split(':')[1].split('_')[0] in _TIER]
            require(rows, 'observed_melee_weapon_required')
            weapon = max(rows, key=lambda row: (_TIER[row['id'].split(':')[1].split('_')[0]],
                        row['id'].endswith('_sword')))['id']
        self.rt.require_success(inventory.ensure_hotbar(self.rt, weapon))

    def station(self, observation, target):
        _safety(observation, self.min_health, target)
        _species_policy(observation, target, station=False)
        grid, stamp = reach._grid(observation)
        grid.require_fresh(stamp, self.rt.clock())
        start = mobility._feet(observation)
        paths = mobility.loaded_paths(grid, start, max_steps=8)
        ranged = target['type'] in ('minecraft:blaze', 'minecraft:creeper', 'minecraft:cave_spider')
        current_distance = math.dist(threats.position(observation.player), threats.position(target))
        def suitable(at):
            point = _center(at)
            distance = math.dist(threats.position(point), threats.position(target))
            if ranged:
                minimum = _minimum_distance(target, observation)
                return minimum + .5 <= distance <= 28
            if target['type'] == 'minecraft:enderman' and not _roof(observation, at):
                return False
            return _box_distance((point['x'], point['y'] + 1.62, point['z']), target) <= 2.8
        if suitable(start) and reach._arrived(observation.player, _center(start)):
            return True
        if target['type'] == 'minecraft:enderman':
            require(target.get('aggressive') is False, 'aggressive_enderman_requires_current_shelter')
            require(_pumpkin(observation), 'enderman_shelter_approach_requires_pumpkin')
            require(observed_calm_enderman(observation, target, pumpkin=True),
                    'enderman_approach_requires_fresh_native_calm')
        if ranged:
            require(current_distance >= _minimum_distance(target, observation), 'mob_already_inside_safe_ranged_boundary')
        candidates = []
        for at, path in paths.items():
            if not suitable(at):
                continue
            if ranged and any(math.dist(threats.position(_center(p)), threats.position(target))
                              < _minimum_distance(target, observation) for p in path):
                continue
            candidates.append(at)
        require(candidates, 'no_observed_safe_mob_attack_station')
        goal = min(candidates, key=lambda p: (len(paths[p]), p.x, p.y, p.z))
        self._move(observation, paths[goal][:3], target)
        return False

    def strike(self, observation, target):
        _safety(observation, self.min_health, target)
        flags = _species_policy(observation, target)
        if target['type'] == 'minecraft:enderman':
            if target.get('line_of_sight') is not True:
                _covered_enderman_melee_line(observation, target, self.rt.clock())
            # Reuse the exact owned terrain-bearing frame, not a second
            # state-only read that could separate the roof/ray proof from the
            # action. Runtime still enforces latest/fresh/unmodified ownership;
            # _Bounded still reserves this sole action before submission.
            result = threats.strike(self.rt, target['uuid'], ranged=False,
                                    min_health=self.min_health, before=observation)
            self.rt.require_success(result)
            return result.evidence.get('target_dead_observed') is True
        require(target.get('line_of_sight') is True, 'observed_mob_line_of_sight_required')
        identity = threats._identity(target)
        ranged = target['type'] in ('minecraft:blaze', 'minecraft:creeper', 'minecraft:cave_spider')
        shield_window = flags.get('blaze_safety_mode') == 'shield_window'
        if shield_window:
            require(self.rt.check() >= 18, 'blaze_shield_window_remaining_deadline_required')
        command = threats._command(observation, 'shoot_entity' if ranged else 'attack_entity', target,
                                   20000 if shield_window else 5000, maximum=20000 if shield_window else 10000)
        command.update(flags, min_health=max(self.min_health, 18) if shield_window else self.min_health)
        if ranged:
            command['draw_ticks'] = 20
        def verified(old, new):
            if shield_window and not _shield_window_completed(old, new, target):
                return False
            # A teleport, despawn or reused integer entity ID is not a kill.
            rows = [row for row in _rows(new) if row['uuid'] == identity[1]]
            if not rows:
                return _native_death(old, new, target, command['action'])
            current = _target(new, identity)
            return (threats._dead(current) or (_number(current.get('health'))
                    and current['health'] < target['health'] - .01))
        result = self.rt.execute('combat_goals.strike', command, verified, before=observation,
                                 max_samples=60 if ranged else 16, stable_samples=2)
        self.rt.require_success(result)
        after = result.last_observation
        if _native_death(observation, after, target, command['action']):
            return True
        return threats._dead(_target(after, identity))

    def defeat(self, observation, target):
        identity = threats._identity(target)
        _safety(observation, self.min_health, target)
        self.weapon(observation, target['type'])
        # Action limits bound both moving-target positioning and successive
        # confirmed hits. Every new hit is freshly observed, never replayed.
        while True:
            before = self.observe()
            target = _target(before, identity)
            require(_living(target), 'mob_target_not_living_before_next_action')
            if not self.station(before, target):
                continue
            if self.strike(before, target):
                self.finished.add(identity)
                return


def discover_mobs(runtime, species=None):
    """Report exact observed choices; discovery confers no safety or action authority."""
    if species is not None:
        _species(species)
    before = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=48)
    rows = [row for row in _rows(before) if _living(row)
            and row['type'] in ({species} if species else SPECIES)]
    rows.sort(key=lambda row: (math.dist(threats.position(before.player), threats.position(row)), row['uuid']))
    selected = []
    for row in rows:
        blockers = []
        try:
            _safety(before, 12, row)
            _species_policy(before, row, station=False)
        except SkillError as exc:
            blockers.append(exc.reason)
        selected.append({'uuid': row['uuid'], 'entity_id': row['entity_id'], 'species': row['type'],
                         'health': row['health'], 'blockers': blockers})
    return runtime.result('combat_goals.discover_mobs', [before], mobs=selected,
        scope='complete_currently_loaded_entity_snapshot_radius_48',
        attack_station_verified=False, all_world_mobs_absent=False)


def defeat_nearby(runtime, species, *, max_targets=1, max_actions=32,
                  max_search_steps=16, max_walk_distance=128, timeout_seconds=120, min_health=12):
    _species(species)
    require(type(max_targets) is int and 1 <= max_targets <= 64, 'invalid_mob_target_budget')
    hunt = _Hunt(runtime, max_actions, timeout_seconds, max_search_steps, max_walk_distance, min_health)
    try:
        while len(hunt.finished) < max_targets:
            observation = hunt.observe()
            target = hunt.select(observation, species)
            if target is None:
                hunt.search(observation, species)
            else:
                hunt.defeat(observation, target)
        final = hunt.observe()
        return hunt.rt.result('combat_goals.defeat_nearby', [final], species=species,
            defeated_targets=[{'entity_id': i, 'uuid': u, 'species': s} for i, u, s in sorted(hunt.finished)],
            target_dead_observed=True, damage_attributed_to_action=False, goal_completed=True)
    except SkillError as exc:
        return hunt.rt.stopped(exc)


def _stable_total(hunt, observation, item_id, count):
    previous = observation
    samples = []
    for _ in range(16):
        hunt.rt.sleeper(.05)
        current = hunt.rt.observe()
        if current.tick > previous.tick and inventory.count(current, item_id) >= count:
            samples.append(current)
            if len(samples) == 2:
                return samples
        else:
            samples = []
        previous = current
    raise SkillError('mob_inventory_total_not_stable')


def hunt_resource(runtime, item_id, *, count=1, max_targets=16, max_actions=256,
                  max_search_steps=32, max_walk_distance=256, timeout_seconds=600, min_health=12):
    """Meet an actual inventory total through dynamically observed drops and mobs.

    Zero-drop kills are allowed by vanilla loot randomness, not treated as
    acquisition. They consume the target budget, and are never attacked again.
    """
    require(item_id in MOB_DROPS, 'unsupported_mob_drop_resource')
    require(type(count) is int and 1 <= count <= 2304, 'invalid_mob_inventory_total')
    require(type(max_targets) is int and 1 <= max_targets <= 64, 'invalid_mob_target_budget')
    hunt = _Hunt(runtime, max_actions, timeout_seconds, max_search_steps, max_walk_distance, min_health)
    initial = None
    try:
        while True:
            before = hunt.observe()
            have = inventory.count(before, item_id)
            if initial is None:
                initial = have
            if have >= count:
                confirmed = _stable_total(hunt, before, item_id, count)
                return hunt.rt.result('combat_goals.hunt_resource', confirmed, item_id=item_id,
                    requested_total=count, actual_total=inventory.count(confirmed[-1], item_id),
                    inventory_delta=inventory.count(confirmed[-1], item_id) - initial,
                    defeated_targets=len(hunt.finished), goal_completed=True,
                    evidence_kind='client_observed_inventory_total', causal_drop_attribution=False)
            drops = resources._drops(before, item_id)
            if drops:
                _safety(before, min_health)
                require(hunt.rt.walk_remaining > 0, 'mob_walk_budget_exhausted')
                result = resources._collect(hunt.rt, item_id, minimum=1, max_targets=1,
                                            max_steps=max(1, min(64, int(hunt.rt.walk_remaining))), baseline=before)
                hunt.rt.require_success(result)
                continue
            require(len(hunt.finished) < max_targets, 'mob_resource_target_budget_exhausted')
            target = hunt.select(before, MOB_DROPS[item_id])
            if target is None:
                hunt.search(before, MOB_DROPS[item_id])
                continue
            baseline = before
            hunt.defeat(before, target)
            # Read-only waiting allows actual drops or auto-pickup to become
            # visible after a verified death. Missing drops remain missing.
            for _ in range(32):
                hunt.rt.sleeper(.05)
                after = hunt.observe()
                if inventory.count(after, item_id) > inventory.count(baseline, item_id):
                    break
                if resources._drops(after, item_id):
                    break
    except SkillError as exc:
        return hunt.rt.stopped(exc)


# Supply asks for the same inventory-total semantic goal.
acquire_mob_drops = hunt_resource
