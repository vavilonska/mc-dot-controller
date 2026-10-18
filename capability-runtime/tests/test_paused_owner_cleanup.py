"""Real Runtime -> IntentClient -> Watchdog -> Resident cleanup regressions.

Only the native endpoint is synthetic. These tests never connect to Minecraft.
"""
from copy import deepcopy
import unittest
import time
from unittest.mock import patch
import test_fall_rescue_owner_chain as fall_chain
from mdc_skills.core import SkillError
from resident_controller.cleanup_proof import validate_cleanup


class PausedEndpoint(fall_chain.Endpoint):
    def __init__(self):
        super().__init__()
        self.game_paused = False
        self.pause_on_status = False
        self.state_edit = lambda s: None
    def snapshot(self):
        state = super().snapshot()
        state['paused'] = self.game_paused
        state['screen_open'] = self.game_paused is True
        state['held_inputs'].update(keys=[], raw_keys=0, world_mouse_buttons=0)
        state['external_controller'] = {'schema_version': 1, 'idle_proven': True,
            'world_generation': state['world']['world_generation'], 'player_uuid': state['player']['uuid'],
            'action_session': state['client_action']['action_session'], 'source_tick': state['world']['game_time']}
        self.state_edit(state)
        return state
    def request(self, method, path, body=None):
        if path == '/control/fall-rescue/status' and self.pause_on_status:
            self.game_paused = True
            self.fall.update(armed=False, status='disarmed', reason='explicit_pause', remaining_ms=0)
        return super().request(method, path, body)


class PausedCleanupChainTests(unittest.TestCase):
    until = fall_chain.FallOwnerChainTests.until
    submit = fall_chain.FallOwnerChainTests.submit
    finish = fall_chain.FallOwnerChainTests.finish
    tearDown = fall_chain.FallOwnerChainTests.tearDown
    def setUp(self):
        with patch.object(fall_chain, 'Endpoint', PausedEndpoint):
            fall_chain.FallOwnerChainTests.setUp(self)
    def records(self, kind):
        return [r for r in self.runtime._journal['records'].values() if r['kind'] == kind]
    def run_paused(self, edit=None):
        self.bridge.pause_on_status = True
        if edit is not None:
            self.bridge.state_edit = lambda s: edit(s) if self.bridge.game_paused else None
        return self.finish(self.submit(duration_ms=4000))
    def assert_no_extra_gameplay(self):
        self.assertFalse([path for path, _ in self.bridge.posts
                          if path in ('/control/action','/control/action/cancel','/control/release-all')], self.bridge.posts)
        self.assertEqual([op for op, _ in self.bridge.fall_calls].count('arm'), 1)
        self.assertEqual([op for op, _ in self.bridge.fall_calls].count('disarm'), 1)
        self.assertNotIn('renew', [op for op, _ in self.bridge.fall_calls])
    def test_real_pause_finishes_old_owner_and_blocks_all_new_gameplay(self):
        result = self.run_paused()
        self.assertEqual(result['state'], 'interrupted', result)
        self.assertEqual(result['cleanup_certainty'], 'confirmed', result)
        self.assertEqual(result['effect_certainty'], 'none_proven', result)
        self.assertEqual(len(self.records('cleanup_observation')), 1)
        self.assertEqual(len(self.records('capability_release')), 1)
        self.assertTrue(self.bridge.game_paused)
        self.until(lambda: self.client.session()['state'] == 'paused')
        session = self.client.session()
        self.assertIsNone(session['capability_lease'])
        self.assertTrue(session['handoff_latched'])
        self.assertEqual(session['reason'], 'capability_owner_released_while_game_paused')
        self.assertIn('error', self.submit('must-stay-paused'))
        self.assert_no_extra_gameplay()
    def test_active_cleanup_remains_normal_and_new_job_can_run(self):
        first = self.finish(self.submit('normal-one'))
        self.assertEqual(first['state'], 'succeeded', first)
        self.assertEqual(first['cleanup_certainty'], 'confirmed', first)
        self.assertFalse(self.client.session()['handoff_latched'])
        second = self.finish(self.submit('normal-two'))
        self.assertEqual(second['state'], 'succeeded', second)
        self.assertEqual(len(self.records('capability_release')), 2)
    def test_unknown_pause_is_not_a_paused_cleanup_exception(self):
        result = self.run_paused(lambda s: s.update(paused=None))
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(result['cleanup_certainty'], 'unknown')
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_foreign_world_is_not_old_owner_cleanup(self):
        result = self.run_paused(lambda s: s['world'].update(world_generation='foreign-world'))
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_foreign_rescue_owner_is_not_old_owner_cleanup(self):
        result = self.run_paused(lambda s: s['native_fall_rescue_status'].update(owner_id='f'*32))
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_external_unknown_blocks_paused_release(self):
        result = self.run_paused(lambda s: s['external_controller'].update(idle_proven=False))
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_unconfirmed_neutral_input_blocks_paused_release(self):
        result = self.run_paused(lambda s: s['held_inputs'].update(raw_keys=1))
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_native_automation_blocked_prevents_release(self):
        result = self.run_paused(lambda s: s['native_fall_rescue_status'].update(automation_blocked=True))
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_delayed_release_prepare_stays_unknown_in_real_owner_chain(self):
        original = self.dog.capability_checkpoint
        prepared = []
        def delayed(lease):
            original(lease)
            if lease is not None and lease.get('cleanup_release_pending') is not None:
                prepared.append(lease['cleanup_release_pending']['intent_id'])
                time.sleep(.85)
        self.dog.capability_checkpoint = delayed
        result = self.run_paused()
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(result['cleanup_certainty'], 'unknown')
        self.assertEqual(len(prepared), 1)
        self.assertIsNotNone(self.dog.capability_lease)
        self.assertEqual(self.runtime.pending_request_id, prepared[0])
        self.runtime.close()
        self.assertEqual(len(prepared), 1)
        self.assert_no_extra_gameplay()
    def test_durable_release_failure_stays_latched_in_real_owner_chain(self):
        original = self.dog.capability_checkpoint
        failed = []
        def lost(lease):
            if lease is None and getattr(self.dog, '_cleanup_release_commit', None) is not None:
                failed.append(True)
                raise OSError('synthetic_tombstone_write_failure')
            original(lease)
        self.dog.capability_checkpoint = lost
        result = self.run_paused()
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(result['cleanup_certainty'], 'unknown')
        self.assertEqual(failed, [True])
        self.assertTrue(self.dog.handoff_latched)
        self.assertFalse(self.dog.armed)
        self.assertIsNone(self.dog.capability_lease)
        self.runtime.close()
        self.assertEqual(failed, [True])
        self.assert_no_extra_gameplay()
    def test_lost_release_ack_keeps_exact_id_and_never_retries_or_resumes(self):
        release = self.client.release_capability
        called = []
        def lost(*args, **kwargs):
            called.append(kwargs['request_id'])
            release(*args, **kwargs)
            raise OSError('synthetic_release_ack_lost')
        self.client.release_capability = lost
        result = self.run_paused()
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(result['cleanup_certainty'], 'unknown')
        rid = self.runtime.pending_request_id
        self.assertEqual(called, [rid])
        reads_before = len(self.bridge.state_paths)
        original_journal = self.runtime._path.read_bytes()
        replay = self.service.call('mdc_job', {'api_version':'mdc.toolbox/1', 'operation':'reconcile',
            'job_id':result['job_id'], 'session_ref':result['session_ref']})
        self.assertEqual(replay['state'], 'unknown', replay)
        self.assertEqual(original_journal, self.runtime._path.read_bytes())
        self.assertEqual(reads_before, len(self.bridge.state_paths))
        self.runtime.close()
        self.assertEqual(called, [rid])
        self.assertEqual(self.runtime.pending_request_id, rid)
        self.assertTrue(self.bridge.game_paused)
        self.assert_no_extra_gameplay()
    def test_cleanup_read_cannot_become_preflight_or_be_followed_by_another_read(self):
        # Exercise the real negotiated cleanup route without public result serialization.
        observation = self.runtime.observe()
        cleanup = self.runtime._observe_cleanup()
        self.assertTrue(cleanup._options['cleanup_only'])
        self.assertIsNone(self.runtime._preflight_request_id)
        self.assertIs(self.runtime._last, observation)
        with self.assertRaisesRegex(SkillError, 'cleanup_only_no_new_work'):
            self.runtime.observe()
        command = {'op':'observe','capability_observation':True,'entity_radius':8,
            '_capability_owner_id':self.runtime._owner,'_navigation_defense_epoch':self.epoch}
        response = self.client.wait(self.client.submit(command), timeout=3)
        self.assertEqual(response['reason'], 'capability_cleanup_only_no_new_work')

    def test_ordinary_observation_still_rejects_pause_and_never_uses_cleanup_exception(self):
        self.runtime.observe()
        self.bridge.game_paused = True
        with self.assertRaisesRegex(SkillError, 'game_paused_or_unknown'):
            self.runtime.observe(allow_menu=True)
        self.assertEqual(self.records('cleanup_observation'), [])
        self.assertEqual(self.records('capability_release'), [])
        self.assertTrue(self.dog.handoff_latched)
        with self.assertRaises(SkillError):
            self.runtime._observe_cleanup()
        self.assertEqual(self.records('cleanup_observation'), [])
    def test_cleanup_cannot_acquire_a_new_owner(self):
        with self.assertRaisesRegex(SkillError, 'cleanup_exact_owner_required'):
            self.runtime._observe_cleanup()
        self.assertEqual(self.records('capability_acquire'), [])
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_foreign_owner_cannot_start_cleanup_read(self):
        self.runtime.observe()
        reads = len(self.bridge.state_paths)
        command = {'op':'observe','capability_observation':True,'entity_radius':8,'capability_cleanup':True,
            '_capability_owner_id':'f'*32,'_navigation_defense_epoch':self.epoch}
        response = self.client.wait(self.client.submit(command), timeout=3)
        self.assertEqual(response['reason'], 'capability_owner_unavailable')
        self.assertEqual(len(self.bridge.state_paths), reads)
        self.assertFalse(self.dog.capability_lease.get('cleanup_started', False))
    def test_foreign_gateway_receipt_does_not_release(self):
        original = self.client.result
        def changed(rid):
            result = original(rid)
            record = self.runtime._journal['records'].get(rid, {})
            if result is not None and record.get('kind') == 'cleanup_observation':
                return {**result, 'session_id':'foreign-gateway-session'}
            return result
        self.client.result = changed
        result = self.run_paused()
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assertEqual(len(self.records('cleanup_observation')), 1)
        self.assert_no_extra_gameplay()
    def test_missing_original_disarm_proof_cannot_be_inferred_from_current_neutral_status(self):
        capture = self.dog.capability_capture_cleanup
        def missing(payload, owner):
            self.dog.capability_lease.pop('cleanup_fall_status', None)
            return capture(payload, owner)
        self.dog.capability_capture_cleanup = missing
        result = self.run_paused()
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_managed_native_owner_blocks_cleanup_even_with_external_idle_true(self):
        result = self.run_paused(lambda s: s.update(managed_navigation_status={
            'managed_navigation_schema_version':1,'input_owned':True,'unknown_outcome_quarantined':False}))
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_replacement_arm_revision_is_not_original_disarm(self):
        result = self.run_paused(lambda s: s['native_fall_rescue_status'].update(arm_revision=2))
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assert_no_extra_gameplay()
    def test_unknown_cleanup_read_is_never_repeated_or_released(self):
        original = self.client.submit
        calls = []
        def lost(command, request_id=None):
            result = original(command, request_id=request_id)
            if command.get('capability_cleanup') is True:
                calls.append(request_id)
                raise OSError('synthetic_cleanup_read_ack_lost')
            return result
        self.client.submit = lost
        result = self.run_paused()
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(self.records('capability_release'), [])
        self.assertEqual(len(calls), 1)
        self.runtime.close()
        self.assertEqual(len(calls), 1)
        self.assert_no_extra_gameplay()
    def test_stale_cleanup_proof_cannot_release(self):
        self.runtime.observe()
        self.bridge.game_paused = True
        self.runtime._observe_cleanup()
        self.dog.capability_lease['cleanup_observation']['observed_at'] -= 1
        command = {'op':'capability_release','owner_id':self.runtime._owner,'expected_defense_epoch':self.epoch}
        response = self.client.wait(self.client.submit(command), timeout=3)
        self.assertEqual(response['reason'], 'capability_cleanup_release_final_fence_failed')
        self.assertIsNotNone(self.dog.capability_lease)
    def test_cleanup_marker_is_closed_and_cannot_smuggle_action_or_menu_close(self):
        self.runtime.observe()
        reads = len(self.bridge.state_paths)
        for value in (None, False, 1, 'true', {}):
            command = {'op':'observe','capability_observation':True,'entity_radius':8,'capability_cleanup':value,
                '_capability_owner_id':self.runtime._owner,'_navigation_defense_epoch':self.epoch}
            response = self.client.wait(self.client.submit(command), timeout=3)
            self.assertEqual(response['reason'], 'invalid_capability_cleanup_observation', value)
        command['capability_cleanup'] = True
        command['op'] = 'action'
        command['action'] = 'close_menu'
        response = self.client.wait(self.client.submit(command), timeout=3)
        self.assertNotEqual(response['status'], 'succeeded')
        self.assertEqual(len(self.bridge.state_paths), reads)
        self.assertFalse(self.dog.capability_lease.get('cleanup_started', False))


class CleanupProofMatrixTests(unittest.TestCase):
    def payload(self):
        from test_gateway_integration import native_bundle
        endpoint = PausedEndpoint();endpoint.game_paused = True
        result = native_bundle(endpoint.snapshot(), 8)
        result['combat'] = {'active':False}
        state = result['state']
        context = {'world_generation':state['world']['world_generation'], 'dimension':state['world']['dimension'],
            'player_uuid':state['player']['uuid'], 'action_session':state['client_action']['action_session']}
        return result, context
    def test_explicit_boolean_pause_and_complete_neutral_proof_required(self):
        payload, context = self.payload()
        self.assertTrue(validate_cleanup(payload, context)['paused'])
        cases = [
            ('paused', lambda s: s.update(paused=None)),
            ('missing_pause', lambda s: s.pop('paused')),
            ('numeric_pause', lambda s: s.update(paused=1)),
            ('string_pause', lambda s: s.update(paused='true')),
            ('focus', lambda s: s.update(focused=None)),
            ('private_world', lambda s: s.update(private_singleplayer=False)),
            ('menu', lambda s: s.update(screen_open=None)),
            ('held_keys', lambda s: s['held_inputs'].update(keys=['W'])),
            ('raw_keys_bool', lambda s: s['held_inputs'].update(raw_keys=False)),
            ('mouse', lambda s: s['held_inputs'].update(world_mouse_buttons=1)),
            ('missing_mouse', lambda s: s['held_inputs'].pop('world_mouse_buttons')),
            ('missing_external', lambda s: s.pop('external_controller')),
            ('external_unknown', lambda s: s['external_controller'].update(idle_proven=None)),
            ('external_tick', lambda s: s['external_controller'].update(source_tick=-1)),
            ('external_session', lambda s: s['external_controller'].update(action_session='other')),
            ('native_missing', lambda s: s.pop('native_fall_rescue_status')),
            ('native_armed', lambda s: s['native_fall_rescue_status'].update(armed=True)),
            ('native_owned', lambda s: s['native_fall_rescue_status'].update(input_owned=True)),
            ('native_quarantine', lambda s: s['native_fall_rescue_status'].update(unknown_outcome_quarantined=True)),
            ('native_automation', lambda s: s['native_fall_rescue_status'].update(automation_blocked=True)),
            ('foreign_player', lambda s: s['player'].update(uuid='other')),
            ('foreign_action_session', lambda s: s['client_action'].update(action_session='other')),
            ('foreign_dimension', lambda s: s['world'].update(dimension='minecraft:the_end')),
        ]
        for feature in ('managed_navigation','external_navigation'):
            for state in (None, {}, {'input_owned':False,'unknown_outcome_quarantined':False},
                          {feature+'_schema_version':True,'input_owned':False,'unknown_outcome_quarantined':False},
                          {feature+'_schema_version':1,'input_owned':True,'unknown_outcome_quarantined':False},
                          {feature+'_schema_version':1,'input_owned':False,'unknown_outcome_quarantined':True}):
                cases.append((feature + repr(state), lambda s, feature=feature, state=state:
                              s.update({feature+'_status':state})))
            cases.append((feature+'_advertised_without_status', lambda s, feature=feature:
                          s.update({feature:{'schema_version':1}})))
        for name, edit in cases:
            with self.subTest(name=name):
                changed = deepcopy(payload);edit(changed['state'])
                with self.assertRaises(ValueError):validate_cleanup(changed, context)


if __name__ == '__main__': unittest.main()
