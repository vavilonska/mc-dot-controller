"""The prior 17-case audit converted into regression expectations for this candidate.
Three historical gap reproductions now require rejection; unchanged-content and
continuous-renewal expectations intentionally differ from the audited baseline.
"""
import copy
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
from mdcoord import Coordinator, Rejected, Acquisition
from support import Clock, CONTEXT, grant, player, sections, publish, proposal


class RevisionAudit(unittest.TestCase):
    def new_owner(self, data=None):
        temp = tempfile.TemporaryDirectory(prefix='journal-', dir=HERE)
        self.addCleanup(temp.cleanup)
        owner = Coordinator(temp.name, clock=self.clock)
        self.addCleanup(owner.close)
        owner.activate(grant())
        publish(owner, data=data)
        return owner

    def setUp(self):
        self.clock = Clock()
        self.owner = self.new_owner()

    def test_player_update_preserves_terrain_only_dependent_segment(self):
        first = proposal(self.owner, 'first')
        second = proposal(self.owner, 'second', start=1.5, end=2.5, dependencies=['first'])
        self.owner.propose(first)
        self.owner.propose(second)
        old = self.owner.snapshots.read()
        self.owner.advance()
        self.owner.executor.finish(self.owner.active['action_id'])
        self.clock.step(.1)
        publish(self.owner, 'arrival', {'player': player(1.5)}, tick=11)
        new = self.owner.snapshots.read()
        self.assertNotEqual(old['sections']['player']['revision'], new['sections']['player']['revision'])
        self.assertEqual(old['sections']['terrain']['revision'], new['sections']['terrain']['revision'])
        self.owner.advance()
        self.assertEqual(self.owner.result('second')['status'], 'running')
        self.assertEqual(len(self.owner.executor.dispatches), 2)
        self.assertEqual(self.owner.executor.max_writers, 1)

    def test_explicit_player_content_revision_survives_unchanged_player_refresh(self):
        plan = proposal(self.owner)
        plan['based_on']['player'] = self.owner.snapshots.read()['sections']['player']['revision']
        self.owner.propose(plan)
        publish(self.owner, 'player-refresh', {'player': player()}, tick=11)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['status'], 'running')
        self.assertEqual(len(self.owner.executor.dispatches), 1)

    def test_new_capture_with_identical_terrain_preserves_old_plan(self):
        plan = proposal(self.owner)
        self.owner.propose(plan)
        old = self.owner.snapshots.read()['sections']['terrain']
        publish(self.owner, 'terrain-refresh', {'terrain': sections()['terrain']}, tick=11)
        new = self.owner.snapshots.read()['sections']['terrain']
        self.assertEqual(old['data'], new['data'])
        self.assertEqual(old['content_revision'], new['content_revision'])
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['status'], 'running')

    def test_unrelated_terrain_cell_change_invalidates_whole_section(self):
        self.owner.propose(proposal(self.owner))
        terrain = copy.deepcopy(sections()['terrain'])
        distant = next(c for c in terrain['cells'] if c['x'] == 17 and c['y'] == 63)
        distant['block_id'] = 'minecraft:dirt'
        publish(self.owner, 'far-cell-change', {'terrain': terrain}, tick=11)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'revision_conflict')

    def test_inventory_only_change_does_not_invalidate_terrain_plan(self):
        self.owner.propose(proposal(self.owner))
        inventory = copy.deepcopy(sections()['inventory'])
        inventory['slots'][0]['count'] = 2
        publish(self.owner, 'inventory-change', {'inventory': inventory}, tick=11)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['status'], 'running')

    def test_fresh_player_does_not_refresh_expired_terrain(self):
        plan = proposal(self.owner)
        plan['ttl_ms'] = 15000
        self.owner.propose(plan)
        self.clock.step(3.1)
        publish(self.owner, 'fresh-player', {'player': player()}, tick=11)
        snapshot = self.owner.snapshots.read()
        self.assertEqual(snapshot['sections']['player']['freshness'], 'fresh')
        self.assertEqual(snapshot['sections']['terrain']['freshness'], 'stale')
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'observation_not_fresh')

    def test_continuous_lease_renewal_preserves_all_queued_roles(self):
        route = proposal(self.owner, 'route')
        defense = proposal(self.owner, 'defense', kind='defend_entity', priority=100)
        self.owner.propose(route)
        self.owner.propose(defense)
        lease = self.owner.lease_state()
        self.owner.renew(lease['epoch'], lease['revision'], 15000)
        for pid in ('route', 'defense'):
            self.assertEqual(self.owner.result(pid)['status'], 'queued')
        self.assertEqual(len(self.owner.pending), 2)

    def test_duplicate_source_cannot_refresh_ttl(self):
        self.clock.step(.01)
        capture = Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(), 1700000000000, 11)
        before = publish(self.owner, 'one-capture', {'player': player()}, capture=capture, ttl=1000)
        self.clock.step(.9)
        after = publish(self.owner, 'one-capture', {'player': player()}, capture=capture, ttl=3000)
        self.assertEqual(before['sections']['player']['revision'], after['sections']['player']['revision'])
        self.assertEqual(before['sections']['player']['expires_mono'], after['sections']['player']['expires_mono'])
        self.clock.step(.2)
        self.assertEqual(self.owner.snapshots.read()['sections']['player']['freshness'], 'stale')

    def test_fresh_actual_endpoint_is_required_despite_dependency_success(self):
        self.owner.propose(proposal(self.owner, 'first'))
        self.owner.propose(proposal(self.owner, 'second', start=1.5, end=2.5, dependencies=['first']))
        self.owner.advance()
        self.owner.executor.finish(self.owner.active['action_id'])
        self.owner.advance()
        self.assertEqual(self.owner.result('second')['reason'], 'expected_start_changed')
        self.assertEqual(len(self.owner.executor.dispatches), 1)

    def test_unknown_dispatch_retains_slot_and_reconciliation_never_replays(self):
        self.owner.executor.fail_after_dispatch = True
        self.owner.propose(proposal(self.owner))
        self.owner.advance()
        active = self.owner.active['action_id']
        self.assertTrue(self.owner.recovery_blocked)
        with self.assertRaisesRegex(Rejected, 'reconciliation_required'):
            self.owner.propose(proposal(self.owner, 'no-second-writer'))
        self.owner.reconcile()
        self.assertTrue(self.owner.recovery_blocked)
        self.owner.executor.finish(active)
        self.owner.reconcile()
        self.assertFalse(self.owner.recovery_blocked)
        self.assertEqual(self.owner.result('plan1')['status'], 'succeeded')
        self.assertEqual(len(self.owner.executor.dispatches), 1)

    def test_terminal_without_release_cannot_free_slot(self):
        self.owner.propose(proposal(self.owner))
        self.owner.advance()
        active = self.owner.active['action_id']
        self.owner.executor.finish(active, released=False)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'terminal_release_unconfirmed')
        self.assertEqual(self.owner.active['action_id'], active)
        self.assertTrue(self.owner.recovery_blocked)

    def test_defense_preemption_waits_for_release_and_later_step(self):
        self.owner.propose(proposal(self.owner, 'route'))
        self.owner.advance()
        self.owner.propose(proposal(self.owner, 'defense', kind='defend_entity', priority=100))
        self.owner.advance()
        self.assertEqual(self.owner.result('route')['status'], 'cancelled')
        self.assertEqual(self.owner.result('defense')['status'], 'queued')
        self.assertEqual(len(self.owner.executor.dispatches), 1)
        self.owner.advance()
        self.assertEqual(self.owner.result('defense')['status'], 'running')
        self.assertEqual(len(self.owner.executor.dispatches), 2)
        self.assertEqual(len(self.owner.executor.cancellations), 1)

    def test_different_journals_are_not_a_global_writer_fence(self):
        other = self.new_owner()
        for owner in (self.owner, other):
            owner.propose(proposal(owner))
            owner.advance()
            self.assertEqual(owner.result('plan1')['status'], 'running')
        self.assertIsNotNone(self.owner.active)
        self.assertIsNotNone(other.active)
        self.assertEqual(len(self.owner.executor.dispatches) + len(other.executor.dispatches), 2)

    def test_omitting_player_revision_cannot_bypass_latest_safety_flags(self):
        for field, value in [('alive', False), ('grounded', False), ('screen_closed', False), ('health', 1)]:
            with self.subTest(field=field):
                owner = self.new_owner()
                plan = proposal(owner)
                self.assertNotIn('player', plan['based_on'])
                owner.propose(plan)
                current = player()
                current[field] = value
                publish(owner, 'unsafe-player', {'player': current}, tick=11)
                owner.advance()
                self.assertEqual(owner.result('plan1')['reason'], 'precondition_failed')
                self.assertEqual(owner.executor.dispatches, [])

    def test_route_admission_now_rejects_missing_entities(self):
        owner = self.new_owner({'player': player(), 'terrain': sections()['terrain']})
        self.assertIn('entities', owner.snapshots.read()['missing_sections'])
        owner.propose(proposal(owner))
        owner.advance()
        self.assertEqual(owner.result('plan1')['status'], 'rejected')
        self.assertEqual(owner.executor.dispatches, [])

    def test_route_admission_now_rejects_stale_entities(self):
        self.clock.step(.01)
        publish(self.owner, 'short-lived-entities', {'entities': sections()['entities']}, tick=11, ttl=50)
        self.clock.step(.1)
        self.assertEqual(self.owner.snapshots.read()['sections']['entities']['freshness'], 'stale')
        self.owner.propose(proposal(self.owner))
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['status'], 'rejected')
        self.assertEqual(self.owner.executor.dispatches, [])

    def test_explicit_entities_dependency_is_not_a_no_threat_condition(self):
        plan = proposal(self.owner)
        proof_id = self.owner.threats.require_clearance(self.owner.snapshots.read(),
            plan['preconditions']['expected_position'], plan['intent']['waypoints'])
        self.owner.threats.revoke(proof_id)
        snapshot = self.owner.snapshots.read()
        self.assertTrue(snapshot['sections']['entities']['data']['entities'][0]['alive'])
        plan['based_on']['entities'] = snapshot['sections']['entities']['revision']
        self.owner.propose(plan)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_proof_revoked')
        self.assertEqual(self.owner.executor.dispatches, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
