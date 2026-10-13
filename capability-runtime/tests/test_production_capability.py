"""Deterministic offline model tests; these are not live Minecraft evidence."""
from collections import Counter
from copy import deepcopy
import importlib.util
from pathlib import Path
import hashlib
import json
from types import SimpleNamespace
import unittest

from mdc_skills.core import SkillError, Outcome
from mdc_skills.production import craft, smelt, open_workstation, close_workstation, FurnaceView

_source = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_existing_crafting_fixture", _source / "gameplay-helpers/tests/test_crafting_helper.py")
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
item = _fixture.item


def bind_snapshot(state):
    def bind(value):
        component = repr((value.get("id"), value.get("damage", 0), value.get("test_component", "")))
        value["component_fingerprint"] = hashlib.sha256(component.encode()).hexdigest()
        value["item_fingerprint"] = hashlib.sha256((component + str(value["count"])).encode()).hexdigest()
    for slot in state["menu"]["slots"]:
        bind(slot["item"])
    bind(state["menu"]["carried"])
    for value in state["player"]["inventory"]:
        bind(value)


class ProductionRuntime:
    def __init__(self, client=None):
        self.client = client or _fixture.FakeQueueClient()
        self.actions = []
        self.serial = 0
        self.time = 0
        self.sleeper = lambda seconds: setattr(self, "time", self.time + seconds)
        self.clock = lambda: self.time
        self.failure_at = None
        self.hook = None
        self.stopped = False

    def observe(self, **kwargs):
        if self.stopped:
            raise SkillError("unknown_or_pending_request_blocks_new_work")
        self.serial += 1
        if isinstance(self.client, FurnaceClient):
            self.client.advance()
            state = self.client.snapshot()
        else:
            rid = "observe-" + str(self.serial)
            self.client.submit({"op": "observe"}, request_id=rid)
            state = self.client.wait(rid)["result"]["state"]
        bind_snapshot(state)
        state["menu"]["state_id"] = self.serial
        state["screen_open"] = state["menu"]["container_id"] != 0
        if self.hook:
            self.hook(state)
        return SimpleNamespace(state=state, player=state["player"], terrain=None,
            tick=state["world"]["game_time"], context=("world", "minecraft:overworld", "player", "session"),
            request_id="r" + str(self.serial))

    def execute(self, skill, command, verify, *, before, **kwargs):
        self.actions.append(deepcopy(command))
        rid = "action-" + str(len(self.actions))
        if self.failure_at == len(self.actions):
            self.stopped = True
            return Outcome("unknown", "simulated_transport_loss", (rid,))
        if command["action"] == "click_slot":
            self.assert_binding(command, before)
            if isinstance(self.client, FurnaceClient):
                self.client.click(command)
            else:
                self.client.submit(command, request_id=rid)
        elif command["action"] == "close_menu":
            self.client.container = 0
            self.client.width = 2
        else:
            raise AssertionError("unexpected action " + command["action"])
        stable = 0
        for _ in range(8):
            after = self.observe(allow_menu=True)
            if verify(before, after):
                stable += 1
                if stable == 2:
                    return Outcome("succeeded", "client_observed_stable", (rid,), {}, after)
            else:
                stable = 0
        self.stopped = True
        return Outcome("blocked", "semantic_result_not_observed", (rid,), {}, after)

    @staticmethod
    def assert_binding(command, before):
        menu = before.state["menu"]
        slot = next(s for s in menu["slots"] if s["menu_index"] == command["slot"])
        assert command["expected_menu_state_id"] == menu["state_id"]
        assert command["expected_slot_item"] == slot["item"]
        assert command["expected_carried"] == menu["carried"]

    @staticmethod
    def require_success(outcome):
        if not outcome.ok:
            raise SkillError(outcome.reason, status=outcome.status,
                             request_id=outcome.request_ids[-1] if outcome.request_ids else None)
        return outcome.last_observation

    @staticmethod
    def result(skill, observations=(), **evidence):
        return Outcome("succeeded", "goal_observed", tuple(o.request_id for o in observations),
                       dict(evidence, server_confirmed=False), observations[-1])


class FurnaceClient:
    def __init__(self, *, station="FurnaceMenu", stock=None, output="iron_ingot", period=20):
        self.station = station
        self.storage = {i: 100 + (i * 13) % 36 for i in range(36)}
        self.slots = {i: item() for i in (0, 1, 2)}
        self.slots.update({i: item() for i in self.storage.values()})
        stock = stock or {0: ("raw_iron", 12), 5: ("coal", 3)}
        for index, (name, count) in stock.items():
            self.slots[self.storage[index]] = item(name, count)
        self.carried = item()
        self.game_time = 100
        self.is_lit = False
        self.cooking = 0
        self.period = period
        self.energy = 0
        self.output = output
        self.quick_moves = 0
        self.never_cook = False

    def advance(self):
        self.game_time += 1
        if self.slots[0]["count"] and not self.is_lit and self.slots[1]["count"]:
            self.is_lit = True
            self.energy = 8 * self.period
            self.slots[1] = (dict(self.slots[1], count=self.slots[1]["count"] - 1)
                             if self.slots[1]["count"] > 1 else item())
        if self.is_lit:
            self.energy -= 1
            self.is_lit = self.energy > 0
            if self.slots[0]["count"] and not self.never_cook:
                self.cooking += 1
                if self.cooking >= self.period:
                    self.cooking = 0
                    self.slots[0] = (dict(self.slots[0], count=self.slots[0]["count"] - 1)
                                     if self.slots[0]["count"] > 1 else item())
                    self.slots[2] = item(self.output, self.slots[2]["count"] + 1)

    def snapshot(self):
        reverse = {v: k for k, v in self.storage.items()}
        slots = []
        for index, value in self.slots.items():
            row = dict(menu_index=index, container_slot=reverse.get(index, index),
                       player_inventory=index in reverse, active=True, item=deepcopy(value))
            if index in reverse:
                row["inventory_index"] = reverse[index]
            slots.append(row)
        return {"menu": {"menu_class": "net.minecraft.world.inventory." + self.station,
                         "container_id": 4, "slots_truncated": False, "slots": slots,
                         "carried": deepcopy(self.carried), "furnace": {
                             "is_lit": self.is_lit, "burn_progress": 0., "lit_progress": .5 if self.is_lit else 0.}},
                "player": {"health": 20., "uuid": "offline-player", "dimension": "minecraft:overworld",
                           "inventory_truncated": False, "inventory": [
                               dict(deepcopy(self.slots[s]), slot=i) for i, s in self.storage.items()]},
                "world": {"world_generation": "offline-world", "game_time": self.game_time}}

    def click(self, command):
        slot = command["slot"]
        if command["click_type"] == "quick_move":
            assert slot == 2 and self.carried["empty"]
            self.quick_moves += 1
            target = next(s for s in self.storage.values() if self.slots[s]["empty"]
                          or self.slots[s]["id"] == self.slots[2]["id"])
            self.slots[target] = dict(self.slots[2], count=self.slots[target]["count"] + self.slots[2]["count"])
            self.slots[2] = item()
        elif command["button"] == 1:
            assert self.carried["count"] > 0
            assert self.slots[slot]["empty"] or self.slots[slot]["id"] == self.carried["id"]
            self.slots[slot] = dict(self.carried, count=self.slots[slot]["count"] + 1)
            self.carried = dict(self.carried, count=self.carried["count"] - 1) if self.carried["count"] > 1 else item()
        else:
            self.slots[slot], self.carried = self.carried, self.slots[slot]


class ProductionTests(unittest.TestCase):
    def test_craft_real_clicks_and_exact_batch_deltas(self):
        runtime = ProductionRuntime()
        result = craft(runtime, "iron_pickaxe", batches=2)
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence["added"], 2)
        self.assertEqual(result.evidence["consumed"], {"minecraft:iron_ingot": 6, "minecraft:stick": 4})
        self.assertEqual(runtime.client.quick_moves, 2)
        self.assertTrue(all(c["slot"] in runtime.client.slots for c in runtime.actions))
        self.assertFalse(result.evidence["server_confirmed"])

    def test_explicit_log_recipe_uses_real_grid(self):
        class LogFixture(_fixture.FakeQueueClient):
            def update_output(self):
                if (self.slots[1]["id"] == "minecraft:stripped_oak_wood"
                        and all(self.slots[i]["empty"] for i in range(2, self.width * self.width + 1))):
                    self.slots[0] = item("oak_planks", 4)
                else:
                    super().update_output()
        runtime = ProductionRuntime(LogFixture(width=2, stock={31: ("stripped_oak_wood", 3)}))
        result = craft(runtime, "oak_planks", batches=2)
        self.assertEqual(result.evidence["added"], 8)
        self.assertEqual(result.evidence["consumed"], {"minecraft:stripped_oak_wood": 2})

    def test_inventory_grid_small_recipe(self):
        runtime = ProductionRuntime(_fixture.FakeQueueClient(width=2))
        self.assertEqual(craft(runtime, "stick").evidence["added"], 4)

    def test_missing_recipe_or_station_no_click(self):
        runtime = ProductionRuntime(_fixture.FakeQueueClient(width=2))
        with self.assertRaisesRegex(SkillError, "requires_3x3"):
            craft(runtime, "iron_pickaxe")
        with self.assertRaisesRegex(SkillError, "unsupported"):
            craft(runtime, "beacon")
        self.assertEqual(runtime.actions, [])

    def test_budget_checked_before_mutation(self):
        runtime = ProductionRuntime()
        with self.assertRaisesRegex(SkillError, "budget_insufficient"):
            craft(runtime, "iron_pickaxe", max_actions=2)
        self.assertEqual(runtime.actions, [])

    def test_reserve_all_batches_output_capacity(self):
        stock = {i: ("dirt", 64) for i in range(35)}
        stock[0] = ("iron_ingot", 64)
        stock[1] = ("stick", 64)
        runtime = ProductionRuntime(_fixture.FakeQueueClient(stock=stock))
        with self.assertRaisesRegex(SkillError, "reserved_output_capacity"):
            craft(runtime, "iron_pickaxe", batches=2)
        self.assertEqual(runtime.actions, [])

    def test_unknown_click_never_repeated_and_cursor_retained(self):
        runtime = ProductionRuntime()
        runtime.failure_at = 2
        with self.assertRaisesRegex(SkillError, "transport_loss"):
            craft(runtime, "iron_pickaxe")
        self.assertEqual(len(runtime.actions), 2)
        self.assertFalse(runtime.client.carried["empty"])

    def test_wrong_output_not_retrieved(self):
        runtime = ProductionRuntime()
        runtime.client.output_override = "iron_axe"
        with self.assertRaisesRegex(SkillError, "wait_"):
            craft(runtime, "iron_pickaxe")
        self.assertEqual(runtime.client.quick_moves, 0)

    def test_furnace_load_fuel_wait_and_collect(self):
        runtime = ProductionRuntime(FurnaceClient())
        result = smelt(runtime, "minecraft:raw_iron", count=3)
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence["produced"], 3)
        self.assertEqual(result.evidence["fuel_loaded"], 1)
        self.assertEqual(runtime.client.quick_moves, 1)
        inputs = [i for i, c in enumerate(runtime.actions) if c["slot"] == 0 and c["button"] == 1]
        fuels = [i for i, c in enumerate(runtime.actions) if c["slot"] == 1 and c["button"] == 1]
        self.assertLess(max(inputs), min(fuels))
        self.assertTrue(runtime.client.slots[0]["empty"] and runtime.client.slots[2]["empty"])

    def test_blast_and_smoker_recipe_gates(self):
        runtime = ProductionRuntime(FurnaceClient(station="BlastFurnaceMenu"))
        self.assertTrue(smelt(runtime, "minecraft:raw_iron").ok)
        runtime = ProductionRuntime(FurnaceClient(station="SmokerMenu"))
        with self.assertRaisesRegex(SkillError, "not_supported_by"):
            smelt(runtime, "minecraft:raw_iron")
        self.assertEqual(runtime.actions, [])

    def test_smoker_food_and_multi_fuel_furnace(self):
        runtime = ProductionRuntime(FurnaceClient(station="SmokerMenu", stock={2: ("beef", 3), 4: ("coal", 1)}, output="cooked_beef"))
        result = smelt(runtime, "minecraft:beef", count=2)
        self.assertEqual(result.evidence["output_id"], "minecraft:cooked_beef")
        runtime = ProductionRuntime(FurnaceClient())
        result = smelt(runtime, "minecraft:raw_iron", count=10)
        self.assertEqual(result.evidence["fuel_loaded"], 2)
        self.assertEqual(result.evidence["produced"], 10)

    def test_wrong_smelting_output_never_collected(self):
        runtime = ProductionRuntime(FurnaceClient(output="gold_ingot"))
        with self.assertRaisesRegex(SkillError, "conservation_failed"):
            smelt(runtime, "minecraft:raw_iron", count=2)
        self.assertEqual(runtime.client.quick_moves, 0)

    def test_smelting_timeout_retains_machine_no_reload(self):
        client = FurnaceClient()
        client.never_cook = True
        runtime = ProductionRuntime(client)
        with self.assertRaisesRegex(SkillError, "wait_"):
            smelt(runtime, "minecraft:raw_iron", count=2, max_samples=3)
        self.assertEqual(client.quick_moves, 0)
        self.assertEqual(client.slots[0]["count"], 2)
        self.assertEqual(len([c for c in runtime.actions if c["slot"] == 0 and c["button"] == 1]), 2)

    def test_hot_or_occupied_furnace_no_click(self):
        client = FurnaceClient()
        client.is_lit, client.energy = True, 100
        runtime = ProductionRuntime(client)
        with self.assertRaisesRegex(SkillError, "unlit"):
            smelt(runtime, "minecraft:raw_iron")
        self.assertEqual(runtime.actions, [])

    def test_menu_slot_forgery_rejected(self):
        runtime = ProductionRuntime(FurnaceClient())
        runtime.hook = lambda state: state["menu"]["slots"][0].update(container_slot=2)
        with self.assertRaisesRegex(SkillError, "machine_mapping"):
            smelt(runtime, "minecraft:raw_iron")
        self.assertEqual(runtime.actions, [])

    def test_missing_fingerprint_fails_before_first_click(self):
        runtime = ProductionRuntime()
        runtime.hook = lambda state: state["menu"]["carried"].pop("item_fingerprint")
        with self.assertRaisesRegex(SkillError, "exact_item_fingerprints"):
            craft(runtime, "iron_pickaxe")
        self.assertEqual(runtime.actions, [])

    def test_unrelated_components_change_stops_even_when_counts_match(self):
        runtime = ProductionRuntime()
        def alter(state):
            if runtime.actions:
                for slot in state["menu"]["slots"]:
                    if slot["item"]["id"] == "minecraft:coal":
                        slot["item"].update(item_fingerprint="changed", component_fingerprint="changed")
                for row in state["player"]["inventory"]:
                    if row["id"] == "minecraft:coal":
                        row.update(item_fingerprint="changed", component_fingerprint="changed")
        runtime.hook = alter
        with self.assertRaisesRegex(SkillError, "semantic_result"):
            craft(runtime, "iron_pickaxe")
        self.assertEqual(len(runtime.actions), 1)

    def test_workstation_interaction_requires_requested_observed_menu(self):
        class StationRuntime(ProductionRuntime):
            def execute(self, skill, command, verify, *, before, **kwargs):
                self.actions.append(deepcopy(command))
                self.client.width, self.client.container = 3, 7
                for i in range(5, 10):
                    self.client.slots[i] = item()
                first = self.observe(allow_menu=True)
                second = self.observe(allow_menu=True)
                return Outcome("succeeded" if verify(before, first) and verify(before, second) else "blocked",
                               "menu_verified", ("interact-once",), {}, second)
        runtime = StationRuntime(_fixture.FakeQueueClient(width=2))
        result = open_workstation(runtime, {"x": 2, "y": 64, "z": 1}, "minecraft:crafting_table")
        self.assertTrue(result.ok)
        self.assertEqual(runtime.actions[0]["action"], "interact_block")
        self.assertEqual(runtime.actions[0]["expected_block_id"], "minecraft:crafting_table")
        runtime = StationRuntime(_fixture.FakeQueueClient(width=2))
        self.assertFalse(open_workstation(runtime, {"x": 2, "y": 64, "z": 1}, "minecraft:furnace").ok)

    def test_close_checks_actual_screen_open(self):
        runtime = ProductionRuntime(_fixture.FakeQueueClient(width=2))
        runtime.hook = lambda state: state.update(screen_open=True)
        with self.assertRaisesRegex(SkillError, ""):
            runtime.require_success(close_workstation(runtime))
        self.assertEqual(len(runtime.actions), 1)
        self.assertEqual(runtime.actions[0]["action"], "close_menu")



class GuardedMenuClient:
    """Actual Runtime adapter with synthetic game/menu responses, no transport."""
    def __init__(self, model, clock):
        from support_core import SESSION, NATIVE
        self.session_id, self.native_id = SESSION, NATIVE
        self.model, self.clock = model, clock
        self.saved, self.commands = {}, []
        self.action = {"action_session": self.native_id, "action_id": None, "status": "idle"}
        self.probe = ProductionRuntime(model)
        self.probe.clock = clock
        self.probe.sleeper = clock.sleep
        self.serial = 0

    def session(self):
        return {"session_id": self.session_id, "state": "ready", "pending": 0}

    def submit(self, command, request_id):
        self.commands.append(deepcopy(command))
        if command["op"] == "action":
            if isinstance(self.model, FurnaceClient):
                self.model.click(command)
            else:
                self.model.submit(command, request_id=request_id)
        self.saved[request_id] = deepcopy(command)
        return request_id

    def wait(self, request_id, timeout=30):
        import uuid
        from support_core import state as safe_state
        command = self.saved[request_id]
        self.clock.sleep(.001)
        observed = self.probe.observe(allow_menu=True)
        value = safe_state(observed.tick)
        value.update(observed.state)
        value["player"] = {**safe_state(observed.tick)["player"], **observed.player}
        value["world"]["dimension"] = value["player"]["dimension"]
        value["client_action"] = deepcopy(self.action)
        payload = {"state": value}
        if command["op"] == "action":
            payload["action"] = {"action_session": self.native_id,
                "action_id": uuid.uuid5(uuid.UUID(self.session_id), request_id + ":1").hex,
                "action": command["action"], "status": "succeeded", "reason": "fixture_dispatched",
                "result": {"input_release_confirmed": True}}
            self.action = deepcopy(payload["action"])
            value["client_action"] = deepcopy(self.action)
        return {"request_id": request_id, "session_id": self.session_id,
                "status": "succeeded", "result": payload}


class ProductionRealRuntimeTests(unittest.TestCase):
    def test_crafting_through_actual_durable_runtime(self):
        import tempfile
        from support_core import Clock
        from mdc_skills.core import Runtime
        clock = Clock()
        client = GuardedMenuClient(_fixture.FakeQueueClient(), clock)
        with tempfile.TemporaryDirectory() as directory, Runtime(client, directory, clock=clock, sleeper=clock.sleep) as runtime:
            result = craft(runtime, "iron_pickaxe")
            self.assertTrue(result.ok)
            actions = [c for c in client.commands if c["op"] == "action"]
            self.assertEqual(sum(c["click_type"] == "quick_move" for c in actions), 1)
            self.assertTrue(all(c["capability_guard"]["schema_version"] == 1 for c in actions))
            self.assertIsNone(runtime.pending_request_id)
            records = json.loads((Path(directory) / "execution.json").read_text())["records"]
            mutations = [r for r in records.values() if r["kind"] == "mutation"]
            self.assertTrue(all(r["status"] == "succeeded" for r in mutations))

    def test_smelting_through_actual_durable_runtime(self):
        import tempfile
        from support_core import Clock
        from mdc_skills.core import Runtime
        clock = Clock()
        client = GuardedMenuClient(FurnaceClient(), clock)
        with tempfile.TemporaryDirectory() as directory, Runtime(client, directory, clock=clock, sleeper=clock.sleep) as runtime:
            result = smelt(runtime, "minecraft:raw_iron", count=2)
            self.assertTrue(result.ok)
            self.assertEqual(result.evidence["produced"], 2)
            self.assertIsNone(runtime.pending_request_id)
            self.assertEqual(sum(c.get("click_type") == "quick_move" for c in client.commands), 1)


if __name__ == "__main__":
    unittest.main()
