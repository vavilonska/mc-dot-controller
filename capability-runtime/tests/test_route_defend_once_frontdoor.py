"""Combined production MCP route→defense handoff. Synthetic Bridge, never Minecraft."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import test_route_local_frontdoor as route
import test_defend_once_frontdoor as defense
import test_defense_late_stop as late
from test_scoped_combat_chain import combat_witness, TARGET
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError
from local_segment_fixture import terminal

BaseEndpoint=route.Endpoint


class Endpoint(BaseEndpoint):
    def __init__(self):
        super().__init__();self.scenario=self.mode_name;self.mode_name='success_obstacle_terrace';self.hurt=False;self.defeated=False
    def snapshot(self):
        value=super().snapshot()
        value['scoped_native_preflight']['profiles']['combat-local-observed-v1']=['combat_entity']
        value['scoped_native_preflight']['guarded_actions'].append('combat_entity')
        if self.hurt:
            value['player']['health']=18.
            world=value['world'];guard=value['capability_guard'];tick=world['game_time'];nano=guard['source_nano']
            row={'uuid':TARGET,'entity_id':9,'type':'minecraft:zombie','alive':not self.defeated,
                'health':0. if self.defeated else 20.,'x':1.5,'y':64.,'z':.5}
            row['native_living']={'schema_version':1,'entity_uuid':TARGET,'entity_id':9,'entity_type':row['type'],
                'dimension':world['dimension'],'world_generation':world['world_generation'],'player_uuid':value['player']['uuid'],
                'known':True,'coverage_complete':True,'inspected':1,'source':'integrated_server_tick','reason':'observed',
                'alive':not self.defeated,'current_target_known':True,
                'current_target':{'uuid':value['player']['uuid'],'type':'minecraft:player'},
                'sample_tick':tick,'source_tick':tick,'source_nano':nano,'sample_nano':nano,'sample_age_ms':0.}
            if self.scenario=='unknown_target':row['native_living']['current_target']=None
            value['nearby']={'entities':[row],'returned':1,'total':1,'truncated':False}
        return value
    def request(self,method,path,body=None):
        if path=='/control/scoped-action' and body['intent']['action']=='combat_entity':
            self.posts.append((path,deepcopy(body)));self.action=combat_witness(body['intent'],body['preflight'])
            self.scopes.append(deepcopy(body['preflight']))
            validate_scoped_witness(self.action,body['preflight'],body['intent']['action_id'],body['intent'])
            if self.scenario=='unknown_defense':raise BridgeError('synthetic_defense_submit_lost',uncertain=True)
            return deepcopy(self.action)
        if path.startswith('/control/action/status') and self.action['status']=='running':
            if self.action['action']=='follow_path':
                self.hurt=True;self.action.update(status='cancelled',reason='capability_damage_observed')
                self.action['result']['local_segment']=terminal(self.action,landed=False)
                if self.scenario=='unknown_motion_gate':
                    self.action.update(reason='local_segment_motion_gate_velocity_changed')
                    self.action['result'].update(unknown_outcome=True,motion_gate_rejected=True)
            else:
                self.defeated=True;self.action.update(status='succeeded',reason='synthetic_target_dead')
            self.action['result']['input_release_confirmed']=True
            return deepcopy(self.action)
        response=super().request(method,path,body)
        if path=='/control/scoped-action' and self.scenario=='unknown_original':
            raise BridgeError('synthetic_original_submit_lost',uncertain=True)
        return response


class RouteDefendOnceFrontdoorTests(defense.DefendOnceFrontdoorTests):
    rpc=route.RouteLocalFrontdoorTests.rpc
    call=route.RouteLocalFrontdoorTests.call
    submit=route.RouteLocalFrontdoorTests.submit
    finish=route.RouteLocalFrontdoorTests.finish
    posts=route.RouteLocalFrontdoorTests.posts
    def setUp(self):
        with patch.object(route,'Endpoint',Endpoint):route.RouteLocalFrontdoorTests.setUp(self)
    def tearDown(self):
        if self.mode in ('unknown_original','unknown_defense','unknown_motion_gate'):self.mode='lost_second'
        route.RouteLocalFrontdoorTests.tearDown(self)
    def defend(self,**changes):
        arguments=dict(capability='navigate_route_local',arguments={'goal':{'x':4,'y':64,'z':0},'radius':6,'max_segments':16,'min_health':12},
            policy={'version':1,'execution_mode':'request_only','reactions':'defend_once',
                'defense':{'target_uuid':TARGET,'timeout_ms':2000,'min_health':14}},
            budgets={'deadline_seconds':60,'max_actions':18,'max_observations':256,'cleanup_reserve_actions':1,'reflex_reserve_actions':1})
        arguments.update(changes)
        return self.finish(self.submit(**arguments))
    def test_defense_transition(self):
        result=self.defend()
        self.assertEqual(result['state'],'interrupted',result)
        self.assertEqual(result['result']['reason'],'ordinary_task_interrupted_after_defense',result)
        self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual([p['intent']['action'] for p in self.posts()],['follow_path','combat_entity'])
        self.assertEqual([p['preflight']['profile'] for p in self.posts()],['movement-local-segment-observed-v1','combat-local-observed-v1'])
        self.assertEqual(len({tuple(p['preflight'][k] for k in ('owner_id','owner_generation','job_id','defense_epoch')) for p in self.posts()}),1)
        self.assertEqual(result['evidence']['budget']['used']['ordinary']['actions'],1)
        self.assertEqual(result['evidence']['budget']['used']['reflex']['actions'],1)
        self.assertFalse(self.bridge.moves)
        self.assertEqual(self.bridge.pos,{'x':.5,'y':64.,'z':.5})
        self.assertIsNone(self.client.session()['capability_lease'])
        repeated=self.call('mdc_job',self.last_submit)
        self.assertEqual(repeated['job_id'],result['job_id']);self.assertEqual(len(self.posts()),2)
    def test_route_keeps_request_only(self):
        result=self.defend(policy={'version':1,'execution_mode':'guarded','reactions':'defend_once',
            'defense':{'target_uuid':TARGET,'timeout_ms':2000,'min_health':14}})
        self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())

class RouteDefenseLateStopTests(late.DefenseLateStopTests):
    def setUp(self):
        with patch.object(late,'Endpoint',Endpoint):late.DefenseLateStopTests.setUp(self)
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
        self.assertEqual(posts[0]['preflight']['profile'],'movement-local-segment-observed-v1')
        self.assertFalse(self.bridge.moves)
        records=[record for record in self.runtime._journal['records'].values() if record.get('skill')=='defense.engage_once']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['evidence']['submission_outcome'],'stopped_before_dispatch')

if __name__=='__main__':unittest.main()
