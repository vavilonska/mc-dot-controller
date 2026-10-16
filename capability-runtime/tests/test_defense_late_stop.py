"""Real Runtime/owner-chain late-stop regression; synthetic Bridge only."""
import unittest
from unittest.mock import patch
import base_watchdog
import test_capability_ownership as owners
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from test_defend_once_frontdoor import Endpoint, TARGET


class DefenseLateStopTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    def setUp(self):
        run=base_watchdog.run
        def request_only(*args, **kwargs):kwargs['execution_policy']='request_only';return run(*args,**kwargs)
        with patch.object(owners,'CombatEndpoint',Endpoint),patch.object(base_watchdog,'run',request_only):
            owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'runtime',wait_timeout=2)
        begin=self.runtime.begin_job
        self.stopped=False
        def begin_with_late_stop(control, **kwargs):
            begin(control,**kwargs)
            emit=control._emit
            def wrapped(event,value):
                pending=self.runtime._journal.get('pending')
                record=self.runtime._journal['records'].get(pending,{})
                if event=='owner_context' and record.get('skill')=='defense.engage_once' and record.get('status')=='reserved' and 'owner_check' not in self._testMethodName:
                    self.stopped=True
                    if self._testMethodName=='test_cancel_after_defense_reservation':control.cancel_event.set()
                    else:control.budget.deadline=control.budget.clock()-1
                emit(event,value)
            control._emit=wrapped
            owner_check=control.owner_check
            def late_owner_check():
                owner_check()
                pending=self.runtime._journal.get('pending')
                record=self.runtime._journal['records'].get(pending,{})
                if 'owner_check' in self._testMethodName and record.get('skill')=='defense.engage_once' and record.get('status')=='reserved':
                    self.stopped=True
                    if 'cancel' in self._testMethodName:control.cancel_event.set()
                    else:control.budget.deadline=control.budget.clock()-1
            control.owner_check=late_owner_check
        self.runtime.begin_job=begin_with_late_stop
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'toolbox')
    def tearDown(self):
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def verify_stop(self, expected):
        d=self.backend.describe()
        result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'late-stop',
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':'navigate_local','capability_version':1,
            'arguments':{'goal':{'x':1,'y':64,'z':0}},'policy':{'version':1,'execution_mode':'request_only','reactions':'defend_once',
                'defense':{'target_uuid':TARGET,'timeout_ms':2000,'min_health':14}},
            'budgets':{'deadline_seconds':30,'max_actions':3,'max_observations':40,'reflex_reserve_actions':1,'cleanup_reserve_actions':1},'wait_ms':10000})
        self.assertTrue(self.stopped,result)
        self.assertEqual(result['state'],expected,result)
        self.assertEqual(result['effect_certainty'],'known')
        self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertIsNone(self.runtime.pending_request_id)
        self.assertIsNone(self.client.session()['capability_lease'])
        posts=[body for path,body in self.bridge.posts if path=='/control/scoped-action']
        self.assertEqual([body['intent']['action'] for body in posts],['follow_path'])
        records=[record for record in self.runtime._journal['records'].values() if record.get('skill')=='defense.engage_once']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['evidence']['submission_outcome'],'stopped_before_dispatch')
    def test_cancel_after_defense_reservation(self):self.verify_stop('cancelled')
    def test_deadline_after_defense_reservation(self):self.verify_stop('interrupted')
    def test_cancel_during_final_owner_check(self):self.verify_stop('cancelled')
    def test_deadline_during_final_owner_check(self):self.verify_stop('interrupted')

if __name__=='__main__':unittest.main()
