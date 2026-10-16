"""Consume unchanged Java v2 serializer bytes from an explicit producer directory.

Allocation-only engine fixtures and synthetic callbacks do not establish live
Minecraft loader, timing, ordinary-world, or physics acceptance. No game starts.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from mdc_skills.core import Runtime, SkillError
from resident_controller.capability_snapshot import validate_scoped_witness, validate_snapshot, exact
from resident_controller.movement_wire import retain, validate_retained, valid_size_diagnostic
from resident_controller.route_spatial_stop_snapshot import PROFILE_V2 as PROFILE, POLICY_V2 as POLICY, valid_rejection_diagnostic
from resident_controller.route_terrain_snapshot import validate_diagnostic as validate_terrain_diagnostic
from resident_controller.controller import action_rejection_admission
from resident_controller.transport import BridgeError
from support_core import Clock, Client, move
import test_route_spatial_stop_contract as transport_fixture


@unittest.skipUnless(os.environ.get('MDC_ROUTE_BEE_NATIVE_WIRE') and os.environ.get('MDC_ROUTE_BEE_ENGINE_EVIDENCE'),
                     'explicit original native wire and engine directories required')
class RouteBeeNativeWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['MDC_ROUTE_BEE_NATIVE_WIRE'])
        cls.engine = Path(os.environ['MDC_ROUTE_BEE_ENGINE_EVIDENCE'])
        cls.cases = ('route-bee-success','route-bee-rejection','route-bee-motion','route-bee-terrain')
        cls.raw = {kind:{name:(cls.root/kind/f'generated-{name}.json').read_bytes()
            for name in ('standalone','coherent','intent','request','size-diagnostic')} for kind in cls.cases}
        cls.values = {kind:{name:json.loads(raw) for name,raw in entries.items()} for kind,entries in cls.raw.items()}

    def data(self, kind):
        a,q,i = (deepcopy(self.values[kind][name]) for name in ('standalone','request','intent'))
        return a,q,a['action_id'],i

    def test_all_original_admission_rows_are_exact_engine_producer_output(self):
        for kind in self.cases:
            data=self.data(kind);w=validate_scoped_witness(*data)
            engine=json.loads((self.engine/kind/'actual-footprint.json').read_bytes())
            with self.subTest(kind=kind):
                self.assertEqual(w['profile'],PROFILE)
                self.assertTrue(exact(w['facts']['local_segment'],engine))
                self.assertEqual(w['facts']['local_segment']['entity_guard']['schema_version'],2)
                self.assertEqual(w['facts']['local_segment']['entity_guard']['policy'],POLICY)
                self.assertNotIn('route_threat_guard',data[3]);self.assertNotIn('route_stop_only',data[3])
                self.assertNotIn('route_threat_stop',data[0]['result'])
                self.assertEqual(json.loads(self.raw[kind]['standalone']),self.values[kind]['standalone'])

    def test_success_retains_authoritative_calm_unstung_bee_and_independent_geometry(self):
        data=self.data('route-bee-success');w=validate_scoped_witness(*data);native=data[0]
        self.assertEqual(native['status'],'succeeded');self.assertTrue(native['result']['input_release_confirmed'])
        frame=w['facts']['local_segment']['entity_guard']
        bees=[r for r in frame['rows'] if r['type']=='minecraft:bee' and not r['removed']]
        self.assertTrue(bees)
        for row in bees:
            facts=row['native_living'];self.assertEqual(row['class'],'net.minecraft.world.entity.animal.Bee')
            self.assertEqual(facts['bee_route']['server_class'],row['class'])
            self.assertTrue(facts['known']);self.assertTrue(facts['coverage_complete'])
            self.assertEqual(facts['source'],'integrated_server_tick');self.assertIsNone(facts['current_target'])
            self.assertFalse(facts['aggressive']);self.assertFalse(facts['bee_route']['has_stung'])
            self.assertEqual(facts['bee'],dict(angry=False,remaining_anger_ticks=0,persistent_anger_target_uuid=None))
            self.assertEqual((facts['entity_uuid'],facts['entity_id'],facts['entity_type']),
                             (row['uuid'],row['id'],row['type']))
            self.assertLessEqual(int(w['admitted_nano'])-int(facts['source_nano']),250000000)
            projected=[0.]*6
            for i in range(3):
                lerp=float(row['lerp_target'][i])-float(row['position'][i]);motion=160*float(row['velocity'][i])
                lo=float(row['aabb'][i]);hi=float(row['aabb'][i+3])
                projected[i]=min(lo,lo+lerp,lo+motion,(lo+lerp)+motion)
                projected[i+3]=max(hi,hi+lerp,hi+motion,(hi+lerp)+motion)
            self.assertEqual(row['projected_aabb'],projected)
            self.assertTrue(any(projected[i+3]<frame['prism'][i] or projected[i]>frame['prism'][i+3] for i in range(3)))
            self.assertEqual(row['verdict'],'outside_context')

    def test_original_continuation_anger_refusal_and_unknown_hook_remain_distinct(self):
        for kind,unknown in (('route-bee-rejection',False),('route-bee-motion',True)):
            data=self.data(kind);validate_scoped_witness(*data);native=data[0]
            with self.subTest(kind=kind):
                self.assertEqual(native['status'],'cancelled')
                d=native['result']['route_entity_rejection'];self.assertTrue(valid_rejection_diagnostic(d))
                self.assertEqual(d['profile'],PROFILE);self.assertEqual(d['entity_type'],'minecraft:bee')
                self.assertEqual(native['reason'],d['rejection_code'])
                self.assertEqual(native['result'].get('unknown_outcome') is True,unknown)
                if unknown:self.assertTrue(native['result']['motion_gate_rejected'])
                admitted=native['result']['scoped_native_preflight']['facts']['local_segment']['entity_guard']
                self.assertTrue(all(not r['native_living']['bee']['angry'] for r in admitted['rows'] if r['type']=='minecraft:bee'))

    def test_original_v2_terrain_diagnostic_keeps_immutable_admission_cells(self):
        data=self.data('route-bee-terrain');w=validate_scoped_witness(*data);native=data[0]
        d=native['result']['route_terrain_rejection']
        self.assertEqual(d['profile'],PROFILE)
        self.assertIs(validate_terrain_diagnostic(d,w,native),d)
        self.assertIn(d['original'],w['facts']['local_segment']['cells'])
        self.assertNotEqual(native['status'],'succeeded')
        bad=deepcopy(data);bad[0]['result']['route_terrain_rejection']['profile']='movement-local-segment-spatial-stop-v1'
        with self.assertRaises(ValueError):validate_scoped_witness(*bad)

    def test_original_coherent_utf8_hash_provenance_and_complete_sibling_equality(self):
        for kind in self.cases:
            source=self.values[kind];raw=self.raw[kind]['coherent'];bundle=source['coherent'];radius=bundle['state']['nearby']['radius']
            with self.subTest(kind=kind):
                semantic=validate_snapshot(bundle,radius);record=retain(raw)
                self.assertEqual(record['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(record['raw_utf8'].encode('utf-8'),raw)
                self.assertTrue(exact(validate_retained(record,semantic,radius),semantic))
                validate_scoped_witness(semantic['action'],source['request'],semantic['action']['action_id'],source['intent'])
                for name in ('status','state'):
                    self.assertTrue(exact(semantic[name]['client_action']['result'],semantic['action']['result']))
                    bad=deepcopy(bundle);bad[name]['client_action']['result']['scoped_native_preflight_ref']['profile']='movement-local-segment-spatial-stop-v1'
                    with self.assertRaises(ValueError):validate_snapshot(bad,radius)
                bad=deepcopy(record);bad['raw_utf8']+=' '
                with self.assertRaises(ValueError):validate_retained(bad,semantic,radius)

    def test_original_bee_schema_context_identity_clock_state_and_collision_tampering_refuse(self):
        for mutation in ('missing_living','server_class','coverage','uuid','entity_id','context','sample_tick','sample_nano',
                'expired','age','angry','anger_time','persistent_target','target','stung','missing_hive','extra_route',
                'current_contact','projected_contact','projection','verdict','policy','frame_version'):
            data=self.data('route-bee-success');w=data[0]['result']['scoped_native_preflight'];frame=w['facts']['local_segment']['entity_guard']
            row=next(r for r in frame['rows'] if r['type']=='minecraft:bee');facts=row['native_living']
            if mutation=='missing_living':del row['native_living']
            elif mutation=='server_class':facts['bee_route']['server_class']='mod.Bee'
            elif mutation=='coverage':facts['coverage_complete']=False
            elif mutation=='uuid':facts['entity_uuid']='00000000-0000-4000-8000-000000000999'
            elif mutation=='entity_id':facts['entity_id']+=1
            elif mutation=='context':facts['world_generation']='other'
            elif mutation=='sample_tick':facts['sample_tick']+=1
            elif mutation=='sample_nano':facts['sample_nano']=str(int(w['admitted_nano'])+1)
            elif mutation=='expired':facts['source_nano']=str(int(facts['sample_nano'])-250000001);facts['sample_age_ms']=250.000001
            elif mutation=='age':facts['sample_age_ms']+=.001
            elif mutation=='angry':facts['bee']['angry']=True
            elif mutation=='anger_time':facts['bee']['remaining_anger_ticks']=1
            elif mutation=='persistent_target':facts['bee']['persistent_anger_target_uuid']=w['context']['player_uuid']
            elif mutation=='target':facts['current_target']={'uuid':w['context']['player_uuid'],'entity_id':1,'type':'minecraft:player'}
            elif mutation=='stung':facts['bee_route']['has_stung']=True
            elif mutation=='missing_hive':del facts['bee_route']['hive_pos']
            elif mutation=='extra_route':facts['bee_route']['calm']=True
            elif mutation=='current_contact':row['position']=[.5,64.,.5];row['aabb']=[.2,64.,.2,.8,65.,.8]
            elif mutation=='projected_contact':row['lerp_target']=[.5,64.,.5]
            elif mutation=='projection':row['projected_aabb'][0]+=.001
            elif mutation=='verdict':row['verdict']='outside_swept'
            elif mutation=='policy':frame['policy']='route-spatial-stop-v1'
            else:frame['schema_version']=1
            with self.subTest(mutation=mutation),self.assertRaises((ValueError,KeyError,TypeError)):validate_scoped_witness(*data)
        self.assertEqual(json.loads(self.raw['route-bee-success']['standalone']),self.values['route-bee-success']['standalone'])

    def test_original_wire_size_schema8_reserves_and_profile_are_exact(self):
        for kind in self.cases:
            d=self.values[kind]['size-diagnostic']
            with self.subTest(kind=kind):
                self.assertTrue(valid_size_diagnostic(d));self.assertEqual(d['schema_version'],8)
                self.assertEqual(d['profile'],PROFILE);self.assertEqual(d['standalone_reserve_bytes'],8192)
                self.assertEqual(d['capability_reserve_bytes'],24576)
                self.assertFalse(valid_size_diagnostic({**d,'schema_version':7}))

    def test_original_unknown_motion_latches_before_rebinding_without_replay(self):
        raw=self.raw['route-bee-motion']['standalone'];native=json.loads(raw)
        self.assertTrue(native['result']['unknown_outcome']);self.assertTrue(native['result']['motion_gate_rejected'])
        with tempfile.TemporaryDirectory() as directory:
            clock=Clock();client=Client(clock);runtime=Runtime(client,directory,clock=clock,sleeper=clock.sleep)
            try:
                before=runtime.observe();record=runtime._reserve('mutation',move(),skill='native_route_bee_consumer',before=before)
                with self.assertRaises(SkillError) as failure:runtime._native_receipt(record,{'action':native},before)
                self.assertEqual(failure.exception.status,'unknown')
                self.assertEqual(failure.exception.reason,'native_receipt_requires_handoff_or_is_uncertain')
                self.assertEqual(record['status'],'unknown');self.assertEqual(runtime.pending_request_id,record['request_id'])
                self.assertEqual(client.action_count,0);runtime.close()
                self.assertEqual(runtime.pending_request_id,record['request_id']);self.assertEqual(client.action_count,0)
                self.assertEqual(json.loads(raw),native)
            finally:runtime.close()

    bridge=transport_fixture.SpatialStopDiagnosticTests.bridge

    def test_original_bee_admission_refusal_survives_transport_once(self):
        raw=(self.engine/'bee-admission-rejection.json').read_bytes();original=json.loads(raw)
        self.assertEqual(original['route_entity_rejection']['entity_type'],'minecraft:bee')
        self.assertEqual(original['route_entity_rejection']['profile'],PROFILE)
        bridge,calls=self.bridge([(409,raw)])
        with self.assertRaises(BridgeError) as caught:bridge.request('POST','/control/scoped-action',{'preflight':{'profile':PROFILE},'intent':{}})
        self.assertFalse(caught.exception.uncertain);self.assertEqual(caught.exception.code,original['error'])
        admission=action_rejection_admission(caught.exception)
        self.assertFalse(admission['admitted']);self.assertEqual(admission['route_entity_rejection'],original['route_entity_rejection'])
        self.assertEqual(len(calls),1)

    def test_original_status_preserves_complete_bytes_without_extra_request(self):
        for kind in self.cases:
            raw=self.raw[kind]['standalone'];original=json.loads(raw);bridge,calls=self.bridge([(200,raw)])
            native=bridge.request('GET','/control/action/status?action_id='+original['action_id'])
            self.assertTrue(exact(native,original));self.assertEqual(len(calls),1)
            validate_scoped_witness(native,self.values[kind]['request'],native['action_id'],self.values[kind]['intent'])
            self.assertEqual(raw,(self.root/kind/'generated-standalone.json').read_bytes())


if __name__=='__main__':unittest.main()
