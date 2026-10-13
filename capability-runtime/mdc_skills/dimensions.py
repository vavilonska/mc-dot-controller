"""Bounded portal and End operations backed by actual native interactions.

Prepared/loaded local routes only. There is no invented stronghold discovery,
world-wide crystal absence, flight controller, respawn ritual, or victory from a
missing dragon. Every write is one guarded runtime action with an observed goal.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from .core import Outcome, SkillError, require
from . import threats
from .reach import block_at, coordinate, interact, navigate

OVERWORLD, NETHER, END = 'minecraft:overworld', 'minecraft:the_nether', 'minecraft:the_end'
AIR = frozenset(('minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'))


def _dimension(observation):
    dimension = observation.state.get('world', {}).get('dimension')
    require(dimension in (OVERWORLD, NETHER, END), 'unsupported_dimension')
    return dimension


def _count(observation, item):
    p = observation.player
    require(p.get('inventory_truncated') is False and isinstance(p.get('inventory'), list),
            'complete_inventory_required')
    stacks = p['inventory']
    for stack in stacks:
        require(type(stack.get('count')) is int and stack['count'] >= 0, 'inventory_count_unknown')
    return sum(s['count'] for s in stacks if s.get('id') == item)


def _select(runtime, item, slot):
    from .inventory import ensure_hotbar
    return runtime.require_success(ensure_hotbar(runtime, item, hotbar_slot=slot))


def _offset(base, x=0, y=0, z=0):
    return dict(x=base['x'] + x, y=base['y'] + y, z=base['z'] + z)


def ignite_nether_portal(runtime, interior_base, *, axis='x', width=2, height=3, hotbar_slot=0):
    """Ignite an observed complete obsidian frame; never build/fix a guessed frame."""
    base = coordinate(interior_base)
    require(axis in ('x', 'z'), 'portal_axis_x_or_z')
    require(type(width) is int and 2 <= width <= 4 and type(height) is int and 3 <= height <= 4,
            'local_portal_dimensions_width2_to4_height3_to4')
    before = runtime.observe(terrain=True, radius=6, vertical=4)
    require(_dimension(before) in (OVERWORLD, NETHER), 'nether_portal_wrong_dimension')
    point = lambda u, v: _offset(base, x=u if axis == 'x' else 0, y=v, z=u if axis == 'z' else 0)
    inside = [point(u, v) for u in range(width) for v in range(height)]
    if all(block_at(before, c)['id'] == 'minecraft:nether_portal'
           and block_at(before, c)['properties'].get('axis') == axis for c in inside):
        return runtime.result('dimensions.ignite_nether_portal', [before], outcome='portal_already_active')
    for u in range(width):
        for v in (-1, height):
            require(block_at(before, point(u, v))['id'] == 'minecraft:obsidian', 'portal_obsidian_frame_required')
    for u in (-1, width):
        for v in range(height):
            require(block_at(before, point(u, v))['id'] == 'minecraft:obsidian', 'portal_obsidian_frame_required')
    require(all(block_at(before, c)['id'] in AIR for c in inside), 'portal_interior_not_empty')
    ready = _select(runtime, 'minecraft:flint_and_steel', hotbar_slot)
    hotbar_slot = ready.player['selected_slot']
    def verified(_, after):
        try:
            return all(block_at(after, c)['id'] == 'minecraft:nether_portal'
                       and block_at(after, c)['properties'].get('axis') == axis for c in inside)
        except SkillError:
            return False
    # Interact takes its own fresh guard-bound snapshot, never reuses the earlier sample.
    live = runtime.observe(terrain=True, radius=6, vertical=4)
    require(live.context == before.context, 'portal_ignition_context_changed')
    for u in range(width):
        for v in (-1, height):
            require(block_at(live, point(u, v))['id'] == 'minecraft:obsidian', 'portal_frame_changed')
    for u in (-1, width):
        for v in range(height):
            require(block_at(live, point(u, v))['id'] == 'minecraft:obsidian', 'portal_frame_changed')
    for c in inside:
        require(block_at(live, c)['id'] in AIR, 'portal_interior_changed')
    support = block_at(live, point(0, -1))
    require(support['id'] == 'minecraft:obsidian', 'portal_ignition_support_changed')
    return runtime.execute('dimensions.ignite_nether_portal',
        {'op': 'action', 'action': 'interact_block', 'target': point(0, -1), 'face': 'up',
         'expected_block_id': support['id'], 'expected_block_properties': support['properties'],
         'hotbar_slot': hotbar_slot, 'timeout_ms': 3000}, verified, before=live)


def end_portal_frames(interior_corner):
    """Twelve inward-facing vanilla frames around the caller's exact 3x3 interior."""
    base = coordinate(interior_corner)
    result = []
    for i in range(3):
        result.extend([(_offset(base, x=i, z=-1), 'south'),
                       (_offset(base, x=i, z=3), 'north'),
                       (_offset(base, x=-1, z=i), 'east'),
                       (_offset(base, x=3, z=i), 'west')])
    return result


def activate_end_portal(runtime, interior_corner, *, max_eyes=12, hotbar_slot=0):
    """Fill only a verified inward-facing 12-frame ring; observe all nine active portal cells."""
    base = coordinate(interior_corner)
    require(type(max_eyes) is int and 1 <= max_eyes <= 12, 'eye_budget_1_to_12')
    frames = end_portal_frames(base)
    before = runtime.observe(terrain=True, radius=6, vertical=2)
    require(_dimension(before) == OVERWORLD, 'end_portal_activation_requires_overworld')
    # Avoid unexpected transition during the last eye insertion.
    px, py, pz = threats.position(before.player)
    require(not (base['x'] - .3 <= px <= base['x'] + 3.3
                 and base['z'] - .3 <= pz <= base['z'] + 3.3 and abs(py-base['y']) < 2),
            'stand_outside_end_portal_before_activation')
    missing = []
    for cell, facing in frames:
        value = block_at(before, cell)
        require(value['id'] == 'minecraft:end_portal_frame'
                and value['properties'].get('facing') == facing, 'complete_inward_end_frames_required')
        eye = value['properties'].get('eye')
        require(eye in ('true', 'false'), 'end_frame_eye_property_unknown')
        if eye == 'false':
            missing.append(cell)
    require(len(missing) <= max_eyes, 'end_portal_eye_budget_exhausted')
    require(_count(before, 'minecraft:ender_eye') >= len(missing), 'insufficient_ender_eyes')
    ids, observations = [], [before]
    if missing:
        ready = _select(runtime, 'minecraft:ender_eye', hotbar_slot)
        hotbar_slot = ready.player['selected_slot']
    for cell in missing:
        # No guessed approach: caller must be within actual block reach, otherwise stop.
        result = interact(runtime, cell, expected_block_id='minecraft:end_portal_frame',
                          expected_properties={'eye': 'true'},
                          verify=lambda old, new, c=cell: block_at(new, c)['properties'].get('eye') == 'true',
                          hotbar_slot=hotbar_slot)
        ids.extend(result.request_ids)
        if not result.ok:
            return result
        observations.append(runtime.require_success(result))
    after = runtime.observe(terrain=True, radius=6, vertical=2)
    require(all(block_at(after, _offset(base, x=x, z=z))['id'] == 'minecraft:end_portal'
                for x in range(3) for z in range(3)), 'active_end_portal_not_observed')
    return runtime.result('dimensions.activate_end_portal', observations + [after],
                          action_request_ids=ids, eyes_inserted=len(missing), outcome='nine_portal_cells_observed')


def _portal_corridor(before, target):
    """At most two blocks of straight, flat, full-footprint dry supported entry."""
    start = threats.position(before.player)
    end = (target['x'] + .5, target['y'], target['z'] + .5)
    require(before.player.get('on_ground') is True and abs(start[1] - end[1]) <= .05,
            'portal_flat_supported_entry_required')
    require(math.dist(start, end) <= 2, 'approach_portal_within_two_blocks_first')
    # Entire swept rectangle is conservative, including diagonal side corners.
    for x in range(math.floor(min(start[0], end[0]) - .31), math.floor(max(start[0], end[0]) + .31) + 1):
        for z in range(math.floor(min(start[2], end[2]) - .31), math.floor(max(start[2], end[2]) + .31) + 1):
            for dy in (-1, 0, 1):
                c = block_at(before, {'x': x, 'y': target['y'] + dy, 'z': z})
                require(c.get('collision_known') is True and c.get('fluid') == 'minecraft:empty'
                        and c.get('fluid_truncated') is False and c.get('hazards') == [], 'portal_entry_hazard_or_unknown')
                require(c.get('full_top_support') is True if dy == -1 else c.get('collision_empty') is True,
                        'portal_entry_support_or_collision')
    return {'x': end[0], 'y': end[1], 'z': end[2]}


def enter_portal(runtime, portal_cell, destination, *, timeout_ms=10000):
    """Enter a specific observed portal; only exact expected dimension can complete.

    Core specially admits an exact known world-transition cancellation with confirmed
    input release. UUID, gateway and action sessions remain bound; unknowns never replay.
    Natural unsupported drops, credits screens and unobserved landing safety stop honestly.
    """
    require(type(timeout_ms) is int and 5000 <= timeout_ms <= 30000, 'portal_timeout_5000_to_30000')
    cell = coordinate(portal_cell)
    before = runtime.observe(terrain=True, radius=4, vertical=4)
    source = _dimension(before)
    transitions = {(OVERWORLD, NETHER): 'minecraft:nether_portal', (NETHER, OVERWORLD): 'minecraft:nether_portal',
                   (OVERWORLD, END): 'minecraft:end_portal', (END, OVERWORLD): 'minecraft:end_portal'}
    kind = transitions.get((source, destination))
    require(kind is not None, 'portal_dimension_pair_unsupported')
    require(block_at(before, cell)['id'] == kind, 'expected_portal_not_observed')
    point = _portal_corridor(before, cell)
    return runtime.execute('dimensions.enter_portal',
        {'op': 'action', 'action': 'follow_path', 'waypoints': [point], 'timeout_ms': timeout_ms},
        lambda old, new: _dimension(new) == destination and new.player.get('alive') is True
                and new.player.get('on_ground') is True
                and all(new.player.get(k) is False for k in threats.ENVIRONMENT_FLAGS),
        before=before, allowed_dimension=destination, max_samples=128, stable_samples=3)


def _chunk_loaded(observation, target_cell):
    rows = observation.state.get('nearby', {}).get('loaded_chunks')
    require(isinstance(rows, list) and len(rows) <= 81, 'loaded_chunk_observation_required')
    cx, cz = target_cell['x'] // 16, target_cell['z'] // 16
    found = [r for r in rows if r.get('x') == cx and r.get('z') == cz]
    require(len(found) == 1 and found[0].get('loaded') is True, 'target_chunk_not_observed_loaded')


def remove_crystal(runtime, target_uuid, *, hotbar_slot=0, min_health=12):
    """One safe-distance bow shot, verified by stable removal from the loaded observed area.

    This evidence proves local removal only. It does not attribute an explosion or
    kill, prove every world crystal absent, or equate bow release with crystal removal.
    Iron cages/other blocks are rechecked by the native ballistic-corridor gate.
    """
    before = runtime.observe(entity_radius=48)
    require(_dimension(before) == END, 'crystal_goal_requires_end')
    threats._health(before, min_health)
    target = threats.entity(before, target_uuid)
    require(target.get('type') == 'minecraft:end_crystal' and target.get('alive') is True,
            'live_end_crystal_required')
    distance = math.dist(threats.position(before.player), threats.position(target))
    require(12 <= distance <= 32, 'crystal_observation_station_12_to_32_blocks')
    target_cell = {k: math.floor(target[k]) for k in ('x', 'y', 'z')}
    _chunk_loaded(before, target_cell)
    _select(runtime, 'minecraft:bow', hotbar_slot)
    live = runtime.observe(entity_radius=48)
    require(live.context == before.context, 'crystal_context_changed')
    require(threats._same_target(target, live) is not None, 'crystal_no_longer_observed')
    require(math.dist(threats.position(before.player), threats.position(live.player)) <= .5, 'crystal_observer_moved')
    before = live
    command = threats._command(before, 'shoot_entity', target, 5000)
    command.update(draw_ticks=20, min_health=min_health)
    def verified(_, after):
        require(math.dist(threats.position(before.player), threats.position(after.player)) <= .5,
                'crystal_observer_moved')
        _chunk_loaded(after, target_cell)
        return threats._same_target(target, after) is None
    result = runtime.execute('dimensions.remove_crystal', command, verified, before=before,
                             max_samples=80, stable_samples=3)
    if result.ok:
        return Outcome(result.status, 'crystal_removed_from_loaded_observed_area', result.request_ids,
            {**result.evidence, 'target_uuid': target_uuid, 'outcome': 'local_removal_observed',
             'destruction_attributed_to_action': False, 'all_world_crystals_absent': False}, result.last_observation)
    return result


def open_crystal_cage(runtime, crystal_uuid, bars, *, max_blocks=8, hotbar_slot=None):
    """Mine caller-selected observed iron bars around one crystal; never hit the crystal."""
    from .resources import mine
    require(type(max_blocks) is int and 1 <= max_blocks <= 16, 'cage_budget_1_to_16')
    require(isinstance(bars, (list, tuple)) and 0 < len(bars) <= max_blocks, 'cage_block_budget_exhausted')
    targets = [coordinate(c) for c in bars]
    require(len({tuple(c.values()) for c in targets}) == len(targets), 'duplicate_cage_blocks')
    observation = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=48)
    require(_dimension(observation) == END, 'cage_goal_requires_end')
    crystal = threats.entity(observation, crystal_uuid)
    require(crystal.get('type') == 'minecraft:end_crystal', 'end_crystal_required')
    for target in targets:
        require(block_at(observation, target)['id'] == 'minecraft:iron_bars'
                and math.dist(threats.position(crystal), tuple(target[k]+.5 for k in ('x', 'y', 'z'))) <= 4,
                'observed_crystal_cage_bar_required')
    ids, observations = [], []
    for target in targets:
        live = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=48)
        threats._health(live, 12)
        require(threats._same_target(crystal, live) is not None, 'crystal_no_longer_observed')
        require(block_at(live, target)['id'] == 'minecraft:iron_bars', 'cage_block_changed')
        result = mine(runtime, target, hotbar_slot=hotbar_slot)
        ids.extend(result.request_ids)
        if not result.ok:
            return result
        observations.append(runtime.require_success(result))
    return runtime.result('dimensions.open_crystal_cage', observations,
        action_request_ids=ids, bars_removed=targets, crystal_uuid=crystal_uuid,
        outcome='selected_cage_bars_removed', firing_lane_confirmed=False)


def wait_dragon_phase(runtime, dragon_uuid, *, max_samples=80, min_health=12):
    """Bounded read-only wait for a visible living dragon in a safe perched phase."""
    require(type(max_samples) is int and 1 <= max_samples <= 128, 'phase_sample_budget_1_to_128')
    first, previous = None, None
    for _ in range(max_samples):
        observation = runtime.observe(entity_radius=48)
        require(_dimension(observation) == END, 'dragon_goal_requires_end')
        threats._health(observation, min_health)
        if first is None:
            first = observation
        require(observation.context == first.context, 'dragon_wait_context_changed')
        if previous is not None:
            require(observation.tick > previous.tick, 'dragon_wait_tick_not_advancing')
        previous = observation
        dragon = threats.entity(observation, dragon_uuid, required=False)
        if dragon is not None:
            require(dragon.get('type') == 'minecraft:ender_dragon', 'dragon_identity_required')
            if threats._dead(dragon):
                return runtime.result('dimensions.wait_dragon_phase', [observation], outcome='dragon_dead_observed')
            if dragon.get('phase_id') in (6, 7):
                return runtime.result('dimensions.wait_dragon_phase', [observation],
                                      phase_id=dragon['phase_id'], outcome='safe_perched_phase_observed')
        runtime.sleeper(.1)
    return Outcome('blocked', 'safe_dragon_phase_not_observed_within_budget', (),
                   {'server_confirmed': False, 'goal_completed': False}, previous)


@dataclass(frozen=True)
class CrystalGoal:
    uuid: str
    firing_station: dict | None = None
    cage_bars: tuple = ()
    cage_station: dict | None = None


def end_battle(runtime, dragon_uuid, *, crystals=(), max_strikes=64, max_phase_samples=80,
               min_health=12, bow_slot=0, weapon_slot=1, cage_tool_slot=2,
               dragon_station=None, exit_portal=None):
    """Execute a bounded explicit End battle plan: cage, shot, dragon phases/head, portal.

    Caller supplies loaded local safe stations and exact scoped crystal UUIDs. The
    native adapter enforces each-tick gaze/collateral/health/phase/head-ray checks.
    No flying-dragon attacks, unsafe towers, global routing or guaranteed victory.
    """
    require(type(max_strikes) is int and 1 <= max_strikes <= 256, 'dragon_strike_budget_1_to_256')
    require(isinstance(crystals, (list, tuple)) and len(crystals) <= 10, 'crystal_scope_maximum_ten')
    require(all(isinstance(goal, CrystalGoal) for goal in crystals), 'explicit_crystal_goals_required')
    require(len({goal.uuid for goal in crystals}) == len(crystals), 'duplicate_crystal_goal')
    before = runtime.observe(entity_radius=48)
    require(_dimension(before) == END, 'end_battle_requires_end')
    ids, observations, stages, damage_samples = [], [before], [], []
    def accept(result, stage):
        ids.extend(result.request_ids)
        observation = runtime.require_success(result)
        observations.append(observation)
        stages.append(stage)
        return observation
    for goal in crystals:
        if goal.cage_bars:
            if goal.cage_station is not None:
                accept(navigate(runtime, goal.cage_station), 'reach_cage_station')
            accept(open_crystal_cage(runtime, goal.uuid, goal.cage_bars,
                                    hotbar_slot=cage_tool_slot), 'open_selected_cage_bars')
        if goal.firing_station is not None:
            accept(navigate(runtime, goal.firing_station), 'reach_crystal_station')
        accept(remove_crystal(runtime, goal.uuid, hotbar_slot=bow_slot, min_health=min_health),
               'crystal_local_removal_observed')
    if dragon_station is not None:
        accept(navigate(runtime, dragon_station), 'reach_dragon_station')
    from .inventory import select_hotbar
    accept(select_hotbar(runtime, weapon_slot), 'select_dragon_weapon')
    dead = None
    for _ in range(max_strikes):
        phase = wait_dragon_phase(runtime, dragon_uuid, max_samples=max_phase_samples, min_health=min_health)
        if not phase.ok:
            return phase
        ready = accept(phase, 'dragon_phase_observed')
        target = threats.entity(ready, dragon_uuid)
        if threats._dead(target):
            dead = ready
            break
        result = threats.strike(runtime, dragon_uuid, min_health=min_health,
                                expected_dragon_phase=target['phase_id'])
        if not result.ok:
            return result
        after = accept(result, 'dragon_health_decreased')
        damage_samples.append({k: result.evidence.get(k) for k in (
            'target_initial_health', 'target_observed_health', 'observed_health_loss', 'target_dead_observed')})
        if threats._dead(threats.entity(after, dragon_uuid, required=False)):
            dead = after
            break
    if dead is None:
        return Outcome('failed', 'dragon_strike_budget_exhausted', tuple(ids),
                       {'stages': stages, 'goal_completed': False, 'server_confirmed': False}, observations[-1])
    # Dragon death animation takes time. An optional caller-selected portal is only
    # successful after actual block observation, never inferred from dragon loss.
    if exit_portal is not None:
        cell = coordinate(exit_portal)
        for _ in range(128):
            after = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=48)
            require(after.context == dead.context, 'end_battle_context_changed')
            try:
                active = block_at(after, cell)['id'] == 'minecraft:end_portal'
            except SkillError:
                active = False
            if active:
                observations.append(after)
                stages.append('exit_portal_observed')
                break
            runtime.sleeper(.1)
        else:
            return Outcome('blocked', 'dragon_dead_exit_portal_not_observed', tuple(ids),
                           {'dragon_dead_observed': True, 'server_confirmed': False}, after)
    return runtime.result('dimensions.end_battle', observations, action_request_ids=ids, stages=stages,
        outcome='dragon_dead_observed', dragon_uuid=dragon_uuid, damage_samples=damage_samples,
        scoped_crystals_removed=[g.uuid for g in crystals], all_world_crystals_absent=False,
        exit_portal_observed=exit_portal is not None, damage_attributed_to_action=False)


def discover_end_goals(runtime, *, max_targets=10, min_health=12):
    """Discover concrete loaded local End targets and an actionable observed subset.

    Missing terrain, range, inventory, phase and gaze constraints are individual
    blockers, never silently promoted into ready goals. The 48-block observation
    boundary is explicit; this is not a global crystal census or End-clear proof.
    """
    require(type(max_targets) is int and 1 <= max_targets <= 10, 'end_discovery_budget_1_to_10')
    before = runtime.observe(terrain=True, radius=4, vertical=2, entity_radius=48)
    require(_dimension(before) == END, 'end_discovery_requires_end')
    values = threats.entities(before)
    global_blockers = []
    try:
        threats._health(before, min_health)
    except SkillError as exc:
        global_blockers.append(exc.reason)
    if any(e.get('type') == 'minecraft:enderman' and e.get('alive') is True for e in values):
        global_blockers.append('enderman_gaze_unplanned')
    try:
        if _count(before, 'minecraft:bow') == 0:
            global_blockers.append('bow_missing')
        if sum(_count(before, kind) for kind in ('minecraft:arrow', 'minecraft:spectral_arrow', 'minecraft:tipped_arrow')) == 0:
            global_blockers.append('ammunition_missing')
    except SkillError as exc:
        global_blockers.append(exc.reason)
    candidates, dragons, ready = [], [], []
    cells = before.terrain.get('cells', []) if isinstance(before.terrain, dict) else []
    observed_crystals = sorted((e for e in values if e.get('type') == 'minecraft:end_crystal'
                               and e.get('alive') is True), key=lambda e: (math.dist(
                               threats.position(before.player), threats.position(e)), e.get('uuid', '')))
    for target in observed_crystals[:max_targets]:
        threats._identity(target)
        blockers = list(global_blockers)
        distance = math.dist(threats.position(before.player), threats.position(target))
        if not 12 <= distance <= 32:
            blockers.append('crystal_observation_station_12_to_32_blocks')
        try:
            _chunk_loaded(before, {k: math.floor(target[k]) for k in ('x', 'y', 'z')})
        except SkillError as exc:
            blockers.append(exc.reason)
        bars = []
        for cell in cells:
            if cell.get('id') == 'minecraft:iron_bars':
                coord = {k: cell.get(k) for k in ('x', 'y', 'z')}
                try:
                    certain = block_at(before, coord)
                    if math.dist(threats.position(target), tuple(coord[k]+.5 for k in ('x', 'y', 'z'))) <= 4:
                        bars.append(coord)
                except SkillError:
                    pass
        if bars:
            blockers.append('observed_cage_requires_explicit_opening_plan')
        selected = {'uuid': target['uuid'], 'entity_id': target['entity_id'], 'distance': distance,
                    'observed_cage_bars': bars, 'blockers': blockers, 'current_station_ready': not blockers,
                    'native_line_of_fire_validation_required': True}
        candidates.append(selected)
        if not blockers:
            ready.append(target['uuid'])
    for dragon in values:
        if dragon.get('type') != 'minecraft:ender_dragon':
            continue
        threats._identity(dragon)
        blockers = []
        if not threats._dead(dragon) and dragon.get('phase_id') not in (6, 7):
            blockers.append('safe_perched_phase_required')
        head = next((p for p in dragon.get('dragon_parts', []) if p.get('name') == 'head'), None)
        if head is None:
            blockers.append('dragon_head_geometry_missing')
        else:
            try:
                eye = threats.position(before.player.get('eye_position', {}))
                box = head['bounding_box']
                low, high = threats.position(box['min']), threats.position(box['max'])
                distance = math.sqrt(sum(max(a-p, 0, p-b)**2 for p, a, b in zip(eye, low, high)))
                if distance > 3:
                    blockers.append('dragon_head_out_of_melee_reach')
            except (KeyError, SkillError):
                blockers.append('dragon_head_geometry_missing')
        dragons.append({'uuid': dragon['uuid'], 'entity_id': dragon['entity_id'],
                        'phase_id': dragon.get('phase_id'), 'health': dragon.get('health'),
                        'blockers': blockers, 'dead_observed': threats._dead(dragon)})
    portals = []
    for c in cells:
        if c.get('id') == 'minecraft:end_portal':
            try:
                coordinate_value = coordinate(c)
                block_at(before, coordinate_value)
                portals.append(coordinate_value)
            except SkillError:
                pass
    return runtime.result('dimensions.discover_end_goals', [before], crystals=candidates,
        selected_crystal_uuids=ready, dragons=dragons, observed_exit_portal_cells=portals,
        global_blockers=global_blockers, observation_radius=48,
        omitted_by_target_budget=max(0, len(observed_crystals)-max_targets),
        all_world_crystals_absent=False, automatic_end_clear_ready=False)


def clear_observed_crystals(runtime, *, max_crystals=3, min_health=12, bow_slot=0):
    """Discover/select then really shoot the ready local crystal subset, never retry failures."""
    discovery = discover_end_goals(runtime, max_targets=max_crystals, min_health=min_health)
    selected = discovery.evidence['selected_crystal_uuids']
    require(bool(selected), 'no_observed_crystal_action_ready')
    ids, observations, removed = [], [discovery.last_observation], []
    for target_uuid in selected:
        result = remove_crystal(runtime, target_uuid, hotbar_slot=bow_slot, min_health=min_health)
        ids.extend(result.request_ids)
        if not result.ok:
            return result
        observations.append(runtime.require_success(result))
        removed.append(target_uuid)
    return runtime.result('dimensions.clear_observed_crystals', observations, action_request_ids=ids,
        removed_crystal_uuids=removed, selection='observed_ready_local_subset',
        all_world_crystals_absent=False, destruction_attributed_to_action=False)
