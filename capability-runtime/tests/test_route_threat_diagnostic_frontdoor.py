"""Production MCP → Owner → Watchdog → Resident → transport, offline bytes only."""
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
        result = self.defend(); code = self.bridge.diagnostic['rejection_code']
        self.assertEqual(result['state'],'blocked',result)
        self.assertEqual(result['result']['reason'],code,result)
        self.assertEqual(result['effect_certainty'],'none_proven'); self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual(len(self.posts()),1); self.assertEqual(len(self.bridge.wire_calls),1)
        self.assertFalse(self.bridge.moves); self.assertEqual(self.bridge.action['status'],'idle')
        self.assertIsNone(self.client.session()['capability_lease'])
        self.assertFalse([p for p in self.posts() if p['intent']['action'] == 'combat_entity'])
        self.assertFalse([p for p,b in self.bridge.posts if p in ('/control/action','/control/action/cancel')])
        public = list(admissions(result)); self.assertTrue(public,result)
        for admission in public:
            self.assertEqual(admission['reason'],code); self.assertFalse(admission['admitted']); self.assertFalse(admission['uncertain'])
            if diagnostic: self.assertTrue(exact(admission['route_threat_rejection'],self.bridge.diagnostic))
            else:
                self.assertNotIn('route_threat_rejection',admission)
                self.assertEqual(admission.get('route_threat_rejection_status'),'invalid' if invalid else None)
        # Read the actual Watchdog result through its public client, retaining
        # the Resident queue receipt and exact original refusal identity.
        receipts = [self.client.result(p.stem) for p in (self.root/'watchdog'/'results').glob('*.json')]
        receipts = [r for r in receipts if type(r) is dict and 'action_admission' in r]
        self.assertEqual(len(receipts),1,receipts); receipt = receipts[0]
        self.assertEqual(receipt['queue_session_id'],self.resident.session_id)
        self.assertTrue(receipt['queue_request_id']); self.assertIsNone(receipt['action_id']); self.assertIsNone(receipt['action'])
        self.assertTrue(exact(receipt['action_admission'],public[0]))
        if diagnostic:
            public[0]['route_threat_rejection']['native']['reason'] = 'changed by caller'
            self.assertTrue(exact(self.client.result(receipt['request_id'])['action_admission'],receipt['action_admission']))
            self.assertTrue(exact(self.bridge.refused.route_threat_rejection,self.bridge.diagnostic))
        repeated = self.call('mdc_job',self.last_submit)
        self.assertEqual(repeated['job_id'],result['job_id']); self.assertEqual(repeated['state'],'blocked')
        self.assertEqual(len(self.posts()),1); self.assertEqual(len(self.bridge.wire_calls),1)
        if diagnostic:
            for admission in admissions(repeated):
                self.assertTrue(exact(admission['route_threat_rejection'],self.bridge.diagnostic))
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
