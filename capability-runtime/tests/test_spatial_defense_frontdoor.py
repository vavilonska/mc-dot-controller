"""Real public MCP/owner-chain tests; synthetic native endpoint, never live evidence."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import test_route_local_frontdoor as route
import test_route_defend_once_frontdoor as combined
import spatial_threat_fixture as spatial
from test_scoped_combat_chain import TARGET

PROFILE = 'movement-local-segment-spatial-threat-v1'


class Endpoint(combined.Endpoint):
    def __init__(self):
        super().__init__()
        if self.scenario in ('preempted_before_motion', 'preempted_overlap') or self.scenario.startswith('fast_'):
            self.hurt = True

    def snapshot(self):
        value = super().snapshot()
        value['scoped_native_preflight']['profiles'][PROFILE] = ['follow_path']
        # Threat preemption has no health loss; inherited flag only exposes target facts.
        value['player']['health'] = 20.
        if self.hurt and not self.defeated:
            row = value['nearby']['entities'][0]
            if self.scenario == 'later_preempted':
                row.update(x=self.pos['x'] + 1., z=self.pos['z'])
            row['native_living']['aggressive'] = True
            if row['native_living']['current_target'] is not None:
                row['native_living']['current_target']['entity_id'] = 1
            if self.scenario in ('stale_attacker', 'fast_stale_attacker'):
                row['native_living']['sample_age_ms'] = 251.
            elif self.scenario == 'fast_unknown_attacker':
                row['native_living']['known'] = False
            elif self.scenario == 'fast_clock_invalid':
                row['native_living']['source_nano'] = 'invalid'
            elif self.scenario == 'fast_context_changed':
                row['native_living']['world_generation'] = '55555555-5555-4555-8555-555555555555'
            elif self.scenario == 'attacker_replaced':
                row['entity_id'] = 10
                row['native_living']['entity_id'] = 10
            elif self.scenario == 'outside_reach':
                row['x'] = 4.
            elif self.scenario == 'airborne':
                value['player']['on_ground'] = False
            elif self.scenario == 'target_not_attacking':
                row['native_living']['current_target'] = None
            if self.scenario == 'fast_extra_attacker':
                other = deepcopy(row)
                other.update(uuid='55555555-5555-4555-8555-555555555555', entity_id=10)
                other['native_living'].update(entity_uuid=other['uuid'], entity_id=10)
                value['nearby']['entities'].append(other)
                value['nearby'].update(returned=2, total=2)
        return value

    def request(self, method, path, body=None):
        if (path.startswith('/control/action/status') and self.action.get('action') == 'follow_path'
                and self.action.get('status') == 'running'
                and self.scenario in ('calm_route', 'calm_wrong_profile', 'later_preempted')):
            value = combined.BaseEndpoint.request(self, method, path, body)
            if self.scenario == 'later_preempted':
                self.hurt = True
            if self.scenario == 'calm_wrong_profile':
                self.action['result']['local_segment']['profile'] = 'movement-local-segment-observed-v1'
                return deepcopy(self.action)
            return value
        if path == '/control/scoped-action' and body['intent']['action'] == 'follow_path':
            if self.scenario in ('admission_refusal', 'fast_target_disappeared', 'fast_corridor_rejected', 'fast_extra_attacker'):
                self.posts.append((path, deepcopy(body)))
                raise route.BridgeError('spatial_threat_unconfirmed', status=409, uncertain=False)
            if self.scenario in ('preempted_before_motion', 'preempted_overlap') or (self.scenario == 'later_preempted' and body['intent'].get('route_stop_only') is True):
                self.posts.append((path, deepcopy(body)))
                self.action, _, _, _ = spatial.fixture(body['intent'], body['preflight'],
                    block=self.block, stop_only=True, projected_overlap=self.scenario == 'preempted_overlap')
                self.action.update(action_schema_version=1, ok=True, server_confirmed=False)
                self.scopes.append(deepcopy(body['preflight']))
                self.actions.append(deepcopy(body['intent']))
                route.validate_scoped_witness(self.action, body['preflight'], body['intent']['action_id'], body['intent'])
                return deepcopy(self.action)
        value = super().request(method, path, body)
        if (path.startswith('/control/action/status') and self.action.get('action') == 'follow_path'
                and self.action.get('status') == 'cancelled'
                and self.action['result']['scoped_native_preflight']['profile'] == PROFILE):
            if self.scenario == 'admission_race':
                self.action['reason'] = 'route_spatial_pre_effect_attacker_changed'
                self.action['result']['local_segment'] = spatial.terminal(self.action, landed=False, effect_attempted=False)
                return deepcopy(self.action)
            self.action['reason'] = 'capability_threat_observed'
            self.action['result']['route_threat_stop'] = spatial.threat_stop(self.action)
            if self.scenario == 'wrong_terminal_uuid':
                self.action['result']['route_threat_stop']['target_uuid'] = '55555555-5555-4555-8555-555555555555'
            elif self.scenario == 'unknown_motion':
                self.action['result'].update(unknown_outcome=True, motion_gate_rejected=True)
            elif self.scenario == 'release_missing':
                self.action['result']['input_release_confirmed'] = False
            return deepcopy(self.action)
        return value


class SpatialDefenseFrontdoorTests(unittest.TestCase):
    until = route.RouteLocalFrontdoorTests.until
    rpc = route.RouteLocalFrontdoorTests.rpc
    call = route.RouteLocalFrontdoorTests.call
    submit = route.RouteLocalFrontdoorTests.submit
    finish = route.RouteLocalFrontdoorTests.finish
    posts = route.RouteLocalFrontdoorTests.posts
    defend = combined.RouteDefendOnceFrontdoorTests.defend

    def setUp(self):
        self.patches = [patch.object(route, 'Endpoint', Endpoint),
                        patch.object(route, 'fixture', spatial.fixture),
                        patch.object(route, 'terminal', spatial.terminal),
                        patch.object(combined, 'terminal', spatial.terminal)]
        for item in self.patches: item.start()
        try: route.RouteLocalFrontdoorTests.setUp(self)
        except BaseException:
            for item in reversed(self.patches): item.stop()
            raise

    def tearDown(self):
        try:
            if self.mode in ('unknown_motion', 'release_missing', 'wrong_terminal_uuid', 'calm_wrong_profile'):
                self.mode = 'lost_second'
            route.RouteLocalFrontdoorTests.tearDown(self)
        finally:
            for item in reversed(self.patches): item.stop()

    def test_spatial_transition(self):
        result = self.defend()
        self.assertEqual(result['state'], 'interrupted', result)
        self.assertEqual(result['result']['reason'], 'ordinary_task_interrupted_after_defense', result)
        posts = self.posts()
        self.assertEqual([p['intent']['action'] for p in posts], ['follow_path', 'combat_entity'])
        self.assertEqual(posts[0]['preflight']['profile'], PROFILE)
        self.assertEqual(posts[0]['intent']['route_threat_guard'], {'schema_version':1, 'target_uuid':TARGET})
        self.assertFalse(posts[1]['intent']['approach'])
        self.assertEqual(len({tuple(p['preflight'][k] for k in ('owner_id','owner_generation','job_id','defense_epoch')) for p in posts}), 1)
        self.assertEqual(result['evidence']['budget']['used']['ordinary']['actions'], 1)
        self.assertEqual(result['evidence']['budget']['used']['reflex']['actions'], 1)
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        self.assertFalse(self.bridge.moves)
        self.assertIsNone(self.client.session()['capability_lease'])
        repeated = self.call('mdc_job', self.last_submit)
        self.assertEqual(repeated['job_id'], result['job_id'])
        self.assertEqual(len(self.posts()), 2)

    def test_calm_route(self):
        result = self.defend()
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(result['result']['reason'], 'route_local_goal_observed', result)
        posts = self.posts()
        self.assertGreater(len(posts), 1)
        self.assertTrue(all(p['intent']['action'] == 'follow_path' and p['preflight']['profile'] == PROFILE for p in posts))
        self.assertEqual(len(self.bridge.moves), len(posts))
        self.assertEqual(result['evidence']['budget']['used']['reflex']['actions'], 0)
        self.assertTrue(all('route_stop_only' not in p['intent'] for p in posts))
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        self.assertIsNone(self.client.session()['capability_lease'])

    def test_later_preempted(self):
        result = self.defend()
        self.assertEqual(result['state'], 'interrupted', result)
        self.assertEqual(result['result']['reason'], 'preempted_before_motion', result)
        posts = self.posts()
        self.assertEqual([p['intent']['action'] for p in posts], ['follow_path', 'follow_path', 'combat_entity'])
        self.assertNotIn('route_stop_only', posts[0]['intent'])
        self.assertIs(posts[1]['intent']['route_stop_only'], True)
        self.assertEqual(len(self.bridge.moves), 1)
        self.assertEqual(result['evidence']['budget']['used']['ordinary']['actions'], 2)
        self.assertEqual(result['evidence']['budget']['used']['reflex']['actions'], 1)
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        self.assertIsNone(self.client.session()['capability_lease'])

    def test_calm_wrong_profile(self):
        result = self.defend()
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual([p['intent']['action'] for p in self.posts()], ['follow_path'])
        self.assertEqual(len(self.bridge.moves), 1)

    def assert_preempted(self):
        result = self.defend()
        self.assertEqual(result['state'], 'interrupted', result)
        self.assertEqual(result['result']['reason'], 'preempted_before_motion', result)
        self.assertEqual([p['intent']['action'] for p in self.posts()], ['follow_path', 'combat_entity'])
        self.assertFalse(self.bridge.moves)
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        self.assertIsNone(self.client.session()['capability_lease'])
        self.assertEqual(self.bridge.snapshot()['player']['health'], 20.)
        self.assertTrue(self.posts()[0]['intent']['route_stop_only'])
        self.assertFalse(self.bridge.terrain_responses)
        self.assertEqual(result['evidence']['budget']['used']['ordinary']['actions'], 1)
        self.assertEqual(result['evidence']['budget']['used']['reflex']['actions'], 1)
        self.assertEqual(len({tuple(p['preflight'][k] for k in ('owner_id','owner_generation','job_id','defense_epoch')) for p in self.posts()}), 1)
        repeated = self.call('mdc_job', self.last_submit)
        self.assertEqual(repeated['job_id'], result['job_id'])
        self.assertEqual(len(self.posts()), 2)

    def test_preempted_before_motion(self): self.assert_preempted()
    def test_preempted_overlap(self): self.assert_preempted()
    def test_admission_refusal(self): self.assert_no_attack()

    def assert_fast_refusal(self, dispatched=False):
        result = self.defend()
        self.assertEqual(result['state'], 'blocked', result)
        self.assertFalse(self.bridge.moves)
        self.assertFalse(self.bridge.terrain_responses)
        self.assertEqual(len(self.posts()), int(dispatched))
        if dispatched:
            self.assertIs(self.posts()[0]['intent']['route_stop_only'], True)
        self.assertEqual(result['cleanup_certainty'], 'confirmed')
        self.assertIsNone(self.client.session()['capability_lease'])

    def test_fast_target_disappeared(self): self.assert_fast_refusal(dispatched=True)
    def test_fast_corridor_rejected(self): self.assert_fast_refusal(dispatched=True)
    def test_fast_extra_attacker(self): self.assert_fast_refusal(dispatched=True)
    def test_fast_unknown_attacker(self): self.assert_fast_refusal()
    def test_fast_stale_attacker(self): self.assert_fast_refusal()
    def test_fast_clock_invalid(self): self.assert_fast_refusal()
    def test_fast_context_changed(self): self.assert_fast_refusal()

    def test_admission_race(self):
        result = self.defend()
        self.assertEqual(result['state'], 'cancelled', result)
        self.assertEqual(result['result']['reason'], 'route_spatial_pre_effect_attacker_changed', result)
        self.assertEqual([p['intent']['action'] for p in self.posts()], ['follow_path'])
        self.assertFalse(self.bridge.moves)
        self.assertEqual(result['cleanup_certainty'], 'confirmed')

    def test_default_stop(self):
        result = self.finish(self.submit())
        self.assertNotEqual(result['state'], 'succeeded', result)
        self.assertEqual(len(self.posts()), 1)
        self.assertNotIn('route_threat_guard', self.posts()[0]['intent'])
        self.assertEqual(self.posts()[0]['preflight']['profile'], 'movement-local-segment-observed-v1')

    def test_no_reserve(self):
        result = self.defend(budgets={'deadline_seconds':60,'max_actions':18,'max_observations':256,
                                     'cleanup_reserve_actions':1,'reflex_reserve_actions':0})
        self.assertEqual(result['state'], 'blocked', result)
        self.assertFalse(self.posts())

    def assert_no_attack(self, unknown=False):
        result = self.defend()
        self.assertEqual([p['intent']['action'] for p in self.posts()], ['follow_path'])
        self.assertEqual(result['state'], 'unknown' if unknown else 'blocked', result)
        self.assertFalse(self.bridge.moves)

    def test_stale_attacker(self): self.assert_no_attack()
    def test_attacker_replaced(self): self.assert_no_attack()
    def test_outside_reach(self): self.assert_no_attack()
    def test_airborne(self): self.assert_no_attack()
    def test_target_not_attacking(self): self.assert_no_attack()
    def test_wrong_terminal_uuid(self): self.assert_no_attack(unknown=True)
    def test_unknown_motion(self): self.assert_no_attack(unknown=True)
    def test_release_missing(self): self.assert_no_attack(unknown=True)


class SpatialDefenseLateStopTests(combined.late.DefenseLateStopTests):
    def setUp(self):
        self.patches = [patch.object(combined.late, 'Endpoint', Endpoint),
                        patch.object(route, 'fixture', spatial.fixture),
                        patch.object(combined, 'terminal', spatial.terminal)]
        for item in self.patches: item.start()
        try: super().setUp()
        except BaseException:
            for item in reversed(self.patches): item.stop()
            raise

    def tearDown(self):
        try: super().tearDown()
        finally:
            for item in reversed(self.patches): item.stop()

    def verify_stop(self,expected):
        d=self.backend.describe()
        result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'route-late-stop',
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':'navigate_route_local','capability_version':1,
            'arguments':{'goal':{'x':4,'y':64,'z':0},'radius':6,'max_segments':16,'min_health':12},
            'policy':{'version':1,'execution_mode':'request_only','reactions':'defend_once',
                'defense':{'target_uuid':TARGET,'timeout_ms':2000,'min_health':14}},
            'budgets':{'deadline_seconds':60,'max_actions':18,'max_observations':256,'reflex_reserve_actions':1,'cleanup_reserve_actions':1},'wait_ms':10000})
        self.assertTrue(self.stopped,result)
        self.assertEqual(result['state'],expected,result)
        self.assertEqual(result['effect_certainty'],'known')
        self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertIsNone(self.runtime.pending_request_id)
        self.assertIsNone(self.client.session()['capability_lease'])
        posts=[body for path,body in self.bridge.posts if path=='/control/scoped-action']
        self.assertEqual([body['intent']['action'] for body in posts],['follow_path'])
        self.assertEqual(posts[0]['preflight']['profile'],PROFILE)
        self.assertFalse(self.bridge.moves)
        records=[record for record in self.runtime._journal['records'].values() if record.get('skill')=='defense.engage_once']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['evidence']['submission_outcome'],'stopped_before_dispatch')


if __name__ == '__main__': unittest.main()
