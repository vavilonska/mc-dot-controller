from copy import deepcopy
from types import SimpleNamespace
import unittest
import uuid
RS="11111111-1111-4111-8111-111111111111"
A=uuid.uuid5(uuid.UUID(RS),"q:1").hex
from resident_controller.action_progress import active_progress

class ProgressTests(unittest.TestCase):
    def task(self):
        return SimpleNamespace(capability_unknown=False,capability_cancel_attempted=False,
            action_id=A,step_number=1,last_action_observed_monotonic=10.,last_action_observed_unix=100.,
            command={'request_id':'q','action':'combat_entity','target_uuid':'target','target_type':'minecraft:zombie','target_entity_id':42,'scoped_native_preflight':{
                'version':'scoped-native-preflight/1','owner_id':'owner','owner_generation':2,'defense_epoch':0,'job_id':'job','profile':'combat-local-observed-v1'}},
            last_action_result={'action_schema_version':1,'action_id':A,'action_session':'as','action':'combat_entity','status':'running','ticks':3,
                'result':{'combat':{'target_uuid':'target','target_type':'minecraft:zombie','target_entity_id':42,'attack_dispatches':1,'target_health':16.,'secret':'excluded'}}})
    def test_exact_fresh_projection(self):
        t=self.task();v=active_progress(t,RS,'as',10.1)
        self.assertEqual(v['request_id'],'q');self.assertEqual(v['owner_id'],'owner')
        self.assertNotIn('secret',v['combat']);self.assertEqual(v['combat']['target_health'],16.)
        self.assertFalse(v['dispatch_authority']);v['combat']['attack_dispatches']=99
        self.assertEqual(t.last_action_result['result']['combat']['attack_dispatches'],1)
    def test_missing_stale_future_terminal_replacement_clear(self):
        self.assertIsNone(active_progress(None,RS,'as',10.1))
        for now in (9.9,10.81):self.assertIsNone(active_progress(self.task(),RS,'as',now))
        for field,value in [('status','succeeded'),('status','cancelled'),('status','failed'),('action_id','replacement'),('action_session','new'),('ticks',True)]:
            t=self.task();t.last_action_result[field]=value
            self.assertIsNone(active_progress(t,RS,'as',10.1))
        for field,value in [('action_id',None),('last_action_result',None),('capability_unknown',True),('capability_cancel_attempted',True)]:
            t=self.task();setattr(t,field,value);self.assertIsNone(active_progress(t,RS,'as',10.1))
    def test_actual_resident_acceptance_captures_and_terminal_clears(self):
        from unittest.mock import patch
        from resident_controller.controller import Resident, Running
        r=Resident.__new__(Resident)
        r.bridge_identity={'action_session':'as'}
        t=Running(deepcopy(self.task().command),iter(()),
            action_id=A,step_number=1)
        receipt=self.task().last_action_result
        with patch('resident_controller.controller.time.monotonic',return_value=10.), patch('resident_controller.controller.time.time',return_value=100.):
            r.accept_action_status(t,receipt)
        self.assertIsNotNone(active_progress(t,RS,'as',10.1))
        receipt['result']['combat']['attack_dispatches']=999
        self.assertEqual(t.last_action_result['result']['combat']['attack_dispatches'],1)
        for malformed in (None,[],{'combat':None},{'combat':[]}):
            bad=deepcopy(t.last_action_result);bad['result']=malformed
            r.accept_action_status(t,bad)
            self.assertIsNone(active_progress(t,RS,'as',t.last_action_observed_monotonic + .1))
        r.accept_action_status(t,self.task().last_action_result)
        terminal=deepcopy(t.last_action_result);terminal.update(status='succeeded',input_release_confirmed=True)
        r.accept_action_status(t,terminal)
        self.assertIsNone(active_progress(t,RS,'as',t.last_action_observed_monotonic + .1))
    def test_missing_owner_scope_clear(self):
        for scope in (None,{}, {'version':'scoped-native-preflight/1','owner_id':'','job_id':'job','owner_generation':1}):
            t=self.task();t.command['scoped_native_preflight']=scope
            self.assertIsNone(active_progress(t,RS,'as',10.1))
if __name__=='__main__':unittest.main()
