"""Isolated synthetic routing checks. No native physics or game execution."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mdc_skills import scoped_route_local as route
from mdc_skills.core import Outcome, SkillError, Survey, _digest


def cell(x, y, z, block='minecraft:air'):
    air = block in route.AIR or block == 'minecraft:void_air'
    return dict(x=x, y=y, z=z, status='loaded', known=True, collision_known=True,
        id=block, id_truncated=False, fluid='minecraft:empty', fluid_truncated=False,
        fluid_source=False, properties={}, properties_truncated=False, hazards=[],
        hazards_exhaustive=False, air=air, collision_empty=air, full_top_support=not air,
        collision_bounds=None if air else [0, 0, 0, 1, 1, 1])


def observed(x=.5, y=64., z=.5, *, number=1, terrain=False, radius=6, heights=None):
    p = dict(x=x, y=y, z=z, health=20., on_ground=True,
             velocity={'x': 0., 'y': -.0784, 'z': 0.}, inventory=[],
             inventory_total=0, inventory_truncated=False, selected_slot=0,
             offhand={'empty': True}, armor=[])
    state = {'player': p, 'private_singleplayer': True,
        'movement_budget': {'schema_version': 1, 'status': 'unarmed'},
        'world': {'world_generation': 'world', 'dimension': 'minecraft:overworld',
                  'navigation_guard': {'epoch': 7}}, 'client_action': {}}
    source = route._source(p)
    tick = 100+number
    terrain_data = None
    if terrain:
        heights = heights or (lambda _x, _z: 64)
        terrain_data = {'complete': True, 'world_generation': 'world', 'dimension': 'minecraft:overworld',
            'origin': {'x': source.x, 'y': source.y, 'z': source.z}, 'radius': radius, 'vertical': 4,
            'source_tick': tick, 'last_tick': tick, 'capture_started_mono': -100000.,
            'scan_generation': 'scan-'+str(number), 'cells': [
                cell(cx, cy, cz, 'minecraft:stone' if cy < heights(cx, cz) else 'minecraft:air')
                for cx in range(source.x-radius, source.x+radius+1)
                for cy in range(source.y-4, source.y+5)
                for cz in range(source.z-radius, source.z+radius+1)]}
    return SimpleNamespace(context=('world', 'minecraft:overworld', 'player', 'session'),
        player=p, state=state, terrain=terrain_data, tick=tick, request_id='observe-'+str(number))


def landed(obs):
    obs.state['client_action'] = {'action': 'follow_path', 'status': 'succeeded', 'result': {
        'input_release_confirmed': True, 'local_segment': {
            'profile': route.PROFILE, 'phase': 'landed', 'landed': True, 'input_neutral': True}}}
    return obs


class Runtime:
    required_execution_policy = 'request_only'
    profile = route.PROFILE
    has_unresolved_execution = False
    pending_request_id = None

    def __init__(self, *, heights=None, results=(), mutate=None, after_action=None):
        self.position = (.5, 64., .5)
        self.heights, self.results, self.mutate, self.after_action = heights, list(results), mutate, after_action
        self.calls, self.actions, self.planning_reads, self.read_count = [], [], 0, 0
        self.current_action = {}

    def scoped_profile(self, action):
        self.assert_action = action
        return self.profile

    def observe(self, **options):
        self.calls.append(('observe', options))
        self.read_count += 1
        if options.get('terrain'):
            self.planning_reads += 1
        obs = observed(*self.position, number=self.read_count, terrain=options.get('terrain', False),
                       radius=options.get('radius', 6), heights=self.heights)
        obs.state['client_action'] = deepcopy(self.current_action)
        if self.mutate is not None:
            self.mutate(self, obs, options)
        return obs

    def survey(self, **options):
        obs = self.observe(terrain=True, **options)
        self.calls[-1] = ('survey', options)
        obs.request_id = 'survey-'+str(self.read_count)
        start = 100.+self.read_count
        terrain = obs.terrain
        terrain.update(historical_survey=True, capture_started_mono=start,
                       capture_finished_mono=start+1.1,
                       source_pages=[{'source_tick': obs.tick, 'response_tick': obs.tick,
                                      'captured_mono': start+1., 'offset': 0,
                                      'returned': len(terrain['cells'])}])
        raw = {'state': obs.state, 'terrain': terrain}
        return Survey(obs.state, terrain, raw, obs.tick, obs.context, start,
                      obs.request_id, 1.1, 'synthetic-route-runtime', _digest(raw))

    def validate_survey(self, survey):
        if (not isinstance(survey, Survey) or survey._owner != 'synthetic-route-runtime'
                or _digest(survey.raw) != survey._fingerprint):
            raise SkillError('invalid_synthetic_survey')
        return survey

    def execute(self, name, command, verify, **options):
        self.calls.append(('execute', name, deepcopy(command), options))
        self.actions.append(deepcopy(command))
        target = command['waypoints'][0]
        status = self.results.pop(0) if self.results else 'succeeded'
        sample = landed(observed(target['x'], target['y'], target['z'], number=100+len(self.actions)))
        sample.state['client_action']['action_id'] = 'native-'+str(len(self.actions))
        if self.after_action:
            self.after_action(self, sample)
        if status == 'succeeded' and not verify(options['before'], sample):
            status = 'failed'
        self.has_unresolved_execution = status == 'unknown'
        if status == 'succeeded':
            self.position = tuple(sample.player[k] for k in ('x', 'y', 'z'))
            self.current_action = deepcopy(sample.state['client_action'])
        return Outcome(status, 'synthetic-'+status, ('action-'+str(len(self.actions)), sample.request_id),
                       {'synthetic': True}, sample)

    def result(self, name, observations, **evidence):
        self.calls.append(('result', name))
        return Outcome('succeeded', 'goal_already_observed', tuple(o.request_id for o in observations),
                       evidence, observations[-1])

    def begin_job(self, *args, **kwargs):
        raise AssertionError('nested owner must not be created')

    def finish_job(self, *args, **kwargs):
        raise AssertionError('outer owner must not be finished')

    def clock(self):
        # Age is reported as diagnostic provenance, never a mutation-age gate.
        return 101.1+self.read_count


class Control:
    def __init__(self, stop_after=None):
        self.checks, self.events, self.stop_after = 0, [], stop_after

    def checkpoint(self):
        self.checks += 1
        if self.stop_after is not None and self.checks >= self.stop_after:
            raise SkillError('synthetic-stop', status='cancelled')

    def emit(self, event, data):
        self.events.append((event, data))


class RouteLocalPlannerTests(unittest.TestCase):
    def test_multi_segment_route_has_fresh_preflight_each_time(self):
        r, control = Runtime(), Control()
        out = route.navigate_route_local(r, {'x': 3, 'y': 64, 'z': 0}, control=control)
        self.assertTrue(out.ok, out)
        self.assertEqual(out.evidence['completed_segments'], 3)
        self.assertEqual(r.planning_reads, 3)
        self.assertEqual([c[0] for c in r.calls], ['survey', 'observe', 'execute']*3)
        for index, action in enumerate(r.actions, 1):
            self.assertEqual(action, {'op': 'action', 'action': 'follow_path',
                'waypoints': [{'x': index+.5, 'y': 64, 'z': .5, 'jump': False}],
                'capability_route': True, 'timeout_ms': 8000, 'min_health': 12})
        for call in (c for c in r.calls if c[0] == 'execute'):
            self.assertEqual(call[3]['max_samples'], 16)
            self.assertEqual(call[3]['stable_samples'], 2)
        self.assertEqual(r.calls[0][1], {'radius': 6, 'vertical': 4, 'entity_radius': 8})
        self.assertEqual(len(set(out.request_ids)), len(out.request_ids))
        self.assertEqual(len(control.events), 3)
        self.assertGreaterEqual(control.checks, 12)

    def test_complete_known_route_required_before_first_action(self):
        def remove_goal(_r, obs, options):
            if options['terrain']:
                obs.terrain['cells'] = [c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) != (2, 63, 0)]
        r = Runtime(mutate=remove_goal)
        out = route.navigate_route_local(r, {'x': 2, 'y': 64, 'z': 0})
        self.assertFalse(out.ok)
        self.assertEqual(out.reason, 'route_local_no_complete_known_route')
        self.assertFalse(r.actions)

    def test_changed_route_stops_after_prior_success_with_all_ids(self):
        def remove_goal(r, obs, options):
            if options['terrain'] and r.planning_reads > 1:
                obs.terrain['cells'] = [c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) != (3, 63, 0)]
        r = Runtime(mutate=remove_goal)
        out = route.navigate_route_local(r, {'x': 3, 'y': 64, 'z': 0})
        self.assertFalse(out.ok)
        self.assertEqual(len(r.actions), 1)
        self.assertEqual(out.evidence['completed_segments'], 1)
        self.assertIn('action-1', out.request_ids)
        self.assertIn('survey-3', out.request_ids)

    def test_every_non_success_stops_without_read_retry_or_replay(self):
        for status in ('blocked', 'failed', 'cancelled', 'interrupted', 'unknown'):
            with self.subTest(status=status):
                r = Runtime(results=('succeeded', status))
                out = route.navigate_route_local(r, {'x': 3, 'y': 64, 'z': 0})
                self.assertEqual(out.status, status)
                self.assertEqual(len(r.actions), 2)
                self.assertEqual(r.read_count, 4)
                self.assertIn('action-1', out.request_ids)
                self.assertIn('action-2', out.request_ids)
                self.assertFalse(out.evidence['automatic_replay_allowed'])

    def test_observe_error_after_effect_keeps_ids_and_request_error(self):
        def fail(r, _obs, _options):
            if r.read_count == 3:
                raise SkillError('stale', request_id='failed-read')
        r = Runtime(mutate=fail)
        out = route.navigate_route_local(r, {'x': 3, 'y': 64, 'z': 0})
        self.assertEqual(out.reason, 'stale')
        self.assertIn('action-1', out.request_ids)
        self.assertIn('failed-read', out.request_ids)
        self.assertEqual(len(r.actions), 1)

    def test_request_bounds_closed_types_and_negotiation(self):
        for kwargs in ({'radius': 1}, {'radius': 9}, {'radius': True}, {'radius': 6.},
                       {'max_segments': 0}, {'max_segments': 17}, {'max_segments': True},
                       {'min_health': 7}, {'min_health': 21}, {'min_health': float('nan')}, {'min_health': True}):
            r = Runtime()
            with self.assertRaises(SkillError):
                route.navigate_route_local(r, {'x': 1, 'y': 64, 'z': 0}, **kwargs)
            self.assertFalse(r.calls)
        for goal in ({'x': True, 'y': 64, 'z': 0}, {'x': 1.5, 'y': 64, 'z': 0}, {'x': 1, 'z': 0}):
            with self.assertRaises(SkillError):
                route.navigate_route_local(Runtime(), goal)
        for attribute, value in (('profile', 'movement-flat-observed-v2'), ('required_execution_policy', 'standard')):
            r = Runtime()
            setattr(r, attribute, value)
            with self.assertRaises(SkillError):
                route.navigate_route_local(r, {'x': 1, 'y': 64, 'z': 0})
            self.assertFalse(r.calls)

    def test_no_route_when_goal_outside_original_horizontal_or_vertical_bounds(self):
        for goal in ({'x': 7, 'y': 64, 'z': 0}, {'x': 0, 'y': 67, 'z': 0}, {'x': 0, 'y': 61, 'z': 0}):
            r = Runtime()
            out = route.navigate_route_local(r, goal)
            self.assertEqual(out.reason, 'route_local_original_bounds_exceeded')
            self.assertFalse(r.actions)

    def test_native_feet_bounds_rejected_without_action(self):
        for y in (-64, 317):
            r = Runtime()
            with self.assertRaisesRegex(SkillError, 'native_feet_bounds'):
                route.navigate_route_local(r, {'x': 1, 'y': y, 'z': 0})
            self.assertFalse(r.calls)
        cells = route._grid(observed(terrain=True), 6)
        self.assertFalse(route._safe_edge(cells, route.Block(0, 316, 0), route.Block(1, 317, 0)))

    def test_original_anchor_never_moves_with_rescans(self):
        seen = []
        original = route._plan
        def capture(cells, source, goal, anchor, radius, remaining):
            seen.append((source, anchor, remaining))
            return original(cells, source, goal, anchor, radius, remaining)
        with patch.object(route, '_plan', capture):
            out = route.navigate_route_local(Runtime(), {'x': 3, 'y': 64, 'z': 0}, max_segments=3)
        self.assertTrue(out.ok)
        self.assertEqual([p[1] for p in seen], [route.Block(0, 64, 0)]*3)
        self.assertEqual([p[2] for p in seen], [3, 2, 1])

    def test_segment_limit_requires_whole_route_to_fit_before_dispatch(self):
        r = Runtime()
        out = route.navigate_route_local(r, {'x': 3, 'y': 64, 'z': 0}, max_segments=2)
        self.assertEqual(out.reason, 'route_local_no_complete_known_route')
        self.assertFalse(r.actions)

    def test_flat_up_and_down_compose_and_no_jump_command_authority(self):
        r = Runtime(heights=lambda x, z: 65 if x == 1 and z == 0 else 64)
        out = route.navigate_route_local(r, {'x': 2, 'y': 64, 'z': 0}, max_segments=2)
        self.assertTrue(out.ok, out)
        self.assertEqual([a['waypoints'][0]['y'] for a in r.actions], [65, 64])
        self.assertTrue(all(a['waypoints'][0]['jump'] is False for a in r.actions))

    def test_plus_two_feet_route_sweep_fits_vertical_four(self):
        r = Runtime(heights=lambda x, z: 64+min(max(x, 0), 2))
        out = route.navigate_route_local(r, {'x': 2, 'y': 66, 'z': 0}, max_segments=2)
        self.assertTrue(out.ok, out)

    def test_radius_two_sweep_known_native_context_may_extend_past_scan(self):
        r = Runtime()
        out = route.navigate_route_local(r, {'x': 2, 'y': 64, 'z': 0}, radius=2)
        self.assertTrue(out.ok, out)
        self.assertEqual(len(r.actions), 2)

    def test_known_obstacle_can_be_routed_around_cardinally(self):
        r = Runtime(heights=lambda x, z: 68 if (x, z) == (1, 0) else 64)
        out = route.navigate_route_local(r, {'x': 2, 'y': 64, 'z': 0}, max_segments=4)
        self.assertTrue(out.ok, out)
        self.assertEqual(len(r.actions), 4)
        prior = (0, 64, 0)
        for action in r.actions:
            p = action['waypoints'][0]
            current = (p['x']-.5, p['y'], p['z']-.5)
            self.assertEqual(abs(current[0]-prior[0])+abs(current[2]-prior[2]), 1)
            prior = current

    def test_geometry_up_sweep_and_down_upper_headroom(self):
        for target, heights, blocked in ((route.Block(1, 65, 0), lambda x, z: 65 if x == 1 else 64, (0, 67, 0)),
                                       (route.Block(1, 63, 0), lambda x, z: 63 if x == 1 else 64, (1, 66, 0))):
            obs = observed(terrain=True, heights=heights)
            cells = route._grid(obs, 6)
            self.assertTrue(route._safe_edge(cells, route.Block(0, 64, 0), target))
            cells[route.Block(*blocked)] = route.Cell(route.Block(*blocked), False, True)
            self.assertFalse(route._safe_edge(cells, route.Block(0, 64, 0), target))

    def test_no_diagonal_two_block_vertical_or_unknown_support(self):
        cells = route._grid(observed(terrain=True), 6)
        source = route.Block(0, 64, 0)
        for target in (route.Block(1, 64, 1), route.Block(1, 66, 0), route.Block(1, 62, 0)):
            self.assertFalse(route._safe_edge(cells, source, target))
        cells.pop(route.Block(1, 63, 0))
        self.assertFalse(route._safe_edge(cells, source, route.Block(1, 64, 0)))

    def test_native_floor_allowlist_is_exact_and_no_legacy_promotions(self):
        self.assertEqual(len(route.FLOORS), 12)
        for block in ('minecraft:stone_slab', 'minecraft:oak_stairs', 'minecraft:obsidian',
                      'minecraft:deepslate', 'minecraft:spruce_planks', 'minecraft:glass'):
            obs = observed(terrain=True)
            row = next(c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) == (1, 63, 0))
            row.update(id=block)
            self.assertFalse(route._grid(obs, 6)[route.Block(1, 63, 0)].support, block)
        obs = observed(terrain=True)
        row = next(c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) == (1, 64, 0))
        row['id'] = 'minecraft:void_air'
        self.assertFalse(route._grid(obs, 6)[route.Block(1, 64, 0)].clear)

    def test_unknown_partial_fluid_hazard_truncation_fail_closed(self):
        for change in ({'known': False}, {'collision_known': False}, {'fluid': 'minecraft:water'},
                       {'fluid_source': True}, {'hazards': ['fire']}, {'id_truncated': True},
                       {'collision_bounds': [0, 0, 0, 1, .5, 1]}, {'status': 'unloaded'}):
            obs = observed(terrain=True)
            row = next(c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) == (1, 63, 0))
            row.update(change)
            self.assertFalse(route._grid(obs, 6)[route.Block(1, 63, 0)].support, change)

    def test_context_station_and_leaf_allowlist_is_separate_from_floor_and_air(self):
        self.assertEqual(route.CONTEXT_LEAVES, {'minecraft:oak_leaves', 'minecraft:birch_leaves'})
        self.assertEqual(route.CONTEXT_BLOCKS, {'minecraft:barrel', 'minecraft:furnace',
                                              'minecraft:oak_leaves', 'minecraft:birch_leaves'})
        self.assertFalse(route.CONTEXT_BLOCKS & route.FLOORS)
        self.assertFalse(route.CONTEXT_BLOCKS & route.AIR)
        for block in route.CONTEXT_BLOCKS:
            obs = observed(terrain=True)
            row = next(c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) == (1, 64, 1))
            row.update(cell(1, 64, 1, block))
            parsed = route._grid(obs, 6)[route.Block(1, 64, 1)]
            self.assertTrue(parsed.context)
            self.assertFalse(parsed.support)
            self.assertFalse(parsed.clear)

    def test_adjacent_context_station_or_leaves_allows_route(self):
        for block in route.CONTEXT_BLOCKS:
            def mutate(_r, obs, options):
                if options['terrain']:
                    row = next(c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) == (1, 64, 1))
                    row.update(cell(1, 64, 1, block))
            r = Runtime(mutate=mutate)
            out = route.navigate_route_local(r, {'x': 3, 'y': 64, 'z': 0}, max_segments=3)
            self.assertTrue(out.ok, (block, out))
            self.assertEqual(len(r.actions), 3)

    def test_context_station_or_leaves_in_source_or_target_support_or_clearance_blocks(self):
        for block in route.CONTEXT_BLOCKS:
            for position in ((0, 63, 0), (1, 63, 0), (0, 64, 0), (1, 64, 0), (1, 65, 0)):
                obs = observed(terrain=True)
                row = next(c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) == position)
                row.update(cell(*position, block))
                cells = route._grid(obs, 6)
                self.assertTrue(cells[route.Block(*position)].context)
                self.assertFalse(route._safe_edge(cells, route.Block(0, 64, 0), route.Block(1, 64, 0)),
                                 (block, position))

    def test_context_station_or_leaves_partial_fluid_unknown_and_truncated_refused(self):
        changes = ({'known': False}, {'collision_known': False}, {'status': 'unloaded'},
                   {'id_truncated': True}, {'properties_truncated': True}, {'fluid_truncated': True},
                   {'properties': None}, {'fluid': 'minecraft:water'}, {'fluid_source': True},
                   {'hazards': ['fire']}, {'hazards_exhaustive': True}, {'air': True},
                   {'collision_empty': True}, {'full_top_support': False},
                   {'collision_bounds': [0, 0, 0, 1, .5, 1]},
                   {'collision_bounds': [0, 0, 0, 1, float('nan'), 1]},
                   {'collision_bounds': [False, 0, 0, 1, 1, 1]})
        for block in route.CONTEXT_BLOCKS:
            for change in changes:
                obs = observed(terrain=True)
                row = next(c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) == (1, 64, 1))
                row.update(cell(1, 64, 1, block))
                row.update(change)
                cells = route._grid(obs, 6)
                self.assertFalse(cells[route.Block(1, 64, 1)].context, (block, change))
                self.assertFalse(route._safe_edge(cells, route.Block(0, 64, 0), route.Block(1, 64, 0)),
                                 (block, change))

    def test_other_station_not_added_to_context_allowlist(self):
        for block in ('minecraft:blast_furnace', 'minecraft:smoker', 'minecraft:crafting_table',
                      'minecraft:chest', 'minecraft:shulker_box'):
            self.assertFalse(route._context_block(cell(1, 64, 1, block)))

    def test_other_leaf_ids_are_not_context_support_or_clear(self):
        for block in ('minecraft:spruce_leaves', 'minecraft:jungle_leaves', 'minecraft:acacia_leaves',
                      'minecraft:dark_oak_leaves', 'minecraft:mangrove_leaves', 'minecraft:cherry_leaves',
                      'minecraft:azalea_leaves', 'minecraft:flowering_azalea_leaves', 'mod:oak_leaves'):
            obs = observed(terrain=True)
            row = next(c for c in obs.terrain['cells'] if (c['x'], c['y'], c['z']) == (1, 64, 1))
            row.update(cell(1, 64, 1, block))
            cells = route._grid(obs, 6)
            parsed = cells[route.Block(1, 64, 1)]
            self.assertFalse(parsed.context, block)
            self.assertFalse(parsed.support, block)
            self.assertFalse(parsed.clear, block)
            self.assertFalse(route._safe_edge(cells, route.Block(0, 64, 0), route.Block(1, 64, 0)), block)

    def test_duplicate_and_foreign_terrain_rejected(self):
        for mutate in (lambda t: t['cells'].append(deepcopy(t['cells'][0])),
                       lambda t: t.update(dimension='minecraft:the_nether'),
                       lambda t: t.update(complete=False), lambda t: t.update(last_tick=99999),
                       lambda t: t.update(radius=8)):
            obs = observed(terrain=True)
            mutate(obs.terrain)
            with self.assertRaises(SkillError):
                route._grid(obs, 6)

    def test_fresh_source_context_epoch_and_pose_rechecked(self):
        def shifted(field, value):
            def mutate(_r, obs, options):
                if not options['terrain']:
                    if field == 'context': obs.context = value
                    elif field == 'epoch': obs.state['world']['navigation_guard']['epoch'] = value
                    else: obs.player[field] = value
            return mutate
        for field, value in (('x', .54), ('y', 64.1), ('epoch', 8),
                             ('context', ('changed', 'minecraft:overworld', 'player', 'session'))):
            r = Runtime(mutate=shifted(field, value))
            out = route.navigate_route_local(r, {'x': 1, 'y': 64, 'z': 0})
            self.assertFalse(out.ok, (field, out))
            self.assertFalse(r.actions)

    def test_private_policy_health_and_unarmed_guards(self):
        for mutate in (lambda o: o.state.update(private_singleplayer=False),
                       lambda o: o.state['movement_budget'].update(status='armed'),
                       lambda o: o.player.update(health=12),
                       lambda o: o.player.update(inventory_truncated=True),
                       lambda o: o.player.update(on_ground=False)):
            r = Runtime(mutate=lambda _r, o, _opts: mutate(o))
            self.assertFalse(route.navigate_route_local(r, {'x': 1, 'y': 64, 'z': 0}).ok)
            self.assertFalse(r.actions)

    def test_native_navigation_epoch_change_after_action_stops_route(self):
        r = Runtime(after_action=lambda _r, obs: obs.state['world']['navigation_guard'].update(epoch=8))
        out = route.navigate_route_local(r, {'x': 2, 'y': 64, 'z': 0})
        self.assertEqual(out.status, 'failed')
        self.assertEqual(len(r.actions), 1)
        self.assertIn('action-1', out.request_ids)

    def test_replaced_native_action_between_segments_preserves_prior_ids(self):
        def mutate(r, obs, options):
            if options['terrain'] and r.planning_reads == 2:
                obs.state['client_action']['action_id'] = 'different-action'
        r = Runtime(mutate=mutate)
        out = route.navigate_route_local(r, {'x': 2, 'y': 64, 'z': 0})
        self.assertEqual(out.reason, 'route_local_native_action_replaced')
        self.assertEqual(len(r.actions), 1)
        self.assertIn('action-1', out.request_ids)

    def test_replaced_native_action_before_first_dispatch_stops(self):
        def mutate(_r, obs, options):
            if not options['terrain']:
                obs.state['client_action']['action_id'] = 'unexpected-action'
        r = Runtime(mutate=mutate)
        out = route.navigate_route_local(r, {'x': 1, 'y': 64, 'z': 0})
        self.assertEqual(out.reason, 'route_local_native_action_replaced')
        self.assertFalse(r.actions)

    def test_native_terminal_exact_endpoint_motion_and_inventory(self):
        target = {'x': 1.5, 'y': 64, 'z': .5}
        sample = landed(observed(1.5))
        self.assertTrue(route._settled_goal(sample, target))
        for field, value in (('profile', 'movement-flat-observed-v2'), ('phase', 'falling'),
                             ('landed', False), ('input_neutral', False)):
            bad = deepcopy(sample)
            bad.state['client_action']['result']['local_segment'][field] = value
            self.assertFalse(route._settled_goal(bad, target))
        for field, value in (('x', 1.581), ('z', .581), ('y', 64.000002), ('on_ground', False)):
            bad = deepcopy(sample)
            bad.player[field] = value
            self.assertFalse(route._settled_goal(bad, target))
        for key, value in (('x', .0031), ('y', .001), ('y', -.091)):
            bad = deepcopy(sample)
            bad.player['velocity'][key] = value
            self.assertFalse(route._settled_goal(bad, target))
        for mutate in (lambda o: o.player.update(health=19),
                       lambda o: o.player['inventory'].append({'slot': 0}),
                       lambda o: o.player.update(selected_slot=1)):
            r = Runtime(after_action=lambda _r, o: mutate(o))
            out = route.navigate_route_local(r, {'x': 2, 'y': 64, 'z': 0})
            self.assertEqual(out.status, 'failed')
            self.assertEqual(len(r.actions), 1)

    def test_already_at_goal_observed_without_action(self):
        r = Runtime()
        out = route.navigate_route_local(r, {'x': 0, 'y': 64, 'z': 0})
        self.assertTrue(out.ok, out)
        self.assertFalse(r.actions)
        self.assertTrue(out.evidence['already_arrived'])

    def test_cancellation_before_planning_and_dispatch(self):
        for stop_after in (1, 2, 3, 4):
            r = Runtime()
            out = route.navigate_route_local(r, {'x': 1, 'y': 64, 'z': 0}, control=Control(stop_after))
            self.assertEqual(out.status, 'cancelled')
            self.assertFalse(r.actions)

    def test_bfs_expansion_ceiling_is_finite(self):
        cells = route._grid(observed(terrain=True), 6)
        with patch.object(route, 'MAX_EXPANSIONS', 1):
            with self.assertRaisesRegex(SkillError, 'expansion_budget_exhausted'):
                route._plan(cells, route.Block(0, 64, 0), route.Block(3, 64, 0), route.Block(0, 64, 0), 6, 16)
        self.assertEqual(route.MAX_EXPANSIONS, 2048)


if __name__ == '__main__':
    unittest.main()
