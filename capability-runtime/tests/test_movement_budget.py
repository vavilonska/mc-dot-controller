"""Native budget through real IntentClient -> Watchdog -> QueueClient -> Resident.

Only the terminal Bridge is synthetic. No game, live process, network, GUI,
credentials, runtime startup or native gameplay is exercised by these tests.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import base_watchdog
from watchdog import Watchdog
from intent_client import IntentClient
from resident_controller.controller import Resident
from resident_controller.transport import BridgeError
from mdc_skills.core import Runtime, SkillError
from mdc_skills.movement_budget import MovementBudgetRuntime
from test_gateway_integration import EndpointFixture
import test_capability_ownership as ownership
from support_core import NATIVE


class BudgetEndpoint(EndpointFixture):
    def __init__(self):
        super().__init__()
        self.meter = {"schema_version": 1, "status": "unarmed", "position_hook_seen": True, "move_hook_seen": True}
        self.patch_snapshot = lambda value: value
        self.position = .5
        self.settle = True
        self.corrupt_terminal = False
        self.corrupt_after_terminal_reads = None
        self.post_action_reads = 0
        self.coast_on_start = False

    def snapshot(self):
        value = super().snapshot()
        value['player']['x'] = self.position
        if self.coast_on_start and self.action.get('action') == 'movement_budget_start':
            self.meter.update(actual_distance=.25, remaining_distance=31.75, position_mutations=1)
            self.coast_on_start = False
        if self.meter['status'] in ('armed', 'stopping'):
            self.meter['boundary_samples'] += 1
            if self.settle:
                self.meter['settled_ticks'] = min(3, self.meter['settled_ticks'] + 1)
        value['movement_budget'] = deepcopy(self.meter)
        if self.action.get('status') == 'succeeded':
            self.post_action_reads += 1
        if (self.corrupt_after_terminal_reads is not None and self.action.get('action') == 'select_hotbar'
                and self.post_action_reads >= self.corrupt_after_terminal_reads):
            value['movement_budget']['coverage_complete'] = False
            value['movement_budget']['status'] = 'invalid'
        return self.patch_snapshot(value)

    def request(self, method, path, body=None):
        if path.startswith('/control/state?'):
            from urllib.parse import parse_qs, urlsplit
            value = super().request(method, path, body)
            value['nearby']['radius'] = int(parse_qs(urlsplit(path).query)['radius'][0])
            return value
        if path == '/control/action':
            self.posts.append((path, deepcopy(body)))
            if self.mode == 'reject':
                raise BridgeError('movement_budget_hooks_unverified', status=409, uncertain=False)
            name = body['action']
            if name == 'movement_budget_start':
                if self.meter['status'] != 'unarmed':
                    raise BridgeError('movement_budget_already_started', status=409, uncertain=False)
                self.meter = {'schema_version': 1, 'mode': 'dry_flat_self_walk_v1',
                    'bundle_id': body['movement_budget']['bundle_id'], 'action_session': NATIVE,
                    'world_generation': body['expected_world_generation'], 'player_uuid': body['expected_player_uuid'],
                    'status': 'armed', 'reason': 'armed', 'actual_distance': 0., 'max_distance': 32.,
                    'arm_origin': {'x': self.position, 'y': 64., 'z': .5},
                    'remaining_distance': 32., 'stop_reserve': 2., 'metric': 'client_self_move_polyline',
                    'coverage_complete': True, 'moving_accepted': True, 'covers_armed_interval_only': True,
                    'position_mutations': 0, 'boundary_samples': 0, 'settled_ticks': 3,
                    'started_nano': '100000000000', 'ended_nano': None, 'no_reset': True, 'all_cause_physical_cap': False}
                reason = 'movement_budget_started'
            else:
                if body.get('movement_budget_bundle_id') != self.meter.get('bundle_id'):
                    raise BridgeError('movement_budget_binding_changed', status=409, uncertain=False)
                reason = 'fixture_action_completed'
                if name == 'movement_budget_finish':
                    if self.meter['settled_ticks'] != 3:
                        raise BridgeError('movement_budget_not_settled', status=409, uncertain=False)
                    self.meter.update(status='sealed', reason='movement_budget_sealed', ended_nano='200000000000')
                    reason = 'movement_budget_sealed'
                elif name == 'follow_path':
                    self.position = body['waypoints'][-1]['x']
                    # Deliberately larger than endpoint displacement: native
                    # polyline can include same-tick back-and-forth travel.
                    self.meter['actual_distance'] += 2.5
                    self.meter['remaining_distance'] -= 2.5
                    self.meter['position_mutations'] += 8
                    self.meter['settled_ticks'] = 0
                elif name == 'select_hotbar':
                    self.selected = body['hotbar_slot']
            self.post_action_reads = 0
            self.action = {'action_schema_version': 1, 'action_session': NATIVE, 'action_id': body['action_id'],
                'action': name, 'status': 'running', 'reason': reason, 'server_confirmed': False,
                'result': {'input_release_confirmed': True, 'movement_budget': deepcopy(self.meter)}}
            if self.corrupt_terminal:
                self.action['result']['movement_budget']['bundle_id'] = 'forged'
            if self.mode == 'unknown':
                raise BridgeError('transport_failed', uncertain=True)
            return {**deepcopy(self.action), 'movement_budget': deepcopy(self.meter)}
        if path.startswith('/control/action/status'):
            self.action['status'] = 'succeeded'
            return {**deepcopy(self.action), 'movement_budget': deepcopy(self.meter)}
        return super().request(method, path, body)


class MovementBudgetChainTests(unittest.TestCase):
    until = ownership.ActualGatewayOwnershipTests.until
    def tearDown(self):
        self.runtime.close()
        ownership.ActualGatewayOwnershipTests.tearDown(self)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offline-native-budget-')
        self.root = Path(self.temp.name)
        self.bridge = BudgetEndpoint()
        self.resident = Resident(self.bridge, self.root / 'resident')
        self.resident.start()
        self.finished, self.resident_paused = threading.Event(), threading.Event()
        self.errors, self.queue_calls = [], []
        self.dog = None
        outer = self
        class CapturedWatchdog(Watchdog):
            def __init__(dog, q, **kwargs):
                submit = q.submit
                def record(command, request_id=None):
                    result = submit(command, request_id=request_id)
                    outer.queue_calls.append((result, deepcopy(command)))
                    return result
                q.submit = record
                super().__init__(q, **kwargs)
                outer.dog = dog
        def resident_loop():
            try:
                while not self.finished.is_set():
                    if not self.resident_paused.is_set():
                        self.resident.tick()
                    time.sleep(.005)
            except BaseException as exc:
                self.errors.append(exc)
        def watchdog_loop():
            try:
                base_watchdog.run(self.root / 'resident', self.root / 'watchdog',
                    watchdog_class=CapturedWatchdog, execution_policy='noncombat')
            except BaseException as exc:
                self.errors.append(exc)
        self.threads = [threading.Thread(target=resident_loop, daemon=True),
                        threading.Thread(target=watchdog_loop, daemon=True)]
        for thread in self.threads:
            thread.start()
        self.client = IntentClient(self.root / 'watchdog')
        self.until(lambda: self.client.session()['state'] == 'ready'
                   and self.client.session().get('capability_context') is not None)
        self.runtime = MovementBudgetRuntime(self.client, self.root / 'runtime', bundle_id='approved-case', wait_timeout=3)
        self.addCleanup(self.runtime.close)

    def posts(self):
        return [body for path, body in self.bridge.posts if path == '/control/action']

    def start(self):
        value = self.runtime.start()
        self.assertTrue(value.ok, value)
        return value

    def select(self, **extra):
        return self.runtime.execute('select', {'op': 'action', 'action': 'select_hotbar',
            'hotbar_slot': 1, 'timeout_ms': 1000, **extra}, lambda old, new: new.player['selected_slot'] == 1)

    def test_actual_chain_start_nested_actions_finish_and_exact_receipts(self):
        start = self.start()
        selected = self.select()
        self.assertTrue(selected.ok, selected)
        moved = self.runtime.execute('walk', {'op': 'action', 'action': 'follow_path',
            'waypoints': [{'x': 1.5, 'y': 64, 'z': .5}], 'timeout_ms': 1000},
            lambda old, new: new.player['x'] == 1.5)
        self.assertTrue(moved.ok, moved)
        self.assertEqual(self.runtime.movement_budget['actual_distance'], 2.5)
        self.assertEqual(self.runtime.movement_budget['position_mutations'], 8)
        finish = self.runtime.finish()
        self.assertTrue(finish.ok, finish)
        self.assertEqual(self.runtime.movement_budget['status'], 'sealed')
        for outcome in (start, selected, moved, finish):
            self.assertEqual(len(outcome.evidence['stable_game_times']), 2)
            self.assertLess(*outcome.evidence['stable_game_times'])
            receipt = self.client.result(outcome.request_ids[0])
            self.assertEqual(receipt['queue_session_id'], self.resident.session_id)
            self.assertNotEqual(receipt['queue_request_id'], outcome.request_ids[0])
        posts = self.posts()
        self.assertEqual([p['action'] for p in posts], ['movement_budget_start', 'select_hotbar', 'follow_path', 'movement_budget_finish'])
        self.assertEqual(posts[0]['movement_budget'], self.runtime.start_command()['movement_budget'])
        self.assertNotIn('movement_budget_bundle_id', posts[0])
        for body in posts:
            self.assertEqual(body['capability_guard']['schema_version'], 1)
            self.assertEqual(body['expected_action_session'], NATIVE)
            self.assertNotIn('_capability_owner_id', body)
        for body in posts[1:]:
            self.assertEqual(body['movement_budget_bundle_id'], 'approved-case')
        walk = posts[2]
        self.assertEqual(walk['expected_origin'], {'x': .5, 'y': 64, 'z': .5})
        self.assertIn('expected_navigation_epoch', walk)
        self.runtime.close()
        self.assertEqual(self.runtime.close_outcome.status, 'succeeded')
        self.assertIsNone(self.client.session()['capability_lease'])

    def test_action_receipt_preserves_opted_in_complete_entity_radius(self):
        self.start()
        before = self.runtime.observe(entity_radius=48)
        result = self.runtime.execute('wide-select', {'op': 'action', 'action': 'select_hotbar',
            'hotbar_slot': 1, 'entity_radius': 48, 'timeout_ms': 1000},
            lambda old, new: new.player['selected_slot'] == 1 and new.state['nearby']['radius'] == 48,
            before=before)
        self.assertTrue(result.ok, result)
        receipt = self.client.result(result.request_ids[0])
        self.assertEqual(receipt['result']['state']['nearby']['radius'], 48)
        self.assertEqual(result.last_observation.state['nearby']['radius'], 48)
        self.assertEqual(self.posts()[-1]['entity_radius'], 48)

    def test_neutral_coasting_during_start_is_retained_in_original_meter(self):
        self.bridge.coast_on_start = True
        self.start()
        self.assertEqual(self.runtime.movement_budget['actual_distance'], .25)
        self.assertEqual(self.runtime.movement_budget['position_mutations'], 1)
        self.assertTrue(self.runtime.finish().ok)
        self.assertEqual(self.runtime.movement_budget['actual_distance'], .25)

    def test_immutable_binding_and_public_commands_do_not_mutate_original(self):
        self.start()
        with self.assertRaises(FrozenInstanceError):
            self.runtime.binding.bundle_id = 'new'
        command = self.runtime.start_command()
        command['movement_budget']['bundle_id'] = 'new'
        self.assertEqual(self.runtime.start_command()['movement_budget']['bundle_id'], 'approved-case')
        meter = self.runtime.movement_budget
        meter['max_distance'] = 100
        self.assertEqual(self.runtime.movement_budget['max_distance'], 32)

    def test_duplicate_start_and_new_bundle_id_never_rearm(self):
        self.start()
        outcome = self.runtime.start()
        self.assertFalse(outcome.ok)
        self.assertEqual(len(self.posts()), 1)
        self.assertFalse(self.select(movement_budget_bundle_id='replacement').ok)
        self.assertFalse(self.runtime.finish().ok)
        self.assertEqual(len(self.posts()), 1)

    def test_direct_lifecycle_dispatch_is_rejected_and_latched_under_active_case(self):
        self.start()
        result = self.runtime.execute('rearm', self.runtime.start_command(), lambda old, new: True)
        self.assertFalse(result.ok)
        self.assertTrue(self.runtime.budget_failed)
        self.assertFalse(self.select().ok)
        self.assertFalse(self.runtime.finish().ok)
        self.assertEqual(len(self.posts()), 1)

    def test_conflicting_bundle_in_nested_action_never_reaches_queue(self):
        self.start()
        result = self.select(movement_budget_bundle_id='replacement')
        self.assertEqual(result.reason, 'movement_budget_bundle_id_conflict')
        self.assertTrue(self.runtime.budget_failed)
        self.assertEqual(len(self.posts()), 1)

    def test_unknown_start_never_retries_finishes_or_releases(self):
        self.bridge.mode = 'unknown'
        outcome = self.runtime.start()
        self.assertEqual(outcome.status, 'unknown', outcome)
        rid = self.runtime.pending_request_id
        self.assertTrue(rid)
        self.assertFalse(self.runtime.start().ok)
        self.assertFalse(self.runtime.finish().ok)
        self.assertFalse(self.select().ok)
        self.assertEqual(self.runtime.pending_request_id, rid)
        self.runtime.close()
        self.assertEqual(len(self.posts()), 1)
        # Retain Resident's existing one exact-ID cancellation after an
        # uncertain POST. The wrapper adds no cancellation or release/replay.
        self.assertEqual(len([p for p, _ in self.bridge.posts if p == '/control/action/cancel']), 1)
        self.assertFalse([p for p, _ in self.bridge.posts if p == '/control/release-all'])

    def test_known_no_effect_start_consumes_original_attempt_without_unknown(self):
        self.bridge.mode = 'reject'
        outcome = self.runtime.start()
        self.assertEqual((outcome.status, outcome.reason), ('blocked', 'movement_budget_hooks_unverified'))
        self.assertIsNone(self.runtime.pending_request_id)
        self.bridge.mode = 'success'
        self.assertFalse(self.runtime.start().ok)
        self.assertEqual(len(self.posts()), 1)

    def test_restart_and_new_id_rejected_by_durable_case_marker(self):
        self.start()
        self.runtime.close()
        for bundle_id in ('approved-case', 'new-case'):
            with self.assertRaisesRegex(SkillError, 'original_case_cannot_restart'):
                MovementBudgetRuntime(self.client, self.root / 'runtime', bundle_id=bundle_id)
        self.assertEqual(len(self.posts()), 1)
        marker = json.loads((self.root / 'runtime' / 'execution.json').read_text())['movement_budget']
        self.assertEqual(marker['bundle_id'], 'approved-case')

    def test_existing_native_bundle_blocks_new_journal_before_action(self):
        self.start()
        self.runtime.close()
        other = MovementBudgetRuntime(self.client, self.root / 'other', bundle_id='other-case', wait_timeout=3)
        try:
            self.assertFalse(other.start().ok)
            self.assertEqual(len(self.posts()), 1)
        finally:
            other.close()

    def test_exact_terminal_meter_binding_required(self):
        self.bridge.corrupt_terminal = True
        result = self.runtime.start()
        self.assertEqual(result.status, 'unknown', result)
        self.assertEqual(result.reason, 'movement_budget_binding_changed')
        self.assertFalse(self.runtime.start().ok)
        self.assertEqual(len(self.posts()), 1)

    def test_internal_semantic_sample_cannot_hide_invalid_native_meter(self):
        self.start()
        # Resident's terminal post-state remains valid; the Runtime's first
        # independent semantic sample is invalid, even if the verifier says yes.
        self.bridge.corrupt_after_terminal_reads = 2
        result = self.select()
        self.assertFalse(result.ok, result)
        self.assertEqual(result.reason, 'movement_budget_coverage_incomplete')
        self.assertTrue(self.runtime.budget_failed)
        self.assertFalse(self.runtime.finish().ok)
        self.assertEqual(len(self.posts()), 2)

    def test_inter_action_coasting_uses_native_counter_not_python_endpoint_distance(self):
        self.start()
        self.bridge.meter.update(actual_distance=1.75, remaining_distance=30.25, position_mutations=7)
        observation = self.runtime.observe()
        self.assertEqual(observation.player['x'], .5)
        self.assertEqual(self.runtime.movement_budget['actual_distance'], 1.75)
        self.assertTrue(self.runtime.finish().ok)

    def test_meter_regression_latches_and_blocks_success_and_cleanup(self):
        self.start()
        self.bridge.meter.update(actual_distance=1, remaining_distance=31, position_mutations=4)
        before = self.runtime.observe()
        self.bridge.meter.update(actual_distance=.5, remaining_distance=31.5, position_mutations=5)
        with self.assertRaisesRegex(SkillError, 'distance_regressed'):
            self.runtime.observe()
        with self.assertRaises(SkillError):
            self.runtime.result('forged-goal', [before])
        self.assertFalse(self.runtime.finish().ok)
        self.assertEqual(len(self.posts()), 1)

    def test_survey_meter_validation_blocks_incomplete_coverage(self):
        self.start()
        self.bridge.meter['coverage_complete'] = False
        with self.assertRaisesRegex(SkillError, 'movement_budget_coverage_incomplete'):
            self.runtime.survey(radius=3, vertical=2)
        self.assertEqual(len(self.posts()), 1)

    def test_finish_waits_read_only_for_neutral_settling_then_dispatches_once(self):
        self.start()
        self.bridge.meter['settled_ticks'] = 0
        before = self.runtime.observe()
        self.assertTrue(self.runtime.finish(before=before).ok)
        self.assertEqual([b['action'] for b in self.posts()], ['movement_budget_start', 'movement_budget_finish'])

    def test_finish_without_settling_never_dispatches_or_retries(self):
        self.start()
        self.bridge.settle = False
        self.bridge.meter['settled_ticks'] = 0
        result = self.runtime.finish()
        self.assertEqual(result.reason, 'movement_budget_finish_not_settled')
        self.assertFalse(self.runtime.finish().ok)
        self.assertEqual(len(self.posts()), 1)

    def test_sealed_meter_is_immutable_and_actions_cannot_continue(self):
        self.start()
        self.assertTrue(self.runtime.finish().ok)
        self.assertFalse(self.select().ok)
        self.bridge.meter['boundary_samples'] += 1
        with self.assertRaisesRegex(SkillError, 'sealed_snapshot_changed'):
            self.runtime.observe()
        self.assertEqual(len(self.posts()), 2)

    def test_session_restart_blocks_original_case(self):
        self.start()
        self.bridge.patch_snapshot = lambda state: {**state, 'client_action': {**state['client_action'], 'action_session': 'restarted'}}
        with self.assertRaises(SkillError):
            self.runtime.observe()
        self.assertFalse(self.select().ok)
        self.assertEqual(len(self.posts()), 1)

    def test_native_meter_contract_rejects_malformed_or_inconsistent_evidence(self):
        self.start()
        base = self.runtime.observe()
        for key, value in (
            ('schema_version', True), ('bundle_id', 'changed'), ('action_session', 'changed'),
            ('world_generation', 'changed'), ('player_uuid', 'changed'), ('max_distance', 64),
            ('actual_distance', float('nan')), ('actual_distance', 33), ('remaining_distance', 1),
            ('stop_reserve', 0), ('coverage_complete', False), ('moving_accepted', False),
            ('mode', 'different'), ('metric', 'sampled_displacement'), ('status', 'stopping'),
            ('status', 'invalid'), ('covers_armed_interval_only', False), ('no_reset', False),
            ('all_cause_physical_cap', True), ('position_mutations', True), ('boundary_samples', -1),
            ('position_mutations', 1), ('started_nano', 'changed'), ('started_nano', '101'),
            ('settled_ticks', 4), ('ended_nano', '200000000000'),
            ('arm_origin', None), ('arm_origin', {'x': .5, 'y': 64}),
            ('arm_origin', {'x': True, 'y': 64, 'z': .5}),
            ('arm_origin', {'x': .5, 'y': float('nan'), 'z': .5}),
            ('arm_origin', {'x': 2, 'y': 64, 'z': .5}),
        ):
            with self.subTest(key=key, value=value):
                state = deepcopy(base.state)
                state['movement_budget'][key] = value
                with self.assertRaises(SkillError):
                    self.runtime._check_meter(state)
        self.assertEqual(len(self.posts()), 1)

    def test_unknown_ordinary_action_cannot_be_replayed_or_finished(self):
        self.start()
        self.bridge.mode = 'unknown'
        result = self.select()
        self.assertEqual(result.status, 'unknown', result)
        original = self.runtime.pending_request_id
        self.assertFalse(self.select().ok)
        self.assertFalse(self.runtime.finish().ok)
        self.assertEqual(self.runtime.pending_request_id, original)
        self.assertEqual(len(self.posts()), 2)

    def test_unknown_finish_cannot_be_replayed_even_if_native_sealed(self):
        self.start()
        self.bridge.mode = 'unknown'
        result = self.runtime.finish()
        self.assertEqual(result.status, 'unknown', result)
        self.assertEqual(self.bridge.meter['status'], 'sealed')
        self.assertFalse(self.runtime.finish().ok)
        self.assertFalse(self.runtime.start().ok)
        self.assertEqual(len(self.posts()), 2)

    def test_older_meter_cannot_rewind_authoritative_distance_or_sealed_state(self):
        self.start()
        older = deepcopy(self.runtime.observe().state)
        self.bridge.meter.update(actual_distance=1., remaining_distance=31., position_mutations=4)
        self.runtime.observe()
        current = self.runtime.movement_budget
        for update in (False, True):
            with self.assertRaisesRegex(SkillError, 'sample_tick_regressed'):
                self.runtime._check_meter(older, update=update)
            self.assertEqual(self.runtime.movement_budget, current)
        self.assertEqual(self.runtime.binding.arm_origin, (.5, 64., .5))
        self.assertTrue(self.runtime.finish().ok)
        current = self.runtime.movement_budget
        with self.assertRaises(SkillError):
            self.runtime._check_meter(older, update=True)
        self.assertEqual(self.runtime.movement_budget, current)

    def test_changed_arm_origin_in_fresh_state_blocks_following_action(self):
        self.start()
        self.bridge.meter['arm_origin']['x'] += .5
        result = self.select()
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'movement_budget_arm_origin_changed')
        self.assertEqual(len(self.posts()), 1)

    def test_unarmed_missing_support_is_not_silently_downgraded(self):
        self.bridge.patch_snapshot = lambda state: {k: v for k, v in state.items() if k != 'movement_budget'}
        result = self.runtime.start()
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'native_movement_budget_missing')
        self.assertFalse(self.posts())


if __name__ == '__main__':
    unittest.main()
