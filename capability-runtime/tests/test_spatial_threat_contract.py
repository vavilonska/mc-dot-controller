"""Independent closed-wire spatial threat consumer tests. All facts are synthetic."""
from copy import deepcopy
from pathlib import Path
import os
import json
import hashlib
import tempfile
import unittest
from resident_controller.capability_snapshot import validate_scoped_witness, validate_snapshot
from resident_controller.spatial_threat_snapshot import (PROFILE, POLICY, validate_request, validate_defense_stop)
from resident_controller.movement_wire import decode, BINDINGS, MARKER, ENCODING, REFERENCE, WITNESS, TARGET as WIRE_TARGET, valid_size_diagnostic, retain, validate_retained
from resident_controller.controller import Resident, Running
from resident_controller.transport import BridgeError
from local_segment_fixture import fixture as old_fixture
from spatial_threat_fixture import fixture, terminal, threat_stop, zombie_row, project, TARGET
from mining_collect.collect.collect_fixture import redigest


def witness(data): return data[0]['result']['scoped_native_preflight']
def movement(data): return witness(data)['facts']['local_segment']
def guard(data): return movement(data)['entity_guard']

def add_row(data, row):
    frame = guard(data); frame['rows'].append(row); frame['rows'].sort(key=lambda r:(r['id'],r['uuid'],r['class']))
    frame.update(enumerated_count=len(frame['rows'])+1, removed_count=sum(r['removed'] for r in frame['rows']))
    frame['live_other_count'] = len(frame['rows']) - frame['removed_count']


def stopped(*, dy=0, preempt=False, overlap=False):
    data = fixture(dy=dy, stop_only=preempt, projected_overlap=overlap)
    if not preempt:
        native = data[0]; native.update(status='cancelled', reason='capability_threat_observed')
        native['result'].update(input_release_confirmed=True, local_segment=terminal(native, landed=False))
        native['result']['route_threat_stop'] = threat_stop(native)
    return data


class SpatialThreatContractTests(unittest.TestCase):
    def reject(self, data):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            validate_scoped_witness(*data)

    def test_all_cardinal_flat_up_down_and_known_terminal(self):
        for dy in (-1,0,1):
            for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
                base=fixture(dy=dy);intent=deepcopy(base[3]);intent['waypoints'][0].update(x=.5+dx,z=.5+dz)
                data=fixture(intent,base[1]);validate_scoped_witness(*data)
                data[0].update(status='succeeded');data[0]['result'].update(input_release_confirmed=True,local_segment=terminal(data[0]))
                validate_scoped_witness(*data)
            for preempt in (False,True):
                data=stopped(dy=dy,preempt=preempt,overlap=preempt)
                validate_scoped_witness(*data);validate_defense_stop(data[0],TARGET)

    def test_closed_profile_request_before_any_native_call(self):
        valid=fixture();validate_request(valid[1],valid[3])
        for scope,intent in ((None,valid[3]),(old_fixture()[1],valid[3]),(valid[1],old_fixture()[3])):
            with self.subTest(scope=scope),self.assertRaises(ValueError):validate_request(scope,intent)
        for key,value in (('schema_version',True),('target_uuid','NOT-A-UUID'),('extra',False)):
            data=deepcopy(valid);data[3]['route_threat_guard'][key]=value;redigest(data[0],data[3]);self.reject(data)
        for key,value in (('action','break_block'),('capability_route',False),('pickup_target',{}),('encounter_route_guard',{})):
            data=deepcopy(valid);data[3][key]=value;redigest(data[0],data[3]);self.reject(data)
        class NoReads:
            def request(self,*args,**kwargs):raise AssertionError('profile mismatch must precede every native read/write')
        with tempfile.TemporaryDirectory() as directory:
            resident=Resident(NoReads(),directory)
            with self.assertRaises(ValueError):resident.command({'op':'action',**valid[3],'scoped_native_preflight':old_fixture()[1]})

    def test_stop_only_flag_is_new_profile_exact_true_and_admitted_attacker(self):
        good=stopped(preempt=True,overlap=True)
        good[3]['route_stop_only']=True;redigest(good[0],good[3])
        validate_request(good[1],good[3]);validate_scoped_witness(*good)
        for value in (False,0,1,None,'true',[],{}):
            bad=deepcopy(good);bad[3]['route_stop_only']=value;redigest(bad[0],bad[3])
            with self.subTest(value=value),self.assertRaises(ValueError):validate_request(bad[1],bad[3])
            self.reject(bad)
        for source in (old_fixture(),fixture()):
            bad=deepcopy(source);bad[3]['route_stop_only']=True;redigest(bad[0],bad[3])
            self.reject(bad)
        # A later attacker does not satisfy the immutable stop-only admission request.
        bad=stopped();bad[3]['route_stop_only']=True;redigest(bad[0],bad[3]);self.reject(bad)
        bad=deepcopy(good);del bad[3]['route_stop_only'];self.reject(bad)
        bad=stopped(preempt=True);bad[3]['route_stop_only']=True;self.reject(bad)
        for status in ('running','succeeded'):
            bad=deepcopy(good);bad[0]['status']=status;self.reject(bad)
        class NoReads:
            def request(self,*args,**kwargs):raise AssertionError('invalid stop-only flag must precede native work')
        with tempfile.TemporaryDirectory() as directory:
            resident=Resident(NoReads(),directory)
            for source in (old_fixture(),good):
                for value in (False,None,1,'true'):
                    scope,intent=source[1],{**source[3],'route_stop_only':value}
                    with self.assertRaises(ValueError):resident.command({'op':'action',**intent,'scoped_native_preflight':scope})
            with self.assertRaises(ValueError):resident.command({'op':'action',**old_fixture()[3],
                'route_stop_only':True,'scoped_native_preflight':old_fixture()[1]})

    def test_submitted_stop_only_wrong_status_is_uncertain_with_original_id_retained(self):
        for status in ('running','succeeded'):
            data=stopped(preempt=True);native,scope,aid,intent=data
            intent['route_stop_only']=True;redigest(native,intent)
            native.update(action_schema_version=1,status=status)
            task=Running({'scoped_native_preflight':scope,'action':'follow_path'},None,action_id=aid,
                scoped_original_intent=deepcopy(intent))
            with tempfile.TemporaryDirectory() as directory:
                resident=Resident(object(),directory);resident.bridge_identity={'action_session':native['action_session']}
                with self.assertRaises(BridgeError) as failed:resident.accept_action_status(task,native)
                self.assertTrue(failed.exception.uncertain);self.assertEqual(task.action_id,aid)
                self.assertIsNone(task.last_action_result)

    def test_legacy_and_other_profiles_cannot_borrow_new_evidence(self):
        data=old_fixture();validate_scoped_witness(*data)
        data[0]['result']['route_threat_stop']=stopped()[0]['result']['route_threat_stop'];self.reject(data)
        for key in ('policy','scope','swept_aabb','selected_target_uuid','stop_only'):
            data=old_fixture();movement(data)['entity_guard'][key]=guard(fixture())[key];self.reject(data)
        for replacement in ('movement-local-segment-observed-v1','movement-step-down-observed-v1','collect-local-observed-v1','mining-local-observed-v2','placement-local-observed-v1'):
            data=fixture();data[1]['profile']=replacement;witness(data)['profile']=replacement;self.reject(data)

    def test_full_frame_and_exact_typed_metadata(self):
        good=fixture();validate_scoped_witness(*good)
        for key in list(guard(good)):
            data=deepcopy(good);del guard(data)[key]
            with self.subTest(missing=key):self.reject(data)
        for key,value in (('schema_version',True),('entity_limit',1025),('enumerated_count',True),('self_count',0),
                ('unsupported_count',1),('future_dynamics_certified',True),('server_confirmed',True),('remaining_projection_ticks',159),
                ('source_tick',99),('source_nano','999999'),('selected_target_uuid','x'),('stop_only',1),('rows',{})):
            data=deepcopy(good);guard(data)[key]=value
            with self.subTest(key=key):self.reject(data)
        for key in ('swept_aabb','prism','player_position'):
            for value in ([],[True]*len(guard(good)[key]),[float('nan')]*len(guard(good)[key])):
                data=deepcopy(good);guard(data)[key]=value;self.reject(data)
            data=deepcopy(good);guard(data)[key][0]+=.000001;self.reject(data)

    def test_passive_inside_halo_outside_swept_body_is_admitted(self):
        data=fixture();row=zombie_row(witness(data),guard(data))
        row.update(type='minecraft:cow',**{'class':'net.minecraft.world.entity.animal.Cow'});del row['native_living']
        add_row(data,row);validate_scoped_witness(*data)
        self.assertLess(row['aabb'][2],guard(data)['prism'][5])
        for key,value in (('class','mod.Cow'),('type','minecraft:bee'),('verdict','pickup_target')):
            bad=deepcopy(data);guard(bad)['rows'][0][key]=value;self.reject(bad)
        bad=deepcopy(data);guard(bad)['rows'][0]['flags']['mob_target_uuid']=TARGET;self.reject(bad)
        bad=deepcopy(data);guard(bad)['rows'][0].update(type='minecraft:rabbit',**{'class':'net.minecraft.world.entity.animal.Rabbit'});self.reject(bad)
        for axis in range(3):
            bad=deepcopy(data);guard(bad)['rows'][0]['projected_aabb'][axis]+=.001;self.reject(bad)

    def test_passive_projection_or_current_contact_refuses(self):
        data=fixture();row=zombie_row(witness(data),guard(data),overlap=True)
        row.update(type='minecraft:cow',**{'class':'net.minecraft.world.entity.animal.Cow'});del row['native_living']
        add_row(data,row);self.reject(data)
        data=fixture();row=zombie_row(witness(data),guard(data));row['aabb'][2]=guard(data)['swept_aabb'][5]
        row['projected_aabb']=project(row,160);add_row(data,row);self.reject(data)

    def test_removed_identity_only_and_complete_ordered_coverage(self):
        data=fixture();row={'id':17,'uuid':'00000000-0000-4000-8000-000000000017','type':'mod:removed','class':'mod.Removed','removed':True}
        add_row(data,row);validate_scoped_witness(*data)
        for change in ('geometry','duplicate_id','duplicate_uuid','count','order'):
            bad=deepcopy(data)
            if change=='geometry':guard(bad)['rows'][0]['position']=[0.,0.,0.]
            elif change=='count':guard(bad)['removed_count']=0
            else:
                new={**row,'id':18,'uuid':'00000000-0000-4000-8000-000000000018'}
                if change=='duplicate_id':new['id']=17
                if change=='duplicate_uuid':new['uuid']=row['uuid']
                add_row(bad,new)
                if change=='order':guard(bad)['rows'].reverse()
            with self.subTest(change=change):self.reject(bad)

    def test_selected_targetless_requires_full_fresh_known_calm_server_state(self):
        data=fixture();add_row(data,zombie_row(witness(data),guard(data)));validate_scoped_witness(*data)
        living=guard(data)['rows'][0]['native_living']
        for key in living:
            bad=deepcopy(data);del guard(bad)['rows'][0]['native_living'][key]
            with self.subTest(missing=key):self.reject(bad)
        for key,value in (('known',False),('coverage_complete',False),('source','client'),('entity_id',10),('entity_uuid','x'),
                ('entity_type','minecraft:husk'),('player_uuid','x'),('world_generation','foreign'),('dimension','minecraft:the_nether'),
                ('current_target_known',False),('aggressive',True),('alive',False),('sample_tick',101),('source_tick',94),
                ('sample_nano','250000092'),('source_nano','-250000000'),('sample_age_ms',1.),('inspected',4097),('extra',False)):
            bad=deepcopy(data);guard(bad)['rows'][0]['native_living'][key]=value
            with self.subTest(key=key):self.reject(bad)
        bad=deepcopy(data);guard(bad)['rows'][0]['native_living']['current_target']={'uuid':TARGET,'entity_id':9,'type':'minecraft:zombie'};self.reject(bad)

    def test_exact_250ms_five_tick_boundaries_and_reported_age(self):
        data=fixture();row=zombie_row(witness(data),guard(data));add_row(data,row)
        row['native_living'].update(source_tick=95,source_nano=str(int(guard(data)['source_nano'])-250000000),sample_age_ms=250.)
        validate_scoped_witness(*data)
        for key,value in (('source_tick',94),('source_nano',str(int(guard(data)['source_nano'])-250000001)),('sample_age_ms',250.000001)):
            bad=deepcopy(data);guard(bad)['rows'][0]['native_living'][key]=value;self.reject(bad)

    def test_nonselected_nearby_or_active_zombie_never_hides_behind_selected(self):
        for active,offset in ((False,2.),(False,8.),(True,20.)):
            data=fixture();add_row(data,zombie_row(witness(data),guard(data),active=active,
                uuid='00000000-0000-4000-8000-000000000018',entity_id=18,offset=offset));self.reject(data)
        data=fixture();add_row(data,zombie_row(witness(data),guard(data),uuid='00000000-0000-4000-8000-000000000018',entity_id=18,offset=8.001))
        validate_scoped_witness(*data)
        bad=stopped(preempt=True);add_row(bad,zombie_row(witness(bad),guard(bad),uuid='00000000-0000-4000-8000-000000000018',entity_id=18))
        self.reject(bad)

    def test_stop_identity_release_and_unknown_motion_are_closed(self):
        good=stopped();validate_scoped_witness(*good)
        stop=good[0]['result']['route_threat_stop']
        for key in stop:
            bad=deepcopy(good);del bad[0]['result']['route_threat_stop'][key]
            with self.subTest(missing=key):self.reject(bad)
        for key,value in (('target_uuid','00000000-0000-4000-8000-000000000019'),('entity_id',10),('entity_type','minecraft:husk'),
                ('player_uuid','x'),('before_next_effect',False),('preempted_before_motion',True),('action_tick',9),('profile','old')):
            bad=deepcopy(good);bad[0]['result']['route_threat_stop'][key]=value;self.reject(bad)
        for where in ('root','result'):
            for key in ('unknown_outcome','motion_gate_rejected','requires_handoff','input_release_unconfirmed','post_uncertain','uncertain'):
                bad=deepcopy(good);(bad[0] if where=='root' else bad[0]['result'])[key]=True;self.reject(bad)
        bad=deepcopy(good);bad[0]['result']['input_release_confirmed']=False;self.reject(bad)
        for status in ('running','succeeded','failed'):
            bad=deepcopy(good);bad[0]['status']=status;self.reject(bad)
        bad=deepcopy(good);del bad[0]['result']['local_segment'];self.reject(bad)
        with self.assertRaises(ValueError):validate_defense_stop(good[0],'00000000-0000-4000-8000-000000000019')

    def test_projection_overlap_only_zero_effect_stop_with_separate_current_body(self):
        good=stopped(preempt=True,overlap=True);validate_scoped_witness(*good)
        self.assertTrue(guard(good)['rows'][0]['projected_overlap'])
        for key,value in (('effect_attempted',True),('sampled_horizontal_distance',.01),('jump_pulses',1),('local_checks',0),('local_checks',2)):
            bad=deepcopy(good);bad[0]['result']['local_segment'][key]=value;self.reject(bad)
        bad=deepcopy(good);guard(bad)['rows'][0]['projected_overlap']=False;self.reject(bad)
        for status in ('running','succeeded'):
            bad=deepcopy(good);bad[0]['status']=status;self.reject(bad)
        bad=deepcopy(good);del bad[0]['result']['route_threat_stop'];self.reject(bad)
        bad=stopped();frame=bad[0]['result']['route_threat_stop']['entity_guard'];frame['rows']=[zombie_row(witness(bad),frame,active=True,overlap=True)]
        self.reject(bad)
        bad=stopped(preempt=True);frame=guard(bad);frame['rows']=[zombie_row(witness(bad),frame,active=True,offset=.5)]
        self.reject(bad)

    def test_original_registry_tick_and_no_motion_pose_bind_typed_stop(self):
        for preempt in (False,True):
            good=stopped(preempt=preempt);validate_scoped_witness(*good)
            for value in (1,160,True,-1,'0',None):
                bad=deepcopy(good)
                if value is None:del bad[0]['ticks']
                else:bad[0]['ticks']=value
                with self.subTest(preempt=preempt,ticks=value):self.reject(bad)
        bad=stopped(preempt=True)
        bad[0]['result']['route_threat_stop']['entity_guard']['player_position'][0]+=.01
        self.reject(bad)
        bad=stopped();bad[0]['result']['local_segment'].update(local_checks=0,entity_guard_checks=0)
        self.reject(bad)

    def test_stop_frame_is_after_admission_before_deadline(self):
        for preempt in (False,True):
            data=stopped(preempt=preempt)
            for nano in (witness(data)['source_nano'],movement(data)['deadline_nano']):
                bad=deepcopy(data);frame=bad[0]['result']['route_threat_stop']['entity_guard']
                frame['source_nano']=nano
                bad[0]['result']['local_segment']['last_entity_check_nano']=nano
                for row in frame['rows']:
                    row['native_living'].update(source_nano=nano,sample_nano=nano,sample_age_ms=0.)
                self.reject(bad)
        bad=stopped(preempt=True);frame=bad[0]['result']['route_threat_stop']['entity_guard']
        frame['source_tick']+=1;bad[0]['result']['local_segment']['last_entity_check_tick']+=1
        for row in frame['rows']:row['native_living'].update(source_tick=frame['source_tick'],sample_tick=frame['source_tick'])
        self.reject(bad)

    def test_stop_current_frame_timing_pose_and_target_are_bound(self):
        good=stopped()
        for key,value in (('source_tick',99),('source_nano','1'),('remaining_projection_ticks',160),('stop_only',False),('player_position',[10.,64.,.5])):
            bad=deepcopy(good);bad[0]['result']['route_threat_stop']['entity_guard'][key]=value;self.reject(bad)
        for key,value in (('last_entity_check_tick',999),('last_entity_check_nano','1000000000'),('last_entity_check_action_tick',9),('entity_guard_policy','observed-projection-v1'),('maximum_checked_population',1)):
            bad=deepcopy(good);bad[0]['result']['local_segment'][key]=value;self.reject(bad)
        for dy in (-1,1):
            bad=stopped(dy=dy);frame=bad[0]['result']['route_threat_stop']['entity_guard']
            frame['player_position']=[.5,63.5,.5] if dy<0 else [1.,64.,.5]
            self.reject(bad)

    def test_pre_effect_attacker_race_is_known_generic_cancel_without_handoff(self):
        data=fixture();data[0].update(status='cancelled',reason='route_spatial_pre_effect_attacker_changed')
        data[0]['result'].update(input_release_confirmed=True,local_segment=terminal(data[0],landed=False,effect_attempted=False))
        validate_scoped_witness(*data)
        self.assertNotIn('route_threat_stop',data[0]['result'])
        with self.assertRaises(ValueError):validate_defense_stop(data[0],TARGET)

    def test_resident_poll_revalidates_original_immutable_admission(self):
        data=fixture();native,scope,aid,intent=data
        native.update(action_schema_version=1)
        task=Running({'scoped_native_preflight':scope,'action':'follow_path'},None,action_id=aid,scoped_original_intent=deepcopy(intent))
        with tempfile.TemporaryDirectory() as directory:
            resident=Resident(object(),directory);resident.bridge_identity={'action_session':native['action_session']}
            resident.accept_action_status(task,native)
            tampered=deepcopy(native);tampered['result']['scoped_native_preflight']['native_owner_revision']+=1
            with self.assertRaises(BridgeError) as failed:resident.accept_action_status(task,tampered)
            self.assertTrue(failed.exception.uncertain);self.assertEqual(task.action_id,aid)
            self.assertEqual(task.last_action_result,native)

    def test_new_canonical_profile_references_and_distinct_diagnostic6(self):
        data=fixture();native=data[0];w=witness(data)
        ref={'schema_version':1,'path':WIRE_TARGET,**{k:w[k] for k in BINDINGS}}
        bundle={MARKER:ENCODING,'action':deepcopy(native),'status':{'client_action':{'result':{REFERENCE:deepcopy(ref)}}},
                'state':{'client_action':{'result':{REFERENCE:deepcopy(ref)}}}}
        semantic=decode(bundle);self.assertEqual(semantic['status']['client_action']['result'][WITNESS],w)
        self.assertIn(REFERENCE,bundle['status']['client_action']['result'])
        for name in ('status','state'):
            bad=deepcopy(bundle);bad[name]['client_action']['result'][REFERENCE]['profile']='movement-local-segment-observed-v1'
            with self.assertRaises(ValueError):decode(bad)
        d=dict(schema_version=6,profile=PROFILE,standalone_bytes=260000,capability_bytes=260000,response_limit=262144,
            standalone_reserve_bytes=40960,capability_reserve_bytes=122880,witness_bytes=250000,entity_frame_bytes=1000,enumerated_count=1,cell_count=180)
        self.assertTrue(valid_size_diagnostic(d))
        for key,value in (('schema_version',5),('profile','movement-local-segment-observed-v1'),('cell_count',179),('entity_frame_bytes',True)):
            self.assertFalse(valid_size_diagnostic({**d,key:value}))


@unittest.skipUnless(os.environ.get('MDC_SPATIAL_THREAT_NATIVE_WIRE'), 'explicit original native wire directory required')
class SpatialThreatNativeWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['MDC_SPATIAL_THREAT_NATIVE_WIRE'])
        cls.raw={kind:{name:(cls.root/kind/f'generated-{name}.json').read_bytes()
            for name in ('standalone','coherent','intent','request','size-diagnostic')}
            for kind in ('spatial-immediate','spatial-continuation')}
        cls.values={kind:{name:json.loads(value) for name,value in entries.items()} for kind,entries in cls.raw.items()}

    def test_original_java_admission_and_continuation_receipts(self):
        for kind,source in self.values.items():
            a,q,i=(deepcopy(source[n]) for n in ('standalone','request','intent'))
            with self.subTest(kind=kind):
                if kind=='spatial-immediate':self.assertIs(i.get('route_stop_only'),True)
                else:self.assertNotIn('route_stop_only',i)
                validate_scoped_witness(a,q,a['action_id'],i)
                stop=validate_defense_stop(a,i['route_threat_guard']['target_uuid'])
                self.assertEqual(stop['preempted_before_motion'],kind=='spatial-immediate')
                self.assertEqual(a['ticks'],stop['action_tick'])
                self.assertEqual(a['result']['local_segment']['local_checks'],1 if kind=='spatial-immediate' else 2)
                self.assertTrue(valid_size_diagnostic(source['size-diagnostic']))

    def test_original_coherent_raw_bytes_and_reference_binding(self):
        for kind,source in self.values.items():
            raw=self.raw[kind]['coherent'];bundle=source['coherent'];radius=bundle['state']['nearby']['radius']
            with self.subTest(kind=kind):
                semantic=validate_snapshot(bundle,radius);record=retain(raw)
                self.assertEqual(record['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(validate_retained(record,semantic,radius),semantic)
                validate_scoped_witness(semantic['action'],source['request'],semantic['action']['action_id'],source['intent'])
                bad=deepcopy(record);bad['raw_utf8']+=' '
                with self.assertRaises(ValueError):validate_retained(bad,semantic,radius)

    def test_original_native_terminal_mutations_refuse(self):
        for kind,source in self.values.items():
            for mutation in ('ticks','release','stop_identity','future_projection','current_overlap','sample_age','policy','clock','stop_only_flag'):
                a,q,i=(deepcopy(source[n]) for n in ('standalone','request','intent'))
                stop=a['result']['route_threat_stop'];frame=stop['entity_guard']
                row=next(r for r in frame['rows'] if r.get('verdict')=='selected_attacker')
                if mutation=='ticks':a['ticks']+=1
                elif mutation=='release':a['result']['input_release_confirmed']=False
                elif mutation=='stop_identity':stop['entity_id']+=1
                elif mutation=='future_projection':row['projected_overlap']=not row['projected_overlap']
                elif mutation=='current_overlap':row['aabb'][0]=frame['swept_aabb'][0]
                elif mutation=='sample_age':row['native_living']['sample_age_ms']+=.1
                elif mutation=='policy':frame['policy']='observed-projection-v1'
                elif mutation=='stop_only_flag':
                    if kind=='spatial-immediate':del i['route_stop_only']
                    else:i['route_stop_only']=True
                else:frame['source_nano']=a['result']['scoped_native_preflight']['source_nano']
                with self.subTest(kind=kind,mutation=mutation),self.assertRaises((ValueError,KeyError,TypeError)):
                    validate_scoped_witness(a,q,a['action_id'],i)


if __name__=='__main__':unittest.main()
