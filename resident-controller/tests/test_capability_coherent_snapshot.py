"""Actual Resident/WorldCache and HTTP adapter, native-shaped 20 TPS fixtures.

No game, socket, process start, credentials, or external service is used.
"""
from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from resident_controller.controller import Resident, action_rejection_admission
from resident_controller.ipc import QueueClient
from resident_controller.transport import Bridge, BridgeError
from resident_controller.capability_snapshot import validate_snapshot
from navigation_controller.fake import FakeClock, FakeWorld
from test_controller import FakeBridge
from test_navigation_binding_producers import state, ACTION_SESSION
from capability_fixtures import native_bundle, freshness


class CallbackBridge(FakeBridge):
    """Each native request waits for one real-rate callback; source time is native."""
    def __init__(self, clock, bundles):
        super().__init__()
        self.clock, self.bundles = clock, deque(deepcopy(bundles))
        self.action['action_session'] = ACTION_SESSION
        self.last_response_metadata = None
        self.terrain_pages = deque()
        self.post_outcomes = []

    def request(self, method, path, body=None):
        self.clock.sleep(.05)
        if path.startswith('/control/capability-snapshot?'):
            self.calls.append((method, path, deepcopy(body)))
            value = self.bundles.popleft()
            if isinstance(value, Exception):
                raise value
            self.last_response_metadata = {'response_bytes_read': 1234, 'http_status': 200,
                                           'response_bytes_status': 'observed_read_length'}
            return value
        if path.startswith('/control/terrain?'):
            self.calls.append((method, path, deepcopy(body)))
            return self.terrain_pages.popleft()
        if method == 'POST' and path == '/control/action' and 'capability_guard' in body:
            guard = body['capability_guard']
            native_tick = 100 + round((self.clock.now - 100) * 20)
            native_nano = round(self.clock.now * 1e9)
            elapsed = native_nano - int(guard['source_nano'])
            delta = native_tick - guard['source_tick']
            if elapsed < 0 or elapsed > 800_000_000 or delta < 0 or delta > 5:
                self.calls.append((method, path, deepcopy(body)))
                facts = freshness(source_tick=guard['source_tick'], current_tick=native_tick,
                                  tick_delta=delta, source_nano=guard['source_nano'], current_nano=str(native_nano),
                                  elapsed_nanos=str(elapsed), nano_age_negative=elapsed < 0,
                                  nano_age_exceeded=elapsed > 800_000_000, tick_reversed=delta < 0,
                                  tick_delta_exceeded=delta > 5)
                self.post_outcomes.append(('rejected', deepcopy(facts)))
                raise BridgeError('capability_source_expired', status=409, capability_source_freshness=facts)
            self.post_outcomes.append(('admitted', deepcopy(guard)))
        response = super().request(method, path, body)
        if method == 'POST' and path == '/control/action':
            self.action['action_session'] = ACTION_SESSION
            response['action_session'] = ACTION_SESSION
        return response


class CoherentSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        for name, call in [('time.monotonic', self.clock.monotonic), ('time.sleep', self.clock.sleep)]:
            stub = patch(name, call); stub.start(); self.addCleanup(stub.stop)

    def resident(self, bundles):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        bridge = CallbackBridge(self.clock, bundles)
        resident = Resident(bridge, temp.name); resident.start(); self.addCleanup(resident.lock.close)
        bridge.calls.clear()
        self.clock.now = 100
        return resident, bridge

    def bundle(self, *, tick=101, **options):
        return native_bundle(state(tick=tick, **options), source_nano=str(round((100 + (tick - 100) / 20) * 1e9)))

    def observe(self, resident, **options):
        return resident.snapshot({'capability_observation': True, 'entity_radius': 48, **options})

    def test_single_callback_preserves_all_four_raw_siblings_and_original_acquisition(self):
        bundle = self.bundle()
        bundle['state']['nearby'].update(total=1, returned=1, entities=[{
            'uuid': 'observed-rabbit', 'type': 'minecraft:rabbit',
            'native_living': {'schema_version': 1, 'current_target': None, 'capture_age_ticks': 11,
                              'source_tick': 90, 'bee': {'persistent_anger_target_uuid': None}},
            'unknown_future_native_fact': {'value': None}}])
        resident, bridge = self.resident([bundle])
        result = self.observe(resident)
        self.assertEqual(bridge.calls, [('GET', '/control/capability-snapshot?radius=48', None)])
        for key in ('status', 'action', 'state', 'screen'):
            self.assertEqual(result[key], bundle[key])
        self.assertEqual(result['capability_capture'], {'started_mono': 100, 'finished_mono': 100.05})
        self.assertEqual(result['state']['capability_guard']['source_nano'], '100050000000')
        self.assertEqual(result['state_read_diagnostics']['response_metadata']['response_bytes_read'], 1234)
        saved = json.loads((resident.root / 'observation.json').read_text())
        self.assertIsNone(saved['state']['nearby']['entities'][0]['native_living']['current_target'])
        self.assertIsNone(saved['action']['action_id'])

    def test_no_fallback_for_unavailable_or_malformed_bundle(self):
        for value in (BridgeError('unknown_endpoint', status=404), None, {}, {'capability_snapshot_schema_version': 1}):
            with self.subTest(value=value):
                resident, bridge = self.resident([value])
                with self.assertRaises((BridgeError, ValueError)):
                    self.observe(resident)
                self.assertEqual(len(bridge.calls), 1)
                self.assertFalse((resident.root / 'observation.json').exists())

    def test_failed_initial_a_invalidates_old_terrain_before_bundle_read(self):
        resident, bridge = self.resident([None])
        resident.cache.grid = object()
        resident.cache.cells = {'old': 'cached'}
        with self.assertRaises(ValueError):
            self.observe(resident, terrain=True, radius=1, vertical=2)
        self.assertIsNone(resident.cache.grid)
        self.assertEqual(resident.cache.cells, {})
        self.assertEqual(len(bridge.calls), 1)

    def test_old_native_sample_is_retained_without_freshness_repair(self):
        bundle = self.bundle(tick=100)
        entity = {'uuid': 'old-server-sample', 'native_living': {
            'current_target': None, 'source_tick': 80, 'capture_age_ticks': 20}}
        bundle['state']['nearby'].update(total=1, returned=1, entities=[entity])
        resident, bridge = self.resident([bundle])
        self.clock.sleep(1.0)
        result = self.observe(resident)
        self.assertEqual(result['state']['capability_guard'], bundle['state']['capability_guard'])
        self.assertEqual(result['state']['nearby']['entities'], [entity])
        self.assertEqual(result['capability_capture']['started_mono'], 101)
        self.assertEqual(result['state']['world']['game_time'], 100)
        self.assertEqual(len(bridge.calls), 1)

    def test_schema_null_missing_downgraded_bool_and_wrong_type_are_rejected(self):
        for sibling in (None, 'status', 'action', 'state', 'screen'):
            for bad in (None, 1, 3, True, '2'):
                with self.subTest(sibling=sibling, bad=bad):
                    bundle = self.bundle()
                    target = bundle if sibling is None else bundle[sibling]
                    target['schema_version'] = bad
                    with self.assertRaises(ValueError): validate_snapshot(bundle, 48)
        for bad in (None, 0, 2, True, '1'):
            bundle = self.bundle(); bundle['capability_snapshot_schema_version'] = bad
            with self.assertRaises(ValueError): validate_snapshot(bundle, 48)
        for key in ('status', 'action', 'state', 'screen'):
            bundle = self.bundle(); bundle[key] = None
            with self.assertRaises(ValueError): validate_snapshot(bundle, 48)

    def test_inconsistent_siblings_or_guard_never_replace_prior_bundle(self):
        variants = [
            lambda b: b['status']['world'].update(game_time=99),
            lambda b: b['status']['world'].update(world_generation='another-world'),
            lambda b: b['status']['world'].update(dimension='minecraft:the_end'),
            lambda b: b['status']['player'].update(uuid='another-player'),
            lambda b: b['status']['player'].update(x=1.5),
            lambda b: b['state']['player'].update(x=10**400),
            lambda b: b['status']['client_action'].update(action_session='another-action-session'),
            lambda b: b['action'].update(status='running'),
            lambda b: b['state']['client_action'].update(ok=1),
            lambda b: b['screen'].update(open=True),
            lambda b: b['screen']['menu'].update(state_id=1),
            lambda b: [b[key].update(menu={}) for key in ('state', 'screen')],
            lambda b: b['state'].update(focused=None),
            lambda b: b['state'].update(paused=0),
            lambda b: b['state']['capability_guard'].update(source_tick=100),
            lambda b: b['state']['capability_guard'].update(source_nano=100050000000),
            lambda b: b['state']['nearby'].update(radius=8),
            lambda b: b['state']['nearby'].update(returned=1),
            lambda b: b['state']['nearby'].update(truncated=True),
            lambda b: b['state'].update(movement_budget={'invented': True}),
        ]
        for mutate in variants:
            with self.subTest(mutate=mutate):
                invalid = self.bundle(); mutate(invalid)
                resident, bridge = self.resident([self.bundle(), invalid])
                self.observe(resident)
                saved = (resident.root / 'observation.json').read_bytes()
                with self.assertRaises(ValueError): self.observe(resident)
                self.assertEqual(len(bridge.calls), 2)
                self.assertIsNone(resident.cache.capability_bundle)
                self.assertEqual(saved, (resident.root / 'observation.json').read_bytes())

    def test_armed_budget_nullable_fields_are_never_normalized_or_dropped(self):
        for phase in ('armed', 'stopping', 'sealed'):
            budget = {'schema_version': 1, 'state': phase, 'ended_nano': None,
                      'last_position': {'x': .5, 'y': 64.0, 'z': .5}}
            bundle = self.bundle()
            for action in (bundle['action'], bundle['status']['client_action'], bundle['state']['client_action']):
                action['movement_budget'] = deepcopy(budget)
            bundle['state']['movement_budget'] = deepcopy(budget)
            self.assertIs(validate_snapshot(bundle, 48), bundle)
            for target in (bundle['action']['movement_budget'], bundle['state']['movement_budget']):
                del target['ended_nano']
                with self.assertRaisesRegex(ValueError, 'mismatch'): validate_snapshot(bundle, 48)
                target['ended_nano'] = None

    def test_run_or_process_identity_change_is_not_an_accepted_observation(self):
        for key, value in [('run_id', 'new-run'), ('process_id', 1235)]:
            bundle = self.bundle(); bundle['status'][key] = value
            resident, bridge = self.resident([bundle])
            with self.assertRaisesRegex(ValueError, 'bridge_restarted'): self.observe(resident)
            self.assertTrue(resident.paused)
            self.assertTrue(all(method == 'GET' for method, _, _ in bridge.calls))

    def test_final_c_replaces_screen_action_status_and_metadata_together(self):
        a, c = self.bundle(), self.bundle(tick=103)
        c['state']['screen_open'] = True
        c['state']['client_action'].update(status='running', action_id='existing-native-action')
        c = native_bundle(c['state'], source_nano=c['state']['capability_guard']['source_nano'])
        resident, bridge = self.resident([a, c])
        page = FakeWorld().pages(radius=1, tick=102)[0]
        page.update(capability_page_schema_version=1, page_limit=1024)
        bridge.terrain_pages.append(page)
        result = self.observe(resident, terrain=True, radius=1, vertical=2)
        for key in ('status', 'action', 'state', 'screen'):
            self.assertEqual(result[key], c[key])
        self.assertTrue(result['screen']['open'])
        self.assertEqual(result['terrain']['capture_started_mono'], 100)
        self.assertAlmostEqual(result['capability_capture']['started_mono'], 100.1)
        self.assertEqual([urlsplit(path).path for _, path, _ in bridge.calls],
                         ['/control/capability-snapshot', '/control/terrain', '/control/capability-snapshot'])
        self.assertEqual(result['terrain_read']['diagnostics']['attempts'][0]['stages'][-1]['phase'], 'assembler_finish')

    def test_invalid_final_c_invalidates_scan_without_retry_or_partial_publish(self):
        for mutate in (lambda b: b.update(capability_snapshot_schema_version=None),
                       lambda b: b['screen'].update(menu=None),
                       lambda b: b['state']['capability_guard'].update(source_tick=1)):
            a, c = self.bundle(), self.bundle(tick=103); mutate(c)
            resident, bridge = self.resident([a, c])
            page = FakeWorld().pages(radius=1, tick=102)[0]
            page.update(capability_page_schema_version=1, page_limit=1024)
            bridge.terrain_pages.append(page)
            with self.assertRaises(ValueError): self.observe(resident, terrain=True, radius=1, vertical=2)
            self.assertIsNone(resident.cache.grid); self.assertEqual(resident.cache.cells, {})
            self.assertEqual(len(bridge.calls), 3)
            self.assertTrue(resident.cache.terrain_read['last_rejection'].startswith('invalid_capability_snapshot_'))
            self.assertFalse((resident.root / 'observation.json').exists())

    def test_coordination_optin_retains_same_bundle_acquisition(self):
        resident, bridge = self.resident([self.bundle()])
        result = self.observe(resident, coordination_step=True)
        self.assertEqual(bridge.calls[0][1], '/control/capability-snapshot?radius=48&coordination_step=1')
        self.assertEqual(result['coordination_capture'], result['capability_capture'])

    def test_real_rate_queue_read_to_post_keeps_native_guard_and_stale_post_is_definite(self):
        for delay, admitted in ((.05, True), (.25, False), (.81, False)):
            with self.subTest(delay=delay):
                bundle = self.bundle()
                resident, bridge = self.resident([bundle])
                queue = QueueClient(resident.root)
                observe_id = queue.submit({'op': 'observe', 'capability_observation': True, 'entity_radius': 48})
                resident.tick()
                result = queue.result(observe_id)
                self.assertEqual(result['status'], 'succeeded')
                guard = result['result']['state']['capability_guard']
                self.clock.sleep(delay)
                request_id = queue.submit({'op': 'action', 'action': 'select_hotbar', 'hotbar_slot': 1,
                                           'capability_guard': guard, 'entity_radius': 48})
                resident.tick()
                posts = [body for method, path, body in bridge.calls if method == 'POST' and path == '/control/action']
                self.assertEqual(len(posts), 1)
                self.assertEqual(posts[0]['capability_guard'], bundle['state']['capability_guard'])
                if admitted:
                    self.assertEqual(bridge.post_outcomes[0][0], 'admitted')
                    self.assertIsNone(queue.result(request_id))
                else:
                    receipt = queue.result(request_id)
                    self.assertEqual(receipt['status'], 'failed')
                    self.assertEqual(receipt['reason'], 'capability_source_expired')
                    self.assertEqual(receipt['action_admission']['capability_source_freshness'], bridge.post_outcomes[0][1])
                    self.assertFalse(receipt['action_admission']['admitted'])
                    self.assertIsNone(receipt['action_id']); self.assertIsNone(receipt['action'])
                    self.assertEqual(len([call for call in bridge.calls if call[0] == 'POST']), 1)
                    for _ in range(3): resident.tick()
                    self.assertEqual(len([call for call in bridge.calls if call[0] == 'POST']), 1)


class CoherentTransportTests(unittest.TestCase):
    def bridge(self, responses):
        responses = deque(responses)
        class Response:
            def __init__(self, status, raw): self.status, self.raw = status, raw
            def getheader(self, name): return None
            def read(self, limit): return self.raw[:limit]
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response(*responses.popleft())
            def close(self): pass
        stub = patch('resident_controller.transport.http.client.HTTPConnection', Connection)
        stub.start(); self.addCleanup(stub.stop)
        return Bridge('http://127.0.0.1:12345', 'synthetic-offline-test-token')

    def test_actual_transport_accepts_bundle_and_retains_256kib_bound(self):
        bundle = native_bundle(state())
        raw = json.dumps(bundle).encode()
        bridge = self.bridge([(200, raw), (200, b' ' * (256 * 1024 + 1))])
        self.assertEqual(bridge.request('GET', '/control/capability-snapshot?radius=48'), bundle)
        self.assertEqual(bridge.last_response_metadata['response_bytes_read'], len(raw))
        with self.assertRaisesRegex(BridgeError, 'response_too_large'):
            bridge.request('GET', '/control/capability-snapshot?radius=48')
        self.assertEqual(bridge.last_response_metadata['response_bytes_status'], 'limit_exceeded_prefix')

    def test_freshness_evidence_survives_wire_and_admission_without_changing_no_effect(self):
        data = freshness()
        bridge = self.bridge([(409, json.dumps({'error': 'capability_source_expired', 'capability_source_freshness': data}).encode()),
                              (409, b'{"error":"capability_source_expired"}')])
        with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/action', {})
        self.assertFalse(caught.exception.uncertain)
        evidence = action_rejection_admission(caught.exception)
        self.assertEqual(evidence['capability_source_freshness'], data)
        data['tick_delta'] = 999
        self.assertEqual(evidence['capability_source_freshness']['tick_delta'], 6)
        with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/action', {})
        self.assertNotIn('capability_source_freshness', action_rejection_admission(caught.exception))
        self.assertNotIn('capability_source_freshness', bridge.last_response_metadata)

    def test_malformed_optional_diagnostics_are_explicitly_invalid_without_changing_error(self):
        for bad in (None, {}, freshness(source_nano=12), freshness(phase='invented'),
                    freshness(tick_delta=True), freshness(max_tick_delta=6), freshness(extra='untrusted')):
            with self.subTest(bad=bad):
                raw = json.dumps({'error': 'capability_source_expired', 'capability_source_freshness': bad}).encode()
                bridge = self.bridge([(409, raw)])
                with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/action', {})
                self.assertFalse(caught.exception.uncertain)
                evidence = action_rejection_admission(caught.exception)
                self.assertNotIn('capability_source_freshness', evidence)
                self.assertEqual(evidence['capability_source_freshness_status'], 'invalid')

    def test_5xx_even_with_valid_diagnostics_stays_uncertain(self):
        raw = json.dumps({'error': 'capability_source_expired', 'capability_source_freshness': freshness()}).encode()
        bridge = self.bridge([(500, raw)])
        with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/action', {})
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(caught.exception.capability_source_freshness, freshness())



class ActualJavaWireFixtureTests(unittest.TestCase):
    FIXTURES = Path(__file__).parent / 'fixtures' / 'capability-bundle-wire'
    CASES = ('known_null', 'current_target', 'persistent_target', 'both_targets', 'unknown_absent',
             'stale_absent', 'missing_current_target', 'missing_persistent_target', 'unrelated_nulls',
             'multiple_rows', 'meter_armed', 'meter_stopping', 'meter_sealed')

    bridge = CoherentTransportTests.bridge

    def test_exact_native_jar_fixture_bytes_are_pinned(self):
        import hashlib
        manifest = json.loads((self.FIXTURES / 'PROVENANCE.json').read_text())
        self.assertEqual(manifest['producer_jar_sha256'],
                         '111099ad4b0626cef4142435f0a54b41482e2efd53ed2f899d708a965ba7a3da')
        self.assertEqual(len(manifest['files']), 14)
        for filename, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((self.FIXTURES / filename).read_bytes()).hexdigest(), expected)

    def test_all_thirteen_actual_encoded_bundles_pass_real_bridge_and_resident_unchanged(self):
        for name in self.CASES:
            with self.subTest(name=name):
                raw = (self.FIXTURES / ('encoded-bundle-' + name + '.json')).read_bytes()
                native = json.loads(raw)
                bridge = self.bridge([(200, json.dumps(native['status']).encode()),
                                      (200, json.dumps(native['action']).encode()), (200, raw)])
                temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
                resident = Resident(bridge, temp.name); resident.start(); self.addCleanup(resident.lock.close)
                result = resident.snapshot({'capability_observation': True, 'entity_radius': 48})
                for key in ('status', 'action', 'state', 'screen'):
                    self.assertEqual(result[key], native[key])
                self.assertEqual(result['state_read_diagnostics']['response_metadata']['response_bytes_read'], len(raw))
                self.assertEqual(result['state']['capability_guard']['source_nano'], native['state']['capability_guard']['source_nano'])
                if name.startswith('meter_'):
                    expected_status = name.removeprefix('meter_')
                    self.assertEqual(result['state']['movement_budget']['status'], expected_status)
                    action = result['action']
                    self.assertEqual(action['status'], 'succeeded')
                    self.assertIn('ended_nano', action['movement_budget'])
                    self.assertIsNone(action['result']['unknown_metric'])
                    self.assertIsNone(action['result']['nested']['unknown'])
                    self.assertEqual(action['movement_budget'], result['state']['movement_budget'])

    def test_actual_encoded_null_fields_cannot_be_omitted_or_changed_in_one_sibling(self):
        for phase in ('armed', 'stopping', 'sealed'):
            for field in ('budget', 'result', 'nested_result', 'state_budget'):
                with self.subTest(phase=phase, field=field):
                    native = json.loads((self.FIXTURES / ('encoded-bundle-meter_' + phase + '.json')).read_bytes())
                    if field == 'budget': del native['action']['movement_budget']['ended_nano']
                    elif field == 'state_budget': del native['state']['movement_budget']['ended_nano']
                    elif field == 'result': del native['action']['result']['unknown_metric']
                    else: native['action']['result']['nested']['unknown'] = False
                    with self.assertRaisesRegex(ValueError, 'mismatch'): validate_snapshot(native, 48)

    def test_actual_native_error_wire_preserves_all_three_phases_and_precise_nano_strings(self):
        fixtures = json.loads((self.FIXTURES / 'capability-freshness-wire.json').read_bytes())
        self.assertEqual([row['name'] for row in fixtures], ['guard_start', 'before_input_release', 'after_input_release'])
        for row in fixtures:
            raw = row['response_json'].encode()
            expected = json.loads(raw)['capability_source_freshness']
            bridge = self.bridge([(row['http_status'], raw)])
            with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/action', {})
            exc = caught.exception
            self.assertEqual(exc.code, 'capability_source_expired')
            self.assertFalse(exc.uncertain)
            self.assertEqual(action_rejection_admission(exc)['capability_source_freshness'], expected)
            self.assertEqual(exc.capability_source_freshness['source_nano'], '9007199254741123')
            self.assertEqual(exc.capability_source_freshness['current_nano'], '9007200054741124')


if __name__ == '__main__': unittest.main()
