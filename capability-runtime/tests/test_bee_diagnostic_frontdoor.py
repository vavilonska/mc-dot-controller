"""Public MCP refusal diagnostics with synthetic native endpoint; no live claim."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
import test_spatial_stop_v2_frontdoor as v2
from bee_diagnostic_fixture import diagnostic_fixture

class Endpoint(v2.Endpoint):
    def request(self, method, path, body=None):
        if path == '/control/scoped-action':
            self.posts.append((path, deepcopy(body)))
            data = v2.spatial.fixture(body['intent'], body['preflight'], block=self.block)
            self.refusal = diagnostic_fixture(data)
            raise v2.route.BridgeError('route_bee_native_unconfirmed', status=409, uncertain=False,
                route_entity_rejection=deepcopy(self.refusal), route_entity_rejection_status='reported')
        return super().request(method, path, body)

class BeeDiagnosticFrontdoorTests(unittest.TestCase):
    until = v2.SpatialStopV2FrontdoorTests.until
    rpc = v2.SpatialStopV2FrontdoorTests.rpc
    call = v2.SpatialStopV2FrontdoorTests.call
    submit = v2.SpatialStopV2FrontdoorTests.submit
    posts = v2.SpatialStopV2FrontdoorTests.posts
    finish = v2.SpatialStopV2FrontdoorTests.finish
    def setUp(self):
        self.endpoint_patch = patch.object(v2, 'Endpoint', Endpoint)
        self.endpoint_patch.start()
        try: v2.SpatialStopV2FrontdoorTests.setUp(self)
        except BaseException:
            if getattr(self, 'stderr', None):
                self.stderr.flush(); self.stderr.seek(0)
                print(self.stderr.read())
            self.endpoint_patch.stop()
            raise
    def tearDown(self):
        try: v2.SpatialStopV2FrontdoorTests.tearDown(self)
        finally: self.endpoint_patch.stop()
    def test_bee_detail(self):
        result = self.finish(self.submit())
        self.assertEqual(result['state'], 'blocked', result)
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        self.assertEqual(len(self.posts()), 1)
        self.assertFalse(self.bridge.moves)
        self.assertIsNone(self.client.session()['capability_lease'])
        found = []
        def walk(value):
            if isinstance(value, dict):
                if 'route_entity_rejection' in value: found.append(value['route_entity_rejection'])
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(result)
        self.assertTrue(found, json.dumps(result))
        self.assertTrue(all(item == self.bridge.refusal for item in found))
        self.assertEqual(found[0]['native_bee_diagnostic']['native']['reason'], 'entity_not_observed')
        self.assertFalse(found[0]['native_bee_diagnostic']['source']['row_present'])
        self.assertEqual(result['evidence']['budget']['used']['reflex']['actions'], 0)

if __name__ == '__main__': unittest.main()
