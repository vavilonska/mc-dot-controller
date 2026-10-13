import copy
import tempfile
import time
import unittest
from unittest.mock import patch

from mdcoord import Coordinator, Rejected, Acquisition
from mdcoord.advice import make_route_advice, route_candidate_from_advice
from mdcoord.planning import PlannerScheduler, PlannerWorker, seal_advice_candidate
from mdcoord.planning_benchmark import candidate_for, run_trial, summarize
from support import Clock, grant, publish, proposal


class SubmissionFenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.owner = Coordinator(self.temp.name, clock=self.clock)
        self.owner.activate(grant())
        publish(self.owner)
        self.scheduler = PlannerScheduler(self.owner.planner(), self.owner.lease_state, clock=self.clock)
        self.capture_number = 0

    def tearDown(self):
        self.scheduler.close(); self.owner.close(); self.temp.cleanup()

    def collect(self, kind='candidate'):
        def advice(request):
            return {'kind': 'route_goal', 'goal': {'x': 1.5, 'y': 64, 'z': .5},
                    'based_on': {'terrain': request.wire()['snapshot']['sections']['terrain']['content_revision']}}
        compute = advice if kind == 'advice' else candidate_for
        batch = self.scheduler.start([PlannerWorker('first', compute), PlannerWorker('second', compute)],
                                     budget_ms=3000, result_kind=kind)
        for _ in range(100):
            values = batch.collect()
            if values: return batch, values[0]
            time.sleep(.001)
        self.fail('worker did not return')

    def fresh(self):
        self.capture_number += 1
        return publish(self.owner, source='new-capture-' + str(self.capture_number), tick=10 + self.capture_number,
                       capture=Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(),
                                           1_700_000_000_000 + 1000 * self.capture_number, 10 + self.capture_number))

    def assert_no_dispatch(self):
        self.owner.advance()
        self.assertEqual(len(self.owner.executor.dispatches), 0)

    def test_audit_repro_delayed_submit_after_expiry_and_same_content_refresh(self):
        batch, ready = self.collect()
        old = ready.wire()
        self.assertEqual(old['planning_fence']['deadline_mono'], 103)
        batch.finish()
        self.clock.step(3.1); self.fresh()
        with self.assertRaises(Rejected): self.owner.planner().submit(old)
        self.assert_no_dispatch()

    def test_delayed_submit_without_finish_preserves_original_absolute_deadline(self):
        _, ready = self.collect()
        self.clock.step(3.1); self.fresh()
        with self.assertRaisesRegex(Rejected, 'planning_absolute_deadline_expired'):
            self.owner.planner().submit(ready.wire())
        self.assert_no_dispatch()

    def test_same_content_new_sample_before_deadline_requires_new_candidate(self):
        _, ready = self.collect()
        self.clock.step(.1); self.fresh()
        with self.assertRaisesRegex(Rejected, 'planning_source_sample_changed'):
            self.owner.planner().submit(ready.wire())
        self.assert_no_dispatch()

    def test_relative_ttl_cannot_extend_original_pending_deadline(self):
        _, ready = self.collect()
        self.clock.step(.5)
        self.owner.planner().submit(ready.wire())
        self.assertEqual(self.owner.pending[ready.request_id]['expires'], 103)
        self.clock.step(2.6); self.fresh()
        self.assert_no_dispatch()

    def test_finish_revokes_unsubmitted_candidates(self):
        batch, ready = self.collect(); batch.finish()
        with self.assertRaisesRegex(Rejected, 'planning_candidate_revoked'):
            self.owner.planner().submit(ready.wire())
        self.assert_no_dispatch()

    def test_submitted_candidate_survives_finish_but_not_deadline_extension(self):
        batch, ready = self.collect()
        self.clock.step(.1)
        self.owner.planner().submit(ready.wire()); batch.finish()
        self.owner.advance()
        self.assertEqual(len(self.owner.executor.dispatches), 1)
        self.owner.executor.finish(self.owner.active['action_id']); self.owner.advance()

    def test_missing_receipt_rejected_after_planning_gate_enabled(self):
        _, ready = self.collect()
        old = ready.wire(); del old['planning_fence']
        with self.assertRaisesRegex(Rejected, 'planning_source_receipt_required'):
            self.owner.planner().submit(old)
        # Changing the identity or role cannot downgrade to the legacy path.
        old['proposal_id'] = 'new-id'; old['role'] = 'legacy-looking-role'
        with self.assertRaisesRegex(Rejected, 'planning_source_receipt_required'):
            self.owner.planner().submit(old)
        self.assert_no_dispatch()

    def test_forged_deadline_ttl_and_identity_rejected(self):
        _, ready = self.collect()
        for change in ('deadline', 'ttl', 'identity'):
            old = ready.wire()
            if change == 'deadline': old['planning_fence']['deadline_mono'] += 100
            elif change == 'ttl': old['ttl_ms'] = 15_000
            else: old['proposal_id'] = 'forged-id'
            with self.assertRaises(Rejected): self.owner.planner().submit(old)
        self.assert_no_dispatch()

    def test_candidate_cannot_be_resealed_against_new_sample(self):
        _, ready = self.collect(); self.clock.step(.1); self.fresh()
        source = self.owner.planner().capture_planning_source()
        old = ready.wire(); del old['planning_fence']
        with self.assertRaisesRegex(Rejected, 'planning_candidate_already_sealed'):
            self.owner.planner().seal_planning_proposal(old, source['source_id'], self.clock() + 1)

    def test_forged_source_or_extended_deadline_cannot_be_sealed(self):
        source = self.owner.planner().capture_planning_source()
        with self.assertRaisesRegex(Rejected, 'planning_source_receipt_unknown'):
            self.owner.planner().seal_planning_proposal(proposal(self.owner), 'fake-source', 102)
        with self.assertRaisesRegex(Rejected, 'planning_deadline_extension'):
            self.owner.planner().seal_planning_proposal(proposal(self.owner), source['source_id'], 104)

    def test_lease_renewal_between_collect_and_submit_requires_replan(self):
        _, ready = self.collect(); lease = self.owner.lease_state()
        self.owner.renew(lease['epoch'], lease['revision'], 5000)
        with self.assertRaisesRegex(Rejected, 'planning_source_lease_revision'):
            self.owner.planner().submit(ready.wire())
        self.assert_no_dispatch()

    def test_accepted_candidate_continuous_lease_renewal_keeps_original_deadline(self):
        _, ready = self.collect(); self.owner.planner().submit(ready.wire())
        lease = self.owner.lease_state(); self.owner.renew(lease['epoch'], lease['revision'], 5000)
        self.assertEqual(self.owner.pending[ready.request_id]['expires'], 103)
        self.owner.advance(); self.assertEqual(len(self.owner.executor.dispatches), 1)
        self.owner.executor.finish(self.owner.active['action_id']); self.owner.advance()

    def test_advice_fresh_replan_delayed_submit_cannot_revive(self):
        _, advice = self.collect('advice'); self.clock.step(.1); self.fresh()
        sealed = seal_advice_candidate(advice, self.owner.planner(), budget_ms=500)
        self.clock.step(.6); self.fresh()
        with self.assertRaisesRegex(Rejected, 'planning_absolute_deadline_expired'):
            self.owner.planner().submit(sealed.wire())
        self.assert_no_dispatch()

    def test_advice_fresh_replan_positive(self):
        _, advice = self.collect('advice'); self.clock.step(.1); self.fresh()
        sealed = seal_advice_candidate(advice, self.owner.planner(), budget_ms=500)
        self.owner.planner().submit(sealed.wire()); self.owner.advance()
        self.assertEqual(len(self.owner.executor.dispatches), 1)
        self.owner.executor.finish(self.owner.active['action_id']); self.owner.advance()

    def test_raw_advice_replan_cannot_bypass_gate(self):
        _, advice = self.collect('advice'); self.clock.step(.1); fresh = self.fresh()
        raw = route_candidate_from_advice(advice, fresh, self.owner.lease_state())
        wrapped = {**proposal(self.owner), **raw}
        with self.assertRaisesRegex(Rejected, 'planning_source_receipt_required'):
            self.owner.planner().submit(wrapped)
        self.assert_no_dispatch()

    def test_receipt_from_different_owner_is_rejected(self):
        _, ready = self.collect()
        with tempfile.TemporaryDirectory() as directory:
            owner = Coordinator(directory, clock=self.clock)
            try:
                owner.activate(grant()); publish(owner)
                with self.assertRaisesRegex(Rejected, 'planning_receipt_unknown_or_changed'):
                    owner.planner().submit(ready.wire())
                self.assertEqual(owner.executor.dispatches, [])
            finally: owner.close()

    def test_legacy_owner_without_planning_mode_keeps_existing_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = Coordinator(directory, clock=self.clock)
            try:
                owner.activate(grant()); publish(owner)
                owner.planner().submit(proposal(owner)); owner.advance()
                self.assertEqual(len(owner.executor.dispatches), 1)
                owner.executor.finish(owner.active['action_id']); owner.advance()
            finally: owner.close()


class BenchmarkRegressionTests(unittest.TestCase):
    def test_bad_advice_first_does_not_lose_good_alternative(self):
        def transform(value, request, completed, source_lease):
            if request.wire()['role'] == 'short_route':
                value = {**value, 'goal': {'x': 99.5, 'y': 64, 'z': .5}}
            return make_route_advice(value, request, completed, source_lease)
        with patch('mdcoord.planning.make_route_advice', side_effect=transform):
            result = run_trial('parallel', source='controlled', workers=2, result_kind='advice')
        self.assertEqual(result['fake_dispatches'], 1)
        self.assertEqual(result['owner_rejections'], [{'reason': 'advice_goal_unavailable'}])

    def test_no_completed_advice_is_unknown_not_zero_expiry_rate(self):
        trial = {'mode': 'serial', 'native_host_evidence': [], 'events': [
            {'status': 'discarded', 'reason': 'planning_timeout', 'started_mono': 1},
            {'status': 'discarded', 'reason': 'planning_timeout', 'not_started': True}],
            'observation_to_first_safe_candidate_ms': None,
            'observation_to_first_fake_dispatch_ms': None, 'observation_to_batch_end_ms': 30000}
        result = summarize([trial], 'native')['modes']['serial']
        self.assertIsNone(result['source_expired_before_advice_return_rate'])
        self.assertEqual(result['started_events'], 1)
        self.assertEqual(result['completed_events'], 0)
        self.assertEqual(result['not_started_events'], 1)
