"""Public same-owner chain; native endpoint only is modeled, no game execution."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import test_capability_ownership as owners
from test_scoped_combat_chain import Endpoint as CombatEndpoint,TARGET
from test_fall_rescue_owner_chain import Endpoint as FallEndpoint
from test_fall_rescue_evidence import ROWS
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend

class RescueEndpointMixin:
    def __init__(self):
        super().__init__();self.rescue_mode='none';self.rescue_polls=0;self.hold_rescue=False;self.allowed_ids=[];self.lose_disarm=False
    def make_rescue(self,index):
        value=deepcopy(ROWS[index])
        for k in ('arm_id','owner_id','action_session','world_generation','player_uuid'):value[k]=self.fall[k]
        e=value.get('episode') or value.get('last_episode');e['episode_id']=self.fall['arm_id']+':1'
        e['interrupted_action']={'action_id':self.action['action_id'],'action':self.action['action'],
            'effect_outcome':'unknown_interrupted','no_auto_resume':True,'requires_reconciliation_before_retry':True}
        value['remaining_ms']=self.fall['remaining_ms'] if value['armed'] else 0
        if index==4:
            value.update(status='quarantined',automation_blocked=True,unknown_outcome_quarantined=True)
            if self.rescue_mode=='partial':e.update(outcome='episode_time_budget_exhausted',rescue_confirmed=False,server_landed_alive_observed=False)
        return value
    def request(self,method,path,body=None):
        if path=='/control/fall-rescue/arm':
            self.allowed_ids=deepcopy(body['permitted_action_ids']);super().request(method,path,body)
            self.fall['remaining_ms']=body['ttl_ms'];return deepcopy(self.fall)
        if path=='/control/fall-rescue/status' and self.rescue_polls:
            self.fall_calls.append(('status',None));self.rescue_polls+=1
            if not self.hold_rescue:self.fall=self.make_rescue(min(4,self.rescue_polls))
            if self.rescue_mode=='wrong_world':return {**deepcopy(self.fall),'world_generation':'replacement-world'}
            return deepcopy(self.fall)
        if path=='/control/fall-rescue/disarm' and self.rescue_polls:
            self.fall_calls.append(('disarm',deepcopy(body)))
            e=deepcopy(self.fall.pop('episode',self.fall.get('last_episode')));e.update(outcome='explicit_disarm',rescue_confirmed=False,server_landed_alive_observed=False)
            self.fall.update(armed=False,input_owned=False,status='quarantined',automation_blocked=True,
                unknown_outcome_quarantined=True,remaining_ms=0,last_episode=e)
            return deepcopy(self.fall)
        if path.startswith('/control/action/status') and self.action['status']=='running' and self.rescue_mode!='none':
            self.action.update(status='cancelled',reason='native_fall_rescue_preempted')
            self.action['result'].update(preempted_by_native_fall_rescue=True,unknown_outcome=True,requires_handoff=True,
                no_auto_resume=True,input_release_confirmed=True)
            self.rescue_polls=1;self.fall=self.make_rescue(2);return deepcopy(self.action)
        value=super().request(method,path,body)
        if path=='/control/fall-rescue/disarm' and self.lose_disarm:
            from resident_controller.transport import BridgeError
            raise BridgeError('synthetic_lost_disarm_response',uncertain=True)
        return value

class Endpoint(RescueEndpointMixin,FallEndpoint,CombatEndpoint):
    pass

class AttachedChainTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    def setUp(self):
        with patch.object(owners,'CombatEndpoint',Endpoint):owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'attached-runtime',wait_timeout=4)
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'jobs')
    def tearDown(self):
        if not self.resident.running:
            # The production Resident intentionally exited. End this offline
            # watchdog fixture without submitting to that stopped controller.
            self.dog.stopped=True
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,*,deadline=25,actions=8,policy=True):
        d=self.backend.describe();p={'version':1,'execution_mode':'guarded','reactions':'stop'}
        if policy:p['fall_rescue']={'schema_version':1,'water_bucket':True}
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'attached-one',
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':'engage','capability_version':1,
            'arguments':{'target_uuid':TARGET,'min_health':14,'timeout_ms':1000},'policy':p,
            'budgets':{'max_actions':actions,'max_observations':40,'deadline_seconds':deadline},'wait_ms':0})
    def finish(self,r):
        self.assertIn('job_id',r,r)
        def done():
            self.result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
                'job_id':r['job_id'],'session_ref':r['session_ref']})
            return self.result['state'] not in ('accepted','running','stopping')
        self.until(done,timeout=8);return self.result
    def test_normal_combat_exact_gateway_id_and_disarm_before_release(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result)
        self.assertEqual(self.bridge.fall_calls[0][1]['ttl_ms'],11000)
        self.assertEqual(self.bridge.allowed_ids,[self.bridge.action['action_id']])
        self.assertEqual([x for x,_ in self.bridge.fall_calls].count('arm'),1)
        self.assertEqual([x for x,_ in self.bridge.fall_calls].count('disarm'),1)
        self.assertNotIn('renew',[x for x,_ in self.bridge.fall_calls]);self.assertIsNone(self.client.session()['capability_lease'])
        native=[b for p,b in self.bridge.posts if p=='/control/scoped-action'][0]
        self.assertNotIn('fall_rescue_policy',native['intent']);self.assertNotIn('fall_rescue_binding',native['intent'])
    def test_preemption_holds_original_until_rescue_then_unknown(self):
        self.bridge.rescue_mode='confirmed';self.bridge.hold_rescue=True;r=self.submit()
        self.until(lambda:self.bridge.rescue_polls>=2);task=self.resident.active
        self.assertIsNotNone(task);self.assertTrue(task.fall_rescue['waiting']);self.assertFalse(task.capability_unknown)
        self.assertNotIn('disarm',[x for x,_ in self.bridge.fall_calls]);self.bridge.hold_rescue=False
        result=self.finish(r);self.assertEqual(result['state'],'unknown',result);self.assertEqual(result['effect_certainty'],'unknown',result)
        self.assertNotIn('disarm',[x for x,_ in self.bridge.fall_calls])
        self.assertEqual(len([1 for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertIsNotNone(self.client.session()['capability_lease'])
        self.assertTrue(any(v.get('receipt_ref') for v in self.runtime._journal['records'].values() if v.get('kind')=='mutation'))
    def test_short_deadline_never_arms_or_shortens_reserve(self):
        result=self.finish(self.submit(deadline=10));self.assertEqual(result['state'],'blocked',result)
        self.assertEqual(self.bridge.fall_calls,[]);self.assertFalse([p for p,b in self.bridge.posts if p=='/control/scoped-action'])
    def test_lost_arm_never_dispatches_or_retries(self):
        self.bridge.lose_arm=True;result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertEqual([x for x,_ in self.bridge.fall_calls],['arm']);self.assertFalse([p for p,b in self.bridge.posts if p=='/control/scoped-action'])
    def test_wrong_world_during_rescue_freezes_without_disarm(self):
        self.bridge.rescue_mode='wrong_world';result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertNotIn('disarm',[x for x,_ in self.bridge.fall_calls])
    def test_lost_disarm_never_retries_or_releases(self):
        self.bridge.lose_disarm=True;result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertEqual([x for x,_ in self.bridge.fall_calls].count('disarm'),1)
        self.assertIsNotNone(self.client.session()['capability_lease']);self.assertFalse(self.bridge.fall['armed'])
    def test_partial_rescue_still_retains_original_unknown(self):
        self.bridge.rescue_mode='partial';result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertFalse(self.bridge.fall['last_episode']['rescue_confirmed'])
        self.assertTrue(self.bridge.fall['last_episode']['server_water_observed'])
        self.assertIsNotNone(self.client.session()['capability_lease']);self.assertNotIn('disarm',[x for x,_ in self.bridge.fall_calls])
    def test_missing_bucket_blocks_before_arm(self):
        self.bridge.no_bucket=True;result=self.finish(self.submit());self.assertEqual(result['state'],'blocked',result)
        self.assertEqual(self.bridge.fall_calls,[])
    def legacy_stop(self,command):
        from resident_controller.ipc import QueueClient
        self.bridge.rescue_mode='confirmed';self.bridge.hold_rescue=True;r=self.submit()
        self.until(lambda:self.bridge.rescue_polls>=2);q=QueueClient(self.root/'resident')
        stop=q.submit(command);reply=q.wait(stop,timeout=3);self.assertEqual(reply['status'],'succeeded',reply)
        result=self.finish(r);self.assertEqual(result['state'],'unknown',result)
        self.assertEqual([x for x,_ in self.bridge.fall_calls].count('disarm'),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/release-all'])
        self.assertTrue(self.resident.paused);self.assertIsNotNone(self.client.session()['capability_lease'])
        return q
    def test_legacy_cancel_mailbox_keeps_original_unknown(self):
        q=self.legacy_stop({'op':'cancel'})
        rid=q.submit({'op':'resume'});reply=q.wait(rid,timeout=3)
        self.assertEqual(reply['status'],'failed',reply);self.assertTrue(self.resident.paused)
    def test_legacy_release_all_uses_exact_stop(self):
        self.legacy_stop({'op':'direct','endpoint':'release-all','body':{}})
    def test_legacy_shutdown_uses_exact_stop(self):
        self.legacy_stop({'op':'shutdown'});self.assertFalse(self.resident.running)

    def test_explicit_cancel_mid_rescue_disarms_once(self):
        self.bridge.rescue_mode='confirmed';self.bridge.hold_rescue=True;r=self.submit();self.until(lambda:self.bridge.rescue_polls>=2)
        self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':r['job_id'],
            'session_ref':r['session_ref'],'cancel_request_id':'stop-original','wait_ms':1000})
        result=self.finish(r);self.assertEqual(result['state'],'unknown',result)
        self.assertEqual([x for x,_ in self.bridge.fall_calls].count('disarm'),1)
        self.assertFalse(self.bridge.fall['armed']);self.assertFalse(self.bridge.fall['input_owned'])
        self.assertEqual(len([1 for p,b in self.bridge.posts if p=='/control/scoped-action']),1)

if __name__=='__main__':unittest.main()
