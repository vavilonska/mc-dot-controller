"""Real public owner-chain tests with a modeled native route endpoint, offline."""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch
import base_watchdog
import test_capability_ownership as owners
import test_fall_rescue_owner_chain as fall_tests
from test_external_navigation_owner import Endpoint as StopEndpoint
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.transport import BridgeError

class Endpoint(StopEndpoint):
    def __init__(self):
        super().__init__();self.busy=False;self.route=None;self.route_calls=[];self.route_polls=0;self.route_settle_after=2
        self.lose_start=False;self.lose_cancel=False;self.foreign=False;self.cancel_requested=False;self.fence_ready=True;self.blocked_door=False;self.hazard_at_goal=False
    def snapshot(self):
        s=super().snapshot();s['managed_navigation']={'schema_version':1,'version':'managed-navigation-owner-control/1',
            'input_fence_ready':self.fence_ready,'walking_only':True,'max_goal_distance':200,'max_timeout_ms':120000}
        s['managed_navigation_status']=deepcopy(self.route) if self.route else {'managed_navigation_schema_version':1,
            'input_owned':False,'unknown_outcome_quarantined':False,'state':'idle'}
        return s
    def request(self,method,path,body=None):
        if not path.startswith('/control/managed-navigation/'):return super().request(method,path,body)
        op=path.rsplit('/',1)[1];self.route_calls.append((method,op,deepcopy(body)))
        if op=='start':
            assert self.route is None and not self.busy;self.busy=True;s=super().snapshot()
            self.route={'managed_navigation_schema_version':1,'input_owned':True,'unknown_outcome_quarantined':False,
                'execution_authority':False,'no_auto_resume':True,'operation_id':body['operation_id'],
                **{k:body[k] for k in ('owner_id','owner_generation','job_id','goal_x','goal_y','goal_z')},
                **{k:body['expected_'+k] for k in ('action_session','world_generation','player_uuid','dimension')},
                'state':'routing','reason':'route_running','start_attempted':True,'stop_attempted':False,'cancel_accepted':None,
                'goal_reached':False,'settings_restored':False,'control_released':False,'idle_samples':0,
                'admission_tick':s['world']['game_time'],'source_tick':s['world']['game_time'],'remaining_ms':body['timeout_ms'],
                'unloaded_terrain_certified':False,'external_controller':self.proof(s)}
            if self.lose_start:raise BridgeError('route_start_response_lost',uncertain=True)
        elif op=='cancel':
            assert not self.cancel_requested;self.cancel_requested=True
            self.route.update(state='stopping',reason='managed_navigation_cancel_requested',stop_attempted=True,cancel_accepted=True)
            if self.lose_cancel:raise BridgeError('route_cancel_response_lost',uncertain=True)
        else:
            self.route_polls+=1
            if self.blocked_door:
                self.route.update(state='stopping',reason='managed_navigation_door_or_nonwalking_input_blocked',stop_attempted=True,cancel_accepted=True)
            if self.hazard_at_goal:
                self.route.update(state='stopping',reason='managed_navigation_health_changed',stop_attempted=True,cancel_accepted=True)
            if self.route_polls>=self.route_settle_after:
                self.busy=False;s=super().snapshot();tick=max(s['world']['game_time'],self.route['admission_tick']+2);s['world']['game_time']=tick
                self.route.update(state='settled',input_owned=False,control_released=True,settings_restored=True,idle_samples=2,
                    goal_reached=not self.cancel_requested and not self.blocked_door,source_tick=tick,external_controller=self.proof(s))
                if not self.cancel_requested and not self.blocked_door and not self.hazard_at_goal:self.route['reason']='managed_navigation_goal_observed'
        result=deepcopy(self.route)
        if self.foreign and op=='status':result['operation_id']='f'*32
        # Actual endpoint wrapper shape is present even in this owner-chain model.
        return {**result,'protocol':'mineclient-bridge','schema_version':2}

class ManagedOwnerTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    finish=fall_tests.FallOwnerChainTests.finish
    def setUp(self):
        original=base_watchdog.run
        with patch.object(owners,'CombatEndpoint',Endpoint),patch.object(base_watchdog,'run',lambda *a,**k:original(*a,**{**k,'execution_policy':'request_only'})):
            owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'runtime',wait_timeout=2);self.backend=OwnerRuntimeBackend(self.runtime)
        self.service=ToolboxService(self.backend,self.root/'jobs')
    def tearDown(self):
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,rid='route-original'):
        d=self.backend.describe()
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':rid,
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':'navigate_managed_walk',
            'capability_version':1,'arguments':{'goal':{'x':2,'y':64,'z':0},'timeout_ms':1000,'max_distance':200},
            'policy':{'version':1,'execution_mode':'request_only','reactions':'stop'},
            'budgets':{'max_actions':3,'max_observations':64,'deadline_seconds':20},'wait_ms':0})
    def cancel(self,first):
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':first['job_id'],
            'session_ref':first['session_ref'],'cancel_request_id':'cancel-original-route','wait_ms':0})
    def test_public_walk_uses_one_owner_start_and_actual_idle_release(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result)
        self.assertEqual(result['cleanup_certainty'],'confirmed');self.assertEqual([r[1] for r in self.bridge.route_calls].count('start'),1)
        self.assertIsNone(self.client.session()['capability_lease']);self.assertEqual(self.submit()['job_id'],result['job_id'])
    def test_cancel_is_one_original_request_ack_is_not_idle(self):
        self.bridge.route_settle_after=50;first=self.submit();self.until(lambda:self.bridge.route_polls>=1)
        self.cancel(first);self.until(lambda:self.bridge.cancel_requested)
        self.assertIsNotNone(self.dog.capability_lease);self.assertEqual(self.bridge.route['state'],'stopping')
        self.bridge.route_settle_after=self.bridge.route_polls+1;result=self.finish(first)
        self.assertEqual(result['state'],'cancelled',result);self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual([r[1] for r in self.bridge.route_calls].count('cancel'),1)
    def test_lost_start_keeps_original_unknown_without_repeat(self):
        self.bridge.lose_start=True;result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertIsNotNone(self.dog.capability_lease);self.assertEqual(len(self.bridge.route_calls),1)
        self.assertIn('error',self.submit('another'));self.assertEqual(len(self.bridge.route_calls),1)
    def test_foreign_status_keeps_owner_unknown(self):
        self.bridge.foreign=True;result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertIsNotNone(self.dog.capability_lease);self.assertEqual([r[1] for r in self.bridge.route_calls].count('start'),1)
    def test_managed_binding_blocks_other_mutation_even_with_same_owner(self):
        self.bridge.route_settle_after=50;first=self.submit();self.until(lambda:self.bridge.route_polls>=1)
        lease=self.dog.capability_lease;old=self.dog.owner;self.dog.owner=None
        try:self.assertTrue(self.dog.capability_submit('other-effect',{'op':'action','action':'select_hotbar',
            '_capability_owner_id':lease['owner_id'],'_navigation_defense_epoch':lease['defense_epoch']}))
        finally:self.dog.owner=old
        self.assertEqual(self.dog.completed[-1]['result']['reason'],'managed_navigation_original_route_unsettled')
        self.bridge.route_settle_after=self.bridge.route_polls+1;self.finish(first)
    def test_lost_cancel_keeps_original_unknown_and_never_repeats(self):
        self.bridge.lose_cancel=True;self.bridge.route_settle_after=50;first=self.submit();self.until(lambda:self.bridge.route_polls>=1)
        self.cancel(first);result=self.finish(first);self.assertEqual(result['state'],'unknown',result)
        self.assertIsNotNone(self.dog.capability_lease)
        self.assertEqual([r[1] for r in self.bridge.route_calls].count('start'),1)
        self.assertEqual([r[1] for r in self.bridge.route_calls].count('cancel'),1)
    def test_missing_actual_input_fence_is_unavailable_before_start(self):
        self.bridge.fence_ready=False
        self.until(lambda:self.dog.latest['state']['managed_navigation']['input_fence_ready'] is False)
        result=self.submit();self.assertIn('error',result);self.assertEqual(self.bridge.route_calls,[])
    def test_blocked_door_is_explicit_interruption_after_release(self):
        self.bridge.blocked_door=True;result=self.finish(self.submit())
        self.assertEqual(result['state'],'interrupted',result);self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual(result['result']['reason'],'managed_navigation_door_or_nonwalking_input_blocked')
        self.assertEqual([r[1] for r in self.bridge.route_calls].count('start'),1)
        self.assertEqual([r[1] for r in self.bridge.route_calls].count('cancel'),0)
    def test_goal_plus_native_health_stop_is_interrupted_with_goal_evidence(self):
        self.bridge.hazard_at_goal=True;result=self.finish(self.submit())
        self.assertEqual(result['state'],'interrupted',result);self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual(result['result']['reason'],'managed_navigation_health_changed')
        self.assertTrue(result['result']['evidence']['native']['goal_reached'])
        self.assertTrue(result['result']['evidence']['native']['stop_attempted'])
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_unmanaged_busy_cannot_be_acquired_for_walk(self):
        self.bridge.busy=True;self.until(lambda:self.dog.latest['state']['external_controller']['idle_proven'] is False)
        result=self.finish(self.submit());self.assertNotEqual(result['state'],'succeeded',result)
        self.assertEqual(self.bridge.route_calls,[]);self.assertIsNone(self.dog.capability_lease)

if __name__=='__main__':unittest.main()
