"""Synthetic existing-queue observations only; never connect to a game."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import boat_entry_guard as module
from boat_entry_guard import BoatEntryGuard, validate_store
from post_trial_safety import PAUSE_SCREEN, SafetyHalt, _write

B = {'resident_session': '00000000000000000000000000000001',  # Actual Resident uses uuid4().hex.
     'action_session': '00000000-0000-0000-0000-000000000002',
     'world_generation': '00000000-0000-0000-0000-000000000003',
     'player_uuid': '00000000-0000-0000-0000-000000000004'}


def observation():
    action = {'action_session': B['action_session'], 'action_id': None, 'status': 'idle', 'input_owner': 'direct'}
    automation = {'aim_lock': {'active': False}, 'combat': {'active': False, 'held_mappings': []}}
    return {**deepcopy(automation), 'action': deepcopy(action),
        'state': {'world': {'world_generation': B['world_generation']}, 'client_action': deepcopy(action),
            'paused': True, 'screen_open': True,
            'player': {'uuid': B['player_uuid'], 'alive': True, 'on_ground': True,
                'health': 20, 'air': 300, 'max_air': 300, 'eye_position': {'y': 65.62},
                'vehicle': {'riding': False}, 'using_item': False, 'sprinting': False}},
        'status': {'world': {'world_generation': B['world_generation']}, 'player': {'uuid': B['player_uuid']},
            'client_action': deepcopy(action), 'held_mappings': [],
            'mouse': {'held_world_buttons': [], 'left_pressed': False, 'right_pressed': False, 'middle_pressed': False},
            'input_isolation': {'held_keys': 0}, 'guarded_turn': {'held_input': False},
            'guarded_movement': {'held_keys': False, 'released': True, 'owner_request_id': None, 'owner_action': None}},
        'screen': {'open': True, 'class': PAUSE_SCREEN}}


class Queue:
    def __init__(self, root):
        self.root, self.events = Path(root), []
        self.current = observation()
        self.state = {'session_id': B['resident_session'], 'state': 'ready', 'reason': None, 'active_request_id': None,
            'active_action_id': None, 'pending': 0, 'pending_request_ids': [],
            'bridge_identity': {'action_session': B['action_session']},
            'aim_lock': {'active': False}, 'combat': {'active': False, 'held_mappings': []}}
        self.requests = {}
        self.observe_error = self.pause_error = self.stale_observe = self.stale_pause = False
        self.pause_effect = True
        self.mutate_pause = lambda value: None

    def session(self):
        return deepcopy(self.state)

    def submit(self, command, request_id):
        self.events.append(command['op'])
        self.requests[request_id] = deepcopy(command)
        if command['op'] == 'encounter_pause':
            self.state.update(state='paused', reason='encounter_pause_requested')
            assert command['expected_resident_session'] == B['resident_session']
            own = [p for p in (self.root / 'boat-entry-guard').glob('*.reservation.json')
                   if json.loads(p.read_text())['pause_request_id'] == request_id]
            assert len(own) == 1 and not own[0].with_name(own[0].name.replace('.reservation.json', '.result.json')).exists()
            assert list((self.root / 'boat-entry-guard').glob('*.reservation.json.sha256'))
            if self.pause_effect:
                self.current['state'].update(paused=True, screen_open=True)
                self.current['screen'] = {'open': True, 'class': PAUSE_SCREEN}
            if self.pause_error:
                self.state['reason'] = 'encounter_pause_unknown'
                raise OSError('synthetic pause outcome unknown')
        elif command['op'] == 'observe':
            if self.observe_error:
                self.observe_error = False
                raise OSError('synthetic fresh read failure')
        else:
            raise AssertionError('Guard must never submit ' + command['op'])
        return request_id

    def wait(self, rid, timeout):
        command = self.requests[rid]
        value = {'request_id': rid, 'session_id': B['resident_session'], 'status': 'succeeded', 'finished_at': 100.0}
        if command['op'] == 'observe':
            value['result'] = deepcopy(self.current)
            if self.stale_observe:
                value['finished_at'] = 99.0
                self.stale_observe = False
        else:
            body = command['body']
            value['result'] = {'ok': True, 'protocol': 'mineclient-bridge', 'schema_version': 2,
                'pause_schema_version': 1, 'action': 'ensure_paused', 'pause_requested': True,
                'pause_screen_installed': True, 'pause_effect_confirmed': False, 'server_confirmed': False,
                'already_pause_screen': False, 'client_paused_observed': False,
                'action_session': B['action_session'], 'world_generation': B['world_generation'],
                'player_uuid': B['player_uuid'], 'expected_action_id': body['expected_action_id'],
                'expected_action_present': False, 'client_action': None, 'input_release_confirmed': None}
            if self.stale_pause: value['finished_at'] = 99.0
            self.mutate_pause(value)
        return value

    def resume_externally(self):
        self.current['state'].update(paused=False, screen_open=False)
        self.current['screen'] = {'open': False}


class BoatEntryGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.q = Queue(self.tmp.name)
        def tracked_write(path, value):
            self.q.events.append('report' if str(path).endswith('.result.json') else 'reservation')
            _write(path, value)
        self.writer = patch.object(module, '_write', tracked_write)
        self.writer.start(); self.addCleanup(self.writer.stop)

    def prepare(self, case_id='one-entry'):
        return BoatEntryGuard(self.q, case_id, B, surface_y=63,
            support_evidence_ref='synthetic-reviewed-solid-dock', pause_authorization_ref='synthetic-explicit-pause',
            clock=lambda: 1.0, wall_clock=lambda: 100.0)

    def run_guard(self, guard, assertions=lambda value: None):
        return guard.check(assertions, main_action_submitted=False)

    def fail_entry(self):
        self.q.current['state']['player']['eye_position']['y'] = 62.9
        self.q.current['state']['player']['air'] = 297

    def test_eye_below_water_pauses_in_same_call_before_report(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry()
        value = self.run_guard(guard)
        self.assertEqual(self.q.events, ['observe', 'reservation', 'observe', 'encounter_pause', 'observe', 'report'])
        self.assertFalse(value['entry_ready']); self.assertTrue(value['pause_acknowledged'])
        self.assertTrue(value['pause_observed']); self.assertTrue(value['neutral_inputs_observed'])
        proof = value['pause_receipt']['result']
        self.assertFalse(proof['expected_action_present'])
        self.assertIsNone(proof['client_action']); self.assertIsNone(proof['input_release_confirmed'])
        self.assertFalse(value['main_action_accepted'])

    def test_read_only_custom_assertion_failure_is_inside_the_guard(self):
        guard = self.prepare(); self.q.resume_externally()
        def assertion(value): raise AssertionError('exact boat or empty hand check failed')
        result = self.run_guard(guard, assertion)
        self.assertTrue(result['pause_attempted']); self.assertIn('exact boat', result['stop_reason'])
        self.assertLess(self.q.events.index('encounter_pause'), self.q.events.index('report'))

    def test_safe_entry_returns_without_submitting_or_claiming_any_boat_action(self):
        guard = self.prepare(); self.q.resume_externally()
        result = self.run_guard(guard)
        self.assertTrue(result['entry_ready']); self.assertFalse(result['pause_attempted'])
        self.assertFalse(result['main_action_submitted']); self.assertFalse(result['main_action_accepted'])
        self.assertEqual(self.q.events, ['observe', 'reservation', 'observe', 'report'])

    def test_same_object_and_durable_case_cannot_be_reused(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); self.run_guard(guard)
        prior = list(self.q.events)
        with self.assertRaises(SafetyHalt): self.run_guard(guard)
        with self.assertRaises(SafetyHalt): self.prepare()
        self.assertEqual(prior, self.q.events)

    def test_unknown_cannot_get_new_budget_by_case_rename_or_ready_restart(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); self.q.pause_error = True
        self.run_guard(guard)
        self.q.state.update(state='ready', reason=None)
        self.q.current = observation()
        prior = list(self.q.events)
        with self.assertRaises(SafetyHalt): self.prepare('new-entry')
        self.assertEqual(prior, self.q.events)

    def test_known_closed_guard_allows_new_distinct_case_but_not_same_id(self):
        guard = self.prepare(); self.q.resume_externally(); self.run_guard(guard)
        self.q.current = observation()
        self.prepare('new-entry')
        with self.assertRaises(SafetyHalt): self.prepare('one-entry')

    def test_existing_empty_or_orphan_store_never_resets_budget(self):
        folder = self.q.root / 'boat-entry-guard'; folder.mkdir()
        with self.assertRaises(SafetyHalt): self.prepare('new-entry')
        (folder / 'lost.reservation.json.sha256').write_text('incomplete')
        with self.assertRaises(SafetyHalt): self.prepare('new-entry')
        self.assertEqual(self.q.events, [])

    def test_unknown_pause_is_consumed_and_never_retried_despite_observed_screen(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); self.q.pause_error = True
        value = self.run_guard(guard)
        self.assertEqual(self.q.events.count('encounter_pause'), 1)
        self.assertFalse(value['pause_acknowledged']); self.assertTrue(value['pause_observed'])
        self.assertIn('unknown', value['pause_error'])
        with self.assertRaises(SafetyHalt): self.run_guard(guard)
        self.assertEqual(self.q.events.count('encounter_pause'), 1)

    def test_fresh_read_failure_pauses_before_report(self):
        guard = self.prepare(); self.q.resume_externally(); self.q.observe_error = True
        result = self.run_guard(guard)
        self.assertTrue(result['pause_attempted']); self.assertTrue(result['pause_observed'])
        self.assertLess(self.q.events.index('encounter_pause'), self.q.events.index('report'))

    def test_stale_fresh_read_is_not_used_to_pass_entry(self):
        guard = self.prepare(); self.q.resume_externally(); self.q.stale_observe = True
        result = self.run_guard(guard)
        self.assertFalse(result['entry_ready']); self.assertTrue(result['pause_attempted'])

    def test_stale_same_id_pause_receipt_is_not_acknowledgement(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); self.q.stale_pause = True
        result = self.run_guard(guard)
        self.assertFalse(result['pause_acknowledged']); self.assertEqual(self.q.events.count('encounter_pause'), 1)

    def test_old_pause_queue_result_blocks_before_submission(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry()
        path = self.q.root / 'results' / (guard.pause_id + '.json'); path.parent.mkdir(); path.write_text('{}')
        result = self.run_guard(guard)
        self.assertFalse(result['pause_attempted']); self.assertIn('preexists', result['pause_error'])
        self.assertNotIn('encounter_pause', self.q.events)

    def test_prior_same_case_queue_id_refuses_reservation(self):
        import uuid
        rid = uuid.uuid5(uuid.UUID(B['resident_session']), 'one-entry:entry-pause').hex
        path = self.q.root / 'inbox' / (rid + '.json'); path.parent.mkdir(); path.write_text('{}')
        with self.assertRaises(SafetyHalt): self.prepare()
        self.assertEqual(self.q.events, [])

    def test_baseline_must_be_native_paused_on_supported_full_air_ground(self):
        for field, value in [('on_ground', False), ('health', 19), ('air', 297), ('alive', False)]:
            with self.subTest(field=field):
                self.q.current = observation(); self.q.current['state']['player'][field] = value
                with self.assertRaises(SafetyHalt): self.prepare()
        self.assertNotIn('reservation', self.q.events); self.assertNotIn('encounter_pause', self.q.events)

    def test_pause_title_or_open_alone_does_not_allow_reservation(self):
        self.q.current['screen']['class'] = 'other.Screen'
        with self.assertRaises(SafetyHalt): self.prepare()
        self.assertNotIn('reservation', self.q.events)

    def test_missing_or_held_baseline_input_refuses(self):
        for key in ('held_mappings', 'input_isolation', 'guarded_movement', 'guarded_turn', 'mouse'):
            with self.subTest(key=key):
                self.q.current = observation(); del self.q.current['status'][key]
                with self.assertRaises(SafetyHalt): self.prepare()
        self.assertNotIn('reservation', self.q.events)

    def test_new_held_input_pauses_but_never_claims_release(self):
        guard = self.prepare(); self.q.resume_externally()
        self.q.current['status']['held_mappings'] = ['key.forward']
        result = self.run_guard(guard)
        self.assertTrue(result['pause_attempted']); self.assertFalse(result['neutral_inputs_observed'])
        self.assertTrue(result['pause_observed'])
        self.assertIsNone(result['pause_receipt']['result']['input_release_confirmed'])

    def test_foreign_resident_owner_or_identity_never_receives_pause(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry()
        self.q.state['active_request_id'] = 'foreign-owner'
        result = self.run_guard(guard)
        self.assertFalse(result['pause_attempted']); self.assertNotIn('encounter_pause', self.q.events)

    def test_existing_resident_unknown_stop_cannot_prepare_a_new_entry(self):
        self.q.state.update(state='paused', reason='uncertain_request_observe_then_resume')
        with self.assertRaises(SafetyHalt): self.prepare()
        self.assertEqual(self.q.events, [])

    def test_new_resident_unknown_stop_cannot_become_a_safe_entry_or_pause_retry(self):
        guard = self.prepare(); self.q.resume_externally()
        self.q.state.update(state='paused', reason='uncertain_request_observe_then_resume')
        result = self.run_guard(guard)
        self.assertFalse(result['entry_ready']); self.assertFalse(result['pause_attempted'])
        self.assertNotIn('encounter_pause', self.q.events)

    def test_ready_descriptor_requires_explicit_null_reason(self):
        del self.q.state['reason']
        with self.assertRaises(SafetyHalt): self.prepare()
        self.q.state['reason'] = 'unreconciled-stop'
        with self.assertRaises(SafetyHalt): self.prepare()
        self.assertEqual(self.q.events, [])

    def test_prior_encounter_pause_stop_cannot_be_borrowed_before_own_attempt(self):
        self.q.state.update(state='paused', reason='encounter_pause_unknown')
        with self.assertRaises(SafetyHalt): self.prepare()
        self.assertEqual(self.q.events, [])

    def test_changed_world_or_native_owner_never_receives_pause(self):
        for branch in ('world', 'native'):
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as temp:
                self.q = Queue(temp); guard = self.prepare(); self.q.resume_externally()
                if branch == 'world': self.q.current['state']['world']['world_generation'] = B['player_uuid']
                else: self.q.current['action'].update(status='running', action_id='foreign')
                result = self.run_guard(guard)
                self.assertFalse(result['pause_attempted']); self.assertNotIn('encounter_pause', self.q.events)

    def test_foreign_guarded_owner_never_receives_pause(self):
        guard = self.prepare(); self.q.resume_externally()
        self.q.current['status']['guarded_movement']['owner_request_id'] = 'foreign'
        self.assertFalse(self.run_guard(guard)['pause_attempted'])
        self.assertNotIn('encounter_pause', self.q.events)

    def test_existing_main_submission_is_outside_helper_scope(self):
        guard = self.prepare(); self.q.resume_externally()
        with self.assertRaises(SafetyHalt): guard.check(lambda value: None, main_action_submitted=True)
        self.assertNotIn('encounter_pause', self.q.events)

    def test_fabricated_release_or_present_action_cannot_supply_missing_action_proof(self):
        for field, value in [('input_release_confirmed', True), ('client_action', {}), ('expected_action_present', True)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                self.q = Queue(temp); guard = self.prepare(); self.q.resume_externally(); self.fail_entry()
                self.q.mutate_pause = lambda receipt: receipt['result'].update({field: value})
                result = self.run_guard(guard)
                self.assertFalse(result['pause_acknowledged']); self.assertEqual(self.q.events.count('encounter_pause'), 1)

    def test_acknowledgement_alone_does_not_prove_pause_effect(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); self.q.pause_effect = False
        result = self.run_guard(guard)
        self.assertTrue(result['pause_acknowledged']); self.assertFalse(result['pause_observed'])
        self.assertEqual(self.q.events.count('encounter_pause'), 1)

    def test_corrupted_reservation_cannot_reauthorize_pause(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); guard.path.write_text('{}')
        result = self.run_guard(guard)
        self.assertFalse(result['pause_attempted']); self.assertNotIn('encounter_pause', self.q.events)

    def test_report_write_failure_occurs_only_after_pause_and_cannot_retry(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry()
        with patch.object(module, '_write', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): self.run_guard(guard)
        self.assertEqual(self.q.events.count('encounter_pause'), 1)
        with self.assertRaises(SafetyHalt): self.run_guard(guard)

    def rewrite(self, path, value):
        path.unlink(); Path(str(path) + '.sha256').unlink(); _write(path, value)

    def test_store_missing_is_unused_and_reservation_only_blocks(self):
        self.assertEqual(validate_store(self.q.root)['files'], {})
        self.prepare()
        with self.assertRaises(SafetyHalt): validate_store(self.q.root)

    def test_closed_entry_store_returns_exact_pins_without_main_completion(self):
        guard = self.prepare(); self.q.resume_externally(); self.run_guard(guard)
        summary = validate_store(self.q.root)
        self.assertEqual(len(summary['files']), 4)
        self.assertEqual(summary['entries'][0]['outcome'], 'entry_ready')
        self.assertFalse(summary['main_action_evaluated'])
        self.assertIn('one-entry', summary['consumed_request_ids'])
        self.assertIn(guard.pause_id, summary['consumed_request_ids'])
        self.assertEqual(len(B['resident_session']), 32)
        self.assertEqual(summary['entries'][0]['binding']['resident_session'], B['resident_session'])

    def test_closed_failure_recomputes_bound_pause_effect_and_null_semantics(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); self.run_guard(guard)
        summary = validate_store(self.q.root)
        self.assertEqual(summary['entries'][0]['outcome'], 'paused_on_entry_failure')
        self.assertIn(guard.pause_id, summary['consumed_request_ids'])

    def test_two_known_closed_guard_cases_remain_distinct_without_main_claims(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); self.run_guard(guard)
        self.q.current = observation(); self.q.state.update(state='ready', reason=None)
        second = self.prepare('second-entry'); self.q.resume_externally(); self.run_guard(second)
        summary = validate_store(self.q.root)
        self.assertEqual(len(summary['files']), 8); self.assertEqual(len(summary['entries']), 2)
        self.assertFalse(summary['main_action_evaluated'])

    def test_consumed_pause_id_cannot_be_reused_as_a_new_case_id(self):
        guard = self.prepare(); self.q.resume_externally(); self.run_guard(guard)
        self.q.current = observation()
        with self.assertRaises(SafetyHalt): self.prepare(guard.pause_id)

    def test_unknown_pause_cannot_be_closed_by_flags_or_later_screen(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); self.q.pause_error = True
        result = self.run_guard(guard)
        with self.assertRaises(SafetyHalt): validate_store(self.q.root)
        result.update(pause_acknowledged=True, pause_observed=True, neutral_inputs_observed=True)
        result.pop('pause_error', None)
        self.rewrite(guard.path.with_name('one-entry.result.json'), result)
        with self.assertRaises(SafetyHalt): validate_store(self.q.root)

    def test_wrong_body_identity_or_native_release_cannot_supply_closed_store(self):
        for mode in ('body', 'binding', 'release', 'after', 'stale'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                self.q = Queue(temp); guard = self.prepare(); self.q.resume_externally(); self.fail_entry()
                result = self.run_guard(guard)
                if mode == 'body': result['command']['body']['expected_player_uuid'] = B['world_generation']
                if mode == 'binding': result['binding']['player_uuid'] = B['world_generation']
                if mode == 'release':
                    result['pause_receipt']['result']['input_release_confirmed'] = True
                    result['requests'][2]['receipt']['result']['input_release_confirmed'] = True
                if mode == 'after':
                    result['after']['state']['paused'] = False
                    result['requests'][3]['receipt']['result']['state']['paused'] = False
                if mode == 'stale':
                    result['pause_receipt']['finished_at'] = 99.0
                    result['requests'][2]['receipt']['finished_at'] = 99.0
                self.rewrite(guard.path.with_name('one-entry.result.json'), result)
                with self.assertRaises(SafetyHalt): validate_store(self.q.root)

    def test_guard_result_never_covers_a_later_main_action(self):
        guard = self.prepare(); self.q.resume_externally(); result = self.run_guard(guard)
        result['main_action_submitted'] = True
        self.rewrite(guard.path.with_name('one-entry.result.json'), result)
        with self.assertRaises(SafetyHalt): validate_store(self.q.root)

    def test_stored_resident_unknown_cannot_be_hidden_by_entry_ready_summary(self):
        guard = self.prepare(); self.q.resume_externally(); result = self.run_guard(guard)
        result['requests'][1]['session_after'].update(state='paused', reason='uncertain_request_observe_then_resume')
        self.rewrite(guard.path.with_name('one-entry.result.json'), result)
        with self.assertRaises(SafetyHalt): validate_store(self.q.root)

    def test_pause_effect_read_cannot_predate_the_pause_even_if_each_receipt_is_fresh(self):
        guard = self.prepare(); self.q.resume_externally(); self.fail_entry(); result = self.run_guard(guard)
        pause = result['requests'][2]
        pause.update(started_monotonic=105.0, finished_monotonic=105.0, started_wall=105.0, finished_wall=105.0)
        pause['receipt']['finished_at'] = 105.0
        result['pause_receipt']['finished_at'] = 105.0
        self.rewrite(guard.path.with_name('one-entry.result.json'), result)
        with self.assertRaises(SafetyHalt): validate_store(self.q.root)

    def test_missing_sidecar_unknown_file_or_symlink_blocks_store(self):
        guard = self.prepare(); self.q.resume_externally(); self.run_guard(guard)
        alien = guard.folder / 'other.txt'; alien.write_text('not a ledger record')
        with self.assertRaises(SafetyHalt): validate_store(self.q.root)
        alien.unlink()
        Path(str(guard.path) + '.sha256').unlink()
        with self.assertRaises(SafetyHalt): validate_store(self.q.root)


if __name__ == '__main__':
    unittest.main()
