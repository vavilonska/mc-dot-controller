"""Covered Enderman regression through real goals/public strike/IPC adapters.

Endpoint/game physics is a deterministic geometry model, not live Minecraft.
The full terrain fixture uses pinned vanilla float dimensions and actual full
cube/bottom-slab shapes. Native production pick/shelter code is unchanged.
"""
from copy import deepcopy
from dataclasses import replace
from itertools import product
import json
import math
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from mdc_skills import combat_goals as goals, threats
from mdc_skills.core import Observation, SkillError
from navigation_controller.fake import FakeWorld
from navigation_controller.terrain import Block
from resident_controller.transport import BridgeError
from support_core import NATIVE
import test_combat_contract_wire as combat_wire
from test_combat_contract_wire import CombatEndpoint, TARGET_UUID
from test_reach_inventory_resources import stack

PLAYER = dict(x=12.536393768248903, y=64, z=25.5)
TARGET = dict(x=10.5, y=64, z=25.5)
WIDTH, HEIGHT = 0.6000000238418579, 2.9000000953674316


def segment_box(start, end, low, high):
    """Independent inclusive slab clipping for this offline geometry fixture."""
    enter, leave = 0., 1.
    for a, b, lo, hi in zip(start, end, low, high):
        delta = b - a
        if delta == 0:
            if not lo <= a <= hi:
                return None
            continue
        near, far = sorted(((lo - a) / delta, (hi - a) / delta))
        enter, leave = max(enter, near), min(leave, far)
        if enter > leave:
            return None
    return enter


class CoveredWorld(FakeWorld):
    def __init__(self, obstruction=False):
        super().__init__()
        self.generation = '11111111-2222-4333-8444-555555555555'
        for x, z in product(range(11, 14), range(24, 27)):
            self.set(Block(x, 66, z), 'stone')
        for x, z in product(range(9, 12), range(24, 27)):
            self.set(Block(x, 67, z), 'stone')
            if (x, z) != (10, 25):
                self.set(Block(x, 64, z), 'stone_slab',
                    properties={'type': 'bottom', 'waterlogged': 'false'},
                    collision_bounds=[0, 0, 0, 1, .5, 1], full_top_support=False)
                self.set(Block(x, 63, z), 'dirt')
        if obstruction:
            self.set(Block(11, 65, 25), 'stone')

    def get(self, pos):
        value = super().get(pos)
        if pos not in self.overrides and pos.y == 63:
            value['id'] = 'minecraft:grass_block'
            value['properties'] = {'snowy': 'false'}
        if value.get('collision_empty') is True:
            value['collision_bounds'] = []
        return value

    def first_collision(self, start, end):
        hits = []
        for xyz in product(*(range(math.floor(min(a, b)), math.floor(max(a, b)) + 1)
                             for a, b in zip(start, end))):
            value = self.get(Block(*xyz))
            bounds = value.get('collision_bounds')
            if value.get('collision_empty') is True:
                continue
            assert bounds and len(bounds) == 6
            low = tuple(xyz[i] + bounds[i] for i in range(3))
            high = tuple(xyz[i] + bounds[i + 3] for i in range(3))
            fraction = segment_box(start, end, low, high)
            if fraction is not None:
                hits.append((fraction, xyz))
        return min(hits) if hits else None


class CoveredEndermanEndpoint(CombatEndpoint):
    def __init__(self, *, obstruction=False, mode='success'):
        super().__init__('enderman', x=TARGET['x'], mode=mode)
        self.world = CoveredWorld(obstruction)
        self.position = deepcopy(PLAYER)
        self.target.update(**TARGET, health=40, max_health=40, on_ground=True,
            velocity=dict(x=0, y=0, z=0),
            bounding_box={'min': dict(x=TARGET['x'] - WIDTH / 2, y=64, z=25.5 - WIDTH / 2),
                          'max': dict(x=TARGET['x'] + WIDTH / 2, y=64 + HEIGHT, z=25.5 + WIDTH / 2)})
        self.dispatches = 0
        self.native_failure = None

    def snapshot(self):
        value = super().snapshot()
        player = value['player']
        player['armor'] = [{'slot': 'head', **stack('minecraft:carved_pumpkin', 1)}]
        player['inventory'][0].update(stack('minecraft:diamond_sword', 1))
        player['mainhand'] = deepcopy(player['inventory'][0])
        player['entity_interaction_range'] = 3.0
        eye = threats.position(player['eye_position'])
        target_eye = (self.target['x'], self.target['y'] + 2.55, self.target['z'])
        for row in value['nearby']['entities']:
            row['line_of_sight'] = self.world.first_collision(eye, target_eye) is None
        return value

    def request(self, method, path, body=None):
        if path.startswith('/control/terrain?'):
            query = parse_qs(urlsplit(path).query)
            if 'radius' in query:
                origin = Block(*(math.floor(self.position[k]) for k in ('x', 'y', 'z')))
                pages = self.world.pages(origin=origin, radius=int(query['radius'][0]),
                    vertical=int(query['vertical'][0]), tick=self.tick,
                    limit=min(int(query.get('limit', ['128'])[0]), 512))
                for page in pages:
                    page.update(capability_page_schema_version=1, page_limit=int(query['limit'][0]))
                self.terrain_pages = iter(pages)
            value = next(self.terrain_pages)
            self.terrain_responses.append(deepcopy(value))
            return value
        if path != '/control/action':
            return super().request(method, path, body)
        self.posts.append((path, deepcopy(body)))
        assert body['action'] == 'attack_entity', body
        if self.mode == 'unknown':
            raise BridgeError('covered_melee_transport_unknown', uncertain=True)
        # Synthetic endpoint authority models unchanged native current geometry.
        # It never treats receipt success as target damage without a new snapshot.
        eye = (self.position['x'], self.position['y'] + 1.62, self.position['z'])
        low, high = (threats.position(self.target['bounding_box'][k]) for k in ('min', 'max'))
        aim = tuple((a + b) / 2 for a, b in zip(low, high))
        fraction = segment_box(eye, aim, low, high)
        distance = math.dist(eye, aim) * fraction if fraction is not None else math.inf
        obstruction = self.world.first_collision(eye, aim)
        failure = self.native_failure or ('exact_target_not_in_melee_reach'
            if obstruction is not None or distance > 3 else None)
        if failure:
            self.action = dict(action_schema_version=1, action_session=NATIVE,
                action_id=body['action_id'], action=body['action'], status='failed',
                reason=failure, result={'input_release_confirmed': True}, server_confirmed=False)
            return deepcopy(self.action)
        self.dispatches += 1
        initial = self.target['health']
        self.target['health'] -= 7
        self.action = dict(action_schema_version=1, action_session=NATIVE, action_id=body['action_id'],
            action=body['action'], status='running', reason='synthetic_melee_damage',
            result={'input_release_confirmed': True, 'target_action': dict(target_uuid=TARGET_UUID,
                target_entity_id=self.target['entity_id'], target_type=self.target['type'],
                target_initial_health=initial, target_min_observed_health=self.target['health'],
                target_dead_observed=False, observation_tick=self.tick, dispatches=1)},
            server_confirmed=False)
        return deepcopy(self.action)


def covered_model():
    """Full geometry with the existing deterministic action/semantic harness."""
    from test_combat_goals import World
    endpoint = CoveredEndermanEndpoint()
    endpoint.active = True
    state = endpoint.snapshot()
    state['world']['world_generation'] = 'world'
    state['player']['uuid'] = 'player'
    class CoveredModel(World):
        def observe(self, **kwargs):
            value = super().observe(**kwargs)
            return replace(value, raw={'state': value.state, 'terrain': value.terrain})
    runtime = CoveredModel(damage=7)
    terrain = deepcopy(runtime.base.terrain)
    terrain.update(origin=dict(x=12, y=64, z=25), radius=4, vertical=4,
        cells=[endpoint.world.get(Block(x, y, z))
               for x, y, z in product(range(8, 17), range(60, 69), range(21, 30))])
    runtime.base = Observation(state, terrain, {}, runtime.tick, runtime.base.context,
                               runtime.time, 'fixture')
    return runtime


class ShelteredEndermanPolicyTests(unittest.TestCase):
    def strike(self, runtime):
        hunt = goals._Hunt(runtime, 1, 30, 0, 0, 12)
        before = hunt.observe()
        target = hunt.select(before, 'minecraft:enderman')
        return hunt, before, target

    def assert_blocked(self, runtime, reason=None):
        hunt, before, target = self.strike(runtime)
        with self.assertRaises(SkillError) as caught:
            hunt.strike(before, target)
        if reason:
            self.assertIn(reason, caught.exception.reason)
        self.assertFalse(runtime.commands)
        self.assertEqual(hunt.rt.remaining, 1)

    def test_full_canonical_fixture_valid_torso_is_single_hit_not_kill(self):
        runtime = covered_model()
        hunt, before, target = self.strike(runtime)
        self.assertFalse(hunt.strike(before, target))
        self.assertEqual(len(runtime.commands), 1)
        self.assertIs(runtime.options[0]['before'], before)
        self.assertEqual(hunt.rt.remaining, 0)
        self.assertIs(target['line_of_sight'], False)

    def test_torso_obstacle_and_partial_shape_never_dispatch(self):
        for block_id, bounds in [('minecraft:stone', [0, 0, 0, 1, 1, 1]),
                                 ('minecraft:oak_slab', [0, 0, 0, 1, .5, 1])]:
            with self.subTest(block_id=block_id):
                runtime = covered_model()
                cell = next(c for c in runtime.base.terrain['cells']
                            if (c['x'], c['y'], c['z']) == (11, 65, 25))
                cell.update(id=block_id, air=False, collision_empty=False,
                            collision_bounds=bounds, full_top_support=False)
                self.assert_blocked(runtime, 'torso_corridor_not_clear')

    def test_missing_unknown_duplicate_malformed_or_wet_corridor_is_not_air(self):
        changes = [('status', 'unloaded'), ('known', False), ('collision_known', False),
                   ('collision_empty', False), ('id_truncated', True),
                   ('properties_truncated', True), ('properties', None),
                   ('fluid', 'minecraft:water'), ('fluid_truncated', True),
                   ('fluid_source', True), ('hazards', ['fire']),
                   ('collision_bounds', [0, 0, 0, 1, 1, 1]),
                   ('collision_bounds', [float('nan')]), ('x', True),
                   ('delete', None), ('duplicate', None)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                runtime = covered_model()
                cells = runtime.base.terrain['cells']
                cell = next(c for c in cells if (c['x'], c['y'], c['z']) == (11, 65, 25))
                if key == 'delete':
                    cells.remove(cell)
                elif key == 'duplicate':
                    cells.append(deepcopy(cell))
                else:
                    cell[key] = value
                self.assert_blocked(runtime)

    def test_partial_or_false_complete_terrain_rejects(self):
        for mutate in (lambda t: t.update(complete=False),
                       lambda t: t['cells'].pop(0),
                       lambda t: t.update(world_generation='other')):
            runtime = covered_model()
            mutate(runtime.base.terrain)
            self.assert_blocked(runtime)

    def test_eye_los_unknown_values_are_never_exception(self):
        for value in (None, 0, 1, 'false'):
            runtime = covered_model()
            runtime.base.state['nearby']['entities'][0]['line_of_sight'] = value
            self.assert_blocked(runtime, 'observed_mob_line_of_sight_required')

    def test_canonical_adult_bounds_and_actual_eye_and_reach_required(self):
        mutations = [
            lambda p, t: t.pop('bounding_box'),
            lambda p, t: t['bounding_box']['max'].update(y=65.45),
            lambda p, t: t['bounding_box']['max'].update(x=11.5),
            lambda p, t: t['bounding_box']['min'].update(x=float('nan')),
            lambda p, t: t.update(x=11.5),
            lambda p, t: p.pop('entity_interaction_range'),
            lambda p, t: p.update(entity_interaction_range=1),
            lambda p, t: p.update(entity_interaction_range=True),
            lambda p, t: p.update(entity_interaction_range=float('nan')),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                runtime = covered_model()
                mutate(runtime.base.player, runtime.base.state['nearby']['entities'][0])
                self.assert_blocked(runtime)

    def test_missing_or_nonfinite_observed_eye_never_dispatches(self):
        for mutate in (lambda p: p.pop('eye_position'),
                       lambda p: p['eye_position'].update(y=float('nan'))):
            runtime = covered_model()
            hunt, before, target = self.strike(runtime)
            mutate(before.player)
            with self.assertRaisesRegex(SkillError, 'position_unavailable'):
                hunt.strike(before, target)
            self.assertFalse(runtime.commands)

    def test_voxel_corner_tangent_obstacle_is_not_skipped(self):
        for obstructed in (False, True):
            with self.subTest(obstructed=obstructed):
                runtime = covered_model()
                runtime.base.player['x'] = 12.5
                row = runtime.base.state['nearby']['entities'][0]
                row['z'] -= 2
                for bounds in row['bounding_box'].values():
                    bounds['z'] -= 2
                if obstructed:
                    cell = next(c for c in runtime.base.terrain['cells']
                                if (c['x'], c['y'], c['z']) == (12, 65, 24))
                    cell.update(id='minecraft:stone', air=False, collision_empty=False,
                                collision_bounds=[0, 0, 0, 1, 1, 1], full_top_support=True)
                    self.assert_blocked(runtime, 'torso_corridor_not_clear')
                else:
                    hunt, before, target = self.strike(runtime)
                    self.assertFalse(hunt.strike(before, target))
                    self.assertEqual(len(runtime.commands), 1)

    def test_true_eye_los_enderman_keeps_exact_death_semantics_and_one_charge(self):
        runtime = covered_model()
        runtime.damage = 40
        runtime.base.state['nearby']['entities'][0]['line_of_sight'] = True
        hunt, before, target = self.strike(runtime)
        with patch.object(threats, 'strike', wraps=threats.strike) as public:
            self.assertTrue(hunt.strike(before, target))
            self.assertEqual(public.call_count, 1)
        self.assertEqual(len(runtime.commands), 1)
        self.assertEqual(hunt.rt.remaining, 0)

    def test_enderman_disappearance_requires_exact_native_death_for_both_los_values(self):
        for eye_los, witness_kind in product((True, False), ('exact', 'absent', 'wrong_target', 'old_tick')):
            with self.subTest(eye_los=eye_los, witness=witness_kind):
                runtime = covered_model()
                runtime.damage = 40
                runtime.base.state['nearby']['entities'][0]['line_of_sight'] = eye_los
                hunt, before, target = self.strike(runtime)
                def remove(command):
                    runtime.base.state['nearby']['entities'].clear()
                    if witness_kind == 'absent':
                        return
                    witness = dict(target_uuid=target['uuid'], target_entity_id=target['entity_id'],
                        target_type=target['type'], target_initial_health=40,
                        target_min_observed_health=0, target_dead_observed=True,
                        observation_tick=runtime.tick)
                    if witness_kind == 'wrong_target':
                        witness['target_uuid'] = 'different-target'
                    elif witness_kind == 'old_tick':
                        witness['observation_tick'] = before.tick - 1
                    runtime.base.state['client_action'] = dict(action_id='new-native-death',
                        action_session=before.context[3], action='attack_entity', status='succeeded',
                        result={'target_action': witness})
                runtime.on_execute = remove
                if witness_kind == 'exact':
                    self.assertTrue(hunt.strike(before, target))
                else:
                    with self.assertRaises(SkillError):
                        hunt.strike(before, target)
                self.assertEqual(len(runtime.commands), 1)
                self.assertEqual(hunt.rt.remaining, 0)

    def test_native_shelter_roof_station_health_and_environment_guards_remain(self):
        mutations = [lambda r: r.base.player['enderman_shelter'].update(safe=False),
                     lambda r: r.base.player['enderman_shelter'].update(schema_version=True),
                     lambda r: r.base.player['enderman_shelter'].update(roof_y=67),
                     lambda r: r.base.player.update(x=12.8),
                     lambda r: r.base.player.update(health=12),
                     lambda r: r.base.player.update(on_ground=False),
                     lambda r: r.base.player.update(in_water=True),
                     lambda r: r.base.state.update(screen_open=True)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                runtime = covered_model()
                mutate(runtime)
                self.assert_blocked(runtime)

    def test_extra_dangerous_entity_and_incomplete_raw_entities_still_block(self):
        from test_combat_goals import mob
        runtime = covered_model()
        runtime.base.state['nearby']['entities'].append(mob('zombie', x=13, z=25, ident=8, uid='other'))
        self.assert_blocked(runtime, 'non_target')
        runtime = covered_model()
        runtime.base.state['nearby']['truncated'] = True
        with self.assertRaisesRegex(SkillError, 'complete_entity_snapshot_required'):
            self.strike(runtime)
        self.assertFalse(runtime.commands)

    def test_other_species_eye_los_guards_remain_unchanged(self):
        from test_combat_goals import World, mob
        for kind, x in [('spider', 2.5), ('creeper', 13.5),
                        ('blaze', 13.5), ('cave_spider', 9.5)]:
            with self.subTest(kind=kind):
                runtime = World([mob(kind, x=x, line_of_sight=False)])
                if kind == 'blaze':
                    runtime.base.player['effects'] = [{'id': 'minecraft:fire_resistance', 'duration_ticks': 600}]
                hunt = goals._Hunt(runtime, 1, 30, 0, 0, 12)
                before = hunt.observe()
                with self.assertRaisesRegex(SkillError, 'observed_mob_line_of_sight_required'):
                    hunt.strike(before, hunt.select(before, 'minecraft:' + kind))
                self.assertFalse(runtime.commands)

    def test_ranged_enderman_remains_unsupported(self):
        runtime = covered_model()
        with self.assertRaisesRegex(SkillError, 'strike_target_unsupported'):
            threats.strike(runtime, TARGET_UUID, ranged=True)
        self.assertFalse(runtime.commands)

    def test_terrain_timestamp_and_game_tick_not_refreshed_by_proof(self):
        for kind in ('wall', 'tick', 'future'):
            runtime = covered_model()
            hunt, before, target = self.strike(runtime)
            if kind == 'wall':
                runtime.time += .81
            elif kind == 'tick':
                before.terrain['source_tick'] -= 6
            else:
                before.terrain['last_tick'] += 1
            with self.assertRaisesRegex(SkillError, 'enderman_melee_terrain_unavailable'):
                hunt.strike(before, target)
            self.assertFalse(runtime.commands)

    def test_goal_action_and_deadline_budgets_still_apply(self):
        for exhausted in ('actions', 'deadline'):
            runtime = covered_model()
            hunt, before, target = self.strike(runtime)
            if exhausted == 'actions':
                hunt.rt.remaining = 0
            else:
                hunt.rt.deadline = runtime.clock() - .01
            with self.assertRaisesRegex(SkillError, 'mob_.*(budget|deadline)'):
                hunt.strike(before, target)
            self.assertFalse(runtime.commands)


class ShelteredEndermanWireTests(unittest.TestCase):
    chain = combat_wire.CombatWireTests.chain
    native_posts = combat_wire.CombatWireTests.native_posts

    def hunt(self, runtime, *, actions=1):
        return goals._Hunt(runtime, actions, 30, 0, 0, 12)

    def test_covered_eye_los_goal_strike_reaches_public_native_wire(self):
        endpoint = CoveredEndermanEndpoint()
        with self.chain(endpoint) as (runtime, client):
            hunt = self.hunt(runtime)
            before = hunt.observe()
            target = hunt.select(before, 'minecraft:enderman')
            self.assertEqual(len(before.terrain['cells']), 729)
            self.assertIs(target['line_of_sight'], False)
            self.assertTrue(hunt.station(before, target))
            eye = threats.position(before.player['eye_position'])
            aim = tuple((target['bounding_box']['min'][k] + target['bounding_box']['max'][k]) / 2
                        for k in ('x', 'y', 'z'))
            self.assertEqual(endpoint.world.first_collision(eye, (10.5, 66.55, 25.5))[1], (11, 66, 25))
            self.assertIsNone(endpoint.world.first_collision(eye, aim))
            with patch.object(threats, 'strike', wraps=threats.strike) as public:
                self.assertFalse(hunt.strike(before, target), 'One modeled hit must not imply a kill')
                self.assertEqual(public.call_count, 1)
            command, = self.native_posts(endpoint)
            self.assertEqual(command['action'], 'attack_entity')
            self.assertTrue(command['enderman_shelter_required'])
            self.assertEqual(command['min_health'], 12)
            self.assertEqual(command['expected_held_item']['id'], 'minecraft:diamond_sword')
            self.assertEqual(command['capability_guard'], before.state['capability_guard'])
            self.assertEqual(endpoint.dispatches, 1)
            self.assertEqual(endpoint.target['health'], 33)
            self.assertEqual(hunt.rt.remaining, 0)
            self.assertIs(target['line_of_sight'], False)
            receipt = client.result(hunt.rt.ids[0])
            self.assertNotEqual(receipt['queue_request_id'], hunt.rt.ids[0])
            destination = os.environ.get('MDC_SHELTERED_LOS_CAPTURE')
            if destination:
                Path(destination).write_text(json.dumps({'scope': 'offline synthetic endpoint only',
                    'before_state': before.state, 'before_terrain': before.terrain,
                    'native_command': command, 'receipt': receipt,
                    'observed_health_after': endpoint.target['health']}, indent=2) + '\n')


    def test_torso_blocked_rejected_before_public_or_native_dispatch(self):
        endpoint = CoveredEndermanEndpoint(obstruction=True)
        with self.chain(endpoint) as (runtime, _):
            hunt = self.hunt(runtime)
            before = hunt.observe()
            with patch.object(threats, 'strike', wraps=threats.strike) as public:
                with self.assertRaisesRegex(SkillError, 'torso_corridor_not_clear'):
                    hunt.strike(before, hunt.select(before, 'minecraft:enderman'))
                self.assertEqual(public.call_count, 0)
            self.assertFalse(self.native_posts(endpoint))
            self.assertEqual(hunt.rt.remaining, 1)

    def test_public_before_preserves_runtime_ownership_fingerprint_and_latest(self):
        for kind, reason in [('foreign', 'observation_not_owned_by_current_runtime'),
                             ('modified', 'observation_modified_after_capture'),
                             ('superseded', 'newer_observation_invalidated_preflight'),
                             ('stale', 'preflight_observation_stale'),
                             ('replaced_terrain', 'enderman_melee_original_terrain_required'),
                             ('modified_terrain', 'observation_modified_after_capture')]:
            with self.subTest(kind=kind):
                endpoint = CoveredEndermanEndpoint()
                with self.chain(endpoint) as (runtime, _):
                    hunt = self.hunt(runtime)
                    before = hunt.observe()
                    if kind == 'foreign':
                        before = replace(before, _owner='different-runtime-owner')
                    elif kind == 'modified':
                        before.player['food'] -= 1
                    elif kind == 'stale':
                        before = replace(before, captured_at=before.captured_at - 1)
                    elif kind == 'replaced_terrain':
                        before = replace(before, terrain=deepcopy(before.terrain))
                    elif kind == 'modified_terrain':
                        before.terrain['cells'][0]['fixture_tamper'] = True
                    else:
                        runtime.observe(entity_radius=48)
                    with self.assertRaisesRegex(SkillError, reason):
                        hunt.strike(before, hunt.select(before, 'minecraft:enderman'))
                    self.assertFalse(self.native_posts(endpoint))

    def test_native_current_obstruction_or_teleport_rejects_and_never_retries(self):
        for kind in ('obstruction', 'teleport'):
            with self.subTest(kind=kind):
                endpoint = CoveredEndermanEndpoint()
                with self.chain(endpoint) as (runtime, _):
                    hunt = self.hunt(runtime, actions=2)
                    before = hunt.observe()
                    target = hunt.select(before, 'minecraft:enderman')
                    if kind == 'obstruction':
                        endpoint.world.set(Block(11, 65, 25), 'stone')
                    else:
                        endpoint.target['x'] -= 10
                        for bounds in endpoint.target['bounding_box'].values():
                            bounds['x'] -= 10
                    with self.assertRaisesRegex(SkillError, 'exact_target_not_in_melee_reach'):
                        hunt.strike(before, target)
                    self.assertEqual(len(self.native_posts(endpoint)), 1)
                    self.assertEqual(endpoint.dispatches, 0)
                    self.assertEqual(endpoint.target['health'], 40)
                    with self.assertRaises(SkillError):
                        hunt.strike(before, target)
                    self.assertEqual(len(self.native_posts(endpoint)), 1)

    def test_unknown_exact_one_post_latches_and_never_retries(self):
        endpoint = CoveredEndermanEndpoint(mode='unknown')
        with self.chain(endpoint) as (runtime, _):
            hunt = self.hunt(runtime, actions=2)
            before = hunt.observe()
            target = hunt.select(before, 'minecraft:enderman')
            with self.assertRaises(SkillError) as first:
                hunt.strike(before, target)
            self.assertEqual(first.exception.status, 'unknown')
            self.assertIsNotNone(runtime.pending_request_id)
            with self.assertRaises(SkillError):
                hunt.strike(before, target)
            self.assertEqual(len(self.native_posts(endpoint)), 1)
            self.assertEqual(endpoint.dispatches, 0)


if __name__ == '__main__':
    unittest.main()
