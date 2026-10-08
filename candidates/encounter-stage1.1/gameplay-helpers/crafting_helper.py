"""Explicit, single-batch shaped crafting through the existing QueueClient.

Importing this module does not open a queue, observe Minecraft, or send actions.
Call craft_once only when the caller has authorized this particular crafting step.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import time
import uuid

from resident_controller.ipc import QueueClient


PLANKS = tuple("minecraft:" + wood + "_planks" for wood in (
    "oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove",
    "cherry", "bamboo", "crimson", "warped"))
STONE = ("minecraft:cobblestone", "minecraft:cobbled_deepslate", "minecraft:blackstone")
IRON = ("minecraft:iron_ingot",)
STICK = ("minecraft:stick",)


@dataclass(frozen=True)
class Recipe:
    pattern: tuple[str, ...]
    ingredients: dict[str, tuple[str, ...]]
    count: int = 1


RECIPES = {
    "wooden_pickaxe": Recipe(("MMM", " S ", " S "), {"M": PLANKS, "S": STICK}),
    "stone_pickaxe": Recipe(("MMM", " S ", " S "), {"M": STONE, "S": STICK}),
    "stone_axe": Recipe(("MM", "MS", " S"), {"M": STONE, "S": STICK}),
    "iron_pickaxe": Recipe(("MMM", " S ", " S "), {"M": IRON, "S": STICK}),
    "iron_axe": Recipe(("MM", "MS", " S"), {"M": IRON, "S": STICK}),
    "shulker_box": Recipe(("S", "C", "S"), {"S": ("minecraft:shulker_shell",), "C": ("minecraft:chest",)}),
    "iron_sword": Recipe(("M", "M", "S"), {"M": IRON, "S": STICK}),
    "shield": Recipe(("PIP", "PPP", " P "), {"P": PLANKS, "I": IRON}),
    "furnace": Recipe(("MMM", "M M", "MMM"), {"M": STONE}),
    "iron_helmet": Recipe(("MMM", "M M"), {"M": IRON}),
    "iron_chestplate": Recipe(("M M", "MMM", "MMM"), {"M": IRON}),
    "iron_leggings": Recipe(("MMM", "M M", "M M"), {"M": IRON}),
    "iron_boots": Recipe(("M M", "M M"), {"M": IRON}),
    "bucket": Recipe(("M M", " M "), {"M": IRON}),
    "stone_hoe": Recipe(("MM", " S", " S"), {"M": STONE, "S": STICK}),
    "iron_hoe": Recipe(("MM", " S", " S"), {"M": IRON, "S": STICK}),
    # These also exercise actual 2x2 InventoryMenu crafting, without opening UI.
    "stick": Recipe(("M", "M"), {"M": PLANKS}, count=4),
    "torch": Recipe(("C", "S"), {"C": ("minecraft:coal", "minecraft:charcoal"), "S": STICK}, count=4),
    "crafting_table": Recipe(("MM", "MM"), {"M": PLANKS}),
}


class CraftStopped(RuntimeError):
    """Do not automatically rerun. Inspect request_id and the current menu first."""
    def __init__(self, reason, *, request_id=None, request_ids=(), state=None):
        super().__init__(reason)
        self.reason = reason
        self.request_id = request_id
        self.request_ids = tuple(request_ids)
        self.state = state


def _require(condition, reason):
    if not condition:
        raise CraftStopped(reason)


def _item(item):
    _require(isinstance(item, dict), "invalid_item_observation")
    count = item.get("count")
    _require(type(count) is int and count >= 0, "invalid_item_count")
    if count == 0:
        _require(item.get("empty") is True, "ambiguous_empty_item")
        return ("", 0, 0)
    _require(item.get("empty") is False and isinstance(item.get("id"), str)
             and item["id"].startswith("minecraft:"), "invalid_item_identity")
    damage = item.get("damage", 0)
    _require(type(damage) is int and damage >= 0, "invalid_item_damage")
    return item["id"], count, damage


EMPTY = ("", 0, 0)


class View:
    def __init__(self, state):
        _require(isinstance(state, dict), "state_missing")
        self.state = state
        player = state.get("player", {})
        _require(isinstance(player, dict), "player_missing")
        health = player.get("health")
        _require(isinstance(health, (float, int)) and math.isfinite(health) and health > 0,
                 "player_not_alive_or_health_missing")
        menu = state.get("menu", {})
        _require(isinstance(menu, dict), "menu_missing")
        kind = menu.get("menu_class")
        types = {"net.minecraft.world.inventory.InventoryMenu": 2,
                 "net.minecraft.world.inventory.CraftingMenu": 3}
        _require(kind in types, "requires_vanilla_inventory_or_crafting_menu")
        self.width = types[kind]
        container = menu.get("container_id")
        _require(type(container) is int and (container == 0 if self.width == 2 else container > 0),
                 "invalid_container_id")
        _require(menu.get("slots_truncated") is False and isinstance(menu.get("slots"), list),
                 "incomplete_menu")
        self.container_id = container
        self.slots = {}
        self.storage = {}
        for slot in menu["slots"]:
            _require(isinstance(slot, dict), "invalid_slot")
            index = slot.get("menu_index")
            _require(type(index) is int and index >= 0 and index not in self.slots,
                     "duplicate_or_invalid_menu_index")
            self.slots[index] = slot
            _item(slot.get("item"))
            if slot.get("player_inventory") is True:
                inventory_index = slot.get("inventory_index")
                _require(type(inventory_index) is int and 0 <= inventory_index <= 40,
                         "invalid_inventory_index")
                if inventory_index <= 35:
                    _require(inventory_index not in self.storage and slot.get("active") is True,
                             "duplicate_or_inactive_player_storage")
                    self.storage[inventory_index] = index
        _require(set(self.storage) == set(range(36)), "incomplete_player_storage_mapping")
        # Exact vanilla menu classes have output at 0 and row-major inputs at
        # 1..4/1..9. Confirm those observed slots and their container-local indices.
        self.grid = tuple(range(1, self.width * self.width + 1))
        self.output = 0
        for index in (self.output,) + self.grid:
            slot = self.slots.get(index, {})
            _require(slot.get("active") is True and slot.get("player_inventory") is False,
                     "missing_or_inactive_crafting_slot")
            _require(slot.get("container_slot") == (index - 1 if index else 0),
                     "unexpected_crafting_slot_mapping")
        self.items = {index: _item(slot["item"]) for index, slot in self.slots.items()}
        self.carried = _item(menu.get("carried"))
        _require(player.get("inventory_truncated") is False
                 and isinstance(player.get("inventory"), list), "incomplete_player_inventory")
        inventory = {}
        for item in player["inventory"]:
            index = item.get("slot") if isinstance(item, dict) else None
            _require(type(index) is int and 0 <= index <= 35 and index not in inventory,
                     "invalid_player_inventory_slot")
            inventory[index] = _item(item)
        _require(set(inventory) == set(self.storage), "incomplete_player_inventory")
        _require(all(inventory[i] == self.items[s] for i, s in self.storage.items()),
                 "menu_and_inventory_disagree")
        world = state.get("world", {})
        _require(isinstance(world, dict) and world.get("world_generation")
                 and player.get("uuid"), "world_or_player_identity_missing")
        self.identity = (kind, container, world["world_generation"], player["uuid"],
                         player.get("dimension"))
        self.mapping = tuple(sorted((i, slot.get("player_inventory"),
                                     slot.get("inventory_index"), slot.get("container_slot"),
                                     slot.get("active")) for i, slot in self.slots.items()))

    def counts(self):
        counts = Counter()
        for index in self.storage.values():
            item, count, _ = self.items[index]
            if count:
                counts[item] += count
        return counts


class _Craft:
    def __init__(self, client, wait_timeout, settle_timeout):
        self.client = client
        self.wait_timeout = wait_timeout
        self.settle_timeout = settle_timeout
        self.request_ids = []
        self.completed = set()
        self.session_id = None
        self.last_state = None
        self.initial_view = None

    def call(self, command):
        # No queue consumption, credential access, raw input, takeover, resume,
        # cancellation, relaunch, reconnect, disconnect or respawn operations.
        session = self.client.session()
        # A completed click can briefly precede the resident's idle publication.
        # Wait on metadata only; never replay a game operation to bridge that gap.
        admission_deadline = time.monotonic() + 2.0
        while (isinstance(session, dict)
               and (session.get("state") == "busy" or session.get("pending", 0) != 0)
               and time.monotonic() < admission_deadline):
            time.sleep(0.02)
            session = self.client.session()
        _require(isinstance(session, dict) and session.get("session_id"), "session_missing")
        if self.session_id is None:
            self.session_id = session["session_id"]
        _require(session["session_id"] == self.session_id, "controller_session_changed")
        idle = session.get("state") == "ready"
        # A result can appear just before the resident publishes its idle state.
        own_completion = (session.get("state") == "busy"
                          and session.get("active_request_id") in self.completed)
        _require((idle or own_completion) and session.get("pending") == 0,
                 "controller_not_idle_do_not_interleave_commands")
        request_id = uuid.uuid4().hex
        self.request_ids.append(request_id)  # Retain even if submit itself raises.
        try:
            submitted = self.client.submit(command, request_id=request_id)
            _require(submitted == request_id, "unexpected_submitted_request_id")
            result = self.client.wait(request_id, timeout=self.wait_timeout)
        except Exception as exc:
            if isinstance(exc, CraftStopped):
                raise
            raise CraftStopped("queue_exchange_uncertain_" + type(exc).__name__,
                               request_id=request_id) from exc
        _require(isinstance(result, dict) and result.get("request_id") == request_id,
                 "result_request_mismatch")
        if result.get("status") != "succeeded":
            raise CraftStopped("request_" + str(result.get("status", "unknown"))
                               + ":" + str(result.get("reason", "")), request_id=request_id)
        _require(result.get("session_id") == self.session_id, "result_session_mismatch")
        self.completed.add(request_id)
        payload = result.get("result", {})
        _require(isinstance(payload, dict), "result_payload_missing")
        state = payload.get("state")
        self.last_state = state
        if command["op"] == "action":
            action = payload.get("action", {})
            _require(isinstance(action, dict) and action.get("status") == "succeeded",
                     "click_success_not_confirmed")
        view = View(state)
        if self.initial_view is None:
            self.initial_view = view
        else:
            _require(view.identity == self.initial_view.identity, "menu_world_or_player_changed")
            _require(view.mapping == self.initial_view.mapping, "menu_slot_mapping_changed")
        return view

    def observe(self):
        return self.call({"op": "observe"})

    def click(self, view, slot, button=0, click_type="pickup"):
        # Always use this live slot's menu_index, never player inventory indices.
        _require(slot in view.slots and view.slots[slot].get("active") is True,
                 "click_slot_not_observed_active")
        return self.call({"op": "action", "action": "click_slot",
                          "container_id": view.container_id, "slot": view.slots[slot]["menu_index"],
                          "button": button, "click_type": click_type, "timeout_ms": 3000})

    @staticmethod
    def check(view, expected, carried):
        _require(view.carried == carried, "cursor_change_not_observed_stop")
        _require(all(view.items[i] == item for i, item in expected.items() if i != view.output),
                 "inventory_or_grid_change_not_observed_stop")

    def wait_output(self, view, expected, output):
        deadline = time.monotonic() + self.settle_timeout
        while True:
            self.check(view, expected, EMPTY)
            if view.items[view.output] == output:
                return view
            _require(time.monotonic() < deadline, "requested_recipe_output_not_observed")
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            view = self.observe()

    def run(self, name, recipe):
        output_id = "minecraft:" + name
        view = self.observe()
        _require(view.carried == EMPTY and all(view.items[i] == EMPTY for i in view.grid),
                 "crafting_grid_or_cursor_not_empty")
        _require(view.items[view.output] == EMPTY, "initial_output_not_empty")
        _require(len(recipe.pattern) <= view.width and max(map(len, recipe.pattern)) <= view.width,
                 "recipe_requires_3x3_crafting_table_menu")
        before = view.counts()
        available = before.copy()
        placements = []
        for row, symbols in enumerate(recipe.pattern):
            for column, symbol in enumerate(symbols):
                if symbol == " ":
                    continue
                item = next((i for i in recipe.ingredients[symbol] if available[i] > 0), None)
                _require(item is not None, "missing_ingredient_" + symbol)
                available[item] -= 1
                placements.append((view.grid[row * view.width + column], item))
        expected = dict(view.items)
        consumed = Counter(item for _, item in placements)
        for target, item_id in placements:
            self.check(view, expected, EMPTY)
            source = next((s for s in view.storage.values()
                           if view.items[s][0] == item_id and view.items[s][1] > 0), None)
            _require(source is not None, "ingredient_disappeared")
            stack = view.items[source]
            _require(view.items[target] == EMPTY, "target_grid_slot_not_empty")
            view = self.click(view, source)
            expected[source] = EMPTY
            self.check(view, expected, stack)
            view = self.click(view, target, button=1)
            expected[target] = (item_id, 1, stack[2])
            remaining = (item_id, stack[1] - 1, stack[2]) if stack[1] > 1 else EMPTY
            self.check(view, expected, remaining)
            if remaining != EMPTY:
                view = self.click(view, source)
                expected[source] = remaining
                self.check(view, expected, EMPTY)
        view = self.wait_output(view, expected, (output_id, recipe.count, 0))
        # One output retrieval only. Exactly one ingredient per occupied input
        # prevents quick_move from crafting multiple batches.
        view = self.click(view, view.output, click_type="quick_move")
        after = before.copy()
        after.subtract(consumed)
        after[output_id] += recipe.count
        deadline = time.monotonic() + self.settle_timeout
        while True:
            if (view.counts() == after and view.carried == EMPTY
                    and all(view.items[i] == EMPTY for i in view.grid)
                    and view.items[view.output] == EMPTY):
                return {"status": "succeeded", "item_id": output_id, "added": recipe.count,
                        "before_count": before[output_id], "after_count": view.counts()[output_id],
                        "consumed": dict(consumed), "cursor_empty": True, "grid_empty": True,
                        "server_confirmed": False, "request_ids": tuple(self.request_ids),
                        "state": view.state}
            _require(time.monotonic() < deadline, "craft_inventory_delta_or_cleanup_not_observed")
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            view = self.observe()


def craft_once(client: QueueClient, recipe_name: str, *, expected_count: int | None = None,
               wait_timeout: float = 30.0, settle_timeout: float = 3.0) -> dict:
    """Craft one recipe batch using the caller's existing credential-free client.

    ``recipe_name`` accepts e.g. ``iron_pickaxe`` or ``minecraft:iron_pickaxe``.
    ``expected_count`` is the exact requested inventory increase for this batch;
    omitted means the recipe's output count. All required equipment yields one.
    Raises CraftStopped on missing data, interference, rejected actions, or
    uncertain completion. Preserve the exception's request IDs; do not replay.
    No GUI is opened/closed, and items are never dropped or automatically cleaned
    up on failure. A stop can therefore leave the cursor/grid partly populated.
    """
    _require(isinstance(recipe_name, str), "recipe_name_must_be_string")
    name = recipe_name.removeprefix("minecraft:")
    if name == "iron_bucket":
        name = "bucket"
    name = {"sticks": "stick", "torches": "torch"}.get(name, name)
    _require(name in RECIPES, "unsupported_recipe")
    recipe = RECIPES[name]
    _require(expected_count is None or (type(expected_count) is int and expected_count == recipe.count),
             "expected_count_must_equal_one_recipe_batch")
    for value in (wait_timeout, settle_timeout):
        _require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                 "timeouts_must_be_positive_finite_numbers")
    job = _Craft(client, wait_timeout, settle_timeout)
    try:
        return job.run(name, recipe)
    except Exception as exc:
        if isinstance(exc, CraftStopped):
            exc.request_ids = tuple(job.request_ids)
            exc.request_id = exc.request_id or (job.request_ids[-1] if job.request_ids else None)
            exc.state = job.last_state
            raise
        raise CraftStopped("craft_stopped_" + type(exc).__name__,
                           request_id=job.request_ids[-1] if job.request_ids else None,
                           request_ids=job.request_ids, state=job.last_state) from exc
