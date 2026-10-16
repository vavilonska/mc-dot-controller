"""Consume original Java-generated local-segment wire bytes, not Python fixture copies.

MDC_LOCAL_SEGMENT_NATIVE_WIRE must name an explicit producer directory containing
flat/up/down/gate_failure cases. Engine readers may be synthetic; this is not live physics.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from mdc_skills.core import Runtime,SkillError
from resident_controller.capability_snapshot import validate_scoped_witness,validate_snapshot
from resident_controller.movement_wire import retain,validate_retained,valid_size_diagnostic
from support_core import Clock,Client,move

PROFILE='movement-local-segment-observed-v1'

@unittest.skipUnless(os.environ.get('MDC_LOCAL_SEGMENT_NATIVE_WIRE'),'explicit native-produced wire directory required')
class LocalSegmentNativeWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['MDC_LOCAL_SEGMENT_NATIVE_WIRE']);cls.raw={};cls.values={}
        for kind in ('flat','up','down'):
            cls.raw[kind]={name:(cls.root/kind/name).read_bytes() for name in ('generated-standalone.json','generated-coherent.json',
                'generated-intent.json','generated-request.json','generated-size-diagnostic.json')}
            cls.values[kind]={name:json.loads(value) for name,value in cls.raw[kind].items()}
    def data(self,kind):
        a,i,q=(deepcopy(self.values[kind][n]) for n in ('generated-standalone.json','generated-intent.json','generated-request.json'))
        return a,q,a['action_id'],i
    def test_production_witness_all_edge_kinds(self):
        for kind,dy in (('flat',0),('up',1),('down',-1)):
            with self.subTest(kind=kind):
                witness=validate_scoped_witness(*self.data(kind));self.assertEqual(witness['profile'],PROFILE)
                m=witness['facts']['local_segment'];self.assertEqual(m['step_dy'],dy)
                self.assertEqual(m['expected_cells'],150 if dy==0 else 180);self.assertEqual(m['movement_budget_status'],'unarmed')
    def test_original_coherent_byte_provenance(self):
        for kind in self.values:
            with self.subTest(kind=kind):
                bundle=self.values[kind]['generated-coherent.json'];radius=bundle['state']['nearby']['radius']
                semantic=validate_snapshot(bundle,radius);record=retain(self.raw[kind]['generated-coherent.json'])
                self.assertEqual(record['sha256'],hashlib.sha256(self.raw[kind]['generated-coherent.json']).hexdigest())
                self.assertEqual(validate_retained(record,semantic,radius),semantic)
                validate_scoped_witness(semantic['action'],self.values[kind]['generated-request.json'],semantic['action']['action_id'],self.values[kind]['generated-intent.json'])
                tampered=deepcopy(record);tampered['raw_utf8']+=' '
                with self.assertRaises(ValueError):validate_retained(tampered,semantic,radius)
    def test_size_diagnostic5_is_not_flat_or_descent(self):
        for kind in self.values:
            d=deepcopy(self.values[kind]['generated-size-diagnostic.json']);self.assertTrue(valid_size_diagnostic(d));self.assertEqual(d['schema_version'],5)
            d['profile']='movement-step-down-observed-v1';self.assertFalse(valid_size_diagnostic(d))
    def test_production_geometry_and_role_mutations_refuse(self):
        for kind in self.values:
            for mode in ('missing','fluid','support','clear','role','context'):
                d=self.data(kind);m=d[0]['result']['scoped_native_preflight']['facts']['local_segment']
                if mode=='missing':m['cells'].pop()
                elif mode=='fluid':m['cells'][0]['fluid']='minecraft:water'
                elif mode=='support':next(c for c in m['cells'] if c['role']=='support')['full_cube']=False
                elif mode=='clear':next(c for c in m['cells'] if c['role']=='clear')['id']='minecraft:stone'
                elif mode=='role':next(c for c in m['cells'] if c['role']=='clear')['role']='context'
                else:next(c for c in m['cells'] if c['role']=='context')['id']='minecraft:slime_block'
                with self.subTest(kind=kind,mode=mode),self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_production_terminal_and_owner_substitution_refuse(self):
        for kind in self.values:
            for key,value in (('profile','movement-step-down-observed-v1'),('input_neutral',False),('sampled_horizontal_distance',3.),('jump_pulses',2)):
                d=self.data(kind);d[0]['result']['local_segment'][key]=value
                with self.subTest(kind=kind,key=key),self.assertRaises(ValueError):validate_scoped_witness(*d)
            b=deepcopy(self.values[kind]['generated-coherent.json'])
            b['state']['client_action']['result']['scoped_native_preflight_ref']['owner_generation']+=1
            with self.assertRaises(ValueError):validate_snapshot(b,b['state']['nearby']['radius'])
    def test_original_native_reviewed_foliage_is_context_only(self):
        seen=set()
        for kind in self.values:
            source=self.data(kind)
            rows=source[0]['result']['scoped_native_preflight']['facts']['local_segment']['cells']
            for index,row in enumerate(rows):
                if row['id'] not in ('minecraft:oak_leaves','minecraft:birch_leaves'):continue
                seen.add(row['id']);self.assertEqual(row['role'],'context')
                for key,value in (('id','minecraft:spruce_leaves'),('full_cube',False),('fluid','minecraft:water'),('friction',.98)):
                    bad=self.data(kind)
                    bad[0]['result']['scoped_native_preflight']['facts']['local_segment']['cells'][index][key]=value
                    with self.subTest(kind=kind,key=key),self.assertRaises(ValueError):validate_scoped_witness(*bad)
                for role in ('support','clear'):
                    bad=self.data(kind)
                    target=next(c for c in bad[0]['result']['scoped_native_preflight']['facts']['local_segment']['cells'] if c['role']==role)
                    target.update(id=row['id'],full_cube=True,friction=row['friction'],fluid=row['fluid'])
                    with self.subTest(kind=kind,role=role),self.assertRaises(ValueError):validate_scoped_witness(*bad)
        self.assertEqual(seen,{'minecraft:oak_leaves','minecraft:birch_leaves'},'explicit native producer must capture both reviewed foliage IDs')
    def test_original_native_gate_failure_is_unknown_before_receipt_identity(self):
        # No action IDs, statuses, reasons, fields, or envelopes are rebound here.
        # This tests original Java bytes at the production Runtime receipt boundary;
        # the actual stdio test separately exercises the complete synthetic-native path.
        path=self.root/'gate_failure'/'generated-standalone.json'
        self.assertTrue(path.is_file(),'explicit producer must include original motion-gate failure bytes')
        raw=path.read_bytes();native=json.loads(raw)
        self.assertEqual(native['status'],'cancelled')
        self.assertIs(native['result']['unknown_outcome'],True)
        self.assertIs(native['result']['motion_gate_rejected'],True)
        self.assertIs(native['result']['input_release_confirmed'],True)
        self.assertIs(native['result']['local_segment']['effect_attempted'],True)
        self.assertIsInstance(native['result']['motion_gate_reason'],str)
        request=json.loads((path.parent/'generated-request.json').read_bytes())
        intent=json.loads((path.parent/'generated-intent.json').read_bytes())
        validate_scoped_witness(native,request,native['action_id'],intent)
        with tempfile.TemporaryDirectory() as directory:
            clock=Clock();client=Client(clock);runtime=Runtime(client,directory,clock=clock,sleeper=clock.sleep)
            try:
                before=runtime.observe()
                record=runtime._reserve('mutation',move(),skill='native_gate_consumer',before=before)
                with self.assertRaises(SkillError) as failure:
                    runtime._native_receipt(record,{'action':native},before)
                self.assertEqual(failure.exception.status,'unknown')
                self.assertEqual(failure.exception.reason,'native_receipt_requires_handoff_or_is_uncertain')
                self.assertEqual(record['status'],'unknown')
                self.assertEqual(runtime.pending_request_id,record['request_id'])
                self.assertEqual(client.action_count,0)
                runtime.close();self.assertEqual(runtime.pending_request_id,record['request_id'])
                self.assertEqual(client.action_count,0)
                self.assertEqual(json.loads(raw),native)
            finally:runtime.close()

if __name__=='__main__':unittest.main()
