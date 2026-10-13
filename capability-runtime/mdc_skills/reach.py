"""Loaded-terrain approach, real face interaction and exact observed menu goals."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import sys

from .core import SkillError, require

_NAV = Path(__file__).resolve().parents[2] / 'navigation-controller'
if str(_NAV) not in sys.path:
    sys.path.insert(0, str(_NAV))
from navigation_controller.planner import plan, PlanConfig
from navigation_controller.terrain import Block, Cell, TerrainGrid, TerrainError

FACES = {'up': (0, 1, 0), 'down': (0, -1, 0), 'north': (0, 0, -1),
         'south': (0, 0, 1), 'east': (1, 0, 0), 'west': (-1, 0, 0)}


@dataclass(frozen=True)
class _Stamp:
    generation: str
    dimension: str
    tick: int

    def same_world(self, other):
        return (self.generation, self.dimension) == (other.generation, other.dimension)


def coordinate(target):
    require(isinstance(target, dict) and all(type(target.get(k)) is int for k in ('x', 'y', 'z')),
            'integer_block_coordinate_required')
    require(all(abs(target[k]) <= 30_000_000 for k in ('x', 'y', 'z')), 'coordinate_out_of_bounds')
    return {k: target[k] for k in ('x', 'y', 'z')}


def block_at(observation, target):
    target = coordinate(target)
    terrain = observation.terrain
    require(isinstance(terrain, dict) and terrain.get('complete') is True, 'complete_terrain_required')
    world = observation.state.get('world', {})
    require(terrain.get('world_generation') == world.get('world_generation')
            and terrain.get('dimension') == world.get('dimension')
            and terrain.get('world_generation') == observation.context[0]
            and terrain.get('dimension') == observation.context[1], 'terrain_context_mismatch')
    cells = [c for c in terrain.get('cells', []) if all(c.get(k) == target[k] for k in target)]
    require(len(cells) == 1, 'target_cell_not_uniquely_observed')
    cell = cells[0]
    require(cell.get('status') == 'loaded' and cell.get('known') is True
            and cell.get('id_truncated') is False and cell.get('properties_truncated') is False
            and isinstance(cell.get('properties'), dict), 'target_cell_unknown')
    return cell


def _grid(observation):
    terrain = observation.terrain
    require(isinstance(terrain, dict) and terrain.get('complete') is True, 'complete_terrain_required')
    world = observation.state['world']
    require(terrain.get('world_generation') == world.get('world_generation')
            and terrain.get('dimension') == world.get('dimension'), 'terrain_context_mismatch')
    require(type(terrain.get('source_tick')) is int and type(terrain.get('last_tick')) is int,
            'terrain_original_tick_required')
    require(isinstance(terrain.get('scan_generation'), str), 'terrain_scan_identity_required')
    require(type(terrain.get('capture_started_mono')) in (int, float), 'terrain_original_capture_required')
    stamp = _Stamp(world['world_generation'], world['dimension'], world['game_time'])
    # Reuse the baseline conservative geometric cell parser and A*, without
    # falsifying dimension identity to its historical Overworld-only WorldStamp.
    parsed = []
    extra_floors = {'minecraft:obsidian', 'minecraft:end_stone', 'minecraft:netherrack',
                    'minecraft:blackstone', 'minecraft:basalt', 'minecraft:polished_blackstone',
                    'minecraft:end_stone_bricks', 'minecraft:purpur_block', 'minecraft:purpur_pillar', 'minecraft:glass', 'minecraft:glowstone', 'minecraft:sea_lantern', 'minecraft:quartz_block'}
    for cell in terrain.get('cells', []):
        # Exact same baseline shape/fluid/hazard checks, with explicitly supported
        # dry full-cube native-dimension floors in this opt-in adapter only.
        candidate = dict(cell)
        block_id=candidate.get('id','')
        shape_floor=block_id.startswith('minecraft:') and (block_id.endswith(('_planks','_log','_wood','_stem','_hyphae')) or block_id in {'minecraft:bamboo_block','minecraft:stripped_bamboo_block','minecraft:crafting_table','minecraft:furnace','minecraft:blast_furnace','minecraft:smoker'})
        if block_id in extra_floors or shape_floor:
            candidate['id'] = 'minecraft:stone'
        parsed_cell=Cell.parse(candidate)
        # Explicit vanilla top-tread supports. A bottom slab's half-height surface
        # is never promoted to an integer floor. Partial stair stands only allow cardinal edges.
        properties=candidate.get('properties',{})
        block_id=cell.get('id','')
        stair=(block_id.startswith('minecraft:') and block_id.endswith('_stairs')
               and properties.get('facing') in ('north','south','east','west')
               and properties.get('half') in ('top','bottom')
               and properties.get('shape') in ('straight','inner_left','inner_right','outer_left','outer_right')
               and properties.get('waterlogged')=='false')
        slab=(block_id.startswith('minecraft:') and block_id.endswith('_slab')
              and properties.get('type') in ('top','double') and properties.get('waterlogged')=='false')
        if stair or slab:
            trusted=dict(candidate);trusted.update(id='minecraft:stone',full_top_support=True,collision_bounds=[0,0,0,1,1,1])
            support=Cell.parse(trusted).support
            # Preserve original actual geometry; only known top-tread/maxY=1 shapes qualify.
            bounds=cell.get('collision_bounds')
            support=support and isinstance(bounds,list) and len(bounds)==6 and bounds[4]==1
            parsed_cell=Cell(parsed_cell.position,False,support,stair and properties.get('half')=='bottom')
        parsed.append(parsed_cell)
    require(len({cell.position for cell in parsed}) == len(parsed), 'duplicate_terrain_cell')
    return TerrainGrid(stamp, terrain['scan_generation'], Block.parse(terrain['origin']),
                       terrain['radius'], terrain['vertical'], terrain['source_tick'],
                       terrain['last_tick'], terrain['capture_started_mono'],
                       {cell.position: cell for cell in parsed}, True), stamp


def _arrived(player, goal):
    velocity = player.get('velocity', {})
    values = [player.get(k) for k in ('x', 'y', 'z')] + [velocity.get(k) for k in ('x', 'z')]
    return (all(type(v) in (float, int) and math.isfinite(v) for v in values)
            and math.hypot(player['x'] - goal['x'], player['z'] - goal['z']) <= .23
            and abs(player['y'] - goal['y']) <= .15 and player.get('on_ground') is True
            and math.hypot(velocity['x'], velocity['z']) <= .08)


def navigate(runtime, goal, *, max_steps=128):
    """Navigate one bounded loaded local route. No unexplored/global path claim."""
    goal = coordinate(goal)
    require(type(max_steps) is int and 1 <= max_steps <= 128, 'invalid_navigation_budget')
    before = runtime.observe(terrain=True)
    target = {'x': goal['x'] + .5, 'y': goal['y'], 'z': goal['z'] + .5}
    if _arrived(before.player, target):
        return runtime.result('reach.navigate', [before], goal=target, already_arrived=True)
    try:
        grid, stamp = _grid(before)
        start = Block(*(math.floor(before.player[k]) for k in ('x', 'y', 'z')))
        route = plan(grid, start, Block.parse(goal), stamp, runtime.clock(),
                     PlanConfig(max_path_steps=max_steps))
    except (TerrainError, KeyError, TypeError, ValueError) as exc:
        raise SkillError('navigation_observation_invalid:' + str(exc)) from None
    require(route.route is not None, 'navigation_' + route.reason)
    points = [{'x': p.x + .5, 'y': p.y, 'z': p.z + .5} for p in route.route.nodes[1:]]
    # Within the same cell, move to its center using the same confirmed safe cell.
    if not points:
        points = [target]
    return runtime.execute('reach.navigate', {'op': 'action', 'action': 'follow_path',
                           'waypoints': points, 'capability_route': True, 'timeout_ms': min(60000, 3000 + 1800 * len(points))},
                           lambda old, new: _arrived(new.player, target), before=before)


def interact(runtime, target, *, face='up', expected_block_id=None, expected_menu_class=None,
             expected_properties=None, verify=None, hotbar_slot=None, stationary_menu=False,
             expected_block_properties=None, expected_open_menu_class=None):
    """Click a real visible block face once, then require a caller-defined semantic change."""
    target = coordinate(target)
    require(face in FACES, 'invalid_face')
    require(expected_menu_class is not None or callable(verify), 'interaction_semantic_goal_required')
    if stationary_menu:
        require(runtime.scoped_profile('interact_block') == 'block-menu-v1', 'block_menu_profile_unavailable')
        require(expected_block_id is not None and type(expected_block_properties) is dict
                and expected_open_menu_class is not None, 'stationary_menu_expectations_required')
        before = runtime.observe()
        require(before.state.get('screen_open') is False
                and before.state.get('menu', {}).get('container_id') == 0
                and before.state.get('menu', {}).get('carried', {}).get('empty') is True,
                'stationary_menu_requires_closed_empty_inventory')
        selected = before.player.get('selected_slot')
        require(hotbar_slot is None or hotbar_slot == selected, 'stationary_menu_selection_change_forbidden')
        held = next((v for v in before.player.get('inventory', []) if v.get('slot') == selected), {})
        require(held.get('empty') is True and before.player.get('offhand', {}).get('empty') is True,
                'stationary_menu_empty_hands_required')
        # These are only expectations. Native target/geometry capture is the sole admission authority.
        command = {'op': 'action', 'action': 'interact_block', 'target': target, 'face': face,
            'expected_block_id': expected_block_id, 'expected_block_properties': expected_block_properties,
            'expected_open_menu_class': expected_open_menu_class, 'timeout_ms': 3000}
        return runtime.execute('reach.interact', command, verify, before=before, allow_menu=True)
    before = runtime.observe(terrain=True)
    cell = block_at(before, target)
    if expected_block_id is not None:
        require(cell['id'] == expected_block_id, 'interaction_target_changed')
    eye = before.player.get('eye_position')
    reach = before.player.get('block_interaction_range')
    require(isinstance(eye, dict) and type(reach) in (int, float) and 0 < reach <= 64,
            'interaction_reach_observation_required')
    point = {k: target[k] + .5 + FACES[face][i] * .5 for i, k in enumerate(('x', 'y', 'z'))}
    require(math.dist([eye[k] for k in point], list(point.values())) <= reach, 'interaction_out_of_reach')
    command = {'op': 'action', 'action': 'interact_block', 'target': target, 'face': face,
               'expected_block_id': cell['id'], 'expected_block_properties': cell['properties'],
               'timeout_ms': 3000}
    if hotbar_slot is not None:
        command['hotbar_slot'] = hotbar_slot
    def verified(old, new):
        if expected_menu_class is not None:
            menu = new.state.get('menu', {})
            if not (menu.get('menu_class', '').split('.')[-1] == expected_menu_class.split('.')[-1]
                    and menu.get('container_id') != old.state.get('menu', {}).get('container_id')
                    and menu.get('slots_truncated') is False):
                return False
        if expected_properties is not None:
            try:
                updated = block_at(new, target)
            except SkillError:
                return False
            if not all(updated['properties'].get(k) == v for k, v in expected_properties.items()):
                return False
        return verify(old, new) if verify is not None else True
    return runtime.execute('reach.interact', command, verified, before=before, allow_menu=True)


def close_menu(runtime):
    before = runtime.observe(allow_menu=True)
    menu = before.state.get('menu', {})
    require(menu.get('carried', {}).get('empty') is True, 'cursor_must_be_empty_before_close')
    if before.state.get('screen_open') is False:
        return runtime.result('reach.close_menu', [before], already_closed=True)
    return runtime.execute('reach.close_menu', {'op': 'action', 'action': 'close_menu',
                           'container_id': menu['container_id'], 'expected_menu_state_id': menu['state_id'],
                           'expected_carried': menu['carried'], 'timeout_ms': 3000},
                           lambda old, new: new.state.get('screen_open') is False
                           and new.state.get('menu', {}).get('container_id') == 0
                           and new.state['menu'].get('carried', {}).get('empty') is True,
                           before=before, allow_menu=True)
