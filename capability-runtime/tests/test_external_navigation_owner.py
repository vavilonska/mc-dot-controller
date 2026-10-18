"""Production sole-owner chain with a modeled native Baritone endpoint, offline."""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch
import base_watchdog
import test_capability_ownership as owners
import test_fall_rescue_owner_chain as fall_tests
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.transport import BridgeError

class Endpoint(owners.CombatEndpoint):
    def __init__(self):
        super().__init__();self.external_calls=[];self.stop=None;self.busy=True;self.bad=False;self.lose=False;self.polls=0;self.settle_after=2
    def proof(self,s):
        return {'schema_version':1,'controller':'baritone','adapter':'baritone-api-neoforge/1.11.3','source_tick':s['world']['game_time'],
            'source_nano':str(time.monotonic_ns()),'world_generation':s['world']['world_generation'],'player_uuid':s['player']['uuid'],
            'action_session':s['client_action']['action_session'],'execution_authority':False,'supported':True,
            'status':'busy' if self.busy else 'idle','idle_proven':not self.busy,'reason':'version_pinned_actual_api_sample','facts':{'context_matches':True,'instances':1,
            'is_pathing':self.busy,'current_path':self.busy,'next_path':False,'planning':False,'goal_present':self.busy,
            'active_process_count':int(self.busy),'registered_process_count':12,'forced_input_count':int(self.busy)}}
    def snapshot(self):
        s=super().snapshot();s['external_controller']=self.proof(s)
        s['external_navigation']={'schema_version':1,'version':'external-navigation-owner-control/1','single_owner_fences':True,'stop_only':True,'no_auto_resume':True}
        s['external_navigation_status']=deepcopy(self.stop) if self.stop else {'external_navigation_schema_version':1,'input_owned':False,'unknown_outcome_quarantined':False,'state':'idle'}
        s['native_fall_rescue_status']={'fall_rescue_schema_version':1,'armed':False,'input_owned':False,'unknown_outcome_quarantined':False,'automation_blocked':False}
        return s
    def request(self,method,path,body=None):
        if path.startswith('/control/external-navigation/'):
            op=path.rsplit('/',1)[1];self.external_calls.append((method,op,deepcopy(body)))
            if op=='stop':
                assert method=='POST' and self.stop is None
                s=super().snapshot();self.stop={'external_navigation_schema_version':1,'input_owned':True,'unknown_outcome_quarantined':False,
                    'no_auto_resume':True,'execution_authority':False,'operation_id':body['operation_id'],
                    **{k:body[k] for k in ('owner_id','owner_generation','job_id')},
                    **{k:body['expected_'+k] for k in ('action_session','world_generation','player_uuid','dimension')},
                    'state':'stopping','reason':'awaiting_actual_idle','stop_attempted':self.busy,'cancel_accepted':True,
                    'control_released':False,'admission_tick':s['world']['game_time'],'idle_samples':0,'source_tick':s['world']['game_time'],'remaining_ms':body['timeout_ms'],
                    'external_controller':self.proof(s)}
                if self.lose:raise BridgeError('stop_response_lost',uncertain=True)
            else:
                assert method=='GET';self.polls+=1
                if self.polls>=self.settle_after:
                    self.busy=False;s=super().snapshot();s['world']['game_time']=max(s['world']['game_time'],self.stop['admission_tick']+2);self.stop.update(state='settled',input_owned=False,control_released=True,
                        idle_samples=2,source_tick=s['world']['game_time'],external_controller=self.proof(s))
            result=deepcopy(self.stop)
            if self.bad and op=='status':result['owner_id']='0'*32
            return result
        return super().request(method,path,body)

class ExternalOwnerTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    finish=fall_tests.FallOwnerChainTests.finish
    def setUp(self):
        original=base_watchdog.run
        with patch.object(owners,'CombatEndpoint',Endpoint),patch.object(base_watchdog,'run',lambda *a,**k:original(*a,**{**k,'execution_policy':'request_only'})):
            owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'runtime',wait_timeout=2)
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'jobs')
    def tearDown(self):
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,rid='stop-one'):
        d=self.backend.describe()
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':rid,
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':'stop_external_navigation',
            'capability_version':1,'arguments':{'timeout_ms':1000},'policy':{'version':1,'execution_mode':'request_only','reactions':'stop'},
            'budgets':{'max_actions':3,'max_observations':32,'deadline_seconds':10},'wait_ms':0})
    def test_public_stop_once_and_verified_idle_release(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result)
        self.assertEqual(result['cleanup_certainty'],'confirmed');self.assertEqual(result['effect_certainty'],'known')
        self.assertEqual([x[1] for x in self.bridge.external_calls].count('stop'),1)
        self.assertGreaterEqual(self.bridge.polls,2);self.assertIsNone(self.client.session()['capability_lease'])
        self.assertEqual(self.submit()['job_id'],result['job_id']);self.assertEqual([x[1] for x in self.bridge.external_calls].count('stop'),1)
    def test_lost_stop_response_preserves_owner_no_repeat(self):
        self.bridge.lose=True;result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(len(self.bridge.external_calls),1);self.assertIsNotNone(self.dog.capability_lease)
        self.assertEqual(self.dog.capability_lease['owner_mode'],'external_stop')
        self.assertIn('error',self.submit('another'));self.assertEqual(len(self.bridge.external_calls),1)
    def test_foreign_status_preserves_unknown_without_new_stop(self):
        self.bridge.bad=True;result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertEqual([x[1] for x in self.bridge.external_calls].count('stop'),1);self.assertTrue(self.dog.handoff_latched)
    def test_cancel_ack_does_not_mean_released(self):
        self.bridge.settle_after=50;first=self.submit();self.until(lambda:self.bridge.polls>=2)
        status=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','session_ref':first['session_ref'],'job_id':first['job_id']})
        self.assertEqual(status['state'],'running',status);self.assertIsNotNone(self.dog.capability_lease)
        self.bridge.settle_after=self.bridge.polls+1;self.assertEqual(self.finish(first)['state'],'succeeded')
    def test_cancel_waits_for_original_stop_without_second_post(self):
        self.bridge.settle_after=50;first=self.submit();self.until(lambda:self.bridge.polls>=1)
        self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':first['job_id'],
            'session_ref':first['session_ref'],'cancel_request_id':'cancel-original-stop','wait_ms':0})
        self.bridge.settle_after=self.bridge.polls+1;result=self.finish(first)
        self.assertEqual(result['state'],'cancelled',result);self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual([x[0] for x in self.bridge.external_calls].count('POST'),1)
    def test_ordinary_acquire_still_refuses_existing_external_owner(self):
        import uuid
        self.dog.capability_control('ordinary-under-busy',{'op':'capability_acquire','owner_id':uuid.uuid4().hex,
            'expected_defense_epoch':self.dog.defense_epoch,'expected_context':deepcopy(self.dog.capability_status()['capability_context']),
            'duration_ms':10000})
        receipt=self.dog.completed[-1]['result']
        self.assertEqual(receipt['status'],'failed');self.assertEqual(receipt['reason'],'capability_admission_not_idle')
        self.assertIsNone(self.dog.capability_lease);self.assertEqual(self.bridge.external_calls,[])
    def test_original_acquire_waits_for_inflight_read_without_replay(self):
        self.resident_paused.set()
        self.until(lambda:self.dog.rpc is not None)
        original_read=self.dog.rpc['id'];first=self.submit('stop-after-read')
        self.until(lambda:bool(list((self.root/'watchdog'/'inbox').glob('*.json'))))
        time.sleep(.08)
        self.assertEqual(self.dog.rpc['id'],original_read)
        self.assertIsNone(self.dog.capability_lease);self.assertEqual(self.bridge.external_calls,[])
        self.resident_paused.clear();result=self.finish(first)
        self.assertEqual(result['state'],'succeeded',result)
        self.assertEqual([x[0] for x in self.bridge.external_calls].count('POST'),1)
    def test_stop_only_lease_cannot_dispatch_ordinary_action(self):
        self.bridge.settle_after=50;first=self.submit();self.until(lambda:self.bridge.polls>=1)
        lease=self.dog.capability_lease
        command={'op':'action','action':'select_hotbar','_capability_owner_id':lease['owner_id'],'_navigation_defense_epoch':lease['defense_epoch']}
        # Same proof cannot turn a special control lease into ordinary input ownership.
        old=self.dog.owner;self.dog.owner=None
        try:self.assertTrue(self.dog.capability_submit('forged-stop-action',command))
        finally:self.dog.owner=old
        self.assertEqual(self.dog.completed[-1]['result']['reason'],'external_stop_lease_is_not_mutation_authority')
        self.bridge.settle_after=self.bridge.polls+1;self.finish(first)

if __name__=='__main__':unittest.main()
