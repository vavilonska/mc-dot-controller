from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from mdc_skills.core import Runtime, SkillError
from support_core import Clock, Client, move, arrived

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.client = Client(self.clock)
        self.runtime = Runtime(self.client, self.tmp.name, clock=self.clock, sleeper=self.clock.sleep)
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()
    def execute(self, **kwargs):
        return self.runtime.execute('reach', move(), arrived, **kwargs)
    def test_real_shaped_gateway_semantic_stable_result(self):
        result = self.execute()
        self.assertTrue(result.ok, result)
        self.assertEqual(self.client.action_count, 1)
        self.assertEqual(len(result.evidence['stable_game_times']), 2)
        self.assertFalse(result.evidence['server_confirmed'])
        command = next(c for c, _ in self.client.calls if c['op'] == 'action')
        self.assertEqual(command['capability_guard']['source_tick'], 101)
        self.assertEqual(command['expected_held_item']['item_fingerprint'], 'item-0')
        self.assertIsNone(self.runtime.pending_request_id)
    def test_unknown_submit_never_replayed_or_released(self):
        self.client.fail_after_submit = True
        result = self.execute()
        self.assertEqual(result.status, 'unknown')
        self.execute()
        self.assertEqual(self.client.action_count, 1)
        self.assertIsNotNone(self.runtime.pending_request_id)
    def test_pending_is_unknown_not_failure(self):
        self.client.mode = 'pending'
        result = self.execute()
        self.assertEqual(result.status, 'unknown')
        self.assertFalse(self.runtime.reconcile().ok)
        self.assertEqual(self.client.action_count, 1)
    def test_receipt_wrong_id_blocks(self):
        def patch(r):
            if 'action' in r['result']: r['result']['action']['action_id'] = 'wrong'
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().status, 'unknown')
    def test_false_release_blocks(self):
        def patch(r):
            if 'action' in r['result']: r['result']['action']['result']['input_release_confirmed'] = False
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().status, 'unknown')
    def test_handoff_wins_over_success(self):
        def patch(r):
            if 'action' in r['result']: r['requires_handoff'] = True
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().reason, 'receipt_requires_handoff_or_is_uncertain')
    def test_nested_uncertain_wins_over_success(self):
        def patch(r):
            if 'action' in r['result']: r['result']['action']['result']['post_uncertain'] = True
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().status, 'unknown')
    def test_native_failed_is_not_outer_success(self):
        def patch(r):
            if 'action' in r['result']: r['result']['action']['status'] = 'failed'
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().status, 'failed')
        self.assertIsNone(self.runtime.pending_request_id)
    def test_known_no_effect_rejection_is_blocked_without_unknown(self):
        def patch(r):
            if 'action' in r['result']:
                return {**r, 'status': 'failed', 'reason': 'capability_source_expired', 'result': {},
                    'action': None, 'action_id': None, 'cancellation': None,
                    'action_admission': {'schema_version': 1, 'http_status': 409, 'admitted': False,
                        'uncertain': False, 'reason': 'capability_source_expired'}}
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().status, 'blocked')
        self.assertIsNone(self.runtime.pending_request_id)
    def test_known_rejection_retains_submission_hash_and_native_diagnostics_without_retry(self):
        diagnostic = {'schema_version': 1, 'violations': ['tick_delta_exceeded'],
                      'source_tick': 101, 'current_tick': 107}
        def patch(r):
            if 'action' in r['result']:
                return {**r, 'status': 'failed', 'reason': 'capability_source_expired', 'result': {},
                    'action': None, 'action_id': None, 'cancellation': None,
                    'action_admission': {'schema_version': 1, 'http_status': 409, 'admitted': False,
                        'uncertain': False, 'reason': 'capability_source_expired',
                        'capability_source_freshness': deepcopy(diagnostic)}}
            return r
        self.client.patch_result = patch
        result = self.execute()
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(self.client.action_count, 1)
        self.assertEqual(result.evidence['submission_outcome'], 'known_no_effect_rejection')
        record = self.runtime._journal['records'][result.request_ids[0]]
        self.assertEqual(result.evidence['command_sha256'], record['command_sha256'])
        self.assertEqual(result.evidence['action_admission']['capability_source_freshness'], diagnostic)
        result.evidence['action_admission']['capability_source_freshness']['source_tick'] = 999
        self.assertEqual(record['evidence']['action_admission']['capability_source_freshness'], diagnostic)
        self.assertIsNone(self.runtime.pending_request_id)
    def test_absent_receipt_does_not_mean_no_effect(self):
        def patch(r):
            if 'action' in r['result']: r['result'].pop('action')
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().status, 'unknown')
    def test_focus_required_before_dispatch(self):
        self.client.patch_state = lambda s: {**s, 'focused': False}
        self.assertEqual(self.execute().status, 'blocked')
        self.assertEqual(self.client.action_count, 0)
    def test_private_singleplayer_required(self):
        self.client.patch_state = lambda s: {**s, 'private_singleplayer': False}
        self.assertEqual(self.execute().status, 'blocked')
    def test_old_observation_cannot_be_reclocked(self):
        before = self.runtime.observe()
        self.clock.now += .81
        self.assertEqual(self.execute(before=before).reason, 'preflight_observation_stale')
        self.assertEqual(self.client.action_count, 0)
    def test_mutated_observation_denied(self):
        before = self.runtime.observe()
        before.player['health'] = 999
        self.assertEqual(self.execute(before=before).reason, 'observation_modified_after_capture')
    def test_defense_epoch_change_does_not_rebind_old_plan(self):
        self.client.epoch = 4
        before = self.runtime.observe()
        self.client.epoch = 5
        self.assertEqual(self.execute(before=before).reason, 'defense_epoch_changed_requires_fresh_plan')
        self.assertEqual(self.client.action_count, 0)
    def test_same_tick_samples_do_not_confirm(self):
        self.client.patch_state = lambda s: {**s, 'world': {**s['world'], 'game_time': 101},
                                           'capability_guard': {**s['capability_guard'], 'source_tick': 101}}
        result = self.execute(max_samples=4)
        self.assertEqual(result.reason, 'postcondition_not_observed')
    def test_postcondition_failure_no_retry(self):
        result = self.runtime.execute('reach', move(), lambda a, b: False, max_samples=2)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(self.client.action_count, 1)
    def test_changed_player_after_action_stops(self):
        def patch(s):
            if self.client.action_count: s['player']['uuid'] = 'other'
            return s
        self.client.patch_state = patch
        self.assertEqual(self.execute().status, 'blocked')
    def test_later_sample_stale_does_not_verify(self):
        before = self.runtime.observe()
        original = self.client.wait
        def wait(rid, timeout):
            result = original(rid, timeout)
            if self.client.action_count and self.client.results[rid]['op'] == 'observe': self.clock.now += 1
            return result
        self.client.wait = wait
        self.assertEqual(self.execute(before=before).reason, 'observation_acquisition_stale')
    def test_single_process_owner(self):
        with self.assertRaisesRegex(SkillError, 'already_running'):
            Runtime(self.client, self.tmp.name)
    def test_closed_runtime_no_success(self):
        before = self.runtime.observe()
        self.runtime.close()
        with self.assertRaisesRegex(SkillError, 'runtime_closed'):
            self.runtime.result('read', (before,))
    def test_pending_runtime_no_already_success(self):
        before = self.runtime.observe()
        self.client.mode = 'pending'
        self.execute(before=before)
        with self.assertRaisesRegex(SkillError, 'unresolved_execution'):
            self.runtime.result('read', (before,))
    def test_restart_retains_unknown_identity_no_submit(self):
        self.client.mode = 'pending'
        self.execute()
        pending = self.runtime.pending_request_id
        self.runtime.close()
        self.runtime = Runtime(self.client, self.tmp.name, clock=self.clock, sleeper=self.clock.sleep)
        self.assertEqual(self.runtime.pending_request_id, pending)
        self.assertFalse(self.execute().ok)
        self.assertEqual(self.client.action_count, 1)
    def test_reconcile_exact_id_no_retry_or_semantic_success(self):
        self.client.mode = 'pending'
        self.execute()
        self.client.mode = None
        result = self.runtime.reconcile()
        self.assertEqual(result.reason, 'known_terminal_requires_fresh_goal_revalidation')
        self.assertFalse(result.ok)
        self.assertEqual(self.client.action_count, 1)
    def test_terrain_options_preserved(self):
        before = self.runtime.observe(terrain=True, radius=12, vertical=6, entity_radius=32)
        self.assertTrue(self.execute(before=before).ok)
        observes = [c for c, _ in self.client.calls if c['op'] == 'observe']
        self.assertTrue(all(c['radius'] == 12 and c['vertical'] == 6 and c['entity_radius'] == 32 for c in observes))
    def test_disallows_raw_inputs(self):
        result = self.runtime.execute('raw', {'op': 'direct', 'endpoint': 'key'}, arrived)
        self.assertEqual(result.reason, 'guarded_native_action_required')
        self.assertEqual(self.client.action_count, 0)
    def test_semantic_verifier_exception_keeps_barrier(self):
        def broken(a, b): raise ValueError('bad')
        result = self.runtime.execute('reach', move(), broken)
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(self.execute().reason, 'previous_semantic_result_requires_reconciliation')
        self.assertEqual(self.client.action_count, 1)
        self.assertFalse(self.runtime.reconcile().ok)
    def test_intent_persisted_before_submit(self):
        submit = self.client.submit
        def checked(command, request_id):
            data = json.loads((Path(self.tmp.name) / 'execution.json').read_text())
            self.assertEqual(data['pending'], request_id)
            self.assertEqual(data['records'][request_id]['command'], command)
            return submit(command, request_id)
        self.client.submit = checked
        self.assertTrue(self.execute().ok)
    def test_two_threads_cannot_interleave_mutations(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.execute())) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertTrue(all(r.ok for r in results))
        ops = [c['op'] for c, _ in self.client.calls]
        self.assertEqual(ops, ['observe', 'action', 'observe', 'observe'] * 2)

    def test_observation_current_handoff_rejects_success(self):
        def patch(r):
            r['result']['requires_handoff'] = True
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().reason, 'observation_requires_handoff_or_is_uncertain')
        self.assertEqual(self.client.action_count, 0)
    def test_observation_current_release_policy_rejects_success(self):
        def patch(r):
            r['result']['resident_policy'] = {'requires_handoff': False, 'input_release_unconfirmed': True}
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().reason, 'observation_requires_handoff_or_is_uncertain')
    def test_invalid_explicit_null_safety_flag_fails_closed(self):
        def patch(r):
            r['post_uncertain'] = None
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().status, 'blocked')
    def test_wrapper_release_contradiction_wins(self):
        def patch(r):
            if 'action' in r['result']: r['input_release_unconfirmed'] = True
            return r
        self.client.patch_result = patch
        self.assertEqual(self.execute().status, 'unknown')
    def test_original_navigation_origin_and_epoch_bound(self):
        self.assertTrue(self.execute().ok)
        command = next(c for c, _ in self.client.calls if c['op'] == 'action')
        self.assertEqual(command['expected_navigation_epoch'], 4)
        self.assertEqual(command['expected_origin'], {'x': .5, 'y': 64, 'z': .5})
    def test_historical_observation_mutation_is_rejected(self):
        older = self.runtime.observe()
        newer = self.runtime.observe()
        older.player['health'] = 19
        with self.assertRaisesRegex(SkillError, 'historical_observation_modified'):
            self.runtime.result('goal', [older, newer])

    def test_new_handoff_invalidates_still_young_older_snapshot(self):
        before = self.runtime.observe()
        def patch(r):
            r['result']['requires_handoff'] = True
            return r
        self.client.patch_result = patch
        with self.assertRaisesRegex(SkillError, 'observation_requires_handoff'):
            self.runtime.observe()
        self.client.patch_result = lambda r: r
        result = self.execute(before=before)
        self.assertEqual(result.reason, 'newer_observation_invalidated_preflight')
        self.assertEqual(self.client.action_count, 0)

if __name__ == '__main__': unittest.main()
