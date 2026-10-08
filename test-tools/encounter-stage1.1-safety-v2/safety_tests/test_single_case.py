"""One-case entrypoint tests with the actual mailbox and a synthetic resident."""
import copy
import json
import unittest

import test_post_trial_safety as support
from test_public_queue_integration import SyntheticResidentQueue
from fixtures_support import receipt, rejection, setup
from post_trial_safety import PostTrialSafety, SafetyHalt
from single_case import run_registered_case


class SingleCaseTests(unittest.TestCase):
    def test_owned_pending_publication_after_idle_observe_does_not_hide_failed_result(self):
        from resident_controller.ipc import atomic_json
        _, failed = setup('failed', request_id=self.h.b.request_id)
        failed['action_session'] = self.h.b.action_session
        self.assertIsNone(self.h.b.native_problem(failed))
        self.q.main_response = receipt(self.h.b, failed)
        actual_result, actual_wait = self.q.result, self.q.wait
        polls = 0
        def delayed(rid):
            nonlocal polls
            if rid == self.h.b.request_id:
                polls += 1
                if polls == 1:
                    self.h.queue.current = support.sample(self.h.b)
                    self.h.queue.current['action'].update(status='idle', action_id=None)
                    return None
                self.h.queue.current = support.sample(self.h.b, failed)
                self.h.queue.session_data.update(pending=0, pending_request_ids=[])
                atomic_json(self.q.root / 'session.json', self.h.queue.session_data)
            return actual_result(rid)
        def observed(rid, timeout):
            result = actual_wait(rid, timeout)
            if polls == 1:
                self.h.queue.session_data.update(pending=1, pending_request_ids=[self.h.b.request_id])
                atomic_json(self.q.root / 'session.json', self.h.queue.session_data)
            return result
        self.q.result, self.q.wait = delayed, observed
        result = self.run_case()
        self.assertIsNone(result['stopped_reason'])
        self.assertEqual(result['resolution']['resolved_outcome']['kind'], 'bound_terminal')
        self.assertEqual(self.report()['response']['status'], 'failed')
        self.assertTrue(result['health']['sampled_health_window_complete'])
        self.assertEqual(len(self.mutations()), 1)
        self.assertEqual(result['closeout'], [])

    def setUp(self):
        self.h = support.SafetyTests(methodName='runTest')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        h = self.h
        self.q = SyntheticResidentQueue(h.base / 'synthetic-mailbox', h.queue, h.b, h.native)
        h.o.c = self.q
        h.register()

    def run_case(self, **kwargs):
        return run_registered_case(self.h.s, self.h.b, 'one', **kwargs)

    def report(self):
        return json.loads((self.h.o.out / 'one.json').read_text())

    def mutations(self):
        return [v for v in self.q.envelopes if v['op'] != 'observe']

    def test_default_records_complete_health_and_report_without_closeout(self):
        result = self.run_case()
        self.assertIsNone(result['stopped_reason'])
        self.assertTrue(result['health']['sampled_health_window_complete'])
        self.assertEqual(result['closeout'], [])
        self.assertEqual([v['op'] for v in self.mutations()], ['action'])
        report = self.report()
        self.assertEqual([s['phase'] for s in report['samples']], ['before', 'running', 'after'])
        self.assertEqual(report['command'], {'op': 'action', **self.h.b.encounter_request})
        self.assertFalse(report['controlled_trial_accepted'])
        self.assertTrue((self.h.o.out / 'one.closeout.json').is_file())

    def test_explicit_closeout_is_two_exact_cleanups_then_pause(self):
        result = self.run_case(closeout_authorization='synthetic-approved-closeout')
        self.assertIsNone(result['stopped_reason'])
        self.assertEqual(len(result['closeout']), 3)
        self.assertEqual([v['op'] for v in self.mutations()], ['action', 'direct', 'direct', 'direct'])
        self.assertEqual([v['body']['command'] for v in self.mutations()[1:3]],
                         ['kill ' + e['uuid'] for e in self.h.es])
        self.assertEqual(self.mutations()[-1]['body']['key'], 'key.keyboard.escape')

    def test_null_rejection_can_use_existing_narrow_closeout(self):
        self.q.main_response = rejection(self.h.b)
        result = self.run_case(closeout_authorization='synthetic-approved-closeout')
        self.assertEqual(result['resolution']['resolved_outcome']['kind'], 'admission_rejected')
        self.assertEqual(len(result['closeout']), 3)

    def test_unknown_never_cancels_cleans_up_or_replays_after_reopen(self):
        self.q.main_response = receipt(self.h.b, self.h.native, status='uncertain')
        result = self.run_case(closeout_authorization='synthetic-approved-closeout')
        self.assertIsNotNone(result['stopped_reason'])
        self.assertEqual(result['closeout'], [])
        self.assertEqual([v['op'] for v in self.mutations()], ['action'])
        original = (self.h.o.out / 'one.json').read_bytes()
        reopened = PostTrialSafety(self.h.o, self.h.s.root)
        with self.assertRaises(SafetyHalt): run_registered_case(reopened, self.h.b, 'new-name')
        self.assertEqual(original, (self.h.o.out / 'one.json').read_bytes())
        self.assertEqual(len(self.mutations()), 1)

    def test_retains_every_sample_until_result_arrives(self):
        actual = self.q.result
        _, running = setup('running', request_id=self.h.b.request_id)
        # Native fixture cases have distinct synthetic action sessions. This
        # replay intentionally represents one session across running/terminal.
        running['action_session'] = self.h.b.action_session
        self.assertIsNone(self.h.b.native_problem(running))
        count = 0
        def delayed(rid):
            nonlocal count
            if rid == self.h.b.request_id:
                count += 1
                if count < 3:
                    self.h.queue.current = support.sample(self.h.b, running)
                    return None
                self.h.queue.current = support.sample(self.h.b, self.h.native)
            return actual(rid)
        self.q.result = delayed
        self.run_case()
        self.assertEqual([s['phase'] for s in self.report()['samples']],
                         ['before', 'running', 'running', 'running', 'after'])
        self.assertEqual([s['observation']['action']['status']
                          for s in self.report()['samples'][1:4]],
                         ['running', 'running', 'succeeded'])
        self.assertEqual(len(self.mutations()), 1)

    def test_health_decrease_is_not_upgraded_by_terminal_success(self):
        actual = self.q.submit
        def damaged(command, request_id=None):
            rid = actual(command, request_id)
            if command['op'] == 'action': self.h.queue.current['state']['player']['health'] = 19
            return rid
        self.q.submit = damaged
        result = self.run_case(closeout_authorization='synthetic-approved-closeout')
        self.assertTrue(result['health']['stop_latched'])
        self.assertEqual(result['stopped_reason'], 'health_stop_requires_operator_handoff')
        self.assertEqual(result['closeout'], [])
        self.assertEqual(len(self.mutations()), 1)

    def test_observation_failure_saves_evidence_and_stops_without_cancel(self):
        actual = self.q.submit
        def failed(command, request_id=None):
            if command['op'] == 'observe' and self.mutations():
                raise OSError('synthetic observation failure')
            return actual(command, request_id)
        self.q.submit = failed
        result = self.run_case(closeout_authorization='synthetic-approved-closeout')
        self.assertTrue(result['health']['stop_required'])
        self.assertIsNotNone(self.report()['before'])
        self.assertIsNone(self.report()['after'])
        self.assertEqual(self.report()['response']['status'], 'succeeded')
        self.assertEqual(result['stopped_reason'], 'synthetic observation failure')
        self.assertEqual(result['record_trial_error']['reason'], 'complete_report_observations_missing')
        self.assertEqual(self.report()['observation_error'], {
            'phase': 'running', 'type': 'OSError', 'reason': 'synthetic observation failure'})
        self.assertEqual(result['closeout'], [])
        self.assertTrue((self.h.case() / 'SAFETY-STOP.json').exists())
        self.assertEqual(len(self.mutations()), 1)

    def test_health_loss_since_registration_blocks_the_only_submit(self):
        self.h.queue.current['state']['player']['health'] = 19
        result = self.run_case()
        self.assertTrue(result['health']['stop_required'])
        self.assertEqual(self.mutations(), [])
        self.assertTrue((self.h.case() / 'SAFETY-STOP.json').exists())

    def test_submit_exception_consumes_claim_and_never_retries(self):
        actual = self.q.submit
        def unknown(command, request_id=None):
            rid = actual(command, request_id)
            if command['op'] == 'action': raise OSError('synthetic lost submit response')
            return rid
        self.q.submit = unknown
        result = self.run_case()
        self.assertIsNotNone(result['stopped_reason'])
        self.assertTrue((self.h.case() / 'trial-dispatch.json').exists())
        with self.assertRaises(SafetyHalt): self.run_case()
        self.assertEqual(len(self.mutations()), 1)

    def test_conflicting_terminal_sample_still_blocks_closeout(self):
        actual = self.q.wait
        changed = False
        def conflicting(rid, timeout):
            nonlocal changed
            response = actual(rid, timeout)
            action = response.get('result', {}).get('action', {})
            if action.get('action_id') == self.h.b.expected_action_id and not changed:
                response = copy.deepcopy(response)
                response['result']['action']['ticks'] += 1
                changed = True
            return response
        self.q.wait = conflicting
        result = self.run_case(closeout_authorization='synthetic-approved-closeout')
        self.assertIsNotNone(result['stopped_reason'])
        self.assertEqual(result['closeout'], [])
        self.assertEqual(len(self.mutations()), 1)

    def test_observer_deadline_is_pending_not_failure_or_retry(self):
        b = self.h.b
        self.h.b = type(b)(b.request_id, b.resident_session, b.action_session,
            b.world_generation, b.player_uuid, b.action_kind,
            encounter_request=dict(b.encounter_request, timeout_ms=50))
        actual = self.q.result
        self.q.result = lambda rid: None if rid == b.request_id else actual(rid)
        now = 1.0
        def clock():
            nonlocal now
            now += 0.01
            return now
        result = self.run_case(clock=clock)
        self.assertEqual(self.report()['response']['status'], 'pending')
        self.assertIsNotNone(result['stopped_reason'])
        self.assertEqual(len(self.mutations()), 1)

    def test_unknown_cleanup_stops_before_second_uuid_and_pause(self):
        self.h.queue.direct_uncertain = True
        result = self.run_case(closeout_authorization='synthetic-approved-closeout')
        self.assertIsNotNone(result['stopped_reason'])
        self.assertEqual([v['op'] for v in self.mutations()], ['action', 'direct'])


if __name__ == '__main__':
    unittest.main()
