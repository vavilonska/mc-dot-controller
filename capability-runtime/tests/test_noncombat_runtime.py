"""Runtime binds an explicitly requested local watchdog policy without weakening receipts."""
from copy import deepcopy
import tempfile
import unittest
from mdc_skills.core import Runtime, SkillError
from support_core import Clock, Client, move, arrived

class PolicyClient(Client):
    def __init__(self, clock):
        super().__init__(clock)
        self.policy = 'noncombat'
    def session(self):
        return {**super().session(), 'execution_policy_schema_version': 1, 'execution_policy': self.policy}

class NoncombatRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.clock=Clock();self.client=PolicyClient(self.clock)
        self.runtime=Runtime(self.client,self.temp.name,clock=self.clock,sleeper=self.clock.sleep,
                             required_execution_policy='noncombat')
    def tearDown(self):self.runtime.close();self.temp.cleanup()
    def reject(self,result):
        if 'action' not in result.get('result',{}):return result
        return {'request_id':result['request_id'],'session_id':result['session_id'],
            'status':'cancelled','reason':'noncombat_execution_policy','queue_request_id':None,
            'gameplay_effect_confirmed':False,
            'policy_rejection':{'schema_version':1,'execution_policy':'noncombat','dispatched':False}}
    def test_noncombat_policy_required_before_first_read(self):
        self.client.policy='standard'
        with self.assertRaisesRegex(SkillError,'required_execution_policy_not_active'):self.runtime.observe()
        self.assertFalse(self.client.calls)
        self.assertIsNone(self.runtime.pending_request_id)
    def test_policy_cannot_change_between_observation_and_mutation(self):
        before=self.runtime.observe();self.client.policy='standard'
        outcome=self.runtime.execute('walk',move(),arrived,before=before)
        self.assertFalse(outcome.ok);self.assertEqual(self.client.action_count,0)
    def test_policy_missing_or_malformed_blocks(self):
        original=self.client.session
        for bad in [None,True,0,'1']:
            self.client.session=lambda:{**original(),'execution_policy_schema_version':bad}
            with self.assertRaisesRegex(SkillError,'required_execution_policy_not_active'):self.runtime.observe()
    def test_exact_noncombat_denial_is_known_no_effect_not_unknown(self):
        self.client.patch_result=self.reject
        result=self.runtime.execute('walk',move(),arrived)
        self.assertEqual((result.status,result.reason),('blocked','noncombat_execution_policy'))
        self.assertIsNone(self.runtime.pending_request_id)
    def test_unproven_or_contradictory_policy_denials_stay_unknown(self):
        valid=self.reject({'request_id':'r','session_id':'s','result':{'action':{}}})
        for key,value in [('queue_request_id','dispatched'),('gameplay_effect_confirmed',True),('requires_handoff',True),('result',{'uncertain':True}),('result',{'action':{'status':'succeeded','action_id':'contradictory-native-id'}}),('result',{'cancellation':{'status':'cancelled'}})]:
            receipt={**deepcopy(valid),key:value}
            self.assertFalse(Runtime._no_effect(receipt),(key,value))
        for key,value in [('schema_version',True),('execution_policy','standard'),('dispatched',None),('uncertain',True)]:
            receipt=deepcopy(valid);receipt['policy_rejection'][key]=value
            self.assertFalse(Runtime._no_effect(receipt),(key,value))
        receipt=deepcopy(valid);receipt.pop('queue_request_id');self.assertFalse(Runtime._no_effect(receipt))
    def test_goal_success_rechecks_requested_policy(self):
        # The policy also applies to sole QueueClient fixtures; production uses IntentClient.
        before=self.runtime.observe();self.client.policy='standard'
        with self.assertRaisesRegex(SkillError,'required_execution_policy_not_active'):
            self.runtime.result('goal',[before])
        self.assertEqual(self.client.action_count,0)

if __name__=='__main__':unittest.main()
