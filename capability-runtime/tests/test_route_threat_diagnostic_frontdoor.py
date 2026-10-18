"""Production MCP → Owner → Watchdog → Resident → transport, offline bytes only."""
from native_unknown_fixture import assert_unknown_refusal
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from resident_controller.capability_snapshot import exact
from route_threat_diagnostic_fixture import diagnostic_fixture
from test_route_threat_diagnostic import encode, exchange
import test_route_local_frontdoor as route
import test_route_defend_once_frontdoor as combined
import test_spatial_defense_frontdoor as spatial


def admissions(value):
    if type(value) is dict:
        if 'action_admission' in value: yield value['action_admission']
        for child in value.values(): yield from admissions(child)
    elif type(value) is list:
        for child in value: yield from admissions(child)


class Endpoint(spatial.Endpoint):
    def __init__(self):
        super().__init__(); self.wire_calls = []; self.refused = None
        self.original_raw = None; self.diagnostic = None

    def request(self, method, path, body=None):
        if path == '/control/scoped-action' and body['intent']['action'] == 'follow_path':
            self.posts.append((path, deepcopy(body)))
            raw = (Path(os.environ['MDC_ROUTE_THREAT_DIAGNOSTIC_FRONTDOOR']).read_bytes()
                   if self.scenario == 'original_java_refusal' else encode(diagnostic_fixture()))
            self.original_raw = raw; self.diagnostic = json.loads(raw)['route_threat_rejection']
            if self.scenario == 'malformed_refusal':
                invalid = deepcopy(self.diagnostic); invalid['native']['reason'] = 'untrusted arbitrary text'
                raw = encode(invalid)
            elif self.scenario == 'absent_refusal':
                raw = json.dumps({'error':self.diagnostic['rejection_code']}).encode()
            status = 500 if self.scenario == 'uncertain_5xx' else 409
            exc, transport, calls = exchange(raw,body,status=status)
            self.last_response_metadata = deepcopy(transport.last_response_metadata)
            self.wire_calls.extend(calls); self.refused = exc
            raise exc
        return super().request(method,path,body)


class RouteThreatDiagnosticFrontdoorTests(unittest.TestCase):
    until = route.RouteLocalFrontdoorTests.until
    rpc = route.RouteLocalFrontdoorTests.rpc
    call = route.RouteLocalFrontdoorTests.call
    submit = route.RouteLocalFrontdoorTests.submit
    finish = route.RouteLocalFrontdoorTests.finish
    posts = route.RouteLocalFrontdoorTests.posts
    defend = combined.RouteDefendOnceFrontdoorTests.defend

    def setUp(self):
        with patch.object(route,'Endpoint',Endpoint): route.RouteLocalFrontdoorTests.setUp(self)

    def tearDown(self):
        if self.mode == 'uncertain_5xx': self.mode = 'lost_second'
        route.RouteLocalFrontdoorTests.tearDown(self)

    def assert_refusal(self, *, diagnostic=True, invalid=False):
        self.expected_mcp_exit = 2
        result = self.defend(); code = self.bridge.diagnostic['rejection_code']
        archived = assert_unknown_refusal(self, result)
        self.assertIn(code, archived['reason'])
        self.assertEqual(len(self.posts()),1); self.assertEqual(len(self.bridge.wire_calls),1)
        self.assertFalse(self.bridge.moves); self.assertEqual(self.bridge.action['status'],'idle')
        self.assertFalse([p for p in self.posts() if p['intent']['action'] == 'combat_entity'])
        self.assertFalse(list(admissions(result)))
        # The immutable original receipt carries diagnostics, not admission authority.
        receipt = self.client.result(archived['request_id'])
        self.assertTrue(exact(receipt, archived))
        evidence = receipt.get('native_refusal_diagnostics') or {}
        self.assertNotIn('action_admission', receipt)
        if diagnostic:
            self.assertTrue(exact(evidence['route_threat_rejection'], self.bridge.diagnostic))
            self.assertFalse(evidence['effect_free_proven'])
            evidence['route_threat_rejection']['native']['reason'] = 'changed by caller'
            self.assertTrue(exact(self.client.result(archived['request_id']), archived))
            self.assertTrue(exact(self.bridge.refused.route_threat_rejection, self.bridge.diagnostic))
        else:
            self.assertNotIn('route_threat_rejection', evidence)
            self.assertEqual(evidence.get('route_threat_rejection_status'), 'invalid' if invalid else None)
        repeated = self.call('mdc_job', self.last_submit)
        self.assertEqual(repeated['job_id'], result['job_id']); self.assertEqual(repeated['state'], 'unknown')
        self.assertEqual(self.resident.active.action_id, archived['action_id'])
        self.assertEqual(len(self.posts()),1); self.assertEqual(len(self.bridge.wire_calls),1)
        self.assertTrue(exact(self.client.result(archived['request_id']), archived))
        return result

    def test_valid_refusal(self): self.assert_refusal()
    def test_malformed_refusal(self): self.assert_refusal(diagnostic=False,invalid=True)
    def test_absent_refusal(self): self.assert_refusal(diagnostic=False)

    def test_uncertain_5xx(self):
        result = self.defend()
        self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(result['effect_certainty'],'unknown'); self.assertEqual(result['cleanup_certainty'],'unknown')
        self.assertEqual(result['continuation'],'reconcile_original_id_required')
        self.assertEqual(len(self.posts()),1); self.assertEqual(len(self.bridge.wire_calls),1)
        self.assertFalse(self.bridge.moves); self.assertIsNone(self.bridge.refused.route_threat_rejection)
        self.assertFalse(list(admissions(result)))
        self.assertTrue(self.resident.active.capability_unknown)
        original_id = self.resident.active.action_id; self.assertTrue(original_id)
        again = self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
            'session_ref':result['session_ref'],'job_id':result['job_id']})
        self.assertEqual(again['state'],'unknown'); self.assertEqual(self.resident.active.action_id,original_id)
        self.assertEqual(len(self.posts()),1); self.assertEqual(len(self.bridge.wire_calls),1)
        self.assertFalse([p for p,b in self.bridge.posts if p in ('/control/action','/control/action/cancel')])

    @unittest.skipUnless(os.environ.get('MDC_ROUTE_THREAT_DIAGNOSTIC_FRONTDOOR'),
                         'explicit original Java HTTP response with offline fixture bindings required')
    def test_original_java_refusal(self):
        path = Path(os.environ['MDC_ROUTE_THREAT_DIAGNOSTIC_FRONTDOOR']); raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest(); self.assert_refusal()
        self.assertEqual(self.bridge.original_raw,raw); self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)


if __name__ == '__main__': unittest.main()
