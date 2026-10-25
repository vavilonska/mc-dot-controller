"""Real public Toolbox→Runtime→IntentClient→watchdog→Resident ownership chain.

Only the final native HTTP endpoint is synthetic. These tests do not execute
Minecraft, loaded mixins, projectile physics, or ordinary-world combat.
"""
from copy import deepcopy
from importlib.util import module_from_spec,spec_from_file_location
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch
import base_watchdog
import test_capability_ownership as owners
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError

_TESTS=Path(__file__).resolve().parents[2]/'resident-controller/tests'
if str(_TESTS) not in sys.path:sys.path.insert(0,str(_TESTS))
from target_action_witness_fixture import fixture,terminal,TARGET
from combat_witness_fixture import reseal
from mdc_skills.scoped_target_action import PROFILE


def target_witness(intent,scope):
    native,_,_,_=fixture(intent['action']=='shoot_entity')
    w=native['result']['scoped_native_preflight'];f=w['facts'];t=f['target_action']
    w.update(scope);w.update(action_id=intent['action_id'],action_session=intent['expected_action_session'],
        source_tick=intent['capability_guard']['source_tick']+1,
        source_nano=str(int(intent['capability_guard']['source_nano'])+1),
        admitted_nano=str(int(intent['capability_guard']['source_nano'])+21))
    f['context'].update({k:intent['expected_'+k] for k in ('world_generation','dimension','player_uuid','action_session')})
    w['context']=deepcopy(f['context']);f['selected_slot']=intent['expected_hotbar_slot']
    held={k:v for k,v in intent['expected_held_item'].items() if k!='slot'}
    f['inventory'][f['selected_slot']]['item']=deepcopy(held);f['equipment']['mainhand']=deepcopy(held)
    f['menu']['slots'][36+f['selected_slot']]['item']=deepcopy(held)
    if 'expected_origin' in intent:f.update(intent['expected_origin'])
    for k in ('action','target_entity_id','target_uuid','target_type','min_health','timeout_ms'):t[k]=intent[k]
    t['deadline_nano']=str(int(w['source_nano'])+intent['timeout_ms']*1000000)
    t['species']={'type':intent['target_type']}
    row=t['entity_frame']['entities'][1];row.update(id=intent['target_entity_id'],uuid=intent['target_uuid'],type=intent['target_type'])
    t['entity_frame']['entities'][0]['uuid']=intent['expected_player_uuid']
    if intent['target_type']=='minecraft:ender_dragon':
        t['dragon_phase']=intent['expected_dragon_phase'];t['species'].update(phase=intent['expected_dragon_phase'],head_entity_id=19)
    if intent['target_type']=='minecraft:enderman':t['species']['shelter_safe']=True
    if intent['target_type']=='minecraft:end_crystal':
        t.update(x=13.5,target_health=0.);row.update(x=13.5,living=False,aabb=[12.5,64.,-.5,14.5,66.,1.5])
    native.update(action_id=intent['action_id'],action_session=intent['expected_action_session'],action=intent['action'],
        ok=True,action_schema_version=1,status='running',reason='synthetic_target_admitted',server_confirmed=False)
    reseal((native,scope,intent['action_id'],intent));return native


class Endpoint(owners.CombatEndpoint):
    def __init__(self):
        super().__init__();self.target_mode='success';self.fixture_error=None;self.advertise=True;self.ranged=False;self.crystal=False
        self.intent=None;self.dragon_phase=None;self.enderman=False;self.sheltered=True;self.sword=False
        self.entities=[dict(uuid=TARGET,entity_id=9,type='minecraft:zombie',alive=True,health=20.,x=2.5,y=64.,z=.5)]
    def snapshot(self):
        s=super().snapshot()
        for row in s['player']['inventory']:
            row.update(item_fingerprint='11111111-1111-4111-8111-111111111111',component_fingerprint='11111111-1111-4111-8111-111111111111',max_stack_size=0)
        s['player']['inventory'][0].update(id='minecraft:bow' if self.ranged else 'minecraft:iron_axe',
            item_fingerprint='22222222-2222-4222-8222-222222222222',component_fingerprint='22222222-2222-4222-8222-222222222222',max_stack_size=1)
        if self.sword:s['player']['inventory'][0]['id']='minecraft:iron_sword'
        if self.dragon_phase is not None:s['nearby']['entities'][0].update(type='minecraft:ender_dragon',phase_id=self.dragon_phase)
        if self.enderman:
            s['nearby']['entities'][0]['type']='minecraft:enderman'
            s['player']['enderman_shelter']={'schema_version':1,'safe':self.sheltered}
        if self.ranged:
            s['player']['inventory'][1].update(id='minecraft:arrow',count=8,empty=False,max_stack_size=64)
            s['nearby']['entities'][0]['x']=12.5
        if self.crystal:
            s['world']['dimension']=s['player']['dimension']='minecraft:the_end'
            s['nearby']['entities'][0].update(type='minecraft:end_crystal',x=13.5)
        s['nearby']['loaded_chunks']=[{'x':0,'z':0,'loaded':True}]
        if self.action['status']=='succeeded' and self.target_mode!='no_damage':
            if self.crystal or self.target_mode=='missing':s['nearby']['entities']=[];s['nearby'].update(returned=0,total=0)
            else:s['nearby']['entities'][0]['health']=16.
        s['scoped_native_preflight']={'version':'scoped-native-preflight/1','private_singleplayer_only':True,
            'same_callback_capture_validate_admit':True,'capability_guard_schema_version':1,
            'profiles':{PROFILE:['attack_entity','shoot_entity']} if self.advertise else {},
            'guarded_actions':['attack_entity','shoot_entity']}
        return s
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)));self.intent=deepcopy(body['intent']);self.action=target_witness(self.intent,body['preflight'])
            try:validate_scoped_witness(self.action,body['preflight'],self.intent['action_id'],self.intent)
            except ValueError as exc:self.fixture_error=str(exc)
            if self.target_mode=='lost':raise BridgeError('synthetic_lost_target_submit',uncertain=True)
            return deepcopy(self.action)
        if path.startswith('/control/action/status') and self.intent is not None and self.action['status']=='running' and not self.hold:
            terminal(self.action,self.intent)
            if self.target_mode=='bad_packet':self.action['result']['target_scope']['offense_packets']=2
            if self.target_mode=='unknown_release':self.action['result'].update(unknown_outcome=True,input_release_confirmed=False)
            return deepcopy(self.action)
        if path=='/control/action/cancel' and self.target_mode=='cancel_draw':
            self.posts.append((path,deepcopy(body)));self.action.update(status='cancelled',reason='cancel_requested')
            self.action['result'].update(unknown_outcome=True,input_release_confirmed=False)
            return deepcopy(self.action)
        return super().request(method,path,body)


class PublicTargetChainTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    def setUp(self):
        environment=patch.dict(os.environ,{'PYTHONDONTWRITEBYTECODE':'1'})
        environment.start();self.addCleanup(environment.stop)
        run=base_watchdog.run
        def request_only(*args,**kwargs):kwargs['execution_policy']='request_only';return run(*args,**kwargs)
        def endpoint():
            value=Endpoint()
            # Establish the End context before owner loops start. Changing dimension
            # after readiness correctly triggers the real gateway transition fence.
            if self._testMethodName=='test_single_crystal_removal_owner_chain':value.ranged=value.crystal=True
            if self._testMethodName.startswith('test_dragon_phase_'):value.dragon_phase=int(self._testMethodName.rsplit('_',1)[1])
            if self._testMethodName in ('test_sheltered_enderman_owner_chain','test_unsheltered_enderman_no_submit'):
                value.enderman=True;value.sheltered=self._testMethodName.startswith('test_sheltered')
            if self._testMethodName=='test_sword_refused_before_submit':value.sword=True
            return value
        with patch.object(owners,'CombatEndpoint',endpoint),patch.object(base_watchdog,'run',request_only):
            owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'target-runtime',wait_timeout=2)
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'toolbox')
    def tearDown(self):
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,capability='strike',**arguments):
        d=self.backend.describe();self.assertIn(capability,d['supported_capabilities'],d)
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'target_one',
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':capability,'capability_version':1,
            'arguments':{'target_uuid':TARGET,**arguments},
            'policy':{'version':1,'execution_mode':'request_only','reactions':'stop'},
            'budgets':{'max_actions':2,'max_observations':30,'deadline_seconds':10},'wait_ms':0})
    def finish(self,r):
        self.assertIn('job_id',r,r)
        def done():
            self.result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','job_id':r['job_id'],'session_ref':r['session_ref']})
            return self.result['state'] not in ('accepted','running','stopping')
        self.until(done,timeout=12);return self.result
    def assert_one_scoped(self):
        posts=[b for p,b in self.bridge.posts if p=='/control/scoped-action'];self.assertEqual(len(posts),1)
        self.assertEqual(posts[0]['preflight']['profile'],PROFILE);self.assertEqual(posts[0]['intent']['target_uuid'],TARGET)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action'])
    def test_single_melee_owner_chain(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        self.assert_one_scoped();self.assertIsNone(self.client.session()['capability_lease'])
    def test_single_bow_owner_chain(self):
        self.bridge.ranged=True
        result=self.finish(self.submit(ranged=True));self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result));self.assert_one_scoped()
    def test_single_crystal_removal_owner_chain(self):
        self.bridge.ranged=self.bridge.crystal=True
        result=self.finish(self.submit('remove_crystal'));self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result));self.assert_one_scoped()
    def test_dragon_phase_6(self):
        result=self.finish(self.submit(expected_dragon_phase=6));self.assertEqual(result['state'],'succeeded',result);self.assert_one_scoped()
        self.assertEqual(self.bridge.intent['expected_dragon_phase'],6)
    def test_dragon_phase_7(self):
        result=self.finish(self.submit(expected_dragon_phase=7));self.assertEqual(result['state'],'succeeded',result);self.assert_one_scoped()
    def test_sheltered_enderman_owner_chain(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result);self.assert_one_scoped()
        self.assertIs(self.bridge.intent['enderman_shelter_required'],True)
    def test_unsheltered_enderman_no_submit(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'blocked',result)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/scoped-action'])
    def test_sword_refused_before_submit(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'blocked',result)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/scoped-action'])
    def test_lost_submit_unknown_no_retry(self):
        self.bridge.target_mode='lost';result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result);self.assert_one_scoped()
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
    def test_missing_living_target_is_not_death(self):
        self.bridge.target_mode='missing';result=self.finish(self.submit());self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_scoped()
    def test_double_packet_evidence_rejected(self):
        self.bridge.target_mode='bad_packet';result=self.finish(self.submit());self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_scoped()
    def test_unknown_release_quarantines(self):
        self.bridge.ranged=True;self.bridge.target_mode='unknown_release';result=self.finish(self.submit(ranged=True));self.assertEqual(result['state'],'unknown',result);self.assert_one_scoped()
    def test_cancel_during_draw_exact_id_no_release_retry(self):
        self.bridge.ranged=True;self.bridge.hold=True;self.bridge.target_mode='cancel_draw';r=self.submit(ranged=True)
        self.until(lambda:any(p=='/control/scoped-action' for p,b in self.bridge.posts))
        self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':r['job_id'],'session_ref':r['session_ref'],'cancel_request_id':'stop_draw','wait_ms':1000})
        result=self.finish(r);self.assertEqual(result['state'],'unknown',result);self.assert_one_scoped()
        cancels=[b for p,b in self.bridge.posts if p=='/control/action/cancel'];self.assertEqual(len(cancels),1)
        self.assertEqual(cancels[0]['action_id'],self.bridge.action['action_id'])
    def test_no_profile_no_target_primitives_or_composites(self):
        self.bridge.advertise=False;self.until(lambda:'strike' not in self.backend.describe()['supported_capabilities'])
        supported=self.backend.describe()['supported_capabilities']
        for name in ('strike','remove_crystal','defeat','hunt_resource','end_battle','end_expedition'):self.assertNotIn(name,supported)

if __name__=='__main__':unittest.main()
