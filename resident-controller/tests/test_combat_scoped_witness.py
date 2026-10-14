"""Mutation tests exercise the actual consumer; fixtures are not native/game proof."""
from copy import deepcopy
import unittest
from combat_witness_fixture import fixture, reseal
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.combat_snapshot import TYPES


class CombatScopedWitnessTests(unittest.TestCase):
    def check(self, data):
        return validate_scoped_witness(*data)

    def test_all_six_species_and_numeric_reserve(self):
        for species in TYPES:
            d = fixture(); d[3]['target_type'] = species
            c = d[0]['result']['scoped_native_preflight']['facts']['combat']
            c['target_type'] = species; c['min_health'] = 14.0
            reseal(d); self.check(d)

    def test_missing_extra_and_future_fields(self):
        for key in fixture()[0]['result']['scoped_native_preflight']['facts']['combat']:
            d = fixture(); del d[0]['result']['scoped_native_preflight']['facts']['combat'][key]
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(d)
        for key, value in [('future_dynamics_certified', True), ('resume', True), ('target2', {})]:
            d = fixture(); d[0]['result']['scoped_native_preflight']['facts']['combat'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(d)

    def test_bad_target_and_bounds(self):
        mutations = [('target_entity_id', True), ('target_entity_id', -1), ('target_entity_id', 2**31),
            ('target_uuid', '44444444-4444-4444-8444-44444444444X'), ('target_type', 'minecraft:creeper'),
            ('target_type', []), ('target_health', 0), ('target_health', float('inf')),
            ('target_health', True), ('x', float('nan')), ('z', 30000001), ('y', 2049),
            ('alive', 1), ('alive', False), ('approach', 1), ('shield', 'true'),
            ('min_health', 10), ('min_health', 21), ('min_health', True),
            ('timeout_ms', True), ('timeout_ms', 49), ('timeout_ms', 30001)]
        for key, value in mutations:
            d = fixture(); d[0]['result']['scoped_native_preflight']['facts']['combat'][key] = value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError): self.check(d)

    def test_matching_invalid_intents_are_still_rejected(self):
        for key, value in [('target_type','minecraft:creeper'), ('min_health',10), ('timeout_ms',30001),
                           ('target_uuid','wrong'), ('approach',1)]:
            d=fixture(); d[3][key]=value
            d[0]['result']['scoped_native_preflight']['facts']['combat'][key]=value
            reseal(d)
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(d)

    def test_target_and_control_mismatch(self):
        for key,value in [('target_entity_id',10), ('target_type','minecraft:husk'),
                          ('target_uuid','55555555-5555-4555-8555-555555555555'),
                          ('approach',False), ('shield',False), ('min_health',15), ('timeout_ms',1000)]:
            d=fixture(); d[3][key]=value; reseal(d)
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(d)

    def test_closed_intent_and_action_profile(self):
        for key in ('future', 'encounter_scope', 'hotbar_slot', 'observation_clock', 'resume'):
            d=fixture(); d[3][key]={}; reseal(d)
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(d)
        d=fixture(); d[3]['action']='attack_entity'; reseal(d)
        with self.assertRaises(ValueError): self.check(d)
        d=fixture(); d[0]['action']='attack_entity'
        with self.assertRaises(ValueError): self.check(d)

    def test_stale_future_acquisition_and_planning_guard(self):
        for key,value in [('admitted_nano','99'), ('admitted_nano','250000101'), ('source_tick',True)]:
            d=fixture(); d[0]['result']['scoped_native_preflight'][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(d)
        for key,value in [('schema_version',True), ('source_tick',101), ('source_nano','101'),
                          ('source_nano','01'), ('future',True)]:
            d=fixture(); d[3]['capability_guard'][key]=value; reseal(d)
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(d)
        d=fixture(); d[3]['capability_guard']['source_nano']='-1000000000'; reseal(d)
        self.check(d)  # Old planning is not authority; fresh native admission is.

    def test_player_guard_and_held_binding(self):
        for key,value in [('health',14),('using_item',True),('screen_class','InventoryScreen'),('paused',True)]:
            d=fixture(); d[0]['result']['scoped_native_preflight']['facts'][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(d)
        d=fixture(); d[3]['expected_held_item']['count']=1; reseal(d)
        with self.assertRaises(ValueError): self.check(d)
        d=fixture(); d[3]['expected_hotbar_slot']=True; reseal(d)
        with self.assertRaises(ValueError): self.check(d)

    def test_navigation_pair_and_exact_origin(self):
        d=fixture(); d[3].update(expected_navigation_epoch=1,expected_origin=dict(x=.5,y=64.,z=.5))
        reseal(d); self.check(d)
        for key,value in [('expected_origin',dict(x=1.,y=64.,z=.5)),('expected_navigation_epoch',True)]:
            bad=deepcopy(d); bad[3][key]=value; reseal(bad)
            with self.assertRaises(ValueError): self.check(bad)
        del d[3]['expected_origin']; reseal(d)
        with self.assertRaises(ValueError): self.check(d)


if __name__ == '__main__': unittest.main()
