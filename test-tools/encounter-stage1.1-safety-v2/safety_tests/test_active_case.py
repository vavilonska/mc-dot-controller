"""Offline explicit-active registration and automated pause-first ordering tests."""
import copy
import json
from pathlib import Path
import sys
import unittest

import test_post_trial_safety as support
from fixtures_support import setup, receipt, rejection
from encounter_binding import EncounterBinding
from post_trial_safety import PostTrialSafety, SafetyHalt, PAUSE_SCREEN
from single_case import run_registered_case

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'candidates/encounter-stage1.1/resident-controller'))
from active_case import run_registered_active_case


def opt_in_native(native):
    native = copy.deepcopy(native)
    native['result']['combat']['encounter']['encounter_pause_on_terminal'] = True
    if native['status'] != 'running':
        native['result']['encounter_terminal_pause'] = {
            'hook_schema_version': 1, 'requested': True, 'attempted': True,
            'pause_call_attempted': True, 'outcome': 'screen_installed',
            'pause_screen_installed': True, 'already_pause_screen': False,
            'client_paused_observed': False, 'pause_effect_confirmed': False,
            'server_confirmed': False,
            'input_release_confirmed': native['result']['input_release_confirmed']}
    return native


class ActiveQueue(support.FakeQueue):
    def __init__(self, binding, native, report_path):
        super().__init__(binding)
        self.native = native
        self.report_path = report_path
        self.main_response = receipt(binding, native)
        self.action_seen = False
        self.polls = 0
        self.immediate_terminal = False
        self.damage = False
        self.observation_error = False
        self.pause_error = False
        self.pause_effect = True
        self.action_error = False
        self.resume_error = False
        self.pause_calls = 0

    def result(self, rid):
        self.calls.append(('result', rid))
        if rid != self.binding.request_id or not self.action_seen:
            return None
        self.polls += 1
        if self.polls == 1 and not self.immediate_terminal:
            return None
        if self.main_response.get('action_id', 'present') is not None:
            health = self.current['state']['player']['health']
            self.current = support.sample(self.binding, self.native)
            self.current['state']['player']['health'] = health
            if (self.pause_effect and self.native['result']['encounter_terminal_pause']['outcome'] == 'screen_installed'):
                self.current['state'].update(paused=True, screen_open=True)
                self.current['screen'] = {'open': True, 'class': PAUSE_SCREEN}
        return copy.deepcopy(self.main_response)

    def submit(self, body, request_id):
        if body['op'] == 'direct':
            assert body == {'op': 'direct', 'endpoint': 'raw-key',
                            'body': {'key': 'key.keyboard.escape', 'action': 'click'}}
            assert self.current['state']['paused'] is True
            self.calls.append(('submit', copy.deepcopy(body), request_id))
            self.current['state'].update(paused=False, screen_open=False)
            self.current['screen'] = {'open': False}
            if self.resume_error:
                raise OSError('synthetic resume unknown')
            self.results[request_id] = {'request_id': request_id,
                'session_id': self.binding.resident_session, 'status': 'succeeded',
                'reason': 'direct_input_dispatched', 'result': {'ok': True,
                    'key': 'key.keyboard.escape', 'action': 'click', 'down': False}}
            return request_id
        if body['op'] == 'action':
            self.calls.append(('submit', copy.deepcopy(body), request_id))
            self.action_seen = True
            _, running = setup('running', request_id=self.binding.request_id)
            running['action_session'] = self.binding.action_session
            self.current = support.sample(self.binding, opt_in_native(running))
            if self.action_error:
                raise OSError('synthetic main post unknown')
            return request_id
        if body['op'] == 'encounter_pause':
            self.calls.append(('submit', copy.deepcopy(body), request_id))
            self.pause_calls += 1
            assert not self.report_path.exists(), 'Report persisted before pause dispatch'
            assert body['expected_resident_session'] == self.binding.resident_session
            present = self.action_seen and self.main_response.get('action_id', 'present') is not None
            health = self.current['state']['player']['health']
            self.current = support.sample(self.binding, self.native if present else None)
            self.current['state']['player']['health'] = health
            if self.pause_effect:
                self.current['state'].update(paused=True, screen_open=True)
                self.current['screen'] = {'open': True, 'class': PAUSE_SCREEN}
            if self.pause_error:
                raise OSError('synthetic pause post unknown')
            value = {'ok': True, 'protocol': 'mineclient-bridge', 'schema_version': 2,
                'pause_schema_version': 1, 'action': 'ensure_paused',
                'pause_requested': True, 'pause_screen_installed': True,
                'already_pause_screen': False, 'client_paused_observed': False,
                'pause_effect_confirmed': False, 'server_confirmed': False,
                'action_session': self.binding.action_session,
                'world_generation': self.binding.world_generation,
                'player_uuid': self.binding.player_uuid,
                'expected_action_id': self.binding.expected_action_id,
                'expected_action_present': present,
                'client_action': copy.deepcopy(self.native) if present else None,
                'input_release_confirmed': True if present else None}
            self.results[request_id] = {'request_id': request_id,
                'session_id': self.binding.resident_session, 'status': 'succeeded', 'result': value}
            return request_id
        if body['op'] == 'observe' and self.action_seen and self.pause_calls == 0:
            if self.observation_error:
                raise OSError('synthetic observation unknown')
            if self.damage:
                self.current['state']['player']['health'] = 19
        return super().submit(body, request_id)


class ActiveCaseTests(unittest.TestCase):
    def setUp(self):
        self.h = support.SafetyTests(methodName='runTest')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        h = self.h
        request = h.b.encounter_request
        request['encounter_pause_on_terminal'] = True
        h.b = EncounterBinding(h.b.request_id, h.b.resident_session, h.b.action_session,
            h.b.world_generation, h.b.player_uuid, h.b.action_kind, encounter_request=request)
        h.native = opt_in_native(h.native)
        self.q = ActiveQueue(h.b, h.native, h.o.out / 'active.json')
        h.o.c = self.q
        self.q.current['state'].update(paused=True, screen_open=True)
        self.q.current['screen'] = {'open': True, 'class': PAUSE_SCREEN}
        self.proof = {'entities': [{'uuid': e['uuid'], 'no_ai': False, 'is_baby': False,
                                    'evidence_ref': 'synthetic-real-format-ai-proof'} for e in h.es]}

    def register(self, **changes):
        values = dict(case_id='active-one', entities=self.h.es,
            observation=copy.deepcopy(self.q.current), evidence_ref='synthetic-preflight',
            active_ai_proof=self.proof, authorization_ref='synthetic-active-approval',
            pause_authorization_ref='synthetic-pause-first-approval')
        values.update(changes)
        return self.h.s.register_active_case(**values)

    def run_case(self):
        self.register()
        return run_registered_active_case(self.h.s, self.h.b, 'active',
            resume_authorization_ref='synthetic-explicit-resume-approval')

    def ops(self):
        return [v[1]['op'] for v in self.q.calls if v[0] == 'submit']

    def test_registration_is_explicit_adult_active_and_native_paused(self):
        registered = self.register()
        self.assertTrue(registered['active_ai_supported'])
        self.assertNotIn('noai_proof', registered)
        self.assertEqual(registered['active_ai_proof'], self.proof)
        with self.assertRaisesRegex(SafetyHalt, 'pause_first'):
            run_registered_case(self.h.s, self.h.b, 'wrong-entry')
        self.assertEqual(self.q.mutations(), [])

    def test_active_case_cannot_dispatch_without_native_terminal_pause_opt_in(self):
        self.register()
        request = self.h.b.encounter_request
        request.pop('encounter_pause_on_terminal')
        b = self.h.b
        without = EncounterBinding(b.request_id, b.resident_session, b.action_session,
            b.world_generation, b.player_uuid, b.action_kind, encounter_request=request)
        with self.assertRaisesRegex(SafetyHalt, 'requires_native_terminal_pause'):
            run_registered_active_case(self.h.s, without, 'missing-flag')
        with self.assertRaisesRegex(SafetyHalt, 'requires_native_terminal_pause'):
            self.h.s.reserve_trial(without, {'op': 'action', **without.encounter_request}, 'missing-flag')
        self.assertEqual(self.q.mutations(), [])

    def test_false_proof_baby_unpaused_or_missing_pause_approval_refuse(self):
        for key, value in [('no_ai', True), ('is_baby', True), ('is_baby', None)]:
            proof = copy.deepcopy(self.proof)
            proof['entities'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(SafetyHalt):
                self.register(active_ai_proof=proof)
        with self.assertRaises(SafetyHalt):
            self.register(pause_authorization_ref='')
        unpaused = copy.deepcopy(self.q.current)
        unpaused['state']['paused'] = False
        with self.assertRaises(SafetyHalt):
            self.register(observation=unpaused)
        self.assertEqual(self.q.mutations(), [])

    def test_terminal_pauses_before_extra_read_or_report_and_never_cleans_up(self):
        result = self.run_case()
        self.assertEqual(self.q.pause_calls, 0)
        ops = self.ops()
        self.assertEqual([v for v in ops if v != 'observe'], ['direct', 'action'])
        self.assertTrue(result['pause']['fallback_skipped_prior_native_attempt'])
        self.assertTrue(result['pause']['native_pause_observed'])
        self.assertTrue(result['pause']['native_release_observed'])
        self.assertEqual(result['closeout'], [])
        self.assertFalse(result['live_acceptance_proven'])
        for operation in [lambda: self.h.s.cleanup_uuid(self.h.es[0]['uuid'], 'approval'),
                          lambda: self.h.s.pause_once('approval'),
                          lambda: run_registered_active_case(PostTrialSafety(self.h.o, self.h.s.root), self.h.b, 'again',
                              resume_authorization_ref='synthetic-explicit-resume-approval')]:
            with self.assertRaises(SafetyHalt):
                operation()
        self.assertEqual(self.q.pause_calls, 0)

    def test_first_terminal_result_pauses_without_running_observation_delay(self):
        self.q.immediate_terminal = True
        result = self.run_case()
        ops = self.ops()
        self.assertEqual(ops[ops.index('direct'):], ['direct', 'action', 'observe'])
        self.assertTrue(result['health']['stop_required'])  # No invented running health sample.
        self.assertTrue(result['pause']['native_pause_observed'])

    def test_damage_and_observation_failure_pause_once_without_cancel_or_cleanup(self):
        self.q.damage = True
        result = self.run_case()
        self.assertTrue(result['health']['stop_latched'])
        self.assertEqual([v for v in self.ops() if v != 'observe'], ['direct', 'action', 'encounter_pause'])

    def test_unknown_observation_uses_reserved_pause_without_retry(self):
        self.q.observation_error = True
        result = self.run_case()
        self.assertEqual(self.q.pause_calls, 1)
        self.assertIn('synthetic observation unknown', result['stopped_reason'])
        self.assertTrue(result['pause']['native_pause_observed'])

    def test_unknown_pause_is_not_upgraded_by_later_paused_read_or_retried(self):
        self.q.damage = True
        self.q.pause_error = True
        result = self.run_case()
        self.assertEqual(self.q.pause_calls, 1)
        self.assertTrue(result['pause']['native_pause_observed'])
        self.assertIn('synthetic pause post unknown', result['stopped_reason'])
        self.assertIn('error', result['pause'])

    def test_screen_placement_without_actual_paused_effect_is_not_success(self):
        self.q.pause_effect = False
        result = self.run_case()
        self.assertFalse(result['pause']['native_pause_observed'])
        self.assertIn('active_pause_effect_unverified', result['stopped_reason'])

    def test_explicit_null_rejection_still_pauses_without_fabricated_action(self):
        self.q.main_response = rejection(self.h.b)
        self.q.immediate_terminal = True
        result = self.run_case()
        self.assertEqual(self.q.pause_calls, 1)
        self.assertIsNone(result['pause']['response']['result']['client_action'])
        self.assertFalse(result['pause']['response']['result']['expected_action_present'])

    def test_main_post_unknown_still_sends_only_one_reserved_pause(self):
        self.q.action_error = True
        result = self.run_case()
        self.assertEqual(self.q.pause_calls, 1)
        self.assertIn('synthetic main post unknown', result['stopped_reason'])
        self.assertEqual([v for v in self.ops() if v != 'observe'], ['direct', 'action', 'encounter_pause'])

    def test_unknown_native_hook_never_causes_outer_pause_post_or_upgrades_main(self):
        hook = self.q.native['result']['encounter_terminal_pause']
        hook.update(outcome='unconfirmed', pause_screen_installed=None,
                    already_pause_screen=None, client_paused_observed=None)
        self.q.main_response = receipt(self.h.b, self.q.native, status='uncertain')
        self.q.immediate_terminal = True
        result = self.run_case()
        self.assertEqual(self.q.pause_calls, 0)
        self.assertTrue(result['pause']['fallback_skipped_prior_native_attempt'])
        self.assertEqual(result['pause']['native_hook']['outcome'], 'unconfirmed')
        self.assertNotEqual((result['resolution'] or {}).get('resolved_outcome', {}).get('kind'), 'bound_terminal')
        self.assertFalse(result['live_acceptance_proven'])

    def test_resume_unknown_never_submits_main_and_uses_one_distinct_pause(self):
        self.q.resume_error = True
        result = self.run_case()
        self.assertFalse(self.q.action_seen)
        self.assertEqual(self.q.pause_calls, 1)
        self.assertEqual([v for v in self.ops() if v != 'observe'], ['direct', 'encounter_pause'])
        report = json.loads((self.h.o.out / 'active.json').read_text())
        self.assertFalse(report['main_submit_attempted'])
        self.assertEqual(report['response']['status'], 'not_submitted')
        self.assertIn('synthetic resume unknown', result['stopped_reason'])

    def test_resume_to_submit_has_no_observe_and_claims_already_exist(self):
        actual_submit = self.q.submit
        def checked(body, request_id):
            if body['op'] == 'direct':
                case = self.h.s._current()
                for name in ('trial-dispatch.json', 'active-resume-reservation.json',
                             'active-resume-dispatch.json', 'active-pause-reservation.json'):
                    self.assertTrue((case / name).is_file())
            return actual_submit(body, request_id)
        self.q.submit = checked
        self.run_case()
        ops = self.ops()
        self.assertEqual(ops[ops.index('direct') + 1], 'action')


if __name__ == '__main__':
    unittest.main()
