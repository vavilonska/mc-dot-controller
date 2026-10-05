import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from combat_controller.bridge import (BridgeError, ConnectionConfig, HttpTransport, MineClientBridge,
                                      terrain_check)
from combat_controller.fake import FakeClock

PROTOCOL = {'ok': True, 'protocol': 'mineclient-bridge', 'schema_version': 2}
IDENTITY = ('test-run', 123, 'test-player', 'minecraft:overworld')


def fixtures():
    world = {'dimension': 'minecraft:overworld', 'game_time': 100, 'world_generation': 'world-a'}
    status = dict(PROTOCOL, process_id=123, run_id='test-run', in_world=True, bridge_running=True,
                  world=copy.deepcopy(world), player={'uuid': 'test-player'},
                  screen={'present': False}, held_mappings=[],
                  mouse={'grabbed': True, 'left_pressed': False, 'right_pressed': False,
                         'middle_pressed': False, 'held_world_buttons': []})
    player = {'uuid': 'test-player', 'dimension': 'minecraft:overworld', 'x': 0.0, 'y': 64.0, 'z': 0.0,
              'yaw': 0.0, 'pitch': 0.0, 'health': 20.0, 'food': 20, 'air': 300, 'max_air': 300,
              'on_ground': True, 'gamemode': 'survival', 'velocity': {'x': 0.0, 'y': 0.0, 'z': 0.0},
              'selected_slot': 0, 'inventory': [{'slot': 0, 'empty': False, 'id': 'minecraft:iron_sword'}]}
    state = dict(PROTOCOL, world=copy.deepcopy(world), player=player,
                 nearby={'entities': [{'uuid': 'test-zombie', 'type': 'minecraft:zombie', 'x': 0, 'y': 64, 'z': 2,
                                       'health': 20, 'alive': True}], 'returned': 1, 'truncated': False},
                 crosshair={'type': 'entity', 'uuid': 'test-zombie', 'entity_type': 'minecraft:zombie',
                            'location': {'x': 0, 'y': 64.9, 'z': 2}, 'distance': 4.81})
    cells = []
    for y in range(62, 67):
        for z in range(-1, 2):
            for x in range(-1, 2):
                floor = y <= 63
                cell = {'x': x, 'y': y, 'z': z, 'status': 'loaded', 'known': True,
                        'id': 'minecraft:stone' if floor else 'minecraft:air',
                        'collision_known': True, 'collision_empty': not floor, 'full_top_support': floor,
                        'hazards': [], 'hazards_exhaustive': False, 'fluid': 'minecraft:empty',
                        'properties_truncated': False, 'id_truncated': False, 'fluid_truncated': False}
                if floor:
                    cell['collision_bounds'] = [0., 0., 0., 1., 1., 1.]
                cells.append(cell)
    terrain = dict(PROTOCOL, terrain_schema_version=1, world_generation='world-a',
                   dimension='minecraft:overworld', game_time=100, complete=True, next_cursor=None,
                   returned=45, total_cells=45, origin={'x': 0, 'y': 64, 'z': 0}, cells=cells)
    return status, terrain, state


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if not self.replies:
            raise AssertionError('unexpected transport call')
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return copy.deepcopy(reply)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.status, self.terrain, self.state = fixtures()
        self.clock = FakeClock()

    def adapter(self, before=None, after=None):
        transport = FakeTransport([before or self.status, self.terrain, self.state, after or self.status])
        return MineClientBridge(transport, IDENTITY, self.clock), transport

    def test_exact_schema_decodes_and_distance_is_not_used_as_meters(self):
        bridge, transport = self.adapter()
        result = bridge.observe()
        self.assertTrue(result.terrain_safe)
        self.assertEqual('test-zombie', result.crosshair_uuid)
        self.assertAlmostEqual(2.19317121994613, result.position.distance(result.crosshair_location))
        self.assertEqual(4, len(transport.calls))

    def test_wrong_expected_process_blocks_before_other_reads(self):
        self.status['process_id'] = 124
        bridge, transport = self.adapter()
        with self.assertRaisesRegex(BridgeError, 'unexpected_session'):
            bridge.observe()
        self.assertEqual(1, len(transport.calls))

    def test_generation_changes_inside_observation(self):
        after = copy.deepcopy(self.status)
        after['world']['world_generation'] = 'world-b'
        bridge, _ = self.adapter(after=after)
        with self.assertRaisesRegex(BridgeError, 'world_generation_unknown_or_changed'):
            bridge.observe()

    def test_base_unextended_state_rejected(self):
        self.state['world'].pop('world_generation')
        bridge, _ = self.adapter()
        with self.assertRaisesRegex(BridgeError, 'world_generation_unknown_or_changed'):
            bridge.observe()

    def test_world_transition_between_requests(self):
        after = copy.deepcopy(self.status)
        after['world']['dimension'] = 'minecraft:the_nether'
        bridge, _ = self.adapter(after=after)
        with self.assertRaisesRegex(BridgeError, 'session_changed'):
            bridge.observe()

    def test_state_player_identity_mismatch(self):
        self.state['player']['uuid'] = 'other-player'
        bridge, _ = self.adapter()
        with self.assertRaisesRegex(BridgeError, 'state_identity_mismatch'):
            bridge.observe()

    def test_slow_observation_tick_drift_rejected(self):
        after = copy.deepcopy(self.status)
        after['world']['game_time'] = 105
        bridge, _ = self.adapter(after=after)
        with self.assertRaisesRegex(BridgeError, 'inconsistent_observation_ticks'):
            bridge.observe()

    def test_screen_open_after_snapshot_is_caught(self):
        after = copy.deepcopy(self.status)
        after['screen']['present'] = True
        bridge, _ = self.adapter(after=after)
        self.assertTrue(bridge.observe().screen_open)

    def test_physical_held_mouse_is_caught(self):
        self.status['mouse']['left_pressed'] = True
        bridge, _ = self.adapter()
        self.assertTrue(bridge.observe().held_inputs)

    def test_missing_required_scalar_rejected(self):
        self.state['player']['food'] = '20'
        bridge, _ = self.adapter()
        with self.assertRaisesRegex(BridgeError, 'invalid_integer'):
            bridge.observe()

    def test_nan_position_rejected(self):
        self.state['player']['x'] = float('nan')
        bridge, _ = self.adapter()
        with self.assertRaisesRegex(BridgeError, 'invalid_number'):
            bridge.observe()

    def test_wrong_protocol_rejected(self):
        self.status['schema_version'] = 99
        bridge, _ = self.adapter()
        with self.assertRaisesRegex(BridgeError, 'unsupported_protocol'):
            bridge.observe()

    def test_duplicate_selected_slot_rejected(self):
        self.state['player']['inventory'] *= 2
        bridge, _ = self.adapter()
        with self.assertRaisesRegex(BridgeError, 'missing_selected_item'):
            bridge.observe()

    def test_attack_only_exact_attack_click(self):
        transport = FakeTransport([{'ok': True, 'mapping_down': False,
            'mod_input_event': {'probe_installed': True, 'event_fired': True, 'event_cancelled_by_mod': False}}])
        bridge = MineClientBridge(transport, IDENTITY, self.clock)
        bridge.attack_click()
        self.assertEqual([('POST', '/control/key', {'mapping': 'key.attack', 'action': 'click', 'exact': True})], transport.calls)

    def test_cancelled_attack_halts(self):
        transport = FakeTransport([{'ok': True, 'mapping_down': False,
            'mod_input_event': {'probe_installed': True, 'event_fired': True, 'event_cancelled_by_mod': True}}])
        with self.assertRaisesRegex(BridgeError, 'attack_delivery_unconfirmed_or_cancelled'):
            MineClientBridge(transport, IDENTITY).attack_click()

    def test_unconfirmed_release_halts(self):
        transport = FakeTransport([{'ok': True, 'mapping_down': True}])
        with self.assertRaisesRegex(BridgeError, 'attack_release_unconfirmed'):
            MineClientBridge(transport, IDENTITY).attack_click()

    def test_cleanup_reads_back_input_state(self):
        transport = FakeTransport([{'ok': True, 'released': True}, self.status])
        self.assertTrue(MineClientBridge(transport, IDENTITY).release_all())
        self.assertEqual(('POST', '/control/release-all', {}), transport.calls[0])

    def test_cleanup_does_not_claim_clear_if_mouse_held(self):
        self.status['mouse']['left_pressed'] = True
        transport = FakeTransport([{'ok': True, 'released': True}, self.status])
        self.assertFalse(MineClientBridge(transport, IDENTITY).release_all())


class TerrainTests(unittest.TestCase):
    def setUp(self):
        _, self.terrain, self.state = fixtures()

    def floor(self):
        return next(c for c in self.terrain['cells'] if c['x'] == 0 and c['y'] == 63 and c['z'] == 0)

    def test_flat_known_vanilla_accepted(self):
        self.assertEqual((True, 'flat_vanilla_test_area'), terrain_check(self.terrain, self.state))

    def test_unknown_and_incomplete_data_fail_closed(self):
        modifications = [dict(complete=False), dict(returned=44), dict(next_cursor='cursor'),
                         dict(world_generation='other'), dict(game_time=90), dict(terrain_schema_version=9)]
        for changes in modifications:
            with self.subTest(changes=changes):
                self.assertFalse(terrain_check(dict(self.terrain, **changes), self.state)[0])

    def test_lava_water_fire_powder_snow_hazards_rejected(self):
        for hazard in ('lava', 'water', 'contact_damage', 'powder_snow', 'slowdown'):
            with self.subTest(hazard=hazard):
                self.floor()['hazards'] = [hazard]
                self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_unloaded_cell_rejected(self):
        self.floor().update(status='unloaded', known=False)
        self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_unknown_collision_rejected(self):
        self.floor()['collision_known'] = False
        self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_truncated_identifiers_rejected(self):
        for key in ('id_truncated', 'fluid_truncated', 'properties_truncated'):
            with self.subTest(key=key):
                _, self.terrain, self.state = fixtures()
                self.floor()[key] = True
                self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_modded_block_not_assumed_safe(self):
        self.floor()['id'] = 'mod:looks_like_stone'
        self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_partial_floor_and_pit_rejected(self):
        for changes in ({'full_top_support': False}, {'collision_empty': True},
                        {'collision_bounds': [0, 0, 0, 1, 0.5, 1]}, {'id': 'minecraft:air'}):
            with self.subTest(changes=changes):
                _, self.terrain, self.state = fixtures()
                self.floor().update(changes)
                self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_obstruction_rejected(self):
        self.terrain['cells'][-1]['id'] = 'minecraft:stone'
        self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_duplicate_or_missing_coordinate_rejected(self):
        self.terrain['cells'][-1] = self.terrain['cells'][0]
        self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_wrong_origin_rejected(self):
        self.terrain['origin']['x'] = 1
        self.assertFalse(terrain_check(self.terrain, self.state)[0])

    def test_slab_height_rejected(self):
        self.state['player']['y'] = 64.5
        self.assertFalse(terrain_check(self.terrain, self.state)[0])


class TransportTests(unittest.TestCase):
    def config(self, **changes):
        return ConnectionConfig(**dict(dict(token='offline-fake-token', expected_identity=IDENTITY), **changes))

    def test_remote_urls_credentials_paths_and_redirect_destinations_rejected(self):
        urls = ['http://example.com:38121', 'https://127.0.0.1:38121', 'http://localhost:38121',
                'http://user@127.0.0.1:38121', 'http://127.0.0.1:38121/else',
                'http://127.0.0.1:38121?token=x', 'http://127.0.0.1']
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.config(base_url=url)

    def test_token_not_in_repr(self):
        self.assertNotIn('offline-fake-token', repr(self.config()))

    def test_control_char_token_rejected(self):
        with self.assertRaises(ValueError):
            self.config(token='x\r\nInjected: yes')

    def test_enable_requires_expected_identity(self):
        with self.assertRaises(ValueError):
            self.config(enabled=True, expected_identity=None)

    def test_disabled_write_never_opens_socket(self):
        with patch('http.client.HTTPConnection') as connection, self.assertRaisesRegex(BridgeError, 'adapter_disabled'):
            HttpTransport(self.config()).request('POST', '/control/release-all', {})
        connection.assert_not_called()

    def test_disallowed_commands_and_persistent_input_never_open_socket(self):
        transport = HttpTransport(self.config(enabled=True))
        calls = [('POST', '/control/command', {'command': 'say no'}),
                 ('POST', '/control/key', {'mapping': 'key.attack', 'action': 'down', 'exact': True}),
                 ('POST', '/control/key', {'mapping': 'key.forward', 'action': 'click', 'exact': True}),
                 ('POST', '/control/mouse', {'action': 'click', 'button': 0}),
                 ('GET', '/control/state?radius=32', None),
                 ('POST', '/control/look', {'yaw': float('nan'), 'pitch': 0, 'relative': False})]
        with patch('http.client.HTTPConnection') as connection:
            for call in calls:
                with self.subTest(call=call), self.assertRaises(BridgeError):
                    transport.request(*call)
            connection.assert_not_called()

    def test_enabled_config_still_cannot_send_live_input_in_stage_one(self):
        transport = HttpTransport(self.config(enabled=True))
        calls = [('/control/look', {'yaw': 1, 'pitch': 2, 'relative': False}),
                 ('/control/key', {'mapping': 'key.attack', 'action': 'click', 'exact': True}),
                 ('/control/release-all', {})]
        with patch('http.client.HTTPConnection') as constructor:
            for path, body in calls:
                with self.subTest(path=path), self.assertRaisesRegex(BridgeError, 'live_input_requires_guarded_bridge_endpoint'):
                    transport.request('POST', path, body)
            constructor.assert_not_called()

    def test_http_timeout_headers_and_read_wire_schema_with_no_real_socket(self):
        with patch('http.client.HTTPConnection') as constructor:
            conn = constructor.return_value
            response = conn.getresponse.return_value
            response.status = 200
            response.getheader.return_value = 'application/json; charset=utf-8'
            response.read.return_value = b'{"ok":true}'
            transport = HttpTransport(self.config())
            transport.request('GET', '/control/status')
            constructor.assert_called_once_with('127.0.0.1', 38121, timeout=0.4)
            args, kwargs = conn.request.call_args
            self.assertEqual(('GET', '/control/status'), args)
            self.assertEqual('Bearer offline-fake-token', kwargs['headers']['Authorization'])
            self.assertIsNone(kwargs['body'])
            conn.close.assert_called_once()

    def test_total_deadline_interrupts_blocked_mock_read(self):
        with patch('http.client.HTTPConnection') as ctor:
            conn = ctor.return_value
            response = conn.getresponse.return_value
            response.status = 200
            response.getheader.return_value = 'application/json'
            interrupted = threading.Event()
            conn.sock.shutdown.side_effect = lambda *_: interrupted.set()
            def slow_read(*_):
                if interrupted.wait(1):
                    raise OSError('mock socket shut down by request deadline')
                raise AssertionError('deadline did not interrupt read')
            response.read.side_effect = slow_read
            started = time.monotonic()
            with self.assertRaises(BridgeError):
                HttpTransport(self.config(timeout=0.05)).request('GET', '/control/status')
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(interrupted.is_set())
            conn.sock.shutdown.assert_called_once()

    def test_http_errors_redirects_oversized_json_and_nonfinite_rejected_without_retry(self):
        cases = [(302, b'{"ok":true}'), (401, b'{"token":"secret"}'), (200, b'x' * (256*1024+1)),
                 (200, b'{"ok":true,"yaw":NaN}'), (200, b'[]')]
        for status, raw in cases:
            with self.subTest(status=status, length=len(raw)), patch('http.client.HTTPConnection') as ctor:
                response = ctor.return_value.getresponse.return_value
                response.status = status
                response.getheader.return_value = 'application/json'
                response.read.return_value = raw
                with self.assertRaises(BridgeError) as caught:
                    HttpTransport(self.config()).request('GET', '/control/status')
                self.assertNotIn('secret', str(caught.exception))
                self.assertEqual(1, ctor.call_count)
                ctor.return_value.close.assert_called_once()

    def test_config_only_explicit_private_file_no_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'explicit.json'
            path.write_text(json.dumps({'token': 'offline-fake-token', 'enabled': False}))
            path.chmod(0o600)
            self.assertFalse(ConnectionConfig.from_file(path).enabled)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                ConnectionConfig.from_file(path)

    def test_config_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target.json'
            target.write_text('{"token":"offline-fake-token"}')
            target.chmod(0o600)
            link = Path(directory) / 'link.json'
            link.symlink_to(target)
            with self.assertRaises(OSError):
                ConnectionConfig.from_file(link)

    def test_boolean_and_infinite_timeout_rejected(self):
        for value in (True, float('inf'), 9):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.config(timeout=value)


if __name__ == '__main__':
    unittest.main()
