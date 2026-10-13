"""P3 deterministic policy/semantic fixtures. These are not gameplay evidence."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mdc_skills.core import Outcome, SkillError
from mdc_skills import container, inventory, interaction_goals
from mdc_skills.stack_selector import selected_rows
from mdc_toolbox.bindings import inventory as binding, interaction
from mdc_toolbox.contracts import ToolboxError, validate_schema
from test_reach_inventory_resources import observation, stack, cell, FakeRuntime


def storage_observation(source_count=8, destination_count=0, *, kind='ChestMenu', component='stone'):
    count = {'ChestMenu': 27, 'HopperMenu': 5, 'DispenserMenu': 9, 'ShulkerBoxMenu': 27}[kind]
    obs = observation(entries={0: stack('minecraft:stone', destination_count, component=component)
                               if destination_count else stack()})
    obs.state['screen_open'] = True
    rows = [{'menu_index': i, 'slot_index': i, 'container_slot': i, 'player_inventory': False,
             'active': True, 'item': stack('minecraft:stone', source_count, component=component) if i == 0 else stack()}
            for i in range(count)]
    # Deliberately different menu and inventory numbering; never infer one from the other.
    for index in list(range(9, 36)) + list(range(9)):
        i = len(rows)
        rows.append({'menu_index': i, 'slot_index': i, 'container_slot': index,
                     'inventory_index': index, 'player_inventory': True, 'active': True,
                     'item': copy.deepcopy(obs.player['inventory'][index])})
    obs.state['menu'].update(menu_class=container.PREFIX + kind, container_id=7, state_id=11,
                             slots=rows, slots_total=len(rows), slots_returned=len(rows))
    return obs


def target_slot(obs, inventory_index=0):
    return next(row['menu_index'] for row in obs.state['menu']['slots']
                if row.get('inventory_index') == inventory_index)


def resized(value, count):
    if not count:
        return stack()
    result = copy.deepcopy(value)
    result.update(count=count, empty=False, item_fingerprint=value['component_fingerprint'] + '/' + str(count) + '/0')
    return result


class ClickRuntime:
    """Independent small pickup model and native expected-state guard simulation."""
    def __init__(self, obs, *, unknown_at=None, corrupt=None, revision_race=False):
        self.current = copy.deepcopy(obs)
        self.commands = []
        self.unknown_at, self.corrupt, self.revision_race = unknown_at, corrupt, revision_race
        self.mutations = 0
    def observe(self, **kwargs):
        return copy.deepcopy(self.current)
    def execute(self, skill, command, verify, *, before, **kwargs):
        self.commands.append(copy.deepcopy(command))
        number = len(self.commands)
        rid = 'p3-click-' + str(number)
        if self.unknown_at == number:
            return Outcome('unknown', 'synthetic_delivery_unknown', (rid,), {}, before)
        current = copy.deepcopy(self.current)
        menu = current.state['menu']
        if self.revision_race:
            menu['state_id'] += 1
        row = next(row for row in menu['slots'] if row['menu_index'] == command['slot'])
        guard_ok = (command['expected_menu_state_id'] == menu['state_id']
            and command['expected_slot_item']['item_fingerprint'] == row['item']['item_fingerprint']
            and command['expected_carried']['item_fingerprint'] == menu['carried']['item_fingerprint'])
        if not guard_ok:
            return Outcome('blocked', 'capability_menu_or_cursor_changed', (rid,), {}, before)
        self.mutations += 1
        carried, old = menu['carried'], row['item']
        if not carried['count']:
            row['item'], menu['carried'] = stack(), copy.deepcopy(old)
        else:
            amount = carried['count'] if command['button'] == 0 else 1
            row['item'] = resized(carried, old['count'] + amount)
            menu['carried'] = resized(carried, carried['count'] - amount)
        menu['state_id'] = (menu['state_id'] + 1) % 32768
        if row.get('player_inventory'):
            index = row['inventory_index']
            current.player['inventory'][index] = {**copy.deepcopy(row['item']), 'slot': index}
        if self.corrupt:
            self.corrupt(current, number)
        self.current = current
        valid = verify(before, current)
        return Outcome('succeeded' if valid else 'failed', 'observed' if valid else 'postcondition_not_observed',
                       (rid,), {'server_confirmed': False}, copy.deepcopy(current))
    def require_success(self, result):
        if not result.ok:
            raise SkillError(result.reason, status=result.status)
        return result.last_observation
    def result(self, skill, observations, **evidence):
        return Outcome('succeeded', 'goal_observed', (), {**evidence, 'server_confirmed': False}, list(observations)[-1])


class Control:
    def __init__(self, stop_at=None):
        self.events, self.calls, self.stop_at = [], 0, stop_at
    def checkpoint(self):
        self.calls += 1
        if self.calls == self.stop_at:
            raise SkillError('cancel_requested', status='cancelled')
    def emit(self, event, payload):
        self.events.append((event, payload))


def args(obs, quantity=8, **kwargs):
    return dict(container_id=7, menu_state_id=11, source_slot=0,
                destination_slot=target_slot(obs), quantity=quantity, **kwargs)


class ContainerTests(unittest.TestCase):
    def test_full_withdraw_has_two_verified_clicks_and_exact_mapping(self):
        obs = storage_observation(); runtime = ClickRuntime(obs)
        result = container.transfer(runtime, operation='withdraw', **args(obs))
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.evidence['performed_clicks'], 2)
        self.assertEqual(result.request_ids, ('p3-click-1', 'p3-click-2'))
        self.assertEqual(runtime.current.player['inventory'][0]['count'], 8)
        self.assertEqual(runtime.commands[1]['slot'], 54)
        self.assertTrue(result.evidence['total_conserved'])
    def test_partial_deposit_preserves_remainder(self):
        obs = storage_observation(source_count=0, destination_count=8)
        runtime = ClickRuntime(obs)
        result = container.transfer(runtime, operation='deposit', **{
            **args(obs, 3), 'source_slot': target_slot(obs), 'destination_slot': 0})
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(runtime.current.player['inventory'][0]['count'], 5)
        self.assertEqual(runtime.current.state['menu']['slots'][0]['item']['count'], 3)
        self.assertEqual(len(runtime.commands), 5)
    def test_split_and_merge_preserve_exact_components(self):
        obs = storage_observation(component='enchanted-stone'); runtime = ClickRuntime(obs)
        split = container.transfer(runtime, operation='split', **args(obs, 3))
        self.assertTrue(split.ok, split.reason)
        current = runtime.current
        merged = container.transfer(runtime, operation='merge', container_id=7,
            menu_state_id=current.state['menu']['state_id'], source_slot=target_slot(current),
            destination_slot=0, quantity=3)
        self.assertTrue(merged.ok, merged.reason)
        self.assertEqual(current.state['menu']['slots'][0]['item']['component_fingerprint'], 'enchanted-stone')
        self.assertEqual(runtime.current.state['menu']['slots'][0]['item']['count'], 8)
    def test_each_supported_external_menu(self):
        for kind in ('ChestMenu', 'HopperMenu', 'DispenserMenu', 'ShulkerBoxMenu'):
            with self.subTest(kind=kind):
                obs = storage_observation(kind=kind)
                self.assertTrue(container.transfer(ClickRuntime(obs), **args(obs)).ok)
    def test_unknown_click_is_not_replayed_and_original_ids_retained(self):
        obs = storage_observation(); runtime = ClickRuntime(obs, unknown_at=2)
        result = container.transfer(runtime, **args(obs))
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(len(runtime.commands), 2)
        self.assertEqual(result.request_ids, ('p3-click-1', 'p3-click-2'))
        self.assertEqual(result.evidence['last_observed_carried']['count'], 8)
        self.assertFalse(result.evidence['auto_cleanup_attempted'])
    def test_cancel_with_cursor_keeps_partial_facts_no_cleanup(self):
        obs = storage_observation(); runtime = ClickRuntime(obs)
        result = container.transfer(runtime, control=Control(stop_at=3), **args(obs))
        self.assertEqual(result.status, 'cancelled')
        self.assertEqual(len(runtime.commands), 1)
        self.assertEqual(result.evidence['last_observed_carried']['count'], 8)
    def test_native_menu_revision_race_blocks_without_mutation_or_retry(self):
        obs = storage_observation(); runtime = ClickRuntime(obs, revision_race=True)
        result = container.transfer(runtime, **args(obs))
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(runtime.mutations, 0)
        self.assertEqual(len(runtime.commands), 1)
    def test_dispatch_without_semantic_effect_is_not_success(self):
        obs = storage_observation(); runtime = ClickRuntime(obs)
        runtime.execute = lambda skill, command, verify, before, **kw: Outcome(
            'succeeded' if verify(before, before) else 'failed', 'postcondition_not_observed', ('dispatch-only',), {}, before)
        self.assertFalse(container.transfer(runtime, **args(obs)).ok)
    def test_unrelated_component_change_stops_before_next_click(self):
        def corrupt(obs, number):
            obs.state['menu']['slots'][1]['item'] = stack('minecraft:stone', 1, component='foreign')
        obs = storage_observation(); runtime = ClickRuntime(obs, corrupt=corrupt)
        result = container.transfer(runtime, **args(obs))
        self.assertFalse(result.ok)
        self.assertEqual(len(runtime.commands), 1)
    def assert_refused(self, obs, expected, arguments=None):
        runtime = ClickRuntime(obs)
        with self.assertRaisesRegex(SkillError, expected):
            container.transfer(runtime, **(arguments or args(obs)))
        self.assertFalse(runtime.commands)
    def test_full_destination_refuses_before_pickup(self):
        obs = storage_observation(destination_count=60)
        self.assert_refused(obs, 'destination_full')
    def test_different_component_refuses_before_pickup(self):
        obs = storage_observation(destination_count=1)
        index = target_slot(obs)
        obs.state['menu']['slots'][index]['item'] = stack('minecraft:stone', 1, component='other')
        obs.player['inventory'][0] = {**stack('minecraft:stone', 1, component='other'), 'slot': 0}
        self.assert_refused(obs, 'components_differ')
    def test_occupied_cursor_refuses(self):
        obs = storage_observation(); obs.state['menu']['carried'] = stack('minecraft:stone', 1)
        self.assert_refused(obs, 'cursor_not_empty')
    def test_caller_stale_revision_refuses(self):
        obs = storage_observation(); self.assert_refused(obs, 'revision_changed', {**args(obs), 'menu_state_id': 10})
    def test_slot_rule_disallow_refuses(self):
        obs = storage_observation(); obs.state['menu']['slots'][target_slot(obs)]['may_place'] = False
        self.assert_refused(obs, 'rules_disallow')
    def test_nested_shulker_deposit_refuses(self):
        obs = storage_observation(source_count=0, destination_count=1, kind='ShulkerBoxMenu')
        value = stack('minecraft:red_shulker_box', 1); value['max_stack_size'] = 1
        obs.player['inventory'][0] = {**value, 'slot': 0}
        obs.state['menu']['slots'][target_slot(obs)]['item'] = value
        self.assert_refused(obs, 'nested_shulker', {**args(obs, 1), 'source_slot': target_slot(obs), 'destination_slot': 0})
    def test_unknown_subclass_and_special_menu_refuse(self):
        for kind in ('modded.ChestMenu', container.PREFIX + 'FurnaceMenu'):
            obs = storage_observation(); obs.state['menu']['menu_class'] = kind
            self.assert_refused(obs, 'menu_unsupported')
    def test_duplicate_mapping_refuses(self):
        obs = storage_observation(); obs.state['menu']['slots'][1]['menu_index'] = 0
        self.assert_refused(obs, 'mapping_invalid')
    def test_menu_inventory_disagreement_refuses(self):
        obs = storage_observation(); obs.player['inventory'][0]['item_fingerprint'] = 'wrong'
        self.assert_refused(obs, 'menu_inventory_disagree')
    def test_missing_capacity_refuses(self):
        obs = storage_observation(); del obs.state['menu']['slots'][0]['item']['max_stack_size']
        self.assert_refused(obs, 'capacity')
    def test_local_action_budget_preflights_whole_sequence(self):
        obs = storage_observation(); self.assert_refused(obs, 'budget_insufficient', args(obs, 3, max_actions=4))
    def test_shared_budgets_refuse_before_source_pickup(self):
        from mdc_toolbox.budgets import SharedBudget
        for budget, reason in [({'max_actions': 2, 'max_observations': 100}, 'shared_action'),
                               ({'max_actions': 10, 'max_observations': 10}, 'shared_observation')]:
            obs = storage_observation(); runtime = ClickRuntime(obs); control = Control()
            control.budget = SharedBudget(budget, 60, wall_clock=lambda: 0, clock=lambda: 0)
            with self.assertRaisesRegex(SkillError, reason):
                container.transfer(runtime, control=control, **args(obs))
            self.assertFalse(runtime.commands)
    def test_exact_selector_mismatch_refuses(self):
        obs = storage_observation(); self.assert_refused(obs, 'selector_mismatch', args(obs, selector={'component_fingerprint': 'wrong'}))


class BindingTests(unittest.TestCase):
    def test_closed_schema_rejects_callback_raw_action_and_bool_slot(self):
        runtime = ClickRuntime(storage_observation()); control = Control()
        for capability, arguments in [('select_hotbar', {'slot': True}),
                ('consume', {'item_id': 'minecraft:potion'}),
                ('container_move', {**args(runtime.current), 'command': {'action': 'click_slot'}})]:
            with self.assertRaises(ToolboxError): binding.invoke(capability, runtime, arguments, control)
        with self.assertRaises(ToolboxError):
            interaction.invoke('interact', runtime, {'target': {'x': 0, 'y': 64, 'z': 0}, 'verify': 'anything'}, control)
        self.assertFalse(runtime.commands)
    def test_binding_dispatch_uses_real_container_and_emits_progress(self):
        obs = storage_observation(); control = Control(); runtime = ClickRuntime(obs)
        result = binding.invoke('container_withdraw', runtime, args(obs), control)
        self.assertTrue(result.ok)
        self.assertEqual(len(runtime.commands), 2)
        self.assertEqual(control.events[0][0], 'container_click_observed')
    def test_catalog_definitions_have_no_live_claim_and_exact_sources(self):
        values = binding.definitions() + interaction.definitions()
        self.assertEqual(len(values), 11)
        for value in values:
            self.assertEqual(value['input_schema']['additionalProperties'], False)
            self.assertEqual(value['validation']['live'], 'not_run')
            self.assertFalse(value['resume_supported'])
            self.assertNotIn('runtime_available', value)
            self.assertTrue(all(len(f['sha256']) == 64 for f in value['source_fingerprints']))
    def test_potion_selector_chooses_matching_timed_effect(self):
        wrong = stack('minecraft:potion', 1, component='poison')
        right = stack('minecraft:potion', 1, component='fire-resistance')
        wrong.update(potion_effects_truncated=False, potion_effects=[{'id': 'minecraft:poison', 'duration_ticks': 100}])
        right.update(potion_effects_truncated=False, potion_effects=[{'id': 'minecraft:fire_resistance', 'duration_ticks': 100}])
        obs = observation(entries={0: wrong, 2: right})
        self.assertEqual(selected_rows(obs, 'minecraft:potion', {'effect_id': 'minecraft:fire_resistance'})[0]['slot'], 2)
        after = copy.deepcopy(obs); after.player['selected_slot'] = 2
        result = inventory.ensure_hotbar(FakeRuntime(obs, after), 'minecraft:potion', selector={'component_fingerprint': 'fire-resistance'})
        self.assertTrue(result.ok)
    def test_typed_menu_goal_requires_full_exact_class_and_open_screen(self):
        before = observation(); before.terrain['cells'].append(cell(1, 64, 3, 'minecraft:chest'))
        after = observation(); after.state['menu'].update(menu_class='modded.ChestMenu', container_id=8)
        after.state['screen_open'] = True
        rt = FakeRuntime(before, after)
        result = interaction_goals.interact(rt, {'x': 1, 'y': 64, 'z': 3},
            goal={'kind': 'menu_open', 'menu_class': container.PREFIX + 'ChestMenu'})
        self.assertFalse(result.ok)
        after.state['menu']['menu_class'] = container.PREFIX + 'ChestMenu'
        self.assertTrue(rt.verifier(before, after))
        after.state['screen_open'] = False
        self.assertFalse(rt.verifier(before, after))
    def test_block_state_goal_requires_block_identity_and_each_property(self):
        before = observation(); target = {'x': 1, 'y': 64, 'z': 3}
        old = cell(**target, item='minecraft:lever'); old['properties'] = {'powered': 'false'}
        before.terrain['cells'].append(old)
        after = copy.deepcopy(before); after.terrain['cells'][-1]['properties']['powered'] = 'true'
        rt = FakeRuntime(before, after)
        result = interaction_goals.interact(rt, target, goal={'kind': 'block_state',
            'block_id': 'minecraft:lever', 'properties': {'powered': 'true'}})
        self.assertTrue(result.ok)
        after.terrain['cells'][-1]['id'] = 'minecraft:stone'
        self.assertFalse(rt.verifier(before, after))


def player_menu_observation(entries=None):
    obs = observation(entries=entries)
    rows = [{'menu_index': i, 'slot_index': i, 'container_slot': max(0, i - 1),
             'player_inventory': False, 'active': True, 'item': stack()} for i in range(5)]
    obs.player['armor'] = [{**stack(), 'slot': slot} for slot in ('feet', 'legs', 'chest', 'head')]
    for inventory_index in [39, 38, 37, 36, *range(9, 36), *range(9), 40]:
        i = len(rows)
        rows.append({'menu_index': i, 'slot_index': i, 'container_slot': inventory_index,
                     'inventory_index': inventory_index, 'player_inventory': True, 'active': True,
                     'item': copy.deepcopy(inventory._inventory_item(obs, inventory_index))})
    obs.state['menu'].update(menu_class=container.PREFIX + 'InventoryMenu', slots=rows,
                            slots_total=len(rows), slots_returned=len(rows), state_id=11)
    return obs


class InventoryUseTests(unittest.TestCase):
    def test_closed_inventory_split_uses_real_topology_and_excludes_crafting(self):
        obs = player_menu_observation({0: stack('minecraft:stone', 8)})
        runtime = ClickRuntime(obs)
        result = container.transfer(runtime, operation='split', container_id=0, menu_state_id=11,
            source_slot=target_slot(obs), destination_slot=target_slot(obs, 1), quantity=3)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(runtime.current.player['inventory'][0]['count'], 5)
        self.assertEqual(runtime.current.player['inventory'][1]['count'], 3)
        runtime = ClickRuntime(obs)
        with self.assertRaisesRegex(SkillError, 'crafting_slot_disallowed'):
            container.transfer(runtime, container_id=0, menu_state_id=11,
                source_slot=target_slot(obs), destination_slot=0, quantity=3)
        self.assertFalse(runtime.commands)
    def test_closed_inventory_armor_endpoint_is_disallowed(self):
        obs = player_menu_observation({0: stack('minecraft:iron_helmet', 1)})
        runtime = ClickRuntime(obs)
        with self.assertRaisesRegex(SkillError, 'special_player_slot_disallowed'):
            container.transfer(runtime, container_id=0, menu_state_id=11,
                source_slot=target_slot(obs), destination_slot=5, quantity=1)
        self.assertFalse(runtime.commands)
    def test_armor_swap_verifies_both_equipped_and_returned_stack(self):
        helm = stack('minecraft:iron_helmet', 1, component='enchanted-helmet')
        prior = stack('minecraft:leather_helmet', 1, component='old-helmet')
        before = player_menu_observation({0: helm})
        before.player['armor'][3] = {**prior, 'slot': 'head'}
        before.state['menu']['slots'][5]['item'] = prior
        after = copy.deepcopy(before)
        after.player['armor'][3] = {**helm, 'slot': 'head'}
        after.player['inventory'][0] = {**prior, 'slot': 0}
        rt = FakeRuntime(before, after)
        result = inventory.equip(rt, 'minecraft:iron_helmet', slot='head',
                                 selector={'component_fingerprint': 'enchanted-helmet'})
        self.assertTrue(result.ok)
        after.player['inventory'][0] = {**stack(), 'slot': 0}
        self.assertFalse(rt.verifier(before, after))
    def test_offhand_swap_verifies_source_return(self):
        shield = stack('minecraft:shield', 1)
        old = stack('minecraft:torch', 5)
        before = player_menu_observation({10: shield})
        before.player['offhand'] = old; before.state['menu']['slots'][45]['item'] = old
        after = copy.deepcopy(before); after.player['offhand'] = shield
        after.player['inventory'][10] = {**old, 'slot': 10}
        after.state['menu']['slots'][10]['item'] = old
        rt = FakeRuntime(before, after)
        result = inventory.equip(rt, 'minecraft:shield', slot='offhand')
        self.assertTrue(result.ok)
        self.assertEqual(rt.commands[0]['button'], 40)
    def test_timed_potion_requires_bottle_and_effect(self):
        potion = stack('minecraft:potion', 1, component='fire-resistance')
        potion.update(potion_effects_truncated=False,
            potion_effects=[{'id': 'minecraft:fire_resistance', 'duration_ticks': 600}])
        before = observation(entries={0: potion})
        after = observation(entries={0: stack('minecraft:glass_bottle', 1)})
        after.player['effects'] = [{'id': 'minecraft:fire_resistance', 'amplifier': 0, 'duration_ticks': 590}]
        rt = FakeRuntime(before, after)
        result = inventory.consume(rt, 'minecraft:potion', effect_id='minecraft:fire_resistance')
        self.assertTrue(result.ok)
        after.player['inventory'][0] = {**stack(), 'slot': 0}
        self.assertFalse(rt.verifier(before, after))
    def test_milk_requires_effect_removal_and_bucket(self):
        before = observation(entries={0: stack('minecraft:milk_bucket', 1)})
        before.player['effects'] = [{'id': 'minecraft:poison', 'duration_ticks': 300}]
        after = observation(entries={0: stack('minecraft:bucket', 1)})
        rt = FakeRuntime(before, after)
        self.assertTrue(inventory.consume(rt, 'minecraft:milk_bucket').ok)
        after.player['effects'] = [{'id': 'minecraft:poison', 'duration_ticks': 280}]
        self.assertFalse(rt.verifier(before, after))
    def test_instant_and_mixed_potions_refuse_before_mutation(self):
        potion = stack('minecraft:potion', 1)
        potion.update(potion_effects_truncated=False,
            potion_effects=[{'id': 'minecraft:instant_health', 'duration_ticks': 1},
                            {'id': 'minecraft:fire_resistance', 'duration_ticks': 600}])
        for goal in ('minecraft:instant_health', 'minecraft:fire_resistance'):
            rt = FakeRuntime(observation(entries={0: potion}))
            with self.assertRaises(SkillError):
                inventory.consume(rt, 'minecraft:potion', effect_id=goal)
            self.assertFalse(rt.commands)
    def test_unknown_use_never_retries(self):
        before = observation(entries={0: stack('minecraft:bread', 3)})
        after = observation(entries={0: stack('minecraft:bread', 2)}); after.player['food'] = 20
        rt = FakeRuntime(before, after, outcome='unknown')
        with self.assertRaises(SkillError) as raised:
            inventory.consume(rt, 'minecraft:bread')
        self.assertEqual(raised.exception.status, 'unknown')
        self.assertEqual(len(rt.commands), 1)


class RealRuntimeBindingTests(unittest.TestCase):
    def make_client(self, clock):
        from support_core import Client
        fixture = ClickRuntime(storage_observation())
        class ContainerClient(Client):
            def __init__(self):
                super().__init__(clock)
                self.patch_state = self.container_state
            def container_state(self, base):
                snapshot = copy.deepcopy(fixture.current.state)
                base['player'].update(snapshot['player'])
                base.update(menu=snapshot['menu'], screen_open=True)
                return base
            def wait(self, request_id, timeout):
                command = self.results[request_id]
                if command['op'] == 'action' and self.mode != 'pending':
                    fixture.execute('fixture', command, lambda old, new: True, before=fixture.current)
                return super().wait(request_id, timeout)
        return ContainerClient(), fixture
    def test_binding_real_runtime_two_stable_reads_and_durable_original_ids(self):
        import tempfile
        from support_core import Clock
        from mdc_skills.core import Runtime
        clock = Clock(); client, model = self.make_client(clock)
        with tempfile.TemporaryDirectory() as directory:
            with Runtime(client, directory, clock=clock, sleeper=clock.sleep) as runtime:
                result = binding.invoke('container_withdraw', runtime, args(model.current), Control())
                self.assertTrue(result.ok, result.reason)
                self.assertEqual(client.action_count, 2)
                self.assertGreaterEqual(len(result.request_ids), 6)
                self.assertIsNone(runtime.pending_request_id)
                self.assertEqual(model.current.player['inventory'][0]['count'], 8)
                self.assertTrue(result.evidence['total_conserved'])
    def test_real_runtime_unknown_delivery_latches_without_cleanup(self):
        import tempfile
        from support_core import Clock
        from mdc_skills.core import Runtime
        clock = Clock(); client, model = self.make_client(clock)
        client.fail_after_submit = True
        with tempfile.TemporaryDirectory() as directory:
            with Runtime(client, directory, clock=clock, sleeper=clock.sleep) as runtime:
                result = binding.invoke('container_withdraw', runtime, args(model.current), Control())
                self.assertEqual(result.status, 'unknown')
                self.assertEqual(client.action_count, 1)
                self.assertIsNotNone(runtime.pending_request_id)
                self.assertIn(runtime.pending_request_id, result.request_ids)
                self.assertFalse(result.evidence['auto_cleanup_attempted'])


if __name__ == '__main__': unittest.main()
