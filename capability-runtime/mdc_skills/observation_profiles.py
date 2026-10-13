"""Small fresh read profiles for one dry-flat segment, never passage authority.

The first state is only a sizing proposal. Only the second, fresh terrain
Observation can be returned for existing standable/safe_edge/native checks.
This module does not dispatch, retry, re-clock, or manufacture observations.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .core import require

_AXES = ('x', 'y', 'z')
# Native MovementBudget inflates the actual AABB by .56 horizontally. Include
# PathSteering's .23 arrival tolerance and the reviewed .07 coast allowance too.
_HORIZONTAL_MARGIN = .56 + .23 + .07
_HEIGHT_EPSILON = 1e-7


@dataclass(frozen=True)
class _Profile:
    origin: tuple[int, int, int]
    radius: int
    vertical: int
    minimum: tuple[int, int, int]
    maximum: tuple[int, int, int]

    def cells(self):
        low, high = self.minimum, self.maximum
        return ((x, y, z) for x in range(low[0], high[0] + 1)
                for y in range(low[1], high[1] + 1)
                for z in range(low[2], high[2] + 1))


def _vector(value, reason):
    require(type(value) is dict and set(value) == set(_AXES), reason)
    values = tuple(value[key] for key in _AXES)
    require(all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 30_000_000
                for v in values), reason)
    return values


def _profile(observation, point):
    """Conservative closed-cell swept AABB and minimal supported centered cube."""
    target = _vector(point, 'flat_segment_invalid_point')
    player = observation.player
    require(isinstance(player, dict), 'flat_segment_player_missing')
    position = _vector({key: player.get(key) for key in _AXES}, 'flat_segment_invalid_position')
    require(player.get('on_ground') is True, 'flat_segment_ground_required')
    require(abs(position[1] - target[1]) <= _HEIGHT_EPSILON,
            'flat_segment_same_height_required')
    origin, end = tuple(map(math.floor, position)), tuple(map(math.floor, target))
    require(origin[1] == end[1] and abs(origin[0]-end[0]) + abs(origin[2]-end[2]) <= 1,
            'flat_segment_one_cardinal_cell_required')
    box = player.get('bounding_box')
    require(type(box) is dict and set(box) == {'min', 'max'}, 'flat_segment_body_unknown')
    low = _vector(box['min'], 'flat_segment_body_unknown')
    high = _vector(box['max'], 'flat_segment_body_unknown')
    require(all(a < b for a, b in zip(low, high))
            and low[0] <= position[0] <= high[0] and low[2] <= position[2] <= high[2]
            and abs(low[1] - position[1]) <= _HEIGHT_EPSILON,
            'flat_segment_body_unknown')
    delta = tuple(target[i] - position[i] for i in range(3))
    # Translation preserves irregular/asymmetric observed bodies; no .5 center
    # or conventional player width/height is assumed. Native uses closed max
    # block coordinates, so exact upper integer faces are conservatively kept.
    minimum = tuple(math.floor(min(low[i], low[i] + delta[i])
                               - (_HORIZONTAL_MARGIN if i != 1 else 0)) for i in range(3))
    maximum = tuple(math.floor(max(high[i], high[i] + delta[i])
                               + (_HORIZONTAL_MARGIN if i != 1 else 0)) for i in range(3))
    minimum = (minimum[0], min(minimum[1], origin[1], end[1]) - 1, minimum[2])
    radius = max(1, *(abs(bound[i] - origin[i]) for bound in (minimum, maximum) for i in (0, 2)))
    vertical = max(2, abs(minimum[1]-origin[1]), abs(maximum[1]-origin[1]))
    require(radius <= 8 and vertical <= 8, 'flat_segment_observation_bounds_exceeded')
    require(all(abs(v) <= 30_000_000 for bounds in (minimum, maximum) for v in bounds),
            'flat_segment_observation_bounds_exceeded')
    return _Profile(origin, radius, vertical, minimum, maximum)


def _identity(observation):
    state = observation.state
    require(isinstance(state, dict), 'flat_segment_context_missing')
    world, player, action = (state.get(key) for key in ('world', 'player', 'client_action'))
    require(all(isinstance(value, dict) for value in (world, player, action)), 'flat_segment_context_missing')
    context = (world.get('world_generation'), world.get('dimension'), player.get('uuid'), action.get('action_session'))
    require(all(isinstance(value, str) and value for value in context)
            and context == observation.context and player.get('dimension') == context[1],
            'flat_segment_context_missing')
    guard = world.get('navigation_guard')
    require(isinstance(guard, dict) and type(guard.get('schema_version')) is int and guard['schema_version'] == 1
            and type(guard.get('epoch')) is int and 0 <= guard['epoch'] <= 2**53-1
            and guard.get('rebind_ready') is True and type(guard.get('stable_ticks')) is int
            and guard['stable_ticks'] == 3 and type(guard.get('fresh_binding_required')) is bool,
            'flat_segment_native_epoch_unknown')
    return context, guard['epoch']


def _known_collision(cell):
    if not (cell.get('status') == 'loaded' and cell.get('known') is True
            and cell.get('collision_known') is True and cell.get('id_truncated') is False
            and cell.get('properties_truncated') is False and isinstance(cell.get('properties'), dict)
            and isinstance(cell.get('id'), str) and cell['id']
            and type(cell.get('air')) is bool and type(cell.get('collision_empty')) is bool
            and type(cell.get('full_top_support')) is bool and cell.get('fluid_truncated') is False
            and isinstance(cell.get('fluid'), str) and cell['fluid'] and type(cell.get('fluid_source')) is bool
            and isinstance(cell.get('hazards'), list) and all(isinstance(v, str) for v in cell['hazards'])
            and cell.get('hazards_exhaustive') is False):
        return False
    bounds = cell.get('collision_bounds')
    if cell['collision_empty']:
        return bounds is None or bounds == []
    return (isinstance(bounds, list) and len(bounds) == 6
            and all(type(v) in (int, float) and math.isfinite(v) for v in bounds)
            and all(bounds[i] < bounds[i+3] for i in range(3)))


def _coverage(observation, profile, requested):
    terrain = observation.terrain
    require(isinstance(terrain, dict) and terrain.get('complete') is True
            and terrain.get('historical_survey', False) is False, 'flat_segment_complete_fresh_terrain_required')
    require(terrain.get('world_generation') == observation.context[0]
            and terrain.get('dimension') == observation.context[1], 'flat_segment_terrain_context_changed')
    origin = _vector(terrain.get('origin'), 'flat_segment_terrain_origin_invalid')
    require(all(type(v) is int for v in origin), 'flat_segment_terrain_origin_invalid')
    require(type(terrain.get('radius')) is int and terrain['radius'] == requested.radius
            and type(terrain.get('vertical')) is int and terrain['vertical'] == requested.vertical,
            'flat_segment_terrain_profile_changed')
    for bounds in (profile.minimum, profile.maximum):
        require(abs(bounds[0]-origin[0]) <= requested.radius and abs(bounds[2]-origin[2]) <= requested.radius
                and abs(bounds[1]-origin[1]) <= requested.vertical, 'flat_segment_fresh_envelope_outside_scan')
    cells = terrain.get('cells')
    require(isinstance(cells, list) and len(cells) <= (2*requested.radius+1)**2*(2*requested.vertical+1),
            'flat_segment_terrain_cells_invalid')
    by_position = {}
    for cell in cells:
        require(isinstance(cell, dict), 'flat_segment_terrain_cells_invalid')
        pos = tuple(cell.get(key) for key in _AXES)
        require(all(type(v) is int for v in pos), 'flat_segment_terrain_cells_invalid')
        require(pos not in by_position, 'flat_segment_duplicate_cell')
        by_position[pos] = cell
    for pos in profile.cells():
        require(pos in by_position, 'flat_segment_required_cell_missing')
        require(_known_collision(by_position[pos]), 'flat_segment_required_collision_unknown')


def observe_flat_segment(runtime, point, *, entity_radius=48):
    """Return a fresh, fully observed envelope for one same-Y cardinal-cell step.

    This proves only the read's coverage and metadata, not that the segment is
    passable. Keep existing safe_edge, standable, threat, and native guards.
    Unknown/changed geometry fails closed without another read or any action.
    """
    require(type(entity_radius) is int and 1 <= entity_radius <= 128, 'flat_segment_entity_radius_invalid')
    _vector(point, 'flat_segment_invalid_point')  # Invalid proposals need no read.
    seed = runtime.observe(terrain=False, entity_radius=entity_radius)
    context = _identity(seed)
    proposal = _profile(seed, point)
    fresh = runtime.observe(terrain=True, radius=proposal.radius, vertical=proposal.vertical,
                            entity_radius=entity_radius)
    require(_identity(fresh) == context, 'flat_segment_context_or_epoch_changed')
    actual = _profile(fresh, point)
    _coverage(fresh, actual, proposal)
    # Never replace fresh.captured_at with the proposal time or time of return.
    age = runtime.clock() - fresh.captured_at
    require(type(runtime.max_age) in (int, float) and 0 < runtime.max_age <= .8
            and 0 <= age <= runtime.max_age, 'flat_segment_fresh_observation_stale')
    return fresh
