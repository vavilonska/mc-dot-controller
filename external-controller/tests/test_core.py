import math
import unittest
from dataclasses import replace

from combat_controller.core import HOSTILE_TYPES, Config, Controller, Entity, Phase, Vec3, bounded_aim, wrap_yaw
from combat_controller.fake import FakeBridge, FakeClock, safe_snapshot


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.bridge = FakeBridge(self.clock)

    def run_session(self, **changes):
        return Controller(self.bridge, Config(enabled=True, session_seconds=0.5, **changes), self.clock).run()

    def stopped(self, expected, **changes):
        self.bridge.snapshots = lambda _: safe_snapshot(self.clock, **changes)
        result = self.run_session()
        self.assertEqual(expected, result.reason)
        self.assertEqual([], self.bridge.attack_times)
        self.assertEqual([], self.bridge.looks)
        self.assertTrue(result.release_confirmed)

    def test_default_disabled_has_zero_side_effects(self):
        result = Controller(self.bridge, clock=self.clock).run()
        self.assertEqual('disabled', result.reason)
        self.assertEqual([], self.bridge.calls)

    def test_safe_aimed_target_single_attack_then_deadline(self):
        result = self.run_session()
        self.assertEqual('session_deadline', result.reason)
        self.assertEqual(1, result.attacks)
        self.assertEqual(1, self.bridge.release_count)
        self.assertEqual('release_all', self.bridge.calls[-1])

    def test_cadence_is_conservative(self):
        result = Controller(self.bridge, Config(enabled=True, session_seconds=4, action_budget=3), self.clock).run()
        self.assertEqual(3, result.attacks)
        self.assertEqual('action_budget', result.reason)
        self.assertTrue(all(b - a >= 1.5 for a, b in zip(self.bridge.attack_times, self.bridge.attack_times[1:])))

    def test_low_health(self):
        self.stopped('low_health', health=13)

    def test_low_food(self):
        self.stopped('low_food', food=11)

    def test_not_full_air(self):
        self.stopped('air_not_full', air=299)

    def test_no_ground(self):
        self.stopped('not_grounded_and_stationary', on_ground=False)

    def test_velocity_halts_without_retreat(self):
        self.stopped('not_grounded_and_stationary', velocity=Vec3(0.2, 0, 0))

    def test_open_screen(self):
        self.stopped('screen_or_mouse_not_ready', screen_open=True)

    def test_ungrabbed_mouse(self):
        self.stopped('screen_or_mouse_not_ready', mouse_grabbed=False)

    def test_existing_held_input(self):
        self.stopped('unexpected_held_input', held_inputs=True)

    def test_unknown_terrain(self):
        self.stopped('terrain_unknown', terrain_safe=False, terrain_reason='terrain_unknown')

    def test_no_generation(self):
        self.stopped('world_generation_unknown', generation=None)

    def test_creative_mode_rejected(self):
        self.stopped('not_survival', gamemode='creative')

    def test_truncated_nearby_list(self):
        self.stopped('entity_observation_truncated', entities_truncated=True)

    def test_wrong_weapon(self):
        self.stopped('weapon_not_allowed', weapon='minecraft:bow')

    def test_unarmed_requires_opt_in(self):
        self.stopped('weapon_not_allowed', weapon='')

    def test_unarmed_explicit_opt_in(self):
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, weapon='', tick=100+n)
        self.assertEqual(1, self.run_session(allow_unarmed=True).attacks)

    def test_players_pets_villagers_never_selected(self):
        for kind in ('minecraft:player', 'minecraft:wolf', 'minecraft:cat', 'minecraft:villager', 'minecraft:zombie_villager', 'minecraft:spider'):
            with self.subTest(kind=kind):
                clock = FakeClock()
                pet = Entity('protected', kind, Vec3(0, 64, 2), True, 20)
                bridge = FakeBridge(clock, lambda n: safe_snapshot(clock, entities=(pet,), tick=100+n,
                                     crosshair_uuid=pet.uuid, crosshair_kind=kind))
                result = Controller(bridge, Config(enabled=True, session_seconds=0.3), clock).run()
                self.assertEqual(0, result.attacks)
                self.assertEqual([], bridge.looks)

    def test_mutable_caller_allowlist_cannot_expand_config(self):
        supplied = set(HOSTILE_TYPES)
        config = Config(enabled=True, allowed_types=supplied, session_seconds=0.2)
        supplied.add('minecraft:player')
        self.assertNotIn('minecraft:player', config.allowed_types)
        self.assertIsInstance(config.allowed_types, frozenset)

    def test_unknown_health_protected_entity_still_blocks(self):
        target = safe_snapshot(self.clock).entities[0]
        self.stopped('protected_or_unknown_entity_nearby', entities=(target, Entity('player', 'minecraft:player', Vec3(1, 64, 2), True, None)))

    def test_creeper_outside_sweep_area_is_still_a_hazard(self):
        target = safe_snapshot(self.clock).entities[0]
        self.stopped('dangerous_mob_nearby', entities=(target, Entity('creeper', 'minecraft:creeper', Vec3(0, 64, 5.5), True, 20)))

    def test_nearby_protected_mob_blocks_sweeping_attack(self):
        target = safe_snapshot(self.clock).entities[0]
        self.stopped('protected_or_unknown_entity_nearby', entities=(target, Entity('cow', 'minecraft:cow', Vec3(1, 64, 2), True, 10)))

    def test_no_extra_reach(self):
        target = replace(safe_snapshot(self.clock).entities[0], position=Vec3(0, 64, 3))
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, entities=(target,), tick=100+n)
        self.assertEqual(0, self.run_session().attacks)
        self.assertEqual([], self.bridge.looks)

    def test_crosshair_point_out_of_range(self):
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, tick=100+n, crosshair_location=Vec3(0, 65, 4))
        self.assertEqual(0, self.run_session().attacks)

    def test_no_attack_without_actual_matching_crosshair(self):
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, tick=100+n, crosshair_uuid='wrong')
        result = self.run_session(action_budget=3)
        self.assertEqual(0, result.attacks)
        self.assertEqual(3, len(self.bridge.looks))
        self.assertEqual('action_budget', result.reason)

    def test_look_requires_new_tick_and_matching_crosshair(self):
        def snapshots(n):
            return safe_snapshot(self.clock, tick=100 if n < 3 else 101,
                                 crosshair_uuid=None if n == 1 else 'fake-zombie-uuid')
        self.bridge.snapshots = snapshots
        result = self.run_session()
        self.assertEqual(1, len(self.bridge.looks))
        self.assertEqual(1, result.attacks)
        self.assertGreaterEqual(self.bridge.attack_times[0] - 100, 0.19)

    def test_cached_tick_expires_heartbeat(self):
        self.bridge.snapshots = lambda _: safe_snapshot(self.clock, tick=100)
        result = Controller(self.bridge, Config(enabled=True, session_seconds=3), self.clock).run()
        self.assertEqual('heartbeat_expired', result.reason)
        self.assertEqual(1, result.attacks)

    def test_stale_snapshot(self):
        self.stopped('stale_snapshot', captured_at=98)

    def test_future_snapshot(self):
        self.stopped('stale_snapshot', captured_at=102)

    def test_world_generation_change_stops(self):
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, tick=100+n, generation='a' if n == 1 else 'b')
        result = self.run_session()
        self.assertEqual('world_identity_changed', result.reason)
        self.assertEqual(1, result.attacks)

    def test_world_identity_change_stops(self):
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, tick=100+n,
            identity=('run', 1 if n == 1 else 2, 'player', 'minecraft:overworld'))
        self.assertEqual('world_identity_changed', self.run_session().reason)

    def test_world_time_reversal_stops(self):
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, tick=101-n)
        self.assertEqual('world_time_reversed', self.run_session().reason)

    def test_damage_stop(self):
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, tick=100+n, health=20 if n == 1 else 18)
        self.assertEqual('damage_received', self.run_session().reason)

    def test_displacement_stop(self):
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, tick=100+n, position=Vec3(0 if n == 1 else 0.4, 64, 0))
        self.assertEqual('unexpected_displacement', self.run_session().reason)

    def test_malformed_nonfinite_state(self):
        self.stopped('malformed_snapshot', yaw=float('nan'))

    def test_duplicate_entity_uuid(self):
        target = safe_snapshot(self.clock).entities[0]
        self.stopped('duplicate_entity_identity', entities=(target, target))

    def test_dead_target_never_attacked(self):
        target = replace(safe_snapshot(self.clock).entities[0], alive=False, health=0)
        self.bridge.snapshots = lambda n: safe_snapshot(self.clock, tick=100+n, entities=(target,))
        self.assertEqual(0, self.run_session().attacks)

    def test_observation_error_releases(self):
        self.bridge.fail_observe = True
        result = self.run_session()
        self.assertEqual('observation_or_input_failed', result.reason)
        self.assertTrue(result.release_confirmed)

    def test_uncertain_attack_not_retried(self):
        self.bridge.fail_attack = True
        result = self.run_session()
        self.assertEqual('observation_or_input_failed', result.reason)
        self.assertEqual(1, result.attacks)
        self.assertEqual(1, len(self.bridge.attack_times))
        self.assertTrue(result.release_confirmed)

    def test_failed_release_not_claimed_success(self):
        self.bridge.fail_release = True
        self.assertFalse(self.run_session().release_confirmed)

    def test_deadline_during_observe_prevents_attack(self):
        def delayed(_):
            self.clock.sleep(0.6)
            return safe_snapshot(self.clock)
        self.bridge.snapshots = delayed
        result = self.run_session()
        self.assertEqual('session_deadline', result.reason)
        self.assertEqual(0, result.attacks)

    def test_external_stop(self):
        controller = Controller(self.bridge, Config(enabled=True), self.clock)
        controller.stop()
        result = controller.run()
        self.assertEqual('stop_requested', result.reason)
        self.assertEqual(['release_all'], self.bridge.calls)

    def test_cannot_restart(self):
        controller = Controller(self.bridge, clock=self.clock)
        controller.run()
        with self.assertRaises(RuntimeError):
            controller.run()

    def test_key_interrupt_still_releases(self):
        self.bridge.snapshots = lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_session()
        self.assertEqual(1, self.bridge.release_count)

    def test_aim_wraps_yaw_shortest_path(self):
        s = safe_snapshot(self.clock, yaw=179)
        target = Entity('z', 'minecraft:zombie', Vec3(0.1, 64, -2), True, 20)
        yaw, pitch = bounded_aim(s, target, Config())
        self.assertLess(abs(wrap_yaw(yaw - 179)), 20)
        self.assertTrue(-180 <= yaw < 180)
        self.assertTrue(-12 <= pitch <= 12)

    def test_unsafe_configurations_rejected(self):
        cases = [dict(attack_range=3), dict(attack_interval=0.1), dict(action_budget=100),
                 dict(allowed_types=frozenset({'minecraft:player'})), dict(session_seconds=999),
                 dict(min_food=2), dict(min_health=1), dict(max_yaw_step=180),
                 dict(session_seconds=float('inf')), dict(enabled='true')]
        for case in cases:
            with self.subTest(case=case), self.assertRaises((ValueError, TypeError)):
                Config(**case)


if __name__ == '__main__':
    unittest.main()
