"""Closed DEFAULT-STOP consumer tests. Synthetic facts are not live safety evidence."""
from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import patch
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.route_spatial_stop_snapshot import (PROFILE, POLICY, validate_request,
    valid_rejection_diagnostic, SWEPT_TYPES, FAR_TYPES)
from resident_controller.movement_wire import (decode, BINDINGS, MARKER, ENCODING, REFERENCE,
    WITNESS, TARGET as WIRE_TARGET, valid_size_diagnostic)
from resident_controller.controller import Resident, Running, action_rejection_admission
from resident_controller.transport import Bridge, BridgeError
from spatial_stop_fixture import (fixture, terminal, entity_row, add_row, project, CLASSES,
    SWEPT_KINDS, FAR_KINDS, witness, movement, guard)
from local_segment_fixture import fixture as old_fixture
from spatial_threat_fixture import fixture as defense_fixture
from mining_collect.collect.collect_fixture import redigest


def diagnostic(**changes):
    return dict(schema_version=1,profile=PROFILE,policy=POLICY,phase='type',entity_type='minecraft:creeper',
                exception_type='rejected',rejection_code='route_stop_entity_unsupported',**changes)


class SpatialStopContractTests(unittest.TestCase):
    def reject(self, data):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            validate_scoped_witness(*data)

    def test_all_cardinal_flat_up_down_and_exact_terminal(self):
        for dy in (-1,0,1):
            for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
                base=fixture(dy=dy);intent=deepcopy(base[3]);intent['waypoints'][0].update(x=.5+dx,z=.5+dz)
                data=fixture(intent,base[1]);add_row(data,entity_row(data,'cow'));add_row(data,entity_row(data,'bat',entity_id=10))
                with self.subTest(dy=dy,dx=dx,dz=dz):
                    validate_scoped_witness(*data)
                    data[0].update(status='succeeded');data[0]['result'].update(input_release_confirmed=True,local_segment=terminal(data[0]))
                    validate_scoped_witness(*data)

    def test_exact_eight_near_and_fifteen_far_types_without_importing_consumer_policy(self):
        self.assertEqual(len(SWEPT_TYPES),8);self.assertEqual(len(FAR_TYPES),15)
        self.assertEqual(set(SWEPT_TYPES),{'minecraft:'+k for k in SWEPT_KINDS})
        self.assertEqual(set(FAR_TYPES),{'minecraft:'+k for k in FAR_KINDS})
        for kind in CLASSES:
            data=fixture();add_row(data,entity_row(data,kind))
            with self.subTest(kind=kind): validate_scoped_witness(*data)
            for key,value in (('class','modded.'+CLASSES[kind]),('verdict','outside'),('native_living',{})):
                bad=deepcopy(data);guard(bad)['rows'][0][key]=value;self.reject(bad)

    def test_unknown_hostile_projectile_explosive_and_unaudited_far_never_ignored(self):
        kinds=('rabbit','wolf','bee','pufferfish','dolphin','axolotl','snow_golem','iron_golem','allay','armor_stand',
            'zombie','creeper','skeleton','arrow','fireball','tnt','tnt_minecart','end_crystal','mod:harmless')
        for kind in kinds:
            data=fixture();row=entity_row(data,'bat',position=[1e6,64.,1e6])
            row['type']=kind if ':' in kind else 'minecraft:'+kind
            row['class']='net.minecraft.world.entity.'+kind
            add_row(data,row)
            with self.subTest(kind=kind):self.reject(data)
        data=fixture();add_row(data,entity_row(data,'bat'));guard(data)['rows'][0]['type']='minecraft:player';self.reject(data)

    def test_nearpassive_halo_is_allowed_only_outside_swept_body(self):
        data=fixture();row=add_row(data,entity_row(data,'cow'))
        self.assertLess(row['aabb'][2],guard(data)['prism'][5]);validate_scoped_witness(*data)
        for contact in ('current','velocity','lerp','combined'):
            bad=deepcopy(data);row=guard(bad)['rows'][0]
            if contact=='current':
                row['aabb'][2]=guard(bad)['swept_aabb'][5]
            elif contact=='velocity':row['velocity'][2]=-.02
            elif contact=='lerp':row['lerp_target'][2]=.5
            else:row['velocity'][2]=-.005;row['lerp_target'][2]=1.8
            row['projected_aabb']=project(row)
            with self.subTest(contact=contact):self.reject(bad)

    def test_farpassive_requires_full_context_exclusion_current_motion_and_lerp(self):
        for kind in FAR_KINDS:
            data=fixture();row=entity_row(data,kind,position=[.5,64.,2.5]);add_row(data,row)
            with self.subTest(kind=kind):self.reject(data)
        for contact in ('current','velocity','lerp','combined'):
            data=fixture();row=add_row(data,entity_row(data,'bat'))
            if contact=='current':row['aabb'][2]=guard(data)['prism'][5]
            elif contact=='velocity':row['velocity'][2]=-.06
            elif contact=='lerp':row['lerp_target'][2]=.5
            else:row['velocity'][2]=-.025;row['lerp_target'][2]=6.
            row['projected_aabb']=project(row)
            with self.subTest(contact=contact):self.reject(data)

    def test_touching_all_exclusion_faces_is_conflict_not_center_distance(self):
        for kind in ('cow','bat'):
            for axis in range(3):
                for high in (False,True):
                    data=fixture();row=entity_row(data,kind,position=[.5,64.5,.5])
                    exclusion=guard(data)['prism' if kind=='bat' else 'swept_aabb']
                    # A box touching one face while intersecting the other axes.
                    row['aabb']=list(exclusion)
                    for i in range(3):
                        row['position'][i]=(exclusion[i]+exclusion[i+3])/2
                    if high:
                        row['aabb'][axis]=exclusion[axis+3]
                        row['aabb'][axis+3]=exclusion[axis+3]+1
                        row['position'][axis]=exclusion[axis+3]+.5
                    else:
                        row['aabb'][axis]=exclusion[axis]-1
                        row['aabb'][axis+3]=exclusion[axis]
                        row['position'][axis]=exclusion[axis]-.5
                    row['lerp_target']=list(row['position']);row['projected_aabb']=project(row);add_row(data,row)
                    with self.subTest(kind=kind,axis=axis,high=high):self.reject(data)

    def test_frame_schema_each_missing_field_extra_and_typed_counts(self):
        good=fixture();add_row(good,entity_row(good,'bat'))
        for key in guard(good):
            bad=deepcopy(good);del guard(bad)[key]
            with self.subTest(missing=key):self.reject(bad)
        for key,value in (('schema_version',True),('policy','observed-projection-v1'),('scope','radius'),
                ('future_dynamics_certified',True),('server_confirmed',True),('entity_limit',1025),
                ('enumerated_count',True),('self_count',0),('live_other_count',0),('removed_count',1),
                ('unsupported_count',1),('maximum_action_ticks',159),('remaining_projection_ticks',159),
                ('source_tick',99),('source_nano','-99'),('rows',{}),('selected_target_uuid','x'),('stop_only',False)):
            bad=deepcopy(good);guard(bad)[key]=value
            with self.subTest(key=key):self.reject(bad)
        for key in ('prism','swept_aabb'):
            for value in ([True]*6,[float('nan')]*6,[],[0.]*6):
                bad=deepcopy(good);guard(bad)[key]=value;self.reject(bad)

    def test_row_closed_schema_identity_and_boolean_types(self):
        good=fixture();add_row(good,entity_row(good,'bat'))
        for key in guard(good)['rows'][0]:
            bad=deepcopy(good);del guard(bad)['rows'][0][key]
            with self.subTest(missing=key):self.reject(bad)
        for key,value in (('id',True),('id',2**31),('uuid','invalid'),('uuid',witness(good)['context']['player_uuid']),
                ('removed',1),('type',''),('class',''),('distance',99999),('verdict','outside_swept')):
            bad=deepcopy(good);guard(bad)['rows'][0][key]=value
            with self.subTest(key=key):self.reject(bad)
        for key in guard(good)['rows'][0]['flags']:
            bad=deepcopy(good);del guard(bad)['rows'][0]['flags'][key];self.reject(bad)
        for key,value in (('living',False),('alive',False),('dying',True),('passenger',True),('has_passengers',True),
                ('leashed',True),('no_physics',True),('on_fire',True),('hurt_time',1),('hurt_time',False),
                ('active_effect_count',1),('mob_target_uuid','target'),('extra',False)):
            bad=deepcopy(good);guard(bad)['rows'][0]['flags'][key]=value
            with self.subTest(flag=key):self.reject(bad)

    def test_finite_geometry_and_binary64_projection_are_recomputed(self):
        good=fixture();add_row(good,entity_row(good,'bat'))
        for key in ('position','velocity','lerp_target','aabb','projected_aabb'):
            for value in (float('inf'),float('nan'),True,10**400):
                bad=deepcopy(good);guard(bad)['rows'][0][key][0]=value
                with self.subTest(key=key,value=str(value)[:12]):self.reject(bad)
        for key in ('position','velocity','lerp_target','aabb','projected_aabb'):
            bad=deepcopy(good);guard(bad)['rows'][0][key]=[];self.reject(bad)
        bad=deepcopy(good);guard(bad)['rows'][0]['velocity'][0]=1e308;self.reject(bad)
        bad=deepcopy(good);guard(bad)['rows'][0]['position'][0]=100.;self.reject(bad)
        bad=deepcopy(good);guard(bad)['rows'][0]['aabb'][3]=guard(bad)['rows'][0]['aabb'][0];self.reject(bad)
        for axis in range(6):
            bad=deepcopy(good);guard(bad)['rows'][0]['projected_aabb'][axis]+=.001;self.reject(bad)

    def test_removed_identity_only_full_ordered_unique_coverage(self):
        good=fixture();add_row(good,dict(id=9,uuid='00000000-0000-4000-8000-000000000009',
            type='mod:removed',**{'class':'mod.Removed'},removed=True));validate_scoped_witness(*good)
        for mutation in ('extra','count','duplicate_id','duplicate_uuid','order'):
            bad=deepcopy(good)
            if mutation=='extra':guard(bad)['rows'][0]['position']=[0.,0.,0.]
            elif mutation=='count':guard(bad)['removed_count']=0
            else:
                row=entity_row(bad,'bat',entity_id=10)
                if mutation=='duplicate_id':row['id']=9
                if mutation=='duplicate_uuid':row['uuid']=guard(bad)['rows'][0]['uuid']
                add_row(bad,row)
                if mutation=='order':guard(bad)['rows'].reverse()
            with self.subTest(mutation=mutation):self.reject(bad)

    def test_world_player_owner_session_intent_and_navigation_stay_bound(self):
        good=fixture();validate_scoped_witness(*good)
        for key,value in (('world_generation','other'),('dimension','minecraft:the_nether'),('player_uuid','other'),('action_session','other')):
            bad=deepcopy(good);witness(bad)['context'][key]=value;self.reject(bad)
        for key,value in (('owner_id','0'*32),('owner_generation',2),('defense_epoch',1),('job_id','other')):
            bad=deepcopy(good);witness(bad)[key]=value;self.reject(bad)
        for key,value in (('expected_navigation_epoch',999),('timeout_ms',1000),('action_id','other')):
            bad=deepcopy(good);bad[3][key]=value;self.reject(bad)

    def test_default_profile_cannot_borrow_defense_or_other_profile_evidence(self):
        good=fixture()
        for source in (old_fixture(),defense_fixture()):
            bad=deepcopy(good);movement(bad)['entity_guard']=deepcopy(movement(source)['entity_guard']);self.reject(bad)
            bad=source;movement(bad)['entity_guard']=deepcopy(guard(good));self.reject(bad)
        for key,value in (('route_threat_guard',{}),('route_stop_only',True),('pickup_target',{}),
                ('encounter_route_guard',{}),('capability_descent',True),('coordination_step',{}),
                ('capability_bridge',True),('movement_budget_bundle_id','x'),('action','combat_entity'),('capability_route',False)):
            bad=deepcopy(good);bad[3][key]=value;redigest(bad[0],bad[3]);self.reject(bad)
            with self.assertRaises(ValueError):validate_request(bad[1],bad[3])
        for key,value in (('route_threat_stop',{}),):
            bad=deepcopy(good);bad[0]['result'][key]=value;self.reject(bad)
        bad=deepcopy(good);bad[0]['reason']='capability_threat_observed';self.reject(bad)

    def test_invalid_request_rejected_before_native_read_or_write(self):
        class NoCalls:
            def request(self,*args,**kwargs):raise AssertionError('invalid request must precede native work')
        with tempfile.TemporaryDirectory() as directory:
            resident=Resident(NoCalls(),directory)
            for key,value in (('action','combat_entity'),('capability_route',False),('pickup_target',{}),('route_stop_only',True)):
                data=fixture();intent={**data[3],key:value}
                with self.assertRaises(ValueError):resident.command({'op':'action',**intent,'scoped_native_preflight':data[1]})

    def test_terminal_profile_policy_success_release_and_schema_are_closed(self):
        good=fixture();good[0].update(status='succeeded');good[0]['result'].update(input_release_confirmed=True,local_segment=terminal(good[0]))
        validate_scoped_witness(*good)
        for key,value in (('profile','movement-local-segment-observed-v1'),('entity_guard_policy','route-spatial-threat-v1'),
                ('input_neutral',False),('velocity_stopped_proven',True),('sampled_horizontal_distance',3.),
                ('local_checks',True),('jump_pulses',1),('extra',False)):
            bad=deepcopy(good);bad[0]['result']['local_segment'][key]=value;self.reject(bad)
        bad=deepcopy(good);bad[0]['result']['input_release_confirmed']=False;self.reject(bad)
        bad=deepcopy(good);del bad[0]['result']['local_segment'];self.reject(bad)

    def test_resident_poll_preserves_immutable_admission_and_original_action_id(self):
        data=fixture();native,scope,aid,intent=data;native.update(action_schema_version=1)
        task=Running({'scoped_native_preflight':scope,'action':'follow_path'},None,action_id=aid,scoped_original_intent=deepcopy(intent))
        with tempfile.TemporaryDirectory() as directory:
            resident=Resident(object(),directory);resident.bridge_identity={'action_session':native['action_session']}
            resident.accept_action_status(task,native)
            for mutation in ('owner','entity','terminal'):
                bad=deepcopy(native)
                if mutation=='owner':bad['result']['scoped_native_preflight']['native_owner_revision']+=1
                elif mutation=='entity':add_row(bad,entity_row(bad,'bat'))
                else:bad['result']['local_segment']={}
                with self.subTest(mutation=mutation),self.assertRaises(BridgeError) as failed:resident.accept_action_status(task,bad)
                self.assertTrue(failed.exception.uncertain);self.assertEqual(task.action_id,aid);self.assertEqual(task.last_action_result,native)

    def test_wire_profile_binding_and_distinct_schema7_diagnostic(self):
        data=fixture();w=witness(data)
        ref={'schema_version':1,'path':WIRE_TARGET,**{k:w[k] for k in BINDINGS}}
        bundle={MARKER:ENCODING,'action':deepcopy(data[0]),'status':{'client_action':{'result':{REFERENCE:deepcopy(ref)}}},
                'state':{'client_action':{'result':{REFERENCE:deepcopy(ref)}}}}
        semantic=decode(bundle);self.assertEqual(semantic['status']['client_action']['result'][WITNESS],w)
        self.assertIn(REFERENCE,bundle['status']['client_action']['result'])
        for name in ('status','state'):
            bad=deepcopy(bundle);bad[name]['client_action']['result'][REFERENCE]['profile']='movement-local-segment-spatial-threat-v1'
            with self.assertRaises(ValueError):decode(bad)
        d=dict(schema_version=7,profile=PROFILE,standalone_bytes=260000,capability_bytes=260000,response_limit=262144,
            standalone_reserve_bytes=8192,capability_reserve_bytes=24576,witness_bytes=250000,entity_frame_bytes=1000,enumerated_count=1,cell_count=180)
        self.assertTrue(valid_size_diagnostic(d))
        for key,value in (('schema_version',6),('profile','movement-local-segment-spatial-threat-v1'),('cell_count',179),
                ('entity_frame_bytes',True),('standalone_reserve_bytes',24576),('capability_reserve_bytes',73728)):
            self.assertFalse(valid_size_diagnostic({**d,key:value}))


class SpatialStopDiagnosticTests(unittest.TestCase):
    def bridge(self, responses):
        queue=list(responses)
        class Response:
            def __init__(self,status,raw):self.status,self.raw=status,raw
            def read(self,bound):return self.raw[:bound]
            def getheader(self,name):return None
        class Connection:
            calls=[]
            def __init__(self,*args,**kwargs):pass
            def request(self,*args,**kwargs):self.calls.append((args,kwargs))
            def getresponse(self):return Response(*queue.pop(0))
            def close(self):pass
        mock=patch('resident_controller.transport.http.client.HTTPConnection',Connection);mock.start();self.addCleanup(mock.stop)
        return Bridge('http://127.0.0.1:12345','synthetic-offline-test-token'),Connection.calls

    def test_closed_bounded_diagnostic_and_malformed_values(self):
        good=diagnostic();self.assertTrue(valid_rejection_diagnostic(good))
        for key in good:
            bad=deepcopy(good);del bad[key];self.assertFalse(valid_rejection_diagnostic(bad))
        for key,value in (('schema_version',True),('profile','movement-local-segment-spatial-threat-v1'),('policy','old'),
                ('phase','future'),('entity_type','x'*129),('entity_type','minecraft:Type'),('entity_type','secret text'),
                ('exception_type','error message'),('rejection_code','arbitrary_error'),('class','private.Foo')):
            self.assertFalse(valid_rejection_diagnostic({**good,key:value}))
        self.assertTrue(valid_rejection_diagnostic({**good,'entity_type':'type_unavailable'}))

    def test_actual_transport_preserves_rejecting_type_under_original_error_once(self):
        good=diagnostic();raw=json.dumps({'error':good['rejection_code'],'route_entity_rejection':good}).encode()
        bridge,calls=self.bridge([(409,raw)]);data=fixture()
        with self.assertRaises(BridgeError) as caught:bridge.request('POST','/control/scoped-action',{'preflight':data[1],'intent':data[3]})
        exc=caught.exception;self.assertFalse(exc.uncertain);self.assertEqual(exc.route_entity_rejection,good)
        self.assertEqual(action_rejection_admission(exc)['route_entity_rejection'],good);self.assertEqual(len(calls),1)

    def test_foreign_profile_wrong_error_and_malformed_diagnostics_cannot_cross_boundary(self):
        good=diagnostic()
        for scope,bad,code in ((old_fixture()[1],good,good['rejection_code']),
                (fixture()[1],{**good,'extra':False},good['rejection_code']),
                (fixture()[1],good,'some_other_error')):
            raw=json.dumps({'error':code,'route_entity_rejection':bad}).encode();bridge,calls=self.bridge([(409,raw)])
            with self.assertRaises(BridgeError) as caught:bridge.request('POST','/control/scoped-action',{'preflight':scope,'intent':{}})
            self.assertIsNone(caught.exception.route_entity_rejection)
            self.assertNotIn('route_entity_rejection',action_rejection_admission(caught.exception));self.assertEqual(len(calls),1)

    def test_5xx_diagnostic_never_converts_unknown_to_known(self):
        good=diagnostic();raw=json.dumps({'error':good['rejection_code'],'route_entity_rejection':good}).encode()
        bridge,calls=self.bridge([(500,raw)])
        with self.assertRaises(BridgeError) as caught:bridge.request('POST','/control/scoped-action',{'preflight':fixture()[1],'intent':{}})
        self.assertTrue(caught.exception.uncertain);self.assertEqual(len(calls),1)

    def test_new_profile_submit_and_status_reject_duplicate_original_json_keys(self):
        native,scope,aid,intent=fixture()
        raw=json.dumps(native,separators=(',',':')).encode()
        duplicate=raw.replace(b'"remaining_projection_ticks":160',b'"remaining_projection_ticks":159,"remaining_projection_ticks":160')
        self.assertNotEqual(raw,duplicate)
        for method,path,body in (('POST','/control/scoped-action',{'preflight':scope,'intent':intent}),
                ('GET','/control/action/status?action_id='+aid,None)):
            bridge,calls=self.bridge([(200,duplicate)])
            with self.subTest(method=method),self.assertRaises(BridgeError):bridge.request(method,path,body)
            self.assertEqual(len(calls),1)

    def test_terminal_diagnostic_is_exact_non_authority_and_defense_cannot_borrow(self):
        data=fixture();data[0]['result']['route_entity_rejection']=diagnostic();validate_scoped_witness(*data)
        data[0]['result']['route_entity_rejection']['extra']=False
        with self.assertRaises(ValueError):validate_scoped_witness(*data)
        data=defense_fixture();data[0]['result']['route_entity_rejection']=diagnostic()
        with self.assertRaises(ValueError):validate_scoped_witness(*data)


if __name__=='__main__':unittest.main()
