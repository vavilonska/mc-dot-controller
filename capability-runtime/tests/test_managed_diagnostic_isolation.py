"""Merged display reads cannot erase an existing managed ownership barrier."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from capability_ownership import CapabilityOwnership,safe_idle
import test_reconciliation_read as reconciliation

class CompactCompletionTests(unittest.TestCase):
    def test_compact_completion_keeps_authoritative_managed_barrier(self):
        for owned,quarantined in ((True,False),(False,True),(True,True)):
            with self.subTest(owned=owned,quarantined=quarantined):
                captured=[]
                policy={'schema_version':1,'requires_handoff':False,'input_release_unconfirmed':False}
                result={'request_id':'read','session_id':'resident','status':'succeeded','resident_policy':policy,
                    'result':{'execution_authority':False,'compact':{'display_only':True}}}
                class Dog(CapabilityOwnership):
                    def capability_expired(self):return False
                    def capability_cancel_tick(self,lease):pass
                    def capability_capture(self,value):captured.append(value)
                    def capability_pause(self,reason):raise AssertionError(reason)
                dog=Dog();dog.capability_lease={'owner_id':'original','managed_navigation':{'navigation_id':'route-original'}}
                dog.owner={'id':'intent','request_id':'read','resident_session':'resident','capability_owner':True,
                    'capability_op':'observe','compact_observation':True}
                dog.stop_requested=False;dog.completed=[];dog.rpc=None;dog.session_id='gateway'
                dog.latest={'state':{'managed_navigation_status':{'managed_navigation_schema_version':1,
                    'input_owned':owned,'unknown_outcome_quarantined':quarantined}}};dog.observed_at=7
                dog.q=SimpleNamespace(result=lambda _:deepcopy(result),session=lambda:{'session_id':'resident','resident_policy':policy})
                before=deepcopy(dog.latest);lease=deepcopy(dog.capability_lease)
                self.assertTrue(dog.capability_tick());self.assertEqual(captured,[])
                self.assertEqual(dog.latest,before);self.assertEqual(dog.observed_at,7)
                self.assertEqual(dog.capability_lease,lease);self.assertFalse(safe_idle(dog.latest))

class ReconciliationManagedTests(unittest.TestCase):
    setUp=reconciliation.ReconciliationTests.setUp
    tearDown=reconciliation.ReconciliationTests.tearDown
    until=reconciliation.ReconciliationTests.until
    read=reconciliation.ReconciliationTests.read
    assert_original=reconciliation.ReconciliationTests.assert_original
    def test_lease_free_read_does_not_settle_managed_quarantine(self):
        managed={'navigation_id':'original-managed-route','state':'unknown','input_owned':True,
            'unknown_outcome_quarantined':True,'managed_navigation_schema_version':1}
        self.resident._managed_navigation_owner=deepcopy(managed)
        self.dog.latest['state']['managed_navigation_status']=deepcopy(managed)
        original_latest=deepcopy(self.dog.latest);original_received=self.dog.observed_at
        value=self.read('managed-diagnostic')
        self.assertEqual(value['diagnostic']['state'],'succeeded',value)
        self.assertFalse(value['settles_original']);self.assertTrue(value['lease_free'])
        self.assertEqual(self.dog.latest,original_latest);self.assertEqual(self.dog.observed_at,original_received)
        self.assertEqual(self.resident._managed_navigation_owner,managed)
        self.assertFalse(safe_idle(self.dog.latest));self.assert_original()
        self.resident._managed_navigation_owner=None # End only the synthetic fixture marker.
