"""Offline producer contracts. Authored under a no-test-run window; no game I/O.

These use the real WorldCache, planner and task generators against an in-memory
bridge. Native readiness is supplied, never manufactured by Python observations.
"""
import copy
from collections import deque
import unittest
from unittest.mock import patch

from resident_controller.tasks import make_task
from resident_controller.world import WorldCache
from navigation_controller.fake import FakeWorld, PLAYER_ID, WORLD_ID


ACTION_SESSION = "00000000-0000-4000-8000-000000000004"
STONE = "minecraft:stone"
ABSENT = object()
BINDING_FIELDS = ("expected_navigation_epoch", "expected_origin",
                  "expected_world_generation", "expected_player_uuid",
                  "expected_action_session")


def guard(epoch=7, ready=True):
    return {"schema_version": 1, "epoch": epoch,
            "fresh_binding_required": True, "rebind_ready": ready,
            "stable_ticks": 3 if ready else 1,
            "reason": "position_discontinuity",
            "large_displacement_threshold": 16, "detects_all_teleports": False}


def state(*, epoch=7, ready=True, navigation_guard=ABSENT, missing=False,
          x=0.371234567891, y=64, z=0.712345678912, tick=100):
    result = {
        "world": {"world_generation": WORLD_ID,
                  "dimension": "minecraft:overworld", "game_time": tick},
        "player": {"uuid": PLAYER_ID, "dimension": "minecraft:overworld",
                   "x": x, "y": y, "z": z, "on_ground": True,
                   "inventory": [{"slot": 0, "id": STONE, "count": 8,
                                  "empty": False}]},
        "client_action": {"action_session": ACTION_SESSION},
    }
    if not missing:
        result["world"]["navigation_guard"] = (
            guard(epoch, ready) if navigation_guard is ABSENT
            else copy.deepcopy(navigation_guard))
    return result


class MemoryBridge:
    """Only explicitly scripted GETs are accepted; no network implementation."""
    def __init__(self, states, *, pages=None):
        self.states = deque(copy.deepcopy(states))
        self.pages = deque(copy.deepcopy(
            FakeWorld().pages(radius=1, vertical=2) if pages is None else pages))
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method != "GET" or body is not None:
            raise AssertionError("The recipe fixture permits reads only")
        if path.startswith("/control/state?"):
            if not self.states:
                raise AssertionError("Unscripted state read: bounded contract exceeded")
            return self.states.popleft()
        if path.startswith("/control/terrain?"):
            if not self.pages:
                raise AssertionError("Unscripted terrain read or scan retry")
            return self.pages.popleft()
        raise AssertionError("Unexpected bridge route: " + path)


class RecipeDriver:
    """Run the existing generator protocol without Resident, queues or POSTs."""
    def __init__(self, cache, bridge):
        self.cache, self.bridge = cache, bridge
        self.actions = []

    def finish(self, recipe):
        response = None
        for unused in range(32):
            try:
                step = recipe.send(response)
            except StopIteration as done:
                return done.value
            response = None
            if step["step"] == "observe":
                response = self.cache.observe(self.bridge)
            elif step["step"] == "action":
                self.actions.append(copy.deepcopy(step["body"]))
                response = {"status": "succeeded", "reason": "offline_observed"}
            elif step["step"] != "wait":
                raise AssertionError("Unknown recipe step: " + repr(step))
        raise AssertionError("Recipe exceeded its bounded offline driver")


class BindingAssertions:
    def assert_binding(self, body, observed):
        self.assertEqual(body["expected_navigation_epoch"],
                         observed["world"]["navigation_guard"]["epoch"])
        self.assertEqual(body["expected_origin"],
                         {key: observed["player"][key] for key in ("x", "y", "z")})
        self.assertEqual(body["expected_world_generation"],
                         observed["world"]["world_generation"])
        self.assertEqual(body["expected_player_uuid"], observed["player"]["uuid"])
        self.assertEqual(body["expected_action_session"],
                         observed["client_action"]["action_session"])

    def assert_legacy(self, body):
        for key in BINDING_FIELDS:
            self.assertNotIn(key, body)


class WorldCacheBindingChecks(BindingAssertions, unittest.TestCase):
    def setUp(self):
        self.cache = WorldCache()
        clock = patch("time.monotonic", return_value=100.0)
        sleep = patch("time.sleep", return_value=None)
        clock.start(); sleep.start()
        self.addCleanup(clock.stop); self.addCleanup(sleep.stop)

    def walk(self, bridge):
        return make_task({"op": "walk_to", "target": {"x": 1, "y": 64, "z": 0},
                          "radius": 1, "vertical": 2}, self.cache, bridge)

    def test_walk_uses_actual_final_scan_state_not_initial_state_or_waypoint(self):
        first = state(epoch=3, x=0.128765432198, z=0.871234567891)
        final = state(epoch=11)
        bridge = MemoryBridge([first, final])
        recipe = self.walk(bridge)
        step = next(recipe)
        self.addCleanup(recipe.close)
        self.assertEqual(step["step"], "action")
        self.assertEqual(step["body"]["action"], "follow_path")
        self.assert_binding(step["body"], final)
        self.assertNotEqual(step["body"]["expected_origin"],
                            step["body"]["waypoints"][0])
        self.assertEqual(sum("/state?" in call[1] for call in bridge.calls), 2)
        frozen = copy.deepcopy(step["body"])
        self.cache.state["player"]["x"] = 99
        self.cache.state["world"]["navigation_guard"]["epoch"] = 99
        self.assertEqual(step["body"], frozen, "A sent binding must not alias cache state")

    def test_scan_first_schema_last_missing_cannot_downgrade_to_legacy(self):
        bridge = MemoryBridge([state(), state(missing=True)])
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            next(self.walk(bridge))
        self.assertTrue(all(method == "GET" for method, _, _ in bridge.calls))
        self.assertIsNone(self.cache.grid, "A poisoned final observation cannot publish terrain")

    def test_scan_initial_legacy_final_schema_uses_final_binding(self):
        final = state(epoch=15)
        bridge = MemoryBridge([state(missing=True), final])
        recipe = self.walk(bridge)
        self.addCleanup(recipe.close)
        self.assert_binding(next(recipe)["body"], final)

    def test_first_malformed_guard_establishes_seen_even_after_exception(self):
        malformed = [None, [], {}, {**guard(), "schema_version": 2},
                     {**guard(), "epoch": True}, {**guard(), "rebind_ready": 1}]
        for value in malformed:
            with self.subTest(guard=value):
                cache = WorldCache()
                bridge = MemoryBridge([state(navigation_guard=value), state(missing=True)])
                with self.assertRaisesRegex(ValueError, "navigation_guard_invalid"):
                    cache.observe(bridge)
                with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
                    cache.observe(bridge)

    def test_invalidation_does_not_forget_capability(self):
        bridge = MemoryBridge([state(), state(missing=True)])
        self.cache.observe(bridge)
        self.cache.invalidate_terrain()
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            self.cache.observe(bridge)

    def test_world_change_does_not_erase_previously_seen_capability(self):
        changed = state(missing=True)
        changed["world"]["world_generation"] = "00000000-0000-4000-8000-000000000099"
        bridge = MemoryBridge([state(), changed])
        self.cache.observe(bridge)
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            self.cache.observe(bridge)

    def test_unready_observations_remain_readable_but_never_create_movement(self):
        unready = state(ready=False)
        bridge = MemoryBridge([unready, unready, unready, unready])
        for unused in range(2):
            self.assertEqual(self.cache.observe(bridge)["world"]["navigation_guard"],
                             unready["world"]["navigation_guard"])
        with self.assertRaises(ValueError):
            next(self.walk(bridge))
        self.assertEqual(self.cache.state["world"]["navigation_guard"]["stable_ticks"], 1)

    def test_all_legacy_scan_keeps_old_wire_body(self):
        bridge = MemoryBridge([state(missing=True), state(missing=True)])
        recipe = self.walk(bridge)
        self.addCleanup(recipe.close)
        body = next(recipe)["body"]
        self.assertEqual(body["action"], "follow_path")
        self.assert_legacy(body)


class TaskBindingLifecycleChecks(BindingAssertions, unittest.TestCase):
    def setUp(self):
        self.cache = WorldCache()
        clock = patch("time.monotonic", return_value=100.0)
        sleep = patch("time.sleep", return_value=None)
        clock.start(); sleep.start()
        self.addCleanup(clock.stop); self.addCleanup(sleep.stop)

    def run_recipe(self, operation, states, **command):
        bridge = MemoryBridge(states)
        driver = RecipeDriver(self.cache, bridge)
        recipe = make_task({"op": operation, **command}, self.cache, bridge)
        driver.finish(recipe)
        return driver

    def test_pillar_binds_each_actual_placement_observation(self):
        initial = state(epoch=2)
        first = state(epoch=3, x=0.278912345678, z=0.678912345678)
        second = state(epoch=4, x=0.612345678912, y=65, z=0.378912345678)
        driver = self.run_recipe("pillar", [initial, first, second, state(y=66)],
                                 height=2, block_id=STONE)
        self.assertEqual([body["action"] for body in driver.actions],
                         ["place_block", "place_block"])
        self.assert_binding(driver.actions[0], first)
        self.assert_binding(driver.actions[1], second)
        self.assertEqual([body["support"]["y"] for body in driver.actions], [63, 64])

    def test_completed_walk_then_new_pillar_cannot_downgrade(self):
        self.run_recipe("walk_to", [state(), state(), state(x=1.5)],
                        target={"x": 1, "y": 64, "z": 0}, radius=1, vertical=2)
        bridge = MemoryBridge([state(missing=True)])
        driver = RecipeDriver(self.cache, bridge)
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            driver.finish(make_task({"op": "pillar", "height": 1, "block_id": STONE},
                                    self.cache, bridge))
        self.assertEqual(driver.actions, [])

    def test_completed_pillar_then_new_walk_cannot_downgrade(self):
        self.run_recipe("pillar", [state(), state(), state(y=65)],
                        height=1, block_id=STONE)
        bridge = MemoryBridge([state(missing=True)])
        driver = RecipeDriver(self.cache, bridge)
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            driver.finish(make_task({"op": "walk_to", "target": {"x": 1, "y": 64, "z": 0},
                                     "radius": 1, "vertical": 2}, self.cache, bridge))
        self.assertEqual(driver.actions, [])

    def test_guard_loss_between_pillar_placements_does_not_replay_first_step(self):
        bridge = MemoryBridge([state(), state(), state(y=65, missing=True)])
        driver = RecipeDriver(self.cache, bridge)
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            driver.finish(make_task({"op": "pillar", "height": 2, "block_id": STONE},
                                    self.cache, bridge))
        self.assertEqual(len(driver.actions), 1)
        self.assertEqual(driver.actions[0]["action"], "place_block")
        self.assertEqual(driver.actions[0]["support"]["y"], 63)

    def test_guard_loss_after_inventory_swap_does_not_replay_or_place(self):
        stored = state()
        stored["player"]["inventory"][0]["slot"] = 9
        stored["menu"] = {
            "container_id": 0, "menu_class": "net.minecraft.world.inventory.InventoryMenu",
            "slots_truncated": False, "carried": {"empty": True, "count": 0},
            "slots": [{"menu_index": 9, "player_inventory": True, "inventory_index": 9,
                       "item": {"id": STONE, "count": 8, "empty": False}}],
        }
        bridge = MemoryBridge([stored, state(), state(missing=True)])
        driver = RecipeDriver(self.cache, bridge)
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            driver.finish(make_task({"op": "pillar", "height": 1, "block_id": STONE},
                                    self.cache, bridge))
        self.assertEqual(len(driver.actions), 1)
        self.assertEqual(driver.actions[0]["action"], "click_slot")
        self.assertEqual(driver.actions[0]["click_type"], "swap")
        self.assert_legacy(driver.actions[0])

    def test_legacy_pillar_remains_compatible(self):
        driver = self.run_recipe("pillar", [state(missing=True), state(missing=True),
                                             state(y=65, missing=True)], height=1, block_id=STONE)
        self.assertEqual(len(driver.actions), 1)
        self.assert_legacy(driver.actions[0])

    def test_raw_action_complete_or_partial_pair_is_never_rebased(self):
        self.cache.observe(MemoryBridge([state(epoch=33)]))
        fields = {"expected_navigation_epoch": 1,
                  "expected_origin": {"x": 91.125, "y": 77, "z": -31.875},
                  "expected_world_generation": "old-world",
                  "expected_player_uuid": "old-player",
                  "expected_action_session": "old-session"}
        variants = [fields, {"expected_origin": fields["expected_origin"]},
                    {"expected_navigation_epoch": 1}, {}]
        for supplied in variants:
            with self.subTest(fields=supplied):
                command = {"op": "action", "action": "follow_path",
                           "waypoints": [{"x": 92.5, "y": 77, "z": -31.5}],
                           **copy.deepcopy(supplied)}
                before = copy.deepcopy(command)
                recipe = make_task(command, self.cache, MemoryBridge([]))
                self.addCleanup(recipe.close)
                body = next(recipe)["body"]
                self.assertEqual(body, {key: value for key, value in before.items() if key != "op"})
                self.assertEqual(command, before)

    def test_same_pillar_recipe_cannot_continue_after_identity_change(self):
        for section,key in [('world','world_generation'),('world','dimension'),('player','uuid'),('client_action','action_session')]:
            first=state(x=.5,z=.5);second=state(x=.5,y=65,z=.5)
            second[section][key]='new-context'
            if section=='world' and key=='dimension':second['player']['dimension']='new-context'
            cache=WorldCache();bridge=MemoryBridge([first,first,second]);driver=RecipeDriver(cache,bridge)
            with self.assertRaisesRegex(ValueError,'navigation_context_changed'):
                driver.finish(make_task({'op':'pillar','height':2,'block_id':STONE},cache,bridge))
            self.assertEqual(1,len(driver.actions))
            self.assertEqual(63,driver.actions[0]['support']['y'])



if __name__ == "__main__":
    unittest.main()
