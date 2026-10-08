import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mdcoord import Coordinator, Rejected
from mdcoord.adapters import dashboard_view, goal_record, publish_recorded, resident_observation
from support import CONTEXT, Clock, grant, player, proposal, publish

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'recorded_resident_synthetic.json'


class AdapterChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.owner = Coordinator(self.tmp.name, clock=Clock())
        self.raw = json.loads(FIXTURE.read_text())

    def tearDown(self):
        self.owner.close(); self.tmp.cleanup()

    def test_existing_resident_result_reused_without_client_or_observe(self):
        # No client argument exists, and all possible socket/queue access is absent.
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            data = resident_observation(self.raw)
            snapshot = publish_recorded(self.owner.snapshots, self.raw)
            view = dashboard_view(snapshot)
        self.assertEqual(data['context'], CONTEXT)
        self.assertEqual(view['observed_at_ms'], 1_700_000_000_000)
        self.assertEqual(view['state_freshness'], 'unknown')
        self.assertFalse(self.owner.executor.dispatches)
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(view))

    def test_importing_old_result_twice_cannot_refresh_it(self):
        first = publish_recorded(self.owner.snapshots, self.raw)
        self.owner.clock.step(9999)
        second = publish_recorded(self.owner.snapshots, self.raw)
        self.assertEqual(first, second)
        self.assertEqual(second['sections']['player']['source_time_ms'], 1_700_000_000_000)
        self.assertEqual(second['sections']['player']['freshness'], 'unknown')
        self.assertIsNone(second['sections']['player']['capture_started_mono'])

    def test_goal_timestamp_kept_separate_from_state(self):
        snapshot = publish_recorded(self.owner.snapshots, self.raw)
        goal = {'goal_id': 'goal1', 'task_id': 'task1', 'status': 'active',
                'updated_at_ms': 1_600_000_000_000,
                'target': {'x': 7.5, 'y': 64, 'z': .5}}
        result = dashboard_view(snapshot, goal)
        self.assertNotEqual(result['observed_at_ms'], result['goal']['updated_at_ms'])
        self.assertEqual(result['goal']['updated_at_ms'], 1_600_000_000_000)
        self.assertEqual(result['goal']['target'], goal['target'])
        self.assertFalse(result['goal']['confers_authorization'])
        self.assertNotIn('goal', self.owner.snapshots.read()['sections'])

    def test_missing_goal_not_invented(self):
        self.assertIsNone(dashboard_view(publish_recorded(self.owner.snapshots, self.raw))['goal'])

    def test_goal_payload_cannot_include_executable_instruction(self):
        goal = {'goal_id': 'goal1', 'task_id': 'task1', 'status': 'active', 'updated_at_ms': 1,
                'target': None, 'command': '/teleport anywhere'}
        with self.assertRaises(Rejected):
            goal_record(goal)

    def test_result_success_or_missing_context_rejected(self):
        for modify in (lambda r: r.update(status='pending'), lambda r: r['result'].pop('state'),
                       lambda r: r['result']['action'].pop('action_session'),
                       lambda r: r.pop('finished_at')):
            data = copy.deepcopy(self.raw); modify(data)
            with self.assertRaises(Rejected):
                resident_observation(data)

    def test_missing_inventory_not_claimed_complete(self):
        self.raw['result']['state']['player'].pop('inventory')
        snapshot = publish_recorded(self.owner.snapshots, self.raw)
        view = dashboard_view(snapshot)
        self.assertFalse(view['inventory']['complete'])
        self.assertEqual(view['inventory']['freshness'], 'unknown')

    def test_raw_native_fields_do_not_certify_safe_corridor_or_release(self):
        data = resident_observation(self.raw)
        self.assertNotIn('terrain', data['sections'])
        self.assertNotIn('entities', data['sections'])
        self.assertIsNone(data['sections']['action']['input_released'])


class PersistenceGuardChecks(unittest.TestCase):
    def test_fsync_delay_expires_plan_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock(); owner = Coordinator(tmp, clock=clock)
            self.addCleanup(owner.close)
            owner.activate(grant()); publish(owner)
            p = proposal(owner); p['ttl_ms'] = 50; owner.propose(p)
            original = owner.journal.save
            def delayed_save(data):
                original(data)
                clock.step(.1)
            with patch.object(owner.journal, 'save', side_effect=delayed_save):
                owner.advance()
            self.assertEqual(owner.result('plan1')['reason'], 'proposal_expired')
            self.assertIsNone(owner.active)
            self.assertFalse(owner.executor.dispatches)

    def test_fsync_delay_cannot_send_past_task_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock(); owner = Coordinator(tmp, clock=clock)
            self.addCleanup(owner.close)
            owner.activate(grant(lease_ms=1100)); publish(owner)
            owner.propose(proposal(owner))
            original = owner.journal.save
            def delayed_save(data):
                original(data); clock.step(.2)
            with patch.object(owner.journal, 'save', side_effect=delayed_save):
                owner.advance()
            self.assertEqual(owner.result('plan1')['reason'], 'action_exceeds_remaining_lease')
            self.assertFalse(owner.executor.dispatches)

    def test_wal_is_visible_on_disk_before_executor_receives_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner = Coordinator(tmp, clock=Clock()); self.addCleanup(owner.close)
            owner.activate(grant()); publish(owner); owner.propose(proposal(owner))
            original = owner.executor.dispatch
            def checked_dispatch(*args):
                data = json.loads((Path(tmp) / 'coordination.json').read_text())
                self.assertEqual(data['active']['action_id'], args[0])
                self.assertEqual(data['records']['plan1']['status'], 'dispatching')
                self.assertEqual(data['active']['state'], 'dispatching')
                return original(*args)
            with patch.object(owner.executor, 'dispatch', side_effect=checked_dispatch):
                owner.advance()
            self.assertEqual(len(owner.executor.dispatches), 1)

    def test_new_journal_path_fsyncs_parent_entries(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'nested' / 'journal'
            touched = []
            real = os.fsync
            def record(fd):
                touched.append(os.readlink('/proc/self/fd/' + str(fd)))
                real(fd)
            with patch('os.fsync', side_effect=record):
                owner = Coordinator(root, clock=Clock())
            self.addCleanup(owner.close)
            self.assertIn(str(root.parent), touched)
            self.assertIn(str(Path(tmp)), touched)
            self.assertIn(str(root), touched)

    def test_unknown_action_at_deadline_receives_one_exact_cancel_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock(); owner = Coordinator(tmp, clock=clock); self.addCleanup(owner.close)
            owner.activate(grant()); publish(owner); owner.propose(proposal(owner)); owner.advance()
            action_id = owner.active['action_id']
            owner.executor.cancel_confirms = False
            with patch.object(owner.executor, 'poll', return_value=None):
                clock.step(2)
                for _ in range(5):
                    owner.advance(); owner.reconcile()
            self.assertEqual(owner.executor.cancellations, [action_id])
            self.assertTrue(owner.status()['recovery_blocked'])
            self.assertEqual(len(owner.executor.dispatches), 1)

    def test_preparation_cannot_consume_entire_action_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock(); owner = Coordinator(tmp, clock=clock); self.addCleanup(owner.close)
            owner.activate(grant()); publish(owner); owner.propose(proposal(owner))
            original = owner.journal.save
            def delayed_save(data):
                original(data); clock.step(1.2)
            with patch.object(owner.journal, 'save', side_effect=delayed_save):
                owner.advance()
            self.assertEqual(owner.result('plan1')['reason'], 'action_preparation_deadline')
            self.assertFalse(owner.executor.dispatches)


class AdapterQualityChecks(unittest.TestCase):
    setUp = AdapterChecks.setUp
    tearDown = AdapterChecks.tearDown
    def test_malformed_inventory_cannot_become_fresh_complete_empty(self):
        from mdcoord import Acquisition
        for index, items in enumerate((['invalid'], [{'slot': 'bad', 'id': 'minecraft:stone', 'count': 1}],
                                       [{'slot': 0, 'id': 'minecraft:stone', 'count': 1}] * 2)):
            data = copy.deepcopy(self.raw); data['result']['state']['player']['inventory'] = items
            extracted = resident_observation(data)
            now = self.owner.clock()
            snapshot = self.owner.snapshots.publish(extracted['context'], 'malformed' + str(index), extracted['sections'],
                         Acquisition(self.owner.snapshots.epoch, now, now, extracted['source_time_ms'], 10))
            inventory = snapshot['sections']['inventory']
            self.assertNotEqual(inventory['freshness'], 'fresh')
            self.assertFalse(inventory['data']['complete'])

    def test_dashboard_metadata_never_passes_secret_objects(self):
        snapshot = publish_recorded(self.owner.snapshots, self.raw)
        snapshot['sections']['player']['revision'] = {'token': 'SYNTHETIC_SECRET'}
        with self.assertRaises(Rejected):
            dashboard_view(snapshot)


class PreemptionBudgetChecks(unittest.TestCase):
    def test_unadmittable_defense_does_not_cancel_current_action(self):
        for label, changes in (('actions', {'max_actions': 1}), ('budget', {'execution_budget_ms': 1000})):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                owner = Coordinator(tmp, clock=Clock()); self.addCleanup(owner.close)
                owner.activate(grant(**changes)); publish(owner)
                owner.propose(proposal(owner)); owner.advance()
                owner.propose(proposal(owner, pid='defense', kind='defend_entity', priority=100))
                owner.advance()
                self.assertEqual(owner.executor.cancellations, [])
                self.assertEqual(owner.result('defense')['status'], 'rejected')
                self.assertEqual(owner.result('plan1')['status'], 'running')


class ReceiptRobustnessChecks(unittest.TestCase):
    def test_malformed_receipt_status_blocks_and_still_attempts_deadline_cancel(self):
        from dataclasses import replace
        for invalid in ([], {}, None, 1):
            with self.subTest(status=invalid), tempfile.TemporaryDirectory() as tmp:
                clock = Clock(); owner = Coordinator(tmp, clock=clock); self.addCleanup(owner.close)
                owner.activate(grant()); publish(owner); owner.propose(proposal(owner)); owner.advance()
                action = owner.active['action_id']
                owner.executor.receipts[action] = replace(owner.executor.receipts[action], status=invalid)
                clock.step(2)
                owner.advance()
                self.assertTrue(owner.status()['recovery_blocked'])
                self.assertEqual(owner.executor.cancellations, [action])
                self.assertEqual(len(owner.executor.dispatches), 1)
