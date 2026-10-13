"""Offline policy/semantic regression checks, not Minecraft gameplay acceptance."""
import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mdc_skills.core import Observation, Outcome, SkillError
from mdc_skills import reach, inventory, resources


def stack(item='', count=0, damage=0, component=None):
    component = component or item or 'empty'
    return {'id': item, 'count': count, 'damage': damage, 'max_damage': 100 if damage else 0,
            'empty': count == 0, 'max_stack_size': 64 if item else 0,
            'item_fingerprint': f'{component}/{count}/{damage}', 'component_fingerprint': component}


def cell(x, y, z, item='minecraft:air'):
    air = item in resources.AIR
    return {'x': x, 'y': y, 'z': z, 'id': item, 'status': 'loaded', 'known': True,
            'id_truncated': False, 'properties_truncated': False, 'properties': {},
            'fluid': 'minecraft:empty', 'fluid_source': False, 'fluid_truncated': False,
            'collision_known': True, 'collision_empty': air, 'full_top_support': not air,
            'collision_bounds': [0, 0, 0, 1, 1, 1] if not air else [],
            'hazards': [], 'hazards_exhaustive': False, 'air': air}


def observation(tick=10, entries=None, x=.5, selected=0, cells=None, dimension='minecraft:overworld'):
    entries = entries or {0: stack('minecraft:stone', 4), 10: stack('minecraft:bread', 3)}
    rows = [{**copy.deepcopy(entries.get(i, stack())), 'slot': i} for i in range(36)]
    slots = [{'menu_index': i + 50, 'inventory_index': i, 'player_inventory': True,
              'active': True, 'item': copy.deepcopy(row)} for i, row in enumerate(rows)]
    player = {'inventory': rows, 'inventory_total': 36, 'inventory_truncated': False,
              'selected_slot': selected, 'mainhand': rows[selected], 'offhand': stack(),
              'armor': [], 'x': x, 'y': 64, 'z': .5, 'food': 16, 'health': 20,
              'using_item': False, 'effects': [], 'effects_truncated': False,
              'eye_position': {'x': x, 'y': 65.62, 'z': .5}, 'block_interaction_range': 4.5,
              'on_ground': True, 'velocity': {'x': 0, 'y': 0, 'z': 0}}
    state = {'player': player, 'screen_open': False,
             'world': {'world_generation': 'world', 'dimension': dimension, 'game_time': tick},
             'menu': {'container_id': 0, 'menu_class': 'InventoryMenu', 'state_id': 1,
                      'carried': stack(), 'slots': slots, 'slots_truncated': False},
             'nearby': {'entities': [], 'truncated': False}}
    terrain = {'complete': True, 'world_generation': 'world', 'dimension': dimension,
               'source_tick': tick, 'last_tick': tick, 'capture_started_mono': 1,
               'capture_finished_mono': 1.1, 'scan_generation': 'scan',
               'origin': {'x': 0, 'y': 64, 'z': 0}, 'radius': 8, 'vertical': 4,
               'cells': cells if cells is not None else [cell(x, y, z, 'minecraft:stone' if y == 63 else 'minecraft:air')
                                                       for x in range(-2, 5) for y in range(63, 67) for z in range(-2, 3)]}
    return Observation(state, terrain, {}, tick, ('world', dimension, 'player', 'session'), 1, str(tick))


class FakeRuntime:
    def __init__(self, before, after=None, outcome='succeeded'):
        self.before, self.after, self.commands = before, after, []
        self.outcome = outcome
        self.verifier = None
        self.sleeper = lambda _: None
    def clock(self): return 1.2
    def observe(self, **_): return self.before
    def execute(self, skill, command, verify, **options):
        self.commands.append(command); self.verifier = verify
        after = self.after or self.before
        status = self.outcome if verify(options.get('before', self.before), after) else 'failed'
        return Outcome(status, 'fake_semantic_check', ('synthetic',), {}, after)
    def result(self, skill, observations=(), **evidence):
        return Outcome('succeeded', skill, (), evidence, list(observations)[-1])
    def require_success(self, result):
        if not result.ok: raise SkillError(result.reason, status=result.status)
        return result.last_observation


class ReachPolicyTests(unittest.TestCase):
    def test_navigation_reuses_loaded_astar_and_real_action(self):
        before, after = observation(), observation(12, x=2.5)
        runtime = FakeRuntime(before, after)
        result = reach.navigate(runtime, {'x': 2, 'y': 64, 'z': 0})
        self.assertTrue(result.ok)
        self.assertEqual(runtime.commands[0]['action'], 'follow_path')
        self.assertEqual(runtime.commands[0]['waypoints'][-1], {'x': 2.5, 'y': 64, 'z': .5})
    def test_navigation_rejects_unknown_or_unloaded_floor(self):
        before = observation()
        next(c for c in before.terrain['cells'] if (c['x'], c['y'], c['z']) == (2, 63, 0))['known'] = False
        runtime = FakeRuntime(before)
        with self.assertRaisesRegex(SkillError, 'not_supported_or_unknown'):
            reach.navigate(runtime, {'x': 2, 'y': 64, 'z': 0})
        self.assertFalse(runtime.commands)
    def test_navigation_preserves_true_end_dimension_and_explicit_floor_extension(self):
        before = observation(dimension='minecraft:the_end')
        for c in before.terrain['cells']:
            if c['y'] == 63: c['id'] = 'minecraft:end_stone'
        grid, stamp = reach._grid(before)
        self.assertEqual(stamp.dimension, 'minecraft:the_end')
        self.assertTrue(grid.standable(reach.Block(0, 64, 0)))
    def test_navigation_rejects_fabricated_capture(self):
        before = observation(); del before.terrain['capture_started_mono']
        with self.assertRaisesRegex(SkillError, 'original_capture'): reach._grid(before)
    def test_interaction_requires_semantic_goal(self):
        runtime = FakeRuntime(observation())
        with self.assertRaisesRegex(SkillError, 'semantic_goal'):
            reach.interact(runtime, {'x': 1, 'y': 64, 'z': 0})
        self.assertFalse(runtime.commands)
    def test_interaction_binds_block_and_rejects_dispatch_only(self):
        before = observation(); before.terrain['cells'].append(cell(1, 64, 3, 'minecraft:crafting_table'))
        runtime = FakeRuntime(before)
        result = reach.interact(runtime, {'x': 1, 'y': 64, 'z': 3}, expected_menu_class='CraftingMenu')
        self.assertFalse(result.ok)
        self.assertEqual(runtime.commands[0]['expected_block_id'], 'minecraft:crafting_table')
        changed = observation(12); changed.state['menu'].update(menu_class='CraftingMenu', container_id=7)
        self.assertTrue(runtime.verifier(before, changed))
    def test_same_menu_class_without_new_container_is_not_opening_success(self):
        before = observation(); before.terrain['cells'].append(cell(1, 64, 3, 'minecraft:crafting_table'))
        runtime = FakeRuntime(before)
        reach.interact(runtime, {'x': 1, 'y': 64, 'z': 3}, expected_menu_class='InventoryMenu')
        self.assertFalse(runtime.verifier(before, before))
    def test_interaction_out_of_range_never_dispatches(self):
        before = observation(); before.terrain['cells'].append(cell(8, 64, 0, 'minecraft:chest'))
        runtime = FakeRuntime(before)
        with self.assertRaisesRegex(SkillError, 'out_of_reach'):
            reach.interact(runtime, {'x': 8, 'y': 64, 'z': 0}, expected_menu_class='ChestMenu')
        self.assertFalse(runtime.commands)
    def test_close_requires_empty_cursor(self):
        before = observation(); before.state['menu']['carried'] = stack('minecraft:stone', 1)
        with self.assertRaisesRegex(SkillError, 'cursor'): reach.close_menu(FakeRuntime(before))


class InventoryPolicyTests(unittest.TestCase):
    def test_exact_components_differ_despite_same_item_id_count(self):
        a = stack('minecraft:potion', 1, component='healing')
        b = stack('minecraft:potion', 1, component='poison')
        self.assertFalse(inventory._same(a, b))
        self.assertFalse(inventory._same(a, b, count=False))
    def test_select_hotbar_requires_observed_selection(self):
        before = observation(entries={0: stack('minecraft:stone', 1), 2: stack('minecraft:bread', 2)})
        after = observation(12, entries={0: stack('minecraft:stone', 1), 2: stack('minecraft:bread', 2)}, selected=2)
        runtime = FakeRuntime(before, after)
        self.assertTrue(inventory.select_hotbar(runtime, 2).ok)
        self.assertEqual(runtime.commands[0]['expected_hotbar_slot'], 0)
        after.player['selected_slot'] = 1
        self.assertFalse(runtime.verifier(before, after))
    def test_swap_uses_menu_index_not_inventory_index_and_binds_both(self):
        before = observation(); after = observation(12, entries={0: stack('minecraft:bread', 3), 10: stack('minecraft:stone', 4)})
        runtime = FakeRuntime(before, after)
        self.assertTrue(inventory._swap(runtime, before, 10, 0).ok)
        self.assertEqual(runtime.commands[0]['slot'], 60)
        self.assertEqual(runtime.commands[0]['button'], 0)
        self.assertIn('expected_swap_item', runtime.commands[0])
    def test_swap_wrong_source_return_fails(self):
        before = observation(); after = observation(12, entries={0: stack('minecraft:bread', 3), 10: stack()})
        self.assertFalse(inventory._swap(FakeRuntime(before, after), before, 10, 0).ok)
    def test_duplicate_slot_map_rejected_before_mutation(self):
        before = observation(); before.state['menu']['slots'].append(copy.deepcopy(before.state['menu']['slots'][10]))
        runtime = FakeRuntime(before)
        with self.assertRaisesRegex(SkillError, 'ambiguous'): inventory._swap(runtime, before, 10, 0)
        self.assertFalse(runtime.commands)
    def test_potion_unknown_or_wrong_effect_blocks_consumption(self):
        before = observation(entries={0: stack('minecraft:potion', 1)})
        runtime = FakeRuntime(before)
        with self.assertRaisesRegex(SkillError, 'observed_potion_effect'):
            inventory.consume(runtime, 'minecraft:potion', effect_id='minecraft:fire_resistance')
        self.assertFalse(runtime.commands)
    def test_food_consumption_requires_count_and_food_increase(self):
        before = observation(entries={0: stack('minecraft:bread', 3)})
        after = observation(12, entries={0: stack('minecraft:bread', 2)}); after.player['food'] = 20
        runtime = FakeRuntime(before, after)
        self.assertTrue(inventory.consume(runtime, 'minecraft:bread').ok)
        after.player['food'] = before.player['food']
        self.assertFalse(runtime.verifier(before, after))
    def test_full_hunger_blocks_food(self):
        before = observation(entries={0: stack('minecraft:bread', 3)}); before.player['food'] = 20
        with self.assertRaisesRegex(SkillError, 'hunger'): inventory.consume(FakeRuntime(before), 'minecraft:bread')


class ResourcePolicyTests(unittest.TestCase):
    def test_mining_binds_target_tool_and_verifies_actual_air(self):
        before = observation()
        target = next(c for c in before.terrain['cells'] if (c['x'], c['y'], c['z']) == (2, 64, 0))
        target.update(cell(2, 64, 0, 'minecraft:coal_ore'))
        after = observation(12)
        runtime = FakeRuntime(before, after)
        self.assertTrue(resources.mine(runtime, {'x': 2, 'y': 64, 'z': 0}, require_drops=True).ok)
        self.assertEqual(runtime.commands[0]['expected_block_id'], 'minecraft:coal_ore')
        self.assertTrue(runtime.commands[0]['require_correct_tool'])
        self.assertFalse(runtime.verifier(before, before))
    def test_mining_floor_below_player_is_blocked(self):
        with self.assertRaisesRegex(SkillError, 'unsafe_player_column'):
            resources.mine(FakeRuntime(observation()), {'x': 0, 'y': 63, 'z': 0})
    def test_mining_falling_ceiling_blocked(self):
        before = observation()
        for c in before.terrain['cells']:
            if (c['x'], c['y'], c['z']) == (2, 64, 0): c.update(cell(2, 64, 0, 'minecraft:coal_ore'))
            if (c['x'], c['y'], c['z']) == (2, 65, 0): c.update(cell(2, 65, 0, 'minecraft:gravel'))
        with self.assertRaisesRegex(SkillError, 'falling_or_fluid'):
            resources.mine(FakeRuntime(before), {'x': 2, 'y': 64, 'z': 0})
    def test_despawn_does_not_mean_pickup(self):
        before = observation()
        runtime = FakeRuntime(before)
        with self.assertRaisesRegex(SkillError, 'drops_missing'):
            resources.collect(runtime, 'minecraft:coal')
        self.assertFalse(runtime.commands)
    def test_truncated_nearby_blocks_pickup_planning(self):
        before = observation(); before.state['nearby']['truncated'] = True
        with self.assertRaisesRegex(SkillError, 'complete_nearby'):
            resources.collect(FakeRuntime(before), 'minecraft:coal')
    def test_unknown_item_stack_not_invented(self):
        before = observation(); before.state['nearby']['entities'] = [{'type': 'minecraft:item', 'alive': True, 'uuid': 'drop'}]
        self.assertEqual(resources._drops(before, 'minecraft:coal'), [])


class PickupEvidenceTests(unittest.TestCase):
    def test_delayed_pickup_waits_without_replaying_route(self):
        first = observation()
        first.state['nearby']['entities'] = [{'type': 'minecraft:item', 'uuid': 'coal-drop',
            'entity_id': 9, 'alive': True, 'x': 2.5, 'y': 64, 'z': .5,
            'item': stack('minecraft:coal', 1)}]
        reached = observation(11, x=2.5)
        later = [observation(t, x=2.5, entries={0: stack('minecraft:coal', 1)} if t >= 14 else None)
                 for t in range(12, 17)]
        runtime = FakeRuntime(first)
        samples = iter([first] + later)
        runtime.observe = lambda **kwargs: next(samples)
        with patch('mdc_skills.resources.reach.navigate', return_value=Outcome('succeeded', 'arrived', (), {}, reached)) as move:
            result = resources.collect(runtime, 'minecraft:coal')
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence['inventory_delta'], 1)
        self.assertEqual(move.call_count, 1)
        self.assertEqual(result.last_observation.tick, 16)

    def test_arbitrary_numeric_pickup_baseline_is_not_public_api(self):
        with self.assertRaises(TypeError):
            resources.collect(FakeRuntime(observation()), 'minecraft:coal', baseline_count=0)

    def test_slow_mining_retains_owned_old_baseline_without_refreshed_capture(self):
        from support_core import Clock, Client
        from mdc_skills.core import Runtime
        clock = Clock(); client = Client(clock)
        def inventory_complete(state):
            state['player']['inventory_total'] = len(state['player']['inventory'])
            return state
        client.patch_state = inventory_complete
        with tempfile.TemporaryDirectory() as directory, Runtime(client, directory, clock=clock, sleeper=clock.sleep) as runtime:
            baseline = runtime.observe()
            captured = baseline.captured_at
            clock.sleep(5)  # A known completed mining operation can take longer than freshness.
            def after(state):
                inventory_complete(state)
                state['player']['inventory'][0].update(id='minecraft:coal', count=1, empty=False)
                return state
            client.patch_state = after
            result = resources._collect(runtime, 'minecraft:coal', baseline=baseline)
            self.assertTrue(result.ok, result.reason)
            self.assertEqual(baseline.captured_at, captured)
            self.assertGreater(clock() - captured, .8)
            self.assertEqual(client.action_count, 0)

    def test_tampered_owned_old_baseline_cannot_become_collection_evidence(self):
        from support_core import Clock, Client
        from mdc_skills.core import Runtime
        clock = Clock(); client = Client(clock)
        client.patch_state = lambda s: (s['player'].update(inventory_total=36) or s)
        with tempfile.TemporaryDirectory() as directory, Runtime(client, directory, clock=clock, sleeper=clock.sleep) as runtime:
            baseline = runtime.observe()
            baseline.player['inventory'][0]['count'] = 1
            with self.assertRaisesRegex(SkillError, 'historical_observation_modified'):
                resources._collect(runtime, 'minecraft:coal', baseline=baseline)


if __name__ == '__main__': unittest.main()
