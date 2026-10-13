"""Fresh Python combat contracts and generated commands; no live game access."""
from copy import deepcopy
import unittest

from mdc_skills import combat_goals as goals, danger_policy, mobility, reach, threats
from mdc_skills.core import SkillError
from test_combat_goals import World, mob, shield_stack
from test_reach_inventory_resources import stack
from test_threats_dimensions import FakeRuntime


CAPABILITIES = dict(schema_version=1, encounter_route_guard_schema_version=1,
                    shulker_open_shell_guard_schema_version=1,
                    caller_health_reserve_guard_schema_version=1)


def encounter(kind, *, health=20, shield=False):
    ranged = kind in ('blaze', 'creeper', 'cave_spider')
    x = 17.5 if kind == 'blaze' and shield else 13.5 if ranged else 2.5
    target = mob(kind, x=x, shell_open=True) if kind == 'shulker' else mob(kind, x=x)
    runtime = World([target], roof=kind == 'enderman', selected=1 if ranged else 0)
    runtime.base.player['health'] = health
    if kind == 'blaze':
        if shield:
            runtime.base.player['offhand'] = shield_stack()
        else:
            runtime.base.player['effects'] = [{'id': 'minecraft:fire_resistance', 'duration_ticks': 600}]
    return runtime, ranged


class ReserveContractTests(unittest.TestCase):
    def test_species_effective_default_used_for_preflight_and_command(self):
        for kind in ('enderman', 'blaze', 'creeper', 'cave_spider'):
            for method in (threats.strike, threats.defeat):
                for health in (10, 11, 12):
                    with self.subTest(kind=kind, method=method.__name__, health=health):
                        runtime, ranged = encounter(kind, health=health)
                        with self.assertRaisesRegex(SkillError, 'health_reserve_required'):
                            method(runtime, 'mob-one', ranged=ranged)
                        self.assertFalse(runtime.commands)
                runtime, ranged = encounter(kind, health=13)
                self.assertTrue(method(runtime, 'mob-one', ranged=ranged).ok)
                self.assertEqual(runtime.commands[0]['min_health'], 12)

    def test_explicit_higher_reserve_is_never_lowered(self):
        for kind in ('zombie', 'spider', 'shulker', 'enderman', 'blaze', 'creeper', 'cave_spider'):
            for minimum in (8, 10, 12, 16, 19):
                with self.subTest(kind=kind, minimum=minimum):
                    runtime, ranged = encounter(kind)
                    result = threats.strike(runtime, 'mob-one', ranged=ranged, min_health=minimum)
                    self.assertTrue(result.ok, result.reason)
                    self.assertEqual(runtime.commands[0]['min_health'], max(minimum,
                        12 if kind in ('enderman', 'blaze', 'creeper', 'cave_spider') else 8))
        for bad in (True, None, '12', float('nan'), float('inf'), 7, 21):
            runtime, ranged = encounter('enderman')
            with self.assertRaisesRegex(SkillError, 'min_health_8_to_20'):
                threats.strike(runtime, 'mob-one', min_health=bad)
            self.assertFalse(runtime.commands)

    def test_ordinary_direct_default_stays_ten(self):
        for kind in ('zombie', 'spider', 'shulker'):
            runtime, ranged = encounter(kind, health=11)
            self.assertTrue(threats.strike(runtime, 'mob-one').ok)
            self.assertEqual(runtime.commands[0]['min_health'], 10)

    def test_engage_matches_existing_floor_and_forwards_caller_reserve(self):
        for minimum, expected in ((8, 14), (10, 14), (14, 14), (17, 17), (19, 19)):
            source, _ = encounter('zombie')
            before = source.observe()
            after = deepcopy(before)
            after.state['nearby']['entities'][0].update(alive=False, health=0)
            runtime = FakeRuntime([before], [after])
            self.assertTrue(threats.engage(runtime, 'mob-one', min_health=minimum).ok)
            self.assertEqual(runtime.commands[0][1]['min_health'], expected)
        source, _ = encounter('zombie', health=14)
        runtime = FakeRuntime([source.observe()])
        with self.assertRaisesRegex(SkillError, 'health_reserve_required'):
            threats.engage(runtime, 'mob-one')
        self.assertFalse(runtime.commands)

    def test_higher_engage_reserve_requires_fresh_exact_native_support(self):
        for bad in (None, {}, {'schema_version': 1},
                    {'schema_version': True, 'caller_health_reserve_guard_schema_version': 1},
                    {'schema_version': 1, 'caller_health_reserve_guard_schema_version': True},
                    {'schema_version': 1, 'caller_health_reserve_guard_schema_version': 1.0}):
            source, _ = encounter('zombie')
            source.base.state['combat_capabilities'] = bad
            runtime = FakeRuntime([source.observe()])
            with self.assertRaisesRegex(SkillError, 'caller_health_reserve_guard_schema_version_required'):
                threats.engage(runtime, 'mob-one', min_health=17)
            self.assertFalse(runtime.commands)


class DirectBlazeDeadlineTests(unittest.TestCase):
    def test_omitted_timeout_selects_full_mode_budget(self):
        for method in (threats.strike, threats.defeat):
            for shield, expected, minimum in ((False, 5000, 12), (True, 20000, 18)):
                runtime, _ = encounter('blaze', shield=shield)
                self.assertTrue(method(runtime, 'mob-one', ranged=True).ok)
                self.assertEqual(runtime.commands[0]['timeout_ms'], expected)
                self.assertEqual(runtime.commands[0]['min_health'], minimum)

    def test_explicit_invalid_deadlines_are_not_replaced_by_defaults(self):
        for shield, values in ((True, (None, True, '20000', 18000.0, 50, 5000, 17999, 20001)),
                               (False, (None, True, '5000', 5000.0, 49, 10001, 20000))):
            for timeout in values:
                with self.subTest(shield=shield, timeout=timeout):
                    runtime, _ = encounter('blaze', shield=shield)
                    with self.assertRaises(SkillError):
                        threats.strike(runtime, 'mob-one', ranged=True, timeout_ms=timeout)
                    self.assertFalse(runtime.commands)

    def test_explicit_valid_shield_deadline_remains_exact(self):
        for timeout in (18000, 19000, 20000):
            runtime, _ = encounter('blaze', shield=True)
            self.assertTrue(threats.strike(runtime, 'mob-one', ranged=True, timeout_ms=timeout).ok)
            self.assertEqual(runtime.commands[0]['timeout_ms'], timeout)

    def test_explicit_invalid_blaze_modes_do_not_become_defaults(self):
        for mode in ('', False, 0, {}, [], 'unknown'):
            runtime, _ = encounter('blaze', shield=True)
            with self.assertRaisesRegex(SkillError, 'invalid_blaze_safety_mode'):
                threats.strike(runtime, 'mob-one', ranged=True, blaze_safety_mode=mode)
            self.assertFalse(runtime.commands)


class DangerAndRouteContractTests(unittest.TestCase):
    def test_unknown_danger_liveness_is_not_treated_as_dead(self):
        for alive in (None, 0, 'false'):
            target = mob('warden', x=3.5, alive=alive)
            runtime = World([target])
            result = goals.defeat_nearby(runtime, 'minecraft:spider')
            self.assertEqual(result.reason, 'mob_entity_liveness_required')
            self.assertFalse(runtime.commands)

    def test_new_dangers_block_search_and_approach_before_any_action(self):
        for kind in ('drowned', 'vex', 'warden', 'breeze', 'piglin', 'zombified_piglin'):
            self.assertNotIn('minecraft:' + kind, goals.SPECIES)
            self.assertNotIn('minecraft:' + kind, threats.MELEE_TYPES | threats.RANGED_TYPES)
            for target in ([], [mob('spider', x=4.5)]):
                runtime = World(target + [mob(kind, x=3.5, uid='danger', ident=55)])
                result = goals.defeat_nearby(runtime, 'minecraft:spider')
                self.assertFalse(result.ok, kind)
                self.assertEqual(result.reason, 'mob_non_target_threat_near')
                self.assertFalse(runtime.commands)
        self.assertNotIn('minecraft:cow', danger_policy.DANGER_TYPES)

    def test_non_marker_potential_attackers_block_before_search_or_approach(self):
        # These vanilla entities can inflict damage without Enemy/NeutralMob.
        # No client-only hint grants an ordinary-rabbit exemption here.
        for kind in ('goat', 'rabbit', 'pufferfish'):
            self.assertNotIn('minecraft:' + kind, goals.SPECIES)
            self.assertNotIn('minecraft:' + kind, threats.MELEE_TYPES | threats.RANGED_TYPES)
            for target in ([], [mob('spider', x=4.5)]):
                with self.subTest(kind=kind, approach=bool(target)):
                    risk = mob(kind, x=3.5, uid='potential-attacker', ident=55, aggressive=False)
                    runtime = World(target + [risk])
                    result = goals.defeat_nearby(runtime, 'minecraft:spider')
                    self.assertFalse(result.ok)
                    self.assertEqual(result.reason, 'mob_non_target_threat_near')
                    self.assertFalse(runtime.commands)

    def test_route_binds_only_exact_approach_identity_and_search_has_none(self):
        runtime = World()
        result = goals.defeat_nearby(runtime, 'minecraft:spider', max_search_steps=1)
        self.assertEqual(result.reason, 'mob_loaded_search_budget_exhausted')
        self.assertEqual(runtime.commands[0]['encounter_route_guard'], {'schema_version': 1})
        runtime = World([mob('spider', x=4.5)])
        result = goals.defeat_nearby(runtime, 'minecraft:spider')
        self.assertTrue(result.ok, result.reason)
        routes = [command for command in runtime.commands if command['action'] == 'follow_path']
        self.assertTrue(routes)
        for command in routes:
            self.assertEqual(command['encounter_route_guard'], dict(schema_version=1,
                target_entity_id=7, target_uuid='mob-one', target_type='minecraft:spider'))
        self.assertNotIn('encounter_route_guard', runtime.commands[-1])
        ordinary = mobility._path_command((reach.Block(0, 64, 0), reach.Block(1, 64, 0)), {})
        self.assertNotIn('encounter_route_guard', ordinary)

    def test_route_requires_exact_fresh_support_even_after_supported_observation(self):
        for field in ('schema_version', 'encounter_route_guard_schema_version'):
            for bad in (None, True, 1.0, 0, 2):
                runtime = World()
                runtime.observe()
                runtime.base.state['combat_capabilities'][field] = bad
                result = goals.defeat_nearby(runtime, 'minecraft:spider')
                self.assertEqual(result.reason, 'native_encounter_route_guard_schema_version_required')
                self.assertFalse(runtime.commands)

    def test_route_checks_whole_segment_for_new_danger_projectile_cloud_and_fuse(self):
        for kind, x in (('warden', 9.0), ('breeze_wind_charge', 6.0),
                        ('area_effect_cloud', 11.0), ('creeper', 15.0)):
            value = mob(kind, x=x, uid='risk', ident=99)
            if kind == 'creeper':
                value['creeper']['ignited'] = True
            runtime = World([value])
            hunt = goals._Hunt(runtime, 5, 20, 2, 10, 12)
            observation = hunt.observe()
            with self.assertRaisesRegex(SkillError, 'route_approaches_non_target_threat'):
                hunt._move(observation, (reach.Block(0, 64, 0), reach.Block(1, 64, 0)))
            self.assertFalse(runtime.commands)

    def test_unknown_guarded_move_stops_and_preserves_request(self):
        runtime = World(unknown_at=1)
        result = goals.defeat_nearby(runtime, 'minecraft:spider', max_search_steps=20)
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.request_ids, ('action-1',))
        self.assertEqual(len(runtime.commands), 1)
        self.assertIn('encounter_route_guard', runtime.commands[0])


class FreshShulkerContractTests(unittest.TestCase):
    def test_closed_missing_or_truthy_shell_never_dispatches(self):
        for shell in (None, False, 1, 'true'):
            runtime, _ = encounter('shulker')
            runtime.base.state['nearby']['entities'][0]['shell_open'] = shell
            with self.assertRaisesRegex(SkillError, 'observed_open_shell'):
                threats.strike(runtime, 'mob-one')
            self.assertFalse(runtime.commands)

    def test_stale_outer_open_shell_cannot_authorize_fresh_closed_shell(self):
        source, _ = encounter('shulker')
        open_sample = source.observe()
        source.base.state['nearby']['entities'][0]['shell_open'] = False
        closed_sample = source.observe()
        runtime = FakeRuntime([open_sample, closed_sample])
        with self.assertRaisesRegex(SkillError, 'observed_open_shell'):
            threats.defeat(runtime, 'mob-one')
        self.assertFalse(runtime.commands)

    def test_native_shell_contract_must_be_fresh_and_cannot_be_bypassed(self):
        for value in (None, {}, dict(schema_version=1, shulker_open_shell_guard_schema_version=True)):
            runtime, _ = encounter('shulker')
            runtime.base.state['combat_capabilities'] = value
            with self.assertRaisesRegex(SkillError, 'shulker_open_shell_guard_schema_version_required'):
                threats.strike(runtime, 'mob-one')
            self.assertFalse(runtime.commands)
        runtime, _ = encounter('shulker')
        self.assertTrue(threats.strike(runtime, 'mob-one').ok)
        self.assertNotIn('shell_open', runtime.commands[0])
        self.assertNotIn('shulker_shell_bypass', runtime.commands[0])


class EndermanCalmContractTests(unittest.TestCase):
    def observed(self):
        runtime = World([mob('enderman', x=9.5)])
        runtime.base.player['armor'] = [{'slot': 'head', **stack('minecraft:carved_pumpkin', 1)}]
        return runtime, runtime.observe()

    def test_non_target_exemption_requires_exact_fresh_native_living(self):
        runtime, before = self.observed()
        row = before.state['nearby']['entities'][0]
        self.assertTrue(danger_policy.observed_calm_enderman(before, row, pumpkin=True))
        goals._safety(before, 12)
        for key, value in (
                ('schema_version', True), ('known', False), ('source', 'client_guess'),
                ('entity_uuid', 'other'), ('entity_id', True), ('entity_type', 'minecraft:cow'),
                ('world_generation', 'other'), ('dimension', 'minecraft:the_end'), ('player_uuid', 'other'),
                ('coverage_complete', False), ('inspected', 0), ('inspected', True),
                ('sample_tick', before.tick + 1), ('source_tick', before.tick - 6),
                ('source_nano', '99600000000'), ('sample_nano', '100300000000'),
                ('sample_age_ms', 251), ('sample_age_ms', True), ('alive', False),
                ('aggressive', True), ('current_target_known', False),
                ('current_target', {'uuid': 'player'})):
            changed = deepcopy(before)
            changed.state['nearby']['entities'][0]['native_living'][key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(SkillError, 'non_target_enderman_gaze_guard'):
                    goals._safety(changed, 12)
        for field in ('native_living', 'aggressive'):
            changed = deepcopy(before)
            changed.state['nearby']['entities'][0].pop(field)
            with self.assertRaisesRegex(SkillError, 'non_target_enderman_gaze_guard'):
                goals._safety(changed, 12)
        self.assertFalse(runtime.commands)

    def test_approach_does_not_trust_client_only_calm_hint(self):
        runtime = World([mob('enderman', native_living=None)], roof=True)
        runtime.base.player['x'] = -2.5
        runtime.base.player['armor'] = [{'slot': 'head', **stack('minecraft:carved_pumpkin', 1)}]
        result = goals.defeat_nearby(runtime, 'minecraft:enderman')
        self.assertEqual(result.reason, 'enderman_approach_requires_fresh_native_calm')
        self.assertFalse(runtime.commands)


if __name__ == '__main__':
    unittest.main()
