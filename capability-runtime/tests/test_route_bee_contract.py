"""Deterministic v2 bee consumer checks; no live timing, AI, or physics claim."""
from copy import deepcopy
import json
import tempfile
import unittest
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.route_spatial_stop_snapshot import (PROFILE as V1_PROFILE, POLICY as V1_POLICY,
    PROFILE_V2, POLICY_V2, validate_request, valid_rejection_diagnostic, SWEPT_TYPES, FAR_TYPES)
from resident_controller.movement_wire import (decode, BINDINGS, MARKER, ENCODING, REFERENCE,
    WITNESS, TARGET as WIRE_TARGET, valid_size_diagnostic)
from resident_controller.controller import Resident, Running, action_rejection_admission
from resident_controller.transport import BridgeError
from spatial_stop_v2_fixture import (fixture, terminal, entity_row, add_row, project,
    witness, movement, guard, CLASSES, PROFILE, POLICY)
from spatial_stop_fixture import fixture as v1_fixture
from local_segment_fixture import fixture as legacy_fixture
from spatial_threat_fixture import fixture as defense_fixture
from route_terrain_fixture import attach_rejection
from mining_collect.collect.collect_fixture import redigest
import test_route_spatial_stop_contract as transport_fixture


def bee(data): return guard(data)['rows'][0]
def living(data): return bee(data)['native_living']
def route(data): return living(data)['bee_route']
def good():
    data = fixture(); add_row(data, entity_row(data)); return data

def diagnostic():
    return dict(schema_version=1, profile=PROFILE, policy=POLICY, phase='state', entity_type='minecraft:bee',
                exception_type='rejected', rejection_code='route_bee_not_calm')


class RouteBeeContractTests(unittest.TestCase):
    def reject(self, data):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            validate_scoped_witness(*data)

    def test_all_cardinal_flat_up_down_calm_bee_and_terminal(self):
        self.assertEqual((PROFILE, POLICY), (PROFILE_V2, POLICY_V2))
        for dy in (-1, 0, 1):
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                base = fixture(dy=dy); intent = deepcopy(base[3]); intent['waypoints'][0].update(x=.5+dx, z=.5+dz)
                data = fixture(intent, base[1]); add_row(data, entity_row(data))
                with self.subTest(dy=dy, dx=dx, dz=dz):
                    validate_scoped_witness(*data)
                    data[0]['status'] = 'succeeded'
                    data[0]['result'].update(input_release_confirmed=True, local_segment=terminal(data[0]))
                    validate_scoped_witness(*data)

    def test_v1_tables_and_all_existing_exact_classes_unchanged(self):
        self.assertEqual(len(SWEPT_TYPES), 8); self.assertEqual(len(FAR_TYPES), 15)
        self.assertNotIn('minecraft:bee', FAR_TYPES); self.assertNotIn('minecraft:bee', SWEPT_TYPES)
        for kind in CLASSES:
            data = fixture(); add_row(data, entity_row(data, kind))
            with self.subTest(kind=kind): validate_scoped_witness(*data)
        data = good()
        for factory in (v1_fixture, legacy_fixture, defense_fixture):
            bad = factory(); add_row(bad, deepcopy(bee(data))); self.reject(bad)
            del bee(bad)['native_living']; self.reject(bad)

    def test_unsupported_far_entities_and_modded_client_or_server_classes_refuse(self):
        for kind in ('rabbit', 'wolf', 'pufferfish', 'dolphin', 'allay', 'iron_golem', 'zombie', 'arrow', 'tnt', 'mod:bee'):
            data = good(); bee(data)['type'] = kind if ':' in kind else 'minecraft:'+kind
            with self.subTest(kind=kind): self.reject(data)
        for field in ('client', 'server'):
            data = good()
            if field == 'client': bee(data)['class'] = 'mod.Bee'
            else: route(data)['server_class'] = 'mod.Bee'
            self.reject(data)

    def test_every_living_and_bee_route_field_is_mandatory_and_closed(self):
        original = good()
        for accessor in (living, lambda d: living(d)['bee'], route):
            for key in accessor(original):
                data = deepcopy(original); del accessor(data)[key]
                with self.subTest(missing=key): self.reject(data)
            data = deepcopy(original); accessor(data)['extra'] = False; self.reject(data)
        for key in ('native_living', 'flags', 'aabb', 'position', 'projected_aabb'):
            data = good(); del bee(data)[key]; self.reject(data)
        for key in ('native_living',):
            for value in (None, [], {}, True):
                data = good(); bee(data)[key] = value; self.reject(data)
        for key in ('bee', 'bee_route'):
            for value in (None, [], {}, True):
                data = good(); living(data)[key] = value; self.reject(data)

    def test_server_coverage_truth_and_exact_row_context_identity(self):
        for key, value in (('schema_version', True), ('schema_version', 2), ('known', False), ('known', 1),
                ('source', 'client_synced'), ('reason', 'unavailable'), ('coverage_complete', False),
                ('coverage_complete', 1), ('inspected', 0), ('inspected', 4097), ('inspected', True),
                ('current_target_known', False), ('current_target_known', 1), ('entity_uuid', 'bad'),
                ('entity_id', 10), ('entity_id', True), ('entity_type', 'minecraft:cow'),
                ('world_generation', 'other'), ('dimension', 'minecraft:the_nether'), ('player_uuid', 'other')):
            data = good(); living(data)[key] = value
            with self.subTest(key=key, value=value): self.reject(data)
        data = good(); living(data)['entity_uuid'] = witness(data)['context']['player_uuid']; self.reject(data)
        data = good(); bee(data)['uuid'] = witness(data)['context']['player_uuid']; living(data)['entity_uuid'] = bee(data)['uuid']; self.reject(data)

    def test_calm_targetless_not_stung_requires_all_exact_server_facts(self):
        for key, value in (('alive', False), ('alive', 1), ('aggressive', True), ('aggressive', 0),
                           ('current_target', {}), ('current_target', {'uuid':'other','entity_id':8,'type':'minecraft:cow'})):
            data = good(); living(data)[key] = value; self.reject(data)
        for key, value in (('angry', True), ('angry', 0), ('remaining_anger_ticks', 1),
                ('remaining_anger_ticks', -1), ('remaining_anger_ticks', False), ('remaining_anger_ticks', 0.),
                ('persistent_anger_target_uuid', ''), ('persistent_anger_target_uuid', '00000000-0000-4000-8000-000000000123')):
            data = good(); living(data)['bee'][key] = value; self.reject(data)
        for key, value in (('schema_version', True), ('schema_version', 2), ('has_stung', True),
                ('has_stung', 0), ('has_nectar', 1), ('has_nectar', None)):
            data = good(); route(data)[key] = value; self.reject(data)
        data = good(); route(data).update(has_nectar=True, hive_pos={'x':2,'y':64,'z':0}, flower_pos={'x':0,'y':64,'z':0})
        validate_scoped_witness(*data)  # Destinations are facts, not paths or entity bodies.

    def test_nullable_destination_coordinates_are_closed_typed_int32(self):
        for key in ('hive_pos', 'flower_pos'):
            for pos in ({}, [], True, {'x':0,'y':1}, {'x':0,'y':1,'z':2,'extra':3},
                        {'x':True,'y':1,'z':2}, {'x':0.,'y':1,'z':2},
                        {'x':2**31,'y':1,'z':2}, {'x':-(2**31)-1,'y':1,'z':2}):
                data = good(); route(data)[key] = pos
                with self.subTest(key=key,pos=pos): self.reject(data)
            data = good(); route(data)[key] = {'x':-(2**31),'y':0,'z':2**31-1}; validate_scoped_witness(*data)

    def test_client_flags_and_server_target_cannot_be_substituted(self):
        for key, value in (('living', False), ('alive', False), ('dying', True), ('passenger', True),
                ('has_passengers', True), ('leashed', True), ('no_physics', True), ('on_fire', True),
                ('active_effect_count', 1), ('hurt_time', 1), ('mob_target_uuid', 'target')):
            data = good(); bee(data)['flags'][key] = value; self.reject(data)
        data = good(); bee(data)['flags']['angry'] = False; del bee(data)['native_living']; self.reject(data)

    def test_freshness_boundaries_bind_sample_to_frame_and_admission_end(self):
        for age in (0, 250000000):
            data = good(); facts = living(data); sample = int(witness(data)['admitted_nano'])
            facts.update(sample_nano=str(sample), source_nano=str(sample-age), sample_age_ms=age/1000000.)
            for skew in (-5, 5):
                facts['source_tick'] = facts['sample_tick']+skew
                validate_scoped_witness(*data)
        for mutation in ('expired', 'expired_at_admission', 'future_source', 'sample_before_frame', 'sample_after_admission',
                'sample_tick', 'source_tick_low', 'source_tick_high', 'source_tick_negative', 'sample_age_mismatch'):
            data = good(); facts = living(data); sample = int(facts['sample_nano'])
            if mutation == 'expired': facts['source_nano'] = str(sample-250000001)
            elif mutation == 'expired_at_admission': witness(data)['admitted_nano'] = str(int(witness(data)['source_nano'])+249000000)
            elif mutation == 'future_source': facts['source_nano'] = str(sample+1)
            elif mutation == 'sample_before_frame': facts['sample_nano'] = str(int(guard(data)['source_nano'])-1)
            elif mutation == 'sample_after_admission': facts['sample_nano'] = str(int(witness(data)['admitted_nano'])+1)
            elif mutation == 'sample_tick': facts['sample_tick'] += 1
            elif mutation == 'source_tick_low': facts['source_tick'] = facts['sample_tick']-6
            elif mutation == 'source_tick_high': facts['source_tick'] = facts['sample_tick']+6
            elif mutation == 'source_tick_negative': facts['source_tick'] = -1
            else: facts['sample_age_ms'] += .001
            if mutation != 'sample_age_mismatch': facts['sample_age_ms'] = (int(facts['sample_nano'])-int(facts['source_nano']))/1000000.
            with self.subTest(mutation=mutation): self.reject(data)

    def test_clock_types_nonfinite_signedlong_and_false_integer_tampering(self):
        for key in ('sample_tick', 'source_tick'):
            for value in (True, -1, 1., '1', None):
                data = good(); living(data)[key] = value; self.reject(data)
        for key in ('sample_nano', 'source_nano'):
            for value in (True, 1, None, '', '1.0', str(2**63), str(-(2**63)-1)):
                data = good(); living(data)[key] = value; self.reject(data)
        for value in (True, float('nan'), float('inf'), 10**400, -1):
            data = good(); living(data)['sample_age_ms'] = value; self.reject(data)

    def test_projected_current_lerp_velocity_combined_context_contacts_refuse(self):
        for contact in ('current', 'velocity', 'lerp', 'combined'):
            data = good(); row = bee(data)
            if contact == 'current': row['aabb'][2] = guard(data)['prism'][5]
            elif contact == 'velocity': row['velocity'][2] = -.06
            elif contact == 'lerp': row['lerp_target'][2] = .5
            else: row['velocity'][2] = -.025; row['lerp_target'][2] = 6.
            row['projected_aabb'] = project(row)
            with self.subTest(contact=contact): self.reject(data)
        data = good(); bee(data)['verdict'] = 'outside_swept'; self.reject(data)
        data = fixture(); add_row(data, entity_row(data,position=[.5,64.,2.5])); self.reject(data)

    def test_exact_touching_all_six_context_faces_refuses(self):
        for axis in range(3):
            for high in (False, True):
                data = good(); row = bee(data); prism = guard(data)['prism']; row['aabb'] = list(prism)
                row['position'] = [(prism[i]+prism[i+3])/2 for i in range(3)]
                row['aabb'][axis] = prism[axis+3] if high else prism[axis]-1
                row['aabb'][axis+3] = prism[axis+3]+1 if high else prism[axis]
                row['position'][axis] = (row['aabb'][axis]+row['aabb'][axis+3])/2
                row['lerp_target'] = list(row['position']); row['projected_aabb'] = project(row)
                with self.subTest(axis=axis,high=high): self.reject(data)

    def test_geometry_finite_box_contains_position_and_projection_recomputed(self):
        for key in ('position','aabb','velocity','lerp_target','projected_aabb'):
            for value in (True,float('nan'),float('inf'),10**400):
                data = good(); bee(data)[key][0] = value; self.reject(data)
            data = good(); bee(data)[key] = []; self.reject(data)
        data = good(); bee(data)['velocity'][0] = 1e308; self.reject(data)
        data = good(); bee(data)['position'][0] = 100.; self.reject(data)
        for axis in range(6):
            data = good(); bee(data)['projected_aabb'][axis] += .001; self.reject(data)

    def test_complete_ordered_unique_population_removed_rows_and_schema_binding(self):
        for mutation in ('missing', 'count', 'order', 'uuid', 'id', 'native_uuid', 'removed_extra'):
            data = good(); add_row(data, entity_row(data,entity_id=10))
            if mutation == 'missing': guard(data)['rows'].pop()
            elif mutation == 'count': guard(data)['enumerated_count'] += 1
            elif mutation == 'order': guard(data)['rows'].reverse()
            elif mutation == 'uuid': guard(data)['rows'][1]['uuid'] = bee(data)['uuid']
            elif mutation == 'id': guard(data)['rows'][1]['id'] = bee(data)['id']
            elif mutation == 'native_uuid': guard(data)['rows'][1]['native_living']['entity_uuid'] = bee(data)['uuid']
            else: bee(data)['removed'] = True
            with self.subTest(mutation=mutation): self.reject(data)
        data = fixture(); add_row(data,dict(id=9,uuid='00000000-0000-4000-8000-000000000009',type='minecraft:bee',
            **{'class':'net.minecraft.world.entity.animal.Bee'},removed=True)); validate_scoped_witness(*data)
        for key,value in (('schema_version',1),('schema_version',True),('policy',V1_POLICY),
            ('scope','all-client-loaded-route-swept-and-far-passives'),('server_confirmed',True),
            ('future_dynamics_certified',True),('remaining_projection_ticks',159),('stop_only',False)):
            data = good(); guard(data)[key] = value; self.reject(data)

    def test_no_defense_pickup_other_profile_or_terminal_authority(self):
        for key,value in (('route_threat_guard',{}),('route_stop_only',True),('pickup_target',{}),
                ('encounter_route_guard',{}),('capability_descent',True),('coordination_step',{}),
                ('capability_bridge',True),('movement_budget_bundle_id','x'),('action','combat_entity'),('capability_route',False)):
            data = good(); data[3][key] = value; redigest(data[0], data[3]); self.reject(data)
            with self.assertRaises(ValueError): validate_request(data[1], data[3])
        data = good(); data[0]['result']['route_threat_stop'] = {}; self.reject(data)
        data = good(); data[0]['status']='succeeded';data[0]['result'].update(input_release_confirmed=True,local_segment=terminal(data[0]))
        for key,value in (('profile',V1_PROFILE),('entity_guard_policy',V1_POLICY),('input_neutral',False),('extra',True)):
            bad = deepcopy(data);bad[0]['result']['local_segment'][key]=value;self.reject(bad)
        bad = deepcopy(data);bad[0]['result']['input_release_confirmed']=False;self.reject(bad)

    def test_immutable_admitted_bee_facts_cannot_be_replaced_in_poll(self):
        native,scope,aid,intent = good(); native['action_schema_version']=1
        task=Running({'scoped_native_preflight':scope,'action':'follow_path'},None,action_id=aid,scoped_original_intent=deepcopy(intent))
        with tempfile.TemporaryDirectory() as directory:
            resident=Resident(object(),directory);resident.bridge_identity={'action_session':native['action_session']}
            resident.accept_action_status(task,native)
            for mutation in ('nectar','hive','source','row','terrain'):
                bad=deepcopy(native)
                if mutation=='nectar':route(bad)['has_nectar']=True
                elif mutation=='hive':route(bad)['hive_pos']={'x':0,'y':0,'z':0}
                elif mutation=='source':living(bad)['source_nano']=str(int(living(bad)['source_nano'])-1);living(bad)['sample_age_ms']+=.000001
                elif mutation=='row':add_row(bad,entity_row(bad,'bat',entity_id=10))
                else:movement(bad)['cells'][0]['state']+='changed'
                with self.subTest(mutation=mutation),self.assertRaises(BridgeError) as failed:resident.accept_action_status(task,bad)
                self.assertTrue(failed.exception.uncertain);self.assertEqual(task.action_id,aid);self.assertEqual(task.last_action_result,native)

    def test_terrain_diagnostic_binds_exact_v2_profile_and_original_admission(self):
        data=good();before=deepcopy(witness(data));d=attach_rejection(data)
        self.assertEqual(d['profile'],PROFILE);validate_scoped_witness(*data);self.assertEqual(witness(data),before)
        d['profile']=V1_PROFILE;self.reject(data)

    def test_v2_wire_reference_and_distinct_size_schema8(self):
        data=good();w=witness(data);ref={'schema_version':1,'path':WIRE_TARGET,**{k:w[k] for k in BINDINGS}}
        bundle={MARKER:ENCODING,'action':deepcopy(data[0]),'status':{'client_action':{'result':{REFERENCE:deepcopy(ref)}}},
                'state':{'client_action':{'result':{REFERENCE:deepcopy(ref)}}}}
        semantic=decode(bundle);self.assertEqual(semantic['status']['client_action']['result'][WITNESS],w)
        for name in ('status','state'):
            bad=deepcopy(bundle);bad[name]['client_action']['result'][REFERENCE]['profile']=V1_PROFILE
            with self.assertRaises(ValueError):decode(bad)
        d=dict(schema_version=8,profile=PROFILE,standalone_bytes=260000,capability_bytes=260000,response_limit=262144,
            standalone_reserve_bytes=8192,capability_reserve_bytes=24576,witness_bytes=250000,entity_frame_bytes=1000,enumerated_count=1,cell_count=180)
        self.assertTrue(valid_size_diagnostic(d))
        for key,value in (('schema_version',7),('schema_version',True),('profile',V1_PROFILE),('cell_count',179),
                ('entity_frame_bytes',True),('standalone_reserve_bytes',24576),('capability_reserve_bytes',73728)):
            self.assertFalse(valid_size_diagnostic({**d,key:value}))


class RouteBeeTransportTests(unittest.TestCase):
    bridge=transport_fixture.SpatialStopDiagnosticTests.bridge

    def test_v2_diagnostic_requires_matching_profile_policy_code_and_request(self):
        d=diagnostic();self.assertTrue(valid_rejection_diagnostic(d))
        self.assertFalse(valid_rejection_diagnostic({**d,'profile':V1_PROFILE}))
        self.assertFalse(valid_rejection_diagnostic({**d,'profile':V1_PROFILE,'policy':V1_POLICY}))
        for scope,expected in ((fixture()[1],True),(v1_fixture()[1],False),(legacy_fixture()[1],False)):
            raw=json.dumps({'error':d['rejection_code'],'route_entity_rejection':d}).encode()
            bridge,calls=self.bridge([(409,raw)])
            with self.assertRaises(BridgeError) as caught:bridge.request('POST','/control/scoped-action',{'preflight':scope,'intent':{}})
            self.assertFalse(caught.exception.uncertain);self.assertEqual(len(calls),1)
            self.assertEqual(caught.exception.route_entity_rejection,d if expected else None)
            self.assertEqual('route_entity_rejection' in action_rejection_admission(caught.exception),expected)
        data=good();data[0]['result']['route_entity_rejection']={**d,'profile':V1_PROFILE,'policy':V1_POLICY,'rejection_code':'route_stop_entity_state_unknown'}
        with self.assertRaises(ValueError):validate_scoped_witness(*data)

    def test_v2_duplicate_bee_keys_refuse_on_submit_and_status_once(self):
        native,scope,aid,intent=good();raw=json.dumps(native,separators=(',',':')).encode()
        duplicate=raw.replace(b'"angry":false',b'"angry":true,"angry":false');self.assertNotEqual(raw,duplicate)
        for method,path,body in (('POST','/control/scoped-action',{'preflight':scope,'intent':intent}),
                ('GET','/control/action/status?action_id='+aid,None)):
            bridge,calls=self.bridge([(200,duplicate)])
            with self.subTest(method=method),self.assertRaises(BridgeError):bridge.request(method,path,body)
            self.assertEqual(len(calls),1)

    def test_5xx_calm_diagnostic_never_certifies_known_effect_or_retries(self):
        d=diagnostic();raw=json.dumps({'error':d['rejection_code'],'route_entity_rejection':d}).encode()
        bridge,calls=self.bridge([(500,raw)])
        with self.assertRaises(BridgeError) as caught:bridge.request('POST','/control/scoped-action',{'preflight':fixture()[1],'intent':{}})
        self.assertTrue(caught.exception.uncertain);self.assertEqual(len(calls),1)
        self.assertIsNone(caught.exception.route_entity_rejection)


if __name__=='__main__':unittest.main()
