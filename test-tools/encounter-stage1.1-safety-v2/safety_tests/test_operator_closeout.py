"""Append-only operator closeout: synthetic evidence and temporary ledgers only."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import test_active_case as active
from post_trial_safety import PostTrialSafety, SafetyHalt


class OperatorCloseoutTests(unittest.TestCase):
    def setUp(self):
        self.a = active.ActiveCaseTests(methodName='runTest')
        self.a.setUp()
        self.addCleanup(self.a.doCleanups)
        self.a.run_case()
        self.h, self.q = self.a.h, self.a.q
        self.s, self.b = self.h.s, self.h.b
        self.case = self.s._current()
        self.report_path = self.h.o.out / 'active.json'
        self.original_files = {p: p.read_bytes() for p in [self.report_path,
            self.case / 'SAFETY-STOP.json', self.case / 'trial-resolution.json',
            self.case / 'registration.json', self.s.root / 'CASE-LEDGER-USED.json',
            self.s.root / 'ledger-case-000001.anchor.json', self.s.ever_used]}
        report = json.loads(self.report_path.read_text())
        self.time = max(s['finished_monotonic'] for s in report['samples']) + 0.0000001
        self.serial = 0
        before = copy.deepcopy(self.q.current)
        current = copy.deepcopy(before)
        proof_before = self.read(before)
        cleanups = []
        for i, entity in enumerate(self.h.es):
            dispatch = self.event({'op': 'direct', 'endpoint': 'command',
                'body': {'command': 'kill ' + entity['uuid']}},
                {'ok': True, 'submitted': True}, 'direct_input_dispatched')
            current['state']['nearby']['entities'][i].update(alive=False, health=0)
            cleanups.append({'uuid': entity['uuid'], 'dispatch': dispatch,
                             'effect': self.read(current)})
        self.proof = dict(native_terminal=copy.deepcopy(self.h.native), before=proof_before,
                         cleanups=cleanups, final_observation=copy.deepcopy(current))
        self.q.current = copy.deepcopy(current)
        self.q.calls.clear()

    def event(self, body, result, reason=None):
        self.serial += 1
        rid = 'operator-proof-' + str(self.serial)
        start = self.time
        end = start + 0.0000001
        self.time = end + 0.0000001
        receipt = {'request_id': rid, 'session_id': self.b.resident_session,
                   'status': 'succeeded', 'result': copy.deepcopy(result)}
        if reason:
            receipt['reason'] = reason
        return {'intent': {'request_id': rid, 'body': body, 'started_monotonic': start},
                'receipt': {'started_monotonic': start, 'finished_monotonic': end, 'receipt': receipt}}

    def read(self, value):
        return self.event({'op': 'observe'}, value)

    def close(self, **changes):
        values = dict(case_id='active-one', authorization_ref='operator-closeout-approval',
                      evidence_ref='synthetic-complete-evidence', **copy.deepcopy(self.proof))
        values.update(changes)
        return self.s.record_operator_closeout(**values)

    def assert_original_unchanged(self):
        for p, value in self.original_files.items():
            self.assertEqual(p.read_bytes(), value, str(p))

    def assert_refuses_proof(self, proof):
        with self.assertRaises(SafetyHalt):
            self.close(**proof)
        self.assertFalse((self.case / 'operator-closeout.json').exists())
        self.assertEqual(self.q.mutations(), [])

    def next_case(self, *, active_case=True):
        new = [dict(e, entity_id=e['entity_id'] + 10,
            uuid='00000000-0000-4000-8000-%012d' % (e['entity_id'] + 10)) for e in self.h.es]
        obs = copy.deepcopy(self.q.current)
        values = obs['state']['nearby']['entities'] + [dict(e, alive=True, health=20) for e in new]
        obs['state']['nearby'].update(entities=values, total=len(values), returned=len(values))
        self.q.current = obs
        second = PostTrialSafety(SimpleNamespace(**{**vars(self.h.o), 'out': self.h.base / 'second-output'}), self.s.root)
        args = dict(case_id='independent-two', entities=new, observation=copy.deepcopy(obs),
            evidence_ref='new-independent-preflight', authorization_ref='new-independent-approval',
            previous_case_authorization_ref='new-independent-approval')
        if active_case:
            args.update(active_ai_proof={'entities': [{'uuid': e['uuid'], 'no_ai': False,
                'is_baby': False, 'evidence_ref': 'new-active-proof'} for e in new]},
                pause_authorization_ref='new-pause-approval')
        else:
            args['noai_proof'] = {'entities': [{'uuid': e['uuid'], 'no_ai': True,
                                               'evidence_ref': 'new-noai-proof'} for e in new]}
        return second, args

    def test_records_dead_corpses_append_only_with_only_fresh_read(self):
        result = self.close()
        self.assertTrue(result['operator_closeout_verified'])
        self.assertFalse(result['ordinary_mutation_permission'])
        self.assertFalse(result['controlled_trial_accepted'])
        self.assertFalse(result['live_acceptance_proven'])
        self.assertEqual([c[1]['op'] for c in self.q.calls if c[0] == 'submit'], ['observe'])
        self.assert_original_unchanged()
        self.proof['cleanups'][0]['uuid'] = 'changed-external-copy'
        self.s._verified_operator_closeout(self.case)
        with self.assertRaises(SafetyHalt):
            self.close()
        with self.assertRaises(SafetyHalt):
            self.s.assert_mutation_allowed(body={'op': 'direct'}, request_id='anything')
        with self.assertRaises(SafetyHalt):
            self.s.cleanup_uuid(self.h.es[0]['uuid'], 'any')
        self.assertEqual(self.q.mutations(), [])

    def test_verified_closeout_allows_new_explicit_active_case_in_same_ledger(self):
        self.close()
        second, args = self.next_case()
        result = second.register_active_case(**args)
        self.assertEqual(result['case_id'], 'independent-two')
        self.assertEqual(second.root, self.s.root)
        self.assertTrue((self.s.root / 'case-000002' / 'registration.json').is_file())
        self.assert_original_unchanged()
        self.assertEqual(self.q.mutations(), [])

    def test_verified_active_closeout_can_precede_independent_noai_case(self):
        self.close()
        second, args = self.next_case(active_case=False)
        self.assertFalse(second.register_noai_case(**args)['active_ai_supported'])
        self.assert_original_unchanged()

    def test_next_case_stays_blocked_without_closeout_or_new_approval(self):
        second, args = self.next_case()
        with self.assertRaises(SafetyHalt):
            second.register_active_case(**args)
        self.assertFalse((self.s.root / 'case-000002').exists())

    def test_old_case_or_closeout_authorization_cannot_authorize_next_case(self):
        self.close()
        second, args = self.next_case()
        for old in ('synthetic-active-approval', 'operator-closeout-approval'):
            with self.subTest(old=old), self.assertRaises(SafetyHalt):
                second.register_active_case(**dict(args, previous_case_authorization_ref=old))

    def test_wrong_case_or_missing_authorization_refuses(self):
        for change in ({'case_id': 'foreign'}, {'authorization_ref': ''}, {'evidence_ref': ''}):
            with self.subTest(change=change), self.assertRaises(SafetyHalt):
                self.close(**change)
        self.assertEqual(self.q.calls, [])

    def test_missing_effect_or_second_cleanup_cannot_use_submitted_ack(self):
        for which in ('effect', 'second'):
            proof = copy.deepcopy(self.proof)
            if which == 'effect':
                proof['cleanups'][0].pop('effect')
            else:
                proof['cleanups'].pop()
            self.assert_refuses_proof(proof)

    def test_foreign_uuid_broad_command_and_unknown_ack_refuse(self):
        for which in ('uuid', 'selector', 'unknown', 'wrong_session', 'wrong_request'):
            proof = copy.deepcopy(self.proof)
            part = proof['cleanups'][0]
            if which == 'uuid': part['uuid'] = self.h.es[1]['uuid']
            if which == 'selector': part['dispatch']['intent']['body']['body']['command'] = 'kill @e'
            if which == 'unknown': part['dispatch']['receipt']['receipt']['post_uncertain'] = True
            if which == 'wrong_session': part['dispatch']['receipt']['receipt']['session_id'] = 'foreign'
            if which == 'wrong_request': part['dispatch']['receipt']['receipt']['request_id'] = 'foreign'
            self.assert_refuses_proof(proof)

    def test_absent_foreign_or_contradictory_target_never_proves_death(self):
        for which in ('absent', 'foreign', 'alive_zero', 'dead_positive', 'alive_positive'):
            proof = copy.deepcopy(self.proof)
            obs = proof['cleanups'][0]['effect']['receipt']['receipt']['result']
            target = obs['state']['nearby']['entities'][0]
            if which == 'absent':
                obs['state']['nearby']['entities'].pop(0)
                obs['state']['nearby'].update(total=1, returned=1)
            if which == 'foreign': target['uuid'] = '00000000-0000-4000-8000-000000000999'
            if which == 'alive_zero': target['alive'] = True
            if which == 'dead_positive': target['health'] = 20
            if which == 'alive_positive': target.update(alive=True, health=20)
            self.assert_refuses_proof(proof)

    def test_missing_pause_release_coverage_or_matching_terminal_refuses(self):
        for which in ('paused', 'held', 'truncated', 'position', 'terminal'):
            proof = copy.deepcopy(self.proof)
            obs = proof['before']['receipt']['receipt']['result']
            if which == 'paused': obs['state']['paused'] = False
            if which == 'held': obs['status']['held_mappings'] = ['key.forward']
            if which == 'truncated': obs['state']['nearby']['truncated'] = True
            if which == 'position': proof['cleanups'][0]['effect']['receipt']['receipt']['result']['state']['player']['x'] += 1
            if which == 'terminal': obs['action']['reason'] = 'different_terminal'
            self.assert_refuses_proof(proof)

    def test_reordered_duplicate_pretrial_and_future_timing_refuse(self):
        for which in ('reordered', 'duplicate', 'pretrial', 'future'):
            proof = copy.deepcopy(self.proof)
            if which == 'reordered': proof['cleanups'].reverse()
            if which == 'duplicate':
                d = proof['cleanups'][0]['dispatch']; rid = proof['before']['intent']['request_id']
                d['intent']['request_id'] = d['receipt']['receipt']['request_id'] = rid
            if which == 'pretrial':
                d = proof['before']; d['intent']['started_monotonic'] = d['receipt']['started_monotonic'] = 0
                d['receipt']['finished_monotonic'] = .1
            if which == 'future':
                for d in [proof['before']] + [p[k] for p in proof['cleanups'] for k in ('dispatch', 'effect')]:
                    d['intent']['started_monotonic'] += 1e9
                    d['receipt']['started_monotonic'] += 1e9
                    d['receipt']['finished_monotonic'] += 1e9
            self.assert_refuses_proof(proof)

    def test_foreign_final_summary_or_changed_original_report_refuses(self):
        proof = copy.deepcopy(self.proof)
        proof['final_observation']['state']['player']['x'] += 1
        self.assert_refuses_proof(proof)
        self.report_path.write_text(self.report_path.read_text() + '\n')
        with self.assertRaisesRegex(SafetyHalt, 'original_trial_artifact_changed'):
            self.close()

    def test_only_separate_active_closeout_stop_reason_is_eligible(self):
        path = self.case / 'SAFETY-STOP.json'
        data = json.loads(path.read_text())
        data['reason'] = 'main_trial_unknown_or_release_unverified'
        path.write_text(json.dumps(data))
        Path(str(path) + '.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(SafetyHalt, 'cannot_clear_unknown_or_other_stop'):
            self.close()
        self.assertEqual(self.q.calls, [])

    def test_fresh_state_cannot_be_unpaused_or_resurrected(self):
        self.q.current['state']['paused'] = False
        with self.assertRaisesRegex(SafetyHalt, 'actual_pause'):
            self.close()
        self.assertFalse((self.case / 'operator-closeout.json').exists())
        self.q.current['state']['paused'] = True
        self.q.current['state']['nearby']['entities'][0].update(alive=True, health=20)
        with self.assertRaisesRegex(SafetyHalt, 'current_living_or_conflicting'):
            self.close()
        self.assertEqual(self.q.mutations(), [])

    def test_rehashed_saved_proof_is_recomputed_before_next_case(self):
        self.close()
        path = self.case / 'operator-closeout.json'
        data = json.loads(path.read_text())
        data['proof']['cleanups'][0]['effect']['receipt']['receipt']['result']['state']['nearby']['entities'][0]['alive'] = True
        raw = json.dumps(data['proof'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        data['proof_sha256'] = hashlib.sha256(raw).hexdigest()
        path.write_text(json.dumps(data))
        Path(str(path) + '.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
        second, args = self.next_case()
        with self.assertRaisesRegex(SafetyHalt, 'exact_death_not_observed'):
            second.register_active_case(**args)
        self.assertFalse((self.s.root / 'case-000002').exists())


if __name__ == '__main__':
    unittest.main()
