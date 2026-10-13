"""Real offline mailbox boundary for the narrow menu-recovery request.

The Resident, QueueClient and Watchdog are real. Only native transport and
deliberate scheduling at its read boundary are synthetic; no game is started.
The ordinary direct-command counterexamples were run separately against the
frozen pre-change tree and are recorded in menu-owner-before.log.
"""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_encounter_handoff_chain import Chain, BridgeError
from resident_controller.ipc import atomic_json


CLOSE = {'op': 'recovery_close_menu'}
ESCAPE = {'op': 'direct', 'endpoint': 'raw-key',
          'body': {'key': 'key.keyboard.escape', 'action': 'click'}}


class MenuRecoveryHandoffTests(unittest.TestCase):
    def chain(self, mode='running'):
        c = Chain(mode)
        self.addCleanup(c.close)
        original = c.bridge.request

        def menu_native(method, path, body=None):
            result = original(method, path, body)
            if path == '/control/status':
                result['held_mappings'] = []
            return result

        c.bridge.request = menu_native
        c.bridge.observed['state'].update(screen_open=True, paused=False)
        return c

    def observation(self, c):
        rid = c.q.submit({'op': 'observe'})
        c.resident.read_commands()
        result = c.q.result(rid)
        self.assertEqual('succeeded', result['status'])
        return result['result']

    def recovery(self, c):
        c.dog.latest = self.observation(c)
        c.dog.observed_at = c.dog.clock()
        c.dog.attention('observation_delayed_cancel_requested')
        c.dog.cancel_confirmed = True
        c.dog.phase = 'recovering_observation'
        c.dog.next_observe = float('inf')
        self.assertTrue(c.dog.menu_close_ready())

    def tag(self, c):
        state = c.bridge.observed['state']
        return {**copy.deepcopy(ESCAPE), 'watchdog_menu_recovery': True,
                'expected_resident_session': c.resident.session_id,
                'expected_menu_context': {
                    'world_generation': state['world']['world_generation'],
                    'player_uuid': state['player']['uuid'],
                    'action_session': c.bridge.session,
                    'game_time': state['world']['game_time'],
                    'paused': state['paused']},
                'menu_recovery_requested_at': time.time()}

    def submit_menu(self, c):
        command = {**CLOSE, '_navigation_defense_epoch': c.dog.defense_epoch,
                   '_menu_recovery_requested_at': time.time()}
        self.assertTrue(c.dog.submit_owner('close-menu', command))
        self.assertTrue(c.dog.owner['menu_recovery'])
        self.assertEqual(c.resident.session_id, c.dog.owner['resident_session'])
        return c.dog.owner['request_id']

    def side_effect_spies(self, c, stack):
        return [stack.enter_context(patch.object(obj, name, wraps=getattr(obj, name)))
                for obj, name in ((c.resident.combat, 'stop'), (c.resident.aim, 'release'),
                                  (c.resident, 'interrupt_local'), (c.resident, 'discard_pending'))]

    def assert_no_takeover(self, spies):
        for spy in spies:
            spy.assert_not_called()

    def assert_only_new_owner_admission(self, spies, mode):
        for index, spy in enumerate(spies):
            if index == 1 and mode in ('pending', 'active', 'release_and_pending'):
                spy.assert_called_once_with('semantic_task_owns_view')
            else:
                spy.assert_not_called()
            spy.reset_mock()

    def add_current_owner(self, c, mode):
        if mode in ('pending', 'active', 'release_and_pending'):
            rid = c.q.submit(c.bridge.command(), request_id='new-encounter')
            c.resident.read_commands()
            if mode == 'active':
                c.resident.advance()
            if mode == 'release_and_pending':
                c.resident.paused, c.resident.reason = True, 'input_release_unconfirmed'
            return rid
        c.resident.paused = True
        c.resident.reason = ('input_release_unconfirmed' if mode == 'release'
                             else 'encounter_requires_handoff')
        return None

    def retained(self, c):
        return {'active': c.resident.active,
                'command': copy.deepcopy(c.resident.active.command) if c.resident.active else None,
                'action_id': getattr(c.resident.active, 'action_id', None),
                'encounter': copy.deepcopy(getattr(c.resident.active, 'encounter_request', None)),
                'pending': copy.deepcopy(list(c.resident.pending)),
                'paused': c.resident.paused, 'reason': c.resident.reason,
                'native': copy.deepcopy(c.bridge.action),
                'action_posts': copy.deepcopy(c.posts('/control/action'))}

    def assert_retained(self, c, before):
        self.assertIs(before['active'], c.resident.active)
        self.assertEqual(before, self.retained(c))
        self.assertEqual([], c.posts('/control/action/cancel'))
        self.assertEqual([], c.posts('/control/release-all'))
        self.assertEqual([], c.posts('/control/raw-key'))

    def test_success_uses_one_tagged_escape_without_generic_takeover(self):
        c = self.chain()
        self.recovery(c)
        rid = self.submit_menu(c)
        queued = json.loads((c.resident.root / 'inbox' / (rid + '.json')).read_text())
        self.assertIs(queued['watchdog_menu_recovery'], True)
        self.assertEqual(c.resident.session_id, queued['expected_resident_session'])
        self.assertEqual(self.tag(c)['expected_menu_context'], queued['expected_menu_context'])
        self.assertEqual(ESCAPE['body'], queued['body'])
        with ExitStack() as stack:
            spies = self.side_effect_spies(c, stack)
            c.resident.read_commands()
            self.assert_no_takeover(spies)
        result = c.q.result(rid)
        self.assertEqual('succeeded', result['status'])
        self.assertIs(result['result']['ok'], True)
        self.assertEqual(c.resident.observation_policy(), result['resident_policy'])
        c.dog.tick()
        for _ in range(12):
            c.resident.read_commands()
            c.dog.tick()
        self.assertEqual([('POST', '/control/raw-key', ESCAPE['body'])], c.posts())
        self.assertFalse(c.dog.armed)

    def test_new_current_owner_after_enqueue_rejects_and_preserves_original(self):
        for mode in ('pending', 'active', 'handoff', 'release', 'release_and_pending'):
            with self.subTest(mode=mode):
                c = self.chain()
                self.recovery(c)
                rid = self.submit_menu(c)
                # A real queue command arrived after admission; consume it while
                # the earlier menu is already claimed, before its dispatch.
                menu_path = c.resident.root / 'inbox' / (rid + '.json')
                menu_path.rename(c.resident.root / 'working' / menu_path.name)
                owner = self.add_current_owner(c, mode)
                (c.resident.root / 'working' / menu_path.name).rename(menu_path)
                before = self.retained(c)
                with ExitStack() as stack:
                    spies = self.side_effect_spies(c, stack)
                    c.resident.read_commands()
                    self.assert_no_takeover(spies)
                self.assert_retained(c, before)
                result = c.q.result(rid)
                self.assertEqual('failed', result['status'])
                self.assertEqual(c.resident.observation_policy(), result['resident_policy'])
                if owner:
                    self.assertIsNone(c.q.result(owner))
                c.dog.tick()
                if mode in ('release', 'release_and_pending'):
                    self.assertTrue(c.dog.input_release_latched)
                    self.assertEqual('owner_input_release_unconfirmed', c.dog.reason)
                else:
                    self.assertTrue(c.dog.handoff_latched)
                self.assertEqual([], c.posts('/control/release-all'))
                if mode == 'pending':
                    c.resident.advance()
                    expected = {key: copy.deepcopy(value) for key, value in c.bridge.command().items()
                                if key != 'op'}
                    expected['action_id'] = uuid.uuid5(uuid.UUID(c.resident.session_id), owner + ':1').hex
                    self.assertEqual([expected], [call[2] for call in c.posts('/control/action')])

    def test_owner_change_inside_native_read_is_rechecked_before_escape(self):
        for mode in ('pending', 'active', 'handoff', 'release', 'release_and_pending'):
            with self.subTest(mode=mode):
                c = self.chain()
                self.recovery(c)
                rid = self.submit_menu(c)
                original = c.bridge.request
                transitioned = []

                def change_during_read(method, path, body=None):
                    result = original(method, path, body)
                    if path == '/control/status' and not transitioned:
                        self.assert_no_takeover(spies)
                        transitioned.append(None)
                        self.add_current_owner(c, mode)
                        self.assert_only_new_owner_admission(spies, mode)
                        transitioned[0] = self.retained(c)
                    return result

                c.bridge.request = change_during_read
                with ExitStack() as stack:
                    spies = self.side_effect_spies(c, stack)
                    c.resident.read_commands()
                    self.assert_no_takeover(spies)
                self.assertEqual(1, len(transitioned))
                self.assert_retained(c, transitioned[0])
                self.assertEqual('failed', c.q.result(rid)['status'])
                self.assertEqual(c.resident.observation_policy(), c.q.result(rid)['resident_policy'])
                c.dog.tick()
                self.assertEqual([], c.posts('/control/release-all'))

    def test_tag_validation_failure_cannot_fall_through_to_ordinary_direct(self):
        edits = [lambda cmd: cmd.update(watchdog_menu_recovery=False),
                 lambda cmd: cmd.update(watchdog_menu_recovery=1),
                 lambda cmd: cmd.update(endpoint='key'),
                 lambda cmd: cmd['body'].update(action='down'),
                 lambda cmd: cmd.update(expected_resident_session='old-session'),
                 lambda cmd: cmd.pop('expected_menu_context'),
                 lambda cmd: cmd['expected_menu_context'].update(paused=0),
                 lambda cmd: cmd['expected_menu_context'].update(game_time=True),
                 lambda cmd: cmd.update(menu_recovery_requested_at=True),
                 lambda cmd: cmd.update(menu_recovery_requested_at=time.time() - 1),
                 lambda cmd: cmd.update(menu_recovery_requested_at=time.time() + 1)]
        for i, edit in enumerate(edits):
            with self.subTest(edit=i):
                c = self.chain()
                self.add_current_owner(c, 'active')
                before = self.retained(c)
                command = self.tag(c)
                edit(command)
                rid = c.q.submit(command)
                with ExitStack() as stack:
                    spies = self.side_effect_spies(c, stack)
                    c.resident.read_commands()
                    self.assert_no_takeover(spies)
                self.assertEqual('failed', c.q.result(rid)['status'])
                self.assertEqual(c.resident.observation_policy(), c.q.result(rid)['resident_policy'])
                self.assert_retained(c, before)

    def test_uncertain_read_after_new_owner_preserves_pending_and_native_id_body(self):
        c = self.chain()
        self.recovery(c)
        rid = self.submit_menu(c)
        original = c.bridge.request
        before = []

        def failed_read(method, path, body=None):
            if path == '/control/state?radius=8':
                self.assert_no_takeover(spies)
                self.add_current_owner(c, 'release_and_pending')
                self.assert_only_new_owner_admission(spies, 'release_and_pending')
                before.append(self.retained(c))
                raise BridgeError('menu_read_timeout', uncertain=True)
            return original(method, path, body)

        c.bridge.request = failed_read
        with ExitStack() as stack:
            spies = self.side_effect_spies(c, stack)
            c.resident.read_commands()
            self.assert_no_takeover(spies)
        self.assertEqual(1, len(before))
        self.assert_retained(c, before[0])
        result = c.q.result(rid)
        self.assertEqual(('uncertain', 'menu_read_timeout'), (result['status'], result['reason']))
        self.assertTrue(result['resident_policy']['requires_handoff'])
        self.assertTrue(result['resident_policy']['input_release_unconfirmed'])
        c.dog.tick()
        self.assertTrue(c.dog.input_release_latched)
        self.assertEqual('owner_input_release_unconfirmed', c.dog.reason)
        self.assertEqual([], c.posts())

    def test_unknown_escape_is_single_dispatch_without_release_or_replay(self):
        for mode in ('timeout', 'malformed_ack'):
            with self.subTest(mode=mode):
                c = self.chain()
                self.recovery(c)
                rid = self.submit_menu(c)
                original = c.bridge.request

                def unknown_post(method, path, body=None):
                    if path == '/control/raw-key':
                        c.bridge.calls.append((method, path, copy.deepcopy(body)))
                        if mode == 'timeout':
                            raise BridgeError('menu_post_timeout', uncertain=True)
                        return {'ok': 'unknown'}
                    return original(method, path, body)

                c.bridge.request = unknown_post
                with ExitStack() as stack:
                    spies = self.side_effect_spies(c, stack)
                    c.resident.read_commands()
                    self.assert_no_takeover(spies)
                self.assertEqual('uncertain', c.q.result(rid)['status'])
                c.dog.tick()
                for _ in range(12):
                    c.dog.tick()
                    c.resident.read_commands()
                self.assertFalse(c.dog.armed)
                self.assertFalse(c.dog.recover_observation)
                self.assertEqual('menu_recovery_outcome_unconfirmed', c.dog.reason)
                self.assertEqual([('POST', '/control/raw-key', ESCAPE['body'])], c.posts())
                self.assertEqual(1, len([done for done in c.dog.completed if done['intent_id'] == 'close-menu']))

    def test_changed_native_status_identity_cannot_call_generic_identity_cleanup(self):
        for field in ('run_id', 'process_id', 'action_session'):
            with self.subTest(field=field):
                c = self.chain()
                command = self.tag(c)
                original = c.bridge.request

                def changed_status(method, path, body=None):
                    result = original(method, path, body)
                    if path == '/control/status':
                        if field == 'action_session':
                            result['client_action'][field] = 'different-native-session'
                        else:
                            result[field] = 'different-native-identity'
                    return result

                c.bridge.request = changed_status
                before = self.retained(c)
                rid = c.q.submit(command)
                with ExitStack() as stack:
                    spies = self.side_effect_spies(c, stack)
                    c.resident.read_commands()
                    self.assert_no_takeover(spies)
                self.assertEqual('failed', c.q.result(rid)['status'])
                self.assert_retained(c, before)

    def test_changed_native_observations_are_rejected_without_takeover(self):
        modes = ('status_running', 'status_out_of_world', 'status_holds', 'status_missing_holds',
                 'world', 'player', 'session', 'state_running', 'missing_pause', 'unknown_pause',
                 'changed_pause', 'closed_screen', 'dead', 'invalid_health', 'backward_tick')
        for mode in modes:
            with self.subTest(mode=mode):
                c = self.chain()
                command = self.tag(c)
                original = c.bridge.request

                def changed_observation(method, path, body=None):
                    result = original(method, path, body)
                    if path == '/control/status':
                        if mode == 'status_running': result['client_action']['status'] = 'running'
                        elif mode == 'status_out_of_world': result['in_world'] = False
                        elif mode == 'status_holds': result['held_mappings'] = ['key.attack']
                        elif mode == 'status_missing_holds': result.pop('held_mappings')
                    if path == '/control/state?radius=8':
                        if mode == 'world': result['world']['world_generation'] = 'different-world'
                        elif mode == 'player': result['player']['uuid'] = 'different-player'
                        elif mode == 'session': result['client_action']['action_session'] = 'different-session'
                        elif mode == 'state_running': result['client_action']['status'] = 'running'
                        elif mode == 'missing_pause': result.pop('paused')
                        elif mode == 'unknown_pause': result['paused'] = None
                        elif mode == 'changed_pause': result['paused'] = not result['paused']
                        elif mode == 'closed_screen': result['screen_open'] = False
                        elif mode == 'dead': result['player']['alive'] = False
                        elif mode == 'invalid_health': result['player']['health'] = float('nan')
                        elif mode == 'backward_tick': result['world']['game_time'] -= 1
                    return result

                c.bridge.request = changed_observation
                before = self.retained(c)
                rid = c.q.submit(command)
                with ExitStack() as stack:
                    spies = self.side_effect_spies(c, stack)
                    c.resident.read_commands()
                    self.assert_no_takeover(spies)
                self.assertEqual('failed', c.q.result(rid)['status'])
                self.assert_retained(c, before)

    def test_missing_menu_result_never_cancelled_or_resubmitted(self):
        c = self.chain()
        self.recovery(c)
        rid = self.submit_menu(c)
        initial = json.loads((c.resident.root / 'inbox' / (rid + '.json')).read_text())
        c.dog.clock = lambda: 150.0
        for _ in range(12):
            c.dog.tick()
        self.assertEqual(rid, c.dog.owner['request_id'])
        self.assertIsNone(c.dog.rpc)
        self.assertEqual([initial], [json.loads(path.read_text())
                                    for path in (c.resident.root / 'inbox').glob('*.json')])
        self.assertEqual([], c.posts())

    def test_untrusted_menu_result_cannot_clear_pause_or_trigger_cancel(self):
        edits = [lambda result: result.update(request_id='foreign-request'),
                 lambda result: result.update(session_id='foreign-session'),
                 lambda result: result.pop('resident_policy'),
                 lambda result: result['resident_policy'].update(input_release_unconfirmed=1),
                 lambda result: result['resident_policy'].update(schema_version=True)]
        for i, edit in enumerate(edits):
            with self.subTest(edit=i):
                c = self.chain()
                self.recovery(c)
                rid = self.submit_menu(c)
                c.resident.read_commands()
                result = c.q.result(rid)
                edit(result)
                atomic_json(c.resident.root / 'results' / (rid + '.json'), result)
                c.dog.tick()
                for _ in range(8):
                    c.dog.tick()
                    c.resident.read_commands()
                self.assertFalse(c.dog.armed)
                self.assertFalse(c.dog.recover_observation)
                self.assertEqual('menu_recovery_outcome_unconfirmed', c.dog.reason)
                self.assertEqual([('POST', '/control/raw-key', ESCAPE['body'])], c.posts())

    def test_explicit_ordinary_direct_still_takes_over_encounter(self):
        c = self.chain()
        owner = self.add_current_owner(c, 'active')
        original = copy.deepcopy(c.posts('/control/action'))
        c.resident.paused, c.resident.reason = True, 'input_release_unconfirmed'
        rid = c.q.submit(copy.deepcopy(ESCAPE))
        c.resident.read_commands()
        self.assertEqual('succeeded', c.q.result(rid)['status'])
        self.assertEqual('cancelled', c.q.result(owner)['status'])
        self.assertEqual('direct_takeover', c.q.result(owner)['reason'])
        self.assertFalse(c.resident.paused)
        self.assertIsNone(c.resident.active)
        self.assertEqual(original, c.posts('/control/action'))
        self.assertEqual(1, len(c.posts('/control/raw-key')))


if __name__ == '__main__':
    unittest.main()
