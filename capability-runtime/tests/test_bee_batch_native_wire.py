"""Unchanged consumer accepts original native equivalent-publication output."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import unittest
from resident_controller.capability_snapshot import validate_scoped_witness, validate_snapshot, exact
from resident_controller.movement_wire import retain, validate_retained

@unittest.skipUnless(os.environ.get('MDC_BEE_BATCH_NATIVE_WIRE') and os.environ.get('MDC_BEE_BATCH_ENGINE_EVIDENCE'),
                     'explicit native equivalent-publication wire and engine directories required')
class BeeBatchNativeWireTests(unittest.TestCase):
    def test_original_equivalent_publication(self):
        root=Path(os.environ['MDC_BEE_BATCH_NATIVE_WIRE'])
        engine=Path(os.environ['MDC_BEE_BATCH_ENGINE_EVIDENCE'])
        raw={k:(root/('generated-'+k+'.json')).read_bytes() for k in ('standalone','coherent','intent','request')}
        value={k:json.loads(v) for k,v in raw.items()}
        native=value['standalone']; before=deepcopy(native)
        witness=validate_scoped_witness(native,value['request'],native['action_id'],value['intent'])
        self.assertEqual(native['status'],'succeeded')
        self.assertTrue(native['result']['input_release_confirmed'])
        self.assertEqual(witness['profile'],'movement-local-segment-spatial-stop-v2')
        footprint=json.loads((engine/'actual-footprint.json').read_bytes())
        self.assertTrue(exact(witness['facts']['local_segment'],footprint))
        bees=[r for r in footprint['entity_guard']['rows'] if r['type']=='minecraft:bee' and not r['removed']]
        self.assertTrue(bees)
        publication=json.loads((engine/'equivalent-publication-evidence.json').read_bytes())
        self.assertTrue(publication['original_witness_retained'])
        self.assertGreaterEqual(publication['same_callback_equivalent_publications'], 2)
        self.assertGreater(int(publication['admission_replacement_source_nano']),int(publication['original_source_nano']))
        for row in bees:
            n=row['native_living']
            self.assertEqual(n['source_nano'],publication['original_source_nano'])
            self.assertTrue(n['known']); self.assertTrue(n['coverage_complete'])
            self.assertFalse(n['aggressive']);self.assertIsNone(n['current_target'])
            self.assertFalse(n['bee']['angry']);self.assertFalse(n['bee_route']['has_stung'])
            self.assertLessEqual(int(witness['admitted_nano'])-int(n['source_nano']),250000000)
        radius=value['coherent']['state']['nearby']['radius']
        semantic=validate_snapshot(value['coherent'],radius);record=retain(raw['coherent'])
        self.assertEqual(record['sha256'],hashlib.sha256(raw['coherent']).hexdigest())
        self.assertTrue(exact(validate_retained(record,semantic,radius),semantic))
        validate_scoped_witness(semantic['action'],value['request'],native['action_id'],value['intent'])
        self.assertTrue(exact(before,native))
        for k,v in raw.items():self.assertEqual((root/('generated-'+k+'.json')).read_bytes(),v)

if __name__=='__main__':unittest.main()
