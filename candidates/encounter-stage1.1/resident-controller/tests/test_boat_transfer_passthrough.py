"""Offline transfer wire checks. The fake bridge never connects to a game."""
import copy
import tempfile
import unittest

from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.tasks import basic
from resident_controller.transport import BridgeError

W = '00000000-0000-0000-0000-000000000001'
P = '00000000-0000-0000-0000-000000000002'
S = '00000000-0000-0000-0000-000000000003'
B = '00000000-0000-0000-0000-000000000004'


def command(action):
    return dict(op='action', action=action, boat_transfer_schema_version=1, timeout_ms=2000,
                expected_world_generation=W, expected_player_uuid=P, expected_action_session=S,
                expected_game_time=100, vehicle_uuid=B, vehicle_entity_id=7, vehicle_type='minecraft:boat')


class TransferBridge:
    base_url = 'http://127.0.0.1:1'  # Never opened.

    def __init__(self, uncertain=False):
        self.calls, self.uncertain = [], uncertain
        self.action = dict(ok=True, action_schema_version=1, action_session=S, status='idle', action_id=None)

    def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path == '/control/status':
            return dict(protocol='mineclient-bridge', schema_version=2, run_id='synthetic-run',
                        process_id=1, in_world=True, world={'world_generation': W}, client_action=copy.deepcopy(self.action))
        if path == '/control/action':
            self.action = dict(ok=True, action_schema_version=1, action_session=S,
                               action_id=body['action_id'], action=body['action'], status='running',
                               result={'world_generation': W})
            if self.uncertain:
                raise BridgeError('synthetic_lost_response', uncertain=True)
            return copy.deepcopy(self.action)
        if path == '/control/action/cancel':
            raise BridgeError('synthetic_cancel_unconfirmed', uncertain=True)
        if path.startswith('/control/action/status'):
            return copy.deepcopy(self.action)
        if path == '/control/state?radius=8':
            return dict(world={'world_generation': W}, player={'inventory': []})
        raise AssertionError((method, path, body))


class BoatTransferPassthroughTest(unittest.TestCase):
    def test_recipe_keeps_strict_body_and_only_one_action_step(self):
        for action in ('boat_mount', 'boat_dismount'):
            task = basic({**command(action), 'request_id': 'synthetic-request', 'action_id': 'ignored'})
            step = next(task)
            self.assertEqual(step, {'step': 'action', 'body': {k: v for k, v in command(action).items() if k != 'op'}})
            self.assertEqual(task.send({'status': 'succeeded'}), {'step': 'observe'})
            with self.assertRaises(StopIteration) as finished:
                task.send({'world': {'world_generation': W}})
            self.assertFalse(finished.exception.value['server_confirmed'])

    def test_resident_preserves_every_binding_and_budget(self):
        for action in ('boat_mount', 'boat_dismount'):
            with tempfile.TemporaryDirectory() as directory:
                bridge = TransferBridge()
                resident = Resident(bridge, directory)
                try:
                    resident.start()
                    client = QueueClient(directory)
                    client.submit(command(action))
                    resident.tick()
                    posts = [body for method, path, body in bridge.calls if method == 'POST' and path == '/control/action']
                    self.assertEqual(len(posts), 1)
                    body = dict(posts[0])
                    self.assertTrue(body.pop('action_id'))
                    self.assertEqual(body, {k: v for k, v in command(action).items() if k != 'op'})
                    self.assertIsNotNone(resident.active)
                finally:
                    if resident.lock:
                        resident.lock.close()

    def test_uncertain_transfer_stops_without_second_post(self):
        for action in ('boat_mount', 'boat_dismount'):
            with tempfile.TemporaryDirectory() as directory:
                bridge = TransferBridge(uncertain=True)
                resident = Resident(bridge, directory)
                try:
                    resident.start()
                    client = QueueClient(directory)
                    request_id = client.submit(command(action))
                    for _ in range(4):
                        resident.tick()
                    self.assertTrue(resident.paused)
                    self.assertEqual(client.result(request_id)['status'], 'uncertain')
                    self.assertEqual(sum(method == 'POST' and path == '/control/action'
                                         for method, path, _ in bridge.calls), 1)
                finally:
                    if resident.lock:
                        resident.lock.close()
