"""Production MCP -> Python Runtime -> Intent/Watchdog/Resident; synthetic Bridge only."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
import test_step_down_frontdoor as front
from test_scoped_combat_chain import combat_witness, TARGET
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError

CANDIDATE=Path(__file__).resolve().parents[2]
BaseEndpoint=front.Endpoint


class Endpoint(BaseEndpoint):
    def __init__(self):
        super().__init__();self.scenario=self.mode_name;self.mode_name='flat_regression';self.hurt=False;self.defeated=False
    def snapshot(self):
        value=super().snapshot()
        value['scoped_native_preflight']['profiles']['combat-local-observed-v1']=['combat_entity']
        value['scoped_native_preflight']['guarded_actions'].append('combat_entity')
        if self.hurt:
            value['player']['health']=18.
            world=value['world'];guard=value['capability_guard'];tick=world['game_time'];nano=guard['source_nano']
            row={'uuid':TARGET,'entity_id':9,'type':'minecraft:zombie','alive':not self.defeated,
                'health':0. if self.defeated else 20.,'x':2.5,'y':64.,'z':.5}
            row['native_living']={'schema_version':1,'entity_uuid':TARGET,'entity_id':9,'entity_type':row['type'],
                'dimension':world['dimension'],'world_generation':world['world_generation'],'player_uuid':value['player']['uuid'],
                'known':True,'coverage_complete':True,'inspected':1,'source':'integrated_server_tick','reason':'observed',
                'alive':not self.defeated,'current_target_known':True,
                'current_target':{'uuid':value['player']['uuid'],'type':'minecraft:player'},
                'sample_tick':tick,'source_tick':tick,'source_nano':nano,'sample_nano':nano,'sample_age_ms':0.}
            if self.scenario == 'unknown_target':row['native_living']['current_target']=None
            value['nearby']={'entities':[row],'returned':1,'total':1,'truncated':False}
        return value
    def request(self,method,path,body=None):
        if path=='/control/scoped-action' and body['intent']['action']=='combat_entity':
            self.posts.append((path,deepcopy(body)));self.action=combat_witness(body['intent'],body['preflight'])
            validate_scoped_witness(self.action,body['preflight'],body['intent']['action_id'],body['intent'])
            if self.scenario == 'unknown_defense':raise BridgeError('synthetic_defense_submit_lost',uncertain=True)
            return deepcopy(self.action)
        if path.startswith('/control/action/status') and self.action['status']=='running':
            if self.action['action']=='follow_path':
                self.hurt=True;self.action.update(status='cancelled',reason='capability_damage_observed')
                if self.scenario=='unknown_motion_gate':self.action.update(reason='motion_gate_rejected',unknown_outcome=True)
            else:
                self.defeated=True;self.action.update(status='succeeded',reason='synthetic_target_dead')
            self.action['result']['input_release_confirmed']=True
            return deepcopy(self.action)
        response=super().request(method,path,body)
        if path=='/control/scoped-action' and self.scenario == 'unknown_original':
            raise BridgeError('synthetic_original_submit_lost',uncertain=True)
        return response


class DefendOnceFrontdoorTests(unittest.TestCase):
    until=front.StepDownFrontdoorTests.until
    call=front.StepDownFrontdoorTests.call
    submit=front.StepDownFrontdoorTests.submit
    finish=front.StepDownFrontdoorTests.finish
    posts=front.StepDownFrontdoorTests.posts
    def tearDown(self):
        if self.mode in ('unknown_original','unknown_defense','unknown_motion_gate'):self.mode='lost'
        front.StepDownFrontdoorTests.tearDown(self)
    def setUp(self):
        with patch.object(front,'Endpoint',Endpoint),patch.object(front,'ROOT',CANDIDATE):
            front.StepDownFrontdoorTests.setUp(self)
    def defend(self, **changes):
        arguments=dict(capability='navigate_local',arguments={'goal':{'x':1,'y':64,'z':0}},
            policy={'version':1,'execution_mode':'request_only','reactions':'defend_once',
                'defense':{'target_uuid':TARGET,'timeout_ms':2000,'min_health':14}},
            budgets={'deadline_seconds':60,'max_actions':3,'max_observations':40,'cleanup_reserve_actions':1,'reflex_reserve_actions':1})
        arguments.update(changes)
        return self.finish(self.submit(**arguments))
    def test_defense_transition(self):
        result=self.defend()
        self.assertEqual(result['state'],'interrupted',result)
        self.assertEqual(result['result']['reason'],'ordinary_task_interrupted_after_defense',result)
        self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual([p['intent']['action'] for p in self.posts()],['follow_path','combat_entity'])
        self.assertEqual(self.posts()[1]['intent']['target_uuid'],TARGET)
        self.assertFalse(self.posts()[1]['intent']['approach'])
        self.assertIsNone(self.client.session()['capability_lease'])
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action'])

    def test_stop_default(self):
        result=self.defend(policy={'version':1,'execution_mode':'request_only','reactions':'stop'})
        self.assertEqual(result['state'],'cancelled',result)
        self.assertEqual([p['intent']['action'] for p in self.posts()],['follow_path'])
    def test_no_reserve(self):
        result=self.defend(budgets={'deadline_seconds':60,'max_actions':2,'max_observations':40,
            'cleanup_reserve_actions':1,'reflex_reserve_actions':0})
        self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())
    def test_unknown_target(self):
        result=self.defend();self.assertEqual(result['state'],'blocked',result)
        self.assertEqual([p['intent']['action'] for p in self.posts()],['follow_path'])
    def test_unknown_original(self):
        result=self.defend();self.assertEqual(result['state'],'unknown',result)
        self.assertEqual([p['intent']['action'] for p in self.posts()],['follow_path'])
    def test_unknown_motion_gate(self):
        result=self.defend();self.assertEqual(result['state'],'unknown',result)
        self.assertEqual([p['intent']['action'] for p in self.posts()],['follow_path'])
    def test_unknown_defense(self):
        result=self.defend();self.assertEqual(result['state'],'unknown',result)
        self.assertEqual([p['intent']['action'] for p in self.posts()],['follow_path','combat_entity'])

if __name__=='__main__':unittest.main()
