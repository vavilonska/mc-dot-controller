"""Original native terrain diagnostics and serializer bytes, never rewritten evidence.

Set MDC_ROUTE_TERRAIN_NATIVE_WIRE and MDC_ROUTE_TERRAIN_ENGINE_EVIDENCE to final,
explicit producer outputs. These tests do not start Java, Minecraft, or sockets.
Synthetic engine readers are not live-world or physics acceptance evidence.
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
from resident_controller.route_terrain_snapshot import POLICY, CURRENT_KEYS, validate_diagnostic
from resident_controller.movement_wire import retain, validate_retained, valid_size_diagnostic
from resident_controller.route_spatial_stop_snapshot import PROFILE
from resident_controller.transport import BridgeError
from support_core import Clock, Client, move
import test_route_spatial_stop_contract as transport_fixture


@unittest.skipUnless(os.environ.get('MDC_ROUTE_TERRAIN_NATIVE_WIRE') and os.environ.get('MDC_ROUTE_TERRAIN_ENGINE_EVIDENCE'),
                     'explicit final native wire and engine directories required')
class RouteTerrainNativeWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['MDC_ROUTE_TERRAIN_NATIVE_WIRE'])
        cls.engine=Path(os.environ['MDC_ROUTE_TERRAIN_ENGINE_EVIDENCE'])
        cases={path.name for path in cls.root.glob('terrain-equivalence-*') if path.is_dir()}
        required={'terrain-equivalence-success','terrain-equivalence-grass-success','terrain-equivalence-rejection','terrain-equivalence-motion','terrain-equivalence-post-tick'}
        if not required <= cases:raise AssertionError('Final producer lacks required terrain cases: '+str(sorted(required-cases)))
        cls.raw={kind:{name:(cls.root/kind/f'generated-{name}.json').read_bytes()
            for name in ('standalone','coherent','intent','request','size-diagnostic')} for kind in sorted(cases)}
        cls.values={kind:{name:json.loads(value) for name,value in entries.items()} for kind,entries in cls.raw.items()}

    def data(self, kind):
        a,q,i=(deepcopy(self.values[kind][n]) for n in ('standalone','request','intent'))
        return a,q,a['action_id'],i

    def test_every_original_standalone_and_admission_footprint_is_unchanged_engine_output(self):
        for kind in self.values:
            data=self.data(kind);w=validate_scoped_witness(*data)
            source=json.loads((self.engine/kind/'actual-footprint.json').read_bytes())
            with self.subTest(kind=kind):
                self.assertEqual(w['profile'],PROFILE)
                self.assertTrue(exact(w['facts']['local_segment'],source))
                self.assertNotIn('route_threat_guard',data[3]);self.assertNotIn('route_stop_only',data[3])
                self.assertNotIn('route_threat_stop',data[0]['result'])

    def test_original_leaf_success_retains_literal_admitted_state_not_accepted_later_state(self):
        data=self.data('terrain-equivalence-success');w=validate_scoped_witness(*data)
        native=data[0];self.assertEqual(native['status'],'succeeded')
        rows=[r for r in w['facts']['local_segment']['cells'] if r['id']=='minecraft:oak_leaves']
        self.assertTrue(rows)
        self.assertTrue(all(r['role']=='context' and 'distance=3,persistent=false,waterlogged=false' in r['state'] for r in rows))
        self.assertNotIn('route_terrain_rejection',native['result'])
        self.assertTrue(native['result']['input_release_confirmed'])
        metadata=json.loads((self.engine/'terrain-equivalence-success'/'actual-metadata.json').read_bytes())
        self.assertEqual(metadata['native_status'],'succeeded');self.assertEqual(metadata['native_reason'],'path_reached')

    def test_original_grass_success_keeps_original_context_grass_without_rebinding(self):
        data=self.data('terrain-equivalence-grass-success');w=validate_scoped_witness(*data)
        native=data[0];self.assertEqual(native['status'],'succeeded');self.assertEqual(native['reason'],'path_reached')
        rows=[r for r in w['facts']['local_segment']['cells'] if r['id']=='minecraft:grass_block']
        self.assertTrue(rows);self.assertTrue(all(r['role']=='context' and r['state']=='minecraft:grass_block[snowy=false]' for r in rows))
        self.assertNotIn('route_terrain_rejection',native['result'])
        metadata=json.loads((self.engine/'terrain-equivalence-grass-success'/'actual-metadata.json').read_bytes())
        self.assertEqual(metadata['native_status'],'succeeded');self.assertEqual(metadata['native_reason'],'path_reached')

    def test_original_refusal_motion_and_post_tick_keep_distinct_outcomes_and_nullable_facts(self):
        for kind,status,reason in (('terrain-equivalence-rejection','cancelled','local_segment_fluid_present'),
                ('terrain-equivalence-motion','cancelled','local_segment_fluid_present'),
                ('terrain-equivalence-post-tick','failed','client_action_error')):
            native,scope,aid,intent=self.data(kind);w=validate_scoped_witness(native,scope,aid,intent)
            d=native['result']['route_terrain_rejection']
            with self.subTest(kind=kind):
                self.assertEqual(native['status'],status);self.assertEqual(native['reason'],reason)
                self.assertEqual(d['policy'],POLICY);self.assertEqual(d['phase'],'capture')
                self.assertEqual(d['rejection_code'],'local_segment_fluid_present')
                self.assertEqual(set(d['current']),CURRENT_KEYS)
                self.assertIs(d['current']['fluid_empty'],False)
                self.assertIsNone(d['current']['full_cube']);self.assertIsNone(d['current']['collision_empty'])
                self.assertIsNone(d['current']['friction']);self.assertEqual(d['changed_fields'],['fluid_empty'])
                self.assertIs(validate_diagnostic(d,w,native),d)
                self.assertEqual(native['result'].get('unknown_outcome') is True,kind=='terrain-equivalence-motion')

    def test_original_coherent_utf8_hash_and_complete_sibling_diagnostic_equality(self):
        for kind,source in self.values.items():
            raw=self.raw[kind]['coherent'];bundle=source['coherent'];radius=bundle['state']['nearby']['radius']
            with self.subTest(kind=kind):
                semantic=validate_snapshot(bundle,radius);record=retain(raw)
                self.assertEqual(record['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(record['raw_utf8'].encode('utf-8'),raw)
                self.assertTrue(exact(validate_retained(record,semantic,radius),semantic))
                validate_scoped_witness(semantic['action'],source['request'],semantic['action']['action_id'],source['intent'])
                for name in ('status','state'):
                    self.assertTrue(exact(semantic[name]['client_action']['result'],semantic['action']['result']))
                bad=deepcopy(record);bad['raw_utf8']+=' '
                with self.assertRaises(ValueError):validate_retained(bad,semantic,radius)

    def test_original_diagnostic_mutations_and_missing_nulls_refuse_without_rewriting_source(self):
        for kind in ('terrain-equivalence-rejection','terrain-equivalence-motion','terrain-equivalence-post-tick'):
            for mutation in ('coordinate','original','current_role','changed','policy','profile','missing_null','extra'):
                data=self.data(kind);d=data[0]['result']['route_terrain_rejection']
                if mutation=='coordinate':d['cell']['x']+=1
                elif mutation=='original':d['original']['state']+=' changed'
                elif mutation=='current_role':d['current']['role']='clear'
                elif mutation=='changed':d['changed_fields']=[]
                elif mutation=='policy':d['policy']='route-spatial-stop-v1'
                elif mutation=='profile':d['profile']='movement-local-segment-spatial-threat-v1'
                elif mutation=='missing_null':del d['current']['friction']
                else:d['current']['extra']=False
                with self.subTest(kind=kind,mutation=mutation),self.assertRaises((ValueError,KeyError,TypeError)):
                    validate_scoped_witness(*data)
            self.assertEqual(json.loads(self.raw[kind]['standalone']),self.values[kind]['standalone'])

    def test_wire_schema7_reserves_and_profile_binding_remain_unchanged(self):
        for kind,source in self.values.items():
            d=source['size-diagnostic']
            with self.subTest(kind=kind):
                self.assertTrue(valid_size_diagnostic(d));self.assertEqual(d['schema_version'],7)
                self.assertEqual(d['profile'],PROFILE);self.assertEqual(d['standalone_reserve_bytes'],8192)
                self.assertEqual(d['capability_reserve_bytes'],24576)
                bad=deepcopy(source['coherent']);bad['state']['client_action']['result']['scoped_native_preflight_ref']['profile']='movement-local-segment-observed-v1'
                with self.assertRaises(ValueError):validate_snapshot(bad,bad['state']['nearby']['radius'])

    def test_actual_original_motion_unknown_latches_without_any_mutation_or_retry(self):
        raw=self.raw['terrain-equivalence-motion']['standalone'];native=json.loads(raw)
        self.assertTrue(native['result']['unknown_outcome']);self.assertTrue(native['result']['motion_gate_rejected'])
        self.assertIn('route_terrain_rejection',native['result'])
        with tempfile.TemporaryDirectory() as directory:
            clock=Clock();client=Client(clock);runtime=Runtime(client,directory,clock=clock,sleeper=clock.sleep)
            try:
                before=runtime.observe();record=runtime._reserve('mutation',move(),skill='native_terrain_consumer',before=before)
                with self.assertRaises(SkillError) as failure:runtime._native_receipt(record,{'action':native},before)
                self.assertEqual(failure.exception.status,'unknown')
                self.assertEqual(failure.exception.reason,'native_receipt_requires_handoff_or_is_uncertain')
                self.assertEqual(record['status'],'unknown');self.assertEqual(runtime.pending_request_id,record['request_id'])
                self.assertEqual(client.action_count,0);runtime.close()
                self.assertEqual(runtime.pending_request_id,record['request_id']);self.assertEqual(client.action_count,0)
                self.assertEqual(json.loads(raw),native)
            finally:runtime.close()

    bridge=transport_fixture.SpatialStopDiagnosticTests.bridge

    def test_actual_transport_preserves_original_nullable_bytes_once(self):
        for kind in ('terrain-equivalence-rejection','terrain-equivalence-motion','terrain-equivalence-post-tick'):
            raw=self.raw[kind]['standalone'];original=json.loads(raw)
            bridge,calls=self.bridge([(200,raw)])
            native=bridge.request('GET','/control/action/status?action_id='+original['action_id'])
            self.assertTrue(exact(native,original));self.assertEqual(len(calls),1)
            validate_scoped_witness(native,self.values[kind]['request'],native['action_id'],self.values[kind]['intent'])


if __name__=='__main__':unittest.main()
