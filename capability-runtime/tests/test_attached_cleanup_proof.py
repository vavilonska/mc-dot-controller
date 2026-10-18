"""Exact normal attached disarm evidence across production owner boundaries."""
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from resident_controller import fall_rescue_attached as f
from resident_controller.controller import Resident
from resident_controller.transport import BridgeError
import test_attached_fall_boundaries as boundary
import test_attached_fall_owner_chain as chain

class ProofTests(unittest.TestCase):
    def fixture(self, status='succeeded'):
        t=boundary.Boundaries();t.setUp();f.arm(t.resident,t.task)
        action=t.native();action['status']=status;action['result']={'input_release_confirmed':True}
        t.task.last_action_result=deepcopy(action)
        t.value.update(armed=False,status='disarmed',remaining_ms=0,reason='explicit_disarm')
        return t,action
    def test_normal_disarm_is_separate_from_unknown_seal(self):
        t,action=self.fixture();self.assertFalse(f.terminal(t.resident,t.task,action))
        self.assertIsNone(t.task.fall_rescue)
        Resident.end_active(t.resident,'succeeded',result={'action':action})
        command,status,fields=t.receipts[0]
        self.assertNotIn('fall_rescue',fields)
        proof=f.verify_cleanup(fields['fall_rescue_cleanup'],t.binding,'combat_entity',{'status':status,**fields})
        self.assertFalse(proof['native_status']['armed']);self.assertEqual(proof['binding']['request_id'],command['request_id'])
    def test_known_exact_cancel_retains_original_cancelled_outcome(self):
        t,action=self.fixture('cancelled')
        c={'request_id':'cancel-one','expected_action_id':t.binding['action_id'],'expected_action_session':t.binding['context']['action_session']}
        f.cancel_exact(t.resident,t.task,c)
        self.assertEqual(t.receipts[0][1],'cancelled');self.assertNotIn('fall_rescue',t.receipts[0][2])
        self.assertEqual(t.receipts[0][2]['fall_rescue_cleanup']['original_action'],action)
        self.assertEqual([p for m,p,b in t.writes],['/control/fall-rescue/arm','/control/fall-rescue/disarm'])
    def test_closed_binding_and_unknown_markers_rejected(self):
        t,action=self.fixture();f.terminal(t.resident,t.task,action);proof=t.task.fall_rescue_cleanup
        mutations=[]
        for key in proof:mutations.append(lambda v,key=key:v.pop(key))
        mutations += [lambda v:v.update(extra=True),lambda v:v.update(schema_version=True)]
        for key in ('arm_id','action_id','owner_id','resident_session','request_id','job_id'):
            mutations.append(lambda v,key=key:v['binding'].__setitem__(key,'foreign'))
        for key in ('arm_id','owner_id','world_generation','player_uuid','action_session'):
            mutations.append(lambda v,key=key:v['native_status'].__setitem__(key,'foreign'))
        for key in ('input_owned','automation_blocked','unknown_outcome_quarantined'):
            mutations.append(lambda v,key=key:v['native_status'].__setitem__(key,True))
        for key in ('action_id','action_session','action'):
            mutations.append(lambda v,key=key:v['original_action'].__setitem__(key,'foreign'))
        for key in ('unknown_outcome','requires_handoff','preempted_by_native_fall_rescue','requires_reconciliation_before_retry','partial_effects'):
            mutations.append(lambda v,key=key:v['original_action']['result'].__setitem__(key,True))
        for outcome in ('unknown','unknown_interrupted','partial'):
            mutations.append(lambda v,outcome=outcome:v['original_action']['result'].__setitem__('effect_outcome',outcome))
        mutations.append(lambda v:v['original_action']['result'].__setitem__('input_release_confirmed',False))
        for index,change in enumerate(mutations):
            v=deepcopy(proof);change(v)
            with self.subTest(index=index),self.assertRaises((ValueError,KeyError,TypeError,BridgeError)):
                f.verify_cleanup(v,t.binding,'combat_entity')
        with self.assertRaises(ValueError):f.verify_cleanup(None,t.binding,'combat_entity')
    def test_replacement_during_validation_never_gets_proof(self):
        t,action=self.fixture();real=f.verify_cleanup;replacement=NS(replacement=True)
        def verify(*a,**kw):
            result=real(*a,**kw);t.resident.active=replacement;return result
        with patch.object(f,'verify_cleanup',side_effect=verify),self.assertRaises(BridgeError):f.retain_cleanup(t.resident,t.task,t.value)
        self.assertIs(t.resident.active,replacement);self.assertFalse(hasattr(replacement,'fall_rescue_cleanup'))
        self.assertFalse(hasattr(t.task,'fall_rescue_cleanup'))
    def test_finish_callback_cannot_clear_replacement(self):
        t,action=self.fixture();f.terminal(t.resident,t.task,action);replacement=NS(replacement=True);real=t.resident.finish
        def finish(*a,**kw):real(*a,**kw);t.resident.active=replacement
        t.resident.finish=finish;Resident.end_active(t.resident,'succeeded',result={'action':action})
        self.assertIs(t.resident.active,replacement)
    def test_runtime_archive_callback_cannot_install_on_replacement(self):
        from mdc_skills.attached_fall import retain
        t,action=self.fixture();f.terminal(t.resident,t.task,action)
        original=NS(job_id=t.binding['job_id']);replacement=NS(job_id=t.binding['job_id'])
        runtime=NS(_job_control=original,_owner=t.binding['owner_id'],_job_generation=t.binding['owner_generation'])
        runtime._receipt=lambda *args:setattr(runtime,'_job_control',replacement)
        def unknown(*args):raise ValueError('original_unknown')
        runtime._unknown=unknown
        record={'command':t.command,'request_id':'gateway-one','gateway_session':'gateway','job_id':original.job_id}
        result={'status':'succeeded','queue_request_id':t.binding['request_id'],'queue_session_id':t.binding['resident_session'],
                'result':{'action':action},'fall_rescue_cleanup':deepcopy(t.task.fall_rescue_cleanup)}
        with self.assertRaises(ValueError):retain(runtime,record,result)
        self.assertIs(runtime._job_control,replacement);self.assertFalse(hasattr(replacement,'fall_rescue_last_status'))


    def test_gateway_reads_and_persistence_cannot_clear_replacement(self):
        from capability_ownership import CapabilityOwnership
        for stage in ('read','persistence'):
            t,action=self.fixture();f.terminal(t.resident,t.task,action)
            proof=t.task.fall_rescue_cleanup
            old={'id':'old-intent','request_id':t.binding['request_id'],'resident_session':t.binding['resident_session'],
                'capability_owner':t.binding['owner_id'],'capability_op':'action',
                'attached_fall_binding':deepcopy(t.binding),'attached_fall_action':'combat_entity'}
            replacement={'id':'replacement'};lease={'owner_id':t.binding['owner_id'],'resident_session':t.binding['resident_session']}
            value={'request_id':old['request_id'],'session_id':old['resident_session'],'status':'succeeded',
                   'result':{'action':action},'fall_rescue_cleanup':proof}
            dog=NS(_fall_adjudications={},capability_lease=lease,stop_requested=False,owner=old,completed=[],session_id='gateway',
                rpc=None,capability_expired=lambda:None,capability_cancel_tick=lambda l:None)
            policy={'schema_version':1,'requires_handoff':False,'input_release_unconfirmed':False}
            def session():
                if stage=='read':dog.owner=replacement
                return {'session_id':old['resident_session'],'resident_policy':policy}
            def checkpoint(l):
                if stage=='persistence':dog.owner=replacement
            dog.q=NS(result=lambda rid:deepcopy(value),session=session);dog.capability_checkpoint=checkpoint
            dog.capability_pause=lambda reason:self.fail('must not pause replacement owner')
            self.assertTrue(CapabilityOwnership.capability_tick(dog))
            self.assertIs(dog.owner,replacement);self.assertIs(dog.capability_lease,lease)
            self.assertEqual(dog.completed[0]['intent_id'],'old-intent')

class OwnerChainTests(unittest.TestCase):
    def run_case(self, transform=None, cancel=False):
        t=chain.AttachedChainTests();t.setUp();retained={};real_finish=t.runtime.finish_job;resident_finish=t.resident.finish
        def finish_job(*args,**kwargs):
            retained['runtime']=deepcopy(getattr(t.runtime._job_control,'fall_rescue_last_status',None))
            retained['gateway']=deepcopy((t.dog.capability_lease or {}).get('cleanup_fall_status'))
            return real_finish(*args,**kwargs)
        def finish(command,status,**fields):
            if transform and 'fall_rescue_cleanup' in fields:transform(fields)
            return resident_finish(command,status,**fields)
        try:
            with patch.object(t.runtime,'finish_job',side_effect=finish_job),patch.object(t.resident,'finish',side_effect=finish):
                if cancel:t.bridge.hold=True
                result=t.submit()
                if cancel:
                    t.until(lambda:t.resident.active is not None and t.resident.active.fall_rescue is not None)
                    t.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':result['job_id'],
                        'session_ref':result['session_ref'],'cancel_request_id':'known-cancel','wait_ms':1000})
                result=t.finish(result)
            if transform:
                self.assertEqual(result['state'],'unknown',result);self.assertIsNotNone(t.dog.capability_lease)
                self.assertNotEqual(result['cleanup_certainty'],'confirmed')
            else:
                self.assertEqual(result['state'],'cancelled' if cancel else 'succeeded',result)
                self.assertEqual(result['cleanup_certainty'],'confirmed',result)
                self.assertIsNotNone(retained['runtime']);self.assertEqual(retained['runtime'],retained['gateway'])
                self.assertFalse(retained['runtime']['armed']);self.assertIsNone(t.dog.capability_lease)
            self.assertEqual([p for p,b in t.bridge.posts].count('/control/scoped-action'),1)
            self.assertEqual([p for p,b in t.bridge.fall_calls].count('disarm'),1)
        finally:t.tearDown()
    def test_normal_attached_completion_carries_both_prior_proofs(self):self.run_case()
    def test_nonpreempted_exact_cancel_carries_both_prior_proofs(self):self.run_case(cancel=True)
    def test_missing_proof_does_not_release(self):self.run_case(lambda f:f.pop('fall_rescue_cleanup'))
    def test_foreign_proof_does_not_release(self):self.run_case(lambda f:f['fall_rescue_cleanup']['binding'].update(owner_id='foreign'))
    def test_unknown_action_proof_does_not_release(self):self.run_case(lambda f:f['fall_rescue_cleanup']['original_action']['result'].update(unknown_outcome=True))

if __name__=='__main__':unittest.main()
