"""Closed public negotiation and independent witness consumer tests; synthetic only."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from mdc_toolbox.catalog import CapabilityCatalog
from mdc_toolbox.contracts import ToolboxError
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.movement_wire import valid_size_diagnostic
from resident_controller.local_segment_snapshot import CONTEXT_LEAVES,FLOORS
from local_segment_fixture import fixture,terminal,PROFILE

class RouteLocalContractTests(unittest.TestCase):
    def test_closed_schema(self):
        catalog=CapabilityCatalog();args={'goal':{'x':4,'y':64,'z':0}}
        entry=catalog.validate('navigate_route_local',1,args)
        self.assertEqual(entry['bounds']['native_segments'],16);self.assertFalse(entry['resume_supported'])
        for key in ('waypoints','segments','jump','sprint','sneak','timeout_ms','profile','max_unstuck','recenter','vertical'):
            with self.subTest(key=key),self.assertRaises(ToolboxError):catalog.validate('navigate_route_local',1,{**args,key:True})
        for fields in ({'radius':1},{'radius':9},{'max_segments':0},{'max_segments':17},{'radius':True},{'min_health':21}):
            with self.assertRaises(ToolboxError):catalog.validate('navigate_route_local',1,{**args,**fields})
        for radius in (2,8):catalog.validate('navigate_route_local',1,{**args,'radius':radius})
        self.assertNotIn('navigate_loaded',OwnerRuntimeBackend.INITIAL_CAPABILITIES)
        self.assertNotIn('navigate',OwnerRuntimeBackend.INITIAL_CAPABILITIES)
    def test_profile_is_capability_specific_and_request_only(self):
        base={'state':'ready','capability_context':{k:'identity' for k in ('world_generation','dimension','player_uuid','action_session')},
            'capability_lease_schema_version':1,'private_singleplayer':True,'execution_policy':'request_only',
            'scoped_native_preflight':{'version':'scoped-native-preflight/1','same_callback_capture_validate_admit':True,
                'private_singleplayer_only':True,'capability_guard_schema_version':1,'guarded_actions':['follow_path']}}
        for profiles,expected in (({PROFILE:['follow_path']},{'navigate_route_local'}),
            ({'movement-flat-observed-v2':['follow_path']},{'navigate_local'}),
            ({PROFILE:['follow_path'],'movement-step-down-observed-v1':['follow_path']},{'navigate_route_local','navigate_step_down'}),
            ({PROFILE:['follow_path','break_block']},set()),({},set())):
            session=deepcopy(base);session['scoped_native_preflight']['profiles']=profiles
            runtime=SimpleNamespace(client=SimpleNamespace(session=lambda:session),has_unresolved_execution=False)
            backend=OwnerRuntimeBackend(runtime)
            self.assertEqual(set(backend.describe()['supported_capabilities']) & {'navigate_route_local','navigate_local','navigate_step_down'},expected)
            self.assertNotEqual(backend._profile_actions({'scoped_profiles':profiles}).get('follow_path'),PROFILE)
        session['execution_policy']='standard';session['scoped_native_preflight']['profiles']={PROFILE:['follow_path']}
        self.assertNotIn('navigate_route_local',backend.describe()['supported_capabilities'])
    def test_flat_up_down_full_coverage_and_terminal(self):
        for dy in (-1,0,1):
            data=fixture(dy=dy);validate_scoped_witness(*data)
            data[0]['status']='succeeded';data[0]['result'].update(input_release_confirmed=True,local_segment=terminal(data[0]))
            validate_scoped_witness(*data)
            self.assertEqual(len(data[0]['result']['scoped_native_preflight']['facts']['local_segment']['cells']),150 if dy==0 else 180)
    def test_roles_geometry_and_profile_substitution_fail(self):
        for mode in ('missing','fluid','support','headroom','role','special_context','meter','food','bounds','profile'):
            data=fixture(dy=1);m=data[0]['result']['scoped_native_preflight']['facts']['local_segment']
            if mode=='missing':m['cells'].pop()
            elif mode=='fluid':m['cells'][0]['fluid']='minecraft:water'
            elif mode=='support':next(c for c in m['cells'] if c['role']=='support')['full_cube']=False
            elif mode=='headroom':next(c for c in m['cells'] if c['role']=='clear' and c['y']==67)['id']='minecraft:stone'
            elif mode=='role':next(c for c in m['cells'] if c['role']=='clear')['role']='context'
            elif mode=='special_context':next(c for c in m['cells'] if c['role']=='context')['id']='minecraft:ice'
            elif mode=='meter':m['movement_budget_status']='armed'
            elif mode=='food':m['source_food_level']=5
            elif mode=='bounds':m['max_y']-=1
            else:data[0]['result']['scoped_native_preflight']['profile']='movement-step-down-observed-v1'
            with self.subTest(mode=mode),self.assertRaises(ValueError):validate_scoped_witness(*data)
    def test_station_and_reviewed_foliage_are_context_only(self):
        self.assertEqual(CONTEXT_LEAVES,{'minecraft:oak_leaves','minecraft:birch_leaves'})
        self.assertFalse(CONTEXT_LEAVES & FLOORS)
        for block_id in ('minecraft:barrel','minecraft:furnace','minecraft:oak_leaves','minecraft:birch_leaves'):
            data=fixture();m=data[0]['result']['scoped_native_preflight']['facts']['local_segment']
            row=next(c for c in m['cells'] if c['role']=='context')
            row.update(id=block_id,full_cube=True,friction=.6000000238418579)
            validate_scoped_witness(*data)
            for role in ('support','clear'):
                bad=fixture();m=bad[0]['result']['scoped_native_preflight']['facts']['local_segment']
                row=next(c for c in m['cells'] if c['role']==role)
                row.update(id=block_id,full_cube=True,friction=.6000000238418579)
                with self.subTest(block=block_id,role=role),self.assertRaises(ValueError):validate_scoped_witness(*bad)
            for key,value in (('friction',.98),('full_cube',False),('fluid','minecraft:water')):
                bad=deepcopy(data);row=next(c for c in bad[0]['result']['scoped_native_preflight']['facts']['local_segment']['cells'] if c['role']=='context')
                row[key]=value
                with self.subTest(block=block_id,key=key),self.assertRaises(ValueError):validate_scoped_witness(*bad)
        for block_id in ('minecraft:spruce_leaves','minecraft:azalea_leaves','mod:oak_leaves'):
            bad=fixture();m=bad[0]['result']['scoped_native_preflight']['facts']['local_segment']
            row=next(c for c in m['cells'] if c['role']=='context')
            row.update(id=block_id,full_cube=True,friction=.6000000238418579)
            with self.subTest(block=block_id),self.assertRaises(ValueError):validate_scoped_witness(*bad)
    def test_success_terminal_requires_exact_jump_and_profile(self):
        for dy in (-1,0,1):
            data=fixture(dy=dy);data[0]['status']='succeeded';data[0]['result'].update(input_release_confirmed=True,local_segment=terminal(data[0]))
            for key,value in (('profile','movement-step-down-observed-v1'),('phase','ground'),('input_neutral',False),('sampled_horizontal_distance',3.),('jump_pulses',2)):
                bad=deepcopy(data);bad[0]['result']['local_segment'][key]=value
                with self.subTest(dy=dy,key=key),self.assertRaises(ValueError):validate_scoped_witness(*bad)
            bad=deepcopy(data);bad[0]['result']['local_segment']['jump_pulses']=0 if dy==1 else 1
            with self.assertRaises(ValueError):validate_scoped_witness(*bad)
            del data[0]['result']['local_segment']
            with self.assertRaises(ValueError):validate_scoped_witness(*data)
    def test_size_diagnostic_profile5_is_distinct(self):
        d={'schema_version':5,'profile':PROFILE,'standalone_bytes':260000,'capability_bytes':260000,
            'response_limit':262144,'standalone_reserve_bytes':8192,'capability_reserve_bytes':24576,
            'witness_bytes':250000,'entity_frame_bytes':1000,'enumerated_count':1,'cell_count':180}
        self.assertTrue(valid_size_diagnostic(d));d['cell_count']=150;self.assertTrue(valid_size_diagnostic(d))
        for key,value in (('schema_version',4),('cell_count',179),('profile','movement-step-down-observed-v1')):
            bad={**d,key:value};self.assertFalse(valid_size_diagnostic(bad))

if __name__=='__main__':unittest.main()
