"""Consume original Java serializer bytes; never rebind receipt IDs or rewrite evidence.

Explicit producer directories are required. Engine fixtures are allocation-only,
not live world/physics evidence. No game, network or native owner is started here.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from mdc_skills.core import Runtime, SkillError
from resident_controller.capability_snapshot import validate_scoped_witness, validate_snapshot
from resident_controller.movement_wire import retain, validate_retained, valid_size_diagnostic
from resident_controller.route_spatial_stop_snapshot import PROFILE, POLICY, FAR_TYPES, valid_rejection_diagnostic
from resident_controller.controller import action_rejection_admission
from resident_controller.transport import BridgeError
import test_route_spatial_stop_contract as diagnostic_tests
from support_core import Clock, Client, move


@unittest.skipUnless(os.environ.get('MDC_ROUTE_STOP_NATIVE_WIRE'), 'explicit original native wire directory required')
class RouteSpatialStopNativeWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['MDC_ROUTE_STOP_NATIVE_WIRE'])
        cls.raw={kind:{name:(cls.root/kind/f'generated-{name}.json').read_bytes()
            for name in ('standalone','coherent','intent','request','size-diagnostic')}
            for kind in ('route-stop-success','route-stop-rejection','route-stop-motion')}
        cls.values={kind:{name:json.loads(value) for name,value in entries.items()} for kind,entries in cls.raw.items()}

    def data(self, kind):
        a,q,i=(deepcopy(self.values[kind][n]) for n in ('standalone','request','intent'))
        return a,q,a['action_id'],i

    def test_original_java_success_admits_all_fifteen_typed_far_classes_and_halo_sheep(self):
        data=self.data('route-stop-success');w=validate_scoped_witness(*data)
        self.assertEqual(w['profile'],PROFILE);self.assertEqual(data[0]['status'],'succeeded')
        frame=w['facts']['local_segment']['entity_guard']
        far=[r for r in frame['rows'] if r.get('verdict')=='outside_context']
        self.assertEqual({r['type'] for r in far},set(FAR_TYPES));self.assertEqual(len(far),15)
        for row in far:self.assertEqual(row['class'],FAR_TYPES[row['type']][0])
        near=[r for r in frame['rows'] if r.get('verdict')=='outside_swept']
        self.assertEqual([r['type'] for r in near],['minecraft:sheep'])
        self.assertEqual(frame['enumerated_count'],17)
        self.assertNotIn('route_threat_guard',data[3]);self.assertNotIn('route_stop_only',data[3])

    def test_original_continuation_refusal_and_unknown_motion_preserve_actual_type(self):
        for kind,entity in (('route-stop-rejection','minecraft:arrow'),('route-stop-motion','minecraft:item')):
            data=self.data(kind);validate_scoped_witness(*data);native=data[0]
            with self.subTest(kind=kind):
                self.assertEqual(native['status'],'cancelled')
                self.assertEqual(native['reason'],'scoped_movement_entity_unsupported')
                d=native['result']['route_entity_rejection'];self.assertTrue(valid_rejection_diagnostic(d))
                self.assertEqual(d['entity_type'],entity);self.assertEqual(d['profile'],PROFILE)
                self.assertNotIn('route_threat_stop',native['result'])
                if kind=='route-stop-motion':
                    self.assertIs(native['result']['unknown_outcome'],True)
                    self.assertIs(native['result']['motion_gate_rejected'],True)
                else:self.assertIsNot(native['result'].get('unknown_outcome'),True)

    def test_original_coherent_bytes_provenance_and_unchanged_complete_siblings(self):
        for kind,source in self.values.items():
            raw=self.raw[kind]['coherent'];bundle=source['coherent'];radius=bundle['state']['nearby']['radius']
            with self.subTest(kind=kind):
                semantic=validate_snapshot(bundle,radius);record=retain(raw)
                self.assertEqual(record['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(record['raw_utf8'].encode('utf-8'),raw)
                self.assertEqual(validate_retained(record,semantic,radius),semantic)
                validate_scoped_witness(semantic['action'],source['request'],semantic['action']['action_id'],source['intent'])
                bad=deepcopy(record);bad['raw_utf8']+=' '
                with self.assertRaises(ValueError):validate_retained(bad,semantic,radius)
                for sibling in ('status','state'):
                    bad=deepcopy(bundle);bad[sibling]['client_action']['result']['scoped_native_preflight_ref']['profile']='movement-local-segment-observed-v1'
                    with self.assertRaises(ValueError):validate_snapshot(bad,radius)

    def test_original_size_schema7_diagnostics_have_ordinary_reserves(self):
        for kind,source in self.values.items():
            d=source['size-diagnostic']
            with self.subTest(kind=kind):
                self.assertTrue(valid_size_diagnostic(d));self.assertEqual(d['schema_version'],7)
                self.assertEqual(d['profile'],PROFILE);self.assertEqual(d['standalone_reserve_bytes'],8192)
                self.assertEqual(d['capability_reserve_bytes'],24576)
                self.assertFalse(valid_size_diagnostic({**d,'schema_version':6}))

    def test_original_rows_never_accept_class_projection_or_profile_substitution(self):
        for mutation in ('missing_row','unknown_class','far_near_verdict','projected','swept','policy','profile','stop_only','native_living'):
            data=self.data('route-stop-success');frame=data[0]['result']['scoped_native_preflight']['facts']['local_segment']['entity_guard']
            row=frame['rows'][0]
            if mutation=='missing_row':frame['rows'].pop()
            elif mutation=='unknown_class':row['class']='mod.Bat'
            elif mutation=='far_near_verdict':row['verdict']='outside_swept'
            elif mutation=='projected':row['projected_aabb'][0]+=.001
            elif mutation=='swept':frame['swept_aabb'][0]+=.001
            elif mutation=='policy':frame['policy']='route-spatial-threat-v1'
            elif mutation=='profile':data[0]['result']['scoped_native_preflight']['profile']='movement-local-segment-observed-v1'
            elif mutation=='stop_only':frame['stop_only']=False
            else:row['native_living']={}
            with self.subTest(mutation=mutation),self.assertRaises((ValueError,KeyError,TypeError)):validate_scoped_witness(*data)

    def test_original_motion_unknown_latches_before_receipt_identity_without_mutation(self):
        raw=self.raw['route-stop-motion']['standalone'];native=json.loads(raw)
        self.assertTrue(native['result']['unknown_outcome']);self.assertTrue(native['result']['motion_gate_rejected'])
        with tempfile.TemporaryDirectory() as directory:
            clock=Clock();client=Client(clock);runtime=Runtime(client,directory,clock=clock,sleeper=clock.sleep)
            try:
                before=runtime.observe();record=runtime._reserve('mutation',move(),skill='native_route_stop_consumer',before=before)
                with self.assertRaises(SkillError) as failure:runtime._native_receipt(record,{'action':native},before)
                self.assertEqual(failure.exception.status,'unknown')
                self.assertEqual(failure.exception.reason,'native_receipt_requires_handoff_or_is_uncertain')
                self.assertEqual(record['status'],'unknown');self.assertEqual(runtime.pending_request_id,record['request_id'])
                self.assertEqual(client.action_count,0);runtime.close()
                self.assertEqual(runtime.pending_request_id,record['request_id']);self.assertEqual(client.action_count,0)
                self.assertEqual(json.loads(raw),native)
            finally:runtime.close()


@unittest.skipUnless(os.environ.get('MDC_ROUTE_STOP_ENGINE_EVIDENCE'), 'explicit original engine evidence directory required')
class RouteSpatialStopNativeAdmissionTests(unittest.TestCase):
    bridge=diagnostic_tests.SpatialStopDiagnosticTests.bridge

    def test_original_native_admission_rejection_survives_real_transport_once(self):
        raw=(Path(os.environ['MDC_ROUTE_STOP_ENGINE_EVIDENCE'])/'admission-rejection.json').read_bytes()
        original=json.loads(raw);self.assertEqual(original['route_entity_rejection']['entity_type'],'minecraft:arrow')
        bridge,calls=self.bridge([(409,raw)])
        with self.assertRaises(BridgeError) as caught:
            bridge.request('POST','/control/scoped-action',{'preflight':{'profile':PROFILE},'intent':{}})
        self.assertEqual(caught.exception.code,original['error']);self.assertFalse(caught.exception.uncertain)
        admission=action_rejection_admission(caught.exception)
        self.assertEqual(admission['route_entity_rejection'],original['route_entity_rejection'])
        self.assertFalse(admission['admitted']);self.assertEqual(len(calls),1)
        self.assertEqual(raw,(Path(os.environ['MDC_ROUTE_STOP_ENGINE_EVIDENCE'])/'admission-rejection.json').read_bytes())


if __name__=='__main__':unittest.main()
