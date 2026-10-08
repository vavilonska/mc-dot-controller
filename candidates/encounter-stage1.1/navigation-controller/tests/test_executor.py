from dataclasses import replace
import unittest
from navigation_controller.executor import ExecutorConfig, Navigator
from navigation_controller.fake import FakeAdapter, FakeClock, FakeWorld
from navigation_controller.observation import Position
from navigation_controller.planner import plan
from navigation_controller.terrain import Block, WorldStamp


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.world = FakeWorld()
        self.adapter = FakeAdapter(self.clock, self.world)
        self.route = self.make_route()

    def make_route(self, target=Block(3, 64, 0)):
        return plan(self.world.grid(), Block(0, 64, 0), target,
                    WorldStamp(self.world.generation, 'minecraft:overworld', 100), 100).route

    def run_route(self, config=None, route=None):
        return Navigator(self.adapter, self.clock, config or ExecutorConfig(enabled=True)).run(route or self.route)

    def test_disabled_by_default(self):
        result = Navigator(self.adapter, self.clock).run(self.route)
        self.assertEqual(result.reason, 'executor_disabled')
        self.assertEqual(self.adapter.calls, [])

    def test_live_adapter_always_refused(self):
        self.adapter.simulation_only = False
        self.assertEqual(self.run_route().reason, 'live_movement_not_implemented')
        self.assertEqual(self.adapter.calls, [])

    def test_fake_arrival_with_bounded_pulses(self):
        result = self.run_route()
        self.assertEqual(result.reason, 'arrived')
        self.assertTrue(result.released)
        self.assertGreater(result.pulses, 0)
        self.assertTrue(all(1 <= n <= 100 for n in self.adapter.pulses))
        self.assertLess(self.adapter.position.distance(Position(3.5, 64, 0.5)), 0.12)
        self.assertFalse(self.adapter.held)

    def test_fake_obstacle_detour(self):
        self.world.set(Block(1, 64, 0))
        result = self.run_route(route=self.make_route())
        self.assertEqual(result.reason, 'arrived')

    def test_observe_and_release_after_every_pulse(self):
        self.run_route()
        for i, call in enumerate(self.adapter.calls):
            if call == 'pulse':
                self.assertEqual(self.adapter.calls[i+1:i+3], ['release', 'observe'])

    def test_world_reset_stops_before_more_pulses(self):
        def hook(obs, count):
            if count == 3:
                changed = replace(obs.world, generation='00000000-0000-4000-8000-000000000099')
                return replace(obs, world=changed)
            return obs
        self.adapter.observation_hook = hook
        result = self.run_route()
        self.assertEqual(result.pulses, 1)
        self.assertNotEqual(result.reason, 'arrived')
        self.assertTrue(result.released)

    def test_player_change_stops(self):
        self.adapter.observation_hook = lambda obs, n: replace(obs, player_uuid='00000000-0000-4000-8000-000000000099') if n >= 3 else obs
        self.assertEqual(self.run_route().reason, 'world_or_player_changed')

    def test_stale_observation_stops(self):
        self.adapter.observation_hook = lambda obs, n: replace(obs, captured_at=90)
        self.assertEqual(self.run_route().reason, 'stale_observation')
        self.assertFalse(self.adapter.pulses)

    def test_stale_terrain_stops(self):
        old = self.world.grid(now=90)
        self.adapter.observation_hook = lambda obs, n: replace(obs, terrain=old)
        self.assertEqual(self.run_route().reason, 'stale_terrain_clock')

    def test_health_loss_stops(self):
        self.adapter.observation_hook = lambda obs, n: replace(obs, health=19) if n >= 3 else obs
        self.assertEqual(self.run_route().reason, 'damage_observed')
        self.assertEqual(len(self.adapter.pulses), 1)

    def test_danger_states_block(self):
        changes = {'screen_open': True, 'mouse_grabbed': False, 'neutral_inputs': False,
                   'on_ground': False, 'survival': False, 'effects_clear': False,
                   'air_full': False, 'nearby_clear': False, 'health': 9, 'food': 7,
                   'horizontal_speed': .5}
        for key, value in changes.items():
            with self.subTest(key=key):
                self.adapter = FakeAdapter(self.clock, self.world)
                self.adapter.observation_hook = lambda obs, n: replace(obs, **{key: value})
                self.assertNotEqual(self.run_route().reason, 'arrived')
                self.assertFalse(self.adapter.pulses)

    def test_fractional_floor_height_blocked(self):
        self.adapter.position = Position(.5, 64.5, .5)
        self.assertEqual(self.run_route().reason, 'non_full_block_standing_height')

    def test_wrong_start_blocked(self):
        self.adapter.position = Position(3.5, 64, .5)
        self.assertEqual(self.run_route().reason, 'route_start_mismatch')

    def test_dynamic_obstacle_after_look_stops(self):
        def hook(obs, n):
            if n == 2:
                self.world.set(Block(1, 64, 0))
                return replace(obs, terrain=self.world.grid(origin=obs.position.block(), radius=2))
            return obs
        self.adapter.observation_hook = hook
        self.assertEqual(self.run_route().reason, 'route_edge_became_unsafe')
        self.assertFalse(self.adapter.pulses)

    def test_pulse_budget(self):
        result = self.run_route(ExecutorConfig(enabled=True, max_pulses=1))
        self.assertEqual(result.reason, 'pulse_budget_exhausted')
        self.assertEqual(result.pulses, 1)

    def test_stalled_motion_stops(self):
        self.adapter.stalled = True
        result = self.run_route()
        self.assertEqual(result.reason, 'movement_stalled')
        self.assertEqual(result.pulses, 3)

    def test_pulse_failure_attempts_emergency_release(self):
        self.adapter.fail_pulse = True
        result = self.run_route()
        self.assertEqual(result.reason, 'adapter_failure')
        self.assertTrue(result.released)
        self.assertFalse(self.adapter.held)
        self.assertEqual(result.pulses, 1)

    def test_release_failure_is_reported(self):
        self.adapter.fail_release = True
        result = self.run_route()
        self.assertEqual(result.reason, 'emergency_release_failed')
        self.assertFalse(result.released)
        self.assertEqual(result.pulses, 1)

    def test_observe_failure_releases(self):
        def broken():
            raise RuntimeError('fake failed read')
        self.adapter.observe = broken
        self.assertEqual(self.run_route().reason, 'adapter_failure')
        self.assertEqual(self.adapter.releases, 1)

    def test_drop_execution_deferred(self):
        self.world.set(Block(1, 63, 0), 'air')
        route = self.make_route(Block(1, 63, 0))
        self.assertEqual(self.run_route(route=route).reason, 'step_down_execution_deferred')
        self.assertFalse(self.adapter.pulses)

    def test_displacement_after_look_stops(self):
        self.adapter.observation_hook = lambda obs, n: replace(obs, position=Position(.7, 64, .5)) if n == 2 else obs
        self.assertEqual(self.run_route().reason, 'state_changed_after_look')
        self.assertFalse(self.adapter.pulses)

    def test_elapsed_budget_after_look_blocks_pulse(self):
        original = self.adapter.look
        def slow(yaw, expected):
            original(yaw, expected)
            self.clock.sleep(2)
        self.adapter.look = slow
        self.assertEqual(self.run_route(ExecutorConfig(enabled=True, max_seconds=1)).reason, 'execution_time_budget')
        self.assertFalse(self.adapter.pulses)

    def test_future_pulse_must_fit_remaining_budget(self):
        self.assertEqual(self.run_route(ExecutorConfig(enabled=True, max_seconds=.05)).reason, 'execution_time_budget')
        self.assertFalse(self.adapter.pulses)

    def test_configuration_rejects_unbounded_pulses(self):
        for ms in (0, 101, True, float('inf')):
            with self.assertRaises(ValueError):
                ExecutorConfig(pulse_ms=ms)

    def test_position_leaving_center_corridor_stops(self):
        self.adapter.position = Position(.85, 64, .5)
        self.assertEqual(self.run_route().reason, 'position_left_route_corridor')

    def test_nonfinite_yaw_after_look_blocked(self):
        self.adapter.observation_hook = lambda obs, n: replace(obs, yaw=float('nan')) if n == 2 else obs
        self.assertEqual(self.run_route().reason, 'invalid_number')
        self.assertFalse(self.adapter.pulses)
