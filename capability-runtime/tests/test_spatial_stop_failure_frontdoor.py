"""Production Node MCP -> owner -> watchdog -> resident, synthetic native endpoint."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import test_route_local_frontdoor as route
import test_route_defend_once_frontdoor as combined
import test_spatial_defense_frontdoor as base
import spatial_threat_fixture as spatial
from test_spatial_stop_failure_contract import add_passive_rows


class Endpoint(base.Endpoint):
    def request(self, method, path, body=None):
        if (path.startswith('/control/action/status') and self.action.get('action') == 'follow_path'
                and self.action.get('status') == 'cancelled'):
            return deepcopy(self.action)
        if path == '/control/scoped-action' and body['intent']['action'] == 'follow_path':
            self.posts.append((path, deepcopy(body)))
            self.action, _, _, _ = spatial.fixture(body['intent'], body['preflight'],
                block=self.block, stop_only=True)
            self.action.update(action_schema_version=1, ok=True, server_confirmed=False)
            add_passive_rows(self.action)
            self.scopes.append(deepcopy(body['preflight']))
            self.actions.append(deepcopy(body['intent']))
            if self.scenario != 'fast_large_proof':
                del self.action['result']['route_threat_stop']
                self.action['reason'] = ('route_spatial_stop_evidence_too_large'
                    if self.scenario == 'fast_oversize_proof' else 'route_spatial_evidence_too_large'
                    if self.scenario == 'fast_oversize_frame' else 'local_segment_check_failed')
                if self.scenario == 'fast_failure_release_missing':
                    self.action['result']['input_release_confirmed'] = False
                elif self.scenario == 'fast_failure_unknown':
                    self.action['result']['unknown_outcome'] = True
                elif self.scenario == 'fast_failure_effect_outcome':
                    self.action['result']['effect_outcome'] = 'unknown'
                elif self.scenario == 'fast_failure_effect':
                    self.action['result']['local_segment']['effect_attempted'] = True
                elif self.scenario == 'fast_failure_identity':
                    self.action['action_id'] = 'unrelated-action-id'
                elif self.scenario == 'fast_failure_digest':
                    self.action['result']['scoped_native_preflight']['command_sha256'] = '0' * 64
            return deepcopy(self.action)
        return super().request(method, path, body)


class SpatialStopFailureFrontdoorTests(unittest.TestCase):
    until = base.SpatialDefenseFrontdoorTests.until
    rpc = base.SpatialDefenseFrontdoorTests.rpc
    call = base.SpatialDefenseFrontdoorTests.call
    submit = base.SpatialDefenseFrontdoorTests.submit
    finish = base.SpatialDefenseFrontdoorTests.finish
    posts = base.SpatialDefenseFrontdoorTests.posts
    defend = base.SpatialDefenseFrontdoorTests.defend

    def setUp(self):
        self.patches = [patch.object(route, 'Endpoint', Endpoint),
                        patch.object(route, 'fixture', spatial.fixture),
                        patch.object(route, 'terminal', spatial.terminal),
                        patch.object(combined, 'terminal', spatial.terminal)]
        for item in self.patches:item.start()
        try:route.RouteLocalFrontdoorTests.setUp(self)
        except BaseException:
            for item in reversed(self.patches):item.stop()
            raise

    def tearDown(self):
        try:route.RouteLocalFrontdoorTests.tearDown(self)
        finally:
            for item in reversed(self.patches):item.stop()

    def assert_terminal(self, state, reason=None, reflex=0):
        result = self.defend()
        self.assertEqual(result['state'], state, result)
        if reason:self.assertEqual(result['result']['reason'], reason, result)
        expected = ['follow_path'] + (['combat_entity'] if reflex else [])
        self.assertEqual([p['intent']['action'] for p in self.posts()], expected)
        self.assertIs(self.posts()[0]['intent']['route_stop_only'], True)
        self.assertFalse(self.bridge.moves)
        self.assertFalse(self.bridge.terrain_responses)
        self.assertEqual(result['evidence']['budget']['used']['ordinary']['actions'], 1)
        self.assertEqual(result['evidence']['budget']['used']['reflex']['actions'], reflex)
        if state != 'unknown':
            self.assertEqual(result['effect_certainty'], 'known', result)
            self.assertEqual(result['cleanup_certainty'], 'confirmed', result)
            self.assertIsNone(self.client.session()['capability_lease'])
        # The exact public ID must return the same terminal, never dispatch a replay.
        again = self.call('mdc_job', self.last_submit)
        self.assertEqual(again['job_id'], result['job_id'])
        self.assertEqual(again['state'], state)
        self.assertEqual([p['intent']['action'] for p in self.posts()], expected)
        return result

    def test_fast_large_proof(self):
        self.assert_terminal('interrupted', 'preempted_before_motion', reflex=1)

    def test_fast_generic_failure(self):
        self.assert_terminal('cancelled', 'local_segment_check_failed')
        self.assertNotIn('route_threat_stop', self.bridge.action['result'])

    def test_fast_oversize_proof(self):
        self.assert_terminal('cancelled', 'route_spatial_stop_evidence_too_large')

    def test_fast_oversize_frame(self):
        self.assert_terminal('cancelled', 'route_spatial_evidence_too_large')

    def assert_unknown(self):
        self.expected_mcp_exit = 2
        self.assert_terminal('unknown')

    def test_fast_failure_release_missing(self):self.assert_unknown()
    def test_fast_failure_unknown(self):self.assert_unknown()
    def test_fast_failure_effect(self):self.assert_unknown()
    def test_fast_failure_effect_outcome(self):self.assert_unknown()
    def test_fast_failure_identity(self):self.assert_unknown()
    def test_fast_failure_digest(self):self.assert_unknown()


if __name__ == '__main__':unittest.main()
