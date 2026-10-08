"""Actual file-mailbox + ledger composition with an in-process synthetic resident.

Only temporary directories are used. No Controller, Bridge, game transport,
credentials, private harness or live Operator is imported or constructed.
"""
import copy
import json
from pathlib import Path
import sys
import unittest

import test_post_trial_safety as support
from fixtures_support import receipt, rejection
from post_trial_safety import PostTrialSafety, SafetyHalt

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'candidates/encounter-stage1.1/resident-controller'))
from resident_controller.ipc import QueueClient, atomic_json


class SyntheticResidentQueue(QueueClient):
    """Consume the actual mailbox format synchronously, never contact a bridge."""
    def __init__(self, directory, fake, binding, native):
        super().__init__(directory)
        self.fake, self.binding, self.native = fake, binding, native
        self.main_response = receipt(binding, native)
        self.envelopes = []
        for folder in ('inbox', 'working', 'results'):
            (self.root / folder).mkdir(parents=True)
        atomic_json(self.root / 'session.json', fake.session_data)

    def submit(self, command, request_id=None):
        rid = super().submit(command, request_id)
        pending = self.root / 'inbox' / (rid + '.json')
        if not pending.exists():
            return rid
        wire = json.loads(pending.read_text())
        self.envelopes.append(wire)
        if command['op'] == 'action':
            response = copy.deepcopy(self.main_response)
            if response.get('action_id', 'not-null') is not None:
                self.fake.current = support.sample(self.binding, self.native)
        else:
            self.fake.submit(command, rid)
            response = self.fake.results[rid]
        atomic_json(self.root / 'results' / (rid + '.json'), response)
        pending.unlink()
        return rid


class PublicQueueIntegration(unittest.TestCase):
    def setUp(self):
        self.h = support.SafetyTests(methodName='runTest')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        h = self.h
        self.q = SyntheticResidentQueue(h.base / 'synthetic-mailbox', h.queue, h.b, h.native)
        h.o.c = self.q

    def submit_and_record(self, response=None):
        h = self.h
        h.register()
        before = support.sample(h.b)
        command = h.reserve()  # Persist reservation and claim BEFORE queue write.
        if response is not None:
            self.q.main_response = response
        self.assertEqual(self.q.submit(command, h.b.request_id), h.b.request_id)
        result = self.q.wait(h.b.request_id, timeout=0.1)
        report = {'name': 'one', 'request_id': h.b.request_id, 'binding': h.b.wire(),
            'command': command, 'before': before, 'samples': [], 'response': result,
            'after': copy.deepcopy(h.queue.current), 'interrupt_proof': None}
        h.o.out.mkdir()
        (h.o.out / 'one.json').write_text(json.dumps(report))
        return h.s.record_trial(report)

    def test_known_terminal_exact_cleanup_then_pause_via_real_mailbox(self):
        h = self.h
        self.assertTrue(self.submit_and_record()['narrow_safety_eligible'])
        for entity in h.es:
            self.assertTrue(h.s.cleanup_uuid(entity['uuid'], 'synthetic-authorization')['effect_confirmed'])
        self.assertTrue(h.s.pause_once('synthetic-authorization')['effect_confirmed'])
        mutations = [v for v in self.q.envelopes if v['op'] != 'observe']
        self.assertEqual([v['op'] for v in mutations], ['action', 'direct', 'direct', 'direct'])
        self.assertEqual([v['body']['command'] for v in mutations[1:3]],
                         ['kill ' + e['uuid'] for e in h.es])
        self.assertEqual(mutations[-1]['body'], {'key': 'key.keyboard.escape', 'action': 'click'})
        self.assertTrue(all(v['session_id'] == h.b.resident_session for v in self.q.envelopes))
        self.assertEqual(mutations[0]['request_id'], h.b.request_id)
        self.assertEqual(mutations[0]['encounter_scope'], h.b.encounter_request['encounter_scope'])
        self.assertIs(mutations[0]['approach'], False)
        self.assertIs(mutations[0]['shield'], False)

    def test_complete_null_rejection_preserves_narrow_closeout(self):
        h = self.h
        record = self.submit_and_record(rejection(h.b))
        self.assertEqual(record['resolved_outcome']['kind'], 'admission_rejected')
        self.assertTrue(h.s.cleanup_uuid(h.es[0]['uuid'], 'synthetic-authorization')['effect_confirmed'])

    def test_unknown_after_mailbox_submit_blocks_closeout_and_replay_on_reopen(self):
        h = self.h
        with self.assertRaises(SafetyHalt):
            self.submit_and_record(receipt(h.b, h.native, status='uncertain'))
        reopened = PostTrialSafety(h.o, h.s.root)
        command = {'op': 'action', **h.b.encounter_request}
        with self.assertRaises(SafetyHalt): reopened.claim_trial_dispatch(h.b.request_id, command)
        with self.assertRaises(SafetyHalt): reopened.reserve_trial(h.b, command, 'another-output')
        with self.assertRaises(SafetyHalt): reopened.cleanup_uuid(h.es[0]['uuid'], 'synthetic-authorization')
        with self.assertRaises(SafetyHalt): reopened.pause_once('synthetic-authorization')
        self.assertEqual([v['op'] for v in self.q.envelopes if v['op'] != 'observe'], ['action'])

    def test_queue_dedup_does_not_substitute_for_persistent_ledger_claim(self):
        h = self.h
        self.submit_and_record()
        command = {'op': 'action', **h.b.encounter_request}
        before = len(self.q.envelopes)
        self.assertEqual(self.q.submit(command, h.b.request_id), h.b.request_id)
        self.assertEqual(len(self.q.envelopes), before)
        # Even if the mailbox result is no longer retained, the case cannot replay.
        (self.q.root / 'results' / (h.b.request_id + '.json')).unlink()
        with self.assertRaises(SafetyHalt): h.s.claim_trial_dispatch(h.b.request_id, command)
        self.assertEqual(len(self.q.envelopes), before)


if __name__ == '__main__':
    unittest.main()
