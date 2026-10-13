from copy import deepcopy
import unittest
from unittest.mock import patch
from mdc_skills import planning
from mdc_skills.registry import default_registry
from mdc_skills.core import SkillError, Outcome
from test_reach_inventory_resources import observation, cell, stack, FakeRuntime

class PlanningTests(unittest.TestCase):
    def test_discover_station_uses_observed_reachable_cells(self):
        before = observation()
        before.terrain['cells'] = [c for c in before.terrain['cells'] if (c['x'],c['y'],c['z']) != (2,64,0)] + [cell(2,64,0,'minecraft:crafting_table')]
        result = planning.discover_workstations(FakeRuntime(before))
        self.assertEqual(result.evidence['stations'][0]['position'], {'x':2,'y':64,'z':0})
        self.assertEqual(result.evidence['stations'][0]['approach']['route_steps'],0)
        self.assertFalse(result.evidence['unseen_stations_known'])
    def test_does_not_invent_unobserved_station(self):
        result = planning.discover_workstations(FakeRuntime(observation()))
        self.assertEqual(result.evidence['stations'],[])
    def test_unknown_station_cell_rejected(self):
        before = observation()
        bad = cell(2,64,0,'minecraft:furnace');bad['known']=False
        before.terrain['cells'] = [c for c in before.terrain['cells'] if (c['x'],c['y'],c['z']) != (2,64,0)] + [bad]
        with self.assertRaisesRegex(SkillError,'unknown'):
            planning.discover_workstations(FakeRuntime(before))
    def test_craft_selects_real_station_without_human_coordinates(self):
        before = observation()
        before.terrain['cells'] = [c for c in before.terrain['cells'] if (c['x'],c['y'],c['z']) != (2,64,0)] + [cell(2,64,0,'minecraft:crafting_table')]
        runtime = FakeRuntime(before)
        done = Outcome('succeeded','fixture',last_observation=before)
        with patch.object(planning.production,'craft',return_value=done) as craft:
            planning.craft_nearby(runtime,'iron_pickaxe')
            self.assertEqual(craft.call_args.kwargs['station']['position'],{'x':2,'y':64,'z':0})
    def test_two_by_two_recipe_needs_no_invented_workstation(self):
        before = observation(); runtime=FakeRuntime(before)
        with patch.object(planning.production,'craft',return_value=Outcome('succeeded','fixture',last_observation=before)) as craft:
            planning.craft_nearby(runtime,'stick')
            self.assertIsNone(craft.call_args.kwargs['station'])
    def test_smelting_chooses_observed_fuel_and_station(self):
        before = observation(entries={0:stack('minecraft:coal',1),1:stack('minecraft:raw_iron',2)})
        before.terrain['cells'] = [c for c in before.terrain['cells'] if (c['x'],c['y'],c['z']) != (2,64,0)] + [cell(2,64,0,'minecraft:furnace')]
        with patch.object(planning.production,'smelt',return_value=Outcome('succeeded','fixture',last_observation=before)) as smelt:
            planning.smelt_nearby(FakeRuntime(before),'minecraft:raw_iron',count=2)
            self.assertEqual(smelt.call_args.kwargs['fuel_id'],'minecraft:coal')
            self.assertEqual(smelt.call_args.kwargs['station']['block_id'],'minecraft:furnace')
    def test_insufficient_fuel_stops_before_station_or_action(self):
        runtime = FakeRuntime(observation())
        with self.assertRaisesRegex(SkillError,'fuel'):
            planning.smelt_nearby(runtime,'minecraft:raw_iron',count=32)
        self.assertEqual(runtime.commands,[])
    def test_acquisition_already_owned_proves_goal_without_mutation(self):
        runtime=FakeRuntime(observation(entries={0:stack('minecraft:oak_log',3)}))
        result=planning.acquire_nearby(runtime,'minecraft:oak_log',count=2)
        self.assertTrue(result.ok)
        self.assertEqual(runtime.commands,[])
    def test_acquisition_does_not_claim_unseen_resource(self):
        runtime=FakeRuntime(observation())
        with self.assertRaisesRegex(SkillError,'no_reachable_resource'):
            planning.acquire_nearby(runtime,'minecraft:oak_log')
        self.assertEqual(runtime.commands,[])
    def test_registry_discoverable_skills_are_concrete(self):
        registry=default_registry()
        names={x['name'] for x in registry.describe()}
        self.assertTrue({'craft_nearby','smelt_nearby','acquire_nearby','discover_end_goals','build','navigate','consume','end_battle'}<=names)
        self.assertTrue(all(callable(registry.get(name).run) for name in names))
        with self.assertRaises(TypeError):registry.get('navigate').validate({'not_a_goal':True})

if __name__=='__main__':unittest.main()
