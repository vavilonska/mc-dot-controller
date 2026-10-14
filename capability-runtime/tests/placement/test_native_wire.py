"""Current production Java placement emitters → real closed Python consumers.

Java fixture facts are explicitly synthetic. Tests do not simulate native
placement effects or claim that Minecraft/mixins were executed.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from resident_controller.capability_snapshot import exact, validate_scoped_witness, validate_snapshot
from resident_controller.movement_wire import MARKER, REFERENCE, WITNESS, WIRE_LIMIT, decode, load_strict, retain, validate_retained
from mdc_skills import scoped_placement


class NativePlacementWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location=os.environ.get('MDC_PLACEMENT_WIRE_DIR')
        if not location:
            raise unittest.SkipTest('Supply current production Java-emitted placement bytes via MDC_PLACEMENT_WIRE_DIR')
        cls.directory=Path(location).resolve()
        names=('placement-standalone.json','placement-coherent.json','placement-request.json','placement-intent.json',
               'placement-inventory-before.json','placement-inventory-after.json',
               'placement-terminal-standalone.json','placement-terminal-coherent.json',
               'placement-witness.json','placement-terminal.json','TERMINAL-EXTRACTION.json')
        cls.raw={name:(cls.directory/name).read_bytes() for name in names}
        if not all(0<len(raw)<=WIRE_LIMIT for raw in cls.raw.values()):
            raise ValueError('Placement Java input exceeds unchanged wire cap')
        cls.hashes={name:hashlib.sha256(raw).hexdigest() for name,raw in cls.raw.items()}
        print(json.dumps({'placement_original_java_inputs':cls.hashes,
                         'scope':'Synthetic captured state; production witness/HTTP codec and exact hashed extracted production terminal method with synthetic readers'}),flush=True)

    @classmethod
    def tearDownClass(cls):
        for name,raw in cls.raw.items():
            if (cls.directory/name).read_bytes()!=raw:
                raise AssertionError('Original placement Java bytes changed: '+name)

    def parsed(self,name):
        name={'standalone':'terminal-standalone','coherent':'terminal-coherent'}.get(name,name)
        return load_strict(self.raw['placement-'+name+'.json'])

    def validate(self,native):
        scope,intent=self.parsed('request'),self.parsed('intent')
        original=deepcopy(native)
        value=validate_scoped_witness(native,scope,intent['action_id'],intent)
        self.assertTrue(exact(original,native),'Consumer must not repair producer evidence')
        return value

    def observations(self):
        native=self.parsed('standalone')
        return (SimpleNamespace(player=self.parsed('inventory-before'),state={}),
                SimpleNamespace(player=self.parsed('inventory-after'),state={'client_action':native}))

    def test_extracted_terminal_body_is_exact_current_production_source(self):
        report=load_strict(self.raw['TERMINAL-EXTRACTION.json'])
        source=Path(__file__).resolve().parents[3]/'client-mod/src/main/java/io/github/campione01/mineclientbridge/ScopedPlacement.java'
        raw=source.read_bytes();text=raw.decode('utf-8')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),report['production_source_sha256'])
        self.assertEqual(report['method_signature'],'    JsonObject terminal(boolean neutral,boolean success)')
        start,end=report['start_offset'],report['end_offset']
        self.assertIs(type(start),int);self.assertIs(type(end),int)
        self.assertTrue(0<=start<end<=len(text))
        method=text[start:end]
        self.assertTrue(method.startswith(report['method_signature']))
        self.assertEqual(hashlib.sha256(method.encode('utf-8')).hexdigest(),report['terminal_method_sha256'])
        # Reader values are synthetic; source-exact compilation is evidence for
        # representation compatibility, never actual engine state or placement.

    def test_admitted_and_terminal_receipts_bind_same_original_intent(self):
        admitted=load_strict(self.raw['placement-standalone.json'])
        self.assertEqual(admitted['status'],'running')
        first=self.validate(admitted)
        final=self.validate(self.parsed('standalone'))
        self.assertTrue(exact(first,final),'Admission facts cannot be recaptured at terminal')
        coherent=validate_snapshot(load_strict(self.raw['placement-coherent.json']),8)
        self.assertTrue(exact(first,self.validate(coherent['action'])))

    def test_actual_java_terminal_and_command_digests(self):
        native=self.parsed('standalone');w=self.validate(native)
        self.assertEqual(native['status'],'succeeded')
        self.assertEqual(w['profile'],scoped_placement.PROFILE)
        t=native['result']['placement']
        self.assertEqual((t['effect_count'],t['packet_count']),(1,1))
        self.assertEqual(t['final_count'],t['initial_count']-1)
        self.assertIs(t['unknown_outcome'],False)
        self.assertIs(t['automatic_replay_allowed'],False)
        self.assertIs(t['protected_inventory_unchanged'],True)
        self.assertIs(t['server_confirmed'],False)
        # Recompute both immutable digests in the real validator, not an assertion
        # against a second independently manufactured witness.
        for name in ('submitted_intent_sha256','command_sha256'):
            bad=deepcopy(native);bad['result'][WITNESS][name]='0'*64
            with self.subTest(name=name),self.assertRaises(ValueError):self.validate(bad)

    def test_actual_coherent_envelope_single_authority_and_retention(self):
        raw=self.raw['placement-terminal-coherent.json'];encoded=self.parsed('coherent');original=deepcopy(encoded)
        self.assertIn(MARKER,encoded)
        for name in ('state','status'):
            result=encoded[name]['client_action']['result']
            self.assertIn(REFERENCE,result);self.assertNotIn(WITNESS,result)
        semantic=validate_snapshot(encoded,8)
        self.assertTrue(exact(encoded,original))
        self.assertTrue(exact(semantic,decode(original)))
        witness=self.validate(semantic['action'])
        self.assertTrue(exact(witness,self.validate(self.parsed('standalone'))))
        provenance=retain(raw)
        self.assertEqual(provenance['sha256'],self.hashes['placement-terminal-coherent.json'])
        self.assertEqual(provenance['raw_utf8'].encode(),raw)
        self.assertTrue(exact(validate_retained(provenance,semantic,8),semantic))

    def test_real_terminal_predicate_with_java_inventory_samples(self):
        before,after=self.observations();proof=after.state['client_action']['result']['placement']
        self.assertTrue(scoped_placement._placed(before,after,proof['target'],proof['selected_slot']))
        slot=proof['selected_slot']
        for change in ('no_decrement','extra_decrement','protected_other_inventory','wrong_selected_slot'):
            bad=deepcopy(after)
            selected=next(r for r in bad.player['inventory'] if r['slot']==slot)
            if change=='no_decrement':selected['count']+=1
            elif change=='extra_decrement':selected['count']-=1
            elif change=='wrong_selected_slot':bad.player['selected_slot']=(slot+1)%9
            else:next(r for r in bad.player['inventory'] if r['slot']!=slot)['component_fingerprint']='changed'
            with self.subTest(change=change):
                self.assertFalse(scoped_placement._placed(before,bad,proof['target'],slot))

    def test_raw_exports_preserve_exact_full_codec_subtrees(self):
        native=self.parsed('standalone')
        self.assertTrue(exact(self.parsed('witness'),native['result'][WITNESS]))
        self.assertTrue(exact(self.parsed('terminal'),native['result']['placement']))

    def test_nullable_entity_fields_survive_real_http_serialization(self):
        native=self.parsed('standalone');w=self.validate(native)
        rows=w['facts']['placement']['entity_guard']['rows']
        living=[r for r in rows if not r['removed'] and r['flags']['living']]
        self.assertTrue(living,'Java input must exercise at least one real nullable entity flag')
        for row in living:
            self.assertIn('mob_target_uuid',row['flags']);self.assertIsNone(row['flags']['mob_target_uuid'])
        bad=deepcopy(native)
        row=next(r for r in bad['result'][WITNESS]['facts']['placement']['entity_guard']['rows']
                 if not r['removed'] and r['flags']['living'])
        del row['flags']['mob_target_uuid']
        with self.assertRaises(ValueError):self.validate(bad)
        bad=deepcopy(native)
        row=next(r for r in bad['result'][WITNESS]['facts']['placement']['entity_guard']['rows']
                 if not r['removed'] and r['flags']['living'])
        row['flags']['mob_target_uuid']='arbitrary-target'
        with self.assertRaises(ValueError):self.validate(bad)

    def test_actual_terminal_exact_types_counts_and_unknown_reject_success(self):
        for name,value in (('effect_count',True),('effect_count',2),('packet_count',0),('unknown_outcome',True),
                           ('block_placed',False),('protected_inventory_unchanged',False),('automatic_replay_allowed',True),
                           ('input_neutral',False),('final_count',True)):
            bad=self.parsed('standalone');bad['result']['placement'][name]=value
            with self.subTest(name=name,value=value),self.assertRaises(ValueError):self.validate(bad)
        bad=self.parsed('standalone');bad['result']['placement']['final_count']+=1
        with self.assertRaises(ValueError):self.validate(bad)

    def test_closed_actual_witness_geometry_and_intent_binding(self):
        for change in ('extra_field','missing_cell','reordered_cells','changed_support','changed_entity_coverage'):
            bad=self.parsed('standalone');p=bad['result'][WITNESS]['facts']['placement']
            if change=='extra_field':p['extra']=True
            elif change=='missing_cell':p['cells'].pop()
            elif change=='reordered_cells':p['cells'].reverse()
            elif change=='changed_support':p['support']['x']+=1
            else:p['entity_guard']['enumerated_count']+=1
            with self.subTest(change=change),self.assertRaises(ValueError):self.validate(bad)

    def test_actual_coherent_wrong_reference_fails_closed(self):
        for change in ('wrong_profile','wrong_owner','missing_marker','inline_duplicate'):
            bad=self.parsed('coherent');result=bad['state']['client_action']['result']
            if change=='wrong_profile':result[REFERENCE]['profile']='mining-local-observed-v2'
            elif change=='wrong_owner':result[REFERENCE]['owner_generation']+=1
            elif change=='missing_marker':del bad[MARKER]
            else:result[WITNESS]=deepcopy(bad['action']['result'][WITNESS])
            with self.subTest(change=change),self.assertRaises(ValueError):validate_snapshot(bad,8)

    def test_actual_raw_bytes_reject_duplicate_and_nonfinite_keys(self):
        raw=self.raw['placement-terminal-standalone.json'];start=raw.index(b'{')
        for extra in (b'"negative":1,"negative":2,',b'"negative":NaN,'):
            with self.assertRaises(ValueError):load_strict(raw[:start+1]+extra+raw[start+1:])


if __name__=='__main__':unittest.main()
