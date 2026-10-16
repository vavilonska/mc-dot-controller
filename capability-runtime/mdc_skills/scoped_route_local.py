"""Read-only bounded routing, composed from independently native-admitted segments.

Historical terrain proposes a complete route; it never grants movement authority. Every edge
uses the original Runtime owner, deadline and action ledger, with a fresh state
preflight and no retry after a non-successful segment.
"""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import math

from .core import Outcome, SkillError, require
from .reach import Block, Cell, TerrainError, coordinate

PROFILE = 'movement-local-segment-observed-v1'
SPATIAL_PROFILE = 'movement-local-segment-spatial-threat-v1'
SPATIAL_STOP_PROFILE = 'movement-local-segment-spatial-stop-v1'
SPATIAL_STOP_PROFILE_V2 = 'movement-local-segment-spatial-stop-v2'
MAX_EXPANSIONS = 2048
FLOORS = frozenset('minecraft:' + name for name in (
    'stone', 'cobblestone', 'dirt', 'grass_block', 'oak_planks', 'andesite',
    'granite', 'diorite', 'cobbled_deepslate', 'smooth_stone', 'stone_bricks', 'bricks'))
AIR = frozenset(('minecraft:air', 'minecraft:cave_air'))
CONTEXT_LEAVES = frozenset(('minecraft:oak_leaves', 'minecraft:birch_leaves'))
CONTEXT_BLOCKS = frozenset(('minecraft:barrel', 'minecraft:furnace')) | CONTEXT_LEAVES
_DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass(frozen=True)
class _RouteCell(Cell):
    # Context-only stations/foliage never acquire the support or clear roles.
    context: bool = False


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _source(player):
    require(all(_number(player.get(k)) for k in ('x', 'y', 'z')), 'route_local_pose_missing')
    x, y, z = (player[k] for k in ('x', 'y', 'z'))
    source = Block(math.floor(x), round(y), math.floor(z))
    require(-63 <= source.y <= 316, 'route_local_native_feet_bounds')
    require(abs(x-source.x-.5) <= .10 and abs(z-source.z-.5) <= .10
            and abs(y-source.y) <= 1e-7, 'route_local_centered_integer_origin_required')
    return source


def _point(block):
    return {'x': block.x+.5, 'y': block.y, 'z': block.z+.5}


def _inside(block, anchor, radius):
    return (abs(block.x-anchor.x) <= radius and abs(block.z-anchor.z) <= radius
            and abs(block.y-anchor.y) <= 2)


def _context_block(row):
    """Validate context block facts; exact class/friction/state remain native-owned."""
    bounds = row.get('collision_bounds')
    return (row.get('id') in CONTEXT_BLOCKS and row.get('status') == 'loaded'
            and row.get('known') is True and row.get('collision_known') is True
            and row.get('id_truncated') is False and row.get('fluid_truncated') is False
            and row.get('properties_truncated') is False and isinstance(row.get('properties'), dict)
            and row.get('fluid') == 'minecraft:empty' and row.get('fluid_source') is False
            and row.get('hazards') == [] and row.get('hazards_exhaustive') is False
            and row.get('air') is False and row.get('collision_empty') is False
            and row.get('full_top_support') is True and isinstance(bounds, list) and len(bounds) == 6
            and all(_number(value) for value in bounds) and bounds == [0, 0, 0, 1, 1, 1])


def _grid(observation, radius):
    """Parse actual cells without legacy slab, stair or extra-floor promotion."""
    terrain = observation.terrain
    require(isinstance(terrain, dict) and terrain.get('complete') is True, 'route_local_complete_terrain_required')
    world = observation.state.get('world', {})
    require(terrain.get('world_generation') == world.get('world_generation') == observation.context[0]
            and terrain.get('dimension') == world.get('dimension') == observation.context[1],
            'route_local_terrain_context_mismatch')
    require(type(terrain.get('source_tick')) is int and type(terrain.get('last_tick')) is int
            and 0 <= terrain['source_tick'] <= terrain['last_tick'] <= observation.tick,
            'route_local_terrain_ticks_invalid')
    require(isinstance(terrain.get('scan_generation'), str) and terrain['scan_generation']
            and _number(terrain.get('capture_started_mono')), 'route_local_terrain_provenance_missing')
    require(type(terrain.get('radius')) is int and terrain['radius'] == radius
            and type(terrain.get('vertical')) is int and terrain['vertical'] == 4,
            'route_local_terrain_bounds_mismatch')
    rows = terrain.get('cells')
    require(type(rows) is list and len(rows) <= (radius*2+1)**2*9, 'route_local_terrain_cells_invalid')
    try:
        origin = Block.parse(terrain['origin'])
        require(origin == _source(observation.player), 'route_local_terrain_origin_mismatch')
        cells = {}
        for row in rows:
            cell = Cell.parse(row)
            require(cell.position not in cells, 'route_local_duplicate_terrain_cell')
            p = cell.position
            require(abs(p.x-origin.x) <= radius and abs(p.z-origin.z) <= radius
                    and abs(p.y-origin.y) <= 4, 'route_local_terrain_cell_outside_scan')
            # Cell.parse supplies exact geometry/fluid/known checks. Tighten its
            # vocabulary to the native profile; never rewrite the observed ID.
            cells[p] = _RouteCell(p, cell.clear and row.get('id') in AIR,
                                 cell.support and row.get('id') in FLOORS,
                                 context=_context_block(row))
        return cells
    except (TerrainError, KeyError, TypeError, ValueError) as exc:
        raise SkillError('route_local_terrain_invalid:' + type(exc).__name__) from None


def _safe_edge(cells, source, target):
    """Exact local-segment support, jump sweep and conservative context prism."""
    dy = target.y-source.y
    if (not (-63 <= source.y <= 316 and -63 <= target.y <= 316)
            or abs(target.x-source.x)+abs(target.z-source.z) != 1 or dy not in (-1, 0, 1)):
        return False
    # Known context walls are allowed, but observed special/unknown context is
    # conservative refusal. The native-only halo may extend beyond this bounded
    # map; its coverage and current safety remain native admission's authority.
    # Every swept/support cell below MUST be present, never an unknown frontier.
    for x in range(min(source.x, target.x)-2, max(source.x, target.x)+3):
        for y in range(min(source.y, target.y)-1, max(source.y, target.y)+4):
            for z in range(min(source.z, target.z)-2, max(source.z, target.z)+3):
                cell = cells.get(Block(x, y, z))
                if cell is not None and not (cell.clear or cell.support or getattr(cell, 'context', False)):
                    return False
    ceiling = source.y + (3 if dy == 1 else 2 if dy == -1 else 1)
    for column in (source, target):
        support = cells.get(column.offset(y=-1))
        if support is None or not support.support:
            return False
        for y in range(column.y, ceiling+1):
            cell = cells.get(Block(column.x, y, column.z))
            if cell is None or not cell.clear:
                return False
    return True


def _plan(cells, source, goal, anchor, radius, remaining_segments):
    """Finite cardinal BFS. No partial/frontier route is ever returned."""
    require(_inside(source, anchor, radius) and _inside(goal, anchor, radius), 'route_local_original_bounds_exceeded')
    if source == goal:
        return (source,), 0
    frontier = deque((source,))
    parents, depths, expansions = {source: None}, {source: 0}, 0
    while frontier and expansions < MAX_EXPANSIONS:
        current = frontier.popleft()
        expansions += 1
        if depths[current] >= remaining_segments:
            continue
        for dx, dz in _DIRECTIONS:
            for dy in (0, 1, -1):
                target = current.offset(x=dx, y=dy, z=dz)
                if (target in parents or not _inside(target, anchor, radius)
                        or not _safe_edge(cells, current, target)):
                    continue
                parents[target], depths[target] = current, depths[current]+1
                if target == goal:
                    route = [target]
                    while parents[route[-1]] is not None:
                        route.append(parents[route[-1]])
                    return tuple(reversed(route)), expansions
                frontier.append(target)
    raise SkillError('route_local_expansion_budget_exhausted' if frontier else 'route_local_no_complete_known_route')


def _pose_settled(observation, target):
    p = observation.player
    velocity = p.get('velocity', {})
    return (all(_number(p.get(k)) and _number(velocity.get(k)) for k in ('x', 'y', 'z'))
            and math.hypot(p['x']-target['x'], p['z']-target['z']) <= .08
            and abs(p['y']-target['y']) <= 1e-6 and p.get('on_ground') is True
            and math.hypot(velocity['x'], velocity['z']) <= .003 and -.09 <= velocity['y'] <= 0)


def _settled_goal(observation, target, profile=PROFILE):
    action = observation.state.get('client_action', {})
    result = action.get('result', {})
    terminal = result.get('local_segment', {})
    meter = observation.state.get('movement_budget', {})
    return (_pose_settled(observation, target)
            and action.get('action') == 'follow_path' and action.get('status') == 'succeeded'
            and result.get('input_release_confirmed') is True
            and terminal.get('profile') == profile and terminal.get('phase') == 'landed'
            and terminal.get('landed') is True and terminal.get('input_neutral') is True
            and type(meter.get('schema_version')) is int and meter['schema_version'] == 1
            and meter.get('status') == 'unarmed')


def _protected(before, after):
    old, new = before.player, after.player
    return (_number(old.get('health')) and _number(new.get('health')) and new['health'] >= old['health']
            and old.get('inventory_truncated') is False and new.get('inventory_truncated') is False
            and type(old.get('inventory_total')) is int and old['inventory_total'] == new.get('inventory_total')
            and type(old.get('inventory')) is list and old['inventory'] == new.get('inventory')
            and all(old.get(k) == new.get(k) for k in ('selected_slot', 'offhand', 'armor')))


def _same_navigation(before, after):
    old = before.state.get('world', {}).get('navigation_guard', {})
    new = after.state.get('world', {}).get('navigation_guard', {})
    return old.get('epoch') == new.get('epoch')


def _guard(observation, min_health):
    require(observation.context[1] == 'minecraft:overworld'
            and observation.state.get('private_singleplayer') is True, 'route_local_private_overworld_required')
    meter = observation.state.get('movement_budget', {})
    require(type(meter) is dict and type(meter.get('schema_version')) is int
            and meter['schema_version'] == 1 and meter.get('status') == 'unarmed',
            'route_local_movement_budget_must_be_unarmed')
    require(_number(observation.player.get('health')) and observation.player['health'] > min_health,
            'mobility_health_guard')
    require(_protected(observation, observation), 'route_local_complete_inventory_required')
    velocity = observation.player.get('velocity', {})
    require(observation.player.get('on_ground') is True
            and all(_number(velocity.get(k)) for k in ('x', 'y', 'z'))
            and math.hypot(velocity['x'], velocity['z']) <= .003 and -.09 <= velocity['y'] <= 0,
            'route_local_settled_source_required')


def _same_plan_source(planned, fresh):
    require(planned.context == fresh.context, 'route_local_context_changed')
    require(all(abs(planned.player[k]-fresh.player[k]) <= .03 for k in ('x', 'y', 'z')),
            'route_local_origin_changed')
    require(_source(planned.player) == _source(fresh.player), 'route_local_source_block_changed')
    require(_same_navigation(planned, fresh), 'route_local_navigation_epoch_changed')
    require(planned.state.get('client_action', {}).get('action_id')
            == fresh.state.get('client_action', {}).get('action_id'), 'route_local_native_action_replaced')
    require(_protected(planned, fresh), 'route_local_health_or_inventory_changed')


def _survey_source(runtime, survey):
    """Retain historical provenance without converting it into a preflight."""
    runtime.validate_survey(survey)
    try:
        from resident_controller.movement_wire import validate_delivery
        validate_delivery(survey.raw, 8)
    except (ValueError, KeyError, TypeError) as exc:
        raise SkillError('route_local_invalid_survey_wire_provenance') from exc
    terrain = survey.terrain
    age = runtime.clock() - survey.captured_at
    require(_number(age) and age >= 0, 'route_local_survey_clock_invalid')
    return {'source_kind': 'historical_survey', 'survey_id': survey.request_id,
            'source_payload_sha256': survey._fingerprint,
            'captured_at': survey.captured_at, 'acquisition_seconds': survey.acquisition_seconds,
            'age_seconds_at_plan': age, 'age_diagnostic_only': True,
            'source_tick': terrain['source_tick'], 'last_tick': terrain['last_tick'],
            'capture_started_mono': terrain['capture_started_mono'],
            'capture_finished_mono': terrain['capture_finished_mono'],
            'source_page_count': len(terrain['source_pages']),
            'freshness_authority': False}


def _preplanning_attacker(observation, target_uuid):
    """Classify this exact fresh row; unknown facts never become calm absence."""
    from . import threats
    from resident_controller.spatial_threat_snapshot import valid_uuid, validate_living
    require(valid_uuid(target_uuid) and target_uuid != observation.context[2],
            'route_local_target_identity_invalid')
    rows = threats.entities(observation)
    require(all(type(row) is dict for row in rows), 'route_local_entity_rows_invalid')
    matches = [row for row in rows if row.get('uuid') == target_uuid]
    require(len(matches) <= 1, 'route_local_duplicate_target_identity')
    if not matches:
        return None
    row = matches[0]
    require(row.get('type') == 'minecraft:zombie' and row.get('alive') is True
            and type(row.get('entity_id')) is int and 0 <= row['entity_id'] < 2**31
            and _number(row.get('health')) and row['health'] > 0,
            'route_local_supported_living_zombie_required')
    position = threats.position(row)
    guard = observation.state.get('capability_guard', {})
    require(observation.player.get('uuid') == observation.context[2]
            and type(guard.get('schema_version')) is int and guard['schema_version'] == 1
            and type(guard.get('source_tick')) is int and guard['source_tick'] == observation.tick,
            'route_local_attacker_context_unconfirmed')
    # This is only a validation view of an unchanged native-living sample,
    # never a constructed native admission witness or a translated clock.
    context = dict(zip(('world_generation', 'dimension', 'player_uuid', 'action_session'), observation.context))
    try:
        active = validate_living(row.get('native_living'),
            {'uuid': row['uuid'], 'id': row['entity_id'], 'type': row['type']},
            {'source_tick': observation.tick, 'source_nano': guard.get('source_nano')},
            {'context': context})
    except (ValueError, KeyError, TypeError) as exc:
        raise SkillError('route_local_attacker_facts_unconfirmed') from exc
    if not active:
        require(row['native_living']['aggressive'] is False, 'route_local_targetless_aggressive')
        return None
    require(math.dist(threats.position(observation.player), position) <= 3.,
            'route_local_attacker_out_of_range')
    return row


def _stop_only_corridor(source, player, attacker):
    """One flat cardinal away from the dominant delta, x on ties; no retry."""
    dx, dz = attacker['x']-player['x'], attacker['z']-player['z']
    if abs(dx) >= abs(dz):
        return source.offset(x=-1 if dx > 0 else 1)
    return source.offset(z=-1 if dz > 0 else 1)


def _unexpected_stop_only_success(_before, _after):
    # A successful native movement receipt violates this command's contract.
    # Runtime retains semantic_pending when the verifier raises uncertainty.
    raise SkillError('route_local_stop_only_unexpected_success', status='unknown')


def navigate_route_local(runtime, goal, *, radius=6, max_segments=16, min_health=12, control=None):
    """Complete a known bounded route, stopping at the first non-success."""
    profile = runtime.scoped_profile('follow_path')
    require(profile in (PROFILE, SPATIAL_PROFILE, SPATIAL_STOP_PROFILE, SPATIAL_STOP_PROFILE_V2), 'route_local_profile_not_negotiated')
    threat_guard = getattr(control, 'route_threat_guard', None)
    if profile == SPATIAL_PROFILE:
        require(type(threat_guard) is dict and set(threat_guard) == {'schema_version', 'target_uuid'}
                and type(threat_guard['schema_version']) is int and threat_guard['schema_version'] == 1
                and isinstance(threat_guard['target_uuid'], str), 'route_local_explicit_threat_guard_required')
    else:
        require(threat_guard is None, 'route_local_threat_profile_not_negotiated')
    require(getattr(runtime, 'required_execution_policy', None) == 'request_only', 'route_local_request_only_required')
    goal = Block.parse(coordinate(goal))
    require(-63 <= goal.y <= 316, 'route_local_native_feet_bounds')
    require(type(radius) is int and 2 <= radius <= 8, 'route_local_radius_2_to8')
    require(type(max_segments) is int and 1 <= max_segments <= 16, 'route_local_max_segments_1_to16')
    require(_number(min_health) and 8 <= min_health <= 20, 'mobility_min_health_8_to20')
    ids, stages, plans = [], [], []
    anchor = initial = last = previous = None
    completed = 0

    def remember(*values):
        for value in values:
            if isinstance(value, str) and value and value not in ids:
                ids.append(value)

    def finish(status, reason, evidence=None):
        return Outcome(status, reason, tuple(ids), {**(evidence or {}),
            'profile': profile, 'goal': _point(goal),
            'original_source': None if anchor is None else {'x': anchor.x, 'y': anchor.y, 'z': anchor.z},
            'radius': radius, 'vertical_feet_limit': 2, 'max_segments': max_segments,
            'completed_segments': completed, 'segments': deepcopy(stages), 'plans': deepcopy(plans),
            'scope': 'known_bounded_cardinal_route', 'geometry_authority': 'native_admission_required',
            'automatic_replay_allowed': False, 'frontier_exploration': False,
            'future_dynamics_certified': False, 'server_confirmed': False}, last)

    try:
        while True:
            if control is not None: control.checkpoint()
            early = None
            if profile == SPATIAL_PROFILE:
                # An active configured attacker must not wait for historical
                # terrain acquisition. Only a stop-only native request may use
                # this branch, and it can never fall back to ordinary movement.
                early = runtime.observe(terrain=False, entity_radius=8)
                last = early
                remember(early.request_id)
                _guard(early, min_health)
                source = _source(early.player)
                bounds_anchor = source if anchor is None else anchor
                require(_inside(source, bounds_anchor, radius) and _inside(goal, bounds_anchor, radius),
                        'route_local_original_bounds_exceeded')
                if previous is not None:
                    _same_plan_source(previous, early)
                if initial is not None:
                    require(early.context == initial.context and _protected(initial, early)
                            and _same_navigation(initial, early), 'route_local_original_context_or_inventory_changed')
                attacker = _preplanning_attacker(early, threat_guard['target_uuid'])
                if attacker is not None:
                    if anchor is None:
                        anchor, initial = source, early
                    corridor = _stop_only_corridor(source, early.player, attacker)
                    require(_inside(corridor, anchor, radius), 'route_local_stop_only_corridor_outside_bounds')
                    target = _point(corridor)
                    plans.append({'source_kind': 'fresh_state_stop_only_candidate',
                        'observation_id': early.request_id, 'source': _point(source), 'target': target,
                        'direction_policy': 'away_dominant_horizontal_delta_x_tie',
                        'movement_authorized': False, 'survey_used': False})
                    command = {'op': 'action', 'action': 'follow_path',
                        'waypoints': [{**target, 'jump': False}], 'capability_route': True,
                        'route_threat_guard': deepcopy(threat_guard), 'route_stop_only': True,
                        'timeout_ms': 8000, 'min_health': min_health}
                    if control is not None: control.checkpoint()
                    outcome = runtime.execute('mobility.navigate_route_local', command,
                        _unexpected_stop_only_success, before=early, max_samples=16, stable_samples=2)
                    remember(*outcome.request_ids)
                    last = outcome.last_observation or early
                    stages.append({'status': outcome.status, 'reason': outcome.reason,
                        'goal': target, 'stop_only': True, 'request_ids': list(outcome.request_ids),
                        'evidence': deepcopy(outcome.evidence)})
                    return finish('unknown' if outcome.ok else outcome.status,
                        'route_local_stop_only_unexpected_success' if outcome.ok else outcome.reason,
                        outcome.evidence)
            # Sequential terrain pages are historical proposal input. Preserve
            # their original timestamps and require a separate owned, fresh
            # state observation before every native-admitted edge or goal claim.
            planned = runtime.survey(radius=radius, vertical=4, entity_radius=8)
            remember(planned.request_id)
            source_evidence = _survey_source(runtime, planned)
            _guard(planned, min_health)
            if early is not None:
                _same_plan_source(early, planned)
            source = _source(planned.player)
            if anchor is None:
                anchor, initial = source, planned
            else:
                _same_plan_source(previous, planned)
            require(planned.context == initial.context and _protected(initial, planned),
                    'route_local_original_context_or_inventory_changed')
            require(_same_navigation(initial, planned), 'route_local_navigation_epoch_changed')
            require(_inside(source, anchor, radius) and _inside(goal, anchor, radius),
                    'route_local_original_bounds_exceeded')
            if control is not None: control.checkpoint()
            cells = _grid(planned, radius)
            route, expansions = _plan(cells, source, goal, anchor, radius, max_segments-completed)
            plans.append({'source': _point(source), 'steps': len(route)-1, 'expansions': expansions,
                          **source_evidence})
            if control is not None:
                control.emit('local_route_planned', {'goal': _point(goal), 'steps': len(route)-1,
                    'completed_segments': completed, 'profile': profile,
                    'geometry_authority': 'native_admission_required'})
            if control is not None: control.checkpoint()
            before = runtime.observe(terrain=False, entity_radius=8)
            last = before
            remember(before.request_id)
            _guard(before, min_health)
            _same_plan_source(planned, before)
            require(_protected(initial, before), 'route_local_health_or_inventory_changed')
            if len(route) == 1:
                require(_pose_settled(before, _point(goal)), 'route_local_goal_not_settled')
                proof = runtime.result('mobility.navigate_route_local', [before], already_arrived=True)
                remember(*proof.request_ids)
                return finish(proof.status, proof.reason, proof.evidence)
            target = _point(route[1])
            command = {'op': 'action', 'action': 'follow_path', 'waypoints': [{**target, 'jump': False}],
                       'capability_route': True, 'timeout_ms': 8000, 'min_health': min_health}
            if profile == SPATIAL_PROFILE:
                command['route_threat_guard'] = deepcopy(threat_guard)
            if control is not None: control.checkpoint()
            outcome = runtime.execute('mobility.navigate_route_local', command,
                lambda old, new: _settled_goal(new, target, profile) and _protected(old, new)
                                and new.context == initial.context and _protected(initial, new)
                                and _same_navigation(initial, new),
                before=before, max_samples=16, stable_samples=2)
            remember(*outcome.request_ids)
            last = outcome.last_observation or before
            stages.append({'status': outcome.status, 'reason': outcome.reason, 'goal': target,
                           'request_ids': list(outcome.request_ids), 'evidence': deepcopy(outcome.evidence)})
            if not outcome.ok:
                return finish(outcome.status, outcome.reason, outcome.evidence)
            require(outcome.last_observation is not None and _settled_goal(last, target, profile)
                    and _protected(before, last) and last.context == initial.context
                    and _same_navigation(initial, last),
                    'route_local_success_evidence_missing')
            completed += 1
            previous = last
            if route[1] == goal:
                return finish('succeeded', 'route_local_goal_observed', outcome.evidence)
            require(completed < max_segments, 'route_local_segment_budget_exhausted')
    except SkillError as exc:
        remember(exc.request_id)
        return finish(exc.status, exc.reason)
    except Exception as exc:
        # The Runtime keeps the original uncertainty latch. Never replay or
        # discard IDs just because a later read/planning callback raised.
        remember(getattr(runtime, 'pending_request_id', None))
        return finish('unknown' if getattr(runtime, 'has_unresolved_execution', False) else 'blocked',
                      'route_local_error:' + type(exc).__name__)
