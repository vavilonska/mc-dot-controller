"""Synthetic native receipt -> real Resident/Watchdog/Navigator, without a game or HTTP."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'navigation-cursor'), str(ROOT / 'navigation-cursor/tests'),
                str(ROOT / 'defense-watchdog')]
from test_navigation_cursor import Gateway, observation
from navigation_cursor import Navigator, input_release_unconfirmed
from test_controller import FakeBridge
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.action_safety import native_release_unconfirmed, task_release_unconfirmed
from base_watchdog import Watchdog as BaseWatchdog
from watchdog import Watchdog

NODES = [(x, 64, z) for x in range(4) for z in range(3)]
GOAL = (3, 64, 0)


def receipt(released=False, status='failed', reason='input_release_unconfirmed'):
    value = {'action_schema_version': 1, 'action_session': 'test-session', 'action_id': 'native-id',
             'action': 'follow_path', 'status': status, 'reason': reason, 'result': {}}
    if released != 'missing':
        value['result']['input_release_confirmed'] = released
    return value


class NativeFixture(FakeBridge):
    def __init__(self):
        super().__init__()
        self.observed = observation((0, 64, 0), NODES)
    def request(self, method, path, body=None):
        if path == '/control/state?radius=8':
            self.calls.append((method, path, copy.deepcopy(body)))
            return copy.deepcopy(self.observed['state'])
        return super().request(method, path, body)


class RealGateway:
    """The real watchdog owns the real resident mailbox; only native I/O is fake."""
    def __init__(self, dog): self.dog = dog
    def session(self): return self.dog.status()
    def submit(self, command, request_id=None):
        if not self.dog.submit_owner(request_id, command):
            raise AssertionError('Gateway admission unexpectedly refused')
        return request_id
    def result(self, request_id):
        for item in self.dog.completed:
            if item['intent_id'] == request_id:
                return item['result']
        return None


class EvidenceTests(unittest.TestCase):
    def test_explicit_nontrue_is_unknown_but_missing_legacy_is_unchanged(self):
        for value in (False, None, 0, 'false'):
            self.assertTrue(native_release_unconfirmed(receipt(value, reason='other_failure')))
        for value in (True, 'missing'):
            self.assertFalse(native_release_unconfirmed(receipt(value, reason='ordinary_failure')))
    def test_task_and_standalone_cursor_agree_on_known_envelopes(self):
        for value in (False, None, 0, True, 'missing'):
            for status in ('failed', 'cancelled', 'uncertain', 'succeeded'):
                for nested in (False, True):
                    action = receipt(value, reason='ordinary_failure')
                    result = {'status': status, 'result': {'action': action}} if nested else {'status': status, 'action': action}
                    self.assertEqual(task_release_unconfirmed(result), input_release_unconfirmed(result))
    def test_successful_observation_does_not_latch_historical_receipt(self):
        value = {'status': 'succeeded', 'result': {'action': receipt(False)}}
        self.assertFalse(task_release_unconfirmed(value))
        self.assertFalse(input_release_unconfirmed(value))


class ReleaseChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = NativeFixture()
        self.resident = Resident(self.bridge, self.temp.name)
        self.resident.start()
        self.q = QueueClient(self.temp.name)
        self.dog = Watchdog(self.q, clock=lambda: 100.0)
        self.dog.latest = copy.deepcopy(self.bridge.observed)
        self.dog.observed_at = 100.0
        self.dog.next_observe = float('inf')
        self.gateway = RealGateway(self.dog)
        self.nav = Navigator(self.gateway, slice_size=2, checkpoint=Path(self.temp.name) / 'cursor.json')
        self.nav.data.update(target=list(GOAL), gateway_session=self.dog.session_id, observation_epoch=0)
    def tearDown(self):
        if self.resident.lock: self.resident.lock.close()
        self.temp.cleanup()
    def pump(self, count=1):
        for _ in range(count):
            if self.resident.active: self.resident.active.wake_at = 0
            self.resident.tick()
            self.dog.tick()
    def posts(self):
        return [c for c in self.bridge.calls if c[0] == 'POST' and c[1] == '/control/action']
    def start_path(self):
        result = self.nav.process_observation(copy.deepcopy(self.bridge.observed))
        self.assertEqual('pending', result['status'])
        self.pump()
        self.assertEqual(1, len(self.posts()))
        return result['request_id']
    def finish_native(self, released, status='failed', reason='input_release_unconfirmed'):
        self.bridge.action.update(status=status, reason=reason, result={})
        if released != 'missing': self.bridge.action['result']['input_release_confirmed'] = released
        raw = copy.deepcopy(self.bridge.action)
        self.pump(4)
        return raw
    def test_false_release_latches_all_layers_and_never_dispatches_a_second_action(self):
        request_id = self.start_path()
        raw = self.finish_native(False)
        queued = self.gateway.result(request_id)
        self.assertEqual('failed', queued['status'])
        self.assertEqual(raw, queued['action'])
        self.assertEqual('failed', queued['action']['status'])
        self.assertTrue(self.resident.paused)
        self.assertTrue(self.dog.input_release_latched)
        result = self.nav.tick(GOAL)
        self.assertEqual('blocked', result['status'])
        self.assertEqual('input_release_unconfirmed_requires_operator', result['reason'])
        self.assertEqual(request_id, self.nav.data['pending']['id'])
        for _ in range(12):
            self.pump()
            self.assertEqual('blocked', self.nav.tick(GOAL)['status'])
        restored = Navigator(self.gateway, checkpoint=Path(self.temp.name) / 'cursor.json')
        self.assertEqual('blocked', restored.tick(GOAL)['status'])
        # A watchdog state/phase refresh cannot bypass its dedicated latch.
        self.dog.armed = True
        self.dog.phase = 'watching'
        self.assertFalse(self.dog.submit_owner('new-intent', {'op': 'action', 'action': 'follow_path', 'waypoints': []}))
        with self.assertRaisesRegex(ValueError, 'input_release_unconfirmed'):
            self.dog.send('start_combat', {'op': 'combat_start'})
        self.q.submit({'op': 'action', 'action': 'follow_path', 'waypoints': [{'x': 3.5, 'y': 64, 'z': .5}]})
        self.pump(3)
        self.assertEqual(1, len(self.posts()))
        self.assertFalse(any(c[0] == 'POST' and c[1] in ('/control/action/cancel', '/control/release-all') for c in self.bridge.calls))
    def test_confirmed_release_allows_a_new_observed_legal_path(self):
        self.start_path()
        self.bridge.observed = observation((2, 64, 0), NODES)
        self.finish_native(True, status='succeeded', reason='path_reached')
        self.assertFalse(self.resident.paused)
        self.assertFalse(self.dog.input_release_latched)
        self.assertEqual('progress', self.nav.tick(GOAL)['status'])
        self.dog.latest = copy.deepcopy(self.bridge.observed)
        self.assertEqual('pending', self.nav.process_observation(copy.deepcopy(self.bridge.observed))['status'])
        self.pump()
        self.assertEqual(2, len(self.posts()))
    def test_old_missing_field_retains_original_failure_and_replan_behavior(self):
        self.start_path()
        self.finish_native('missing', reason='stuck')
        self.assertFalse(self.resident.paused)
        self.assertFalse(self.dog.input_release_latched)
        self.assertEqual('progress', self.nav.tick(GOAL)['status'])
        self.assertEqual('pending', self.nav.process_observation(copy.deepcopy(self.bridge.observed))['status'])
        self.pump()
        self.assertEqual(2, len(self.posts()))
    def test_pending_queue_is_discarded_when_terminal_release_is_unconfirmed(self):
        self.start_path()
        request_id = self.q.submit({'op': 'action', 'action': 'follow_path', 'waypoints': [{'x': 2, 'y': 64, 'z': 0}]})
        self.finish_native(False)
        self.assertEqual('cancelled', self.q.result(request_id)['status'])
        self.assertEqual(1, len(self.posts()))
    def test_resident_restart_does_not_erase_terminal_release_uncertainty(self):
        self.start_path()
        self.finish_native(False)
        self.resident.lock.close()
        self.resident = Resident(self.bridge, self.temp.name)
        self.resident.start()
        self.assertTrue(self.resident.paused)
        self.assertEqual('input_release_unconfirmed', self.resident.reason)
        self.assertEqual(1, len(self.posts()))


class Queue:
    def __init__(self): self.results = {}; self.commands = []
    def result(self, identity): return self.results.get(identity)
    def submit(self, command):
        identity = str(len(self.commands) + 1)
        self.commands.append(copy.deepcopy(command));return identity


class WatchdogPriorityTests(unittest.TestCase):
    def dog(self, cls=Watchdog):
        q = Queue();dog = cls(q, clock=lambda: 100.0)
        dog.latest = observation((0, 64, 0), NODES);dog.observed_at = 100.0;dog.next_observe = float('inf')
        return dog,q
    def test_environment_priority_cannot_skip_owner_release_failure(self):
        dog,q = self.dog();calls = []
        dog.owner = {'id': 'owner', 'request_id': 'queue'}
        q.results['queue'] = {'status': 'failed', 'action': receipt(False)}
        dog.environment.active = True
        dog.environment.tick = lambda current: calls.append('environment_tick')
        dog.tick()
        for _ in range(5): dog.tick()
        self.assertTrue(dog.input_release_latched)
        self.assertEqual([], calls);self.assertEqual([], q.commands)
        self.assertEqual('paused', dog.status()['state'])
    def test_internal_ranged_path_uses_the_same_latch_before_priority_work(self):
        dog,q = self.dog();dog.ranged_move = {'id': 'ranged', 'started': 100.0}
        q.results['ranged'] = {'status': 'failed', 'reason': 'stuck', 'action': receipt(False, reason='stuck')}
        dog.tick();self.assertTrue(dog.input_release_latched)
        for _ in range(5): dog.tick()
        self.assertEqual([], q.commands)
    def test_original_base_watchdog_also_latches_without_cleanup_retry(self):
        dog,q = self.dog(BaseWatchdog);dog.owner = {'id': 'owner', 'request_id': 'queue'}
        q.results['queue'] = {'status': 'failed', 'reason': 'input_release_unconfirmed'}
        dog.tick();self.assertTrue(dog.input_release_latched);self.assertEqual([], q.commands)
    def test_explicit_operator_stop_remains_available_after_latch(self):
        dog,q = self.dog();dog.latch_input_release('test');dog.stop();dog.tick()
        self.assertEqual([{'op': 'cancel'}], q.commands)
        q.results['1'] = {'status': 'succeeded', 'result': {'ok': True}}
        dog.tick();self.assertTrue(dog.stopped)
        dog.tick();self.assertEqual(1, len(q.commands))
    def test_confirmed_or_legacy_failed_owner_does_not_latch(self):
        for value in (True, 'missing'):
            dog,q = self.dog();dog.owner = {'id': 'owner', 'request_id': 'queue'}
            q.results['queue'] = {'status': 'failed', 'reason': 'stuck', 'action': receipt(value, reason='stuck')}
            dog.tick();self.assertFalse(dog.input_release_latched)
            self.assertTrue(dog.submit_owner('next', {'op': 'action', 'action': 'follow_path', 'waypoints': []}))
