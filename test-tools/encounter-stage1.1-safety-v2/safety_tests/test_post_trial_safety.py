"""Offline-only safety capability tests. No real transport imports or live I/O."""
import copy
import hashlib
import json
import shutil
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'adaptation_tests'))
from fixtures_support import setup, observation, receipt, rejection
from post_trial_safety import PostTrialSafety, SafetyHalt, PAUSE_SCREEN


class FakeQueue:
    def __init__(self, binding):
        self.binding = binding
        self.current = sample(binding)
        self.calls = []
        self.results = {}
        self.main_result = None
        self.direct_status = 'succeeded'
        self.direct_uncertain = False
        self.remove_target = True
        self.pause_effect = True
        self.throw_submit = False
        self.throw_wait = False
        self.after_hook = None
        self.session_data = {'session_id': binding.resident_session, 'state': 'ready',
            'bridge_identity': {'action_session': binding.action_session},
            'active_request_id': None, 'active_action_id': None, 'pending': 0,
            'aim_lock': {'active': False}, 'combat': {'active': False, 'held_mappings': []}}
    def session(self):
        self.calls.append(('session',))
        return copy.deepcopy(self.session_data)
    def result(self, rid):
        self.calls.append(('result', rid))
        return copy.deepcopy(self.main_result)
    def submit(self, body, request_id):
        self.calls.append(('submit', copy.deepcopy(body), request_id))
        if self.throw_submit:
            raise OSError('synthetic submit interrupted')
        if body['op'] == 'observe':
            result = copy.deepcopy(self.current)
            response = {'request_id': request_id, 'session_id': self.binding.resident_session,
                        'status': 'succeeded', 'result': result}
        else:
            if body['endpoint'] == 'command':
                target = body['body']['command'].removeprefix('kill ')
                result = {'ok': True, 'submitted': True}
                if self.remove_target:
                    items = [e for e in self.current['state']['nearby']['entities'] if e['uuid'] != target]
                    self.current['state']['nearby'].update(entities=items, total=len(items), returned=len(items))
            elif body['endpoint'] == 'raw-key':
                result = {'ok': True, 'key': 'key.keyboard.escape', 'action': 'click', 'down': False}
                if self.pause_effect:
                    self.current['state'].update(paused=True, screen_open=True)
                    self.current['screen'] = {'open': True, 'class': PAUSE_SCREEN}
            else:
                raise AssertionError('arbitrary mutation escaped capability')
            response = {'request_id': request_id, 'session_id': self.binding.resident_session,
                'status': self.direct_status, 'reason': 'direct_input_dispatched',
                'result': result, 'post_uncertain': self.direct_uncertain}
            if self.after_hook:
                self.after_hook(self.current)
        self.results[request_id] = response
        return request_id
    def wait(self, rid, timeout):
        self.calls.append(('wait', rid, timeout))
        if self.throw_wait:
            raise TimeoutError('synthetic wait interrupted')
        return copy.deepcopy(self.results[rid])
    def mutations(self):
        return [c for c in self.calls if c[0] == 'submit' and c[1]['op'] != 'observe']


def entities(binding):
    return [dict(e, x=i + 1, y=64, z=0) for i, e in enumerate(binding.encounter_request['encounter_scope'])]


def sample(binding, native=None):
    result = observation(binding, native)
    es = [dict(e, alive=True, health=20) for e in entities(binding)]
    result['state']['nearby'] = {'radius': 8, 'total': 2, 'returned': 2, 'truncated': False, 'entities': es}
    result['screen'] = {'open': False}
    result['aim_lock'] = {'active': False}
    result['combat'] = {'active': False, 'held_mappings': []}
    return result


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.b, self.native = setup()
        self.queue = FakeQueue(self.b)
        self.o = types.SimpleNamespace(c=self.queue, out=self.base / 'output',
            resident=self.b.resident_session, session=self.b.action_session,
            world=self.b.world_generation, player=self.b.player_uuid)
        self.s = PostTrialSafety(self.o, self.base / 'shared-ledger')
        self.es = entities(self.b)
        self.proof = {'entities': [{'uuid': e['uuid'], 'no_ai': True,
                                   'evidence_ref': 'operator-noai-nbt-proof'} for e in self.es]}
    def register(self, **changes):
        values = dict(case_id='noai-one', entities=self.es, observation=sample(self.b),
            evidence_ref='registration-artifact', noai_proof=self.proof, authorization_ref='user-noai-authorization')
        values.update(changes)
        return self.s.register_noai_case(**values)
    def reserve(self):
        command = {'op': 'action', **self.b.encounter_request}
        self.s.reserve_trial(self.b, command, 'one')
        self.s.claim_trial_dispatch(self.b.request_id, command, owned_request=self.b.request_id)
        return command
    def record(self, response=None, after=None, **changes):
        command = self.reserve()
        report = {'name': 'one', 'request_id': self.b.request_id, 'binding': self.b.wire(),
            'command': command, 'before': sample(self.b), 'samples': [],
            'response': response if response is not None else receipt(self.b, self.native),
            'after': after if after is not None else sample(self.b, self.native),
            'interrupt_proof': None, 'summary': {'task_success': True, 'native_admission_confirmed': True},
            'outcome': {'kind': 'bound_terminal'}}
        report.update(changes)
        self.o.out.mkdir()
        (self.o.out / 'one.json').write_text(json.dumps(report))
        (self.o.out / 'STOP-RECONCILE.json').write_text('{"existing":true}')
        self.queue.current = copy.deepcopy(report['after'])
        return self.s.record_trial(report)
    def ready(self):
        self.register(); return self.record()
    def case(self):
        return self.s.root / 'case-000001'
    def test_constructor_has_no_io(self):
        self.assertFalse(self.s.root.exists()); self.assertEqual(self.queue.calls, [])
    def test_register_requires_exact_two_canonical_zombies(self):
        for value in [[], self.es[:1], self.es + self.es[:1], [dict(self.es[0], uuid='@e'), self.es[1]],
                      [dict(self.es[0], type='minecraft:skeleton'), self.es[1]], [dict(self.es[0], entity_id=True), self.es[1]]]:
            with self.subTest(value=value), self.assertRaises(SafetyHalt):
                self.register(entities=value)
        self.assertEqual(self.queue.mutations(), [])
    def test_noai_evidence_is_explicit_not_inferred_from_stationary(self):
        for proof in [{}, {'entities': []}, {'entities': [dict(p, no_ai=False) for p in self.proof['entities']]}]:
            with self.subTest(proof=proof), self.assertRaises(SafetyHalt): self.register(noai_proof=proof)
        self.assertEqual(self.queue.calls, [])
    def test_register_keeps_evidence_copy_and_current_authorization(self):
        self.register(); self.es[0]['x'] = 77
        self.assertEqual(json.loads((self.case() / 'registration.json').read_text())['entities'][0]['x'], 1)
        self.assertEqual(self.s.current_authorization_ref(), 'user-noai-authorization')
    def test_fresh_registration_required(self):
        self.queue.current['state']['nearby']['entities'][0]['x'] = 3
        with self.assertRaisesRegex(SafetyHalt, 'current_noai'): self.register()
        self.assertEqual(self.queue.mutations(), [])
    def test_registration_truncated_rejected(self):
        obs = sample(self.b); obs['state']['nearby']['truncated'] = True
        with self.assertRaisesRegex(SafetyHalt, 'nearby_not_complete'): self.register(observation=obs)
    def test_reserve_exact_scope_and_claim_only_once(self):
        self.register(); command = {'op': 'action', **self.b.encounter_request}
        self.s.reserve_trial(self.b, command, 'one')
        self.s.assert_mutation_allowed(request_id=self.b.request_id, body=command, owned_request=self.b.request_id)
        self.s.claim_trial_dispatch(self.b.request_id, command, owned_request=self.b.request_id)
        with self.assertRaisesRegex(SafetyHalt, 'already_consumed'):
            self.s.claim_trial_dispatch(self.b.request_id, command, owned_request=self.b.request_id)
        with self.assertRaises(SafetyHalt): self.s.assert_mutation_allowed(request_id='foreign', body={'op': 'combat_start'})
    def test_report_full_resolve_ignores_forged_summary(self):
        self.register()
        with self.assertRaisesRegex(SafetyHalt, 'unknown_or_release'):
            self.record(response=receipt(self.b, self.native, status='uncertain'))
        resolution = json.loads((self.case() / 'trial-resolution.json').read_text())
        self.assertFalse(resolution['narrow_safety_eligible'])
        self.assertEqual(resolution['resolved_outcome']['kind'], 'unknown_post_outcome')
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'operator-cleanup')
        with self.assertRaises(SafetyHalt): self.s.pause_once('operator-pause')
        self.assertEqual(self.queue.mutations(), [])
    def test_pending_main_blocks_cleanup(self):
        self.register()
        with self.assertRaises(SafetyHalt): self.record(response={'request_id': self.b.request_id, 'status': 'pending'})
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_unknown_terminal_and_missing_release_block_cleanup(self):
        self.register(); after = sample(self.b, self.native); after['status']['held_mappings'] = ['key.forward']
        with self.assertRaises(SafetyHalt): self.record(after=after)
        self.assertEqual(self.queue.mutations(), [])
    def test_complete_null_admission_allows_narrow_cleanup(self):
        self.register(); result = self.record(response=rejection(self.b), after=sample(self.b))
        self.assertTrue(result['narrow_safety_eligible'])
        self.assertEqual(result['resolved_outcome']['kind'], 'admission_rejected')
        cleanup = self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertTrue(cleanup['effect_confirmed']); self.assertFalse(cleanup['combat_success'])
    def test_binding_rejection_without_explicit_null_is_not_allowed(self):
        self.register()
        response = receipt(self.b, reason='action_world_changed', status='failed')
        with self.assertRaises(SafetyHalt): self.record(response=response, after=sample(self.b))
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
    def test_cleanup_exact_uuid_once_preserves_trial_and_stop(self):
        self.ready(); original = (self.o.out / 'one.json').read_bytes(); stop = (self.o.out / 'STOP-RECONCILE.json').read_bytes()
        result = self.s.cleanup_uuid(self.es[0]['uuid'], 'explicit-cleanup')
        self.assertEqual(len(self.queue.mutations()), 1)
        self.assertEqual(self.queue.mutations()[0][1], {'op': 'direct', 'endpoint': 'command', 'body': {'command': 'kill ' + self.es[0]['uuid']}})
        self.assertEqual(result['effect'], 'exact_uuid_absent_in_same_complete_coverage')
        self.assertFalse(result['task_success']); self.assertFalse(result['controlled_trial_accepted'])
        self.assertEqual(original, (self.o.out / 'one.json').read_bytes()); self.assertEqual(stop, (self.o.out / 'STOP-RECONCILE.json').read_bytes())
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'explicit-cleanup')
        self.assertEqual(len(self.queue.mutations()), 1)
    def test_immutable_intent_receipt_effect_are_separate(self):
        self.ready(); self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        for suffix in ('intent', 'receipt', 'effect'):
            self.assertTrue((self.case() / ('cleanup-' + self.es[0]['uuid'] + '.' + suffix + '.json')).is_file())
    def test_cleanup_dispatch_without_effect_is_not_success(self):
        self.ready(); self.queue.remove_target = False
        with self.assertRaisesRegex(SafetyHalt, 'safety_effect|cleanup_precondition'):
            self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[1]['uuid'], 'authorization')
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        self.assertEqual(len(self.queue.mutations()), 1)
        self.assertTrue((self.case() / 'SAFETY-STOP.json').exists())
    def test_kill_while_paused_never_unpauses_or_retries_if_ineffective(self):
        self.ready(); self.s.pause_once('authorization'); self.queue.remove_target = False
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertTrue(self.queue.current['state']['paused'])
        self.assertEqual([c[1]['endpoint'] for c in self.queue.mutations()], ['raw-key', 'command'])
    def test_unknown_cleanup_reply_never_replayed(self):
        self.ready(); self.queue.direct_uncertain = True
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(len(self.queue.mutations()), 1)
    def test_cleanup_submit_exception_leaves_durable_intent(self):
        self.ready(); original_submit = self.queue.submit
        def submit(body, request_id):
            if body['op'] == 'direct': raise OSError('synthetic unknown post')
            return original_submit(body, request_id)
        self.queue.submit = submit
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertTrue((self.case() / ('cleanup-' + self.es[0]['uuid'] + '.intent.json')).exists())
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[1]['uuid'], 'authorization')
    def test_reconstructed_helper_rejects_crash_left_intent(self):
        self.ready()
        (self.case() / ('cleanup-' + self.es[0]['uuid'] + '.intent.json')).write_text('{}')
        second = PostTrialSafety(self.o, self.s.root)
        with self.assertRaises(SafetyHalt):
            second.cleanup_uuid(self.es[1]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_forged_or_changed_original_report_blocks(self):
        self.ready(); (self.o.out / 'one.json').write_text('{}')
        with self.assertRaisesRegex(SafetyHalt, 'artifact_changed'): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_uuid_selector_name_unregistered_or_uppercase_rejected(self):
        self.ready()
        for target in ['@e', '@e[type=zombie]', 'Zombie', '00000000-0000-4000-8000-000000000099', self.es[0]['uuid'] + ';say unsafe']:
            with self.subTest(target=target), self.assertRaises(SafetyHalt): self.s.cleanup_uuid(target, 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_target_missing_from_precheck_is_not_cleanup_success(self):
        self.ready(); self.queue.current['state']['nearby'].update(entities=[], total=0, returned=0)
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_entity_id_reuse_is_not_matching_uuid(self):
        self.ready(); self.queue.current['state']['nearby']['entities'][0]['uuid'] = '00000000-0000-4000-8000-000000000099'
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_post_absence_changed_coverage_is_not_effect(self):
        self.ready(); self.queue.after_hook = lambda obs: obs['state']['player'].update(x=0.1)
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(len(self.queue.mutations()), 1)
    def test_boundary_target_not_blindly_killed(self):
        self.ready(); self.queue.current['state']['nearby']['entities'][0]['x'] = 8
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_pause_once_exact_raw_key_proves_effect(self):
        self.ready(); result = self.s.pause_once('explicit-pause')
        self.assertEqual(result['effect'], 'native_escape_pause_observed')
        self.assertEqual(self.queue.mutations()[0][1], {'op': 'direct', 'endpoint': 'raw-key', 'body': {'key': 'key.keyboard.escape', 'action': 'click'}})
        with self.assertRaises(SafetyHalt): self.s.pause_once('explicit-pause')
        self.assertEqual(len(self.queue.mutations()), 1)
    def test_already_paused_does_not_toggle(self):
        self.ready(); self.queue.current['state'].update(paused=True, screen_open=True)
        self.queue.current['screen'] = {'open': True, 'class': PAUSE_SCREEN}
        result = self.s.pause_once('explicit-pause')
        self.assertEqual(result['effect'], 'already_paused_no_toggle'); self.assertEqual(self.queue.mutations(), [])
    def test_wrong_screen_never_escape_toggles(self):
        self.ready(); self.queue.current['state'].update(paused=True, screen_open=True)
        self.queue.current['screen'] = {'open': True, 'class': 'InventoryScreen'}
        with self.assertRaises(SafetyHalt): self.s.pause_once('explicit-pause')
        self.assertEqual(self.queue.mutations(), [])
    def test_pause_receipt_without_screen_effect_stops(self):
        self.ready(); self.queue.pause_effect = False
        with self.assertRaises(SafetyHalt): self.s.pause_once('explicit-pause')
        with self.assertRaises(SafetyHalt): self.s.pause_once('explicit-pause')
        self.assertEqual(len(self.queue.mutations()), 1)
    def test_active_pending_unknown_identity_blocks_native_actions(self):
        self.ready(); self.queue.session_data['pending'] = 1
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_foreign_native_running_blocks_native_actions(self):
        self.ready(); self.queue.current['action']['status'] = 'running'
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_automatic_combat_blocks_native_takeover(self):
        self.ready(); self.queue.session_data['combat']['active'] = True
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_external_escape_only_records_never_unlocks_or_proves(self):
        self.register()
        with self.assertRaises(SafetyHalt): self.record(response=receipt(self.b, status='uncertain'))
        before = list(self.queue.calls)
        result = self.s.record_external_escape({'operator_executed': True, 'method': 'cua_escape',
            'evidence_ref': 'operator-screenshot', 'authorization_ref': 'rescue-authorization'})
        self.assertEqual(self.queue.calls, before)
        for key in ('native_release_proven', 'native_outcome_proven', 'controlled_trial_accepted', 'ordinary_mutation_permission'):
            self.assertFalse(result[key])
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        self.assertTrue((self.case() / 'SAFETY-STOP.json').exists())
    def test_cross_output_does_not_reset_trial_budget(self):
        self.ready(); second_o = types.SimpleNamespace(**{**vars(self.o), 'out': self.base / 'different-output'})
        second = PostTrialSafety(second_o, self.s.root)
        with self.assertRaises(SafetyHalt): second.assert_mutation_allowed(request_id='new', body={'op': 'combat_start'})
        with self.assertRaises(SafetyHalt): second.register_noai_case('next', self.es, sample(self.b), evidence_ref='new', noai_proof=self.proof, authorization_ref='new')
        self.assertEqual(self.queue.mutations(), [])
    def test_cleanup_itself_never_grants_new_mutation(self):
        self.ready()
        for e in self.es: self.s.cleanup_uuid(e['uuid'], 'cleanup-authorization')
        self.s.pause_once('pause-authorization')
        with self.assertRaises(SafetyHalt): self.s.assert_mutation_allowed(request_id='new', body={'op': 'action'})
    def test_running_cancel_requires_bound_running_and_is_single_exact_owner(self):
        self.register(); self.reserve()
        running = copy.deepcopy(self.native); running['status'] = 'running'; running['reason'] = 'running'
        enc = running['result']['combat']['encounter']; enc['outcome_scope'] = None
        self.queue.current = sample(self.b, running)
        self.queue.session_data.update(state='busy', active_request_id=self.b.request_id, active_action_id=self.b.expected_action_id)
        rid = self.s.authorize_running_cancel(self.queue.current, reason='outer_health_drop', authorization_ref='user-noai-authorization')
        self.s.assert_mutation_allowed(request_id=rid, body={'op': 'cancel'}, owned_request=self.b.request_id)
        for body, owner in [({'op': 'direct', 'endpoint': 'look'}, self.b.request_id), ({'op': 'cancel'}, 'foreign')]:
            with self.assertRaises(SafetyHalt): self.s.claim_trial_dispatch(rid, body, owned_request=owner)
        self.s.claim_trial_dispatch(rid, {'op': 'cancel'}, owned_request=self.b.request_id)
        with self.assertRaises(SafetyHalt): self.s.claim_trial_dispatch(rid, {'op': 'cancel'}, owned_request=self.b.request_id)
        self.assertEqual(self.queue.mutations(), [])
    def test_running_cancel_denied_after_unknown_main_receipt(self):
        self.register(); self.reserve()
        running = copy.deepcopy(self.native); running['status'] = 'running'; running['result']['combat']['encounter']['outcome_scope'] = None
        self.queue.current = sample(self.b, running); self.queue.main_result = {'status': 'uncertain'}
        with self.assertRaisesRegex(SafetyHalt, 'main_receipt_already_present'):
            self.s.authorize_running_cancel(self.queue.current, reason='health_missing', authorization_ref='user-noai-authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_ledger_context_change_is_not_new_trial_permission(self):
        self.ready(); self.o.world = '00000000-0000-4000-8000-000000000999'
        second = PostTrialSafety(self.o, self.s.root)
        with self.assertRaisesRegex(SafetyHalt, 'context_changed|sibling_anchor_identity'): second.assert_mutation_allowed()

    def test_noai_registration_requires_full_caller_and_fresh_health(self):
        obs = sample(self.b); obs['state']['player']['health'] = 19.99
        with self.assertRaisesRegex(SafetyHalt, 'full_health_20'): self.register(observation=obs)
        self.queue.current['state']['player']['health'] = 19.99
        with self.assertRaisesRegex(SafetyHalt, 'full_health_20'): self.register()
        self.assertEqual(self.queue.mutations(), [])
    def test_cleanup_health_drop_is_separate_stopped_safety_not_acceptance(self):
        self.ready(); self.queue.current['state']['player']['health'] = 19.99
        result = self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertTrue(result['effect_confirmed']); self.assertFalse(result['controlled_trial_accepted'])
        self.assertTrue((self.case() / 'POST-HEALTH-STOPPED-SAFETY.json').is_file())
        original = json.loads((self.o.out / 'one.json').read_text())
        self.assertEqual(original['after']['state']['player']['health'], 20)
    def test_four_mutable_authority_records_tamper_is_fail_closed(self):
        self.ready()
        targets = [('registration.json', lambda x: x.update(authorization_ref='replacement')),
            ('trial-reservation.json', lambda x: x['command'].update(timeout_ms=9999)),
            ('trial-resolution.json', lambda x: x.update(release_observed=False)),
            ('trial-dispatch.json', lambda x: x.update(request_id='replacement'))]
        for filename, change in targets:
            path = self.case() / filename; original = path.read_bytes(); data = json.loads(original); change(data)
            path.write_text(json.dumps(data))
            with self.subTest(filename=filename), self.assertRaises(SafetyHalt):
                self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
            self.assertEqual(self.queue.mutations(), [])
            path.write_bytes(original)  # Test-only restoration; implementation never rewrites evidence.
    def test_rehashed_registration_still_cannot_kill_third_uuid(self):
        self.ready(); path = self.case() / 'registration.json'; data = json.loads(path.read_text())
        data['entities'][0]['uuid'] = '00000000-0000-4000-8000-000000000099'
        path.write_text(json.dumps(data)); Path(str(path) + '.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
        self.queue.current['state']['nearby']['entities'][0]['uuid'] = data['entities'][0]['uuid']
        with self.assertRaisesRegex(SafetyHalt, 'authority_chain|registration_anchor'):
            self.s.cleanup_uuid(data['entities'][0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_rehashed_resolution_does_not_override_recomputed_outcome(self):
        self.ready(); path = self.case() / 'trial-resolution.json'; data = json.loads(path.read_text())
        data['resolved_outcome']['kind'] = 'admission_rejected'
        path.write_text(json.dumps(data)); Path(str(path) + '.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(SafetyHalt, 'main_trial_not_safe'):
            self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])
    def test_exact_dead_observation_is_effect_without_disappearance(self):
        self.ready(); self.queue.remove_target = False
        self.queue.after_hook = lambda obs: obs['state']['nearby']['entities'][0].update(alive=False, health=0)
        result = self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(result['effect'], 'exact_uuid_dead_observed')
    def test_exact_health_zero_is_effect_without_disappearance(self):
        self.ready(); self.queue.remove_target = False
        self.queue.after_hook = lambda obs: obs['state']['nearby']['entities'][0].update(health=0)
        result = self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(result['effect'], 'exact_uuid_dead_observed')
    def closed_with_new_entities(self):
        self.ready()
        for e in self.es: self.s.cleanup_uuid(e['uuid'], 'cleanup-authorization')
        self.s.pause_once('pause-authorization')
        new = [dict(e, entity_id=e['entity_id'] + 10, uuid='00000000-0000-4000-8000-%012d' % (e['entity_id'] + 10)) for e in self.es]
        values = [dict(e, alive=True, health=20) for e in new]
        self.queue.current['state']['nearby'].update(entities=values, total=2, returned=2)
        second_o = types.SimpleNamespace(**{**vars(self.o), 'out': self.base / 'second-output'})
        second = PostTrialSafety(second_o, self.s.root)
        kwargs = dict(case_id='independent-two', entities=new, observation=copy.deepcopy(self.queue.current),
            evidence_ref='new-registration-evidence', noai_proof={'entities': [{'uuid': e['uuid'], 'no_ai': True,
                'evidence_ref': 'new-noai-proof'} for e in new]}, authorization_ref='new-explicit-case-authorization',
            previous_case_authorization_ref='new-explicit-case-authorization')
        return second, kwargs
    def test_known_handoff_new_explicit_authorization_allows_independent_noai_case(self):
        second, kwargs = self.closed_with_new_entities()
        result = second.register_noai_case(**kwargs)
        self.assertEqual(result['case_id'], 'independent-two')
        self.assertFalse(result['ordinary_mutation_permission'])
        self.assertTrue((self.s.root / 'case-000002' / 'registration.json').is_file())
        self.assertTrue((self.case() / 'trial-reservation.json').is_file())
        with self.assertRaises(SafetyHalt): second.assert_mutation_allowed(body={'op': 'combat_start'}, request_id='new')
    def test_next_case_cannot_reuse_old_authorization(self):
        second, kwargs = self.closed_with_new_entities()
        kwargs['previous_case_authorization_ref'] = 'user-noai-authorization'
        with self.assertRaisesRegex(SafetyHalt, 'new_explicit_authorization'): second.register_noai_case(**kwargs)
        self.assertFalse((self.s.root / 'case-000002').exists())
    def test_next_case_historical_pause_is_not_fresh_pause(self):
        second, kwargs = self.closed_with_new_entities()
        self.queue.current['state'].update(paused=False, screen_open=False)
        self.queue.current['screen'] = {'open': False}
        kwargs['observation'] = copy.deepcopy(self.queue.current)
        with self.assertRaisesRegex(SafetyHalt, 'fresh_previous_pause'): second.register_noai_case(**kwargs)
    def test_next_case_requires_full_health_even_after_handoff(self):
        second, kwargs = self.closed_with_new_entities(); kwargs['observation']['state']['player']['health'] = 19
        with self.assertRaisesRegex(SafetyHalt, 'full_health_20'): second.register_noai_case(**kwargs)
    def test_unregistered_guard_checks_remain_read_only(self):
        self.s.assert_mutation_allowed(body={'op': 'direct'}, request_id='unrelated-pretrial')
        self.assertFalse(self.s.root.exists()); self.assertEqual(self.queue.calls, [])

    def test_cancel_dispatch_rechecks_main_terminal_after_authorization(self):
        self.register(); self.reserve()
        running = copy.deepcopy(self.native); running['status'] = 'running'; running['result']['combat']['encounter']['outcome_scope'] = None
        self.queue.current = sample(self.b, running)
        self.queue.session_data.update(state='busy', active_request_id=self.b.request_id, active_action_id=self.b.expected_action_id)
        rid = self.s.authorize_running_cancel(self.queue.current, reason='health_drop', authorization_ref='authorization')
        self.queue.main_result = receipt(self.b, self.native); self.queue.current = sample(self.b, self.native)
        before = len([c for c in self.queue.calls if c[0] == 'submit'])
        with self.assertRaisesRegex(SafetyHalt, 'main_receipt_already_present'):
            self.s.claim_trial_dispatch(rid, {'op': 'cancel'}, owned_request=self.b.request_id)
        self.assertEqual(self.queue.mutations(), [])
        self.assertTrue((self.case() / 'running-cancel-rejected.json').is_file())
        self.assertEqual(before, len([c for c in self.queue.calls if c[0] == 'submit']))
    def test_cancel_dispatch_rechecks_active_native_owner_without_extra_observe(self):
        self.register(); self.reserve()
        running = copy.deepcopy(self.native); running['status'] = 'running'; running['result']['combat']['encounter']['outcome_scope'] = None
        self.queue.current = sample(self.b, running)
        self.queue.session_data.update(state='busy', active_request_id=self.b.request_id, active_action_id=self.b.expected_action_id)
        rid = self.s.authorize_running_cancel(self.queue.current, reason='health_drop', authorization_ref='authorization')
        self.queue.current = sample(self.b, self.native)
        self.queue.session_data.update(state='ready', active_request_id=None, active_action_id=None)
        with self.assertRaisesRegex(SafetyHalt, 'bound_owner_unavailable'):
            self.s.claim_trial_dispatch(rid, {'op': 'cancel'}, owned_request=self.b.request_id)
        self.assertEqual(self.queue.mutations(), [])

    def assert_budget_stays_locked(self, helper=None):
        safety = helper or self.s
        with self.assertRaises(SafetyHalt): safety.assert_mutation_allowed(request_id='new-direct', body={'op': 'direct'})
        with self.assertRaises(SafetyHalt): safety.claim_trial_dispatch('new-direct', {'op': 'direct'})
        with self.assertRaises(SafetyHalt): self.register(case_id='replacement-case')
        self.assertEqual(self.queue.mutations(), [])
    def test_renamed_unresolved_case_never_resets_budget(self):
        self.register(); self.reserve()
        self.case().rename(self.case().with_name('case-000001-interrupted'))
        self.assert_budget_stays_locked()
    def test_deleted_unresolved_case_never_resets_budget(self):
        self.register(); self.reserve(); shutil.rmtree(self.case())
        self.assert_budget_stays_locked()
    def test_deleted_case_and_root_index_still_used_marker_blocks(self):
        self.register(); self.reserve(); shutil.rmtree(self.case())
        for path in self.s.root.glob('ledger-case-*'): path.unlink()
        self.assert_budget_stays_locked()
    def test_missing_case_anchor_is_not_recreated(self):
        self.register(); self.reserve(); (self.s.root / 'ledger-case-000001.anchor.json').unlink()
        self.assert_budget_stays_locked()
    def test_renamed_case_anchor_is_not_ignored(self):
        self.register(); self.reserve()
        anchor = self.s.root / 'ledger-case-000001.anchor.json'; anchor.rename(anchor.with_name('ledger-case-broken.anchor.json'))
        self.assert_budget_stays_locked()
    def test_symlink_case_cannot_reuse_original_records(self):
        self.ready(); moved = self.base / 'moved-case'; self.case().rename(moved); self.case().symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(SafetyHalt, 'case_name_or_type'): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assert_budget_stays_locked()
    def test_unexpected_extra_case_directory_blocks(self):
        self.register(); self.reserve(); (self.s.root / 'case-000003').mkdir()
        self.assert_budget_stays_locked()
    def test_root_anchor_is_committed_before_case_directory(self):
        import post_trial_safety as module
        original = module._write
        def write(path, value):
            if Path(path).name == 'registration.json':
                self.assertTrue((self.s.root / 'ledger-case-000001.anchor.json').is_file())
                self.assertTrue((self.s.root / 'CASE-LEDGER-USED.json').is_file())
                self.assertTrue(self.s.ever_used.is_file())
                raise OSError('synthetic crash before registration record')
            return original(path, value)
        with patch.object(module, '_write', side_effect=write):
            with self.assertRaises(OSError): self.register()
        self.assert_budget_stays_locked()
    def test_whole_ledger_deletion_keeps_sibling_budget_anchor(self):
        self.register(); self.reserve(); shutil.rmtree(self.s.root)
        self.assertTrue(self.s.ever_used.is_file())
        self.assert_budget_stays_locked(PostTrialSafety(self.o, self.s.root))
        self.assertFalse(self.s.root.exists())
    def test_whole_ledger_rename_keeps_sibling_budget_anchor(self):
        self.register(); self.reserve(); self.s.root.rename(self.base / 'renamed-ledger')
        self.assert_budget_stays_locked(PostTrialSafety(self.o, self.s.root))
    def test_deleted_sibling_anchor_does_not_erase_root_commitment(self):
        self.register(); self.reserve(); self.s.ever_used.unlink(); Path(str(self.s.ever_used) + '.sha256').unlink()
        self.assert_budget_stays_locked()

    def test_root_symlink_to_fresh_empty_ledger_cannot_reset_budget(self):
        self.register(); self.reserve()
        original = self.s.root; original.rename(self.base / 'old-ledger')
        empty = self.base / 'fresh-empty'; empty.mkdir(); original.symlink_to(empty, target_is_directory=True)
        replacement = PostTrialSafety(self.o, original)
        self.assertEqual(replacement.root, original)
        self.assert_budget_stays_locked(replacement)
        self.assertEqual(list(empty.iterdir()), [])
    def test_ancestor_symlink_to_empty_parent_cannot_reset_budget(self):
        self.register(); self.reserve()
        empty = self.base / 'empty-parent'; empty.mkdir()
        alias = self.base / 'aliased-parent'; alias.symlink_to(empty, target_is_directory=True)
        replacement = PostTrialSafety(self.o, alias / 'shared-ledger')
        with self.assertRaisesRegex(SafetyHalt, 'root_alias_or_symlink'):
            replacement.assert_mutation_allowed(request_id='new-direct', body={'op': 'direct'})
        with self.assertRaisesRegex(SafetyHalt, 'root_alias_or_symlink'):
            replacement.claim_trial_dispatch('new-direct', {'op': 'direct'})
        self.assertEqual(list(empty.iterdir()), [])
        self.assertEqual(self.queue.mutations(), [])

    def test_corrupt_previous_cleanup_effect_blocks_second_uuid_and_pause(self):
        self.ready(); self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        effect = self.case() / ('cleanup-' + self.es[0]['uuid'] + '.effect.json')
        effect.write_text('{broken')
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[1]['uuid'], 'authorization')
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        self.assertEqual(len(self.queue.mutations()), 1)
        self.assertEqual(effect.read_text(), '{broken')
    def test_corrupt_previous_cleanup_receipt_blocks_second_uuid_and_pause(self):
        self.ready(); self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        receipt_path = self.case() / ('cleanup-' + self.es[0]['uuid'] + '.receipt.json')
        receipt_path.write_text('{broken')
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[1]['uuid'], 'authorization')
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        self.assertEqual(len(self.queue.mutations()), 1)
        self.assertEqual(receipt_path.read_text(), '{broken')
    def test_missing_previous_effect_digest_blocks_next_narrow_action(self):
        self.ready(); self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        (self.case() / ('cleanup-' + self.es[0]['uuid'] + '.effect.json.sha256')).unlink()
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[1]['uuid'], 'authorization')
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        self.assertEqual(len(self.queue.mutations()), 1)
    def test_rehashed_previous_receipt_breaks_effect_chain_before_next_action(self):
        self.ready(); self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        path = self.case() / ('cleanup-' + self.es[0]['uuid'] + '.receipt.json')
        payload = json.loads(path.read_text()); payload['result']['submitted'] = False
        path.write_text(json.dumps(payload)); Path(str(path) + '.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[1]['uuid'], 'authorization')
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        self.assertEqual(len(self.queue.mutations()), 1)
    def test_corrupt_noop_pause_effect_blocks_cleanup(self):
        self.ready(); self.queue.current['state'].update(paused=True, screen_open=True)
        self.queue.current['screen'] = {'open': True, 'class': PAUSE_SCREEN}
        self.s.pause_once('authorization'); effect = self.case() / 'pause.effect.json'
        effect.write_text('{broken')
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(self.queue.mutations(), [])

    def test_previous_effect_with_deleted_intent_blocks_all_next_mutations(self):
        self.ready(); self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        (self.case() / ('cleanup-' + self.es[0]['uuid'] + '.intent.json')).unlink()
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[1]['uuid'], 'authorization')
        with self.assertRaises(SafetyHalt): self.s.pause_once('authorization')
        with self.assertRaises(SafetyHalt): self.s.cleanup_uuid(self.es[0]['uuid'], 'authorization')
        self.assertEqual(len(self.queue.mutations()), 1)


if __name__ == '__main__':
    unittest.main()
