"""Diagnostic-only consumer tests; no Python terrain-equivalence or live safety claim."""
from copy import deepcopy
import json
import tempfile
import unittest
from resident_controller.capability_snapshot import validate_scoped_witness, exact
from resident_controller.route_terrain_snapshot import POLICY, REJECTION_CODES, CHANGED_FIELDS, validate_diagnostic
from resident_controller.controller import Resident, Running
from resident_controller.transport import BridgeError
from mdc_skills.core import Runtime, SkillError
from route_terrain_fixture import fixture, attach_rejection
from spatial_stop_fixture import witness, movement, terminal
from local_segment_fixture import fixture as legacy_fixture
from spatial_threat_fixture import fixture as defense_fixture
from support_core import Clock, Client, move
import test_route_spatial_stop_contract as transport_fixture


def diagnostic(data): return data[0]['result']['route_terrain_rejection']


class RouteTerrainDiagnosticTests(unittest.TestCase):
    def reject(self, data):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            validate_scoped_witness(*data)

    def test_all_three_phases_and_eight_codes_preserve_original_witness(self):
        for phase in ('capture','equivalence','raw_fence'):
            for code in REJECTION_CODES:
                data=fixture();before=deepcopy(witness(data));attached=attach_rejection(data,phase=phase,rejection_code=code)
                with self.subTest(phase=phase,code=code):
                    validate_scoped_witness(*data);self.assertTrue(exact(witness(data),before))
                    self.assertIs(attached,diagnostic(data));self.assertEqual(attached['changed_fields'],['state'])

    def test_helper_preserves_existing_terminal_and_admission_without_normalizing_states(self):
        data=fixture();native=data[0]
        native['result']['local_segment']=terminal(native);native['ticks']=42
        native['result']['local_segment']['sampled_horizontal_distance']=.75
        before=deepcopy(witness(data));existing=deepcopy(native['result']['local_segment'])
        attach_rejection(native)
        self.assertTrue(exact(witness(data),before));self.assertTrue(exact(native['result']['local_segment'],existing))
        self.assertEqual(native['ticks'],42);validate_scoped_witness(*data)

    def test_closed_top_schema_and_exact_version_policy_phase_status_reason(self):
        good=fixture();attach_rejection(good)
        for key in diagnostic(good):
            bad=deepcopy(good);del diagnostic(bad)[key]
            with self.subTest(missing=key):self.reject(bad)
        for key,value in (('schema_version',True),('schema_version',2),('profile','movement-local-segment-spatial-threat-v1'),
                ('policy','route-spatial-stop-v1'),('phase','admission'),('rejection_code','unexpected'),
                ('extra',False),('current',None),('original',None),('cell',None),('changed_fields',None)):
            bad=deepcopy(good);diagnostic(bad)[key]=value
            with self.subTest(key=key):self.reject(bad)
        for key,value in (('action','combat_entity'),('status','succeeded'),('status','running'),('status','failed'),('reason','other')):
            bad=deepcopy(good);bad[0][key]=value
            with self.subTest(native=key,value=value):self.reject(bad)

    def test_coordinates_and_original_row_are_exact_immutable_witness_reference(self):
        good=fixture();attach_rejection(good)
        for key,value in (('x',True),('y',1.5),('z',2**31),('z',-(2**31)-1),('extra',0)):
            bad=deepcopy(good);diagnostic(bad)['cell'][key]=value;self.reject(bad)
        for key in diagnostic(good)['original']:
            bad=deepcopy(good);del diagnostic(bad)['original'][key];self.reject(bad)
        for key,value in (('x',200),('state','different-original-state'),('id','minecraft:dirt'),('fluid','minecraft:water'),
                ('role','support'),('full_cube',False),('friction',.8),('friction',True),('extra',False)):
            bad=deepcopy(good);diagnostic(bad)['original'][key]=value
            with self.subTest(original=key):self.reject(bad)
        bad=deepcopy(good);diagnostic(bad)['cell']['x']=12345;diagnostic(bad)['original']['x']=12345;self.reject(bad)
        bad=deepcopy(good);diagnostic(bad)['original']['state']='bad';diagnostic(bad)['current']['state']='bad'
        diagnostic(bad)['changed_fields']=[];self.reject(bad)

    def test_original_and_current_strings_are_bounded_and_registry_keys_are_typed(self):
        good=fixture();attach_rejection(good)
        for field,values in (('id',(None,'',True,'minecraft:Bad','x'*129,'minecraft:'+'x'*120)),
                             ('state',('',True,'x'*513))):
            for value in values:
                if field=='id' and isinstance(value,str) and value.startswith('minecraft:') and len(value)<=128 and value.islower():
                    continue
                bad=deepcopy(good);diagnostic(bad)['original'][field]=value;self.reject(bad)
        for field,values in (('id',('',True,'minecraft:Bad','minecraft:'+'x'*119)),('state',('',True,'x'*513))):
            for value in values:
                bad=deepcopy(good);diagnostic(bad)['current'][field]=value
                with self.subTest(current=field,value=str(value)[:15]):self.reject(bad)
        data=fixture();attach_rejection(data,current={'id':'x:'+'a'*126,'state':'x'*512})
        validate_scoped_witness(*data)

    def test_current_schema_nullable_fields_and_types_never_infer_missing_values(self):
        good=fixture();attach_rejection(good)
        for key in diagnostic(good)['current']:
            bad=deepcopy(good);del diagnostic(bad)['current'][key];self.reject(bad)
        for key,value in (('loaded',None),('loaded',1),('role','support'),('fluid_empty',1),('full_cube','true'),
                ('collision_empty',0),('friction',True),('friction',float('inf')),('friction',float('nan')),
                ('friction',10**400),('extra',False)):
            bad=deepcopy(good);diagnostic(bad)['current'][key]=value;self.reject(bad)
        data=fixture();attach_rejection(data,phase='capture',rejection_code='local_segment_unknown_corridor_cell',
            current={'loaded':False,'id':None,'state':None,'fluid_empty':None,'full_cube':None,
                     'collision_empty':None,'friction':None})
        validate_scoped_witness(*data);self.assertEqual(diagnostic(data)['changed_fields'],['loaded'])
        data=fixture();attach_rejection(data,phase='capture',rejection_code='local_segment_special_friction',
            current={'friction':None})
        validate_scoped_witness(*data);self.assertEqual(diagnostic(data)['changed_fields'],[])

    def test_changed_fields_recomputed_all_fields_exact_order_unique_and_complete(self):
        data=fixture();attach_rejection(data,current={'loaded':False,'id':'minecraft:dirt','state':'changed',
            'fluid_empty':False,'full_cube':False,'collision_empty':True,'friction':.9})
        self.assertEqual(diagnostic(data)['changed_fields'],list(CHANGED_FIELDS));validate_scoped_witness(*data)
        for fields in ([],list(reversed(CHANGED_FIELDS)),list(CHANGED_FIELDS)+['state'],['unknown'],[True],
                       list(CHANGED_FIELDS[:-1]),tuple(CHANGED_FIELDS)):
            bad=deepcopy(data);diagnostic(bad)['changed_fields']=fields;self.reject(bad)
        bad=deepcopy(data);diagnostic(bad)['current']['friction']=None;self.reject(bad)

    def test_air_collision_and_solid_friction_baselines_come_from_admitted_row(self):
        for role in ('clear','support','context'):
            data=fixture();d=attach_rejection(data,role=role,current={})
            self.assertEqual(d['changed_fields'],[]);validate_scoped_witness(*data)
            bad=deepcopy(data);diagnostic(bad)['current']['collision_empty']=not d['current']['collision_empty']
            self.reject(bad);diagnostic(bad)['changed_fields']=['collision_empty'];validate_scoped_witness(*bad)

    def test_foreign_profiles_cannot_borrow_even_schema_correct_diagnostic(self):
        data=fixture();attach_rejection(data);d=deepcopy(diagnostic(data))
        for factory in (legacy_fixture,defense_fixture):
            bad=factory();bad[0].update(status='cancelled',reason=d['rejection_code'])
            bad[0]['result']['route_terrain_rejection']=deepcopy(d);self.reject(bad)

    def test_admission_cell_geometry_and_terminal_schema_never_relaxed_by_diagnostic(self):
        good=fixture();attach_rejection(good)
        for field,value in (('id','minecraft:spruce_leaves'),('fluid','minecraft:water'),('full_cube',False),
                ('friction',.98),('role','clear')):
            bad=deepcopy(good);row=movement(bad)['cells'][0];row[field]=value
            diagnostic(bad)['original']=deepcopy(row)
            with self.subTest(field=field):self.reject(bad)
        bad=deepcopy(good);bad[0]['result']['local_segment']['terrain_equivalent']=True;self.reject(bad)
        bad=deepcopy(good);movement(bad)['terrain_equivalent']=True;self.reject(bad)
        bad=deepcopy(good);diagnostic(bad)['equivalent']=True;self.reject(bad)

    def test_leaf_state_replacement_remains_forbidden_in_immutable_admission_poll(self):
        data=fixture();native,scope,aid,intent=data
        row=next(r for r in movement(data)['cells'] if r['role']=='context' and r['full_cube'])
        row.update(id='minecraft:oak_leaves',state='Block{minecraft:oak_leaves}[distance=7,persistent=false,waterlogged=false]')
        native['action_schema_version']=1
        task=Running({'scoped_native_preflight':scope,'action':'follow_path'},None,action_id=aid,
                     scoped_original_intent=deepcopy(intent))
        with tempfile.TemporaryDirectory() as directory:
            resident=Resident(object(),directory);resident.bridge_identity={'action_session':native['action_session']}
            resident.accept_action_status(task,native)
            bad=deepcopy(native);newrow=next(r for r in movement(bad)['cells'] if r['id']=='minecraft:oak_leaves')
            newrow['state']=newrow['state'].replace('distance=7','distance=6')
            attach_rejection(bad,cell_index=movement(bad)['cells'].index(newrow))
            with self.assertRaises(BridgeError) as failed:resident.accept_action_status(task,bad)
            self.assertTrue(failed.exception.uncertain);self.assertEqual(task.action_id,aid)
            self.assertTrue(exact(task.last_action_result,native))

    def test_motion_unknown_and_cleanup_wrapping_keep_unknown_without_mutation(self):
        for wrap in ('none','failed_reason','release'):
            data=fixture();attach_rejection(data,motion_unknown=True)
            if wrap=='failed_reason':data[0].update(status='failed',reason='outer_cleanup_failed')
            elif wrap=='release':
                data[0].update(status='failed',reason='input_release_unconfirmed')
                data[0]['result']['input_release_confirmed']=False
            validate_scoped_witness(*data)
            with tempfile.TemporaryDirectory() as directory:
                clock=Clock();client=Client(clock);runtime=Runtime(client,directory,clock=clock,sleeper=clock.sleep)
                try:
                    before=runtime.observe();record=runtime._reserve('mutation',move(),skill='terrain_diagnostic',before=before)
                    with self.assertRaises(SkillError) as failed:runtime._native_receipt(record,{'action':data[0]},before)
                    self.assertEqual(failed.exception.status,'unknown');self.assertEqual(record['status'],'unknown')
                    self.assertEqual(runtime.pending_request_id,record['request_id']);self.assertEqual(client.action_count,0)
                finally:runtime.close()

    def test_post_tick_generic_failure_keeps_diagnostic_without_changing_settlement(self):
        data=fixture();attach_rejection(data);data[0].update(status='failed',reason='client_action_error')
        before=deepcopy(data[0]);validate_scoped_witness(*data)
        self.assertTrue(exact(data[0],before));self.assertEqual(data[0]['status'],'failed')
        self.assertEqual(data[0]['reason'],'client_action_error')
        bad=deepcopy(data);bad[0]['reason']='unrelated_failure';self.reject(bad)

    def test_original_success_is_not_created_by_adding_terrain_diagnostic(self):
        data=fixture();attach_rejection(data);data[0]['status']='succeeded'
        data[0]['result']['local_segment']=terminal(data[0]);self.reject(data)
        data[0]['result']['unknown_outcome']=True;self.reject(data)

    bridge=transport_fixture.SpatialStopDiagnosticTests.bridge

    def test_original_transport_diagnostic_unchanged_and_duplicate_keys_rejected(self):
        data=fixture();attach_rejection(data)
        raw=json.dumps(data[0],separators=(',',':')).encode();bridge,calls=self.bridge([(200,raw)])
        parsed=bridge.request('GET','/control/action/status?action_id='+data[2])
        self.assertEqual(parsed,data[0]);validate_scoped_witness(parsed,*data[1:]);self.assertEqual(len(calls),1)
        bad=raw.replace(b'"phase":"equivalence"',b'"phase":"capture","phase":"equivalence"')
        self.assertNotEqual(raw,bad);bridge,calls=self.bridge([(200,bad)])
        with self.assertRaises(BridgeError):bridge.request('GET','/control/action/status?action_id='+data[2])
        self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
