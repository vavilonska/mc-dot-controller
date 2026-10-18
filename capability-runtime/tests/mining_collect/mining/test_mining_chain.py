"""Actual public→Runtime→Intent→Watchdog→Resident chain; only native endpoint is fake.
No Minecraft instance, real network, credentials, geometry or physical motion is used.
"""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch
from mining_collect.bootstrap import load_owner_fixture
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.transport import BridgeError
from resident_controller.capability_snapshot import validate_scoped_witness
from .mining_fixture import mining_fixture

owner_fixture = load_owner_fixture()

class MiningEndpoint(owner_fixture.CombatEndpoint):
    def __init__(self):
        super().__init__();self.mining_mode='success';self.goal=None;self.fixture_error=None
    def snapshot(self):
        state=super().snapshot()
        # This boundary fixture supplies complete synthetic native stack handles; no borrowed loose placeholders.
        for row in state['player']['inventory']:
            row.update(item_fingerprint='11111111-1111-4111-8111-111111111111',
                       component_fingerprint='11111111-1111-4111-8111-111111111111',max_stack_size=0)
        held=state['player']['inventory'][0]
        held.update(item_fingerprint='22222222-2222-4222-8222-222222222222',
                    component_fingerprint='22222222-2222-4222-8222-222222222222',max_stack_size=1)

        state['scoped_native_preflight']={'version':'scoped-native-preflight/1','private_singleplayer_only':True,
            'same_callback_capture_validate_admit':True,'capability_guard_schema_version':1,
            'profiles':{'mining-local-observed-v2':['break_block']},'guarded_actions':['break_block']}
        if self.goal is not None and self.action['status']=='succeeded':
            pass  # Native mining never moves the fixture player.
        return state
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)))
            self.goal=deepcopy(body['intent']['target'])
            self.action=mining_fixture(body['intent'],body['preflight'])[0]
            self.action.update(ok=True,action_schema_version=1,status='running',reason='synthetic-mining-admitted',server_confirmed=False)
            try:validate_scoped_witness(self.action,body['preflight'],body['intent']['action_id'],body['intent'])
            except ValueError as exc:self.fixture_error=str(exc)
            if self.mining_mode=='size409':
                from .test_preview_diagnostics import size_diagnostic
                raise BridgeError('scoped_movement_response_evidence_too_large',status=409,uncertain=False,scoped_movement_response_size=size_diagnostic(),scoped_movement_response_size_status='reported')
            if self.mining_mode=='late409':raise BridgeError('synthetic_post_hook_refusal',status=409,uncertain=False)
            if self.mining_mode=='lost':raise BridgeError('synthetic_lost_submit',uncertain=True)
            if self.mining_mode=='bad_cleanup':self.action['result']['input_release_confirmed']=False
            return deepcopy(self.action)
        if path=='/control/action/cancel':
            self.action['result']['mining']['block_removed']=False
            self.action['result'].pop('observed_block',None)
        return super().request(method,path,body)

class PublicMiningChainTests(unittest.TestCase):
    until=owner_fixture.ActualGatewayOwnershipTests.until
    def setUp(self):
        with patch.object(owner_fixture,'CombatEndpoint',MiningEndpoint):
            owner_fixture.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'mining-runtime',wait_timeout=2)
        self.backend=OwnerRuntimeBackend(self.runtime)
        self.service=ToolboxService(self.backend,self.root/'toolbox')
    def tearDown(self):
        self.service.close();self.runtime.close()
        owner_fixture.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,arguments=None):
        description=self.backend.describe()
        self.assertIn('mine_local',description['supported_capabilities'])
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'mine_one',
            'session_ref':description['session_ref'],'expected_context_ref':description['context_ref'],
            'capability':'mine_local','capability_version':1,'arguments':arguments or {'target':{'x':2,'y':64,'z':0},'expected_block_id':'minecraft:stone','expected_block_properties':{}},
            'policy':{'version':1,'execution_mode':'guarded'},
            'budgets':{'max_actions':3,'max_observations':16,'deadline_seconds':10},'wait_ms':0})
    def finish_job(self,response):
        self.assertIn('job_id',response,response)
        def terminal():
            self.result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
                'job_id':response['job_id'],'session_ref':response['session_ref']})
            return self.result['state'] not in ('accepted','running','stopping')
        self.until(terminal,timeout=6)
        return self.result
    def test_public_reach_uses_one_scoped_post_and_no_terrain(self):
        result=self.finish_job(self.submit())
        self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        self.assertEqual(result['effect_certainty'],'known');self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action'])
        self.assertFalse(self.bridge.terrain_responses)
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_exact_running_cancel_and_release(self):
        self.bridge.hold=True;submitted=self.submit()
        self.until(lambda:any(p=='/control/scoped-action' for p,b in self.bridge.posts))
        self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':submitted['job_id'],
            'session_ref':submitted['session_ref'],'cancel_request_id':'cancel_one','wait_ms':1000})
        result=self.finish_job(submitted)
        self.assertEqual(result['state'],'cancelled',(self.bridge.fixture_error,result));self.assertEqual(result['cleanup_certainty'],'confirmed')
        cancels=[b for p,b in self.bridge.posts if p=='/control/action/cancel']
        self.assertEqual(len(cancels),1);self.assertEqual(cancels[0]['action_id'],self.bridge.action['action_id'])
        self.assertEqual(cancels[0]['expected_action_session'],self.bridge.action['action_session'])
    def test_lost_submit_unknown_no_cancel_or_replay(self):
        self.bridge.mining_mode='lost';result=self.finish_job(self.submit())
        self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        self.assertTrue(self.runtime.has_unresolved_execution)
    def test_scoped_late409_is_unknown_without_cancel_or_replay(self):
        self.bridge.mining_mode='late409';result=self.finish_job(self.submit())
        self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
    def test_preview_size_refusal_stays_unknown_without_cancel_or_replay(self):
        self.bridge.mining_mode='size409';result=self.finish_job(self.submit())
        self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        self.assertTrue(self.runtime.has_unresolved_execution)
    def test_unconfirmed_cleanup_remains_unknown(self):
        self.bridge.mining_mode='bad_cleanup';result=self.finish_job(self.submit())
        self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(result['cleanup_certainty'],'unknown')
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)

if __name__=='__main__':unittest.main()
