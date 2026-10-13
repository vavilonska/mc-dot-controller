"""Bounded, observed vanilla crafting and furnace production.

No transport, credentials, game start, recipe-book commands or background retry.
Every click uses the observed menu index and an atomic native item/menu guard.
Supported recipes/stations/fuels are explicit; output identity is observed, not
inferred from a successful click. Partial cursor/grid contents are left intact
on any stop. Do not restart an interrupted production call blindly.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import json
from pathlib import Path
import time

from crafting_helper import RECIPES as BASE_RECIPES, Recipe, View, CraftStopped, EMPTY, _item, PLANKS
from .core import SkillError, require


STATIONS = {
    "minecraft:crafting_table": "net.minecraft.world.inventory.CraftingMenu",
    "minecraft:furnace": "net.minecraft.world.inventory.FurnaceMenu",
    "minecraft:blast_furnace": "net.minecraft.world.inventory.BlastFurnaceMenu",
    "minecraft:smoker": "net.minecraft.world.inventory.SmokerMenu",
}
# Reuse the audited shaped recipe vocabulary; additional log->plank recipes are
# explicit vanilla identities rather than a wildcard suffix conversion.
CRAFT_RECIPES = dict(BASE_RECIPES)
# Ordinary chest supports the shulker-box goal without a manual intermediate.
CRAFT_RECIPES["chest"] = Recipe(("PPP", "P P", "PPP"), {"P": PLANKS})
for _wood in ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry"):
    CRAFT_RECIPES[_wood + "_planks"] = Recipe(("L",), {"L": tuple(
        f"minecraft:{prefix}{_wood}_{suffix}" for prefix in ("", "stripped_")
        for suffix in ("log", "wood"))}, count=4)

# Exact shaped recipes extracted from the pinned official1.21.1 client JAR.
# Each recipe retains its source-path/hash in the bundled data for offline audit.
_BUILD_RECIPES = json.loads(Path(__file__).with_name("vanilla_building_recipes.json").read_text())
for _name, _recipe in _BUILD_RECIPES["recipes"].items():
    CRAFT_RECIPES[_name] = Recipe(tuple(_recipe["pattern"]),
        {symbol: tuple(items) for symbol, items in _recipe["ingredients"].items()}, _recipe["count"])


@dataclass(frozen=True)
class SmeltingRecipe:
    input_id: str
    output_id: str
    stations: tuple[str, ...]
    furnace_ticks: int = 200


SMELTING_RECIPES = {}
for _source, _output in (("raw_iron", "iron_ingot"), ("iron_ore", "iron_ingot"),
                         ("deepslate_iron_ore", "iron_ingot"), ("raw_gold", "gold_ingot"),
                         ("gold_ore", "gold_ingot"), ("deepslate_gold_ore", "gold_ingot"),
                         ("raw_copper", "copper_ingot"), ("copper_ore", "copper_ingot"),
                         ("deepslate_copper_ore", "copper_ingot")):
    SMELTING_RECIPES["minecraft:" + _source] = SmeltingRecipe(
        "minecraft:" + _source, "minecraft:" + _output,
        ("minecraft:furnace", "minecraft:blast_furnace"))
for _source, _output in (("cobblestone", "stone"), ("stone", "smooth_stone"),
                         ("sand", "glass"), ("red_sand", "glass"), ("clay_ball", "brick"),
                         ("sandstone", "smooth_sandstone"), ("quartz_block", "smooth_quartz"), ("netherrack", "nether_brick")):
    SMELTING_RECIPES["minecraft:" + _source] = SmeltingRecipe(
        "minecraft:" + _source, "minecraft:" + _output, ("minecraft:furnace",))
for _source, _output in (("beef", "cooked_beef"), ("porkchop", "cooked_porkchop"),
                         ("chicken", "cooked_chicken"), ("mutton", "cooked_mutton"),
                         ("rabbit", "cooked_rabbit"), ("cod", "cooked_cod"),
                         ("salmon", "cooked_salmon"), ("potato", "baked_potato")):
    SMELTING_RECIPES["minecraft:" + _source] = SmeltingRecipe(
        "minecraft:" + _source, "minecraft:" + _output,
        ("minecraft:furnace", "minecraft:smoker"))
for _wood in ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry"):
    for _prefix in ("", "stripped_"):
        for _suffix in ("log", "wood"):
            _source = f"minecraft:{_prefix}{_wood}_{_suffix}"
            SMELTING_RECIPES[_source] = SmeltingRecipe(_source, "minecraft:charcoal", ("minecraft:furnace",))
# Only fuels with no returned container. Durations are ordinary-furnace ticks;
# smoker/blast-furnace halve both cooking and fuel time, preserving this ratio.
FUELS = {"minecraft:coal": 1600, "minecraft:charcoal": 1600,
         "minecraft:coal_block": 16000, "minecraft:stick": 100}
for _wood in ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry",
              "bamboo", "crimson", "warped"):
    FUELS[f"minecraft:{_wood}_planks"] = 300
# Nonflammable Nether wood is deliberately excluded.
FUELS.pop("minecraft:crimson_planks")
FUELS.pop("minecraft:warped_planks")


def _normal_item(value):
    try:
        return _item(value)
    except CraftStopped as exc:
        raise SkillError(exc.reason) from exc


def _craft_view(observation):
    try:
        view = View(observation.state)
    except CraftStopped as exc:
        raise SkillError(exc.reason) from exc
    _state_id(view)
    _require_item_bindings(view)
    return view


def _state_id(view):
    value = view.state.get("menu", {}).get("state_id")
    require(type(value) is int and value >= 0, "menu_state_id_missing")
    return value



def _require_item_bindings(view):
    """Reject legacy/partial item snapshots before any production mutation."""
    menu = view.state["menu"]
    for value in [s["item"] for s in view.slots.values()] + [menu["carried"]]:
        require(isinstance(value.get("item_fingerprint"), str) and bool(value["item_fingerprint"])
                and isinstance(value.get("component_fingerprint"), str) and bool(value["component_fingerprint"]),
                "production_exact_item_fingerprints_required")
    inventory = {i["slot"]: i for i in view.state["player"]["inventory"]}
    require(all(inventory[i].get("item_fingerprint") == view.slots[slot]["item"].get("item_fingerprint")
                for i, slot in view.storage.items()), "production_menu_inventory_fingerprints_disagree")


def _component_flow(before, after, clicked, click_type):
    # Full fingerprints retain custom components even where inventory counts are
    # unchanged. Count-changing splits preserve the component-only fingerprint.
    for slot in before.slots:
        a, b = before.items[slot], after.items.get(slot)
        if b is None:
            return False
        old, new = before.slots[slot]["item"], after.slots[slot]["item"]
        if a[0] and a[0] == b[0]:
            if old["component_fingerprint"] != new["component_fingerprint"]:
                return False
            if a == b and old["item_fingerprint"] != new["item_fingerprint"]:
                return False
    old_cursor = before.state["menu"]["carried"]
    new_cursor = after.state["menu"]["carried"]
    if click_type == "pickup":
        if after.carried != EMPTY:
            origin = before.slots[clicked]["item"] if before.carried == EMPTY else old_cursor
            if new_cursor["component_fingerprint"] != origin["component_fingerprint"]:
                return False
        if before.carried != EMPTY and after.items[clicked] != EMPTY:
            if after.slots[clicked]["item"]["component_fingerprint"] != old_cursor["component_fingerprint"]:
                return False
    elif click_type == "quick_move":
        output = before.slots[clicked]["item"]
        for slot in before.storage.values():
            old, new = before.slots[slot]["item"], after.slots[slot]["item"]
            if old["item_fingerprint"] == new["item_fingerprint"]:
                continue
            if not (new.get("id") == output.get("id") and (old.get("empty") is True or old.get("id") == output.get("id"))
                    and new.get("count", 0) > old.get("count", 0)
                    and new["component_fingerprint"] == output["component_fingerprint"]):
                return False
    return True


def _same_menu(before, after):
    require(before.identity == after.identity, "production_menu_or_identity_changed")
    require(before.mapping == after.mapping, "production_menu_mapping_changed")


def _counts(view):
    return +view.counts()


def _expected_counts(before, consumed, output=None):
    value = before.copy()
    value.subtract(consumed)
    require(all(n >= 0 for n in value.values()), "production_inventory_underflow")
    if output:
        value[output[0]] += output[1]
    return +value


class _Budget:
    def __init__(self, limit):
        require(type(limit) is int and 1 <= limit <= 4096, "production_action_budget_must_be_1_to_4096")
        self.remaining = limit
        self.request_ids = []
        self.observations = []

    def execute(self, runtime, command, verify, before):
        require(self.remaining > 0, "production_action_budget_exhausted")
        self.remaining -= 1
        outcome = runtime.execute("production", command, verify, before=before, allow_menu=True)
        self.request_ids.extend(outcome.request_ids)
        obs = runtime.require_success(outcome)
        self.observations.append(obs)
        return obs


def _click(runtime, budget, observation, view, slot, check, *, button=0, click_type="pickup", reader=_craft_view):
    require(slot in view.slots and view.slots[slot].get("active") is True,
            "production_click_target_not_observed_active")
    menu = view.state["menu"]
    command = {"op": "action", "action": "click_slot", "container_id": view.container_id,
               "slot": slot, "button": button, "click_type": click_type, "timeout_ms": 3000,
               "expected_menu_state_id": _state_id(view),
               "expected_slot_item": dict(view.slots[slot]["item"]),
               "expected_carried": dict(menu["carried"])}

    def verify(_before, after):
        other = reader(after)
        _same_menu(view, other)
        return _component_flow(view, other, slot, click_type) and bool(check(other))

    return budget.execute(runtime, command, verify, observation)


def _check_items(view, expected, carried, *, ignore=()):
    return (view.carried == carried and all(view.items.get(slot) == value
            for slot, value in expected.items() if slot not in ignore))


def _wait(runtime, observation, reader, check, *, seconds, max_samples, poll_seconds=0.1):
    require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 600,
            "production_wait_must_be_positive_at_most_600_seconds")
    require(type(max_samples) is int and 2 <= max_samples <= 6000, "invalid_production_wait_samples")
    clock = getattr(runtime, "clock", time.monotonic)
    sleeper = getattr(runtime, "sleeper", time.sleep)
    deadline = clock() + seconds
    original = reader(observation)
    last_tick = observation.tick
    stable = 0
    for _ in range(max_samples):
        require(clock() <= deadline, "production_wait_deadline_reached_no_replay")
        sleeper(min(poll_seconds, max(0, deadline - clock())))
        observation = runtime.observe(allow_menu=True)
        other = reader(observation)
        _same_menu(original, other)
        require(_component_flow(original, other, 0, "observe"), "production_components_changed_during_wait")
        require(observation.tick >= last_tick, "production_tick_regressed")
        if check(other) and observation.tick > last_tick:
            stable += 1
        else:
            stable = 0
        last_tick = observation.tick
        if stable >= 2:
            return observation
    raise SkillError("production_wait_sample_budget_exhausted_no_replay")


def open_workstation(runtime, position, block_id, *, face="up"):
    """Open an observed vanilla workstation using exactly one native interaction."""
    require(block_id in STATIONS, "unsupported_workstation")
    require(isinstance(position, dict) and set(position) == {"x", "y", "z"}
            and all(type(v) is int for v in position.values()), "invalid_workstation_position")
    require(face in ("up", "down", "north", "south", "east", "west"), "invalid_workstation_face")
    before = runtime.observe(terrain=True, radius=4, vertical=4, allow_menu=True)
    menu = before.state.get("menu", {})
    require(menu.get("container_id") == 0 and before.state.get("screen_open") is False,
            "close_existing_container_before_workstation_interaction")
    require(_normal_item(menu.get("carried")) == EMPTY, "workstation_cursor_must_be_empty")
    wanted = STATIONS[block_id]
    return runtime.execute("production.open_workstation", {
        "op": "action", "action": "interact_block", "target": dict(position), "face": face,
        "expected_block_id": block_id, "timeout_ms": 3000,
    }, lambda _b, a: a.state.get("menu", {}).get("menu_class") == wanted
        and type(a.state.get("menu", {}).get("container_id")) is int
        and a.state["menu"]["container_id"] > 0
        and _normal_item(a.state["menu"].get("carried")) == EMPTY,
        before=before, allow_menu=True)


def close_workstation(runtime):
    """Close a menu only with an empty cursor, preserving its machine contents."""
    before = runtime.observe(allow_menu=True)
    menu = before.state.get("menu", {})
    require(_normal_item(menu.get("carried")) == EMPTY, "cannot_close_menu_with_carried_items")
    if menu.get("container_id") == 0 and before.state.get("screen_open") is False:
        return runtime.result("production.close_workstation", (before,), menu_closed=True)
    require(type(menu.get("container_id")) is int and menu["container_id"] >= 0
            and type(menu.get("state_id")) is int, "invalid_menu_close_identity")
    return runtime.execute("production.close_workstation", {
        "op": "action", "action": "close_menu", "container_id": menu["container_id"],
        "expected_menu_state_id": menu["state_id"], "expected_carried": dict(menu["carried"]),
        "timeout_ms": 3000}, lambda _b, a: a.state.get("menu", {}).get("container_id") == 0
        and a.state.get("screen_open") is False, before=before, allow_menu=True)


def craft(runtime, recipe_name, *, batches=1, station=None, max_actions=1024, ingredients=None):
    """Craft 1..32 exact batches from the explicit CRAFT_RECIPES vocabulary.

    station optionally supplies {position, block_id:'minecraft:crafting_table',
    face}. A 3x3 recipe otherwise requires the already-open CraftingMenu. The
    menu is left open. Ingredients and output space are checked before recipe clicks.
    """
    require(isinstance(recipe_name, str), "invalid_recipe_name")
    name = recipe_name.removeprefix("minecraft:")
    name = {"iron_bucket": "bucket", "sticks": "stick", "torches": "torch"}.get(name, name)
    require(name in CRAFT_RECIPES, "unsupported_crafting_recipe")
    require(type(batches) is int and 1 <= batches <= 32, "craft_batches_must_be_1_to_32")
    budget = _Budget(max_actions)
    recipe = CRAFT_RECIPES[name]
    if ingredients is not None:
        require(isinstance(ingredients, dict) and set(ingredients) == set(recipe.ingredients)
                and all(isinstance(value, str) and value in recipe.ingredients[key] for key, value in ingredients.items()),
                "invalid_recipe_ingredient_binding")
    output_id = "minecraft:" + name
    recipe_actions = batches * (3 * sum(symbol != " " for row in recipe.pattern for symbol in row) + 1)
    require(budget.remaining >= recipe_actions + int(station is not None), "crafting_action_budget_insufficient_before_start")
    if station is not None:
        require(isinstance(station, dict) and station.get("block_id") == "minecraft:crafting_table",
                "crafting_station_must_be_crafting_table")
        outcome = open_workstation(runtime, station.get("position"), station["block_id"], face=station.get("face", "up"))
        budget.remaining -= 1
        budget.request_ids.extend(outcome.request_ids)
        runtime.require_success(outcome)
    observation = runtime.observe(allow_menu=True)
    view = _craft_view(observation)
    require(view.carried == EMPTY and all(view.items[i] == EMPTY for i in (view.output,) + view.grid),
            "crafting_grid_output_and_cursor_must_be_empty")
    require(len(recipe.pattern) <= view.width and max(map(len, recipe.pattern)) <= view.width,
            "recipe_requires_3x3_crafting_table_menu")
    first = _counts(view)
    available = first.copy()
    all_placements = []
    for _ in range(batches):
        placements = []
        for row, symbols in enumerate(recipe.pattern):
            for column, symbol in enumerate(symbols):
                if symbol == " ":
                    continue
                choices = (ingredients[symbol],) if ingredients is not None else recipe.ingredients[symbol]
                ingredient = next((i for i in choices if available[i] > 0), None)
                require(ingredient is not None, "missing_crafting_ingredient_" + symbol)
                available[ingredient] -= 1
                placements.append((view.grid[row * view.width + column], ingredient))
        all_placements.append(placements)
    # A free observed main slot is conservative and covers every supported output
    # (all batches retrieved individually, max output stack <= 4).
    output_stack = 16 if name == "bucket" else 1 if name in {"bow", "shield", "shulker_box"} or name.endswith(("_pickaxe", "_axe", "_sword", "_hoe", "_helmet", "_chestplate", "_leggings", "_boots")) else 64
    require(sum(view.items[s] == EMPTY for s in view.storage.values()) >= math.ceil(recipe.count * batches / output_stack),
            "crafting_requires_reserved_output_capacity")
    worst = sum(3 * len(p) + 1 for p in all_placements)
    require(budget.remaining >= worst, "crafting_action_budget_insufficient_before_start")
    total_consumed = Counter()
    for placements in all_placements:
        before_counts = _counts(view)
        expected = dict(view.items)
        consumed = Counter(i for _, i in placements)
        for target, item_id in placements:
            require(_check_items(view, expected, EMPTY, ignore=(view.output,)), "crafting_input_changed")
            source = next((s for s in view.storage.values() if view.items[s][0] == item_id and view.items[s][1]), None)
            require(source is not None, "crafting_ingredient_disappeared")
            stack = view.items[source]
            expected[source] = EMPTY
            observation = _click(runtime, budget, observation, view, source,
                lambda v, e=dict(expected), c=stack: _check_items(v, e, c, ignore=(v.output,)))
            view = _craft_view(observation)
            expected[target] = (item_id, 1, stack[2])
            remaining = (item_id, stack[1] - 1, stack[2]) if stack[1] > 1 else EMPTY
            observation = _click(runtime, budget, observation, view, target,
                lambda v, e=dict(expected), c=remaining: _check_items(v, e, c, ignore=(v.output,)), button=1)
            view = _craft_view(observation)
            if remaining != EMPTY:
                expected[source] = remaining
                observation = _click(runtime, budget, observation, view, source,
                    lambda v, e=dict(expected): _check_items(v, e, EMPTY, ignore=(v.output,)))
                view = _craft_view(observation)
        observation = _wait(runtime, observation, _craft_view,
            lambda v: _check_items(v, expected, EMPTY, ignore=(v.output,))
                and v.items[v.output] == (output_id, recipe.count, 0), seconds=3, max_samples=40)
        view = _craft_view(observation)
        wanted = _expected_counts(before_counts, consumed, (output_id, recipe.count))
        observation = _click(runtime, budget, observation, view, view.output,
            lambda v: _counts(v) == wanted and v.carried == EMPTY
                and all(v.items[i] == EMPTY for i in (v.output,) + v.grid), click_type="quick_move")
        view = _craft_view(observation)
        total_consumed.update(consumed)
    require(_counts(view) == _expected_counts(first, total_consumed, (output_id, recipe.count * batches)),
            "crafting_final_total_delta_mismatch")
    return runtime.result("production.craft", tuple(budget.observations) + (observation,),
        recipe=name, batches=batches, item_id=output_id, added=recipe.count * batches,
        consumed=dict(total_consumed), action_request_ids=budget.request_ids,
        cursor_empty=True, grid_empty=True, menu_left_open=view.container_id != 0,
        supported_recipes=tuple(sorted(CRAFT_RECIPES)))


class FurnaceView:
    """Exact vanilla machine slots plus observed (never hardcoded) storage map."""
    def __init__(self, observation):
        self.state = observation.state
        menu = self.state.get("menu", {})
        require(menu.get("menu_class") in tuple(STATIONS.values())[1:], "requires_supported_furnace_menu")
        self.station = next(k for k, v in STATIONS.items() if v == menu["menu_class"])
        self.container_id = menu.get("container_id")
        require(type(self.container_id) is int and self.container_id > 0, "invalid_furnace_container")
        _state_id(self)
        require(menu.get("slots_truncated") is False and isinstance(menu.get("slots"), list), "incomplete_furnace_menu")
        self.slots, self.storage, self.items = {}, {}, {}
        for slot in menu["slots"]:
            require(isinstance(slot, dict), "invalid_furnace_slot")
            index = slot.get("menu_index")
            require(type(index) is int and index >= 0 and index not in self.slots and slot.get("active") is True,
                    "duplicate_or_inactive_furnace_slot")
            self.slots[index] = slot
            self.items[index] = _normal_item(slot.get("item"))
            if slot.get("player_inventory") is True:
                inv = slot.get("inventory_index")
                require(type(inv) is int and 0 <= inv <= 35 and inv not in self.storage, "invalid_furnace_storage_mapping")
                self.storage[inv] = index
        require(set(self.storage) == set(range(36)), "incomplete_furnace_storage")
        require(set(self.slots) == {0, 1, 2} | set(self.storage.values()), "unexpected_furnace_slots")
        for index in (0, 1, 2):
            slot = self.slots[index]
            require(slot.get("player_inventory") is False and slot.get("container_slot") == index,
                    "invalid_furnace_machine_mapping")
        player = self.state.get("player", {})
        require(player.get("inventory_truncated") is False and isinstance(player.get("inventory"), list),
                "incomplete_furnace_player_inventory")
        inventory = {}
        for item in player["inventory"]:
            require(isinstance(item, dict), "invalid_furnace_player_item")
            index = item.get("slot")
            require(type(index) is int and 0 <= index <= 35 and index not in inventory, "invalid_furnace_player_slot")
            inventory[index] = _normal_item(item)
        require(set(inventory) == set(range(36)) and all(inventory[i] == self.items[s] for i, s in self.storage.items()),
                "furnace_menu_and_inventory_disagree")
        self.carried = _normal_item(menu.get("carried"))
        world = self.state.get("world", {})
        require(world.get("world_generation") and player.get("uuid"), "furnace_identity_missing")
        self.identity = (menu["menu_class"], self.container_id, world["world_generation"], player["uuid"], player.get("dimension"))
        self.mapping = tuple(sorted((i, s.get("player_inventory"), s.get("inventory_index"), s.get("container_slot"),
                                     s.get("active")) for i, s in self.slots.items()))
        self.furnace = menu.get("furnace", {})
        _require_item_bindings(self)

    def counts(self):
        result = Counter()
        for slot in self.storage.values():
            item_id, count, _ = self.items[slot]
            if count:
                result[item_id] += count
        return result


def _load_cold_slot(runtime, budget, observation, view, target, item_id, count):
    """Load input before fuel. Cold machine cannot consume partially loaded input."""
    expected = dict(view.items)
    loaded = 0
    while loaded < count:
        source = next((s for s in view.storage.values() if view.items[s][0] == item_id and view.items[s][1] > 0), None)
        require(source is not None, "smelting_material_disappeared")
        stack = view.items[source]
        require(stack[2] == 0, "unexpected_damaged_smelting_material")
        n = min(count - loaded, stack[1])
        expected[source] = EMPTY
        observation = _click(runtime, budget, observation, view, source,
            lambda v, e=dict(expected), c=stack: _check_items(v, e, c), reader=FurnaceView)
        view = FurnaceView(observation)
        for used in range(n):
            loaded += 1
            expected[target] = (item_id, loaded, 0)
            left = stack[1] - used - 1
            carried = (item_id, left, 0) if left else EMPTY
            observation = _click(runtime, budget, observation, view, target,
                lambda v, e=dict(expected), c=carried: _check_items(v, e, c), button=1, reader=FurnaceView)
            view = FurnaceView(observation)
        left = stack[1] - n
        if left:
            expected[source] = (item_id, left, 0)
            observation = _click(runtime, budget, observation, view, source,
                lambda v, e=dict(expected): _check_items(v, e, EMPTY), reader=FurnaceView)
            view = FurnaceView(observation)
    return observation, view


def _machine_conserved(view, recipe, count, fuel_id, loaded_fuel):
    input_item, fuel, output = (view.items[i] for i in (0, 1, 2))
    if input_item != EMPTY and (input_item[0] != recipe.input_id or input_item[2] != 0):
        return False
    if output != EMPTY and (output[0] != recipe.output_id or output[2] != 0):
        return False
    if fuel != EMPTY and (fuel[0] != fuel_id or fuel[2] != 0):
        return False
    return input_item[1] + output[1] == count and 0 <= fuel[1] <= loaded_fuel


def smelt(runtime, input_id, *, count=1, fuel_id="minecraft:coal", station=None,
          max_actions=1024, wait_seconds=360, max_samples=4000):
    """Smelt 1..32 inputs in an initially empty, unlit vanilla machine.

    Loads exact inputs, then the minimum explicit fuel units; verifies all
    inventory/cursor transitions and input+output conservation while the furnace
    ticks. A single output retrieval follows two later exact-output observations.
    Timeout leaves contents untouched and must not be blindly replayed.
    """
    require(input_id in SMELTING_RECIPES, "unsupported_smelting_recipe")
    require(fuel_id in FUELS, "unsupported_smelting_fuel")
    require(type(count) is int and 1 <= count <= 32, "smelt_count_must_be_1_to_32")
    require(type(wait_seconds) in (int, float) and math.isfinite(wait_seconds) and 0 < wait_seconds <= 600,
            "invalid_smelting_wait_seconds")
    require(type(max_samples) is int and 2 <= max_samples <= 6000, "invalid_smelting_wait_samples")
    recipe = SMELTING_RECIPES[input_id]
    fuel_count = math.ceil(count * recipe.furnace_ticks / FUELS[fuel_id])
    require(fuel_count <= 64, "smelting_fuel_stack_limit")
    budget = _Budget(max_actions)
    require(budget.remaining >= 3 * (count + fuel_count) + 1 + int(station is not None), "smelting_action_budget_insufficient_before_start")
    if station is not None:
        require(isinstance(station, dict) and station.get("block_id") in recipe.stations, "invalid_smelting_station")
        outcome = open_workstation(runtime, station.get("position"), station["block_id"], face=station.get("face", "up"))
        budget.remaining -= 1
        budget.request_ids.extend(outcome.request_ids)
        runtime.require_success(outcome)
    observation = runtime.observe(allow_menu=True)
    view = FurnaceView(observation)
    require(view.station in recipe.stations, "recipe_not_supported_by_this_furnace")
    require(view.furnace.get("is_lit") is False, "smelting_requires_observed_unlit_furnace")
    require(view.carried == EMPTY and all(view.items[i] == EMPTY for i in (0, 1, 2)),
            "smelting_requires_empty_machine_and_cursor")
    first = _counts(view)
    need = Counter({input_id: count})
    need[fuel_id] += fuel_count
    require(all(first[i] >= n for i, n in need.items()), "insufficient_smelting_inputs_or_fuel")
    require(any(view.items[s] == EMPTY for s in view.storage.values()), "smelting_requires_free_output_slot")
    observation, view = _load_cold_slot(runtime, budget, observation, view, 0, input_id, count)
    # Fuel is deposited one unit at a time. Once lit, machine slots can change
    # legitimately; storage/cursor and material conservation remain exact.
    expected_storage = {s: view.items[s] for s in view.storage.values()}
    loaded = 0
    while loaded < fuel_count:
        source = next((s for s in view.storage.values() if view.items[s][0] == fuel_id and view.items[s][1] > 0), None)
        require(source is not None, "smelting_fuel_disappeared")
        stack = view.items[source]
        n = min(fuel_count - loaded, stack[1])
        expected_storage[source] = EMPTY
        observation = _click(runtime, budget, observation, view, source,
            lambda v, e=dict(expected_storage), c=stack, f=loaded: _check_items(v, e, c)
                and _machine_conserved(v, recipe, count, fuel_id, f), reader=FurnaceView)
        view = FurnaceView(observation)
        for used in range(n):
            loaded += 1
            left = stack[1] - used - 1
            carried = (fuel_id, left, stack[2]) if left else EMPTY
            observation = _click(runtime, budget, observation, view, 1,
                lambda v, e=dict(expected_storage), c=carried, f=loaded: _check_items(v, e, c)
                    and _machine_conserved(v, recipe, count, fuel_id, f), button=1, reader=FurnaceView)
            view = FurnaceView(observation)
        left = stack[1] - n
        if left:
            expected_storage[source] = (fuel_id, left, stack[2])
            observation = _click(runtime, budget, observation, view, source,
                lambda v, e=dict(expected_storage), f=loaded: _check_items(v, e, EMPTY)
                    and _machine_conserved(v, recipe, count, fuel_id, f), reader=FurnaceView)
            view = FurnaceView(observation)
    def ready(v):
        require(_check_items(v, expected_storage, EMPTY), "smelting_storage_or_cursor_changed")
        require(_machine_conserved(v, recipe, count, fuel_id, fuel_count), "smelting_machine_conservation_failed")
        return v.items[0] == EMPTY and v.items[2] == (recipe.output_id, count, 0)
    observation = _wait(runtime, observation, FurnaceView, ready, seconds=wait_seconds, max_samples=max_samples, poll_seconds=0.25)
    view = FurnaceView(observation)
    wanted = _expected_counts(first, need, (recipe.output_id, count))
    remaining_fuel = view.items[1]
    observation = _click(runtime, budget, observation, view, 2,
        lambda v: _counts(v) == wanted and v.carried == EMPTY and v.items[0] == EMPTY
            and v.items[2] == EMPTY and v.items[1] == remaining_fuel,
        click_type="quick_move", reader=FurnaceView)
    view = FurnaceView(observation)
    return runtime.result("production.smelt", tuple(budget.observations) + (observation,),
        input_id=input_id, output_id=recipe.output_id, produced=count, fuel_id=fuel_id,
        fuel_loaded=fuel_count, fuel_remaining_in_machine=view.items[1][1],
        station=view.station, action_request_ids=budget.request_ids, cursor_empty=True,
        output_collected=True, menu_left_open=True, residual_heat_possible=True)
