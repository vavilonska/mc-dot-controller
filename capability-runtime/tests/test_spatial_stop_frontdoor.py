"""Public MCP owner chain with synthetic native rows; no world/physics claim."""
from native_unknown_fixture import assert_unknown_refusal
from copy import deepcopy
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch
import test_route_local_frontdoor as route
import spatial_stop_fixture as spatial


class Endpoint(route.Endpoint):
    def __init__(self):
        super().__init__()
        self.scenario = self.mode_name
        if self.scenario not in ('lost_second', 'motion_gate_unknown'):
            self.mode_name = 'success_obstacle_terrace'

    def snapshot(self):
        value = super().snapshot()
        if self.scenario != 'legacy_fallback':
            value['scoped_native_preflight']['profiles'][spatial.PROFILE] = ['follow_path']
        return value

    def request(self, method, path, body=None):
        if path == '/control/scoped-action' and self.scenario == 'known_native_refusal':
            self.posts.append((path, deepcopy(body)))
            raise route.BridgeError('scoped_movement_entity_unsupported', status=409, uncertain=False,
                route_entity_rejection={'schema_version':1, 'profile':spatial.PROFILE, 'policy':spatial.POLICY,
                    'phase':'type', 'entity_type':'minecraft:pufferfish', 'exception_type':'rejected',
                    'rejection_code':'scoped_movement_entity_unsupported'}, route_entity_rejection_status='reported')
        value = super().request(method, path, body)
        if (path.startswith('/control/action/status') and self.action.get('status') == 'succeeded'
                and self.scenario in ('terrain_change_stops_route', 'terrain_change_unknown_stops_route')
                and len(self.actions) == 2):
            from route_terrain_fixture import attach_rejection
            attach_rejection(self.action, motion_unknown=self.scenario == 'terrain_change_unknown_stops_route')
            return deepcopy(self.action)
        if (path.startswith('/control/action/status') and self.action.get('status') == 'succeeded'
                and self.scenario == 'wrong_terminal_profile'):
            self.action['result']['local_segment']['profile'] = route.PROFILE
            return deepcopy(self.action)
        return value


class SpatialStopFrontdoorTests(unittest.TestCase):
    until = route.RouteLocalFrontdoorTests.until
    rpc = route.RouteLocalFrontdoorTests.rpc
    call = route.RouteLocalFrontdoorTests.call
    submit = route.RouteLocalFrontdoorTests.submit
    posts = route.RouteLocalFrontdoorTests.posts

    def finish(self, result):
        result = route.RouteLocalFrontdoorTests.finish(self, result)
        directory = os.environ.get('MDC_SPATIAL_STOP_MCP_EVIDENCE')
        if directory:
            out = Path(directory) / self._testMethodName
            out.mkdir(parents=True, exist_ok=True)
            (out / 'public-result.json').write_text(json.dumps(result, indent=2) + '\n')
            (out / 'native-posts.json').write_text(json.dumps(self.posts(), indent=2) + '\n')
        return result

    def setUp(self):
        original_fixture, original_terminal = route.fixture, route.terminal
        def fixture(intent=None, scope=None, **kwargs):
            if scope is not None and scope.get('profile') == spatial.PROFILE:
                value = spatial.fixture(intent, scope, **kwargs)
                if self._testMethodName == 'test_far_passive_route':
                    spatial.add_row(value[0], spatial.entity_row(value[0], kind='bat', position=[40.,64.,40.]))
                return value
            return original_fixture(intent, scope, **kwargs) if intent is not None else original_fixture(**kwargs)
        def terminal(native, **kwargs):
            if native['result']['scoped_native_preflight']['profile'] == spatial.PROFILE:
                return spatial.terminal(native, **kwargs)
            return original_terminal(native, **kwargs)
        self.patches = [patch.object(route, 'Endpoint', Endpoint), patch.object(route, 'fixture', fixture),
                        patch.object(route, 'terminal', terminal)]
        for item in self.patches: item.start()
        try: route.RouteLocalFrontdoorTests.setUp(self)
        except BaseException:
            for item in reversed(self.patches): item.stop()
            raise

    def tearDown(self):
        try:
            if self.mode == 'wrong_terminal_profile': self.mode = 'lost_second'
            route.RouteLocalFrontdoorTests.tearDown(self)
        finally:
            for item in reversed(self.patches): item.stop()

    def assert_route(self, profile):
        result = self.finish(self.submit())
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(self.bridge.pos, {'x':4.5, 'y':64, 'z':.5})
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        posts = self.posts()
        self.assertGreater(len(posts), 1)
        self.assertTrue(all(p['preflight']['profile'] == profile for p in posts))
        self.assertTrue(all(not any(k in p['intent'] for k in ('route_threat_guard', 'route_stop_only')) for p in posts))
        self.assertEqual(len(self.bridge.moves), len(posts))
        self.assertEqual(result['evidence']['budget']['used']['ordinary']['actions'], len(posts))
        self.assertEqual(result['evidence']['budget']['used']['reflex']['actions'], 0)
        self.assertEqual(len({tuple(p['preflight'][k] for k in ('owner_id','owner_generation','job_id','defense_epoch')) for p in posts}), 1)
        self.assertIsNone(self.client.session()['capability_lease'])
        return result

    def test_default_spatial_route(self): self.assert_route(spatial.PROFILE)
    def test_far_passive_route(self): self.assert_route(spatial.PROFILE)
    def test_legacy_fallback(self): self.assert_route(route.PROFILE)
    def test_known_native_refusal(self):
        self.expected_mcp_exit = 2
        result = self.finish(self.submit())
        receipt = assert_unknown_refusal(self, result)
        self.assertEqual(len(self.posts()), 1)
        self.assertFalse(self.bridge.moves)
        self.assertIn('minecraft:pufferfish', json.dumps(receipt))
        self.assertIn('route_entity_rejection', json.dumps(receipt))
        self.assertFalse([p for p in self.posts() if p['intent']['action'] == 'combat_entity'])

    def test_wrong_terminal_profile(self):
        result = self.finish(self.submit())
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(len(self.bridge.moves), 1)

    def test_terrain_change_stops_route(self):
        result = self.finish(self.submit())
        self.assertNotEqual(result['state'], 'succeeded', result)
        self.assertNotEqual(result['state'], 'unknown', result)
        self.assertEqual(len(self.posts()), 2)
        self.assertEqual(len(self.bridge.moves), 2)
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        self.assertIn('route_terrain_rejection', json.dumps(result))
        self.assertIn('local_segment_footprint_changed', json.dumps(result))
        self.assertFalse([p for p in self.posts() if p['intent']['action'] == 'combat_entity'])
        self.assertIsNone(self.client.session()['capability_lease'])

    def test_terrain_change_unknown_stops_route(self):
        self.expected_mcp_exit = 2
        result = self.finish(self.submit())
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(len(self.posts()), 2)
        self.assertEqual(len(self.bridge.moves), 2)
        # Unknown public outcomes omit untrusted payload; originals remain archived.
        import gzip
        receipts = list((self.root / 'runtime').glob('receipt-*.json.gz'))
        self.assertTrue(any('route_terrain_rejection' in gzip.decompress(p.read_bytes()).decode() for p in receipts))
        self.assertIn('route_terrain_rejection', self.bridge.action['result'])
        self.assertFalse([p for p in self.posts() if p['intent']['action'] == 'combat_entity'])

    test_lost_second = route.RouteLocalFrontdoorTests.test_lost_second
    test_motion_gate_unknown = route.RouteLocalFrontdoorTests.test_motion_gate_unknown


if __name__ == '__main__': unittest.main()
