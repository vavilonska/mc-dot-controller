"""Offline deterministic worlds exercise real tactics and native command wiring.

These tests are not game/loot-rate acceptance. The model independently supplies
health, drops and inventory; the goal must prove its own semantic postconditions.
"""
from copy import deepcopy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mdc_skills import combat_goals as goals, inventory, resources
from mdc_skills.core import Observation, Outcome, SkillError
from test_reach_inventory_resources import observation, cell, stack


def mob(kind='spider', *, x=2.5, z=.5, health=8, uid='mob-one', ident=7, **extra):
    size = 2.9 if kind == 'enderman' else 1.8
    value = dict(type='minecraft:' + kind, uuid=uid, entity_id=ident, alive=health > 0,
        health=health, x=x, y=64, z=z, aggressive=False, line_of_sight=True,
        bounding_box={'min': dict(x=x-.3, y=64, z=z-.3),
                      'max': dict(x=x+.3, y=64+size, z=z+.3)})
    if kind == 'creeper':
        value['creeper'] = dict(ignited=False, powered=False, swell_ticks=0, swell_direction=-1,
                               fuse_ticks=30, explosion_radius=3)
        for key in tuple(extra):
            if key in value['creeper']:
                value['creeper'][key] = extra.pop(key)
    if kind == 'blaze':
        value['blaze'] = {'charged': extra.pop('charged', False)}
    value.update(extra)
    return value


def item_drop(item_id, *, x=2.5, uid='drop-one', ident=99):
    value = mob('item', x=x, uid=uid, ident=ident)
    value['item'] = stack(item_id, 1)
    return value


def shield_stack():
    return {**stack('minecraft:shield', 1), 'max_damage': 336, 'damage': 0}


class World:
    """A tiny independent endpoint model, never a real gateway or resident."""
    def __init__(self, mobs=(), *, roof=False, selected=0, stock=None, loot=None,
                 auto_pickup=False, unknown_at=None, damage=8):
        self.time, self.tick, self.commands, self.options = 1.2, 10, [], []
        self.base = observation(entries=stock or {0: stack('minecraft:iron_sword', 1),
            1: stack('minecraft:bow', 1), 2: stack('minecraft:arrow', 32)}, selected=selected)
        self.base.player.update(**{key: False for key in goals.threats.ENVIRONMENT_FLAGS})
        self.base.player['alive'] = True
        self.base.player['uuid'] = 'player'
        self.base.state['combat_capabilities'] = dict(schema_version=1,
            encounter_route_guard_schema_version=1, shulker_open_shell_guard_schema_version=1,
            caller_health_reserve_guard_schema_version=1)
        self.base.player['enderman_shelter'] = {'schema_version': 1, 'safe': roof, 'roof_y': 66}
        self.base.state['nearby'].update(entities=list(deepcopy(mobs)), total=len(mobs), returned=len(mobs))
        self.base.terrain['cells'] = [cell(x, y, z, 'minecraft:stone' if y == 63 else 'minecraft:air')
            for x in range(-4, 5) for z in range(-4, 5) for y in range(63, 68)]
        if roof:
            for c in self.base.terrain['cells']:
                if c['y'] == 66 and abs(c['x']) <= 1 and abs(c['z']) <= 1:
                    c.update(cell(c['x'], c['y'], c['z'], 'minecraft:stone'))
        self.loot, self.auto_pickup, self.unknown_at, self.damage = loot, auto_pickup, unknown_at, damage
        self.context_override = None
        self.freeze_tick = False
        self.drop_counter = 100
        self.on_execute = None

    def clock(self):
        return self.time

    def sleeper(self, seconds):
        self.time += seconds

    def add(self, item_id, amount=1):
        row = next((r for r in self.base.player['inventory'] if r['id'] == item_id), None)
        if row is None:
            row = next(r for r in self.base.player['inventory'] if r['empty'])
        slot = row['slot']
        row.update(stack(item_id, row['count'] + amount), slot=slot)

    def observe(self, **kwargs):
        if not self.freeze_tick:
            self.tick += 1
        state, terrain = deepcopy(self.base.state), deepcopy(self.base.terrain)
        state['world']['game_time'] = self.tick
        state['capability_guard'] = dict(schema_version=1, source_tick=self.tick, source_nano='100000000000')
        state['nearby']['returned'] = state['nearby']['total'] = len(state['nearby']['entities'])
        for row in state['nearby']['entities']:
            if row['type'] == 'minecraft:enderman':
                row.setdefault('native_living', dict(schema_version=1, known=True, source='integrated_server_tick',
                    reason='observed', entity_uuid=row['uuid'], entity_id=row['entity_id'], entity_type=row['type'],
                    world_generation='world', dimension='minecraft:overworld', player_uuid='player',
                    sample_tick=self.tick, source_tick=self.tick, sample_nano='100000000000',
                    source_nano='99950000000', sample_age_ms=50, alive=row['alive'],
                    coverage_complete=True, inspected=len(state['nearby']['entities']),
                    aggressive=row.get('aggressive'), current_target_known=True, current_target=None))
        state['player']['mainhand'] = next(r for r in state['player']['inventory']
                                          if r['slot'] == state['player']['selected_slot'])
        p = state['player']
        p['eye_position'] = dict(x=p['x'], y=p['y']+1.62, z=p['z'])
        terrain.update(source_tick=self.tick, last_tick=self.tick, capture_started_mono=self.time,
                       capture_finished_mono=self.time)
        return Observation(state, terrain if kwargs.get('terrain') else None, {}, self.tick,
                           self.context_override or self.base.context, self.time, 'read-' + str(self.tick))

    def execute(self, skill, command, verify, **options):
        self.commands.append(deepcopy(command)); self.options.append(options)
        rid = 'action-' + str(len(self.commands))
        if self.unknown_at == len(self.commands):
            return Outcome('unknown', 'synthetic_unknown', (rid,), {}, options['before'])
        action = command['action']
        if action == 'select_hotbar':
            self.base.player['selected_slot'] = command['hotbar_slot']
        elif action == 'follow_path':
            self.base.player.update({k: command['waypoints'][-1][k] for k in ('x', 'y', 'z')})
            for row in list(self.base.state['nearby']['entities']):
                if row['type'] == 'minecraft:item' and math.dist(goals.threats.position(row),
                        goals.threats.position(self.base.player)) < .8:
                    self.add(row['item']['id'], row['item']['count'])
                    self.base.state['nearby']['entities'].remove(row)
        elif action in ('attack_entity', 'shoot_entity'):
            target = next(r for r in self.base.state['nearby']['entities'] if r['uuid'] == command['target_uuid'])
            old_health = target['health']
            target['health'] = max(0, target['health'] - self.damage)
            target['alive'] = target['health'] > 0
            if not target['alive'] and self.loot:
                if self.auto_pickup:
                    self.add(self.loot)
                else:
                    self.drop_counter += 1
                    self.base.state['nearby']['entities'].append(item_drop(self.loot,
                        x=target['x'], uid='drop-' + str(self.drop_counter), ident=self.drop_counter))
            if command.get('blaze_safety_mode') == 'shield_window':
                self.base.state['client_action'] = dict(action_id='native-' + rid, action_session='session',
                    action=action, status='succeeded', result={'target_action':dict(target_uuid=target['uuid'],
                    target_entity_id=target['entity_id'], target_type=target['type'], target_initial_health=old_health,
                    target_min_observed_health=target['health'], target_dead_observed=not target['alive'],
                    observation_tick=self.tick, shield_window=True, pre_cover_saw_charge=True,
                    pre_cover_complete=True, shield_raised=True, shield_released=True,
                    shield_blocking_observed=True, cover_ticks=20, risk_remaining=False)})
        else:
            raise AssertionError('unmodeled native action: ' + action)
        if self.on_execute:
            self.on_execute(command)
        after = self.observe(terrain=True)
        passed = verify(options['before'], after)
        return Outcome('succeeded' if passed else 'failed', 'observed' if passed else 'no_semantic_change',
                       (rid,), {}, after)

    def result(self, skill, observations=(), **evidence):
        values = list(observations)
        return Outcome('succeeded', skill, tuple(o.request_id for o in values),
                       {**evidence, 'server_confirmed': False}, values[-1])

    def require_success(self, result):
        if not result.ok:
            raise SkillError(result.reason, status=result.status)
        return result.last_observation


class SpeciesTests(unittest.TestCase):
    def test_spider_selected_without_uuid_and_kill_requires_real_health(self):
        rt = World([mob()])
        result = goals.defeat_nearby(rt, 'minecraft:spider')
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.evidence['defeated_targets'][0]['uuid'], 'mob-one')
        self.assertEqual(rt.commands[0]['action'], 'attack_entity')
        self.assertEqual(rt.options[0]['stable_samples'], 2)
        self.assertFalse(result.evidence['server_confirmed'])

    def test_zero_damage_receipt_is_failure_and_never_replayed(self):
        rt = World([mob()], damage=0)
        result = goals.defeat_nearby(rt, 'minecraft:spider', max_actions=30)
        self.assertFalse(result.ok)
        self.assertEqual(len(rt.commands), 1)

    def test_target_disappearance_or_reused_identity_never_counts_as_death(self):
        for changed in ('gone', 'reuse'):
            rt = World([mob()])
            def mutate(command):
                if changed == 'gone':
                    rt.base.state['nearby']['entities'].clear()
                else:
                    rt.base.state['nearby']['entities'][0]['entity_id'] = 600
            rt.on_execute = mutate
            result = goals.defeat_nearby(rt, 'minecraft:spider')
            self.assertFalse(result.ok)
            self.assertIn(result.reason, ('no_semantic_change', 'mob_target_identity_changed'))
            self.assertEqual(len(rt.commands), 1)

    def test_enderman_uses_observed_two_block_height_roof(self):
        rt = World([mob('enderman')], roof=True)
        result = goals.defeat_nearby(rt, 'minecraft:enderman')
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(rt.commands[0]['enderman_shelter_required'])

    def test_enderman_selects_and_reaches_existing_roof_from_geometry(self):
        rt = World([mob('enderman')], roof=True)
        rt.base.player['x'] = -2.5
        rt.base.player['armor'] = [{'slot':'head', **stack('minecraft:carved_pumpkin',1)}]
        result = goals.defeat_nearby(rt, 'minecraft:enderman')
        self.assertTrue(result.ok, result.reason)
        self.assertEqual([c['action'] for c in rt.commands], ['follow_path','follow_path','attack_entity'])
        self.assertEqual(rt.base.player['x'], .5)
        rt = World([mob('enderman')], roof=True)
        rt.base.player['x'] = -2.5
        result = goals.defeat_nearby(rt, 'minecraft:enderman')
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'enderman_shelter_approach_requires_pumpkin')
        self.assertFalse(rt.commands)

    def test_missing_partial_wet_or_unknown_roof_blocks_before_attack(self):
        for kind in ('missing', 'partial', 'wet', 'unknown', 'native_missing'):
            rt = World([mob('enderman')], roof=True)
            ceiling = next(c for c in rt.base.terrain['cells'] if (c['x'], c['y'], c['z']) == (1,66,1))
            if kind == 'missing':
                rt.base.terrain['cells'].remove(ceiling)
            elif kind == 'partial':
                ceiling['collision_bounds'] = [0, .5, 0, 1, 1, 1]
            elif kind == 'wet':
                ceiling['fluid'] = 'minecraft:water'
            elif kind == 'unknown':
                ceiling['known'] = False
            else:
                rt.base.player.pop('enderman_shelter')
            result = goals.defeat_nearby(rt, 'minecraft:enderman')
            self.assertFalse(result.ok, kind)
            self.assertFalse(any(c['action'] == 'attack_entity' for c in rt.commands))

    def test_creeper_ranged_distance_and_fuse_guard(self):
        rt = World([mob('creeper', x=13.5)], selected=1)
        result = goals.defeat_nearby(rt, 'minecraft:creeper')
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(rt.commands[0]['action'], 'shoot_entity')
        self.assertTrue(rt.commands[0]['creeper_safety_required'])
        for extra in ({'ignited': True}, {'swell_ticks': 1}, {'swell_direction': 1},
                      {'powered': True}, {'fuse_ticks': 20}, {'explosion_radius': 8}):
            rt = World([mob('creeper', x=13.5, **extra)], selected=1)
            result = goals.defeat_nearby(rt, 'minecraft:creeper')
            self.assertFalse(result.ok, extra)
            self.assertFalse(rt.commands, extra)

    def test_blaze_requires_observed_fire_resistance_before_shot(self):
        rt = World([mob('blaze', x=13.5)], selected=1)
        result = goals.defeat_nearby(rt, 'minecraft:blaze')
        self.assertFalse(result.ok)
        self.assertFalse(rt.commands)
        rt.base.player['effects'] = [{'id': 'minecraft:fire_resistance', 'duration_ticks': 600}]
        result = goals.defeat_nearby(rt, 'minecraft:blaze')
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(rt.commands[0]['fire_resistance_required'])

    def test_first_blaze_uses_actual_shield_window_without_brewing(self):
        rt = World([mob('blaze', x=17.5)], selected=1)
        rt.base.player['offhand'] = shield_stack()
        result = goals.defeat_nearby(rt, 'minecraft:blaze')
        self.assertTrue(result.ok, result.reason)
        command = rt.commands[0]
        self.assertEqual(command['blaze_safety_mode'], 'shield_window')
        self.assertEqual(command['expected_offhand_item'], rt.base.player['offhand'])
        self.assertEqual(command['min_health'], 18)
        self.assertEqual(command['timeout_ms'], 20000)
        self.assertNotIn('fire_resistance_required', command)

    def test_first_blaze_shield_mode_rejects_charge_fireballs_low_health_and_short_deadline(self):
        for variant in ('durability', 'fireball', 'health', 'deadline'):
            rt = World([mob('blaze', x=17.5, charged=variant == 'charged')], selected=1)
            rt.base.player['offhand'] = shield_stack()
            if variant == 'durability':
                rt.base.player['offhand']['max_damage'] = 63
            if variant == 'fireball':
                rt.base.state['nearby']['entities'].append(mob('small_fireball', x=20, uid='fire', ident=80))
            elif variant == 'health':
                rt.base.player['health'] = 18
            result = goals.defeat_nearby(rt, 'minecraft:blaze', timeout_seconds=1 if variant == 'deadline' else 120)
            self.assertFalse(result.ok, variant)
            self.assertFalse(rt.commands, variant)

    def test_flat_species_facts_rejected_in_favor_of_actual_native_nested_schema(self):
        for kind in ('creeper', 'blaze'):
            target = mob(kind, x=13.5)
            target.update(target.pop(kind))
            rt = World([target], selected=1)
            rt.base.player['effects'] = [{'id':'minecraft:fire_resistance','duration_ticks':600}]
            result = goals.defeat_nearby(rt, 'minecraft:' + kind)
            self.assertFalse(result.ok)
            self.assertFalse(rt.commands)

    def test_native_death_witness_requires_exact_fresh_action_and_target(self):
        target = mob('blaze', x=17.5)
        rt = World([target], selected=1)
        before = rt.observe(terrain=True)
        proof = dict(target_uuid=target['uuid'], target_entity_id=target['entity_id'],
            target_type=target['type'], target_initial_health=8, target_min_observed_health=0,
            target_dead_observed=True, observation_tick=before.tick)
        rt.base.state['client_action'] = dict(status='succeeded', action='shoot_entity', action_id='new-native',
            action_session='session', result={'target_action':proof})
        after = rt.observe(terrain=True)
        self.assertTrue(goals._native_death(before, after, target, 'shoot_entity'))
        for field, value in [('target_uuid','other'), ('target_entity_id',44), ('target_type','minecraft:spider'),
                ('target_dead_observed',False), ('observation_tick',before.tick-1),
                ('target_min_observed_health',1)]:
            changed = deepcopy(after)
            changed.state['client_action']['result']['target_action'][field] = value
            self.assertFalse(goals._native_death(before, changed, target, 'shoot_entity'), field)
        changed = deepcopy(after)
        changed.state['client_action']['action_session'] = 'other'
        self.assertFalse(goals._native_death(before, changed, target, 'shoot_entity'))

    def test_expired_corpse_succeeds_only_with_bound_native_death_witness(self):
        rt = World([mob('blaze', x=17.5)], selected=1)
        rt.base.player['offhand'] = shield_stack()
        def expire_corpse(command):
            target = rt.base.state['nearby']['entities'].pop()
            self.assertEqual(rt.base.state['client_action']['result']['target_action']['target_uuid'], target['uuid'])
        rt.on_execute = expire_corpse
        result = goals.defeat_nearby(rt, 'minecraft:blaze')
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(len(rt.commands), 1)

    def test_cave_spider_never_melee_and_poison_blocks(self):
        rt = World([mob('cave_spider', x=9.5)], selected=1)
        self.assertTrue(goals.defeat_nearby(rt, 'minecraft:cave_spider').ok)
        self.assertTrue(rt.commands[0]['poison_guard_required'])
        rt = World([mob('cave_spider', x=9.5)], selected=1)
        rt.base.player['effects'] = [{'id': 'minecraft:poison', 'duration_ticks': 30}]
        self.assertIn('poison', goals.defeat_nearby(rt, 'minecraft:cave_spider').reason)
        self.assertFalse(rt.commands)

    def test_other_hostile_blocks_while_species_target_selected(self):
        rt = World([mob(), mob('zombie', x=3.5, ident=8, uid='other')])
        result = goals.defeat_nearby(rt, 'minecraft:spider')
        self.assertFalse(result.ok)
        self.assertIn('non_target_threat', result.reason)
        self.assertFalse(rt.commands)


class BudgetTests(unittest.TestCase):
    def test_unknown_native_action_retains_exact_id_and_never_replays(self):
        rt = World([mob()], unknown_at=1)
        result = goals.defeat_nearby(rt, 'minecraft:spider', max_actions=200)
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.request_ids, ('action-1',))
        self.assertEqual(len(rt.commands), 1)

    def test_nested_equipment_consumes_same_action_budget(self):
        rt = World([mob('creeper', x=13.5)], selected=0)
        result = goals.defeat_nearby(rt, 'minecraft:creeper', max_actions=1)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'mob_action_budget_exhausted')
        self.assertEqual([c['action'] for c in rt.commands], ['select_hotbar'])

    def test_nested_action_deadline_and_clock_regression_stop(self):
        for time in (5.0, .1):
            rt = World([mob(health=30)])
            rt.on_execute = lambda command: setattr(rt, 'time', time)
            result = goals.defeat_nearby(rt, 'minecraft:spider', timeout_seconds=1)
            self.assertFalse(result.ok)
            self.assertEqual(len(rt.commands), 1)
            self.assertIn('deadline' if time > 1 else 'clock_regressed', result.reason)

    def test_context_rollover_stops_before_second_hit(self):
        rt = World([mob(health=30)])
        rt.on_execute = lambda command: setattr(rt, 'context_override', ('other','minecraft:overworld','player','session'))
        result = goals.defeat_nearby(rt, 'minecraft:spider')
        self.assertFalse(result.ok)
        self.assertEqual(len(rt.commands), 1)

    def test_absent_mobs_use_loaded_frontier_then_bounded_search_stop(self):
        rt = World()
        result = goals.defeat_nearby(rt, 'minecraft:spider', max_search_steps=1)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'mob_loaded_search_budget_exhausted')
        self.assertEqual(len(rt.commands), 1)
        self.assertEqual(rt.commands[0]['action'], 'follow_path')
        self.assertLessEqual(len(rt.commands[0]['waypoints']), 2)

    def test_unknown_frontier_does_not_invent_route(self):
        rt = World()
        for c in rt.base.terrain['cells']:
            if c['y'] == 63 and (c['x'], c['z']) != (0, 0):
                c['known'] = False
        result = goals.defeat_nearby(rt, 'minecraft:spider')
        self.assertFalse(result.ok)
        self.assertFalse(rt.commands)

    def test_forged_or_truncated_entity_snapshots_rejected(self):
        rt = World([mob()])
        rt.base.state['nearby']['truncated'] = True
        result = goals.defeat_nearby(rt, 'minecraft:spider')
        self.assertFalse(result.ok)
        self.assertFalse(rt.commands)
        rt = World([mob(), mob(ident=7, uid='second')])
        result = goals.defeat_nearby(rt, 'minecraft:spider')
        self.assertIn('duplicate', result.reason)
        self.assertFalse(rt.commands)

    def test_distance_budget_counts_diagonal_vertical_and_centering_lengths(self):
        for point, expected in [(dict(x=1.5,y=64,z=1.5), math.sqrt(2)),
                                (dict(x=1.5,y=65,z=.5), math.sqrt(2)),
                                (dict(x=.7,y=64,z=.5), .2)]:
            rt = World()
            bounded = goals._Bounded(rt, 2, 10)
            bounded.walk_remaining = expected - .01
            before = bounded.observe(terrain=True)
            with self.assertRaisesRegex(SkillError, 'walk_budget'):
                bounded.execute('test', {'action':'follow_path','waypoints':[point]},
                                lambda old,new: True, before=before)
            self.assertFalse(rt.commands)


class ResourceTests(unittest.TestCase):
    def test_real_drop_navigation_and_actual_inventory_delta(self):
        rt = World([mob('enderman')], roof=True, loot='minecraft:ender_pearl')
        result = goals.acquire_mob_drops(rt, 'minecraft:ender_pearl')
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.evidence['actual_total'], 1)
        self.assertEqual(result.evidence['inventory_delta'], 1)
        self.assertFalse(result.evidence['causal_drop_attribution'])
        self.assertEqual([c['action'] for c in rt.commands], ['attack_entity','follow_path'])
        self.assertIn('action-1', result.request_ids)
        self.assertIn('action-2', result.request_ids)

    def test_blaze_rod_autopickup_is_inventory_evidence_not_kill_claim(self):
        rt = World([mob('blaze', x=13.5)], selected=1, loot='minecraft:blaze_rod', auto_pickup=True)
        rt.base.player['effects'] = [{'id':'minecraft:fire_resistance','duration_ticks':600}]
        result = goals.hunt_resource(rt, 'minecraft:blaze_rod')
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.evidence['actual_total'], 1)
        self.assertEqual(len(rt.commands), 1)

    def test_verified_kill_with_no_drop_is_not_resource_success(self):
        rt = World([mob('enderman')], roof=True)
        result = goals.hunt_resource(rt, 'minecraft:ender_pearl', max_targets=1)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'mob_resource_target_budget_exhausted')
        self.assertEqual(len(rt.commands), 1)

    def test_zero_drop_target_is_not_replayed_and_next_target_is_discovered(self):
        rt = World([mob('enderman')], roof=True)
        def next_mob(command):
            if len(rt.commands) == 1:
                rt.base.state['nearby']['entities'].append(mob('enderman', uid='new-observed', ident=8))
                rt.loot, rt.auto_pickup = 'minecraft:ender_pearl', True
        rt.on_execute = next_mob
        result = goals.hunt_resource(rt, 'minecraft:ender_pearl', max_targets=2)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual([c['target_uuid'] for c in rt.commands], ['mob-one','new-observed'])
        self.assertEqual(result.evidence['defeated_targets'], 2)
        self.assertEqual(result.evidence['actual_total'], 1)

    def test_existing_observed_drop_needs_no_caller_target_or_weapon(self):
        rt = World([item_drop('minecraft:blaze_rod')], stock={0: stack('minecraft:stone', 1)})
        result = goals.hunt_resource(rt, 'minecraft:blaze_rod')
        self.assertTrue(result.ok, result.reason)
        self.assertEqual([c['action'] for c in rt.commands], ['follow_path'])

    def test_disappearing_drop_without_inventory_never_counts_as_pickup(self):
        rt = World([item_drop('minecraft:ender_pearl')])
        def remove_gain(command):
            for row in rt.base.player['inventory']:
                if row['id'] == 'minecraft:ender_pearl':
                    row.update(stack(), slot=row['slot'])
        rt.on_execute = remove_gain
        result = goals.hunt_resource(rt, 'minecraft:ender_pearl')
        self.assertFalse(result.ok)
        self.assertEqual(len(rt.commands), 1)

    def test_existing_total_still_needs_two_later_ticks(self):
        rt = World(stock={0: stack('minecraft:ender_pearl', 3)})
        result = goals.hunt_resource(rt, 'minecraft:ender_pearl', count=2)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.evidence['inventory_delta'], 0)
        self.assertFalse(rt.commands)
        rt.freeze_tick = True
        result = goals.hunt_resource(rt, 'minecraft:ender_pearl', count=2)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'mob_inventory_total_not_stable')

    def test_collection_and_equipment_do_not_escape_action_walk_budget(self):
        rt = World([mob('enderman')], roof=True, loot='minecraft:ender_pearl')
        result = goals.hunt_resource(rt, 'minecraft:ender_pearl', max_actions=1)
        self.assertFalse(result.ok)
        self.assertEqual(len(rt.commands), 1)
        rt = World([item_drop('minecraft:ender_pearl')])
        result = goals.hunt_resource(rt, 'minecraft:ender_pearl', max_walk_distance=0)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'mob_walk_budget_exhausted')
        self.assertFalse(rt.commands)


if __name__ == '__main__':
    unittest.main()
