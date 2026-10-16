"""Pure route control tests with owned-shape Observations and synthetic server facts.

Native geometry, stop-only admission and public owner chain have separate tests.
"""
from copy import deepcopy
import unittest

from mdc_skills import scoped_route_local as route
from mdc_skills.core import Observation, Outcome, SkillError, _digest
import test_route_local_planner as planner

PLAYER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
TARGET = '44444444-4444-4444-8444-444444444444'


def target(observation, *, active=True):
    row = {'uuid': TARGET, 'entity_id': 9, 'type': 'minecraft:zombie', 'alive': True,
           'health': 20., 'x': observation.player['x']+1., 'y': 64., 'z': .5}
    row['native_living'] = {'schema_version': 1, 'entity_uuid': TARGET, 'entity_id': 9,
        'entity_type': 'minecraft:zombie', 'dimension': observation.context[1],
        'world_generation': observation.context[0], 'player_uuid': PLAYER,
        'known': True, 'source': 'integrated_server_tick', 'reason': 'observed',
        'current_target_known': True, 'coverage_complete': True, 'inspected': 1,
        'sample_tick': observation.tick, 'source_tick': observation.tick,
        'sample_nano': '100000000000', 'source_nano': '100000000000',
        'sample_age_ms': 0., 'alive': True, 'aggressive': active,
        'current_target': {'uuid': PLAYER, 'entity_id': 1, 'type': 'minecraft:player'} if active else None}
    return row


class Runtime(planner.Runtime):
    profile = route.SPATIAL_PROFILE

    def __init__(self, *, selected='active', change=None, stop_result='cancelled', later=False):
        super().__init__(after_action=lambda _, obs: obs.state['client_action']['result']['local_segment'].update(profile=self.profile))
        self.selected, self.change, self.stop_result, self.later = selected, change, stop_result, later
        self.last_fresh = None

    def observe(self, **options):
        obs = super().observe(**options)
        obs.player['uuid'] = PLAYER
        obs.context = (obs.context[0], obs.context[1], PLAYER, obs.context[3])
        obs.state['capability_guard'] = {'schema_version': 1, 'source_tick': obs.tick,
                                         'source_nano': '100000000000'}
        selected = 'absent' if self.later and not self.actions else self.selected
        rows = [] if selected == 'absent' else [target(obs, active=selected == 'active')]
        obs.state['nearby'] = {'truncated': False, 'returned': len(rows), 'total': len(rows), 'entities': rows}
        if self.change: self.change(obs)
        if options.get('terrain'): return obs
        raw = {'state': obs.state}
        fresh = Observation(obs.state, None, raw, obs.tick, obs.context, 100.+self.read_count,
                            obs.request_id, 'synthetic-route-runtime', _digest(raw))
        self.last_fresh = fresh
        return fresh

    def execute(self, name, command, verify, **options):
        if not command.get('route_stop_only'):
            # The existing synthetic landing fixture has a short player context;
            # preserve the same selected context for an ordinary spatial segment.
            self.after_action = lambda _, obs: (obs.state['client_action']['result']['local_segment'].update(profile=self.profile),
                setattr(obs, 'context', options['before'].context), obs.player.update(uuid=PLAYER))
            return super().execute(name, command, verify, **options)
        self.calls.append(('execute', name, deepcopy(command), options))
        self.actions.append(deepcopy(command))
        if self.stop_result == 'verifier':
            verify(options['before'], options['before'])
        status = self.stop_result
        return Outcome(status, 'capability_threat_observed' if status == 'cancelled' else 'synthetic-'+status,
                       ('stop-only-1',), {'synthetic': True}, options['before'])


def control():
    value = planner.Control()
    value.route_threat_guard = {'schema_version': 1, 'target_uuid': TARGET}
    return value


class StopOnlyPreplanningTests(unittest.TestCase):
    def run_route(self, runtime, goal=None):
        return route.navigate_route_local(runtime, goal or {'x': 1, 'y': 64, 'z': 0}, control=control())

    def test_active_target_has_one_away_corridor_no_survey_same_observation(self):
        runtime = Runtime()
        out = self.run_route(runtime)
        self.assertEqual(out.status, 'cancelled')
        self.assertEqual([c[0] for c in runtime.calls], ['observe', 'execute'])
        self.assertEqual(runtime.planning_reads, 0)
        self.assertIs(runtime.calls[-1][3]['before'], runtime.last_fresh)
        self.assertIsInstance(runtime.last_fresh, Observation)
        self.assertIs(out.last_observation, runtime.last_fresh)
        self.assertEqual(runtime.actions[0]['waypoints'], [{'x': -.5, 'y': 64, 'z': .5, 'jump': False}])
        self.assertIs(runtime.actions[0]['route_stop_only'], True)
        self.assertEqual(out.evidence['completed_segments'], 0)
        self.assertEqual(out.request_ids, ('observe-1', 'stop-only-1'))

    def test_every_non_success_stops_without_fallback_or_other_corridor(self):
        for status in ('blocked', 'failed', 'cancelled', 'interrupted', 'unknown'):
            with self.subTest(status=status):
                runtime = Runtime(stop_result=status)
                out = self.run_route(runtime)
                self.assertEqual(out.status, status)
                self.assertEqual(len(runtime.actions), 1)
                self.assertEqual(runtime.planning_reads, 0)
                self.assertEqual(runtime.read_count, 1)

    def test_unexpected_success_is_unknown_not_movement_success(self):
        runtime = Runtime(stop_result='succeeded')
        out = self.run_route(runtime)
        self.assertEqual((out.status, out.reason), ('unknown', 'route_local_stop_only_unexpected_success'))
        self.assertEqual(out.evidence['completed_segments'], 0)
        self.assertEqual(runtime.read_count, 1)
        with self.assertRaises(SkillError) as caught:
            route._unexpected_stop_only_success(None, None)
        self.assertEqual(caught.exception.status, 'unknown')

    def test_absent_and_proven_calm_targets_use_historical_route_without_flag(self):
        for selected in ('absent', 'calm'):
            with self.subTest(selected=selected):
                runtime = Runtime(selected=selected)
                out = self.run_route(runtime)
                self.assertTrue(out.ok, out)
                self.assertEqual([c[0] for c in runtime.calls], ['observe', 'survey', 'observe', 'execute'])
                self.assertNotIn('route_stop_only', runtime.actions[0])
                self.assertEqual(runtime.planning_reads, 1)

    def test_unknown_stale_mixed_or_partial_target_facts_never_fall_back(self):
        changes = [lambda o: o.state['nearby'].update(truncated=True),
            lambda o: o.state['nearby']['entities'].append(deepcopy(o.state['nearby']['entities'][0])),
            lambda o: o.state['nearby']['entities'][0].pop('native_living'),
            lambda o: o.state['nearby']['entities'][0]['native_living'].update(sample_age_ms=251.),
            lambda o: o.state['nearby']['entities'][0]['native_living'].update(source_tick=o.tick-6),
            lambda o: o.state['nearby']['entities'][0]['native_living'].update(world_generation='other'),
            lambda o: o.state['nearby']['entities'][0]['native_living'].update(known=False),
            lambda o: o.state['nearby']['entities'][0]['native_living'].update(coverage_complete=False),
            lambda o: o.state['nearby']['entities'][0]['native_living'].update(current_target_known=False),
            lambda o: o.state['nearby']['entities'][0]['native_living'].update(current_target=None),
            lambda o: o.state['nearby']['entities'][0].update(entity_id=True),
            lambda o: o.state['nearby']['entities'][0].update(type='minecraft:husk'),
            lambda o: o.state['nearby']['entities'][0].update(x=4.),
            lambda o: o.state['nearby']['entities'][0]['native_living']['current_target'].update(uuid=TARGET)]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                runtime = Runtime(change=change)
                out = self.run_route(runtime)
                self.assertEqual(out.status, 'blocked', out)
                self.assertFalse(runtime.actions)
                self.assertEqual(runtime.planning_reads, 0)

    def test_existing_health_inventory_motion_bounds_guards_precede_dispatch(self):
        for change in (lambda o: o.player.update(on_ground=False),
                       lambda o: o.player.update(health=12),
                       lambda o: o.player.update(inventory_truncated=True),
                       lambda o: o.player['velocity'].update(x=.1),
                       lambda o: o.state['movement_budget'].update(status='armed')):
            runtime = Runtime(change=change)
            self.assertEqual(self.run_route(runtime).status, 'blocked')
            self.assertFalse(runtime.actions)
            self.assertEqual(runtime.planning_reads, 0)
        runtime = Runtime()
        self.assertEqual(self.run_route(runtime, {'x': 7, 'y': 64, 'z': 0}).status, 'blocked')
        self.assertFalse(runtime.actions)

    def test_corridor_is_deterministic_flat_and_away(self):
        source = route.Block(0, 64, 0)
        for x, z, expected in ((1.5, .5, (-1, 0)), (-.5, .5, (1, 0)),
                               (.5, 2., (0, -1)), (.5, -2., (0, 1)),
                               (1.5, 1.5, (-1, 0)), (.5, .5, (1, 0))):
            actual = route._stop_only_corridor(source, {'x': .5, 'z': .5}, {'x': x, 'z': z})
            self.assertEqual(actual, source.offset(x=expected[0], z=expected[1]))

    def test_later_attacker_preserves_anchor_and_previous_segment(self):
        runtime = Runtime(later=True)
        out = self.run_route(runtime, {'x': 3, 'y': 64, 'z': 0})
        self.assertEqual(out.status, 'cancelled', out)
        self.assertEqual(out.evidence['completed_segments'], 1)
        self.assertEqual(out.evidence['original_source'], {'x': 0, 'y': 64, 'z': 0})
        self.assertEqual(runtime.planning_reads, 1)
        self.assertEqual(len(runtime.actions), 2)
        self.assertTrue(runtime.actions[-1]['route_stop_only'])
        self.assertIn('action-1', out.request_ids)
        self.assertIn('stop-only-1', out.request_ids)

    def test_later_changed_action_or_navigation_blocks_stop_only_dispatch(self):
        for field in ('action', 'navigation'):
            runtime = Runtime(later=True)
            def changed(obs):
                if runtime.actions:
                    if field == 'action': obs.state['client_action']['action_id'] = 'replacement'
                    else: obs.state['world']['navigation_guard']['epoch'] = 8
            runtime.change = changed
            out = self.run_route(runtime, {'x': 3, 'y': 64, 'z': 0})
            self.assertEqual(out.status, 'blocked', out)
            self.assertEqual(out.evidence['completed_segments'], 1)
            self.assertEqual(len(runtime.actions), 1)
            self.assertNotIn('route_stop_only', runtime.actions[0])
            self.assertEqual(runtime.planning_reads, 1)

    def test_exact_native_clock_and_distance_boundaries(self):
        def boundary(obs):
            row = obs.state['nearby']['entities'][0]
            row['x'] = obs.player['x']+3.
            row['native_living'].update(source_tick=obs.tick-5,
                sample_nano='100250000000', source_nano='100000000000', sample_age_ms=250.)
        runtime = Runtime(change=boundary)
        self.assertEqual(self.run_route(runtime).status, 'cancelled')
        self.assertEqual(len(runtime.actions), 1)
        for field, value in (('sample_nano', '100250000001'), ('source_nano', '99999999999'),
                             ('sample_age_ms', 250.000001)):
            def exceeded(obs):
                boundary(obs)
                obs.state['nearby']['entities'][0]['native_living'][field] = value
            runtime = Runtime(change=exceeded)
            self.assertEqual(self.run_route(runtime).status, 'blocked')
            self.assertFalse(runtime.actions)


if __name__ == '__main__': unittest.main()
