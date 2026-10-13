"""Narrow integration of the real boat guard's pure validator into rollover.

Synthetic Queue and temporary fixed stores only; no real ledger/game I/O.
"""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from boat_entry_guard import BoatEntryGuard, validate_store
from post_trial_safety import SafetyHalt
from session_rollover import durable_queue_audit, verify_saved_queue_audit, request_consumed
from test_boat_entry_guard import Queue, B


def rewrite(path,value):
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
    path.write_bytes(raw);Path(str(path)+'.sha256').write_text(hashlib.sha256(raw).hexdigest()+'\n')


class RolloverBoatEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.q=Queue(self.temp.name);self.q.state.update(state='ready',reason=None)
        for name in ('results','inbox','working'):(self.q.root/name).mkdir(exist_ok=True)
        self.s=SimpleNamespace(root=self.q.root/'safety-ledger',_cases=lambda:[])
    def prepare(self):
        return BoatEntryGuard(self.q,'guard-once',B,surface_y=63,
            support_evidence_ref='synthetic-solid-support',pause_authorization_ref='synthetic-pause-approval',
            clock=lambda:1.,wall_clock=lambda:100.)
    def complete(self,kind='entry_ready'):
        guard=self.prepare();self.q.resume_externally()
        if kind!='entry_ready':self.q.current['state']['player']['air']=297
        if kind=='unknown':self.q.pause_error=True
        result=guard.check(lambda value:None,main_action_submitted=False)
        return guard,result
    def audit(self):return durable_queue_audit(self.s)
    def result_path(self):return self.q.root/'boat-entry-guard/guard-once.result.json'
    def test_no_store_preserves_existing_rollover_audit(self):
        self.assertEqual(self.audit()['durable_gate_files'],{})
    def test_existing_empty_store_is_a_consumed_partial_claim(self):
        (self.q.root/'boat-entry-guard').mkdir()
        with self.assertRaises(SafetyHalt):self.audit()
    def test_reservation_only_cannot_be_forgotten_after_restart(self):
        self.prepare()
        with self.assertRaises(SafetyHalt):self.audit()
    def test_unknown_pause_cannot_be_upgraded_by_observed_pause_or_expired_result(self):
        guard,result=self.complete('unknown')
        self.assertTrue(result['pause_attempted']);self.assertFalse(result['pause_acknowledged'])
        self.assertTrue(result['pause_observed']);self.assertEqual(list((self.q.root/'results').iterdir()),[])
        with self.assertRaises(SafetyHalt):self.audit()
        self.assertEqual(self.q.events.count('encounter_pause'),1)
    def test_known_entry_ready_is_only_guard_completion_and_pins_all_four_files(self):
        guard,result=self.complete()
        self.assertTrue(result['entry_ready']);self.assertIs(result['main_action_submitted'],False)
        self.assertIs(result['main_action_accepted'],False)
        hashes=validate_store(self.q.root)['files'];audit=self.audit()
        self.assertEqual(audit['durable_gate_files'],hashes);self.assertEqual(len(hashes),4)
        verify_saved_queue_audit(self.s,audit)
        self.assertNotIn('boat_main_action_completed',audit)
    def test_known_missing_action_pause_preserves_null_release(self):
        guard,result=self.complete('paused')
        reply=result['pause_receipt']['result']
        self.assertIs(reply['expected_action_present'],False);self.assertIsNone(reply['client_action'])
        self.assertIsNone(reply['input_release_confirmed'])
        before=self.result_path().read_bytes();self.audit()
        self.assertEqual(self.result_path().read_bytes(),before)
        self.assertIsNone(json.loads(before)['pause_receipt']['result']['input_release_confirmed'])
    def test_body_binding_and_pause_id_must_match_original_claim(self):
        self.complete('paused');original=json.loads(self.result_path().read_text())
        for mutate in [lambda r:r['binding'].update(world_generation=B['player_uuid']),
                       lambda r:r['command']['body'].update(expected_action_id='foreign'),
                       lambda r:r.update(pause_request_id='foreign')]:
            bad=copy.deepcopy(original);mutate(bad);rewrite(self.result_path(),bad)
            with self.assertRaises(SafetyHalt):self.audit()
        rewrite(self.result_path(),original)
    def test_borrowed_pause_ack_or_forged_release_is_rejected_even_with_new_hash(self):
        self.complete('paused');original=json.loads(self.result_path().read_text())
        for mutation in ('request','release'):
            bad=copy.deepcopy(original)
            if mutation=='request':bad['pause_receipt']['request_id']='borrowed-other-case'
            else:bad['pause_receipt']['result']['input_release_confirmed']=True
            for raw in bad['requests']:
                if raw['command'].get('op')=='encounter_pause':raw['receipt']=copy.deepcopy(bad['pause_receipt'])
            rewrite(self.result_path(),bad)
            with self.assertRaises(SafetyHalt):self.audit()
        rewrite(self.result_path(),original)
    def test_pinned_record_or_sidecar_change_is_rejected(self):
        self.complete();audit=self.audit();path=self.result_path();raw=path.read_bytes();digest=Path(str(path)+'.sha256')
        path.write_bytes(raw+b' ')
        with self.assertRaises(SafetyHalt):verify_saved_queue_audit(self.s,audit)
        path.write_bytes(raw);digest.write_text('0'*64+'\n')
        with self.assertRaises(SafetyHalt):verify_saved_queue_audit(self.s,audit)
    def test_pinned_guard_deletion_is_not_a_new_empty_store(self):
        self.complete();audit=self.audit();self.result_path().unlink()
        with self.assertRaises(SafetyHalt):verify_saved_queue_audit(self.s,audit)
        with self.assertRaises(SafetyHalt):self.audit()
    def test_pause_id_stays_consumed_after_retained_mailbox_result_expires(self):
        guard,result=self.complete('paused')
        self.assertEqual(list((self.q.root/'results').iterdir()),[])
        self.assertTrue(request_consumed(self.s,guard.pause_id))
    def test_entry_ready_does_not_resolve_a_separate_unknown_boat_action(self):
        self.complete()
        (self.q.root/'results/boat-main.json').write_text(json.dumps({'request_id':'boat-main',
            'session_id':B['resident_session'],'status':'uncertain','post_uncertain':True}))
        with self.assertRaisesRegex(SafetyHalt,'durable_queue_outcome_unknown'):self.audit()

    def test_real_resident_hex_format_is_preserved_in_known_guard_binding(self):
        with patch.dict(B,{'resident_session':B['resident_session'].replace('-','')}):
            self.q=Queue(self.temp.name)
            guard,result=self.complete('paused')
            self.assertEqual(len(result['binding']['resident_session']),32)
            self.assertEqual(self.audit()['durable_gate_files'],validate_store(self.q.root)['files'])
