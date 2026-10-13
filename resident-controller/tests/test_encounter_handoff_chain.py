"""Java-emitted fixture -> real Resident/QueueClient/v5 Watchdog/Cursor.

This is a synthetic offline consumer chain, not game or live-physics evidence.
The fixture file is a byte-for-byte copy of EncounterReceiptEmissionTest output
(SHA-256 below). Only native I/O is fake: the Resident mailbox, task generator,
Watchdog decision logic and Navigator pending/checkpoint handling are real.

At the fake native boundary, ``action_id`` is adapted to the real Resident's
UUID5 step ID. Each terminal case has its own emitted action_session; the
running fixture's session is adapted to that case's request/session before
polling. Terminal receipts otherwise remain unchanged. Thus this does NOT
claim that unmodified native fixture bytes traversed the entire chain.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'resident-controller'),
                str(ROOT / 'resident-controller/tests'),
                str(ROOT / 'navigation-cursor'),
                str(ROOT / 'navigation-cursor/tests'),
                str(ROOT / 'defense-watchdog')]
from test_controller import FakeBridge
from test_navigation_cursor import observation
from navigation_cursor import Navigator, input_release_unconfirmed
from resident_controller.action_safety import task_handoff_required, task_release_unconfirmed
from resident_controller.controller import Resident
from resident_controller.encounter_contract import validate_encounter_request, validate_encounter_receipt
from resident_controller.ipc import QueueClient
from resident_controller.transport import BridgeError
from watchdog import Watchdog

FIXTURE = Path(__file__).with_name('fixtures') / 'native-encounter-receipts.json'
FIXTURE_SHA256 = 'ad12c62ff936057a27f3110ea3bcf9d86c65649184cfd29f494ba02d5ef0a539'
CASES = {case['name']: case for case in json.loads(FIXTURE.read_bytes())['cases']}
NODES = [(x, 64, z) for x in range(4) for z in range(3)]
GOAL = (3, 64, 0)


class NativeReceiptBridge(FakeBridge):
    """Only the native transport is simulated; never opens sockets or a game."""
    def __init__(self, case_name='succeeded', post_failure=None):
        super().__init__()
        self.case = copy.deepcopy(CASES[case_name])
        self.post_failure = post_failure
        self.cancel_failure = False
        self.accepted = None
        self.session = self.case['request']['expected_action_session']
        self.action['action_session'] = self.session
        self.observed = observation((0, 64, 0), NODES)
        self.observed['state']['world'].update(
            world_generation=self.case['request']['expected_world_generation'], game_time=10)
        self.observed['terrain']['world_generation'] = self.case['request']['expected_world_generation']
        self.observed['state']['player'].update(
            uuid=self.case['request']['expected_player_uuid'], inventory=[])
        self.observed['state'].update(paused=False, screen_open=False)

    def command(self):
        # The real Resident, not a test-supplied ID, owns the native step ID.
        return {'op': 'action', **{k: copy.deepcopy(v) for k, v in self.case['request'].items()
                                  if k != 'action_id'}}

    def adapted_receipt(self, name, action_id):
        result = copy.deepcopy(CASES[name]['receipt'])
        result['action_id'] = action_id
        if name == 'running':
            result['action_session'] = self.session
        return result

    def finish_native(self):
        self.action = self.adapted_receipt(self.case['name'], self.accepted['action_id'])
        return copy.deepcopy(self.action)

    def request(self, method, path, body=None):
        if path == '/control/action' and body.get('encounter_mode'):
            self.calls.append((method, path, copy.deepcopy(body)))
            if self.post_failure == 'gate409':
                raise BridgeError('encounter_stage1_disabled', status=409)
            self.accepted = copy.deepcopy(body)
            self.action = self.adapted_receipt('running', body['action_id'])
            if self.post_failure == 'timeout':
                raise BridgeError('transport_failed', uncertain=True)
            return copy.deepcopy(self.action)
        if path == '/control/action/cancel':
            if self.cancel_failure:
                self.calls.append((method, path, copy.deepcopy(body)))
                raise BridgeError('transport_failed', uncertain=True)
            return super().request(method, path, body)
        if path == '/control/state?radius=8':
            self.calls.append((method, path, copy.deepcopy(body)))
            state = copy.deepcopy(self.observed['state'])
            state['client_action'] = copy.deepcopy(self.action)
            return state
        # A release acknowledgement is fixture transport behavior, not native
        # release evidence. Never use it to rewrite the preserved raw receipt.
        if path == '/control/release-all':
            self.calls.append((method, path, copy.deepcopy(body)))
            return {'ok': True}
        result = super().request(method, path, body)
        if path == '/control/action':
            # Legacy controls use an ordinary synthetic FakeBridge receipt.
            self.action['action_session'] = self.session
            result['action_session'] = self.session
        if path == '/control/status':
            result['world'] = copy.deepcopy(self.observed['state']['world'])
            result['player'] = copy.deepcopy(self.observed['state']['player'])
        return result


class WatchdogGateway:
    """In-process adapter around the actual watchdog, never canned results."""
    def __init__(self, dog):
        self.dog = dog

    def session(self):
        return self.dog.status()

    def submit(self, command, request_id=None):
        if not self.dog.submit_owner(request_id, command):
            raise AssertionError('Unexpected watchdog admission refusal')
        return request_id

    def result(self, request_id):
        return next((entry['result'] for entry in self.dog.completed
                     if entry['intent_id'] == request_id), None)


class Chain:
    def __init__(self, case_name='succeeded', post_failure=None):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = NativeReceiptBridge(case_name, post_failure)
        self.resident = Resident(self.bridge, self.temp.name)
        self.resident.start()
        self.q = QueueClient(self.temp.name)
        self.dog = Watchdog(self.q, clock=lambda: 100.0)
        self.dog.latest = copy.deepcopy(self.bridge.observed)
        self.dog.observed_at = 100.0
        self.dog.next_observe = float('inf')
        self.gateway = WatchdogGateway(self.dog)
        self.checkpoint = Path(self.temp.name) / 'cursor.json'
        self.nav = Navigator(self.gateway, checkpoint=self.checkpoint)
        self.nav.data.update(target=list(GOAL), gateway_session=self.dog.session_id, observation_epoch=0)
        self.intent_id = self.queue_id = self.native_id = None

    def close(self):
        if self.resident.lock:
            self.resident.lock.close()
        self.temp.cleanup()

    def pump(self, count=1):
        for _ in range(count):
            if self.resident.active:
                self.resident.active.wake_at = 0
            self.resident.tick()
            self.dog.tick()

    def start(self):
        result = self.nav.submit('action', self.bridge.command(), start_index=0, end_index=0,
                                 purpose='explicit_encounter_test')
        if result['status'] != 'pending':
            raise AssertionError(result)
        self.intent_id = result['request_id']
        self.queue_id = self.dog.owner['request_id']
        self.pump()
        self.native_id = self.posts('/control/action')[0][2]['action_id']
        return result

    def finish_native(self):
        raw = self.bridge.finish_native()
        self.pump(5)
        return raw

    def posts(self, path=None):
        return [call for call in self.bridge.calls if call[0] == 'POST'
                and (path is None or call[1] == path)]

    def hostile(self):
        entity = dict(self.bridge.case['request']['encounter_scope'][0], alive=True,
                      health=20, distance=2, x=2.5, y=64, z=.5)
        self.bridge.observed['state']['nearby'] = {'entities': [entity]}
        self.bridge.observed['state']['player']['inventory'] = [
            {'id': 'minecraft:iron_sword', 'count': 1, 'slot': 0}]
        self.dog.latest = copy.deepcopy(self.bridge.observed)


class NativeFixtureProvenanceTests(unittest.TestCase):
    def test_exact_emitted_bytes_and_five_states(self):
        self.assertEqual(FIXTURE_SHA256, hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        self.assertEqual({'running', 'succeeded', 'failed', 'cancelled', 'cleanup_failed'}, set(CASES))
        self.assertEqual('synthetic_offline_no_game_physics', json.loads(FIXTURE.read_bytes())['observations'])

    def test_every_unadapted_emitted_receipt_validates_against_its_own_request(self):
        for name, case in CASES.items():
            with self.subTest(case=name):
                request = validate_encounter_request(case['request'])
                validate_encounter_receipt(case['receipt'], request)
                self.assertEqual(case['request']['action_id'], case['receipt']['action_id'])
                self.assertEqual(case['request']['expected_action_session'], case['receipt']['action_session'])


class EncounterHandoffChainTests(unittest.TestCase):
    def chain(self, *args, **kwargs):
        chain = Chain(*args, **kwargs)
        self.addCleanup(chain.close)
        return chain

    def assert_no_replay(self, c, reason='encounter_requires_handoff'):
        for _ in range(8):
            c.pump()
            result = c.nav.tick(GOAL)
            self.assertEqual(('blocked', reason), (result['status'], result['reason']))
        self.assertEqual(1, len(c.posts('/control/action')))
        self.assertEqual(c.intent_id, c.nav.data['pending']['id'])
        restored = Navigator(c.gateway, checkpoint=c.checkpoint)
        self.assertEqual(reason, restored.tick(GOAL)['reason'])
        self.assertEqual(c.intent_id, restored.data['pending']['id'])

    def assert_terminal(self, name):
        c = self.chain(name)
        c.start()
        queued_path = c.q.submit({'op': 'action', 'action': 'follow_path', 'waypoints': []})
        raw = c.finish_native()
        result = c.gateway.result(c.intent_id)
        self.assertEqual(raw['status'], result['status'])
        native_result = result['result']['action'] if result['status'] == 'succeeded' else result['action']
        self.assertEqual(raw, native_result)
        original = copy.deepcopy(CASES[name]['receipt'])
        original['action_id'] = c.native_id
        self.assertEqual(original, native_result)
        self.assertTrue(result['requires_handoff'])
        self.assertTrue(result['risk_remaining'])
        self.assertFalse(result['safety_assured'])
        self.assertTrue(task_handoff_required(result))
        self.assertEqual(c.queue_id, result['request_id'])
        self.assertEqual(c.resident.session_id, result['session_id'])
        completed = next(entry for entry in c.dog.completed if entry['intent_id'] == c.intent_id)
        self.assertEqual(c.queue_id, completed['queue_request_id'])
        self.assertEqual(c.dog.session_id, completed['session_id'])
        expected_id = uuid.uuid5(uuid.UUID(c.resident.session_id), c.queue_id + ':1').hex
        self.assertEqual(expected_id, c.native_id)
        self.assertEqual(3, len({c.intent_id, c.queue_id, c.native_id}))
        self.assertNotEqual('combat-a', c.native_id)
        self.assertTrue(c.resident.paused)
        self.assertFalse(c.resident.combat.active)
        self.assertEqual('cancelled', c.q.result(queued_path)['status'])
        self.assertEqual('paused', c.dog.status()['state'])
        self.assertFalse(c.dog.armed)
        reason = ('input_release_unconfirmed_requires_operator' if name == 'cleanup_failed'
                  else 'encounter_requires_handoff')
        self.assertEqual(name == 'cleanup_failed', c.dog.input_release_latched)
        if name != 'cleanup_failed':
            self.assertTrue(raw['result']['input_release_confirmed'])
            self.assertTrue(c.dog.handoff_latched)
        self.assert_no_replay(c, reason)
        self.assertEqual(['/control/action'], [call[1] for call in c.posts()])
        self.assertFalse(c.dog.submit_owner('later-path', {'op': 'action', 'action': 'follow_path', 'waypoints': []}))
        with self.assertRaises(ValueError):
            c.dog.send('start_combat', {'op': 'combat_start'})
        later_path = c.q.submit({'op': 'action', 'action': 'follow_path', 'waypoints': []})
        old_combat = c.q.submit({'op': 'combat_start'})
        c.pump(3)
        self.assertEqual('failed', c.q.result(later_path)['status'])
        self.assertEqual('failed', c.q.result(old_combat)['status'])
        self.assertEqual(['/control/action'], [call[1] for call in c.posts()])

    def test_success_with_confirmed_release_still_requires_handoff(self):
        self.assert_terminal('succeeded')

    def test_failure_with_confirmed_release_still_requires_handoff(self):
        self.assert_terminal('failed')

    def test_cancellation_with_confirmed_release_still_requires_handoff(self):
        self.assert_terminal('cancelled')

    def test_cleanup_failure_preserves_failed_native_receipt_and_release_latch(self):
        self.assert_terminal('cleanup_failed')

    def test_running_hold_prevents_environment_and_ranged_priority_preemption(self):
        for priority in ('environment_active', 'new_environment_hazard', 'expired_ranged_move'):
            with self.subTest(priority=priority):
                c = self.chain('succeeded')
                c.start()
                before = copy.deepcopy(c.dog.owner)
                if priority == 'environment_active':
                    c.dog.environment.active = True
                    c.dog.environment.next_observe = 0
                elif priority == 'new_environment_hazard':
                    c.dog.latest['state']['player'].update(environment_schema_version=1,
                        in_water=True, eye_in_water=False, in_lava=False, in_powder_snow=False,
                        on_fire=False, frozen_ticks=0)
                else:
                    c.dog.ranged_move = {'id': 'preexisting-ranged-request', 'started': 0}
                c.dog.next_observe = 0
                for _ in range(8):
                    c.pump()
                    result = c.nav.tick(GOAL)
                    self.assertEqual(('pending', c.intent_id), (result['status'], result['request_id']))
                self.assertEqual(before, c.dog.owner)
                self.assertIsNone(c.dog.rpc)
                self.assertIsNone(c.q.result(c.queue_id))
                self.assertFalse(c.resident.paused)
                self.assertFalse(c.dog.handoff_latched)
                self.assertEqual(c.bridge.session, c.bridge.action['action_session'])
                validate_encounter_receipt(c.bridge.action, c.bridge.command())
                self.assertEqual(['/control/action'], [call[1] for call in c.posts()])
                self.assertEqual([], list((Path(c.temp.name) / 'inbox').glob('*.json')))

    def test_restarted_watchdog_cannot_clear_resident_handoff_with_automatic_cancel(self):
        for name in ('succeeded', 'failed', 'cancelled', 'cleanup_failed'):
            with self.subTest(case=name):
                c = self.chain(name)
                c.start()
                raw = c.finish_native()
                self.assertTrue(c.resident.paused)
                c.hostile()
                c.dog = Watchdog(c.q, clock=lambda: 100.0)
                c.pump(8)
                self.assertTrue(c.resident.paused, f'Automatic writes after restart: {c.posts()}')
                self.assertTrue(c.dog.latest['requires_handoff'])
                self.assertEqual(raw, c.dog.latest['action'])
                self.assertEqual('paused', c.dog.status()['state'])
                if name == 'cleanup_failed':
                    self.assertEqual('input_release_unconfirmed', c.resident.reason)
                    self.assertTrue(c.dog.input_release_latched)
                else:
                    self.assertEqual('encounter_requires_handoff', c.resident.reason)
                    self.assertTrue(c.dog.handoff_latched)
                self.assertEqual(['/control/action'], [call[1] for call in c.posts()])

    def test_restarted_watchdog_observes_running_owner_without_cancel_or_legacy_defense(self):
        c = self.chain('running')
        c.start()
        c.hostile()
        c.dog = Watchdog(c.q, clock=lambda: 100.0)
        c.pump(8)
        self.assertTrue(c.dog.latest['requires_handoff'])
        self.assertTrue(c.dog.handoff_latched)
        self.assertEqual('paused', c.dog.status()['state'])
        self.assertIsNotNone(c.resident.active)
        self.assertEqual(c.native_id, c.resident.active.action_id)
        self.assertIsNone(c.q.result(c.queue_id))
        self.assertEqual('running', c.bridge.action['status'])
        self.assertEqual(['/control/action'], [call[1] for call in c.posts()])
        c.dog.stop()
        c.pump(8)
        self.assertTrue(c.dog.stopped)
        self.assertTrue(c.dog.cancel_confirmed)
        self.assertEqual(1, len(c.posts('/control/release-all')))
        self.assertEqual(1, len(c.posts('/control/action')))

    def test_explicit_resume_removes_current_marker_without_erasing_historical_receipt(self):
        for name in ('succeeded', 'failed', 'cancelled'):
            with self.subTest(case=name):
                c = self.chain(name)
                c.start()
                raw = c.finish_native()
                self.assertTrue(raw['result']['input_release_confirmed'])
                resume_id = c.q.submit({'op': 'resume'})  # Explicit operator command in this test.
                c.pump(2)
                self.assertEqual('succeeded', c.q.result(resume_id)['status'])
                self.assertFalse(c.resident.paused)
                observe_id = c.q.submit({'op': 'observe'})
                c.pump(2)
                observed = c.q.result(observe_id)
                self.assertEqual('succeeded', observed['status'])
                self.assertNotIn('requires_handoff', observed['result'])
                self.assertEqual(raw, observed['result']['action'])
                self.assertFalse(task_handoff_required(observed))
                c.dog = Watchdog(c.q, clock=lambda: 100.0)
                c.pump(4)
                self.assertFalse(c.dog.handoff_latched)
                self.assertFalse(c.dog.input_release_latched)
                self.assertEqual('ready', c.dog.status()['state'])
                self.assertEqual(['/control/action'], [call[1] for call in c.posts()])

    def test_gate409_is_definite_rejection_and_never_retried(self):
        c = self.chain(post_failure='gate409')
        c.start()
        c.pump(3)
        result = c.gateway.result(c.intent_id)
        self.assertEqual('failed', result['status'])
        self.assertEqual('encounter_stage1_disabled', result['reason'])
        self.assertEqual({'schema_version': 1, 'http_status': 409, 'admitted': False,
                          'uncertain': False, 'reason': 'encounter_stage1_disabled'},
                         result['action_admission'])
        self.assertIsNone(result['action'])
        self.assertIsNone(result['action_id'])
        self.assertIsNone(result['cancellation'])
        self.assertIsNone(result['resolved_action'])
        self.assertEqual('unresolved', result['action_outcome'])
        self.assertFalse(result['task_completed'])
        self.assertTrue(result['requires_handoff'])
        self.assertTrue(c.resident.paused)
        self.assertTrue(c.dog.handoff_latched)
        self.assert_no_replay(c)
        self.assertEqual(['/control/action'], [call[1] for call in c.posts()])

    def test_uncertain_post_with_unknown_cancellation_stops_without_action_replay(self):
        c = self.chain(post_failure='timeout')
        c.bridge.cancel_failure = True
        c.start()
        c.pump(3)
        result = c.gateway.result(c.intent_id)
        self.assertEqual('uncertain', result['status'])
        self.assertEqual('transport_failed', result['reason'])
        self.assertEqual(c.native_id, result['action_id'])
        self.assertIsNone(result['action'])
        self.assertIsNone(result['resolved_action'])
        self.assertEqual('unresolved', result['action_outcome'])
        self.assertFalse(result['task_completed'])
        self.assertEqual({'status': 'unconfirmed'}, result['cancellation'])
        self.assertTrue(c.resident.paused)
        self.assertTrue(c.dog.handoff_latched)
        self.assertEqual(1, len(c.posts('/control/action/cancel')))
        self.assertEqual({'action_id': c.native_id, 'expected_action_session': c.bridge.session},
                         c.posts('/control/action/cancel')[0][2])
        self.assert_no_replay(c)
        self.assertEqual(['/control/action', '/control/action/cancel'], [call[1] for call in c.posts()])

    def test_unknown_polled_status_preserves_last_valid_running_receipt_and_stops(self):
        c = self.chain()
        c.start()
        running = copy.deepcopy(c.bridge.action)
        c.bridge.action['status'] = 'future_native_status'
        c.bridge.cancel_failure = True
        c.pump(3)
        result = c.gateway.result(c.intent_id)
        self.assertEqual('uncertain', result['status'])
        self.assertEqual('encounter_action_receipt_invalid', result['reason'])
        self.assertEqual(running, result['action'])
        self.assertEqual(c.native_id, result['action_id'])
        self.assertIsNone(result['resolved_action'])
        self.assertFalse(result['task_completed'])
        self.assertTrue(c.resident.paused)
        self.assertTrue(c.dog.handoff_latched)
        self.assert_no_replay(c)
        self.assertEqual(['/control/action', '/control/action/cancel'], [call[1] for call in c.posts()])

    def test_explicit_operator_stop_remains_available_while_running_and_after_each_terminal(self):
        for name in CASES:
            with self.subTest(case=name):
                c = self.chain(name)
                c.start()
                if name != 'running':
                    c.finish_native()
                c.dog.stop()
                c.pump(8)
                self.assertTrue(c.dog.stopped)
                self.assertTrue(c.dog.cancel_confirmed)
                self.assertEqual('stopped', c.dog.status()['state'])
                self.assertEqual(1, len(c.posts('/control/release-all')))
                self.assertEqual(1, len(c.posts('/control/action')))
                c.pump(8)
                self.assertEqual(1, len(c.posts('/control/release-all')))
                self.assertEqual(1, len(c.posts('/control/action')))

    def test_successful_observation_of_historical_receipt_does_not_latch_any_consumer(self):
        for name in ('succeeded', 'failed', 'cancelled', 'cleanup_failed'):
            with self.subTest(case=name):
                c = self.chain(name)
                # Installed after Resident startup: a historical read in a
                # currently unpaused resident is not a newly completed task.
                c.bridge.action = copy.deepcopy(CASES[name]['receipt'])
                c.nav.data['target'] = [0, 64, 0]
                result = c.nav.submit('observe', {'op': 'observe'}, defense_epoch=0)
                c.pump(3)
                response = c.gateway.result(result['request_id'])
                self.assertEqual('succeeded', response['status'])
                self.assertEqual(CASES[name]['receipt'], response['result']['action'])
                self.assertFalse(task_handoff_required(response))
                self.assertFalse(task_release_unconfirmed(response))
                self.assertFalse(input_release_unconfirmed(response))
                self.assertFalse(c.resident.paused)
                self.assertFalse(c.dog.handoff_latched)
                self.assertFalse(c.dog.input_release_latched)
                self.assertEqual('ready', c.dog.status()['state'])
                arrived = c.nav.tick((0, 64, 0))
                self.assertEqual(('complete', 'target_arrival_observed'),
                                 (arrived['status'], arrived['reason']))
                self.assertIsNone(c.nav.data['blocked'])
                self.assertIsNone(c.nav.data['pending'])
                self.assertEqual([], c.posts())

    def test_legacy_combat_without_encounter_keeps_existing_path_resume_semantics(self):
        for status in ('succeeded', 'failed', 'cancelled'):
            for release in ('missing', True):
                with self.subTest(status=status, release=release):
                    c = self.chain()
                    request = c.nav.submit('action', {'op': 'action', 'action': 'combat_entity',
                        'target_uuid': 'legacy-target'}, start_index=0, end_index=0)
                    c.pump()
                    c.bridge.action.update(status=status, reason='legacy_terminal', result={'combat': {}})
                    if release is True:
                        c.bridge.action['result']['input_release_confirmed'] = True
                    c.pump(5)
                    response = c.gateway.result(request['request_id'])
                    self.assertEqual(status, response['status'])
                    self.assertNotIn('requires_handoff', response)
                    self.assertFalse(task_handoff_required(response))
                    self.assertFalse(c.resident.paused)
                    self.assertFalse(c.dog.handoff_latched)
                    self.assertFalse(c.dog.input_release_latched)
                    self.assertEqual('progress', c.nav.tick(GOAL)['status'])
                    self.assertIsNone(c.nav.data['pending'])
                    self.assertEqual('pending', c.nav.process_observation(copy.deepcopy(c.bridge.observed))['status'])
                    c.pump()
                    self.assertEqual(['combat_entity', 'follow_path'],
                                     [call[2]['action'] for call in c.posts('/control/action')])


if __name__ == '__main__':
    unittest.main()
