"""Equivalent standalone adapters, strict value types and immutable explicit pairs."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest
from resident_controller.navigation_binding import NativeBindingContext
from test_navigation_binding_producers import state

ROOT=Path(__file__).resolve().parents[2]


class BindingContractTests(unittest.TestCase):
    def adapters(self):
        paths=[ROOT/'resident-controller/resident_controller/navigation_binding.py',
               ROOT/'navigation-cursor/navigation_binding.py',ROOT/'gameplay-helpers/navigation_binding.py']
        self.assertEqual(1,len({hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))
        for i,p in enumerate(paths):
            spec=importlib.util.spec_from_file_location('binding_contract_'+str(i),p)
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);yield m.NativeBindingContext
    def test_same_contract_vectors_for_all_standalone_adapters(self):
        for adapter in self.adapters():
            context=adapter();s=state();pair=context.bind({'action':'follow_path'},s)
            self.assertEqual(s['player']['x'],pair['expected_origin']['x'])
            self.assertEqual({'seen':True},context.dump())
            with self.assertRaisesRegex(ValueError,'missing_after_seen'):context.observe(state(missing=True))
            restored=adapter(context.dump())
            with self.assertRaisesRegex(ValueError,'missing_after_seen'):restored.observe(state(missing=True))
    def test_all_adapters_reject_read_only_observation_clock(self):
        for adapter in self.adapters():
            observed = state()
            observed['observation_clock'] = {'tick': 1}
            with self.assertRaisesRegex(ValueError, 'read_only_observation_navigation_forbidden'):
                adapter().bind({'action': 'follow_path'}, observed)

    def test_explicit_matching_fields_remain_byte_equivalent_and_detached(self):
        s=state(x=1.0);c=NativeBindingContext();body=c.bind({'action':'follow_path'},s)
        body['expected_origin']['x']=1 # Equal finite numeric spelling is retained, never rebound.
        before=copy.deepcopy(body);bound=c.bind(body,s)
        self.assertEqual(before,bound);self.assertIs(type(bound['expected_origin']['x']),int)
        s['player']['x']=100;self.assertEqual(before,bound)
        body['expected_origin']['x']=123;self.assertEqual(1,bound['expected_origin']['x'])
    def test_partial_mismatched_and_bool_origin_do_not_gain_authority(self):
        c=NativeBindingContext();s=state(x=1.0)
        invalid=[{'expected_origin':{'x':1,'y':64,'z':s['player']['z']}},
                 {'expected_navigation_epoch':7},
                 {'expected_navigation_epoch':7,'expected_origin':{'x':True,'y':64,'z':s['player']['z']}},
                 {'expected_navigation_epoch':False,'expected_origin':{'x':1,'y':64,'z':s['player']['z']}},
                 {'expected_navigation_epoch':7,'expected_origin':{'x':100,'y':64,'z':0}},
                 {'expected_world_generation':'wrong'}]
        for body in invalid:
            with self.subTest(body=body),self.assertRaisesRegex(ValueError,'navigation_binding_conflict'):
                c.bind(body,s)
    def test_explicit_pair_cannot_be_validated_by_legacy_absence(self):
        with self.assertRaisesRegex(ValueError,'navigation_binding_conflict'):
            NativeBindingContext().bind({'expected_navigation_epoch':0,'expected_origin':{'x':0,'y':64,'z':0}},state(missing=True))
    def test_invalid_presence_is_sticky_and_legacy_absence_otherwise_remains(self):
        for invalid in (None,False,{}, {'schema_version':2}):
            c=NativeBindingContext()
            with self.assertRaises(ValueError):c.observe(state(navigation_guard=invalid))
            self.assertEqual({'seen':True},c.dump())
            with self.assertRaises(ValueError):c.observe(state(missing=True))
        self.assertEqual({'action':'follow_path'},NativeBindingContext().bind({'action':'follow_path'},state(missing=True)))
