"""Synthetic result identity tests; no network or game state is read."""
import copy
import tempfile
import unittest
from unittest.mock import patch
from test_controller import FakeBridge
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.transport import BridgeError

class EvidenceBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.mode = 'post_timeout'
        self.terminal = 'succeeded'
        self.corrupt = None
    def stamp(self):
        self.action['result'] = {'world_generation': 'world-A'}
    def request(self, method, path, body=None):
        if path == '/control/action':
            result = super().request(method, path, body)
            self.stamp()
            self.action.update(status=self.terminal, reason='path_reached' if self.terminal == 'succeeded' else 'deadline_exceeded')
            if self.mode == 'post_timeout':
                raise BridgeError('transport_failed', uncertain=True)
            return copy.deepcopy(self.action)
        if path == '/control/action/cancel':
            self.calls.append((method, path, copy.deepcopy(body)))
            result = copy.deepcopy(self.action)
            if self.corrupt:
                key, value = self.corrupt
                if key == 'world_generation': result['result'][key] = value
                else: result[key] = value
            return result
        if path == '/control/state?radius=8' and self.mode == 'observe_timeout':
            self.calls.append((method, path, body))
            raise BridgeError('transport_failed')
        result = super().request(method, path, body)
        if path == '/control/status': result['world'] = {'world_generation': 'world-A'}
        return result

class ReconciliationChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = EvidenceBridge()
        self.r = Resident(self.bridge, self.tmp.name)
        self.r.start()
        self.q = QueueClient(self.tmp.name)
    def tearDown(self):
        self.r.lock.close(); self.tmp.cleanup()
    def run_action(self):
        rid = self.q.submit({'op': 'action', 'action': 'follow_path', 'waypoints': [{'x': 0, 'y': 64, 'z': 1}]})
        self.r.tick()
        if self.r.active: self.r.active.wake_at = 0
        self.r.tick()
        return self.q.result(rid)
    def test_cancel_success_reconciles_action_but_not_recipe_or_transport(self):
        result = self.run_action()
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(result['action_outcome'], 'succeeded')
        self.assertEqual(result['resolved_action']['reason'], 'path_reached')
        self.assertEqual(result['original_error'], 'transport_failed')
        self.assertFalse(result['task_completed'])
        self.assertFalse(result['postcondition_observed'])
        self.assertTrue(self.r.paused)
        self.assertEqual(sum(p == '/control/action' for _, p, _ in self.bridge.calls), 1)
        self.assertEqual(sum(p == '/control/action/cancel' for _, p, _ in self.bridge.calls), 1)
    def test_cross_identity_or_nonterminal_cancel_does_not_claim_success(self):
        for key, value in [('action_id', 'other'), ('action_session', 'other'),
                           ('action', 'break_block'), ('world_generation', 'world-B'),
                           ('action_schema_version', 2), ('status', 'running')]:
            with self.subTest(key=key):
                self.r.paused = False; self.r.reason = None
                self.bridge.corrupt = (key, value)
                result = self.run_action()
                self.assertIsNone(result['resolved_action'])
                self.assertEqual(result['action_outcome'], 'unresolved')
    def test_failed_and_cancelled_terminal_are_not_promoted_or_replayed(self):
        for status in ('failed', 'cancelled'):
            self.r.paused = False; self.r.reason = None
            self.bridge.terminal = status
            before = len(self.bridge.calls)
            result = self.run_action()
            self.assertEqual(result['action_outcome'], status)
            self.assertFalse(result['task_completed'])
            self.assertEqual(sum(p == '/control/action' for _, p, _ in self.bridge.calls[before:]), 1)
    def test_postcondition_read_failure_preserves_completed_action(self):
        self.bridge.mode = 'observe_timeout'
        result = self.run_action()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['action_outcome'], 'succeeded')
        self.assertEqual(result['original_error'], 'transport_failed')
        self.assertFalse(result['task_completed'])
        self.assertFalse(any(p == '/control/action/cancel' for _, p, _ in self.bridge.calls))
    def test_no_known_launch_world_never_resolves_terminal(self):
        self.r.bridge_identity['action_session'] = 'test-session'
        original = self.bridge.request
        def without_world(m, p, b=None):
            result = original(m, p, b)
            if p == '/control/status': result.pop('world', None)
            return result
        self.bridge.request = without_world
        self.assertIsNone(self.run_action()['resolved_action'])

    def test_next_rejected_step_never_borrows_previous_success(self):
        self.bridge.mode = 'success'
        original = self.bridge.request
        posts = [0]
        def reject_second(method, path, body=None):
            if path == '/control/action':
                posts[0] += 1
                if posts[0] == 2:
                    raise BridgeError('action_world_changed', status=409)
            return original(method,path,body)
        self.bridge.request = reject_second
        def recipe(*args):
            yield {'step':'action','body':{'action':'follow_path','waypoints':[]}}
            yield {'step':'action','body':{'action':'follow_path','waypoints':[]}}
        with patch('resident_controller.controller.make_task', side_effect=recipe):
            result = self.run_action()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['action_step'], 2)
        self.assertIsNone(result['resolved_action'])
        self.assertEqual(result['action_outcome'], 'unresolved')

    def test_explicit_callers_world_or_session_are_never_rebased_to_current(self):
        for field, value in (('expected_world_generation','world-B'), ('expected_action_session','other-session')):
            with self.subTest(field=field):
                before = len(self.bridge.calls)
                rid = self.q.submit({'op':'action','action':'follow_path','waypoints':[],field:value})
                self.r.tick()
                result = self.q.result(rid)
                self.assertEqual(result['status'],'failed')
                self.assertFalse(any(m=='POST' for m,_,_ in self.bridge.calls[before:]))

    def test_matching_explicit_guard_is_preserved(self):
        rid = self.q.submit({'op':'action','action':'follow_path','waypoints':[],
                             'expected_world_generation':'world-A','expected_action_session':'test-session'})
        self.r.tick()
        body = next(b for m,p,b in self.bridge.calls if p=='/control/action')
        self.assertEqual(body['expected_world_generation'],'world-A')
        self.assertEqual(body['expected_action_session'],'test-session')

if __name__ == '__main__': unittest.main()
