"""Offline continuity/renewal regression; every execution is FakeExecutor only."""
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mdcoord import Acquisition, Coordinator, Rejected
from support import Clock, grant, player, proposal, publish, sections


class SafeRenewalChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.owner = Coordinator(self.temp.name, clock=self.clock)
        self.owner.activate(grant())
        publish(self.owner)

    def tearDown(self):
        self.owner.close()
        self.temp.cleanup()

    def renew(self, ms=15000):
        state = self.owner.lease_state()
        return self.owner.renew(state['epoch'], state['revision'], ms)

    def queue(self, pid='route', **kwargs):
        plan = proposal(self.owner, pid, **kwargs)
        self.owner.propose(plan)
        return plan

    def test_safe_renewal_preserves_all_roles_and_original_encoded_evidence(self):
        route = self.queue()
        self.queue('defense', kind='defend_entity', priority=100)
        before = copy.deepcopy(self.owner.pending)
        digests = {pid: r['digest'] for pid, r in self.owner.records.items()}
        lease_before = self.owner.lease_state()
        self.clock.step(.1)
        lease = self.renew()
        self.assertEqual(set(self.owner.pending), {'route', 'defense'})
        for pid, entry in self.owner.pending.items():
            for field in ('proposal', 'received', 'expires', 'authority', 'observation_basis', 'threat_proof_id'):
                self.assertEqual(entry.get(field), before[pid].get(field))
            self.assertEqual(entry['validated_lease_revision'], lease['revision'])
            self.assertEqual(self.owner.records[pid]['digest'], digests[pid])
            self.assertEqual(self.owner.result(pid)['status'], 'queued')
        self.assertEqual(lease['task_deadline_mono'], lease_before['task_deadline_mono'])
        self.assertEqual(lease['reserved_execution_ms'], lease_before['reserved_execution_ms'])
        self.assertEqual(self.owner.propose(route)['status'], 'queued')
        self.owner.advance()
        self.assertEqual(self.owner.result('defense')['status'], 'running')
        self.assertEqual(len(self.owner.executor.dispatches), 1)

    def test_queued_route_dispatches_after_multiple_continuous_renewals(self):
        self.queue()
        for _ in range(6):
            self.clock.step(.01)
            self.renew()
        self.owner.advance()
        self.assertEqual(self.owner.result('route')['status'], 'running')
        self.assertEqual(self.owner.executor.max_writers, 1)

    def test_new_submission_with_old_revision_still_fails(self):
        plan = proposal(self.owner, 'not-yet-received')
        self.renew()
        with self.assertRaisesRegex(Rejected, 'lease_revision_conflict'):
            self.owner.propose(plan)

    def test_wrong_cas_does_not_touch_queue(self):
        self.queue()
        old = copy.deepcopy(self.owner.pending)
        state = self.owner.lease_state()
        with self.assertRaisesRegex(Rejected, 'lease_revision_conflict'):
            self.owner.renew(state['epoch'], state['revision'] + 1, 1000)
        self.assertEqual(self.owner.pending, old)

    def test_expired_proposal_cannot_be_revived_by_renewal(self):
        plan = proposal(self.owner, 'expired'); plan['ttl_ms'] = 50
        self.owner.propose(plan)
        self.clock.step(.05)
        self.renew()
        self.assertEqual(self.owner.result('expired')['reason'], 'proposal_expired')
        self.assertNotIn('expired', self.owner.pending)
        publish(self.owner, 'new-sample', tick=11)
        self.assertEqual(self.owner.propose(plan)['status'], 'rejected')
        self.owner.advance()
        self.assertFalse(self.owner.executor.dispatches)

    def test_original_lease_capped_proposal_deadline_never_extends(self):
        self.owner.activate(grant(task_id='short', lease_ms=1200))
        plan = self.queue()
        expiry = self.owner.pending['route']['expires']
        self.clock.step(.1); self.renew(15000)
        self.assertEqual(self.owner.pending['route']['expires'], expiry)
        self.clock.step(1.101); self.owner.advance()
        self.assertEqual(self.owner.result('route')['reason'], 'proposal_expired')
        self.assertFalse(self.owner.executor.dispatches)

    def test_expired_lease_revokes_entire_queue_and_cannot_restart(self):
        self.queue(); state = self.owner.lease_state()
        self.clock.step(15)
        with self.assertRaisesRegex(Rejected, 'lease_expired'):
            self.owner.renew(state['epoch'], state['revision'], 15000)
        self.assertFalse(self.owner.pending)
        self.assertEqual(self.owner.result('route')['reason'], 'lease_expired')
        self.assertFalse(self.owner.executor.dispatches)

    def test_permission_replacement_cannot_keep_queue(self):
        self.queue()
        self.owner.activate(grant(task_id='replacement', allowed_kinds=frozenset({'follow_path'})))
        self.assertFalse(self.owner.pending)
        self.assertEqual(self.owner.result('route')['reason'], 'task_replaced')

    def test_fault_injected_owner_epoch_or_grant_change_is_fail_closed(self):
        for field in ('owner', 'grant', 'epoch', 'in-place-grant', 'task-deadline', 'in-place-context'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                owner = Coordinator(temp, clock=Clock()); self.addCleanup(owner.close)
                owner.activate(grant()); publish(owner); owner.propose(proposal(owner))
                lease = owner.lease_state()
                if field == 'owner': owner.epoch = 'another-owner'
                if field == 'epoch': owner.lease.epoch = 'another-epoch'
                if field == 'grant': owner.lease.grant = replace(owner.lease.grant, execution_budget_ms=600000)
                if field == 'in-place-grant': object.__setattr__(owner.lease.grant, 'allowed_kinds', frozenset({'defend_entity'}))
                if field == 'task-deadline': owner.lease.deadline += 1000
                if field == 'in-place-context':
                    # Copy shared fixture context first, then mutate only this owner grant.
                    object.__setattr__(owner.lease.grant, 'context', replace(owner.lease.grant.context))
                    object.__setattr__(owner.lease.grant.context, 'world_generation', 'altered-world')
                with self.assertRaisesRegex(Rejected, 'lease_authority_changed'):
                    owner.renew(lease['epoch'], lease['revision'], 15000)
                self.assertFalse(owner.pending)
                self.assertFalse(owner.executor.dispatches)

    def test_restart_cancels_renewed_queue_never_restores_grant(self):
        self.queue(); self.renew()
        self.owner.close()
        self.owner = Coordinator(self.temp.name, clock=self.clock)
        self.assertEqual(self.owner.result('route')['reason'], 'owner_restarted_no_replay')
        self.assertIsNone(self.owner.lease)
        self.assertFalse(self.owner.pending)
        self.assertFalse(self.owner.executor.dispatches)

    def test_renew_durability_failure_cannot_dispatch_retained_queue(self):
        self.queue()
        with patch.object(self.owner.journal, 'save', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError): self.renew()
        with self.assertRaisesRegex(Rejected, 'durability_fault'):
            self.owner.advance()
        self.assertFalse(self.owner.executor.dispatches)

    def test_unknown_dispatch_interruption_cannot_renew_or_revive_queue(self):
        self.queue('first'); self.queue('later', dependencies=['first'])
        self.owner.executor.fail_after_dispatch = True
        self.owner.advance()
        with self.assertRaisesRegex(Rejected, 'reconciliation_required'): self.renew()
        self.assertEqual(self.owner.result('later')['status'], 'cancelled')
        self.assertEqual(len(self.owner.executor.dispatches), 1)

    def test_renew_preserves_consumed_action_and_execution_budget(self):
        self.owner.activate(grant(task_id='one-action', max_actions=1, execution_budget_ms=1000))
        self.queue('first'); self.queue('later', start=1.5, end=2.5, dependencies=['first'])
        self.owner.advance(); self.renew()
        self.owner.executor.finish(self.owner.active['action_id'])
        self.clock.step(.1); publish(self.owner, 'arrival', {'player': player(1.5)}, tick=11)
        self.owner.advance()
        self.assertEqual(self.owner.result('later')['reason'], 'task_action_budget')
        self.assertEqual(self.owner.lease.actions, 1)
        self.assertEqual(self.owner.lease.reserved_ms, 1000)

    def test_renew_never_extends_inflight_action_deadline(self):
        self.queue(); self.owner.advance()
        deadline = self.owner.active['deadline']
        self.clock.step(.1); self.renew()
        self.assertEqual(self.owner.active['deadline'], deadline)
        self.clock.step(1); self.owner.advance()
        self.assertEqual(len(self.owner.executor.cancellations), 1)

    def test_same_content_fresh_terrain_and_player_allow_original_plan(self):
        plan = self.queue()
        plan['proposal_id'] = 'player-pinned'
        plan['based_on']['player'] = self.owner.snapshots.read()['sections']['player']['revision']
        self.owner.propose(plan)
        self.clock.step(.1)
        publish(self.owner, 'fresh-terrain-player', {'terrain': sections()['terrain'], 'player': player()}, tick=11)
        self.renew()
        self.owner.advance()
        self.assertEqual(self.owner.result('player-pinned')['status'], 'running')
        self.assertEqual(self.owner.result('route')['status'], 'queued')

    def test_changed_then_reverted_content_never_revives_proposal(self):
        self.queue()
        terrain = copy.deepcopy(sections()['terrain']); terrain['cells'][0]['block_id'] = 'minecraft:dirt'
        self.clock.step(.1); publish(self.owner, 'change', {'terrain': terrain}, tick=11)
        self.clock.step(.1); publish(self.owner, 'revert', {'terrain': sections()['terrain']}, tick=12)
        self.renew()
        self.assertEqual(self.owner.result('route')['reason'], 'revision_conflict')
        self.assertFalse(self.owner.pending)

    def test_expired_terrain_gap_cannot_be_hidden_by_equal_fresh_content(self):
        plan = self.queue(); original = self.owner.snapshots.read()['sections']['terrain']
        self.clock.step(3.1)
        publish(self.owner, 'recovered', tick=11)
        latest = self.owner.snapshots.read()['sections']['terrain']
        self.assertEqual(original['content_revision'], latest['content_revision'])
        self.assertGreater(latest['continuity_revision'], original['continuity_revision'])
        self.owner.advance()
        self.assertEqual(self.owner.result('route')['reason'], 'proposal_expired')
        self.assertFalse(self.owner.executor.dispatches)

    def test_observation_gap_invalidates_long_ttl_proposal_even_without_advance_during_gap(self):
        plan = proposal(self.owner, 'long'); plan['ttl_ms'] = 15000
        self.owner.propose(plan)
        self.clock.step(3.1); publish(self.owner, 'recovered', tick=11)
        self.owner.advance()
        self.assertEqual(self.owner.result('long')['reason'], 'observation_continuity_broken')
        self.assertFalse(self.owner.executor.dispatches)

    def test_stale_at_receipt_cannot_be_revived_by_capture_before_advance(self):
        self.clock.step(3.1)
        plan = proposal(self.owner, 'already-stale')
        self.owner.propose(plan)
        publish(self.owner, 'fresh-after-submit', tick=11)
        self.owner.advance()
        self.assertIn(self.owner.result('already-stale')['reason'], ('player_not_fresh', 'observation_not_fresh'))
        self.assertFalse(self.owner.executor.dispatches)

    def test_post_fsync_actual_player_revalidation_cannot_be_bypassed(self):
        self.queue()
        save = self.owner.journal.save
        def altered_after_persistence(data):
            save(data)
            if data['active'] and data['active']['state'] == 'dispatching':
                self.clock.step(.01)
                publish(self.owner, 'arrived-elsewhere', {'player': player(2.5)}, tick=11)
        with patch.object(self.owner.journal, 'save', side_effect=altered_after_persistence):
            self.owner.advance()
        self.assertEqual(self.owner.result('route')['reason'], 'expected_start_changed')
        self.assertFalse(self.owner.executor.dispatches)

    def test_latest_safety_flags_are_checked_after_same_content_renewal(self):
        for index, (field, value) in enumerate((('alive', False), ('grounded', False), ('screen_closed', False), ('health', 1))):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                owner = Coordinator(temp, clock=Clock()); self.addCleanup(owner.close)
                owner.activate(grant()); publish(owner); owner.propose(proposal(owner))
                state=owner.lease_state(); owner.renew(state['epoch'],state['revision'],15000)
                current=player(); current[field]=value
                owner.clock.step(.1); publish(owner, 'unsafe', {'player':current}, tick=11)
                owner.advance()
                self.assertEqual(owner.result('plan1')['reason'],'precondition_failed')
                self.assertFalse(owner.executor.dispatches)


if __name__ == '__main__': unittest.main(verbosity=2)
