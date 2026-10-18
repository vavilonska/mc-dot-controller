"""Actual public/owner chain with fabricated native replies; no game or network."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from mining_collect.bootstrap import load_owner_fixture
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.transport import BridgeError
from resident_controller.capability_snapshot import validate_scoped_witness
from .collect_fixture import collect_fixture, redigest, UUID, FP
from .movement_fixture import movement_fixture

owner_fixture = load_owner_fixture()

PROFILE='collect-local-observed-v1'

def bound_fixture(intent,scope):
    native,_,_,_=movement_fixture(intent,scope)
    template=collect_fixture()[0]['result']['scoped_native_preflight']['facts']['movement']
    w=native['result']['scoped_native_preflight'];m=w['facts']['movement'];m['profile']=PROFILE
    for k in ('entity_limit','live_other_entities','entity_scope'):m.pop(k)
    m['pickup_target']={**deepcopy(intent['pickup_target']),'simple_components':True,
                        'on_ground':True,'resting_envelope':'vanilla-grounded-item-v1'}
    m['entity_guard']=deepcopy(template['entity_guard'])
    m['entity_guard'].update(source_tick=w['source_tick'],source_nano=w['source_nano'])
    redigest(native,intent)
    return native

class CollectEndpoint(owner_fixture.CombatEndpoint):
    def __init__(self):
        super().__init__();self.collect_mode='success';self.fixture_error=None;self.advertise=True;self.collected=False;self.collect_item='minecraft:coal'
    def snapshot(self):
        state=super().snapshot()
        state['player']['inventory_total']=36
        for row in state['player']['inventory']:
            row.update(id='',count=0,empty=True,item_fingerprint=FP,component_fingerprint=FP,max_stack_size=0,identity_complete=True)
        if self.collected and self.collect_mode not in ('removed','cancel'):
            state['player']['inventory'][0].update(id=self.collect_item,count=3,empty=False,max_stack_size=64)
        target={'uuid':UUID,'entity_id':7,'type':'minecraft:item','class':'net.minecraft.world.entity.item.ItemEntity',
            'alive':True,'x':1.5,'y':64.,'z':.5,'distance':1.,
            'item':{'id':self.collect_item,'count':3,'empty':False,'item_fingerprint':FP,'component_fingerprint':FP,'max_stack_size':64,'identity_complete':True}}
        state['nearby'].update(entities=[] if self.collected else [target],total=0 if self.collected else 1,returned=0 if self.collected else 1)
        state['scoped_native_preflight']={'version':'scoped-native-preflight/1','private_singleplayer_only':True,
            'same_callback_capture_validate_admit':True,'capability_guard_schema_version':1,
            'profiles':{PROFILE:['follow_path']} if self.advertise else {},'guarded_actions':['follow_path']}
        return state
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)))
            self.action=bound_fixture(body['intent'],body['preflight'])
            self.action.update(ok=True,action_schema_version=1,status='running',reason='synthetic-collect-admitted',server_confirmed=False)
            try:validate_scoped_witness(self.action,body['preflight'],body['intent']['action_id'],body['intent'])
            except ValueError as exc:self.fixture_error=str(exc)
            if self.collect_mode=='lost':raise BridgeError('synthetic_lost_submit',uncertain=True)
            if self.collect_mode=='bad_cleanup':self.action['result']['input_release_confirmed']=False
            return deepcopy(self.action)
        if path.startswith('/control/action/status') and self.action['status']=='running' and not self.hold:
            self.action.update(status='cancelled',reason='scoped_collect_target_absent');self.collected=True
            return deepcopy(self.action)
        return super().request(method,path,body)

class PublicCollectChainTests(unittest.TestCase):
    until=owner_fixture.ActualGatewayOwnershipTests.until
    def setUp(self):
        with patch.object(owner_fixture,'CombatEndpoint',CollectEndpoint):owner_fixture.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'collect-runtime',wait_timeout=2)
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'toolbox')
    def tearDown(self):
        self.service.close();self.runtime.close();owner_fixture.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,**budgets):
        d=self.backend.describe()
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'collect_one',
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':'collect_local','capability_version':1,
            'arguments':{'target_uuid':UUID,'item_id':self.bridge.collect_item},'policy':{'version':1,'execution_mode':'guarded'},
            'budgets':{'max_actions':3,'max_observations':32,'deadline_seconds':10,**budgets},'wait_ms':0})
    def finish_job(self,response):
        self.assertIn('job_id',response,response)
        def terminal():
            self.result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','job_id':response['job_id'],'session_ref':response['session_ref']})
            return self.result['state'] not in ('accepted','running','stopping')
        self.until(terminal,timeout=8);return self.result
    def assert_one_post(self):
        self.assertIsNone(self.bridge.fixture_error)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action']);self.assertFalse(self.bridge.terrain_responses)
    def test_typed_gain_after_exact_absence_cancel(self):
        r=self.finish_job(self.submit());self.assertEqual(r['state'],'succeeded',(self.bridge.fixture_error,r));self.assert_one_post()
        self.assertEqual(r['effect_certainty'],'known');self.assertEqual(r['cleanup_certainty'],'confirmed')
        evidence=r['result']['evidence'];self.assertEqual(evidence['inventory_delta'],3)
        self.assertTrue(evidence['inventory_acquisition_confirmed']);self.assertFalse(evidence['causal_drop_attribution'])
        self.assertEqual(evidence['movement']['status'],'cancelled')
        self.assertEqual(evidence['movement']['reason'],'scoped_collect_target_absent')
        self.assertEqual(self.bridge.action['status'],'cancelled');self.assertEqual(self.bridge.action['reason'],'scoped_collect_target_absent')
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_other_actor_removal_without_inventory_gain(self):
        self.bridge.collect_mode='removed';r=self.finish_job(self.submit());self.assertEqual(r['state'],'failed',r);self.assert_one_post()
    def test_lost_submission_unknown_without_replay(self):
        self.bridge.collect_mode='lost';r=self.finish_job(self.submit());self.assertEqual(r['state'],'unknown',r);self.assert_one_post()
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel']);self.assertTrue(self.runtime.has_unresolved_execution)
    def test_cleanup_failure_stays_unknown(self):
        self.bridge.collect_mode='bad_cleanup';r=self.finish_job(self.submit());self.assertEqual(r['state'],'unknown',r);self.assert_one_post()
        self.assertEqual(r['cleanup_certainty'],'unknown')
    def test_exact_running_cancel(self):
        self.bridge.hold=True;self.bridge.collect_mode='cancel';submitted=self.submit()
        self.until(lambda:any(p=='/control/scoped-action' for p,b in self.bridge.posts))
        self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':submitted['job_id'],
            'session_ref':submitted['session_ref'],'cancel_request_id':'cancel_collect','wait_ms':1000})
        r=self.finish_job(submitted);self.assertEqual(r['state'],'cancelled',r);self.assert_one_post()
        cancels=[b for p,b in self.bridge.posts if p=='/control/action/cancel'];self.assertEqual(len(cancels),1)
        self.assertEqual(cancels[0]['action_id'],self.bridge.action['action_id']);self.assertEqual(cancels[0]['expected_action_session'],self.bridge.action['action_session'])
    def test_missing_profile_no_motion(self):
        self.bridge.advertise=False
        self.until(lambda:'collect_local' not in self.backend.describe()['supported_capabilities'])
        r=self.submit()
        if 'job_id' in r:r=self.finish_job(r)
        self.assertNotEqual(r.get('state'),'succeeded',r);self.assertFalse(self.bridge.posts)
    def test_observation_budget_no_motion(self):
        r=self.submit(max_observations=1)
        if 'job_id' in r:r=self.finish_job(r)
        self.assertNotEqual(r.get('state'),'succeeded',r);self.assertFalse(self.bridge.posts)

# Each finite ID gets a fresh real owner/resident/public service fixture; only native replies are synthetic.
from mdc_skills.scoped_collect import ITEMS

def survival_item_case(item):
    def test(self):
        self.bridge.collect_item=item
        self.test_typed_gain_after_exact_absence_cancel()
        self.assertEqual(self.result['result']['evidence']['item_id'],item)
        post=next(b for p,b in self.bridge.posts if p=='/control/scoped-action')
        self.assertEqual(post['intent']['pickup_target']['item_id'],item)
    return test

for item in sorted(ITEMS):
    setattr(PublicCollectChainTests,'test_survival_item_'+item.split(':')[1],survival_item_case(item))

if __name__=='__main__':unittest.main()
