"""Historical route planning through real MCP/owner IPC; native endpoints are synthetic.

These checks do not execute Minecraft or prove live native geometry/physics.
Delayed pages and native admission refusals are explicit synthetic inputs.
"""
from copy import deepcopy
import gzip
import hashlib
import json
import time
import unittest

from mdc_skills import scoped_route_local as route
from mdc_skills.core import Survey
from resident_controller.transport import BridgeError
import test_route_local_frontdoor as frontdoor
import test_route_local_planner as planner


class RouteSurveyAuthorityTests(unittest.TestCase):
    def test_history_never_becomes_last_observation_on_planning_refusal(self):
        runtime = planner.Runtime()
        out = route.navigate_route_local(runtime, {'x': 7, 'y': 64, 'z': 0})
        self.assertEqual(out.reason, 'route_local_original_bounds_exceeded')
        self.assertIsNone(out.last_observation)
        self.assertEqual(runtime.calls[0][0], 'survey')
        self.assertFalse(runtime.actions)

    def test_original_historical_hash_age_and_page_metadata_are_explicit(self):
        runtime = planner.Runtime()
        out = route.navigate_route_local(runtime, {'x': 1, 'y': 64, 'z': 0})
        self.assertTrue(out.ok, out)
        source = out.evidence['plans'][0]
        self.assertEqual(source['source_kind'], 'historical_survey')
        self.assertEqual(source['survey_id'], 'survey-1')
        self.assertNotIn('observation_id', source)
        self.assertEqual(source['captured_at'], 101.)
        self.assertGreater(source['acquisition_seconds'], .8)
        self.assertGreater(source['age_seconds_at_plan'], .8)
        self.assertTrue(source['age_diagnostic_only'])
        self.assertIs(source['freshness_authority'], False)
        self.assertRegex(source['source_payload_sha256'], '^[a-f0-9]{64}$')
        self.assertFalse(isinstance(out.last_observation, Survey))
        self.assertEqual([c[0] for c in runtime.calls], ['survey', 'observe', 'execute'])
        self.assertFalse(isinstance(runtime.calls[-1][3]['before'], Survey))

    def test_modified_survey_is_rejected_before_fresh_read_or_action(self):
        runtime = planner.Runtime()
        original = runtime.survey
        def tampered(**options):
            result = original(**options)
            result.terrain['cells'][0]['id'] = 'minecraft:lava'
            return result
        runtime.survey = tampered
        out = route.navigate_route_local(runtime, {'x': 1, 'y': 64, 'z': 0})
        self.assertEqual(out.reason, 'invalid_synthetic_survey')
        self.assertIsNone(out.last_observation)
        self.assertEqual(len(runtime.calls), 1)
        self.assertFalse(runtime.actions)


class RouteSurveyMcpTests(unittest.TestCase):
    # Reuse the exact production Node stdio/configured-Python/Runtime/Intent/
    # Watchdog/Resident harness without inheriting or duplicating its tests.
    until = frontdoor.RouteLocalFrontdoorTests.until
    rpc = frontdoor.RouteLocalFrontdoorTests.rpc
    call = frontdoor.RouteLocalFrontdoorTests.call
    submit = frontdoor.RouteLocalFrontdoorTests.submit
    finish = frontdoor.RouteLocalFrontdoorTests.finish
    posts = frontdoor.RouteLocalFrontdoorTests.posts
    tearDown = frontdoor.RouteLocalFrontdoorTests.tearDown

    def setUp(self):
        frontdoor.RouteLocalFrontdoorTests.setUp(self)
        self.expected_mcp_exit = 2 if self.mode == 'mixed_action_session' else 0
        self.pages = 0
        self.terrain_complete = False
        self.states_after_pages = 0
        self.native_geometry_changed = False
        original = self.bridge.request
        def request(method, path, body=None):
            if path.startswith('/control/terrain?'):
                # Explicit synthetic T35-like cost: total paging 971 ms plus
                # 46 ms state capture; not a real-game performance guarantee.
                time.sleep(.971/2)
                self.pages += 1
                if self.mode == 'changed_between_pages' and self.pages == 2:
                    self.native_geometry_changed = True
                if self.mode == 'mixed_action_session' and self.pages == 2:
                    self.bridge.action['action_session'] = '99999999-9999-4999-8999-999999999999'
                value = original(method, path, body)
                if self.mode == 'mixed_world' and self.pages == 2:
                    value['world_generation'] = '99999999-9999-4999-8999-999999999999'
                self.terrain_complete = value.get('complete') is True
                return value
            if path.startswith('/control/capability-snapshot?') and self.terrain_complete:
                time.sleep(.046)
                self.states_after_pages += 1
                # First is scan C, second is the new independent state preflight.
                if self.states_after_pages == 2:
                    if self.mode == 'fresh_state_still_expires': time.sleep(.85)
                    if self.mode == 'changed_after_plan': self.native_geometry_changed = True
            if path == '/control/scoped-action':
                if self.mode == 'changed_before_segment': self.native_geometry_changed = True
                if self.native_geometry_changed:
                    self.bridge.posts.append((path, deepcopy(body)))
                    raise BridgeError('local_segment_clearance_or_hazard_changed', status=409, uncertain=False)
            return original(method, path, body)
        self.bridge.request = request

    def route_once(self):
        return self.finish(self.submit(arguments={
            'goal': {'x': 1, 'y': 64, 'z': 0}, 'radius': 6, 'max_segments': 1, 'min_health': 12}))

    def records(self):
        return json.loads((self.root/'runtime'/'execution.json').read_text())['records']

    def receipt(self, record):
        ref = record['receipt_ref']
        raw = gzip.decompress((self.root/'runtime'/ref['file']).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ref['sha256'])
        return json.loads(raw)

    def test_slow_survey_succeeds(self):
        result = self.route_once()
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(len(self.bridge.moves), 1)
        self.assertEqual(self.pages, 2)
        records = self.records()
        survey = next(r for r in records.values() if r['kind'] == 'survey')
        source = result['result']['evidence']['plans'][0]
        payload = self.receipt(survey)['result']
        self.assertTrue(survey['command']['capability_survey'])
        self.assertEqual(survey['status'], 'succeeded')
        self.assertEqual(survey['reason'], 'historical_region_survey')
        self.assertEqual(source['survey_id'], survey['request_id'])
        self.assertEqual(source['source_payload_sha256'], hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest())
        self.assertGreater(source['acquisition_seconds'], 1.)
        self.assertGreater(source['age_seconds_at_plan'], .8)
        self.assertLessEqual(source['captured_at'], payload['terrain']['capture_started_mono'])
        self.assertEqual(source['capture_started_mono'], payload['terrain']['capture_started_mono'])
        self.assertEqual(source['capture_finished_mono'], payload['terrain']['capture_finished_mono'])
        self.assertEqual(source['source_page_count'], 2)
        self.assertEqual(len(payload['terrain']['source_pages']), 2)
        self.assertIs(source['freshness_authority'], False)
        mutation = next(r for r in records.values() if r['kind'] == 'mutation')
        self.assertGreater(mutation['before_tick'], payload['state']['world']['game_time'])
        # Journal maps may be key-sorted on disk; bind by original source tick,
        # not dictionary order or the mutation's receipt-arrival timestamp.
        matching = [r for r in records.values() if r['kind'] == 'observation'
                    and self.receipt(r)['result']['state']['world']['game_time'] == mutation['before_tick']]
        self.assertEqual(len(matching), 1)
        prior = matching[0]
        self.assertEqual(mutation['command']['capability_guard'],
                         self.receipt(prior)['result']['state']['capability_guard'])
        self.assertFalse(prior['command'].get('terrain', False))
        self.assertEqual(prior['observation_acquisition']['max_age_seconds'], .8)
        self.assertLess(prior['observation_acquisition']['checkpoints_ms']['freshness_checked'], 800.)

    def test_fresh_state_still_expires(self):
        result = self.route_once()
        self.assertEqual(result['state'], 'blocked', result)
        self.assertEqual(result['result']['reason'], 'observation_acquisition_stale')
        self.assertFalse(self.posts())
        self.assertFalse(self.bridge.moves)
        self.assertEqual(result['effect_certainty'], 'none_proven')
        self.assertEqual(len([r for r in self.records().values() if r['kind'] == 'survey']), 1)

    def assert_changed_geometry_refused(self):
        result = self.route_once()
        self.assertEqual(result['state'], 'blocked', result)
        self.assertEqual(result['effect_certainty'], 'none_proven')
        self.assertEqual(len(self.posts()), 1)
        self.assertFalse(self.bridge.moves)
        self.assertEqual(result['result']['evidence']['completed_segments'], 0)
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        self.assertEqual(len([r for r in self.records().values() if r['kind'] == 'survey']), 1)
        self.assertFalse([p for p, _ in self.bridge.posts if p == '/control/action'])

    def test_changed_between_pages(self): self.assert_changed_geometry_refused()
    def test_changed_after_plan(self): self.assert_changed_geometry_refused()
    def test_changed_before_segment(self): self.assert_changed_geometry_refused()

    def assert_mixed_context_refused(self):
        result = self.route_once()
        self.assertNotEqual(result['state'], 'succeeded', result)
        self.assertFalse(self.posts())
        self.assertFalse(self.bridge.moves)
        self.assertEqual(result['result']['evidence']['completed_segments'], 0)

    def test_mixed_world(self): self.assert_mixed_context_refused()
    def test_mixed_action_session(self): self.assert_mixed_context_refused()


if __name__ == '__main__': unittest.main()
