"""Focused closed public, producer and Resident consumers; all fixtures synthetic."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from mdc_skills import scoped_step_down as s, scoped_mobility
from mdc_skills.core import Outcome, SkillError
from mdc_toolbox.catalog import CapabilityCatalog
from mdc_toolbox.contracts import ToolboxError
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.movement_wire import valid_size_diagnostic
from step_down_fixture import fixture,terminal


def observed():
    return SimpleNamespace(context=('w','minecraft:overworld','p','a'),player={'x':.5,'y':64.,'z':.5,
        'health':20.,'on_ground':True,'velocity':{'x':0.,'y':0.,'z':0.},
        'inventory':[],'inventory_total':0,'inventory_truncated':False,'selected_slot':0},
        state={'movement_budget':{'schema_version':1,'status':'unarmed'}})


class Runtime:
    required_execution_policy='request_only'
    profile=s.PROFILE
    def __init__(self):self.before=observed();self.calls=[]
    def scoped_profile(self,action):return self.profile
    def observe(self,**kwargs):self.calls.append(('observe',kwargs));return self.before
    def execute(self,name,command,verify,**kwargs):
        self.calls.append(('execute',name,command,verify,kwargs));return Outcome('unknown','synthetic-lost')


class StepDownContractTests(unittest.TestCase):
    def test_exact_one_action_no_replay_on_unknown(self):
        r=Runtime();out=s.navigate_step_down(r,{'x':1,'y':63,'z':0})
        self.assertEqual(out.status,'unknown');self.assertFalse(out.evidence['automatic_replay_allowed'])
        self.assertEqual(len(r.calls),2);command=r.calls[1][2]
        self.assertEqual(command,{'op':'action','action':'follow_path','waypoints':[{'x':1.5,'y':63,'z':.5,'jump':False}],
            'capability_route':True,'timeout_ms':8000,'min_health':12})
    def test_closed_schema_and_old_flat_is_not_descent(self):
        c=CapabilityCatalog();args={'goal':{'x':1,'y':63,'z':0}}
        e=c.validate('navigate_step_down',1,args)
        self.assertEqual(e['bounds']['footprint_cells'],180);self.assertFalse(e['resume_supported'])
        for key in ('jump','sprint','timeout_ms','waypoints','max_segments','capability_route'):
            with self.assertRaises(ToolboxError):c.validate('navigate_step_down',1,{**args,key:True})
        with self.assertRaises(SkillError):scoped_mobility._points(observed().player,args['goal'])
        self.assertNotIn('navigate',OwnerRuntimeBackend.INITIAL_CAPABILITIES)
        self.assertNotIn('navigate_loaded',OwnerRuntimeBackend.INITIAL_CAPABILITIES)
        backend=OwnerRuntimeBackend(SimpleNamespace())
        self.assertEqual(backend._profile_actions({'scoped_profiles':{s.PROFILE:['follow_path']}}),{})
        self.assertEqual(backend._profile_actions({'scoped_profiles':{s.PROFILE:['follow_path'],scoped_mobility.PROFILE:['follow_path']}}),
            {'follow_path':scoped_mobility.PROFILE})
    def test_invalid_goal_policy_profile_meter_before_dispatch(self):
        for goal in ({'x':1,'y':64,'z':0},{'x':1,'y':65,'z':0},{'x':1,'y':62,'z':0},
                     {'x':1,'y':63,'z':1},{'x':2,'y':63,'z':0}):
            r=Runtime()
            with self.assertRaises(SkillError):s.navigate_step_down(r,goal)
            self.assertFalse(any(c[0]=='execute' for c in r.calls))
        for attr,value in (('profile',scoped_mobility.PROFILE),('required_execution_policy','noncombat')):
            r=Runtime();setattr(r,attr,value)
            with self.assertRaises(SkillError):s.navigate_step_down(r,{'x':1,'y':63,'z':0})
            self.assertFalse(r.calls)
        r=Runtime();r.before.state['movement_budget']['status']='armed'
        with self.assertRaises(SkillError):s.navigate_step_down(r,{'x':1,'y':63,'z':0})
        self.assertEqual(len(r.calls),1)
    def test_semantic_goal_rejects_motion_height_and_terminal_forgery(self):
        obs=observed();obs.player.update(x=1.5,y=63.)
        obs.state['client_action']={'action':'follow_path','status':'succeeded','result':{
            'input_release_confirmed':True,'step_down':{'profile':s.PROFILE,'phase':'landed','landed':True,'input_neutral':True}}}
        target={'x':1.5,'y':63,'z':.5};self.assertTrue(s._settled_goal(obs,target))
        for field,value in (('phase','descending'),('landed',False),('input_neutral',False),('profile',scoped_mobility.PROFILE)):
            bad=deepcopy(obs);bad.state['client_action']['result']['step_down'][field]=value
            self.assertFalse(s._settled_goal(bad,target))
        for field,value in (('y',63.1),('on_ground',False),('x',1.8)):
            bad=deepcopy(obs);bad.player[field]=value;self.assertFalse(s._settled_goal(bad,target))
        bad=deepcopy(obs);bad.player['velocity']['x']=.004;self.assertFalse(s._settled_goal(bad,target))
        before=observed();self.assertTrue(s._protected(before,obs))
        bad=deepcopy(obs);bad.player['health']=19;self.assertFalse(s._protected(before,bad))
        bad=deepcopy(obs);bad.player['inventory'].append({'slot':0});self.assertFalse(s._protected(before,bad))
    def test_full_resident_witness_and_negative_geometry(self):
        data=fixture();self.assertTrue(validate_scoped_witness(*data)['admitted'])
        for key,value in (('movement_budget_status','armed'),('maximum_airborne_ticks',21),('source_food_level',5),('expected_cells',150)):
            bad=fixture();bad[0]['result']['scoped_native_preflight']['facts']['step_down'][key]=value
            with self.assertRaises(ValueError):validate_scoped_witness(*bad)
        for target in ('missing','fluid','support','headroom'):
            bad=fixture();m=bad[0]['result']['scoped_native_preflight']['facts']['step_down']
            if target=='missing':m['cells'].pop()
            elif target=='fluid':m['cells'][0]['fluid']='minecraft:water'
            elif target=='support':m['cells'][0]['full_cube']=False
            else:next(c for c in m['cells'] if c['y']==64)['id']='minecraft:stone'
            with self.assertRaises(ValueError):validate_scoped_witness(*bad)
    def test_terminal_and_profile_substitution_are_rejected(self):
        data=fixture();data[0]['result']['step_down']=terminal(data[0]);validate_scoped_witness(*data)
        cancelled=deepcopy(data);cancelled[0]['status']='cancelled'
        validate_scoped_witness(*cancelled)  # Lower ground reached, residual velocity may still be settling.
        succeeded=fixture();succeeded[0]['status']='succeeded'
        with self.assertRaises(ValueError):validate_scoped_witness(*succeeded)
        for key,value in (('phase','descending'),('profile',scoped_mobility.PROFILE),('sampled_horizontal_distance',3.),('last_entity_check_action_tick',160)):
            bad=deepcopy(data);bad[0]['result']['step_down'][key]=value
            with self.assertRaises(ValueError):validate_scoped_witness(*bad)
        bad=deepcopy(data);bad[0]['result']['scoped_native_preflight']['profile']=scoped_mobility.PROFILE
        with self.assertRaises(ValueError):validate_scoped_witness(*bad)

    def test_capability_specific_negotiation(self):
        base={'state':'ready','capability_context':{k:'identity' for k in ('world_generation','dimension','player_uuid','action_session')},
            'capability_lease_schema_version':1,'private_singleplayer':True,'execution_policy':'request_only',
            'scoped_native_preflight':{'version':'scoped-native-preflight/1','same_callback_capture_validate_admit':True,
                'private_singleplayer_only':True,'capability_guard_schema_version':1,'guarded_actions':['follow_path']}}
        for profiles,expected in (({s.PROFILE:['follow_path']},{'navigate_step_down'}),
            ({scoped_mobility.PROFILE:['follow_path']},{'navigate_local'}),
            ({s.PROFILE:['follow_path'],scoped_mobility.PROFILE:['follow_path']},{'navigate_local','navigate_step_down'}),
            ({s.PROFILE:['follow_path','break_block']},set()),({s.PROFILE:['break_block']},set()),({},set())):
            session=deepcopy(base);session['scoped_native_preflight']['profiles']=profiles
            runtime=SimpleNamespace(client=SimpleNamespace(session=lambda:session),has_unresolved_execution=False)
            actual=set(OwnerRuntimeBackend(runtime).describe()['supported_capabilities'])
            self.assertEqual(actual & {'navigate_local','navigate_step_down','collect_local'},expected)
        session=deepcopy(base);session['execution_policy']='standard';session['scoped_native_preflight']['profiles']={s.PROFILE:['follow_path']}
        self.assertNotIn('navigate_step_down',OwnerRuntimeBackend(SimpleNamespace(client=SimpleNamespace(session=lambda:session),has_unresolved_execution=False)).describe()['supported_capabilities'])

if __name__=='__main__':unittest.main()
