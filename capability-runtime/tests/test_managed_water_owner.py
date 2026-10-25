"""Actual public managed owner chain; only the native endpoint's dry refusal is modeled."""
from copy import deepcopy
from unittest.mock import patch
import unittest
import test_managed_navigation_owner as managed

class ManagedWaterOwnerTests(unittest.TestCase):
    setUp=managed.ManagedOwnerTests.setUp
    tearDown=managed.ManagedOwnerTests.tearDown
    submit=managed.ManagedOwnerTests.submit
    finish=managed.ManagedOwnerTests.finish
    until=managed.ManagedOwnerTests.until

    def refusal(self,reason,at_goal=False):
        original=self.bridge.request
        def request(method,path,body=None):
            result=original(method,path,body)
            if path.endswith('/managed-navigation/status'):
                result=deepcopy(result)
                result.update(reason=reason,goal_reached=at_goal and result['state']=='settled',stop_attempted=True,cancel_accepted=True)
                if result['state']!='settled':result['state']='stopping'
                self.bridge.route.update({k:v for k,v in result.items() if k not in ('protocol','schema_version')})
            return result
        with patch.object(self.bridge,'request',request):
            first=self.submit();result=self.finish(first)
        self.assertEqual(result['state'],'interrupted',result)
        self.assertEqual(result['cleanup_certainty'],'confirmed',result)
        self.assertEqual(result['effect_certainty'],'known',result)
        self.assertEqual(result['result']['reason'],reason)
        evidence=result['result']['evidence']['native']
        self.assertEqual(evidence['reason'],reason)
        self.assertNotIn('dry_step',evidence)
        self.assertEqual([x[1] for x in self.bridge.route_calls].count('start'),1)
        self.assertEqual([x[1] for x in self.bridge.route_calls].count('cancel'),0)
        self.assertIsNone(self.client.session()['capability_lease'])
        before=len(self.bridge.route_calls)
        self.assertEqual(self.submit()['job_id'],first['job_id'])
        self.assertEqual(len(self.bridge.route_calls),before)

    def test_water_edge_is_known_interruption_without_replay(self):
        self.refusal('managed_navigation_step_fluid_present')
    def test_dry_support_gap_is_known_interruption_without_replay(self):
        self.refusal('managed_navigation_step_support_or_clearance')
    def test_cutoff_path_is_explicit_unsupported_not_a_water_success(self):
        self.refusal('managed_navigation_cutoff_path_reader_unsupported')
    def test_final_owner_reentry_is_interrupted_after_confirmed_idle(self):
        self.refusal('managed_navigation_dry_reentrant_check')
    def test_goal_location_does_not_turn_water_refusal_into_success(self):
        self.refusal('managed_navigation_step_fluid_present',at_goal=True)

if __name__=='__main__':unittest.main()
