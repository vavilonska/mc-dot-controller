"""Offline scan protocol checks. No real sockets, credentials, game or queue."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from resident_controller.controller import Resident, Running
from resident_controller.ipc import QueueClient
from resident_controller.prospecting import (
    MAX_CACHE_BYTES, MAX_CACHED_SCANS, start_body, validate_scan)
from resident_controller.transport import Bridge, BridgeError
from test_controller import FakeBridge


WORLD = {'dimension': 'minecraft:overworld', 'world_generation': 'world-one'}


def scan(identifier='sample', status='running', **changes):
    return {'ok': True, 'scan_schema_version': 1, 'scan_id': identifier,
            'status': status, **WORLD, 'started_at_ms': 1000, 'observed_at_ms': 1100,
            'finished_at_ms': None if status == 'running' else 1100,
            'coverage': {'scanned_blocks': 12, 'unknown_chunks': 4},
            'results': {'ore_counts': {'minecraft:iron_ore': 2},
                        'ore_clusters': [{'block_id': 'minecraft:iron_ore', 'x': 1, 'y': 16, 'z': 2}],
                        'cherry_sites': []}, **changes}


class ScanBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.world = copy.deepcopy(WORLD)
        self.in_world = True
        self.scans = {}
        self.scan_error = None
        self.scan_override = None

    def request(self, method, path, body=None):
        if path.startswith('/control/scan'):
            self.calls.append((method, path, copy.deepcopy(body)))
            if self.scan_error:
                raise self.scan_error
            if self.scan_override is not None:
                return copy.deepcopy(self.scan_override)
            identifier = body['id'] if body else path.split('id=', 1)[1]
            if path == '/control/scan':
                self.scans.setdefault(identifier, scan(identifier, **self.world))
            elif path == '/control/scan/cancel':
                self.scans[identifier].update(status='cancelled', finished_at_ms=1200)
            return copy.deepcopy(self.scans[identifier])
        value = super().request(method, path, body)
        if path == '/control/status':
            value.update(world=copy.deepcopy(self.world), in_world=self.in_world)
        if path == '/control/state?radius=8':
            value['world'] = copy.deepcopy(self.world)
        return value


class ScanOptionsChecks(unittest.TestCase):
    def test_default_and_explicit_options(self):
        self.assertEqual(start_body({'op': 'scan_start', 'request_id': 'abc'}),
                         {'id': 'abc', 'mode': 'both', 'max_results': 64, 'sort': 'count'})
        bounds = {'min_x': -10, 'max_x': 10, 'min_z': 1, 'max_z': 3, 'min_y': -64}
        command = {'op': 'scan_start', 'id': 'a-b_9', 'mode': 'ores', 'bounds': bounds,
                   'ore_ids': ['minecraft:diamond_ore', 'example:deep/ore'], 'max_results': 256,
                   'request_id': 'mail', 'session_id': 'resident', 'submitted_at': 10}
        actual = start_body(command)
        self.assertEqual(set(actual), {'id', 'mode', 'bounds', 'ore_ids', 'max_results', 'sort'})
        self.assertEqual(actual['bounds'], bounds)
        bounds['min_x'] = 0
        self.assertEqual(actual['bounds']['min_x'], -10)

    def test_generic_modes_filters_and_sort_are_forwarded_without_presets(self):
        for mode in ('ores', 'cherry_sites', 'both', 'blocks', 'surface_sites'):
            options = {'id': 'custom', 'mode': mode, 'block_ids': ['minecraft:cherry_log'],
                       'biome_ids': ['minecraft:plains'], 'require_water': True,
                       'water_radius': 128, 'sort': 'distance', 'max_results': 256}
            self.assertEqual(start_body({'op': 'scan_start', **options}), options)
        self.assertEqual(start_body({'op': 'scan_start', 'id': 'zero',
                                     'require_water': False, 'water_radius': 0})['water_radius'], 0)
        self.assertFalse(start_body({'op': 'scan_start', 'id': 'false',
                                    'require_water': False})['require_water'])
        for sort in ('count', 'density', 'distance'):
            self.assertEqual(start_body({'op': 'scan_start', 'id': 'sorted', 'sort': sort})['sort'], sort)

    def test_biomes_mode_requires_biome_filter_and_rejects_block_filters(self):
        options = {'id': 'biome', 'mode': 'biomes', 'biome_ids': ['minecraft:plains'],
                   'require_water': True, 'water_radius': 16, 'sort': 'density', 'max_results': 32}
        self.assertEqual(start_body({'op': 'scan_start', **options}), options)
        for changes in ({'biome_ids': []}, {'biome_ids': None},
                        {'block_ids': ['minecraft:stone']}, {'ore_ids': ['minecraft:coal_ore']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                start_body({'op': 'scan_start', **options, **changes})
        with self.assertRaisesRegex(ValueError, 'biome_ids_required'):
            start_body({'op': 'scan_start', 'id': 'missing', 'mode': 'biomes'})

    def test_registry_id_lengths_and_nonempty_arrays_match_java(self):
        maximum = 'n' * 40 + ':' + 'p' * 100
        for key in ('block_ids', 'ore_ids', 'biome_ids'):
            self.assertEqual(start_body({'op': 'scan_start', 'id': 'max', key: [maximum]})[key], [maximum])
            for ids in ([], ['n' * 41 + ':x'], ['x:' + 'p' * 101], [':x'], ['x:']):
                with self.subTest(key=key, ids=ids), self.assertRaises(ValueError):
                    start_body({'op': 'scan_start', 'id': 'bad', key: ids})

    def test_bounds_match_java_limits(self):
        for bounds in (
            {'min_x': 0, 'max_x': 2048, 'min_z': 0, 'max_z': 0},
            {'min_x': 0, 'max_x': 0, 'min_z': 0, 'max_z': 2048},
            {'min_x': 0, 'max_x': 2047, 'min_z': 0, 'max_z': 2047},
            {'min_x': -30_000_001, 'max_x': -30_000_000, 'min_z': 0, 'max_z': 0},
            {'min_x': 0, 'max_x': 0, 'min_z': 0, 'max_z': 0, 'min_y': -1_000_001},
        ):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                start_body({'op': 'scan_start', 'id': 'too-big', 'bounds': bounds})
        bounds = {'min_x': -2048, 'max_x': -1, 'min_z': 0, 'max_z': 0,
                  'min_y': -1_000_000, 'max_y': 1_000_000}
        self.assertEqual(start_body({'op': 'scan_start', 'id': 'edge', 'bounds': bounds})['bounds'], bounds)

    def test_invalid_generic_filters_rejected_locally(self):
        for change in (
            {'block_ids': [], 'ore_ids': []}, {'block_ids': ['minecraft:Stone']},
            {'block_ids': ['minecraft:stone'] * 33}, {'block_ids': [False]},
            {'biome_ids': 'minecraft:plains'}, {'biome_ids': ['no_namespace']},
            {'biome_ids': [None]}, {'biome_ids': ['minecraft:plains'] * 33},
            {'require_water': 1}, {'require_water': 'true'}, {'require_water': None},
            {'water_radius': -1}, {'water_radius': 129}, {'water_radius': False},
            {'water_radius': 0.5}, {'water_radius': '32'}, {'sort': 'random'}, {'sort': []},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                start_body({'op': 'scan_start', 'id': 'valid', **change})

    def test_invalid_options_and_injection_ids(self):
        for change in (
            {'id': '../x'}, {'id': 'a&id=other'}, {'id': 'a' * 65}, {'id': ''}, {'id': 4},
            {'mode': 'explore'}, {'mode': []}, {'max_results': True}, {'max_results': 0},
            {'max_results': 257}, {'max_results': 1.2}, {'bounds': []},
            {'bounds': {'min_x': 0, 'max_x': 1}},
            {'bounds': {'min_x': 2, 'max_x': 1, 'min_z': 0, 'max_z': 1}},
            {'bounds': {'min_x': False, 'max_x': 1, 'min_z': 0, 'max_z': 1}},
            {'bounds': {'min_x': 0, 'max_x': 1, 'min_z': 0, 'max_z': 1, 'extra': 0}},
            {'ore_ids': 'minecraft:diamond_ore'}, {'ore_ids': ['minecraft:a'] * 33},
            {'ore_ids': [4]}, {'ore_ids': ['stone']}, {'ore_ids': ['minecraft:Stone']},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                start_body({'op': 'scan_start', 'id': 'valid', **change})

    def test_response_validation_is_versioned_bounded_and_world_stamped(self):
        for change in (
            {'scan_schema_version': True}, {'scan_schema_version': 2}, {'scan_id': 'wrong'},
            {'dimension': None}, {'world_generation': ''}, {'status': 'idle'},
            {'observed_at_ms': None}, {'started_at_ms': -1}, {'coverage': []},
            {'results': []}, {'results': {'ore_clusters': [{}] * 257}},
            {'results': {'cherry_sites': [4] * 257}}, {'results': {'block_clusters': [{}] * 257}},
            {'results': {'surface_sites': [{}] * 257}}, {'results': {'regions': [{}] * 257}},
            {'results': {'biome_clusters': [{}] * 257}},
            {'padding': 'a' * (256 * 1024)},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_scan(scan(**change), 'sample')
        self.assertEqual(validate_scan(scan(), 'sample')['scan_id'], 'sample')


class ProspectingChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = ScanBridge()
        self.resident = Resident(self.bridge, self.tmp.name)
        self.resident.start()
        self.client = QueueClient(self.tmp.name)

    def tearDown(self):
        self.resident.lock.close()
        self.tmp.cleanup()

    def command(self, command, request_id=None):
        request_id = self.client.submit(command, request_id)
        # Process explicit commands only: no unrelated combat/task advancement.
        self.resident.read_commands()
        return self.client.result(request_id)

    def test_start_returns_running_snapshot_without_poll_or_input(self):
        result = self.command({'op': 'scan_start'}, 'scan-default-id')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['result']['status'], 'running')
        self.assertEqual(result['scan_id'], 'scan-default-id')
        posts = [call for call in self.bridge.calls if call[0] == 'POST']
        self.assertEqual(posts, [('POST', '/control/scan',
                                 {'id': 'scan-default-id', 'mode': 'both', 'max_results': 64, 'sort': 'count'})])
        before = len(self.bridge.calls)
        self.resident.tick()
        self.resident.tick()
        self.assertEqual(len(self.bridge.calls), before)
        self.assertIsNone(self.resident.active)
        self.assertEqual(len(self.resident.pending), 0)

    def test_generic_region_metrics_and_registry_context_are_preserved(self):
        regions = [{'block_count': 23, 'density': 0.18, 'distance': 14.5,
                    'biome_id': 'minecraft:plains', 'water_distance': 3,
                    'bounds': {'min_x': 1, 'max_x': 16}}]
        self.bridge.scan_override = scan('custom', results={
            'block_counts': {'minecraft:cherry_log': 23},
            'block_clusters': regions, 'regions': regions})
        options = {'op': 'scan_start', 'id': 'custom', 'mode': 'blocks',
                   'block_ids': ['minecraft:cherry_log'], 'biome_ids': ['minecraft:plains'],
                   'require_water': True, 'water_radius': 10, 'sort': 'distance'}
        result = self.command(options)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['result']['results']['regions'], regions)
        self.assertEqual(self.client.scan_cache()['observations'][0]['results']['regions'], regions)
        posted = next(body for method, path, body in self.bridge.calls if path == '/control/scan')
        self.assertEqual(posted, {k: v for k, v in options.items() if k != 'op'} | {'max_results': 64})
        self.assertNotIn('ore_ids', posted)

    def test_status_reads_and_cancel_only_cancels_named_scan(self):
        self.command({'op': 'scan_start', 'id': 'one'})
        self.bridge.scans['one']['observed_at_ms'] = 1300
        first = self.command({'op': 'scan_status', 'id': 'one'})
        self.assertEqual(first['result']['observed_at_ms'], 1300)
        result = self.command({'op': 'scan_cancel', 'id': 'one'})
        self.assertEqual(result['result']['status'], 'cancelled')
        self.assertEqual([p for m, p, b in self.bridge.calls if m == 'POST'],
                         ['/control/scan', '/control/scan/cancel'])
        self.assertEqual(self.client.scan_cache()['observations'][0]['status'], 'cancelled')

    def test_accumulates_distinct_scans_preserving_original_observation_time(self):
        with patch('resident_controller.prospecting.time.time', return_value=99.0):
            self.command({'op': 'scan_start', 'id': 'before-moving'})
        self.command({'op': 'scan_start', 'id': 'after-moving', 'bounds':
                      {'min_x': 30, 'max_x': 40, 'min_z': 0, 'max_z': 10}})
        cached = self.client.scan_cache()
        self.assertTrue(cached['historical_observations_only'])
        self.assertEqual(cached['scan_count'], 2)
        self.assertEqual(cached['observations'][0]['observed_at_ms'], 1100)
        self.assertEqual(cached['observations'][0]['resident_received_at'], 99.0)
        self.assertEqual(cached['world_generation'], WORLD['world_generation'])
        self.assertEqual(cached['dimension'], WORLD['dimension'])

    def test_status_replaces_same_id_instead_of_duplicate_observations(self):
        self.command({'op': 'scan_start', 'id': 'one'})
        self.bridge.scans['one'].update(status='succeeded', observed_at_ms=1400, finished_at_ms=1400)
        self.command({'op': 'scan_status', 'id': 'one'})
        cached = self.client.scan_cache()
        self.assertEqual(cached['scan_count'], 1)
        self.assertEqual(cached['observations'][0]['status'], 'succeeded')

    def test_new_world_or_dimension_clears_old_observations(self):
        for world in ({**WORLD, 'dimension': 'minecraft:the_nether'},
                      {**WORLD, 'world_generation': 'world-two'}):
            self.bridge.world = copy.deepcopy(WORLD)
            self.command({'op': 'scan_start', 'id': 'old'})
            self.bridge.world = world
            result = self.command({'op': 'scan_status', 'id': 'old'})
            self.assertFalse(result['scan_cache']['result_retained'])
            self.assertEqual(result['result']['world_generation'], WORLD['world_generation'])
            self.assertEqual(self.client.scan_cache()['observations'], [])
            self.assertEqual(self.client.scan_cache()['dimension'], world['dimension'])
            self.assertEqual(self.client.scan_cache()['world_generation'], world['world_generation'])

    def test_no_world_clears_cache_but_can_read_old_terminal_status(self):
        self.command({'op': 'scan_start', 'id': 'one'})
        self.bridge.in_world = False
        self.bridge.scans['one'].update(status='failed', reason='world_changed')
        result = self.command({'op': 'scan_status', 'id': 'one'})
        self.assertEqual(result['result']['status'], 'failed')
        self.assertFalse(result['scan_cache']['result_retained'])
        self.assertIsNone(self.client.scan_cache()['world_generation'])
        self.assertEqual(self.client.scan_cache()['observations'], [])

    def test_ordinary_observe_also_invalidates_changed_world_cache(self):
        self.command({'op': 'scan_start', 'id': 'one'})
        self.bridge.world = {**WORLD, 'world_generation': 'world-two'}
        result = self.command({'op': 'observe'})
        self.assertEqual(result['result']['scan_cache']['scan_count'], 0)
        self.assertEqual(result['result']['scan_cache']['world_generation'], 'world-two')
        self.assertEqual(self.client.scan_cache()['observations'], [])

    def test_bridge_restart_clears_cache_before_rejecting_new_scan(self):
        self.command({'op': 'scan_start', 'id': 'one'})
        self.bridge.action['action_session'] = 'different-jvm'
        result = self.command({'op': 'scan_start', 'id': 'two'})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'bridge_restarted_owner_restart_controller')
        self.assertEqual(self.client.scan_cache()['observations'], [])
        self.assertEqual(sum(p == '/control/scan' for m, p, b in self.bridge.calls), 1)

    def test_restart_clears_disk_cache_and_never_restarts_a_scan(self):
        self.command({'op': 'scan_start', 'id': 'one'})
        old_session = self.client.scan_cache()['session_id']
        self.resident.lock.close()
        self.resident = Resident(self.bridge, self.tmp.name)
        self.resident.start()
        self.assertNotEqual(self.client.scan_cache()['session_id'], old_session)
        self.assertEqual(self.client.scan_cache()['observations'], [])
        self.assertEqual(sum(p == '/control/scan' for m, p, b in self.bridge.calls), 1)

    def test_duplicate_mailbox_request_never_reposts_scan(self):
        self.command({'op': 'scan_start', 'id': 'one'}, 'mail-one')
        self.command({'op': 'scan_start', 'id': 'one'}, 'mail-one')
        self.assertEqual(sum(p == '/control/scan' for m, p, b in self.bridge.calls), 1)

    def set_active_controls(self):
        self.resident.aim.active = True
        self.resident.combat.active = True
        self.resident.combat.held.add('key.forward')
        self.resident.active = Running({'request_id': 'existing-task'}, object(), action_id='existing-action')
        self.resident.pending.append({'request_id': 'existing-queued-task'})
        self.resident.paused = True
        self.resident.reason = 'existing-pause'

    def assert_active_controls(self):
        self.assertTrue(self.resident.aim.active)
        self.assertTrue(self.resident.combat.active)
        self.assertEqual(self.resident.combat.held, {'key.forward'})
        self.assertEqual(self.resident.active.action_id, 'existing-action')
        self.assertEqual(len(self.resident.pending), 1)
        self.assertTrue(self.resident.paused)
        self.assertEqual(self.resident.reason, 'existing-pause')
        self.assertFalse(any(m == 'POST' and not p.startswith('/control/scan') for m, p, b in self.bridge.calls))

    def test_scan_requests_leave_actions_aim_combat_and_pause_unchanged(self):
        self.set_active_controls()
        for command in ({'op': 'scan_start', 'id': 'one'}, {'op': 'scan_status', 'id': 'one'},
                        {'op': 'scan_cancel', 'id': 'one'}):
            self.assertEqual(self.command(command)['status'], 'succeeded')
            self.assert_active_controls()

    def test_uncertain_scan_start_and_cancel_never_interrupt_inputs_or_retry(self):
        self.set_active_controls()
        self.bridge.scan_error = BridgeError('transport_failed', uncertain=True)
        for op in ('scan_start', 'scan_cancel'):
            result = self.command({'op': op, 'id': 'unknown'})
            self.assertEqual(result['status'], 'uncertain')
            self.assertEqual(result['scan_id'], 'unknown')
            self.assert_active_controls()
        before = len(self.bridge.calls)
        self.resident.read_commands()
        self.assertEqual(len(self.bridge.calls), before)

    def test_bad_scan_ack_is_uncertain_but_bad_get_is_failed(self):
        self.set_active_controls()
        self.bridge.scan_override = scan('wrong')
        for op, expected in (('scan_start', 'uncertain'), ('scan_status', 'failed'), ('scan_cancel', 'uncertain')):
            result = self.command({'op': op, 'id': 'one'})
            self.assertEqual(result['status'], expected)
            self.assertEqual(result['reason'], 'invalid_scan_response')
            self.assert_active_controls()
        self.assertEqual(self.client.scan_cache()['observations'], [])

    def test_invalid_scan_options_fail_before_bridge_calls(self):
        for command in ({'op': 'scan_start', 'max_results': 999}, {'op': 'scan_status'},
                        {'op': 'scan_cancel', 'id': 'x&other=1'}):
            before = len(self.bridge.calls)
            self.assertEqual(self.command(command)['status'], 'failed')
            self.assertEqual(len(self.bridge.calls), before)

    def test_missing_mod_scan_route_is_clear_failure_without_fallback(self):
        self.bridge.scan_error = BridgeError('bridge_http_404', status=404)
        result = self.command({'op': 'scan_start', 'id': 'one'})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'bridge_http_404')
        self.assertFalse(self.resident.paused)
        self.assertEqual([p for m, p, b in self.bridge.calls if m == 'POST'], ['/control/scan'])

    def test_cache_is_count_bounded(self):
        for index in range(MAX_CACHED_SCANS + 3):
            self.resident.prospecting.record(scan(str(index)))
        cached = self.client.scan_cache()
        self.assertEqual(cached['scan_count'], MAX_CACHED_SCANS)
        self.assertEqual(cached['observations'][0]['scan_id'], '3')

    def test_cache_is_byte_bounded_and_does_not_alias_results(self):
        response = scan('one', padding='x' * (150 * 1024))
        self.resident.prospecting.record(response)
        response['results']['ore_counts'].clear()
        self.assertEqual(self.client.scan_cache()['observations'][0]['results']['ore_counts'],
                         {'minecraft:iron_ore': 2})
        for index in range(15):
            self.resident.prospecting.record(scan(str(index), padding='x' * (150 * 1024)))
        self.assertLessEqual((Path(self.tmp.name) / 'scan_cache.json').stat().st_size, MAX_CACHE_BYTES)
        self.assertLess(self.client.scan_cache()['scan_count'], MAX_CACHED_SCANS)


class ScanTransportChecks(unittest.TestCase):
    def test_scan_routes_share_existing_auth_and_listener(self):
        bridge = Bridge('http://127.0.0.1:12345', 'synthetic-token')
        with patch('http.client.HTTPConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = b'{"ok":true}'
            for method, path, body in (
                ('POST', '/control/scan', {'id': 'one'}),
                ('GET', '/control/scan/status?id=one', None),
                ('POST', '/control/scan/cancel', {'id': 'one'}),
            ):
                bridge.request(method, path, body)
                connection.assert_called_with('127.0.0.1', 12345, timeout=6.0)
                args, kwargs = connection.return_value.request.call_args
                self.assertEqual(args, (method, path))
                self.assertEqual(kwargs['headers']['Authorization'], 'Bearer synthetic-token')
                self.assertEqual(kwargs['body'], None if body is None else b'{"id":"one"}')

    def test_wrong_scan_methods_and_routes_rejected_without_socket(self):
        bridge = Bridge('http://127.0.0.1:12345', 'synthetic-token')
        with patch('http.client.HTTPConnection') as connection:
            for method, path, body in (
                ('GET', '/control/scan', None), ('GET', '/control/scan/cancel', None),
                ('POST', '/control/scan/status', {}), ('POST', '/control/scan?id=x', {}),
                ('POST', '/control/scan/other', {}), ('GET', '/control/scan/status#fragment', None),
            ):
                with self.subTest(path=path), self.assertRaises(BridgeError):
                    bridge.request(method, path, body)
            connection.assert_not_called()


if __name__ == '__main__':
    unittest.main()
