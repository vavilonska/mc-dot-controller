"""Pure-object safety regressions. No Operator, QueueClient, filesystem or live I/O."""
import copy
import json
import math
from types import SimpleNamespace
import unittest

from encounter_health import HealthStopGuard


IDENTITY = {'world_generation': '11111111-1111-4111-8111-111111111111',
            'player_uuid': '22222222-2222-4222-8222-222222222222',
            'action_session': '33333333-3333-4333-8333-333333333333'}


def observation(health=20):
    return {'state': {'world': {'world_generation': IDENTITY['world_generation']},
                     'player': {'uuid': IDENTITY['player_uuid'], 'health': health},
                     'client_action': {'action_session': IDENTITY['action_session']}}}


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class HealthStopGuardTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.guard = HealthStopGuard(IDENTITY, clock=self.clock)

    def sample(self, health=20, phase='before', *, start=None, finish=None, obs=None):
        start = self.clock.now if start is None else start
        finish = start + .01 if finish is None else finish
        self.clock.now = finish
        return self.guard.record(observation(health) if obs is None else obs,
                                 start, finish, phase)

    def complete(self, health=20):
        self.sample(health)
        self.sample(health, 'running')
        self.sample(health, 'after')
        return self.guard.report(final=True)

    def test_missing_baseline_blocks_before_submission(self):
        report = self.guard.report()
        self.assertTrue(report['stop_required'])
        self.assertFalse(report['ready_to_submit'])
        self.assertFalse(report['controller_same_owner_stop_required'])
        self.assertFalse(report['stop_latched'])

    def test_valid_baseline_allows_only_initial_submission(self):
        self.assertTrue(self.sample()['ready_to_submit'])
        self.assertFalse(self.sample(20, 'running')['ready_to_submit'])

    def test_stable_chain_never_proves_continuous_or_active_ai_acceptance(self):
        report = self.complete()
        self.assertFalse(report['stop_required'])
        self.assertTrue(report['sampled_health_window_complete'])
        self.assertTrue(report['no_decrease_observed'])
        for key in ('continuous_health_coverage_proven', 'absence_of_damage_proven',
                    'hard_realtime_stop_proven', 'controlled_trial_accepted',
                    'full_active_ai_acceptance', 'safety_assured'):
            self.assertIs(report[key], False, key)

    def test_point_zero_one_damage_above_native_threshold_stops(self):
        self.sample()
        report = self.sample(19.99, 'running')
        self.assertTrue(report['stop_required'])
        self.assertEqual(report['status'], 'STOPPED-SAFETY')
        self.assertIn('health_decrease_observed', report['reasons'])
        self.assertTrue(report['controller_same_owner_stop_required'])

    def test_no_epsilon_allows_smallest_representable_decrease(self):
        self.sample()
        report = self.sample(math.nextafter(20, 0), 'running')
        self.assertTrue(report['decrease_observed'])

    def test_healing_cannot_reset_latch(self):
        self.sample()
        self.sample(19.99, 'running')
        self.sample(20, 'running')
        self.sample(20, 'after')
        report = self.guard.report(final=True)
        self.assertTrue(report['stop_latched'])
        self.assertIsNone(report['no_decrease_observed'])
        self.assertFalse(report['controlled_trial_accepted'])

    def test_decrease_above_original_baseline_after_healing_stops(self):
        self.sample(17)
        self.sample(20, 'running')
        report = self.sample(19.99, 'running')
        self.assertTrue(report['decrease_observed'])
        self.assertEqual(report['baseline_health'], 17)

    def test_second_before_decrease_blocks_submission(self):
        self.sample()
        report = self.sample(19.99)
        self.assertFalse(report['ready_to_submit'])
        self.assertTrue(report['stop_latched'])

    def test_final_health_decrease_overrides_terminal_success_race(self):
        self.sample()
        self.sample(20, 'running')
        obs = observation(19.99)
        obs['action'] = {'status': 'succeeded', 'reason': 'encounter_clearance_observed'}
        self.sample(phase='after', obs=obs)
        report = self.guard.report(final=True)
        self.assertTrue(report['stop_required'])
        self.assertFalse(report['controlled_trial_accepted'])
        self.assertEqual(obs['action']['status'], 'succeeded')

    def test_missing_running_window_cannot_invent_fast_winner_coverage(self):
        self.sample()
        report = self.sample(20, 'after')
        self.assertIn('health_running_observation_window_missing', report['reasons'])
        self.assertTrue(self.guard.report(final=True)['stop_required'])

    def test_final_report_without_after_latches_incomplete_evidence(self):
        self.sample()
        self.sample(20, 'running')
        report = self.guard.report(final=True)
        self.assertIn('health_after_observation_window_missing', report['reasons'])
        self.assertFalse(report['sampled_health_window_complete'])

    def test_running_before_baseline_never_establishes_baseline(self):
        report = self.sample(20, 'running')
        self.assertIsNone(report['baseline_health'])
        self.assertTrue(report['stop_latched'])

    def test_missing_health_before_latches_even_after_valid_recovery(self):
        obs = observation()
        del obs['state']['player']['health']
        self.sample(obs=obs)
        report = self.sample()
        self.assertTrue(report['stop_required'])
        self.assertFalse(report['ready_to_submit'])

    def test_invalid_health_values_never_count_as_clean_samples(self):
        for value in (None, True, False, '20', float('nan'), float('inf'),
                      -float('inf'), -1, [], {}, 10 ** 1000):
            with self.subTest(value=repr(value)[:40]):
                guard = HealthStopGuard(IDENTITY, clock=self.clock)
                report = guard.record(observation(value), 0, 0, 'before')
                self.assertTrue(report['stop_required'])
                self.assertIsNone(report['baseline_health'])
                json.dumps(report, allow_nan=False)

    def test_zero_health_is_a_stop_even_as_first_baseline(self):
        self.assertIn('health_zero_observed', self.sample(0)['reasons'])

    def test_missing_running_health_requests_owner_stop(self):
        self.sample()
        report = self.sample(None, 'running')
        self.assertTrue(report['controller_same_owner_stop_required'])
        self.assertFalse(report['stop_authority_granted'])
        self.assertFalse(report['automatic_cancel'])
        self.assertFalse(report['automatic_escape'])

    def test_observation_request_exception_latches(self):
        self.sample()
        report = self.guard.mark_unknown('observe_timeout', phase='running')
        self.assertTrue(report['controller_same_owner_stop_required'])
        self.sample(20, 'running')
        self.sample(20, 'after')
        self.assertTrue(self.guard.report(final=True)['stop_required'])

    def test_identity_changes_are_not_new_baselines(self):
        paths = (('world', 'world_generation'), ('player', 'uuid'),
                 ('client_action', 'action_session'))
        for part, key in paths:
            with self.subTest(part=part):
                clock = Clock()
                guard = HealthStopGuard(IDENTITY, clock=clock)
                guard.record(observation(), 0, 0, 'before')
                obs = observation(21)
                obs['state'][part][key] = 'changed'
                report = guard.record(obs, 0, 0, 'running')
                self.assertIn('health_observation_identity_mismatch', report['reasons'])
                self.assertEqual(report['latest_health'], 20)

    def test_malformed_nested_observations_fail_closed(self):
        for obs in (None, [], {}, {'state': None}, {'state': []},
                    {'state': {'player': []}}, {'state': {'world': None}}):
            with self.subTest(observation=obs):
                guard = HealthStopGuard(IDENTITY, clock=self.clock)
                report = guard.record(obs, 0, 0, 'before')
                self.assertTrue(report['stop_required'])
                self.assertIsNone(report['no_decrease_observed'])

    def test_long_request_cannot_be_a_covered_baseline(self):
        report = self.sample(start=0, finish=1.01)
        self.assertIn('health_observation_request_too_long', report['reasons'])
        self.assertFalse(report['ready_to_submit'])

    def test_long_local_gap_stops_with_unchanged_health(self):
        self.sample()
        report = self.sample(20, 'running', start=2, finish=2.01)
        self.assertIn('health_local_observation_gap', report['reasons'])
        self.assertIsNone(report['no_decrease_observed'])

    def test_stale_baseline_is_blocked_before_submission_without_new_read(self):
        self.sample()
        self.clock.now += 2
        report = self.guard.report()
        self.assertFalse(report['ready_to_submit'])
        self.assertIn('health_local_observation_gap', report['reasons'])

    def test_running_stall_detected_by_report_without_new_read(self):
        self.sample()
        self.sample(20, 'running')
        self.clock.now += 2
        self.assertTrue(self.guard.report()['controller_same_owner_stop_required'])

    def test_final_snapshot_does_not_claim_future_monitoring(self):
        self.complete()
        self.clock.now += 100
        report = self.guard.report()
        self.assertFalse(report['stop_required'])
        self.assertFalse(report['continuous_health_coverage_proven'])

    def test_interval_clock_reversal_stops(self):
        report = self.sample(start=1, finish=.5)
        self.assertIn('health_clock_reversal', report['reasons'])

    def test_clock_reversal_between_reports_stops(self):
        self.sample(start=1, finish=1.1)
        self.clock.now = 1.09
        self.assertIn('health_clock_reversal', self.guard.report()['reasons'])

    def test_overlapping_requests_do_not_prove_ordered_health(self):
        self.sample(start=1, finish=1.1)
        report = self.sample(20, 'running', start=1.05, finish=1.2)
        self.assertIn('health_observation_interval_overlap_or_reversal', report['reasons'])

    def test_invalid_intervals_fail_closed_and_report_remains_json_safe(self):
        for start, finish in ((True, 1), (0, float('nan')), (0, None),
                              ('0', 1), (0, float('inf')), (-1, 0), (0, 10 ** 1000)):
            with self.subTest(start=start, finish=str(finish)[:40]):
                guard = HealthStopGuard(IDENTITY, clock=self.clock)
                report = guard.record(observation(), start, finish, 'before')
                self.assertTrue(report['stop_required'])
                json.dumps(report, allow_nan=False)

    def test_invalid_clock_and_clock_exception_fail_closed(self):
        def bad_clock():
            raise RuntimeError('offline fake clock failure')
        for clock in (lambda: None, lambda: True, lambda: float('nan'), bad_clock):
            with self.subTest(clock=clock):
                guard = HealthStopGuard(IDENTITY, clock=clock)
                self.assertTrue(guard.record(observation(), 0, 0, 'before')['stop_required'])

    def test_phase_reversal_and_invalid_phase_stop(self):
        self.sample()
        self.sample(20, 'running')
        self.assertIn('health_phase_reversal', self.sample()['reasons'])
        self.assertIn('health_phase_invalid', self.sample(phase='unknown')['reasons'])

    def test_damage_and_unknown_both_retained(self):
        self.sample()
        self.sample(19.99, 'running')
        self.guard.mark_unknown('lost_read', phase='running')
        self.sample(20, 'running')
        report = self.guard.report()
        self.assertIn('health_decrease_observed', report['reasons'])
        self.assertIn('health_observation_unknown', report['reasons'])
        self.assertEqual(report['decrease_count'], 1)

    def test_timing_gap_does_not_hide_simultaneous_observed_damage(self):
        self.sample()
        report = self.sample(19.99, 'running', start=2, finish=2.01)
        self.assertIn('health_local_observation_gap', report['reasons'])
        self.assertIn('health_decrease_observed', report['reasons'])

    def test_mark_unknown_normalizes_invalid_arguments(self):
        report = self.guard.mark_unknown(None, phase=object())
        self.assertIn('health_observation_unknown', report['reasons'])
        self.assertIn('health_phase_invalid', report['reasons'])
        json.dumps(report, allow_nan=False)

    def test_explicit_report_clock_checks_stale_baseline(self):
        self.sample()
        report = self.guard.report(now_monotonic=5)
        self.assertTrue(report['stop_required'])
        self.assertFalse(report['ready_to_submit'])

    def test_larger_outer_gap_limit_never_proves_continuous_coverage(self):
        guard = HealthStopGuard(IDENTITY, clock=self.clock, max_gap_seconds=2)
        for phase, now in (('before', 0), ('running', 1.5), ('after', 3)):
            self.clock.now = now
            guard.record(observation(), now, now, phase)
        report = guard.report(final=True)
        self.assertFalse(report['stop_required'])
        self.assertFalse(report['continuous_health_coverage_proven'])
        self.assertFalse(report['full_active_ai_acceptance'])

    def test_identity_and_reports_are_isolated_from_caller_mutation(self):
        identity = copy.deepcopy(IDENTITY)
        guard = HealthStopGuard(identity, clock=self.clock)
        identity['player_uuid'] = 'changed'
        guard.identity['player_uuid'] = 'changed'
        obs = observation()
        report = guard.record(obs, 0, 0, 'before')
        obs['state']['player']['health'] = 1
        report['identity']['player_uuid'] = 'changed'
        report['samples'][0]['health'] = 1
        self.assertEqual(guard.report()['samples'][0]['health'], 20)
        self.assertEqual(guard.identity, IDENTITY)

    def test_binding_like_identity_is_supported(self):
        guard = HealthStopGuard(SimpleNamespace(**IDENTITY), clock=self.clock)
        self.assertEqual(guard.identity, IDENTITY)

    def test_invalid_configuration_is_rejected(self):
        for identity in ({}, None, {**IDENTITY, 'player_uuid': True}):
            with self.subTest(identity=identity):
                with self.assertRaisesRegex(ValueError, 'identity'):
                    HealthStopGuard(identity, clock=self.clock)
        for limit in (0, -1, True, '1', float('inf'), float('nan')):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(ValueError, 'gap_limit'):
                    HealthStopGuard(IDENTITY, clock=self.clock, max_gap_seconds=limit)
        with self.assertRaisesRegex(ValueError, 'clock'):
            HealthStopGuard(IDENTITY, clock=None)

    def test_finalization_does_not_allow_more_samples_or_submission(self):
        report = self.complete()
        self.assertFalse(report['ready_to_submit'])
        report = self.sample(20, 'after')
        self.assertIn('health_observation_after_finalization', report['reasons'])

    def test_native_health_loss_threshold_is_not_a_dependency(self):
        self.sample()
        obs = observation(19.99)
        obs['action'] = {'result': {'combat': {'player_health_lost_observed': 0}}}
        report = self.sample(phase='running', obs=obs)
        self.assertTrue(report['decrease_observed'])
        self.assertTrue(report['stop_required'])


if __name__ == '__main__':
    unittest.main()
