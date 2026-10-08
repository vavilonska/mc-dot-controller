"""Offline fake-QueueClient contract checks; no mailbox, socket, or game I/O."""
from copy import deepcopy
from collections import Counter
import unittest
from unittest.mock import patch

from crafting_helper import CraftStopped, RECIPES, craft_once


def item(name="", count=0):
    return {"id": "minecraft:" + name if name and ":" not in name else name if count else "",
            "count": count, "empty": count == 0, "damage": 0}


# Independent fixtures rather than generating the fake output from RECIPES.
SHAPES = {
    "shulker_box": ("H..", "B..", "H.."),
    "wooden_pickaxe": ("PPP", ".S.", ".S."),
    "stone_pickaxe": ("CCC", ".S.", ".S."),
    "stone_axe": ("CC.", "CS.", ".S."),
    "iron_pickaxe": ("III", ".S.", ".S."),
    "iron_axe": ("II.", "IS.", ".S."),
    "iron_sword": ("I..", "I..", "S.."),
    "shield": ("PIP", "PPP", ".P."),
    "furnace": ("CCC", "C.C", "CCC"),
    "iron_helmet": ("III", "I.I", "..."),
    "iron_chestplate": ("I.I", "III", "III"),
    "iron_leggings": ("III", "I.I", "I.I"),
    "iron_boots": ("I.I", "I.I", "..."),
    "bucket": ("I.I", ".I.", "..."),
    "stone_hoe": ("CC.", ".S.", ".S."),
    "iron_hoe": ("II.", ".S.", ".S."),
    "stick": ("P..", "P..", "..."),
    "crafting_table": ("PP.", "PP.", "..."),
    "torch": ("F..", "S..", "..."),
}


class FakeQueueClient:
    """Minimal scripted ordinary-click contract, not a Minecraft simulation."""
    def __init__(self, width=3, stock=None):
        self.width = width
        self.container = 7 if width == 3 else 0
        self.session_id = "offline-session"
        self.session_state = "ready"
        self.pending = 0
        self.commands = []
        self.results = {}
        self.slots = {i: item() for i in range(width * width + 1)}
        # Deliberately nonstandard, shuffled storage indices: the caller MUST use
        # observed player_inventory/inventory_index, never 36 + hotbar index.
        self.storage = {i: 100 + (i * 13) % 36 for i in range(36)}
        self.slots.update({s: item() for s in self.storage.values()})
        stock = stock if stock is not None else {
            0: ("iron_ingot", 64), 5: ("cobblestone", 64),
            9: ("stick", 10), 31: ("oak_planks", 64), 35: ("coal", 8), 20: ("shulker_shell", 2), 21: ("chest", 1)}
        for index, (name, count) in stock.items():
            self.slots[self.storage[index]] = item(name, count)
        self.carried = item()
        self.hook = None
        self.mutate_snapshot = None
        self.quick_moves = 0
        self.output_override = None
        self.state_identity = "offline-world"
        self.unconsumed = False
        self.final_pending_observes = 0
        self.pending_output = None

    def session(self):
        return {"session_id": self.session_id, "state": self.session_state,
                "pending": self.pending, "active_request_id": None}

    def snapshot(self):
        reverse = {v: k for k, v in self.storage.items()}
        slots = []
        for index, value in self.slots.items():
            slot = {"menu_index": index, "container_slot": reverse.get(index, max(0, index - 1)),
                    "player_inventory": index in reverse, "active": True, "item": deepcopy(value)}
            if index in reverse:
                slot["inventory_index"] = reverse[index]
            slots.append(slot)
        state = {"menu": {"menu_class": "net.minecraft.world.inventory."
                         + ("InventoryMenu" if self.width == 2 else "CraftingMenu"),
                         "container_id": self.container, "slots_truncated": False,
                         "slots": list(reversed(slots)), "carried": deepcopy(self.carried)},
                 "player": {"health": 20.0, "uuid": "offline-player", "dimension": "minecraft:overworld",
                            "inventory_truncated": False, "inventory": [
                                dict(deepcopy(self.slots[s]), slot=i) for i, s in self.storage.items()]},
                 "world": {"world_generation": self.state_identity}}
        if self.mutate_snapshot:
            self.mutate_snapshot(state)
        return state

    def update_output(self):
        symbols = []
        for i in range(1, self.width * self.width + 1):
            name = self.slots[i]["id"].removeprefix("minecraft:")
            symbol = ("P" if name.endswith("_planks") else
                      "C" if name in ("cobblestone", "blackstone", "cobbled_deepslate") else
                      "I" if name == "iron_ingot" else "S" if name == "stick" else
                      "H" if name == "shulker_shell" else "B" if name == "chest" else
                      "F" if name in ("coal", "charcoal") else "." if not name else "?")
            symbols.append(symbol)
        padded = tuple("".join(symbols[r * self.width:(r + 1) * self.width]).ljust(3, ".")
                       if r < self.width else "..." for r in range(3))
        name = next((name for name, shape in SHAPES.items() if padded == shape), "")
        self.slots[0] = item(name, (4 if name in ("torch", "stick") else 1) if name else 0)
        if self.output_override and name:
            self.slots[0] = item(self.output_override, 1)

    def finish_output(self, output):
        destination = next(s for s in self.storage.values()
                           if self.slots[s]["empty"] or self.slots[s]["id"] == output["id"])
        previous = self.slots[destination]["count"]
        self.slots[destination] = dict(output, count=previous + output["count"])
        for i in range(self.width * self.width + 1):
            self.slots[i] = item()

    def submit(self, command, request_id=None):
        self.commands.append(deepcopy(command))
        result = {"request_id": request_id, "session_id": self.session_id, "status": "succeeded"}
        execute = True
        if self.hook:
            execute = self.hook(self, command, result) is not False
        if execute and command["op"] == "action":
            assert command["action"] == "click_slot"
            assert command["container_id"] == self.container
            slot = command["slot"]
            if command["click_type"] == "quick_move":
                assert slot == 0 and not self.slots[0]["empty"]
                self.quick_moves += 1
                if self.final_pending_observes:
                    self.pending_output = deepcopy(self.slots[0])
                elif not self.unconsumed:
                    self.finish_output(deepcopy(self.slots[0]))
            elif command["button"] == 1:
                assert not self.carried["empty"] and self.slots[slot]["empty"]
                self.slots[slot] = dict(self.carried, count=1)
                self.carried = (dict(self.carried, count=self.carried["count"] - 1)
                                if self.carried["count"] > 1 else item())
            else:
                self.carried, self.slots[slot] = self.slots[slot], self.carried
            self.update_output()
        elif execute and command["op"] == "observe" and self.pending_output:
            self.final_pending_observes -= 1
            if not self.final_pending_observes:
                self.finish_output(self.pending_output)
                self.pending_output = None
        payload = {"state": self.snapshot()}
        if command["op"] == "action":
            payload["action"] = {"status": "succeeded"}
        result["result"] = payload
        self.results[request_id] = result
        return request_id

    def wait(self, request_id, timeout=30):
        return deepcopy(self.results[request_id])


class CraftChecks(unittest.TestCase):
    def test_transient_busy_and_pending_waits_without_replay(self):
        client = FakeQueueClient()
        original = client.session
        states = [{"state": "busy", "pending": 0}, {"state": "ready", "pending": 1}]
        def session():
            data = original()
            if states:
                data.update(states.pop(0))
            return data
        client.session = session
        with patch("crafting_helper.time.sleep"):
            result = self.craft(client, "shield")
        self.assertEqual(result["added"], 1)
        self.assertEqual(client.quick_moves, 1)

    def craft(self, client, name, **kwargs):
        return craft_once(client, name, settle_timeout=0.001, **kwargs)

    def test_all_required_recipes_and_requested_extras(self):
        self.assertEqual(set(RECIPES), set(SHAPES))
        for name in SHAPES:
            with self.subTest(name=name):
                client = FakeQueueClient()
                result = self.craft(client, name)
                self.assertEqual(result["item_id"], "minecraft:" + name)
                self.assertEqual(result["added"], 4 if name in ("stick", "torch") else 1)
                self.assertEqual(result["after_count"] - result["before_count"], result["added"])
                self.assertEqual(client.quick_moves, 1)
                self.assertTrue(result["cursor_empty"] and result["grid_empty"])
                self.assertFalse(result["server_confirmed"])
                self.assertTrue(all(c["op"] in ("observe", "action") for c in client.commands))
                self.assertTrue(all(c.get("click_type", "pickup") in ("pickup", "quick_move")
                                    for c in client.commands))
                inputs = [c for c in client.commands if c.get("button") == 1]
                self.assertEqual(len(inputs), sum(result["consumed"].values()))

    def test_2x2_grid_supported_and_3x3_required_recipes_rejected_before_click(self):
        for name in ("crafting_table", "stick", "torch"):
            with self.subTest(name=name):
                self.craft(FakeQueueClient(width=2), name)
        for name in ("iron_boots", "bucket", "iron_hoe", "wooden_pickaxe", "furnace", "shulker_box"):
            client = FakeQueueClient(width=2)
            with self.assertRaisesRegex(CraftStopped, "3x3"):
                self.craft(client, name)
            self.assertEqual(len(client.commands), 1)

    def test_live_inventory_mapping_and_return_remainder(self):
        client = FakeQueueClient()
        self.craft(client, "iron_pickaxe")
        first = client.commands[1]
        self.assertEqual(first["slot"], client.storage[0])
        self.assertEqual(client.slots[client.storage[0]]["count"], 61)
        self.assertEqual(client.slots[client.storage[9]]["count"], 8)

    def test_single_items_and_split_material_stacks(self):
        client = FakeQueueClient(stock={0: ("iron_ingot", 1), 1: ("iron_ingot", 1),
                                       2: ("iron_ingot", 1)})
        result = self.craft(client, "iron_bucket")
        self.assertEqual(result["consumed"], {"minecraft:iron_ingot": 3})
        self.assertEqual(len([c for c in client.commands if c.get("action")]), 7)

    def test_alternative_materials_and_plural_aliases(self):
        self.craft(FakeQueueClient(stock={0: ("blackstone", 3), 1: ("stick", 2)}), "stone_pickaxe")
        result = self.craft(FakeQueueClient(width=2, stock={0: ("cherry_planks", 1),
                                                         1: ("bamboo_planks", 1)}), "sticks")
        self.assertEqual(result["added"], 4)
        self.craft(FakeQueueClient(width=2, stock={0: ("charcoal", 1), 1: ("stick", 1)}), "torches")

    def test_dirty_cursor_or_grid_rejects_before_click(self):
        for dirty in ("cursor", "grid", "output"):
            client = FakeQueueClient()
            if dirty == "cursor":
                client.carried = item("iron_ingot", 1)
            else:
                client.slots[0 if dirty == "output" else 9] = item("iron_ingot", 1)
            with self.assertRaises(CraftStopped):
                self.craft(client, "iron_pickaxe")
            self.assertEqual(len(client.commands), 1)

    def test_missing_ingredients_rejects_before_click(self):
        client = FakeQueueClient(stock={0: ("iron_ingot", 2), 1: ("stick", 2)})
        with self.assertRaisesRegex(CraftStopped, "missing_ingredient"):
            self.craft(client, "iron_pickaxe")
        self.assertEqual(len(client.commands), 1)

    def test_invalid_count_or_recipe_does_not_even_observe(self):
        client = FakeQueueClient()
        for name, count in (("iron_pickaxe", 2), ("stick", 1), ("unknown", 1), ("bucket", True)):
            with self.assertRaises(CraftStopped):
                self.craft(client, name, expected_count=count)
        self.assertEqual(client.commands, [])

    def test_invalid_observation_rejects_before_click(self):
        def changes():
            yield lambda s: s["menu"].update(slots_truncated=True)
            yield lambda s: s["menu"].update(menu_class="other.CraftingMenu")
            yield lambda s: s["player"].update(health=0)
            yield lambda s: s["player"].update(inventory_truncated=True)
            yield lambda s: s["menu"]["slots"][0].update(inventory_index=99)
            yield lambda s: s["menu"]["slots"].pop()
            yield lambda s: s["player"]["inventory"][0].update(count=1)
            yield lambda s: s["menu"]["slots"].append(s["menu"]["slots"][0])
        for change in changes():
            client = FakeQueueClient()
            client.mutate_snapshot = change
            with self.assertRaises(CraftStopped):
                self.craft(client, "iron_pickaxe")
            self.assertEqual(len(client.commands), 1)

    def test_busy_or_paused_controller_is_not_taken_over(self):
        for state in ("busy", "paused", "stopped"):
            client = FakeQueueClient()
            client.session_state = state
            with self.assertRaisesRegex(CraftStopped, "not_idle"):
                self.craft(client, "iron_pickaxe")
            self.assertEqual(client.commands, [])

    def test_pending_failed_cancelled_uncertain_action_not_replayed(self):
        for status in ("pending", "failed", "cancelled", "uncertain"):
            client = FakeQueueClient()
            def fail(queue, command, result):
                if command["op"] == "action":
                    result["status"] = status
                    return False
            client.hook = fail
            with self.assertRaises(CraftStopped) as caught:
                self.craft(client, "iron_pickaxe")
            self.assertEqual(len(client.commands), 2)
            self.assertEqual(len(caught.exception.request_ids), 2)
            self.assertEqual(caught.exception.request_id, caught.exception.request_ids[-1])

    def test_submit_exception_preserves_id_and_does_not_retry(self):
        client = FakeQueueClient()
        def fail(queue, command, result):
            if command["op"] == "action":
                raise OSError("simulated uncertain submit")
        client.hook = fail
        with self.assertRaisesRegex(CraftStopped, "queue_exchange_uncertain") as caught:
            self.craft(client, "iron_pickaxe")
        self.assertEqual(len(client.commands), 2)
        self.assertTrue(caught.exception.request_id)

    def test_wrong_click_effect_stops_without_cleanup_or_retry(self):
        client = FakeQueueClient()
        def ignore_right_click(queue, command, result):
            return command.get("button") != 1
        client.hook = ignore_right_click
        with self.assertRaisesRegex(CraftStopped, "not_observed_stop"):
            self.craft(client, "iron_pickaxe")
        self.assertEqual(len(client.commands), 3)
        self.assertEqual(client.carried["count"], 64)

    def test_wrong_actual_output_is_never_retrieved(self):
        client = FakeQueueClient()
        client.output_override = "diamond_pickaxe"
        with self.assertRaisesRegex(CraftStopped, "requested_recipe_output_not_observed"):
            self.craft(client, "iron_pickaxe")
        self.assertEqual(client.quick_moves, 0)

    def test_final_output_move_never_replayed_if_inventory_does_not_change(self):
        client = FakeQueueClient()
        client.unconsumed = True
        with self.assertRaisesRegex(CraftStopped, "craft_inventory_delta"):
            self.craft(client, "iron_pickaxe")
        self.assertEqual(client.quick_moves, 1)

    def test_delayed_output_confirmation_only_observes(self):
        client = FakeQueueClient()
        client.final_pending_observes = 2
        with patch("crafting_helper.time.sleep"):
            result = craft_once(client, "iron_pickaxe", settle_timeout=1)
        self.assertEqual(result["added"], 1)
        self.assertEqual(client.quick_moves, 1)
        self.assertEqual(client.commands[-1], {"op": "observe"})

    def test_world_menu_and_session_changes_stop(self):
        for changed in ("world", "container", "session"):
            client = FakeQueueClient()
            def change(queue, command, result):
                if command["op"] == "action":
                    if changed == "world":
                        queue.state_identity = "different-world"
                    elif changed == "container":
                        queue.container = 9
                        return False
                    else:
                        queue.session_id = "different-controller"
            client.hook = change
            with self.assertRaises(CraftStopped):
                self.craft(client, "iron_pickaxe")
            self.assertEqual(len(client.commands), 2)

    def test_observed_storage_interference_stops_before_next_click(self):
        client = FakeQueueClient()
        def interfere(queue, command, result):
            if command.get("button") == 1:
                queue.slots[queue.storage[35]] = item("coal", 9)
        client.hook = interfere
        with self.assertRaisesRegex(CraftStopped, "inventory_or_grid_change"):
            self.craft(client, "iron_pickaxe")
        self.assertEqual(len(client.commands), 3)
        self.assertEqual(client.quick_moves, 0)

    def test_changed_slot_mapping_stops_before_next_click(self):
        client = FakeQueueClient()
        def change(queue, command, result):
            if command["op"] == "action":
                queue.storage[1], queue.storage[2] = queue.storage[2], queue.storage[1]
        client.hook = change
        with self.assertRaisesRegex(CraftStopped, "mapping_changed"):
            self.craft(client, "iron_pickaxe")
        self.assertEqual(len(client.commands), 2)

    def test_unknown_result_identity_is_not_replayed(self):
        for changed in ("session_id", "request_id"):
            client = FakeQueueClient()
            def wrong_identity(queue, command, result):
                result[changed] = "incorrect-result-identity"
            client.hook = wrong_identity
            with self.assertRaises(CraftStopped):
                self.craft(client, "iron_pickaxe")
            self.assertEqual(len(client.commands), 1)

    def test_nonempty_final_cursor_prevents_success_after_one_output_click(self):
        client = FakeQueueClient()
        def change(queue, command, result):
            if command.get("click_type") == "quick_move":
                queue.carried = item("iron_ingot", 1)
        client.hook = change
        with self.assertRaisesRegex(CraftStopped, "craft_inventory_delta"):
            self.craft(client, "iron_pickaxe")
        self.assertEqual(client.quick_moves, 1)

    def test_zero_negative_infinite_and_boolean_timeouts_rejected_without_observing(self):
        client = FakeQueueClient()
        for value in (0, -1, float("inf"), float("nan"), True):
            with self.assertRaisesRegex(CraftStopped, "timeouts"):
                craft_once(client, "iron_pickaxe", wait_timeout=value)
        self.assertEqual(client.commands, [])


if __name__ == "__main__":
    unittest.main()
