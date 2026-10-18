from types import SimpleNamespace
import unittest
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend

class IntegratedDiscoveryTests(unittest.TestCase):
    def describe(self, version=None, ready=True):
        session={'native_fall_rescue':{'native_fences_ready':ready,'external_controller_unknown':False},
            'native_fall_rescue_attached_policy':'native-fall-rescue-attached-policy/1',
            'fall_rescue_original_adjudication':version}
        backend=OwnerRuntimeBackend(SimpleNamespace(client=SimpleNamespace(session=lambda:session),has_unresolved_execution=False),bindings={})
        return backend.describe()['fall_rescue_availability']
    def test_exact_adjudication_feature(self):
        for version in (None,True,1,'native-fall-rescue-original-adjudication/2',''):
            with self.subTest(version=version):self.assertFalse(self.describe(version)['operator_adjudication_available'])
        self.assertTrue(self.describe('native-fall-rescue-original-adjudication/1')['operator_adjudication_available'])
        self.assertFalse(self.describe('native-fall-rescue-original-adjudication/1',False)['operator_adjudication_available'])
    def test_attached_scope_excludes_managed_walking(self):
        value=self.describe('native-fall-rescue-original-adjudication/1')
        self.assertEqual(value['attached_native_actions'],['follow_path','combat_entity'])
        self.assertFalse(value['managed_walking_protected']);self.assertFalse(value['baritone_route_protected'])
        self.assertFalse(value['automatic_settlement']);self.assertIn('UNKNOWN',value['operator_adjudication_scope'])
        from mdc_toolbox.bindings.managed_navigation import definitions
        self.assertTrue(any('Attached fall rescue is unsupported' in v for v in definitions()[0]['known_limits']))

class AdjudicationCrossOwnerTests(unittest.TestCase):
    def test_scope_refuses_foreign_control_record_before_commit_and_status(self):
        from resident_controller.fall_rescue_adjudication import scope_current
        selected={'resident_session':'original','expected_context':{'action_session':'native-original'}}
        for paused,entry,reason in ((True,None,'fall_rescue_original_outcome_unknown'),(False,{'state':'authority_released'},None)):
            resident=SimpleNamespace(session_id='original',active=None,pending=[],combat=SimpleNamespace(active=False,held=False),
                aim=SimpleNamespace(active=False),bridge_identity={'action_session':'native-original'},paused=paused,reason=reason)
            self.assertTrue(scope_current(resident,selected,entry))
            for field in ('_external_navigation_owner','_managed_navigation_owner'):
                for value in ({},{'state':'unknown'},{'state':'settled'}):
                    setattr(resident,field,value)
                    with self.subTest(paused=paused,field=field,value=value):self.assertFalse(scope_current(resident,selected,entry))
                    setattr(resident,field,None)
            self.assertTrue(scope_current(resident,selected,entry))
