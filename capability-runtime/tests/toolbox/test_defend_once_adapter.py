"""Public service/production adapter transition with a synthetic Runtime.
No native physics, real game or live acceptance is established here.
"""
from copy import deepcopy
from types import SimpleNamespace
import tempfile
import unittest
from mdc_skills.core import Outcome
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend

TARGET='44444444-4444-4444-8444-444444444444'
PLAYER='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
CONTEXT=('world', 'minecraft:overworld', PLAYER, 'action-session')


class Runtime:
    def __init__(self):
        self._job_control=None; self._job_effect_certainty='none_proven'; self._job_request_ids=[]
        self.has_unresolved_execution=False; self._lease_active=False
        self.client=SimpleNamespace(session=self.session)
        self.commands=[]; self.begins=0; self.finishes=0; self.mutate=None
        self.native={'action_id':'original-id', 'action_session':CONTEXT[3], 'action':'follow_path',
            'status':'cancelled', 'reason':'capability_damage_observed', 'result':{'input_release_confirmed':True}}
        self.ordinary_status='cancelled'; self.defense_status='succeeded'; self.profile=True
    def session(self):
        return {'session_id':'session', 'state':'ready', 'private_singleplayer':True,
            'capability_context':dict(zip(('world_generation','dimension','player_uuid','action_session'),CONTEXT)),
            'capability_lease_schema_version':1, 'capability_cancel_schema_version':1, 'execution_policy':'request_only',
            'scoped_native_preflight':{'version':'scoped-native-preflight/1', 'same_callback_capture_validate_admit':True,
                'private_singleplayer_only':True, 'capability_guard_schema_version':1,
                'profiles':{'movement-flat-observed-v2':['follow_path'],
                    **({'combat-local-observed-v1':['combat_entity']} if self.profile else {})},
                'guarded_actions':['follow_path','combat_entity']}}
    def begin_job(self, control, **kwargs):
        self.begins+=1; self._job_control=control; self._lease_active=True
    def owner_context(self): return {'owner_id':'same-owner','owner_generation':1,'gateway_session':'session','world_context':list(CONTEXT)}
    def finish_job(self):
        self.finishes+=1
        if self.has_unresolved_execution:return Outcome('unknown','job_execution_requires_reconciliation')
        with self._job_control.cleanup():self._job_control.consume('observations')
        self._job_control=None; self._lease_active=False
        return Outcome('succeeded','job_owner_release_confirmed')
    def observe(self, **kwargs):
        self._job_control.consume('observations')
        target={'uuid':TARGET,'entity_id':9,'type':'minecraft:zombie','alive':True,'health':20.,'x':2.,'y':64.,'z':0.,
            'native_living':{'schema_version':1,'entity_uuid':TARGET,'entity_id':9,'entity_type':'minecraft:zombie',
                'dimension':CONTEXT[1],'world_generation':CONTEXT[0],'player_uuid':PLAYER,
                'known':True,'coverage_complete':True,'inspected':1,'source':'integrated_server_tick','reason':'observed',
                'alive':True,'current_target_known':True,'current_target':{'uuid':PLAYER,'type':'minecraft:player'},
                'sample_tick':11,'source_tick':10,'source_nano':'1000000000','sample_nano':'1010000000','sample_age_ms':10.}}
        obs=SimpleNamespace(context=CONTEXT,tick=11,player={'uuid':PLAYER,'health':20.,'x':0.,'y':64.,'z':0.,
            'on_ground':True,**{k:False for k in ('in_water','eye_in_water','in_lava','in_powder_snow','on_fire')}},
            state={'client_action':deepcopy(self.native),'capability_guard':{'schema_version':1,'source_tick':11,'source_nano':'1005000000'},
                'nearby':{'entities':[target],'truncated':False,'returned':1,'total':1}})
        if self.mutate:self.mutate(obs,target)
        return obs
    def execute(self, skill, command, verify, **kwargs):
        self._job_control.consume('actions'); self.commands.append((skill,deepcopy(command),self._job_control))
        self._job_request_ids.append('defense-request')
        if self.defense_status=='unknown':self.has_unresolved_execution=True;self._job_effect_certainty='unknown'
        return Outcome(self.defense_status,'synthetic-defense',('defense-request',))


class OrdinaryPlugin:
    def invoke(self, capability, runtime, arguments, control):
        control.consume('actions'); runtime._job_effect_certainty='known';runtime._job_request_ids.append('ordinary-request')
        return Outcome(runtime.ordinary_status,runtime.native['reason'],('ordinary-request',),
            {'native':deepcopy(runtime.native)},SimpleNamespace(context=CONTEXT))


class DefendOnceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.runtime=Runtime(); self.backend=OwnerRuntimeBackend(self.runtime, {'navigate_local':OrdinaryPlugin()})
        self.service=ToolboxService(self.backend,self.temp.name)
        desc=self.backend.describe()
        self.request={'api_version':'mdc.toolbox/1','operation':'submit','request_id':'defend-once-test',
            'session_ref':desc['session_ref'],'expected_context_ref':desc['context_ref'],'capability':'navigate_local',
            'capability_version':1,'arguments':{'goal':{'x':1,'y':64,'z':0}},
            'policy':{'version':1,'execution_mode':'request_only','reactions':'defend_once',
                'defense':{'target_uuid':TARGET,'timeout_ms':2000,'min_health':14}},
            'budgets':{'deadline_seconds':30,'max_actions':3,'reflex_reserve_actions':1,'cleanup_reserve_actions':1,'max_observations':20},'wait_ms':1000}
    def tearDown(self):self.temp.cleanup()
    def submit(self):return self.service.call('mdc_job',self.request)
    def test_public_transition_one_owner_and_no_resume(self):
        result=self.submit()
        self.assertEqual(result.get('state'),'interrupted', result)
        self.assertEqual(result['result']['reason'],'ordinary_task_interrupted_after_defense')
        self.assertEqual((self.runtime.begins,self.runtime.finishes),(1,1))
        self.assertEqual(len(self.runtime.commands),1)
        cmd=self.runtime.commands[0][1]
        self.assertEqual((cmd['target_uuid'],cmd['approach'],cmd['shield']),(TARGET,False,True))
        result2=self.submit();self.assertEqual(result2['job_id'],result['job_id']);self.assertEqual(len(self.runtime.commands),1)
    def test_stop_policy_does_not_defend(self):
        self.request['policy']={'version':1,'execution_mode':'request_only','reactions':'stop'}
        self.assertEqual(self.submit()['state'],'cancelled');self.assertFalse(self.runtime.commands)
    def test_explicit_target_required(self):
        del self.request['policy']['defense']['target_uuid']
        self.assertEqual(self.submit()['error']['code'],'invalid_request');self.assertEqual(self.runtime.begins,0)
    def test_noncombat_mode_refuses_defense(self):
        self.request['policy']['execution_mode']='noncombat'
        self.assertEqual(self.submit()['error']['code'],'invalid_request')
    def test_unsupported_reaction_keeps_rejected(self):
        self.request['policy']={'version':1,'execution_mode':'request_only','reactions':'defend'}
        self.assertEqual(self.submit()['error']['code'],'policy_violation')
    def test_no_native_combat_no_admission(self):
        self.runtime.profile=False
        self.assertEqual(self.submit()['error']['code'],'policy_violation');self.assertFalse(self.runtime.commands)
    def test_no_reflex_reserve_no_dispatch(self):
        self.request['budgets']['reflex_reserve_actions']=0
        self.assertEqual(self.submit()['state'],'blocked');self.assertEqual(self.runtime.begins,0)
    def test_hazard_is_not_counterattack(self):
        self.runtime.native['reason']='capability_environment_hazard'
        self.assertEqual(self.submit()['state'],'cancelled');self.assertFalse(self.runtime.commands)
    def test_unknown_original_no_dispatch(self):
        self.runtime.ordinary_status='unknown'
        self.assertEqual(self.submit()['state'],'unknown');self.assertFalse(self.runtime.commands)
    def test_unconfirmed_native_release_no_dispatch(self):
        self.runtime.native['result']['input_release_confirmed']=False
        self.assertEqual(self.submit()['state'],'unknown');self.assertFalse(self.runtime.commands)
    def test_target_not_attacking_refuses(self):
        self.runtime.mutate=lambda obs,row:row['native_living'].update(current_target=None)
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_stale_attacker_refuses(self):
        self.runtime.mutate=lambda obs,row:row['native_living'].update(sample_age_ms=251)
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_context_changed_refuses(self):
        self.runtime.mutate=lambda obs,row:setattr(obs,'context',('changed',*CONTEXT[1:]))
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_player_or_unsupported_target_refuses(self):
        self.runtime.mutate=lambda obs,row:row.update(type='minecraft:player')
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_health_reserve_refuses(self):
        self.runtime.mutate=lambda obs,row:obs.player.update(health=14)
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_unknown_defense_quarantines_no_retry(self):
        self.runtime.defense_status='unknown'
        result=self.submit();self.assertEqual(result['state'],'unknown');self.assertEqual(len(self.runtime.commands),1)
        self.submit();self.assertEqual(len(self.runtime.commands),1);self.assertTrue(self.backend._quarantined)
    def test_unknown_target_uuid_refuses(self):
        self.request['policy']['defense']['target_uuid']='55555555-5555-4555-8555-555555555555'
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_out_of_range_refuses(self):
        self.runtime.mutate=lambda obs,row:row.update(x=7.)
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_original_action_replaced_refuses(self):
        self.runtime.mutate=lambda obs,row:obs.state['client_action'].update(action_id='other-action')
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_cancel_during_fresh_observation_prevents_defense(self):
        self.runtime.mutate=lambda obs,row:self.runtime._job_control.cancel_event.set()
        self.assertEqual(self.submit()['state'],'cancelled');self.assertFalse(self.runtime.commands)
    def test_native_target_clock_spoof_refuses(self):
        self.runtime.mutate=lambda obs,row:row['native_living'].update(source_nano='100000')
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)
    def test_observation_cleanup_reserve(self):
        self.request['budgets']['max_observations']=14
        self.assertEqual(self.submit()['state'],'blocked');self.assertFalse(self.runtime.commands)

if __name__=='__main__':unittest.main()
