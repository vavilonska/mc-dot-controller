"""Deterministic Runtime dispatch fence, with real durable goal/intent writes.

Only the transport is fake. Named hooks advance the injected monotonic clock
inside reservation, bound validation/session, or final command preparation.
No real sleep, process, queue, native endpoint, or replacement observation is
used to make an expired preflight usable.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mdc_skills import core
from mdc_skills.core import Runtime, SkillError
from mdc_skills.scheduler import Registry, Scheduler, SkillSpec
from support_core import Clock, Client, arrived, move


class DispatchClient(Client):
    """Record the fake transport boundary, not a real queue/native dispatch."""
    def __init__(self, clock):
        super().__init__(clock)
        self.original_capture = None
        self.action_submissions = []

    def submit(self, command, request_id):
        if command['op'] == 'action':
            self.action_submissions.append({
                'request_id': request_id,
                'source_age': self.clock() - self.original_capture,
                'command': deepcopy(command),
            })
        return super().submit(command, request_id)


class FinalDispatchFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        # A zero age origin makes the exact float .8 boundary representable
        # without cancellation from subtracting a much larger origin.
        self.clock.now = 0.
        self.client = DispatchClient(self.clock)
        self.runtime = Runtime(self.client, self.tmp.name,
                               clock=self.clock, sleeper=self.clock.sleep)
        self.addCleanup(self.runtime.close)
        self.events = []
        self.hook = None
        self.reserved = None
        self.final_session_returned = False

        def terrain_provenance(receipt):
            terrain = receipt.get('result', {}).get('terrain')
            if terrain is not None:
                guard = receipt['result']['state']['capability_guard']
                terrain.update(source_tick=guard['source_tick'],
                               source_nano=guard['source_nano'],
                               capture_started_mono=self.clock() - .0005,
                               capture_finished_mono=self.clock())
            return receipt
        self.client.patch_result = terrain_provenance
        self.before = self.runtime.observe(terrain=True)
        self.original_raw = deepcopy(self.before.raw)
        self.original_capture = self.before.captured_at
        self.client.original_capture = self.original_capture

        # The production scheduler performs and persists the real action charge.
        # Keep its wall clock independent so a reversed monotonic clock reaches
        # the Runtime guard rather than being caught by a different fence.
        self.registry = Registry()
        self.registry.register(SkillSpec('walk',
            lambda rt: rt.execute('walk', move(), arrived, before=self.before),
            lambda args: not args))
        self.scheduler = Scheduler(self.runtime, self.registry, wall_clock=lambda: 1000.)
        self.scheduler.add('one-action', 'walk', {}, max_actions=1, deadline_seconds=10)

        save = self.runtime._save
        def durable_save():
            save()
            record = self.pending_mutation()
            if record is not None and record['status'] == 'reserved':
                self.reserved = deepcopy(record)
                # This is after the actual fsynced pending intent reaches disk,
                # but still inside Runtime._reserve's durable-save operation.
                self.advance_at('durable_mutation_reservation')
        self.runtime._save = durable_save

        validate = self.runtime._validate_state
        def bound_validate(payload, **kwargs):
            value = validate(payload, **kwargs)
            if self.pending_mutation() is not None:
                # The post-reservation _fresh already passed its entry age test.
                self.advance_at('post_reservation_bound_validation')
            return value
        self.runtime._validate_state = bound_validate

        session = self.runtime._session
        def bound_session(**kwargs):
            value = session(**kwargs)
            if self.pending_mutation() is not None:
                self.advance_at('final_bound_session')
                self.final_session_returned = True
            return value
        self.runtime._session = bound_session

        # Identify the final defensive command copy by object identity and the
        # completed session stage, not by counting clock or deepcopy invocations.
        def command_copy(value, *args, **kwargs):
            result = deepcopy(value, *args, **kwargs)
            record = self.pending_mutation()
            if (record is not None and value is record['command']
                    and self.final_session_returned):
                self.advance_at('final_command_preparation')
            return result
        self.patch_copy = patch.object(core, 'deepcopy', command_copy)
        self.patch_copy.start()
        self.addCleanup(self.patch_copy.stop)

    def pending_mutation(self):
        record = self.runtime._journal['records'].get(self.runtime.pending_request_id)
        return record if record is not None and record['kind'] == 'mutation' else None

    def advance_at(self, stage):
        age = self.clock() - self.original_capture
        self.events.append({'stage': stage, 'age_on_entry': age})
        if self.hook is not None and self.hook[0] == stage:
            _, target = self.hook
            self.clock.now = self.original_capture + target
            self.hook = None
            self.events[-1]['age_on_return'] = self.clock() - self.original_capture

    def read_journal(self):
        return json.loads((Path(self.tmp.name) / 'execution.json').read_text())

    def assert_source_unchanged(self):
        self.assertEqual(self.before.captured_at, self.original_capture)
        self.assertEqual(self.before.raw, self.original_raw)
        self.assertEqual(self.before.state, self.original_raw['state'])
        self.assertEqual(self.before.terrain, self.original_raw['terrain'])
        self.assertEqual(self.runtime.max_age, .8)

    def assert_charge_and_no_replay(self, outcome, status):
        goal = self.scheduler.status('one-action')
        saved = json.loads((Path(self.tmp.name) / 'goals.json').read_text())['goals']['one-action']
        self.assertEqual(goal, saved)
        self.assertEqual(goal['actions_reserved'], 1)
        self.assertEqual(goal['state'], status)
        self.assertEqual(goal['request_ids'], list(outcome.request_ids))
        self.assertEqual(goal['max_actions'], 1)
        calls = deepcopy(self.client.calls)
        journal = self.read_journal()
        self.assertEqual(self.scheduler.advance().reason, 'no_runnable_goal')
        self.assertEqual(self.client.calls, calls)
        self.assertEqual(self.read_journal(), journal)
        later = Scheduler(self.runtime, self.registry, wall_clock=lambda: 1000.)
        self.assertEqual(later.status('one-action')['actions_reserved'], 1)
        self.assertEqual(later.advance().reason, 'no_runnable_goal')
        self.assertEqual(self.client.calls, calls)

    def assert_blocked_reservation(self, outcome):
        # Assert dispatch first: baseline red evidence names the unsafe boundary.
        self.assertEqual(self.client.action_submissions, [], self.client.action_submissions)
        self.assertEqual(self.client.action_count, 0)
        self.assertIsNone(self.client.native)
        self.assertEqual(len(self.client.calls), 1)  # Original observation only.
        self.assertEqual(outcome.status, 'blocked')
        self.assertEqual(outcome.reason, 'preflight_observation_stale')
        self.assertEqual(outcome.request_ids, (self.reserved['request_id'],))
        saved = self.read_journal()
        record = saved['records'][self.reserved['request_id']]
        self.assertEqual(record['status'], 'blocked')
        self.assertEqual(record['reason'], outcome.reason)
        for key in ('request_id', 'kind', 'skill', 'command', 'command_sha256',
                    'gateway_session', 'before_context', 'before_tick'):
            self.assertEqual(record[key], self.reserved[key], key)
        digest = hashlib.sha256(json.dumps(record['command'], sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        self.assertEqual(record['command_sha256'], digest)
        self.assertEqual(record['command']['capability_guard'],
                         self.original_raw['state']['capability_guard'])
        self.assertNotIn('receipt', record)
        self.assertNotIn('receipt_ref', record)
        self.assertIsNone(saved['pending'])
        self.assertIsNone(saved['semantic_pending'])
        self.assertFalse(self.runtime.has_unresolved_execution)
        self.assertEqual(self.runtime.audit_evidence()['receipts'], 1)
        self.assert_source_unchanged()
        self.assert_charge_and_no_replay(outcome, 'blocked')

    def assert_expiry_at(self, stage, age=.801):
        self.hook = (stage, age)
        out = self.scheduler.advance()
        self.assertIsNone(self.hook, 'Named hook was never exercised')
        event = next(row for row in self.events if 'age_on_return' in row)
        self.assertGreaterEqual(event['age_on_entry'], 0)
        self.assertLessEqual(event['age_on_entry'], .8)
        self.assertAlmostEqual(event['age_on_return'], age)
        self.assert_blocked_reservation(out)
        return out

    def test_expiry_inside_actual_durable_reservation_blocks(self):
        self.assert_expiry_at('durable_mutation_reservation')
        self.assertFalse(self.final_session_returned)

    def test_expiry_inside_post_reservation_bound_validation_blocks(self):
        self.assert_expiry_at('post_reservation_bound_validation')

    def test_expiry_inside_final_bound_session_blocks(self):
        self.assert_expiry_at('final_bound_session')

    def test_expiry_inside_final_command_preparation_blocks(self):
        self.assert_expiry_at('final_command_preparation')

    def test_reversed_time_inside_final_bound_session_blocks(self):
        self.assert_expiry_at('final_bound_session', -.001)

    def assert_single_submission_at(self, age):
        self.hook = ('final_command_preparation', age)
        out = self.scheduler.advance()
        self.assertTrue(out.ok, out)
        self.assertIsNone(self.hook)
        self.assertEqual(self.client.action_count, 1)
        self.assertEqual(len(self.client.action_submissions), 1)
        submission = self.client.action_submissions[0]
        self.assertEqual(submission['source_age'], age)
        self.assertEqual(submission['request_id'], self.reserved['request_id'])
        self.assertEqual(submission['command'], self.reserved['command'])
        self.assertEqual(out.evidence['command_sha256'], self.reserved['command_sha256'])
        self.assertIsNone(self.runtime.pending_request_id)
        self.assert_source_unchanged()
        self.assert_charge_and_no_replay(out, 'succeeded')

    def test_under_budget_final_preparation_submits_exactly_once(self):
        self.assert_single_submission_at(.799)

    def test_just_below_800ms_submits_exactly_once(self):
        self.assert_single_submission_at(.799999)

    def test_exact_800ms_boundary_is_inclusive(self):
        self.assert_single_submission_at(.8)

    def test_just_above_800ms_blocks(self):
        self.assert_expiry_at('final_command_preparation', .800001)

    def test_failed_finish_write_never_submits_or_claims_durable_cleanup(self):
        self.hook = ('final_bound_session', .801)
        save = self.runtime._save
        failed = []
        def reject_finish_save():
            if (self.reserved is not None
                    and self.runtime.pending_request_id is None
                    and self.runtime._journal['records'][self.reserved['request_id']].get('reason')
                        == 'preflight_observation_stale'):
                failed.append(True)
                raise SkillError('checkpoint_capacity_exhausted')
            save()
        self.runtime._save = reject_finish_save
        out = self.scheduler.advance()
        self.assertEqual(failed, [True])
        self.assertEqual(self.client.action_submissions, [])
        self.assertEqual(self.client.action_count, 0)
        self.assertIsNone(self.client.native)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(out.status, 'blocked')  # Existing finish failure semantics.
        self.assertEqual(out.reason, 'checkpoint_capacity_exhausted')
        rid = self.reserved['request_id']
        self.assertEqual(out.request_ids, (rid,))
        saved = self.read_journal()
        self.assertEqual(saved['pending'], rid)
        self.assertIsNone(saved['semantic_pending'])
        self.assertEqual(saved['records'][rid], self.reserved)
        self.assertEqual(saved['records'][rid]['status'], 'reserved')
        self.assertNotIn('reason', saved['records'][rid])
        self.assertNotIn('receipt', saved['records'][rid])
        # The failed write left transient memory different from durable disk.
        # Do not report pending cleared or a durably completed stale rejection.
        self.assertIsNone(self.runtime.pending_request_id)
        self.assertEqual(self.runtime._journal['records'][rid]['status'], 'blocked')
        self.assert_source_unchanged()
        self.assert_charge_and_no_replay(out, 'blocked')

    def test_transport_started_exception_stays_unknown_with_exact_pending_id(self):
        self.hook = ('final_command_preparation', .799)
        self.client.fail_after_submit = True
        out = self.scheduler.advance()
        self.assertEqual(out.status, 'unknown')
        self.assertEqual(out.reason, 'queue_exchange_unknown:OSError')
        self.assertEqual(self.client.action_count, 1)
        self.assertEqual(len(self.client.action_submissions), 1)
        rid = self.reserved['request_id']
        self.assertEqual(out.request_ids, (rid,))
        saved = self.read_journal()
        self.assertEqual(saved['pending'], rid)
        self.assertIsNone(saved['semantic_pending'])
        record = saved['records'][rid]
        self.assertEqual(record['status'], 'unknown')
        self.assertEqual(record['command'], self.reserved['command'])
        self.assertEqual(record['command_sha256'], self.reserved['command_sha256'])
        self.assertEqual(self.scheduler.status('one-action')['actions_reserved'], 1)
        self.assertEqual(self.scheduler.status('one-action')['state'], 'unknown')
        self.assertTrue(self.runtime.has_unresolved_execution)
        with self.assertRaisesRegex(SkillError, 'unresolved_execution_blocks_scheduler'):
            self.scheduler.advance()
        again = self.runtime.execute('walk', move(), arrived, before=self.before)
        self.assertEqual(again.reason, 'unknown_or_pending_request_blocks_new_work')
        self.assertEqual(self.client.action_count, 1)
        self.assertEqual(self.read_journal(), saved)
        self.assert_source_unchanged()

    def assert_early_guard(self, reason):
        out = self.scheduler.advance()
        self.assertEqual(out.status, 'blocked')
        self.assertEqual(out.reason, reason)
        self.assertEqual(out.request_ids, ())
        self.assertEqual(self.client.action_submissions, [])
        self.assertIsNone(self.reserved)
        self.assertEqual(self.client.action_count, 0)
        self.assertIsNone(self.client.native)
        self.assertIsNone(self.runtime.pending_request_id)
        self.assert_charge_and_no_replay(out, 'blocked')

    def test_original_reversed_clock_blocks_before_reservation(self):
        self.clock.now = self.before.captured_at - .001
        self.assert_early_guard('preflight_observation_stale')

    def test_foreign_observation_blocks_before_reservation(self):
        self.before = replace(self.before, _owner='another-runtime')
        self.assert_early_guard('observation_not_owned_by_current_runtime')

    def test_modified_observation_blocks_before_reservation(self):
        self.before.state['player']['health'] = 19
        self.assert_early_guard('observation_modified_after_capture')

    def test_superseded_observation_blocks_before_reservation(self):
        self.runtime.observe(terrain=True)
        self.assert_early_guard('newer_observation_invalidated_preflight')


if __name__ == '__main__':
    unittest.main()
