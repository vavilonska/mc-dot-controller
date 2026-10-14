"""Strict synthetic placement witness mutations; no live execution claims."""
from copy import deepcopy
import unittest
from placement.placement_fixture import placement_fixture
from resident_controller.capability_snapshot import validate_scoped_witness

class WitnessTests(unittest.TestCase):
    def bad(self,change):
        d=placement_fixture();change(d)
        with self.assertRaises((ValueError,KeyError,TypeError)):validate_scoped_witness(*d)
    def test_complete_and_exact(self):self.assertEqual(validate_scoped_witness(*placement_fixture())['profile'],'placement-local-observed-v1')
    def test_closed_fact_terminal_and_intent_keys(self):
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['placement'].update(unknown=True))
        self.bad(lambda d:d[0]['result']['placement'].update(unknown=True))
        self.bad(lambda d:d[3].update(capability_bridge=True))
    def test_one_item_and_once_only_success(self):
        for key,value in [('final_count',5),('final_count',3),('initial_count',6),('effect_count',0),('effect_count',2),
                          ('packet_count',0),('packet_count',True),('unknown_outcome',True),('protected_inventory_unchanged',False),
                          ('automatic_replay_allowed',True),('block_placed',False),('input_neutral',False),('selected_slot',1)]:
            with self.subTest(key=key,value=value):self.bad(lambda d:d[0]['result']['placement'].update({key:value}))
    def test_no_effect_cancel_accepted_after_effect_cancel_unknown(self):
        d=placement_fixture();d[0]['status']='cancelled';t=d[0]['result']['placement']
        t.update(effect_attempted=False,effect_count=0,packet_count=0,block_placed=False,protected_inventory_unchanged=False,final_count=5)
        validate_scoped_witness(*d)
        t.update(effect_attempted=True)
        with self.assertRaises(ValueError):validate_scoped_witness(*d)
        t['unknown_outcome']=True;validate_scoped_witness(*d)
    def test_original_context_owner_and_deadline_bound(self):
        for key,value in [('deadline_nano','0'),('maximum_action_ticks',160),('initial_count',True),('selected_slot',1),('all_loaded',False)]:
            self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['placement'].update({key:value}))
        self.bad(lambda d:d[0]['result']['scoped_native_preflight'].update(owner_generation=2))
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['context'].update(dimension='minecraft:the_end'))
    def test_complete_cells_and_strict_entity_policy(self):
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['placement']['cells'].pop())
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['placement']['cells'].reverse())
        for key,value in [('loaded',False),('block_class','custom.Block'),('fluid','minecraft:water'),('properties',{'foo':'bar'})]:
            self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['placement']['cells'][0].update({key:value}))
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['placement']['entity_guard'].update(policy='mining-observed-items-v1'))
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['placement']['entity_guard'].update(enumerated_count=2))

class WireTests(unittest.TestCase):
    def test_same_envelope_placement_authority_and_size_diagnostic(self):
        from resident_controller import movement_wire as wire
        n,_,_,_=placement_fixture();w=n['result'][wire.WITNESS]
        reference={'schema_version':1,'path':wire.TARGET,**{k:deepcopy(w[k]) for k in wire.BINDINGS}}
        sibling=deepcopy(n);del sibling['result'][wire.WITNESS];sibling['result'][wire.REFERENCE]=reference
        bundle={wire.MARKER:wire.ENCODING,'action':n,'state':{'client_action':deepcopy(sibling)},'status':{'client_action':deepcopy(sibling)}}
        decoded=wire.decode(bundle)
        self.assertEqual(decoded['state']['client_action']['result'][wire.WITNESS],w)
        bad=deepcopy(bundle);bad['state']['client_action']['result'][wire.REFERENCE]['profile']='mining-local-observed-v2'
        with self.assertRaises(ValueError):wire.decode(bad)
        diag={'schema_version':3,'profile':'placement-local-observed-v1','standalone_bytes':260000,'capability_bytes':270000,
              'response_limit':262144,'standalone_reserve_bytes':8192,'capability_reserve_bytes':24576,
              'witness_bytes':240000,'entity_frame_bytes':100000,'enumerated_count':1,'cell_count':75}
        self.assertTrue(wire.valid_size_diagnostic(diag))
        self.assertFalse(wire.valid_size_diagnostic({**diag,'schema_version':2}))

if __name__=='__main__':unittest.main()
