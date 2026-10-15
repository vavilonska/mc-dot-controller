"""Consume original production Java serializer bytes; explicit synthetic-engine origin.

Set MDC_STEP_DOWN_NATIVE_WIRE to the native producer output directory. These are
separate wire-consumer tests and make no live Minecraft physics claim.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import unittest
from resident_controller.capability_snapshot import validate_scoped_witness,validate_snapshot
from resident_controller.movement_wire import retain,validate_retained,valid_size_diagnostic


@unittest.skipUnless(os.environ.get('MDC_STEP_DOWN_NATIVE_WIRE'),'explicit native-produced wire directory required')
class StepDownNativeWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['MDC_STEP_DOWN_NATIVE_WIRE'])
        cls.raw={name:(cls.root/name).read_bytes() for name in ('generated-standalone.json','generated-coherent.json',
            'generated-intent.json','generated-request.json','generated-size-diagnostic.json')}
        cls.values={name:json.loads(value) for name,value in cls.raw.items()}
    def data(self):
        a,i,q=(deepcopy(self.values[n]) for n in ('generated-standalone.json','generated-intent.json','generated-request.json'))
        return a,q,a['action_id'],i
    def test_exact_standalone_production_witness(self):
        witness=validate_scoped_witness(*self.data())
        self.assertEqual(witness['profile'],'movement-step-down-observed-v1')
        self.assertEqual(witness['facts']['step_down']['expected_cells'],180)
        self.assertEqual(witness['facts']['step_down']['movement_budget_status'],'unarmed')
    def test_exact_coherent_and_original_byte_provenance(self):
        bundle=self.values['generated-coherent.json'];radius=bundle['state']['nearby']['radius']
        semantic=validate_snapshot(bundle,radius)
        record=retain(self.raw['generated-coherent.json']);self.assertEqual(record['sha256'],hashlib.sha256(self.raw['generated-coherent.json']).hexdigest())
        self.assertEqual(validate_retained(record,semantic,radius),semantic)
        validate_scoped_witness(semantic['action'],self.values['generated-request.json'],semantic['action']['action_id'],self.values['generated-intent.json'])
        tampered=deepcopy(record);tampered['raw_utf8']+=' '
        with self.assertRaises(ValueError):validate_retained(tampered,semantic,radius)
    def test_size_diagnostic_is_distinct_from_flat(self):
        value=deepcopy(self.values['generated-size-diagnostic.json']);self.assertTrue(valid_size_diagnostic(value))
        value['cell_count']=150;self.assertFalse(valid_size_diagnostic(value))
        value=deepcopy(self.values['generated-size-diagnostic.json']);value['profile']='movement-flat-observed-v2'
        self.assertFalse(valid_size_diagnostic(value))
    def test_native_geometry_missing_fluid_and_wrong_support_refuse(self):
        for mode in ('missing','fluid','support','headroom','meter','food'):
            d=self.data();m=d[0]['result']['scoped_native_preflight']['facts']['step_down']
            if mode=='missing':m['cells'].pop()
            elif mode=='fluid':m['cells'][0]['fluid']='minecraft:water'
            elif mode=='support':m['cells'][0]['id']='minecraft:air'
            elif mode=='headroom':next(c for c in m['cells'] if c['y']==m['start_y'])['id']='minecraft:stone'
            elif mode=='meter':m['movement_budget_status']='armed'
            else:m['source_food_level']=5
            with self.subTest(mode=mode),self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_native_terminal_forgery_and_profile_alias_refuse(self):
        for key,value in (('profile','movement-flat-observed-v2'),('phase','upper'),('input_neutral',False),('sampled_horizontal_distance',3.)):
            d=self.data();d[0]['result']['step_down'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_scoped_witness(*d)
        d=self.data();del d[0]['result']['step_down']
        with self.assertRaises(ValueError):validate_scoped_witness(*d)
        d=self.data();d[1]['profile']='movement-flat-observed-v2'
        with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_encoded_reference_cannot_switch_owner(self):
        b=deepcopy(self.values['generated-coherent.json'])
        b['state']['client_action']['result']['scoped_native_preflight_ref']['owner_generation']+=1
        with self.assertRaises(ValueError):validate_snapshot(b,b['state']['nearby']['radius'])

if __name__=='__main__':unittest.main()
