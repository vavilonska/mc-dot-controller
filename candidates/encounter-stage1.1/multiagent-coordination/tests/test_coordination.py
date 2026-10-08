import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mdcoord import Coordinator, FakeExecutor, Rejected, ResidentAdapter
from mdcoord.executor import Receipt
from mdcoord.schema import Proposal
from support import CONTEXT, Clock, grant, player, proposal, publish, sections


class CoordinationChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock, self.executor = Clock(), FakeExecutor()
        self.owner = Coordinator(self.tmp.name, executor=self.executor, clock=self.clock)
        self.owner.activate(grant())
        publish(self.owner)

    def tearDown(self):
        self.owner.close()
        self.tmp.cleanup()

    def submit(self, **options):
        p = proposal(self.owner, **options)
        self.owner.propose(p)
        return p

    def finish(self, **options):
        self.executor.finish(self.owner.active['action_id'], **options)
        self.owner.advance()

    def test_submit_never_means_done(self):
        self.submit()
        self.assertEqual(self.executor.dispatches, [])
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['status'], 'running')
        self.assertFalse(self.owner.result('plan1')['server_confirmed'])
        self.finish()
        self.assertEqual(self.owner.result('plan1')['status'], 'succeeded')

    def test_multithreaded_duplicate_submission_and_dispatch_single_writer(self):
        p = proposal(self.owner)
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda _: self.owner.propose(p), range(40)))
            list(pool.map(lambda _: self.owner.advance(), range(40)))
        self.assertEqual(len(self.executor.dispatches), 1)
        self.assertEqual(self.executor.max_writers, 1)
        self.assertEqual(self.owner.metrics.snapshot()['counts']['duplicate_proposals'], 39)

    def test_duplicate_changed_payload_fails(self):
        p = self.submit(); p['role'] = 'other_role'
        with self.assertRaisesRegex(Rejected, 'payload_conflict'):
            self.owner.propose(p)
        self.assertEqual(self.executor.dispatches, [])

    def test_mutating_original_proposal_does_not_change_dispatch(self):
        p = self.submit(); p['intent']['waypoints'][0]['x'] = 99
        self.owner.advance()
        self.assertEqual(self.executor.dispatches[0][2]['waypoints'][0]['x'], 1.5)

    def test_dependency_preplanning_uses_fresh_actual_endpoint_no_new_model_plan(self):
        self.submit()
        self.submit(pid='plan2', start=1.5, end=2.5, dependencies=('plan1',))
        self.owner.advance()
        self.executor.finish(self.owner.active['action_id'])
        self.clock.step(.1)
        publish(self.owner, 'obs2', {'player': player(1.5)}, tick=11)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['status'], 'succeeded')
        self.assertEqual(self.owner.result('plan2')['status'], 'running')
        self.assertEqual(len(self.executor.dispatches), 2)

    def test_dependency_success_without_observed_endpoint_blocks_next_segment(self):
        self.submit()
        self.submit(pid='plan2', start=1.5, end=2.5, dependencies=('plan1',))
        self.owner.advance(); self.finish()
        self.assertEqual(self.owner.result('plan2')['reason'], 'expected_start_changed')
        self.assertEqual(len(self.executor.dispatches), 1)

    def test_expired_proposal_never_dispatches(self):
        p = proposal(self.owner); p['ttl_ms'] = 50
        self.owner.propose(p); self.clock.step(.051); self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'proposal_expired')
        self.assertFalse(self.executor.dispatches)

    def test_revision_conflict_rejected(self):
        self.submit()
        terrain = sections()['terrain']
        terrain['cells'][0]['block_id'] = 'minecraft:dirt'
        publish(self.owner, 'obs2', {'terrain': terrain})
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'revision_conflict')
        self.assertFalse(self.executor.dispatches)

    def test_world_or_player_or_action_session_change_rejected(self):
        for field, value in [('world_generation', 'new-world'), ('player_id', 'new-player'),
                             ('action_session', 'new-action-session'), ('resident_session', 'new-resident')]:
            with self.subTest(field=field):
                p = proposal(self.owner, pid='p-' + field)
                self.owner.propose(p)
                publish(self.owner, 'o-' + field, context=replace(CONTEXT, **{field: value}))
                self.owner.advance()
                self.assertEqual(self.owner.result(p['proposal_id'])['reason'], 'context_changed')
                publish(self.owner, 'reset-' + field)
        self.assertFalse(self.executor.dispatches)

    def test_foreign_role_name_cannot_authorize_action(self):
        self.owner.activate(grant(task_id='navigation-only', allowed_kinds=frozenset({'follow_path'})))
        p = proposal(self.owner, kind='defend_entity'); p['role'] = 'trusted_owner'
        with self.assertRaisesRegex(Rejected, 'intent_not_authorized'):
            self.owner.propose(p)

    def test_unknown_and_raw_commands_rejected(self):
        for kind in ('shell', 'command', 'chat', 'raw-key', 'text', 'click_slot', 'break_block'):
            p = proposal(self.owner); p['intent'] = {'kind': kind, 'timeout_ms': 1000}
            with self.subTest(kind=kind), self.assertRaises(Rejected):
                self.owner.propose(p)
        p = proposal(self.owner); p['intent']['shell'] = 'echo no'
        with self.assertRaises(Rejected):
            self.owner.propose(p)
        self.assertFalse(self.executor.dispatches)

    def test_old_epoch_or_lease_revision_rejected(self):
        old = proposal(self.owner)
        state = self.owner.lease_state()
        self.owner.renew(state['epoch'], state['revision'], 10_000)
        with self.assertRaisesRegex(Rejected, 'lease_revision_conflict'):
            self.owner.propose(old)
        p = proposal(self.owner); p['epoch'] = 'old-epoch'
        with self.assertRaisesRegex(Rejected, 'lease_epoch_conflict'):
            self.owner.propose(p)

    def test_renew_cas_and_hard_deadline(self):
        state = self.owner.lease_state(); deadline = state['task_deadline_mono']
        for _ in range(4):
            state = self.owner.renew(state['epoch'], state['revision'], 30_000)
            self.assertEqual(state['task_deadline_mono'], deadline)
            self.assertLessEqual(state['expires_mono'], deadline)
        with self.assertRaisesRegex(Rejected, 'lease_revision_conflict'):
            self.owner.renew(state['epoch'], 1, 1000)
        self.clock.step(20)
        with self.assertRaisesRegex(Rejected, 'lease_expired'):
            self.owner.renew(state['epoch'], state['revision'], 1000)

    def test_same_task_cannot_reset_budget_or_deadline(self):
        with self.assertRaisesRegex(Rejected, 'task_grant_cannot_restart'):
            self.owner.activate(grant())
        self.owner.close()
        self.owner = Coordinator(self.tmp.name, executor=self.executor, clock=self.clock)
        with self.assertRaisesRegex(Rejected, 'task_grant_cannot_restart'):
            self.owner.activate(grant())

    def test_total_execution_budget_reserved_not_refunded(self):
        self.owner.activate(grant(task_id='budgeted', execution_budget_ms=1000))
        self.submit(); self.owner.advance(); self.finish()
        self.submit(pid='plan2'); self.owner.advance()
        self.assertEqual(self.owner.result('plan2')['reason'], 'task_execution_budget')

    def test_task_action_budget(self):
        self.owner.activate(grant(task_id='one-action', max_actions=1))
        self.submit(); self.owner.advance(); self.finish()
        self.submit(pid='plan2'); self.owner.advance()
        self.assertEqual(self.owner.result('plan2')['reason'], 'task_action_budget')

    def test_dispatch_must_fit_remaining_lease(self):
        self.owner.activate(grant(task_id='short-lease', lease_ms=500))
        self.submit(); self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'action_exceeds_remaining_lease')

    def test_lost_dispatch_response_never_replays(self):
        self.executor.fail_after_dispatch = True
        p = self.submit(); self.owner.advance()
        for _ in range(5):
            self.owner.propose(p); self.owner.advance(); self.owner.reconcile()
        self.assertEqual(len(self.executor.dispatches), 1)
        self.assertTrue(self.owner.status()['recovery_blocked'])
        self.executor.finish(self.owner.active['action_id'])
        self.owner.reconcile()
        self.assertEqual(self.owner.result('plan1')['status'], 'succeeded')
        self.assertFalse(self.owner.status()['recovery_blocked'])

    def test_crash_recovery_has_no_lease_and_no_replay(self):
        self.submit(); self.submit(pid='plan2', dependencies=('plan1',))
        self.owner.advance(); active = dict(self.owner.active)
        self.owner.close()
        self.clock = Clock(); self.clock.now = 1  # unrelated new monotonic epoch
        self.owner = Coordinator(self.tmp.name, executor=self.executor, clock=self.clock)
        self.assertIsNone(self.owner.lease_state())
        self.assertEqual(self.owner.result('plan2')['status'], 'cancelled')
        self.assertEqual(self.owner.result('plan1')['status'], 'unknown')
        with self.assertRaisesRegex(Rejected, 'unreleased_action'):
            self.owner.activate(grant(task_id='new-task'))
        self.owner.advance(); self.owner.reconcile()
        self.assertEqual(len(self.executor.dispatches), 1)
        self.executor.finish(active['action_id']); self.owner.reconcile()
        self.assertEqual(self.owner.result('plan1')['status'], 'succeeded')
        self.assertNotIn('native_execution', self.owner.metrics.snapshot()['durations'])

    def test_crash_before_send_is_conservatively_unknown(self):
        self.submit()
        with patch.object(self.executor, 'dispatch', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.owner.advance()
        self.owner.close()
        self.owner = Coordinator(self.tmp.name, executor=self.executor, clock=self.clock)
        self.owner.reconcile()
        self.assertTrue(self.owner.status()['recovery_blocked'])
        self.assertFalse(self.executor.dispatches)

    def test_journal_failure_before_send_does_not_execute(self):
        self.submit()
        with patch.object(self.owner.journal, 'save', side_effect=OSError):
            with self.assertRaises(OSError):
                self.owner.advance()
        self.assertFalse(self.executor.dispatches)
        with self.assertRaisesRegex(Rejected, 'durability_fault'):
            self.owner.advance()

    def test_single_process_lock(self):
        with self.assertRaisesRegex(ValueError, 'owner_exists'):
            Coordinator(self.tmp.name, clock=self.clock)

    def test_defense_waits_for_confirmed_release_and_next_step(self):
        self.submit(); self.owner.advance()
        self.submit(pid='defense', kind='defend_entity', priority=100)
        self.owner.advance()
        self.assertEqual(len(self.executor.dispatches), 1)
        self.assertEqual(self.owner.result('plan1')['status'], 'cancelled')
        self.assertIsNone(self.owner.active)
        self.owner.advance()
        self.assertEqual(len(self.executor.dispatches), 2)
        self.assertEqual(self.owner.result('defense')['status'], 'running')

    def test_unconfirmed_cancel_blocks_preemption_and_is_not_retried(self):
        self.executor.cancel_confirms = False
        self.submit(); self.owner.advance()
        self.submit(pid='defense', kind='defend_entity', priority=100)
        self.owner.advance()
        for _ in range(4):
            self.owner.advance(); self.owner.reconcile(); self.owner.cancel_current()
        self.assertEqual(len(self.executor.cancellations), 1)
        self.assertEqual(len(self.executor.dispatches), 1)
        self.assertTrue(self.owner.status()['recovery_blocked'])
        self.assertEqual(self.owner.result('defense')['status'], 'cancelled')

    def test_preemption_budget_can_be_zero_without_bypassing_deadline_release(self):
        self.owner.activate(grant(task_id='no-preempt', max_cancellations=0))
        self.submit(); self.owner.advance()
        self.submit(pid='defense', kind='defend_entity', priority=100)
        self.owner.advance()
        self.assertFalse(self.executor.cancellations)
        self.clock.step(1.1); self.owner.advance()
        self.assertEqual(len(self.executor.cancellations), 1)

    def test_lease_expiry_cancels_owned_action_only_once(self):
        self.submit(); self.owner.advance(); self.clock.step(16)
        self.owner.advance(); self.owner.advance()
        self.assertEqual(len(self.executor.cancellations), 1)
        self.assertEqual(self.owner.result('plan1')['status'], 'cancelled')

    def test_failed_segment_cancels_ordinary_dependents(self):
        self.submit(); self.submit(pid='plan2', dependencies=('plan1',))
        self.owner.advance(); self.finish(status='failed', postcondition=False)
        self.assertEqual(self.owner.result('plan2')['status'], 'cancelled')

    def test_terminal_without_postcondition_not_success(self):
        self.submit(); self.owner.advance(); self.finish(postcondition=False)
        self.assertEqual(self.owner.result('plan1')['status'], 'failed')
        self.assertEqual(self.owner.result('plan1')['reason'], 'terminal_without_observed_postcondition')

    def test_terminal_without_input_release_blocks_new_writer(self):
        self.submit(); self.owner.advance(); self.finish(released=False)
        self.assertEqual(self.owner.result('plan1')['status'], 'unknown')
        self.assertTrue(self.owner.status()['recovery_blocked'])

    def test_mismatched_native_receipt_blocks(self):
        self.submit(); self.owner.advance()
        a = self.owner.active
        good = self.executor.receipts[a['action_id']]
        self.executor.receipts[a['action_id']] = replace(good, request_id='other')
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'receipt_identity_or_schema_mismatch')

    def test_queue_is_bounded(self):
        for i in range(32):
            self.submit(pid='plan' + str(i))
        with self.assertRaisesRegex(Rejected, 'queue_full'):
            self.submit(pid='overflow')

    def test_dependencies_cannot_reference_other_task(self):
        self.submit(); self.owner.activate(grant(task_id='another-task'))
        with self.assertRaisesRegex(Rejected, 'dependency_not_in_current_task'):
            self.submit(pid='plan2', dependencies=('plan1',))

    def test_dependency_cycles_cannot_be_admitted(self):
        with self.assertRaisesRegex(Rejected, 'dependency_not_in_current_task'):
            self.submit(pid='a', dependencies=('b',))
        with self.assertRaisesRegex(Rejected, 'invalid_dependency'):
            self.submit(pid='a', dependencies=('a',))

    def test_cancel_marker_is_never_dispatched(self):
        p = proposal(self.owner); p['cancel_requested'] = True
        self.owner.propose(p); self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['status'], 'cancelled')
        self.assertFalse(self.executor.dispatches)

    def test_outside_grant_bounds_rejected(self):
        with self.assertRaisesRegex(Rejected, 'outside_authorized_bounds'):
            self.submit(end=100.5)

    def test_planner_port_has_no_execution_or_owner_api(self):
        port = self.owner.planner()
        for method in ('activate', 'renew', 'advance', 'cancel_current', 'executor', 'journal'):
            self.assertFalse(hasattr(port, method))
        self.assertEqual(port.snapshot()['context'], CONTEXT.wire())

    def test_live_adapter_has_hard_gate(self):
        adapter = ResidentAdapter()
        self.assertEqual(adapter.prepare(proposal(self.owner)['intent'], CONTEXT)['op'], 'action')
        for method in ('dispatch', 'cancel', 'poll'):
            with self.assertRaisesRegex(RuntimeError, 'not_integrated'):
                getattr(adapter, method)()

    def test_non_dry_executor_rejected(self):
        class Live: dry_run = False
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(Rejected, 'live_executor_disabled'):
            Coordinator(tmp, executor=Live())

    def test_readers_do_not_trigger_dispatch_or_scan(self):
        before = self.owner.metrics.snapshot()
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda _: self.owner.planner().snapshot(), range(256)))
        self.assertEqual(before, self.owner.metrics.snapshot())
        self.assertFalse(self.executor.dispatches)


if __name__ == '__main__':
    unittest.main()
