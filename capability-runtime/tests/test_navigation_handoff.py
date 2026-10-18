from copy import deepcopy
from types import SimpleNamespace
import tempfile
import unittest
from mdc_skills.navigation_handoff import report
from mdc_skills.core import Runtime, SkillError
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox import ToolboxService
from support_core import state, Clock, NATIVE
from test_execution_recovery_p0 import ReadLeaseClient


def complete(s):
    s=deepcopy(s)
    s['player'].update(environment_schema_version=1,in_water=False,eye_in_water=False,in_lava=False,
        in_powder_snow=False,on_fire=False,air=300,max_air=300,velocity={'x':0,'y':0,'z':0},vehicle={'riding':False})
    s['external_controller']={'schema_version':1,'idle_proven':True,'status':'absent',
        'action_session':s['client_action']['action_session'],'world_generation':s['world']['world_generation'],
        'player_uuid':s['player']['uuid'],'source_tick':s['world']['game_time']}
    return s


class HandoffTests(unittest.TestCase):
    def setUp(self):self.s=complete(state())
    def get(self,**kwargs):
        o=SimpleNamespace(state=self.s,player=self.s['player'],captured_at=100,request_id='original',tick=100,
             context=('world-one','minecraft:overworld','player-one',NATIVE))
        return report(o,now=kwargs.pop('now',100.1),max_age=.5,owner_released=kwargs.pop('owner_released',True),**kwargs)
    def test_walking_handoff_requires_new_admission(self):
        r=self.get();self.assertTrue(r['control_released']);self.assertTrue(r['physical_safe'])
        self.assertEqual(r['mode'],'walk');self.assertEqual(r['selector']['decision'],'fresh_owner_admission_required')
        self.assertFalse(r['selector']['execution_authority']);self.assertFalse(r['selector']['automatic_resume'])
    def test_swim_drift_does_not_mean_held_controls(self):
        self.s['player'].update(in_water=True,on_ground=False,velocity={'x':.08,'y':-.02,'z':.03})
        r=self.get();self.assertTrue(r['control_released']);self.assertTrue(r['physical_safe']);self.assertEqual(r['mode'],'swim')
        self.assertTrue(r['physics_motion_present'])
    def test_boat_drift(self):
        self.s['player'].update(on_ground=False,velocity={'x':.2,'y':0,'z':0},vehicle={'riding':True,
            'ordinary_boat':True,'controlling_seat':True,'alive':True,'water_status':'in_water'})
        r=self.get();self.assertTrue(r['control_released']);self.assertTrue(r['physical_safe']);self.assertEqual(r['mode'],'boat')
    def test_air_hazard_is_separate_from_control(self):
        self.s['player'].update(in_water=True,eye_in_water=True,air=10,on_ground=False)
        r=self.get();self.assertTrue(r['control_released']);self.assertFalse(r['physical_safe'])
        self.assertIn('air_critical',r['hazards']);self.assertEqual(r['selector']['decision'],'safety_recovery_required')
    def test_stale_and_reversed_do_not_grant_handoff(self):
        for now in (101,99):
            r=self.get(now=now);self.assertFalse(r['control_released']);self.assertIsNone(r['physical_safe'])
    def test_unknown_execution_blocks_even_neutral(self):
        r=self.get(unresolved=True);self.assertFalse(r['control_released'])
        self.assertEqual(r['selector']['decision'],'reconcile_original_owner')
    def test_rescue_quarantine_never_cleared_by_report(self):
        self.s['native_fall_rescue_status']={'fall_rescue_schema_version':1,'input_owned':False,'unknown_outcome_quarantined':True}
        before=deepcopy(self.s);r=self.get();self.assertFalse(r['control_released']);self.assertEqual(self.s,before)
    def test_lease_is_separate_from_controls(self):
        r=self.get(owner_released=False);self.assertTrue(r['control_released']);self.assertFalse(r['ownership_released'])
        self.assertEqual(r['selector']['decision'],'wait_exact_owner_release')
    def test_external_proof_missing_busy_or_cross_context(self):
        for patch in ({'idle_proven':False},{'action_session':'other'},{'source_tick':99},{'schema_version':2}):
            self.s['external_controller'].update(patch);self.assertFalse(self.get()['control_released']);self.s=complete(state())
    def test_falling_is_not_safe_even_if_controls_released(self):
        self.s['player'].update(on_ground=False,velocity={'x':0,'y':-.9,'z':0})
        r=self.get();self.assertTrue(r['control_released']);self.assertFalse(r['physical_safe']);self.assertEqual(r['mode'],'airborne')
    def test_unknown_environment_does_not_become_safe(self):
        del self.s['player']['environment_schema_version'];self.assertIsNone(self.get()['physical_safe'])
    def test_native_busy_neutral_is_not_release(self):
        self.s['client_action']['status']='running';self.assertFalse(self.get()['control_released'])
    def test_production_public_observation_and_cleanup_report(self):
        with tempfile.TemporaryDirectory() as d:
            clock=Clock();client=ReadLeaseClient(clock,d+'/runtime');client.patch_state=complete
            runtime=Runtime(client,d+'/runtime',clock=clock,sleeper=clock.sleep)
            backend=OwnerRuntimeBackend(runtime);service=ToolboxService(backend,d+'/service')
            r=service.call('mdc_observe',{'api_version':'mdc.toolbox/1','session_ref':backend.describe()['session_ref'],
                'profile':'player','request_id':'public-read'})
            self.assertEqual(r['job_state'],'succeeded',r)
            h=r['navigation_handoff'];self.assertTrue(h['ownership_released']);self.assertTrue(h['physical_safe'])
            self.assertIn(h['source_request_id'],r['request_ids']);self.assertNotEqual(h['source_request_id'],r['request_id'])
            service.shutdown();runtime.close()
    def test_fall_capabilities_and_live_status_are_separate(self):
        from capability_ownership import safe_idle
        self.s['native_fall_rescue']={'schema_version':1,'explicit_arm_required':True,'private_integrated_server_only':True}
        self.s['native_fall_rescue_status']={'fall_rescue_schema_version':1,'status':'disarmed',
            'input_owned':False,'unknown_outcome_quarantined':False}
        payload={'state':self.s,'action':{'status':'idle'},'combat':{'active':False},'status':{'held_mappings':[]}}
        self.assertTrue(safe_idle(payload));self.assertTrue(self.get()['control_released'])
        self.s['native_fall_rescue_status']['unknown_outcome_quarantined']=True
        self.assertFalse(safe_idle(payload));self.assertFalse(self.get()['control_released'])
        for bad in (None, {}, {'fall_rescue_schema_version':True,'input_owned':False,'unknown_outcome_quarantined':False}):
            self.s['native_fall_rescue_status']=bad
            self.assertFalse(safe_idle(payload));self.assertFalse(self.get()['control_released'])
        del self.s['native_fall_rescue_status']
        self.assertFalse(safe_idle(payload));self.assertFalse(self.get()['control_released'])

    def test_owner_lease_gate_blocks_external_controller_but_not_physics_drift(self):
        from capability_ownership import safe_idle
        payload={'state':self.s,'action':{'status':'idle'},'combat':{'active':False},'status':{'held_mappings':[]}}
        self.s['player'].update(in_water=True,on_ground=False,velocity={'x':.1,'y':-.02,'z':0})
        self.assertTrue(safe_idle(payload))
        self.s['external_controller']['idle_proven']=False
        self.assertFalse(safe_idle(payload))
        self.s['external_controller']['idle_proven']=True
        self.s['external_controller']['source_tick']=99
        self.assertFalse(safe_idle(payload))
        self.s['external_controller']['source_tick']=100
        self.s['native_fall_rescue_status']={'fall_rescue_schema_version':1,'input_owned':False,'unknown_outcome_quarantined':True}
        self.assertFalse(safe_idle(payload))

    def test_native_external_busy_rejected_by_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            clock=Clock();client=ReadLeaseClient(clock,d+'/runtime')
            def busy(s):s=complete(s);s['external_controller']['idle_proven']=False;return s
            client.patch_state=busy;runtime=Runtime(client,d+'/runtime',clock=clock,sleeper=clock.sleep)
            with self.assertRaises(SkillError) as error:runtime.observe()
            self.assertEqual(error.exception.reason,'external_controller_idle_unproven');runtime.close()
