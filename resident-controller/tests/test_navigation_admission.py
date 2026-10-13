"""Only actual POST rejection provenance can authorize a fresh navigation plan."""
import copy
import tempfile
import unittest
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.transport import BridgeError
from test_controller import FakeBridge


class RejectedBridge(FakeBridge):
    def __init__(self, code, status, uncertain=False):
        super().__init__();self.error=BridgeError(code,status=status,uncertain=uncertain)
    def request(self,method,path,body=None):
        if method=='POST' and path=='/control/action':
            self.calls.append((method,path,copy.deepcopy(body)))
            raise self.error
        return super().request(method,path,body)


class NavigationAdmissionTests(unittest.TestCase):
    def execute(self,bridge):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        resident=Resident(bridge,temp.name);resident.start();self.addCleanup(resident.lock.close)
        q=QueueClient(temp.name)
        body={'op':'action','action':'follow_path','waypoints':[{'x':1.5,'y':64,'z':.5}],
              'expected_navigation_epoch':3,'expected_origin':{'x':.5,'y':64,'z':.5}}
        rid=q.submit(body);resident.tick()
        return resident,q,rid,body
    def test_real_post_409_preserves_exact_code_and_exposes_unadmitted_provenance(self):
        for code in ('navigation_rebind_required','navigation_epoch_changed','navigation_not_settled','navigation_origin_changed'):
            bridge=RejectedBridge(code,409);resident,q,rid,body=self.execute(bridge)
            result=q.result(rid)
            self.assertEqual('failed',result['status']);self.assertEqual(code,result['reason'])
            self.assertEqual({'schema_version':1,'http_status':409,'admitted':False,'uncertain':False,'reason':code},result['action_admission'])
            self.assertIsNone(result['action_id']);self.assertIsNone(result['action'])
            self.assertEqual(1,len([c for c in bridge.calls if c[0]=='POST']))
            sent=next(c[2] for c in bridge.calls if c[0]=='POST')
            self.assertEqual(body['expected_origin'],sent['expected_origin'])
            self.assertEqual(3,sent['expected_navigation_epoch'])
            self.assertTrue(resident.cache.native_binding.dump()['seen'])
    def test_400_and_identity_rejection_not_marked_recoverable_by_reason(self):
        for code,status in [('expected_origin_required',400),('world_generation_changed',409),('navigation_origin_changed',400)]:
            bridge=RejectedBridge(code,status);resident,q,rid,_=self.execute(bridge)
            self.assertEqual('failed',q.result(rid)['status'])
            evidence=q.result(rid).get('action_admission')
            if evidence:self.assertEqual(status,evidence['http_status'])
            self.assertFalse(resident.paused)
    def test_uncertain_even_with_409_is_not_definite_no_effect(self):
        bridge=RejectedBridge('navigation_origin_changed',409,True)
        resident,q,rid,_=self.execute(bridge)
        result=q.result(rid)
        self.assertEqual('uncertain',result['status'])
        self.assertNotIn('action_admission',result)
        self.assertTrue(resident.paused)
    def test_5xx_and_transport_failure_never_get_recovery_evidence(self):
        for status in (500,None):
            bridge=RejectedBridge('navigation_origin_changed',status,True)
            resident,q,rid,_=self.execute(bridge)
            self.assertEqual('uncertain',q.result(rid)['status'])
            self.assertNotIn('action_admission',q.result(rid))
    def test_admitted_terminal_navigation_text_is_not_admission_rejection(self):
        bridge=FakeBridge();resident,q,rid,_=self.execute(bridge)
        bridge.action.update(status='failed',reason='navigation_origin_changed',result={'input_release_confirmed':True})
        resident.active.wake_at=0;resident.tick()
        result=q.result(rid)
        self.assertEqual('failed',result['status']);self.assertNotIn('action_admission',result)
        self.assertEqual(bridge.action,result['action'])

    def test_later_recipe_rejection_remembers_capability_without_whole_task_no_effect_claim(self):
        from resident_controller.controller import Running
        bridge=RejectedBridge('navigation_rebind_required',409)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        resident=Resident(bridge,temp.name);resident.start();self.addCleanup(resident.lock.close)
        q=QueueClient(temp.name)
        command={'op':'pillar','request_id':'prior-placement','session_id':resident.session_id}
        def next_placement():
            yield {'step':'action','body':{'action':'place_block','support':{'x':0,'y':64,'z':0},'face':'up'}}
        previous={'status':'succeeded','reason':'block_placed_observed','action_id':'prior-native'}
        resident.active=Running(command,next_placement(),step_number=1,last_action_result=previous)
        resident.tick()
        result=q.result('prior-placement')
        self.assertEqual('failed',result['status']);self.assertEqual(previous,result['action'])
        self.assertNotIn('action_admission',result)
        self.assertTrue(resident.cache.native_binding.dump()['seen'])
        for _ in range(3):resident.tick()
        self.assertEqual(1,sum(p=='/control/action' for _,p,_ in bridge.calls))
