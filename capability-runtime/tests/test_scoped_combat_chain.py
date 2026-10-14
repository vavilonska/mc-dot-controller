"""Actual public→Runtime→Intent→Watchdog→Resident route; native endpoint is synthetic.
No game, native physics, packet hooks or live safety is established by this test.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch
import test_capability_ownership as owners
# Load the shared synthetic fixture by repository-relative path so the standard
# capability test discovery does not require Resident's test folder on PYTHONPATH.
from pathlib import Path
from importlib.util import module_from_spec, spec_from_file_location
_fixture_spec = spec_from_file_location('mdc_scoped_combat_fixture',
    Path(__file__).resolve().parents[2] / 'resident-controller/tests/combat_witness_fixture.py')
_fixture_module = module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
fixture, reseal = _fixture_module.fixture, _fixture_module.reseal
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox.bindings import tactical
from mdc_toolbox.contracts import ToolboxError,validate_schema
from resident_controller.transport import BridgeError
from resident_controller.capability_snapshot import validate_scoped_witness
TARGET='44444444-4444-4444-8444-444444444444'


def combat_witness(intent,scope):
    native,_,_,_=fixture();w=native['result']['scoped_native_preflight'];f=w['facts']
    w.update(scope);w.update(action_id=intent['action_id'],action_session=intent['expected_action_session'],
        source_tick=intent['capability_guard']['source_tick']+1,source_nano=str(int(intent['capability_guard']['source_nano'])+1),
        admitted_nano=str(int(intent['capability_guard']['source_nano'])+21))
    f['context'].update({k:intent['expected_'+k] for k in ('world_generation','dimension','player_uuid','action_session')})
    w['context']=deepcopy(f['context']);f['selected_slot']=intent['expected_hotbar_slot']
    held={k:v for k,v in intent['expected_held_item'].items() if k!='slot'}
    f['inventory'][f['selected_slot']]['item']=deepcopy(held);f['equipment']['mainhand']=deepcopy(held)
    f['menu']['slots'][36+f['selected_slot']]['item']=deepcopy(held)
    if 'expected_origin' in intent:f.update(intent['expected_origin'])
    for k in ('target_entity_id','target_uuid','target_type','approach','shield','min_health','timeout_ms'):f['combat'][k]=intent[k]
    native.update(action_id=intent['action_id'],action_session=intent['expected_action_session'],action='combat_entity',
        ok=True,action_schema_version=1,status='running',reason='synthetic_combat_admitted',server_confirmed=False)
    reseal((native,scope,intent['action_id'],intent));return native


class Endpoint(owners.CombatEndpoint):
    def __init__(self):
        super().__init__();self.combat_mode='success';self.fixture_error=None;self.advertise=True
        self.entities=[dict(uuid=TARGET,entity_id=9,type='minecraft:zombie',alive=True,health=20.,x=2.5,y=64.,z=.5)]
    def snapshot(self):
        state=super().snapshot()
        for row in state['player']['inventory']:
            row.update(item_fingerprint='11111111-1111-4111-8111-111111111111',component_fingerprint='11111111-1111-4111-8111-111111111111',max_stack_size=0)
        state['player']['inventory'][0].update(item_fingerprint='22222222-2222-4222-8222-222222222222',component_fingerprint='22222222-2222-4222-8222-222222222222',max_stack_size=1)
        if self.action['status']=='succeeded' and self.combat_mode!='no_damage':
            for target in state['nearby']['entities']:target.update(alive=False,health=0.)
        state['scoped_native_preflight']={'version':'scoped-native-preflight/1','private_singleplayer_only':True,
            'same_callback_capture_validate_admit':True,'capability_guard_schema_version':1,
            'profiles':{'combat-local-observed-v1':['combat_entity']} if self.advertise else {},'guarded_actions':['combat_entity']}
        return state
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)));self.action=combat_witness(body['intent'],body['preflight'])
            try:validate_scoped_witness(self.action,body['preflight'],body['intent']['action_id'],body['intent'])
            except ValueError as exc:self.fixture_error=str(exc)
            if self.combat_mode=='lost':raise BridgeError('synthetic_lost_submit',uncertain=True)
            if self.combat_mode=='late409':raise BridgeError('synthetic_post_hook_refusal',status=409,uncertain=False)
            return deepcopy(self.action)
        return super().request(method,path,body)


class PublicCombatChainTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    def setUp(self):
        with patch.object(owners,'CombatEndpoint',Endpoint):owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'combat-runtime',wait_timeout=2)
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'toolbox')
    def tearDown(self):
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self):
        d=self.backend.describe();self.assertIn('engage',d['supported_capabilities'])
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'combat_one',
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':'engage','capability_version':1,
            'arguments':{'target_uuid':TARGET,'min_health':14,'timeout_ms':1000},
            'policy':{'version':1,'execution_mode':'guarded','reactions':'stop'},
            'budgets':{'max_actions':3,'max_observations':24,'deadline_seconds':10},'wait_ms':0})
    def finish(self,r):
        self.assertIn('job_id',r,r)
        def terminal():
            self.result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','job_id':r['job_id'],'session_ref':r['session_ref']})
            return self.result['state'] not in ('accepted','running','stopping')
        self.until(terminal,timeout=8);return self.result
    def test_public_scoped_dispatch_exact_target_and_release(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        posts=[b for p,b in self.bridge.posts if p=='/control/scoped-action'];self.assertEqual(len(posts),1)
        self.assertEqual(posts[0]['intent']['target_uuid'],TARGET);self.assertEqual(posts[0]['preflight']['profile'],'combat-local-observed-v1')
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action']);self.assertIsNone(self.client.session()['capability_lease'])
    def test_exact_cancel_no_resume(self):
        self.bridge.hold=True;r=self.submit();self.until(lambda:any(p=='/control/scoped-action' for p,b in self.bridge.posts))
        self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':r['job_id'],'session_ref':r['session_ref'],'cancel_request_id':'stop_combat','wait_ms':1000})
        result=self.finish(r);self.assertEqual(result['state'],'cancelled',result)
        cancels=[b for p,b in self.bridge.posts if p=='/control/action/cancel'];self.assertEqual(len(cancels),1)
        self.assertEqual(cancels[0]['action_id'],self.bridge.action['action_id'])
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
    def test_lost_submit_unknown_never_replayed(self):
        self.bridge.combat_mode='lost';result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
    def test_no_damage_is_not_victory(self):
        self.bridge.combat_mode='no_damage';result=self.finish(self.submit());self.assertNotEqual(result['state'],'succeeded',result)
    def test_profile_missing_does_not_enable_combat(self):
        self.bridge.advertise=False;self.until(lambda:'engage' not in self.backend.describe()['supported_capabilities'])
        self.assertEqual(self.backend.describe()['supported_policies']['reactions'],['stop'])
    def test_reserve_schema_explicit_floor(self):
        for value in (10,13.99,True,21):
            with self.assertRaises(ToolboxError):validate_schema({'target_uuid':TARGET,'min_health':value},tactical._SCHEMAS['engage'])

if __name__=='__main__':unittest.main()
