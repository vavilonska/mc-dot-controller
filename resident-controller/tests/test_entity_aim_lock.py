"""Offline geometry and fake-protocol checks. Never opens a socket or game."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from resident_controller.controller import Resident
from resident_controller.entity_aim_lock import EntityAimLock, angles_to_center, view_changed
from resident_controller.ipc import QueueClient
from resident_controller.transport import BridgeError
from test_controller import FakeBridge

PLAYER = '11111111-1111-4111-8111-111111111111'
TARGET = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'


def state():
    return {'aim_view_guard_schema_version': 1, 'screen_open': False, 'paused': False,
            'client_action': {'action_session': 'test-session', 'status': 'idle'},
            'world': {'world_generation': 'world-one', 'game_time': 100},
            'player': {'uuid': PLAYER, 'yaw': 0, 'pitch': 0, 'alive': True, 'health': 20,
                       'eye_position': {'x': 0, 'y': 65.62, 'z': 0}},
            'crosshair': {'type': 'entity', 'uuid': TARGET},
            'nearby': {'truncated': False, 'entities': [
                {'uuid': TARGET, 'entity_id': 4, 'alive': True, 'health': 10,
                 'bounding_box': {'min': {'x': 1, 'y': 64, 'z': 3},
                                  'max': {'x': 3, 'y': 66, 'z': 5}}}]}}


class AimGeometryChecks(unittest.TestCase):
    def test_exact_aabb_center_from_actual_eye(self):
        observation = state()
        yaw, pitch, center = angles_to_center(observation['player'], observation['nearby']['entities'][0])
        self.assertEqual(center, {'x': 2, 'y': 65, 'z': 4})
        self.assertAlmostEqual(yaw, math.degrees(math.atan2(-2, 4)))
        self.assertAlmostEqual(pitch, -math.degrees(math.atan2(-0.62, math.sqrt(20))))
    def test_vertical_target_preserves_yaw(self):
        observation = state()
        observation['player']['eye_position'] = {'x': 2, 'y': 64, 'z': 4}
        observation['player']['yaw'] = 35
        yaw, pitch, _ = angles_to_center(observation['player'], observation['nearby']['entities'][0])
        self.assertEqual((yaw, pitch), (35, -90))
    def test_wrap_does_not_look_like_manual_turn(self):
        self.assertFalse(view_changed((-180, 0), (180, 0)))
        self.assertFalse(view_changed((360, 0), (0, 0)))
        self.assertTrue(view_changed((0.1, 0), (0, 0)))
    def test_rejects_nonfinite_or_inverted_bounds(self):
        for value in (math.inf, math.nan, True):
            observation = state()
            observation['nearby']['entities'][0]['bounding_box']['min']['x'] = value
            with self.assertRaises(ValueError):
                angles_to_center(observation['player'], observation['nearby']['entities'][0])
        observation = state()
        observation['nearby']['entities'][0]['bounding_box']['min']['x'] = 4
        with self.assertRaisesRegex(ValueError, 'invalid_entity_bounding_box'):
            angles_to_center(observation['player'], observation['nearby']['entities'][0])
    def test_explicit_uuid_or_entity_crosshair_only(self):
        observation = state()
        observation['crosshair'] = {'type': 'miss'}
        aim = EntityAimLock()
        with self.assertRaisesRegex(ValueError, 'requires_entity'):
            aim.start({}, observation, 'test-session')
        aim.start({'target_uuid': TARGET}, observation, 'test-session')
        self.assertEqual(aim.target_uuid, TARGET)


class AimBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.state = state()
        self.held = set()
        self.look_error = None
        self.manual_race = False
    def request(self, method, path, body=None):
        if path.startswith('/control/state?'):
            self.calls.append((method, path, copy.deepcopy(body)))
            return copy.deepcopy(self.state)
        if method == 'POST' and path == '/control/look':
            self.calls.append((method, path, copy.deepcopy(body)))
            if self.look_error:
                raise self.look_error
            if body.get('guard'):
                if self.manual_race:
                    self.state['player']['yaw'] += 1
                expected = body['guard']['expected_yaw'], body['guard']['expected_pitch']
                actual = self.state['player']['yaw'], self.state['player']['pitch']
                if view_changed(actual, expected):
                    raise BridgeError('manual_view_changed', status=409)
            yaw, pitch = body['yaw'], body['pitch']
            if body.get('relative'):
                yaw += self.state['player']['yaw']
                pitch += self.state['player']['pitch']
            self.state['player'].update(yaw=yaw, pitch=pitch)
            return {'ok': True, 'yaw': yaw, 'pitch': pitch, 'aim_view_guard_schema_version': 1}
        if method == 'POST' and path == '/control/key':
            if body['action'] == 'down':
                self.held.add(body['mapping'])
            elif body['action'] == 'up':
                self.held.discard(body['mapping'])
        if method == 'POST' and path == '/control/release-all':
            self.held.clear()
        return super().request(method, path, body)


class AimControllerChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = AimBridge()
        self.resident = Resident(self.bridge, self.tmp.name)
        self.resident.start()
        self.client = QueueClient(self.tmp.name)
    def tearDown(self):
        self.resident.lock.close()
        self.tmp.cleanup()
    def command(self, command):
        rid = self.client.submit(command)
        self.resident.tick()
        return self.client.result(rid)
    def start_aim(self):
        result = self.command({'op': 'aim_lock'})
        self.assertEqual(result['status'], 'succeeded', result)
        return result
    def update(self):
        self.resident.aim.next_update = 0
        self.resident.tick()
    def look_count(self):
        return sum(p == '/control/look' for _, p, _ in self.bridge.calls)
    def test_lock_tracks_moving_target_and_moving_player(self):
        self.start_aim()
        old = self.bridge.state['player']['yaw']
        box = self.bridge.state['nearby']['entities'][0]['bounding_box']
        box['min']['x'] += 1
        box['max']['x'] += 1
        self.bridge.state['player']['eye_position']['z'] += 1
        self.update()
        self.assertNotEqual(self.bridge.state['player']['yaw'], old)
        self.assertEqual(self.look_count(), 2)
        self.assertEqual(self.resident.aim.last_center, {'x': 3, 'y': 65, 'z': 4})
    def test_direct_movement_attack_stay_held_across_updates_and_unlock(self):
        self.start_aim()
        for key in ('key.forward', 'key.attack'):
            self.command({'op': 'direct', 'endpoint': 'key', 'body': {'mapping': key, 'action': 'down'}})
        self.update()
        self.assertTrue(self.resident.aim.active)
        self.command({'op': 'aim_unlock'})
        self.assertFalse(self.resident.aim.active)
        self.assertEqual(self.bridge.held, {'key.forward', 'key.attack'})
        self.assertFalse(any(p == '/control/release-all' for _, p, _ in self.bridge.calls))
    def test_manual_direct_look_takes_over_once(self):
        self.start_aim()
        self.command({'op': 'direct', 'endpoint': 'look', 'body': {'yaw': 5, 'pitch': 3, 'relative': True}})
        self.update()
        self.assertFalse(self.resident.aim.active)
        self.assertEqual(self.resident.aim.reason, 'manual_look')
        self.assertEqual(self.look_count(), 2)
    def test_observed_manual_turn_releases_without_a_write(self):
        self.start_aim()
        self.bridge.state['player']['yaw'] += 2
        self.update()
        self.assertEqual(self.resident.aim.reason, 'manual_view_changed')
        self.assertEqual(self.look_count(), 1)
    def test_manual_turn_between_read_and_write_is_not_overwritten(self):
        self.start_aim()
        self.bridge.manual_race = True
        old = self.bridge.state['player']['yaw']
        self.update()
        self.assertEqual(self.resident.aim.reason, 'manual_view_changed')
        self.assertEqual(self.bridge.state['player']['yaw'], old + 1)
        self.update()
        self.assertEqual(self.look_count(), 2)  # One rejected dispatch, never retried.
    def test_target_missing_never_retargets_nearest(self):
        self.start_aim()
        self.bridge.state['nearby']['entities'][0]['uuid'] = OTHER
        self.bridge.state['nearby']['truncated'] = True
        self.update()
        self.assertEqual(self.resident.aim.reason, 'target_missing')
        self.assertEqual(self.look_count(), 1)
    def test_target_death_preserves_direct_attack_key(self):
        self.start_aim()
        self.command({'op': 'direct', 'endpoint': 'key', 'body': {'mapping': 'key.attack', 'action': 'down'}})
        self.bridge.state['nearby']['entities'][0]['alive'] = False
        self.update()
        self.assertEqual(self.resident.aim.reason, 'target_dead')
        self.assertEqual(self.bridge.held, {'key.attack'})
    def test_context_changes_release(self):
        cases = [('screen_opened', ('screen_open',), True), ('game_paused', ('paused',), True),
                 ('world_changed', ('world', 'world_generation'), 'new-world'),
                 ('player_changed', ('player', 'uuid'), OTHER),
                 ('player_unavailable', ('player', 'alive'), False),
                 ('bridge_session_changed', ('client_action', 'action_session'), 'other-session'),
                 ('action_owns_view', ('client_action', 'status'), 'running')]
        for reason, path, value in cases:
            with self.subTest(reason=reason):
                self.bridge.state = state()
                self.start_aim()
                target = self.bridge.state
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.update()
                self.assertFalse(self.resident.aim.active)
                self.assertEqual(self.resident.aim.reason, reason)
    def test_uncertain_write_pauses_without_retry(self):
        self.start_aim()
        self.bridge.look_error = BridgeError('transport_failed', uncertain=True)
        self.update()
        self.update()
        self.assertTrue(self.resident.paused)
        self.assertFalse(self.resident.aim.active)
        self.assertEqual(self.look_count(), 2)
    def test_malformed_write_acknowledgement_is_uncertain_not_failed(self):
        real_request = self.bridge.request
        def request(method, path, body=None):
            result = real_request(method, path, body)
            if method == 'POST' and path == '/control/look':
                result.pop('aim_view_guard_schema_version')
            return result
        with patch.object(self.bridge, 'request', side_effect=request):
            result = self.command({'op': 'aim_lock'})
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(result['reason'], 'aim_update_response_invalid')
        self.assertTrue(self.resident.paused)
        self.assertFalse(self.resident.aim.active)
        self.update()
        self.assertEqual(self.look_count(), 1)
    def test_old_mod_is_rejected_before_first_write(self):
        del self.bridge.state['aim_view_guard_schema_version']
        result = self.command({'op': 'aim_lock'})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'aim_view_guard_mod_required')
        self.assertEqual(self.look_count(), 0)
    def test_cancel_releases_both_lock_and_held_keys(self):
        self.start_aim()
        self.bridge.held.add('key.forward')
        self.command({'op': 'cancel'})
        self.assertFalse(self.resident.aim.active)
        self.assertEqual(self.bridge.held, set())
    def test_semantic_task_takes_view_without_competing_look(self):
        self.start_aim()
        self.command({'op': 'action', 'action': 'break_block', 'target': {'x': 2, 'y': 64, 'z': 2}})
        self.assertFalse(self.resident.aim.active)
        self.assertEqual(self.resident.aim.reason, 'semantic_task_owns_view')
        self.assertEqual(self.look_count(), 1)
    def test_active_task_blocks_lock_without_cancel(self):
        self.command({'op': 'action', 'action': 'break_block', 'target': {'x': 2, 'y': 64, 'z': 2}})
        result = self.command({'op': 'aim_lock'})
        self.assertEqual(result['reason'], 'action_owns_view_cancel_task_first')
        self.assertIsNotNone(self.resident.active)
        self.assertEqual(self.look_count(), 0)
    def test_radius_bounds_reject_without_write(self):
        for radius in (0, 33, True, 1.5):
            with self.subTest(radius=radius):
                self.assertEqual(self.command({'op': 'aim_lock', 'radius': radius})['status'], 'failed')
        self.assertEqual(self.look_count(), 0)
    def test_stale_state_is_not_written(self):
        self.start_aim()
        count = self.look_count()
        with patch('resident_controller.controller.time.monotonic', return_value=100):
            with self.assertRaisesRegex(ValueError, 'stale_aim_observation'):
                self.resident.apply_aim(self.bridge.state, 99)
        self.assertEqual(self.look_count(), count)
    def test_session_exposes_aim_and_restart_does_not_restore_it(self):
        self.start_aim()
        self.assertTrue(self.client.session()['aim_lock']['active'])
        self.resident.lock.close()
        self.resident = Resident(self.bridge, self.tmp.name)
        self.resident.start()
        self.assertFalse(self.client.session()['aim_lock']['active'])
        self.assertEqual(self.look_count(), 1)


if __name__ == '__main__':
    unittest.main()
