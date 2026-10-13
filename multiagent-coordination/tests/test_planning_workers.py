import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mdcoord import Coordinator, Rejected, Acquisition, Context, Proposal
from mdcoord.advice import PlanningAdvice, route_candidate_from_advice
from mdcoord.host_bridge import NativeHostBridge, complete, pending
from mdcoord.planning import PlannerScheduler, PlannerWorker
from mdcoord.planning_benchmark import candidate_for, distribution, run_trial
from support import Clock, grant, publish, sections, CONTEXT


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.owner = Coordinator(self.temp.name, clock=self.clock)
        self.owner.activate(grant())
        publish(self.owner)
        self.scheduler = PlannerScheduler(self.owner.planner(), self.owner.lease_state, clock=self.clock)
        self.releases = []

    def tearDown(self):
        for event in self.releases:
            event.set()
        self.scheduler.close()
        self.owner.close()
        self.temp.cleanup()

    def workers(self, first=None, second=None, origin='controlled_test'):
        return [PlannerWorker('short_route', first or candidate_for, origin),
                PlannerWorker('cautious_route', second or candidate_for, origin)]

    def collect_when_done(self, batch):
        for _ in range(100):
            result = batch.collect()
            if result or batch.finished or batch.exhausted:
                return result
            time.sleep(.001)
        self.fail('workers did not settle')

    def advice_value(self, request):
        return {'kind': 'route_goal', 'goal': {'x': 2.5, 'y': 64, 'z': .5},
                'based_on': {'terrain': request.wire()['snapshot']['sections']['terrain']['content_revision']}}

    def advice(self):
        batch = self.scheduler.start(self.workers(self.advice_value, self.advice_value), result_kind='advice')
        return self.collect_when_done(batch)[0]

    def fresh(self, raw=None):
        self.clock.step(.01)
        return publish(self.owner, source='fresh-independent', data=raw, tick=11,
                       capture=Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(), 1_700_000_001_000, 11))

    def test_computation_starts_inside_two_parallel_workers(self):
        barrier = threading.Barrier(2)
        def plan(request):
            barrier.wait(timeout=1)
            self.assertNotEqual(threading.get_ident(), self.scheduler._owner_thread)
            return candidate_for(request)
        batch = self.scheduler.start(self.workers(plan, plan))
        result = self.collect_when_done(batch)
        self.assertTrue(result)
        self.assertEqual(len(self.owner.executor.dispatches), 0)
        self.assertEqual(self.owner.pending, {})

    def test_identical_snapshot_bytes_and_mutation_isolation(self):
        values = []
        def plan(request):
            wire = request.wire()
            values.append((wire['snapshot_sha256'], wire['snapshot']['sections']['player']['data']['x']))
            wire['snapshot']['sections']['player']['data']['x'] = 999
            self.assertEqual(request.wire()['snapshot']['sections']['player']['data']['x'], .5)
            with self.assertRaises(Exception):
                request.encoded = b'changed'
            return candidate_for(request)
        batch = self.scheduler.start(self.workers(plan, plan))
        self.collect_when_done(batch)
        self.assertEqual(len(set(values)), 1)
        self.assertEqual(self.owner.snapshots.read()['sections']['player']['data']['x'], .5)

    def test_serial_launches_second_only_after_first_returns(self):
        release, started = threading.Event(), []
        self.releases.append(release)
        def first(request):
            started.append('first'); release.wait(1); return candidate_for(request)
        def second(request):
            started.append('second'); return candidate_for(request)
        batch = self.scheduler.start(self.workers(first, second), mode='serial')
        time.sleep(.01)
        self.assertEqual(started, ['first'])
        release.set(); self.collect_when_done(batch)
        for _ in range(100):
            if len(started) == 2: break
            time.sleep(.001)
        self.assertEqual(started, ['first', 'second'])

    def test_strict_count_two_or_three(self):
        for workers in ([], [PlannerWorker('one', candidate_for)], self.workers() * 2):
            with self.assertRaises(Rejected): self.scheduler.start(workers)

    def test_duplicate_role_rejected(self):
        with self.assertRaisesRegex(Rejected, 'duplicate_planner_role'):
            self.scheduler.start([PlannerWorker('same', candidate_for)] * 2)

    def test_second_batch_blocked_while_active(self):
        self.scheduler.start(self.workers())
        with self.assertRaisesRegex(Rejected, 'planning_batch_or_worker_still_active'):
            self.scheduler.start(self.workers())

    def test_lease_revision_change_rejects_completed_results(self):
        batch = self.scheduler.start(self.workers())
        lease = self.owner.lease_state()
        self.owner.renew(lease['epoch'], lease['revision'], 5000)
        self.assertEqual(batch.collect(), [])
        self.assertTrue(batch.finished)
        self.assertTrue(all(e['reason'] == 'planning_lease_fence' for e in batch.events))

    def test_context_switch_fences_all_results(self):
        batch = self.scheduler.start(self.workers())
        different = Context('minecraft:overworld', 'new-world', CONTEXT.player_id,
                            CONTEXT.action_session, CONTEXT.resident_session)
        publish(self.owner, source='new-context', context=different)
        self.assertEqual(batch.collect(), [])
        self.assertTrue(batch.finished)

    def test_changed_terrain_fences_candidate(self):
        batch = self.scheduler.start(self.workers())
        raw = sections(); raw['terrain']['cells'][0]['hazard'] = True
        self.fresh(raw)
        self.assertEqual(batch.collect(), [])
        self.assertTrue(batch.finished)

    def test_old_observation_expiry_not_revived_by_new_sample(self):
        batch = self.scheduler.start(self.workers(), budget_ms=5000)
        self.clock.step(3.1); self.fresh()
        self.assertEqual(batch.collect(), [])
        self.assertTrue(batch.finished)
        self.assertEqual(len(self.owner.executor.dispatches), 0)

    def test_result_cannot_forge_authority_or_ttl(self):
        def malicious(request):
            return {**candidate_for(request), 'ttl_ms': 15000, 'task_id': 'forged'}
        batch = self.scheduler.start(self.workers(malicious, malicious))
        self.assertEqual(self.collect_when_done(batch), [])
        self.assertTrue(all(e['status'] == 'rejected' for e in batch.events))

    def test_owner_supplies_identity_and_caps_ttl(self):
        batch = self.scheduler.start(self.workers(), budget_ms=800)
        candidates = self.collect_when_done(batch)
        wire = candidates[0].wire()
        self.assertEqual(wire['task_id'], 'test-task')
        self.assertLessEqual(wire['ttl_ms'], 800)
        self.assertEqual(wire['context'], CONTEXT.wire())

    def test_abstention_is_not_error(self):
        batch = self.scheduler.start(self.workers(lambda _: None, lambda _: None))
        self.assertEqual(self.collect_when_done(batch), [])
        self.assertTrue(all(e['status'] == 'abstained' for e in batch.events))

    def test_failed_planner_is_not_retried(self):
        calls = []
        def broken(_):
            calls.append(1); raise RuntimeError('private diagnostic')
        batch = self.scheduler.start(self.workers(broken, broken))
        self.assertEqual(self.collect_when_done(batch), [])
        self.assertEqual(len(calls), 2)
        self.assertNotIn('private diagnostic', str(batch.events))

    def test_worker_system_exit_is_contained(self):
        def broken(_): raise SystemExit(9)
        batch = self.scheduler.start(self.workers(broken, broken))
        self.assertEqual(self.collect_when_done(batch), [])
        self.assertTrue(all(e.get('reason') == 'planner_failed' for e in batch.events))

    def test_finish_discards_late_results(self):
        release = threading.Event(); self.releases.append(release)
        def delayed(request): release.wait(1); return candidate_for(request)
        batch = self.scheduler.start(self.workers(delayed, delayed))
        batch.finish(); release.set()
        self.assertEqual(batch.collect(), [])
        self.assertEqual(self.owner.pending, {})

    def test_no_replacement_while_old_workers_still_running(self):
        release = threading.Event(); self.releases.append(release)
        def delayed(request): release.wait(1); return candidate_for(request)
        batch = self.scheduler.start(self.workers(delayed, delayed))
        batch.finish()
        with self.assertRaisesRegex(Rejected, 'planning_batch_or_worker_still_active'):
            self.scheduler.start(self.workers())

    def test_collect_owner_thread_only(self):
        batch = self.scheduler.start(self.workers())
        errors = []
        def collect():
            try: batch.collect()
            except Rejected as exc: errors.append(str(exc))
        thread = threading.Thread(target=collect); thread.start(); thread.join()
        self.assertEqual(errors, ['planning_owner_thread_required'])

    def test_advice_cannot_parse_as_proposal(self):
        advice = self.advice()
        self.assertIs(type(advice), PlanningAdvice)
        self.assertFalse(advice.wire()['actionable'])
        with self.assertRaises(Rejected): Proposal.parse(advice.wire())

    def test_advice_survives_source_expiry_without_becoming_actionable(self):
        release = threading.Event(); self.releases.append(release)
        def plan(request): release.wait(1); return self.advice_value(request)
        batch = self.scheduler.start(self.workers(plan, plan), result_kind='advice', budget_ms=10000)
        self.clock.step(4); release.set()
        advice = self.collect_when_done(batch)[0]
        self.assertFalse(advice.wire()['actionable'])
        self.assertTrue(batch.events[0]['source_observation_expired_at_completion'])
        self.assertEqual(self.owner.pending, {})
        fresh = self.fresh()
        value = route_candidate_from_advice(advice, fresh, self.owner.lease_state())
        self.assertEqual(value['preconditions']['expected_position']['x'], .5)
        self.assertNotIn('proposal_id', value)

    def test_advice_requires_independent_observation(self):
        advice = self.advice()
        with self.assertRaisesRegex(Rejected, 'advice_independent_observation_required'):
            route_candidate_from_advice(advice, self.owner.snapshots.read(), self.owner.lease_state())

    def test_advice_task_fence(self):
        advice = self.advice(); fresh = self.fresh()
        with self.assertRaisesRegex(Rejected, 'advice_task_fence'):
            route_candidate_from_advice(advice, fresh, {'task_id': 'other', 'epoch': 'other'})

    def test_advice_uses_new_actual_player_position(self):
        advice = self.advice(); raw = sections(); raw['player']['x'] = 1.5
        value = route_candidate_from_advice(advice, self.fresh(raw), self.owner.lease_state())
        self.assertEqual(value['preconditions']['expected_position']['x'], 1.5)
        self.assertEqual(value['intent']['waypoints'], [{'x': 2.5, 'y': 64, 'z': .5}])

    def test_advice_changed_terrain_is_replanned_not_reused(self):
        advice = self.advice(); raw = sections()
        for cell in raw['terrain']['cells']:
            if cell['x'] == 1 and cell['y'] == 64: cell['hazard'] = True
        with self.assertRaisesRegex(Rejected, 'advice_no_safe_route'):
            route_candidate_from_advice(advice, self.fresh(raw), self.owner.lease_state())

    def test_advice_new_snapshot_must_be_fresh(self):
        advice = self.advice(); self.fresh(); self.clock.step(4)
        with self.assertRaisesRegex(Rejected, 'advice_new_observation_not_fresh'):
            route_candidate_from_advice(advice, self.owner.snapshots.read(), self.owner.lease_state())

    def test_advice_refuses_action_fields(self):
        def bad(request): return {**self.advice_value(request), 'intent': {'kind': 'attack'}}
        batch = self.scheduler.start(self.workers(bad, bad), result_kind='advice')
        self.assertEqual(self.collect_when_done(batch), [])


class HostBridgeTests(unittest.TestCase):
    def test_host_exchange_fenced_once_and_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            from mdcoord.planning import PlanningRequest
            from mdcoord.schema import canonical
            request = PlanningRequest(canonical({'request_id': 'native-test', 'snapshot_sha256': 'abc',
                                                 'result_kind': 'advice'}), time.monotonic() + 1)
            bridge = NativeHostBridge(directory)
            output = []
            def compute(): output.append(bridge.compute(request))
            with patch('socket.socket', side_effect=AssertionError('network forbidden')):
                thread = threading.Thread(target=compute); thread.start()
                for _ in range(100):
                    if pending(directory): break
                    time.sleep(.001)
                # Test-only transport exchange, not an actual model benchmark.
                complete(directory, 'native-test', None, 'transport-test-fixture')
                thread.join(1)
                self.assertEqual(output, [None])
                with self.assertRaises(FileExistsError):
                    complete(directory, 'native-test', None, 'transport-test-fixture')
                self.assertEqual(pending(directory), [])

    def test_preexisting_response_rejected(self):
        from mdcoord.planning import PlanningRequest
        from mdcoord.schema import canonical
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'native-test.response.json').write_text('{}')
            request = PlanningRequest(canonical({'request_id': 'native-test', 'snapshot_sha256': 'abc'}), time.monotonic() + 1)
            with self.assertRaisesRegex(Rejected, 'host_unrequested_response'):
                NativeHostBridge(directory).compute(request)

    def test_missing_native_task_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'request.request.json').write_text('{"request":{"snapshot_sha256":"abc"}}')
            with self.assertRaisesRegex(Rejected, 'host_native_task_evidence_required'):
                complete(directory, 'request', None, '')

    def test_small_sample_p95_is_not_reported(self):
        self.assertIsNone(distribution([1, 2, 3])['p95_ms'])
        self.assertEqual(distribution(range(20))['p95_ms'], 18)

    def test_end_to_end_fake_owner_gets_only_one_alternative(self):
        result = run_trial('parallel', source='controlled', workers=3)
        self.assertEqual(result['fake_dispatches'], 1)
        self.assertEqual(result['max_writers'], 1)
        self.assertEqual(result['real_game_actions'], 0)
        self.assertIsNotNone(result['observation_to_first_safe_candidate_ms'])

    def test_advice_end_to_end_independent_observation(self):
        result = run_trial('parallel', source='controlled', workers=2, result_kind='advice')
        self.assertEqual(result['fake_dispatches'], 1)
        self.assertEqual(result['independent_observation'], 'new_synthetic_capture')
        self.assertEqual(result['real_game_actions'], 0)
