"""Versioned explicit-state construction, without an embedded building design.

A blueprint is data, not execution authority. Each invocation requires the same
Runtime guards as every other capability. Plans use only one complete bounded
scan; they do not merge stale scans, excavate terrain, or infer unknown support.
"""
from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
from dataclasses import dataclass
import math
import re
import json
from pathlib import Path

from building_controller.model import Pos, Region, PALETTE, AIR_IDS, PlanError
from building_controller.terrain import Cell, parse_inventory, state_blockers
from .core import SkillError, require, atomic_write
from . import building as legacy

MAX_CELLS = 8192
HORIZONTAL = ("north", "east", "south", "west")
VECTORS = {name: legacy.FACES[name] for name in HORIZONTAL}
WOODS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "bamboo", "crimson", "warped")
STAIR_BASES = WOODS + ("stone", "cobblestone", "stone_brick", "brick", "sandstone", "smooth_sandstone", "andesite", "diorite", "granite", "cobbled_deepslate", "deepslate_brick", "deepslate_tile", "quartz", "smooth_quartz", "blackstone", "polished_blackstone", "polished_blackstone_brick", "end_stone_brick")
STAIRS = {"minecraft:" + b + "_stairs" for b in STAIR_BASES}
SLABS = {"minecraft:" + b + "_slab" for b in STAIR_BASES} | {"minecraft:smooth_stone_slab"}
DOORS = {"minecraft:" + b + "_door" for b in WOODS} | {"minecraft:iron_door"}
FENCES = {"minecraft:" + b + "_fence" for b in WOODS} | {"minecraft:nether_brick_fence"}
LOGS = {"minecraft:" + prefix + b + suffix for b in WOODS[:8] for prefix in ("", "stripped_") for suffix in ("_log", "_wood")}
PLAIN = PALETTE | {"minecraft:" + b + "_planks" for b in WOODS} | {"minecraft:glass", "minecraft:glowstone", "minecraft:sea_lantern", "minecraft:crafting_table", "minecraft:obsidian", "minecraft:quartz_block"}
STATIONS = {"minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker"}
LIGHTS = {"minecraft:torch", "minecraft:wall_torch", "minecraft:soul_torch", "minecraft:soul_wall_torch"}
PANE = "minecraft:glass_pane"


def _position(value):
    require(isinstance(value, dict) and set(value) == {"x", "y", "z"}, "invalid_exact_blueprint_position")
    return Pos.parse(value)


def _properties(block, props):
    require(isinstance(block, str) and isinstance(props, dict) and all(type(k) is str and type(v) is str for k, v in props.items()), "invalid_blueprint_blockstate")
    schema = {}
    if block in PLAIN:
        pass
    elif block in LOGS:
        schema = {"axis": ("x", "y", "z")}
    elif block in STAIRS:
        schema = {"facing": HORIZONTAL, "half": ("top", "bottom"), "shape": ("straight", "inner_left", "inner_right", "outer_left", "outer_right"), "waterlogged": ("false",)}
    elif block in SLABS:
        schema = {"type": ("top", "bottom"), "waterlogged": ("false",)}
    elif block in DOORS:
        schema = {"facing": HORIZONTAL, "half": ("lower", "upper"), "hinge": ("left", "right"), "open": ("false",), "powered": ("false",)}
    elif block in FENCES or block == PANE:
        schema = dict.fromkeys(HORIZONTAL, ("false", "true")) | {"waterlogged": ("false",)}
    elif block in STATIONS:
        schema = {"facing": HORIZONTAL, "lit": ("false",)}
    elif block in LIGHTS:
        schema = {"facing": HORIZONTAL} if "wall" in block else {}
    else:
        raise SkillError("unsupported_blueprint_block:" + block)
    require(set(props) == set(schema) and all(props[k] in schema[k] for k in schema), "unsupported_blueprint_properties:" + block)
    return dict(props)


def _dynamic(block):
    return {"shape"} if block in STAIRS else set(HORIZONTAL) if block in FENCES or block == PANE else set()


def _static_equal(a, b):
    return a[0] == b[0] and {k: v for k, v in a[1].items() if k not in _dynamic(a[0])} == {k: v for k, v in b[1].items() if k not in _dynamic(b[0])}


def _body(spec):
    return {k: spec[k] for k in ("region", "cells", "clearance", "light_checks", "access_points")}


def seal_blueprint(spec):
    """Offline import helper: add the content digest; never add an approval."""
    value = deepcopy(spec)
    for key in ("clearance", "light_checks", "access_points"):
        value.setdefault(key, [])
    value.setdefault("identity", {})["content_sha256"] = legacy._digest(_body(value))
    return VersionedBlueprint.parse(value).spec()


@dataclass(frozen=True)
class VersionedBlueprint:
    value: dict
    region: Region
    entries: tuple

    def spec(self):
        return deepcopy(self.value)

    def cells(self):
        return tuple((p, block) for p, block, _ in self.entries)

    @classmethod
    def parse(cls, value):
        if isinstance(value, cls):
            value = value.spec()
        require(isinstance(value, dict) and set(value) == {"schema_version", "identity", "region", "cells", "clearance", "light_checks", "access_points"} and type(value["schema_version"]) is int and value["schema_version"] == 3, "invalid_versioned_blueprint_schema")
        identity = value["identity"]
        require(isinstance(identity, dict) and set(identity) == {"blueprint_id", "revision", "source", "content_sha256"}, "versioned_blueprint_identity_required")
        require(all(isinstance(identity[k], str) and 1 <= len(identity[k]) <= 1024 for k in identity), "invalid_blueprint_identity")
        require(re.fullmatch(r"[0-9a-f]{64}", identity["content_sha256"]) and legacy._digest(_body(value)) == identity["content_sha256"], "blueprint_revision_content_hash_mismatch")
        try:
            region = Region.parse(value["region"])
            _position(value["region"]["min"])
            _position(value["region"]["max"])
            require(isinstance(value["cells"], list) and 1 <= len(value["cells"]) <= MAX_CELLS, "blueprint_cell_budget_must_be_1_to_8192")
            entries, seen = [], set()
            for item in value["cells"]:
                require(isinstance(item, dict) and set(item) == {"position", "block", "properties"}, "invalid_versioned_blueprint_cell")
                pos = _position(item["position"])
                require(pos not in seen and region.contains(pos), "duplicate_or_outside_blueprint_cell")
                props = _properties(item["block"], item["properties"])
                entries.append((pos, item["block"], props))
                seen.add(pos)
            desired = {p: (b, props) for p, b, props in entries}
            for p, block, props in entries:
                if block in DOORS:
                    other = p.offset(y=1 if props["half"] == "lower" else -1)
                    require(desired.get(other) == (block, dict(props, half="upper" if props["half"] == "lower" else "lower")), "door_requires_exact_two_cell_footprint")
            for key, fields in (("clearance", {"position", "purpose"}), ("light_checks", {"position", "min_block_light"}), ("access_points", {"x", "y", "z"})):
                require(isinstance(value[key], list) and len(value[key]) <= MAX_CELLS, "invalid_blueprint_acceptance_list")
                unique = set()
                for item in value[key]:
                    require(isinstance(item, dict) and set(item) == fields, "invalid_blueprint_acceptance_entry")
                    pos = _position(item if key == "access_points" else item["position"])
                    require(pos not in unique, "duplicate_blueprint_acceptance_position")
                    unique.add(pos)
                    if key != "access_points":
                        require(region.contains(pos), "acceptance_position_outside_region")
                    if key == "clearance":
                        require(pos not in seen and item["purpose"] in ("cavity", "interior", "access"), "invalid_blueprint_clearance")
                    if key == "light_checks":
                        require(type(item["min_block_light"]) is int and 0 <= item["min_block_light"] <= 15, "invalid_blueprint_light_threshold")
            return cls(deepcopy(value), region, tuple(sorted(entries, key=lambda row: (row[0].y, row[0].z, row[0].x))))
        except (KeyError, TypeError, PlanError) as exc:
            raise SkillError("invalid_versioned_blueprint:" + str(exc)) from None


def classify(raw, baseline):
    """Preserve every unknown/fluid/hazard test before recognizing stateful dry blocks."""
    if baseline.kind != "unsupported":
        return baseline
    block, props = raw.get("id"), raw.get("properties")
    try:
        _properties(block, props)
    except SkillError:
        return baseline
    if raw.get("air") is not False or type(raw.get("collision_empty")) is not bool:
        return baseline
    pos = baseline.position
    if block in PLAIN | LOGS | STATIONS and raw.get("collision_bounds") == [0, 0, 0, 1, 1, 1] and raw.get("full_top_support") is True and raw["collision_empty"] is False:
        return Cell(pos, block, "solid", "known_supported_exact_state_full_cube")
    bounds = raw.get("collision_bounds")
    if raw["collision_empty"] is False and ((block in STAIRS and bounds == [0, 0, 0, 1, 1, 1]) or (block in SLABS and props["type"] == "top" and bounds == [0, .5, 0, 1, 1, 1])):
        return Cell(pos, block, "tread", "known_supported_integer_top_tread")
    return Cell(pos, block, "obstacle", "known_supported_exact_state_nonfull_cube")


def _terrain(observation, *, historical=False):
    return legacy._terrain(observation, extended=True, historical=historical)


def _states(source):
    return {p: (c["id"], dict(c["properties"])) for p, c in source.items() if isinstance(c.get("properties"), dict) and c.get("known") is True}


def _full(state):
    return state is not None and (state[0] in PLAIN | LOGS | STATIONS or state[0] in ("minecraft:stone", "minecraft:dirt", "minecraft:grass_block", "minecraft:deepslate"))


def _face_sturdy(state, face):
    if _full(state):
        return True
    if state is None or state[0] not in STAIRS:
        return False
    facing, shape = state[1]["facing"], state[1]["shape"]
    sides = {facing} if not shape.startswith("outer_") else set()
    if shape == "inner_left":
        sides.add(_rotate(facing, -1))
    elif shape == "inner_right":
        sides.add(_rotate(facing, 1))
    return face in sides


def _offset(pos, facing):
    return pos.offset(*VECTORS[facing])


def _rotate(facing, n):
    return HORIZONTAL[(HORIZONTAL.index(facing) + n) % 4]


def stage_state(pos, state, states):
    """Vanilla dry fence/pane connections and stair corner shape for a local stage.

    Native BlockItem.getStateForPlacement is authoritative and independently
    rejects predictions that do not match real engine placement semantics.
    """
    block, props = state[0], dict(state[1])
    if block in FENCES or block == PANE:
        for facing in HORIZONTAL:
            neighbor = states.get(_offset(pos, facing))
            same = neighbor and (neighbor[0] == PANE if block == PANE else neighbor[0] in FENCES and (neighbor[0] == "minecraft:nether_brick_fence") == (block == "minecraft:nether_brick_fence"))
            props[facing] = "true" if _face_sturdy(neighbor, _rotate(facing, 2)) or same else "false"
    elif block in STAIRS:
        facing, half = props["facing"], props["half"]
        def stair(at):
            candidate = states.get(at)
            return candidate[1] if candidate and candidate[0] in STAIRS and candidate[1].get("half") == half else None
        def compatible(at, direction):
            other = stair(_offset(at, direction))
            return other is None or other.get("facing") != facing
        props["shape"] = "straight"
        front = stair(_offset(pos, facing))
        if front and (HORIZONTAL.index(front["facing"]) - HORIZONTAL.index(facing)) % 2 and compatible(pos, _rotate(front["facing"], 2)):
            props["shape"] = "outer_left" if front["facing"] == _rotate(facing, -1) else "outer_right"
        else:
            back = stair(_offset(pos, _rotate(facing, 2)))
            if back and (HORIZONTAL.index(back["facing"]) - HORIZONTAL.index(facing)) % 2 and compatible(pos, back["facing"]):
                props["shape"] = "inner_left" if back["facing"] == _rotate(facing, -1) else "inner_right"
    return block, props


def _exact(source, pos, state):
    raw = source.get(pos, {})
    return raw.get("known") is True and raw.get("status") == "loaded" and raw.get("id_truncated") is False and raw.get("properties_truncated") is False and raw.get("id") == state[0] and raw.get("properties") == state[1]


def _standable(cells, pos, blocked):
    def kind(p):
        return cells[p].kind if p in cells else "unknown"
    return (pos not in blocked and pos.offset(y=1) not in blocked and kind(pos) == kind(pos.offset(y=1)) == "clear" and kind(pos.offset(y=-1)) in ("solid", "tread") and all(kind(pos.offset(dx, dy, dz)) in ("clear", "solid", "obstacle", "tread") for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)) for dy in (0, 1)))


def _routes(cells, start, blocked, max_steps):
    require(_standable(cells, start, blocked), "building_start_not_safe_or_overlaps_target")
    paths, queue = {start: (start,)}, deque([start])
    while queue:
        node = queue.popleft()
        if len(paths[node]) > max_steps:
            continue
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            for dy in (0, 1, -1):
                target = node.offset(dx, dy, dz)
                if target in paths or not _standable(cells, target, blocked):
                    continue
                swept = (node.offset(y=2), target.offset(y=2)) if dy == 1 else (target.offset(y=2),) if dy == -1 else ()
                if any(cells.get(p, Cell(p, None, "unknown", "unseen")).kind != "clear" for p in swept):
                    continue
                paths[target] = paths[node] + (target,)
                queue.append(target)
    return paths


def _hit_points(support, face):
    normal = legacy.FACES[face]
    axes = [i for i, n in enumerate(normal) if n == 0]
    center = list(legacy._face_point(support, face))
    for a, b in ((.5, .5), (.25, .5), (.75, .5), (.5, .25), (.5, .75), (.25, .25), (.75, .75)):
        point = list(center)
        point[axes[0]] += a - .5
        point[axes[1]] += b - .5
        yield tuple(point)


def _facing(yaw):
    return ("south", "west", "north", "east")[math.floor(yaw / 90 + .5) % 4]


def _door_hinge(pos, facing, hit, states):
    # Vanilla 1.21.1 DoorBlock.getHinge, checked against the restored official
    # compiled class. Neighbor solids and double doors take precedence over hit.
    left, right = _offset(pos, _rotate(facing, -1)), _offset(pos, _rotate(facing, 1))
    score = sum(bool(_full(states.get(p))) for p in (right, right.offset(y=1))) - sum(bool(_full(states.get(p))) for p in (left, left.offset(y=1)))
    def lower_door(p):
        other = states.get(p)
        return other is not None and other[0] in DOORS and other[1].get("half") == "lower"
    ldoor, rdoor = lower_door(left), lower_door(right)
    if ldoor and not rdoor or score > 0:
        return "right"
    if rdoor and not ldoor or score < 0:
        return "left"
    dx, _, dz = VECTORS[facing]
    x, z = hit[0] - pos.x, hit[2] - pos.z
    return "right" if dx < 0 and z < .5 or dx > 0 and z > .5 or dz < 0 and x > .5 or dz > 0 and x < .5 else "left"


def _orientation_ok(state, support, face, hit, yaw, *, target=None, states=None):
    block, props = state
    facing = _facing(yaw)
    if block in STAIRS and props["facing"] != facing:
        return False
    if block in STATIONS and props["facing"] != _rotate(facing, 2):
        return False
    if block in DOORS:
        if props["facing"] != facing or face != "up":
            return False
        if target is None or states is None or _door_hinge(target, facing, hit, states) != props["hinge"]:
            return False
    if block in STAIRS or block in SLABS:
        half = "top" if face == "down" or face != "up" and hit[1] - math.floor(hit[1]) > .5 else "bottom"
        if props.get("half", props.get("type")) != half:
            return False
    if block in LOGS and props["axis"] != ("y" if face in ("up", "down") else "x" if face in ("east", "west") else "z"):
        return False
    if block in LIGHTS:
        if "wall" in block:
            return face in HORIZONTAL and props["facing"] == face
        return face == "up"
    return True


def _placement_candidate(pos, state, cells, states, routes, eye_height, reach, actual_eye=None, required_positions=()):
    anchors = legacy.ANCHORS + ((0, 1, 0, "down"),)
    for dx, dy, dz, face in anchors:
        support = pos.offset(dx, dy, dz)
        if support not in cells or cells[support].kind != "solid":
            continue
        for stand in sorted(routes, key=lambda p: (len(routes[p]), math.dist((p.x, p.y, p.z), (pos.x, pos.y, pos.z)), p)):
            if any(abs(p.x-stand.x) > 4 or abs(p.z-stand.z) > 4 or abs(p.y-stand.y) > 4 for p in required_positions):
                continue
            eye = actual_eye or (stand.x + .5, stand.y + eye_height, stand.z + .5)
            for hit in _hit_points(support, face):
                yaw = math.degrees(math.atan2(-(hit[0] - eye[0]), hit[2] - eye[2]))
                if not _orientation_ok(state, support, face, hit, yaw, target=pos, states=states):
                    continue
                if not legacy._visible(cells, stand, eye_height, support, face, reach, actual_eye=eye, hit_point=hit):
                    continue
                return {"position": pos.json(), "block": state[0], "properties": dict(state[1]), "support": support.json(), "face": face, "stand": stand.json(), "route": [p.json() for p in routes[stand]], "placement_hit": dict(zip(("x", "y", "z"), hit)), "placement_yaw": yaw}
    return None


def _footprint(pos, state, desired):
    return (pos, pos.offset(y=1)) if state[0] in DOORS and state[1]["half"] == "lower" else (pos,)


def _stage_changes(footprint, desired, states):
    """Local fixed point including fence changes caused by a neighboring stair's
    new corner shape. Source requirements are returned for fresh-window binding.
    """
    projected = dict(states)
    projected.update({p: desired[p] for p in footprint})
    affected = set(footprint)
    for p in footprint:
        for direction in HORIZONTAL:
            q = _offset(p, direction)
            if q in desired and q in states and states[q][0] in STAIRS | FENCES | {PANE}:
                affected.add(q)
    # Changing a stair shape can change one more fence/pane face at distance 2.
    for p in tuple(affected):
        if projected[p][0] in STAIRS:
            for direction in HORIZONTAL:
                q = _offset(p, direction)
                if q in desired and q in states and states[q][0] in FENCES | {PANE}:
                    affected.add(q)
    required = set(footprint)
    for p in footprint:
        required.update(p.offset(*delta) for delta in legacy.FACES.values())
    for p in affected:
        if _dynamic(projected[p][0]):
            required.update(_offset(p, direction) for direction in HORIZONTAL)
    require(all(p in states for p in required), "building_neighbor_state_outside_observed_scope")
    for _ in range(3):
        updated = {p: stage_state(p, projected[p], projected) for p in affected}
        if all(projected[p] == state for p, state in updated.items()):
            break
        projected.update(updated)
    require(all(stage_state(p, projected[p], projected) == projected[p] for p in affected), "building_neighbor_state_did_not_stabilize")
    changes = {p: projected[p] for p in affected if p in footprint or projected[p] != states.get(p)}
    return projected, changes, required


def _raw_simulated(pos, state):
    block, props = state
    return {**pos.json(), "known": True, "status": "loaded", "id": block, "properties": dict(props), "id_truncated": False, "properties_truncated": False}


def _verify_clearance(blueprint, terrain):
    for entry in blueprint.value["clearance"]:
        require(terrain.get(Pos.parse(entry["position"])).kind == "clear", "blueprint_required_clearance_not_observed_air")


def _audit_targets(blueprint):
    positions = {p for p, _, _ in blueprint.entries}
    positions.update(Pos.parse(row["position"]) for row in blueprint.value["clearance"] + blueprint.value["light_checks"])
    cavities = {Pos.parse(row["position"]) for row in blueprint.value["clearance"] if row["purpose"] == "cavity"}
    for pos in cavities:
        positions.update(pos.offset(*delta) for delta in legacy.FACES.values())
    return positions


def _audit_plan(blueprint, cells, start, final_exit, max_steps):
    remaining = _audit_targets(blueprint)
    require(len(remaining) <= MAX_CELLS * 7, "building_audit_target_budget")
    windows = []
    while remaining:
        routes = _routes(cells, start, set(), max_steps)
        best, score = None, None
        for stand, route in routes.items():
            covered = {p for p in remaining if abs(p.x-stand.x) <= 4 and abs(p.z-stand.z) <= 4 and abs(p.y-stand.y) <= 4}
            if not covered:
                continue
            value = (-len(covered), len(route), stand)
            if score is None or value < score:
                score = value
                best = (stand, route, covered)
        require(best is not None, "building_final_fresh_audit_cells_unreachable")
        stand, route, covered = best
        windows.append({"stand": stand.json(), "route": [p.json() for p in route], "positions": [p.json() for p in sorted(covered)]})
        require(len(windows) <= 128, "building_fresh_audit_window_budget")
        remaining.difference_update(covered)
        start = stand
    routes = _routes(cells, start, set(), max_steps)
    require(final_exit in routes, "building_post_audit_exit_unreachable")
    return windows, [p.json() for p in routes[final_exit]]


# A survey route only sizes a finite allowance. Navigation still derives every
# submitted waypoint from a new local observation. Two extra short segments are
# the entire detour allowance; exhaustion stops rather than replaying a route.
BUILD_LOCAL_STEPS = 4
BUILD_DETOUR_SEGMENTS = 2


def _navigation_limits(route, max_steps=64):
    steps = min(max_steps, BUILD_LOCAL_STEPS)
    segments = max(1, math.ceil((len(route) - 1) / steps)) + BUILD_DETOUR_SEGMENTS
    require(segments <= 128, "building_navigation_segment_budget")
    return {"max_steps": steps, "max_segments": segments}


def _action_seconds(runtime, native_seconds):
    # A successful fresh read is bounded by max_age. A stale/failed read stops
    # the goal. Exchange wait bounds cover transport as well as native time;
    # verification uses Runtime.execute's default eight reads and .05 s sleeps.
    read = getattr(runtime, "max_age", .8)
    exchange = max(native_seconds, getattr(runtime, "wait_timeout", 30))
    return exchange + 8 * (read + .05)


def _navigation_budget(runtime, route, max_steps=64):
    limits = _navigation_limits(route, max_steps)
    seconds = limits["max_segments"] * (getattr(runtime, "max_age", .8)
        + _action_seconds(runtime, 3 + 1.8 * limits["max_steps"]))
    return limits["max_segments"], seconds


def _audit_budget(runtime, windows, return_route, *, max_steps=64,
                  current_actions=0, current_seconds=0):
    # Include possible recentering even for a one-position historical route.
    # These are the same finite segment limits used by actual navigation below.
    costs = [_navigation_budget(runtime, w["route"], max_steps) for w in windows]
    costs.append(_navigation_budget(runtime, return_route, max_steps))
    actions = sum(row[0] for row in costs)
    read = getattr(runtime, "max_age", .8)
    # Each window: entry read, baseline read, up to eight later-tick reads and
    # sleeps. Return: an entry read and the final fresh read at the exit stand.
    seconds = sum(row[1] for row in costs) + len(windows) * (10 * read + 8 * .05) + 2 * read
    reservation = {"audit_actions": actions, "audit_seconds": seconds,
                   "local_steps": min(max_steps, BUILD_LOCAL_STEPS),
                   "detour_segments_per_move": BUILD_DETOUR_SEGMENTS}
    method = getattr(runtime, "effective_remaining_budget", None)
    if method is not None:
        budget = method()
        require(budget["remaining_actions"] >= actions + current_actions, "building_original_action_budget_cannot_reserve_final_audit")
        require(budget["remaining_seconds"] >= seconds + current_seconds, "building_original_deadline_cannot_reserve_final_audit")
    return reservation


def _initial_budget(runtime, plan, start, *, max_placements, max_moves, max_steps):
    require(len(plan["placements"]) <= max_placements, "build_placement_budget_insufficient_before_start")
    current, moves = start, 0
    for entry in plan["placements"] + plan["audit_windows"]:
        stand = Pos.parse(entry["stand"])
        moves += stand != current
        current = stand
    moves += current != start
    require(moves <= max_moves, "build_move_budget_insufficient_before_start")
    # The first pending placement must also fit before procurement can begin.
    # Later placement admission repeats this check against remaining time.
    first_seconds, first_actions = 0, 0
    if plan["placements"]:
        move_actions, move_seconds = _navigation_budget(runtime, plan["placements"][0]["route"], max_steps)
        first_actions = move_actions + 3
        first_seconds = move_seconds + _placement_seconds(runtime)
    return _audit_budget(runtime, plan["audit_windows"], plan["audit_return_route"],
                         max_steps=max_steps, current_actions=max(len(plan["placements"]), first_actions),
                         current_seconds=first_seconds)


def _placement_seconds(runtime):
    # Hotbar swap and selection (at most two 3 s actions), one 5 s placement,
    # and the two inventory reads plus the final local placement read.
    return 2 * _action_seconds(runtime, 3) + _action_seconds(runtime, 5) + 3 * getattr(runtime, "max_age", .8)


def _at_stand(observation, stand):
    return (math.hypot(observation.player["x"]-stand.x-.5, observation.player["z"]-stand.z-.5) <= .23
            and abs(observation.player["y"]-stand.y) <= .15 and observation.player.get("on_ground") is True)


def _verify_window(blueprint, observation, positions):
    terrain, source = _terrain(observation)
    desired = {p: (block, props) for p, block, props in blueprint.entries}
    clearances = {Pos.parse(row["position"]): row["purpose"] for row in blueprint.value["clearance"]}
    lights = {Pos.parse(row["position"]): row["min_block_light"] for row in blueprint.value["light_checks"]}
    cavities = {pos for pos, purpose in clearances.items() if purpose == "cavity"}
    boundaries = {pos.offset(*delta) for pos in cavities for delta in legacy.FACES.values()} - cavities
    for pos in positions:
        require(pos in source, "building_fresh_audit_cell_outside_observation")
        if pos in desired:
            require(_exact(source, pos, desired[pos]), "building_final_exact_state_verification_failed")
        if pos in clearances:
            require(terrain.get(pos).kind == "clear", "building_final_required_clearance_not_air")
        if pos in boundaries:
            require(terrain.get(pos).kind == "solid", "building_cavity_boundary_not_closed_full_cube")
        if pos in lights:
            value = source[pos].get("block_light")
            require(type(value) is int and lights[pos] <= value <= 15, "building_requested_light_level_not_observed")
    return True


def execution_plan(blueprint, observation, *, max_steps=64, historical=False, planning_materials=None,
                   ambient_policy=None):
    blueprint = VersionedBlueprint.parse(blueprint)
    terrain, source = _terrain(observation, historical=historical)
    desired = {p: (b, props) for p, b, props in blueprint.entries}
    _verify_clearance(blueprint, terrain)
    states = _states(source)
    existing, pending = {}, {}
    for pos, state in desired.items():
        require(pos in source and terrain.get(pos).kind in ("clear", "solid", "obstacle", "tread"), "building_unknown_or_unsafe_target_no_terrain_modification")
        if terrain.get(pos).kind == "clear":
            pending[pos] = state
        else:
            require(_static_equal(states[pos], state) and states[pos] == stage_state(pos, state, states), "building_existing_block_conflict_no_replacement")
            existing[pos] = states[pos]
        for delta in legacy.FACES.values():
            require(terrain.get(pos.offset(*delta)).kind in ("clear", "solid", "obstacle", "tread"), "building_unknown_or_unsafe_neighbor")
    for pos, state in desired.items():
        if state[0] in DOORS:
            other = pos.offset(y=1 if state[1]["half"] == "lower" else -1)
            require((pos in pending) == (other in pending), "partial_door_footprint_no_replay")
    blockers = state_blockers(observation.state, terrain, list(pending),
                              ambient_policy=ambient_policy) if pending or ambient_policy is not None else []
    if historical:
        # Historical global geometry never supplies action-time freshness.
        blockers = [b for b in blockers if b != "state_terrain_ticks_incoherent"]
    require(not blockers, "building_preflight_blocked:" + ",".join(blockers))
    stock = Counter(parse_inventory(observation.state))
    required = Counter(_item_id(state[0]) for state in pending.values() if not (state[0] in DOORS and state[1]["half"] == "upper"))
    materials = [{"item": item, "remaining": count, "available": stock[item], "shortage": max(0, count - stock[item])} for item, count in sorted(required.items())]
    if planning_materials is None:
        require(not any(row["shortage"] for row in materials), "building_material_shortage_before_start")
    else:
        # Procurement preflight may propose geometry against the explicit full
        # bill. Never modify owned survey/state bytes or invent inventory credit.
        require(historical and planning_materials == material_requirements(blueprint)["items"],
                "building_planning_materials_require_exact_historical_bill")
    if not pending:
        require(all(_exact(source, pos, state) for pos, state in desired.items()), "building_final_neighbor_properties_disagree")
        start, _, _ = legacy._geometry(observation)
        windows, returned = _audit_plan(blueprint, dict(terrain.cells), start, start, max_steps)
        return {"placements": [], "material_plan": materials, "proposal_only": True, "materials_assumed_for_proposal": planning_materials is not None, "already_correct": len(existing), "existing": existing, "audit_windows": windows, "audit_return_route": returned}
    start, eye_height, reach = legacy._geometry(observation)
    audit_stand = start
    cells, ordered = dict(terrain.cells), []
    original_pending = set(pending)
    while pending:
        routes = _routes(cells, start, set(pending), max_steps)
        chosen = None
        for pos in sorted(pending, key=lambda p: (p.y, p.z, p.x)):
            target_state = pending[pos]
            if target_state[0] in DOORS and target_state[1]["half"] == "upper":
                continue
            footprint = _footprint(pos, target_state, desired)
            projected, changes, required = _stage_changes(footprint, desired, states)
            state = projected[pos]
            candidate = _placement_candidate(pos, state, cells, states, routes, eye_height, reach, required_positions=required)
            if candidate:
                chosen = candidate
                break
        require(chosen is not None, "building_no_reachable_oriented_supported_stand")
        footprint = _footprint(pos, pending[pos], desired)
        states, changes, required = _stage_changes(footprint, desired, states)
        chosen["required_observation_positions"] = [p.json() for p in sorted(required)]
        chosen["footprint"] = [{"position": p.json(), "block": states[p][0], "properties": states[p][1]} for p in footprint]
        chosen["neighbor_updates"] = [{"position": p.json(), "block": s[0], "properties": s[1]} for p, s in changes.items() if p not in footprint]
        chosen["properties"] = states[pos][1]
        chosen["item"] = _item_id(chosen["block"])
        for p in footprint:
            cells[p] = Cell(p, states[p][0], "solid" if _full(states[p]) else "tread" if states[p][0] in STAIRS or states[p][0] in SLABS and states[p][1]["type"] == "top" else "obstacle", "planned_exact_blockstate")
            pending.pop(p)
        start = Pos.parse(chosen["stand"])
        require(_standable(cells, start, set(pending)), "building_placement_would_trap_or_overlap_stand")
        ordered.append(chosen)
    require(all(states[p] == desired[p] for p in desired), "blueprint_final_neighbor_properties_inconsistent")
    exits = [Pos.parse(p) for p in blueprint.value["access_points"]]
    routes = _routes(cells, start, set(), max_steps)
    require(audit_stand in routes, "building_final_audit_vantage_unreachable")
    if exits:
        require(any(p in routes for p in exits), "building_final_exit_unreachable")
    windows, returned = _audit_plan(blueprint, cells, start, audit_stand, max_steps)
    return {"placements": ordered, "audit_windows": windows, "audit_return_route": returned, "material_plan": materials, "proposal_only": True, "materials_assumed_for_proposal": planning_materials is not None, "already_correct": len(existing), "existing": existing,
            "scanned_target_cells": len(desired), "scan_radius": terrain.radius, "scan_vertical": terrain.vertical,
            "access_verified": bool(exits), "remaining_cells": len(original_pending), "audit_stand": audit_stand.json()}



def _planning_identity(observation):
    from .observation_profiles import _identity
    return _identity(observation), tuple(observation.player[k] for k in ("x", "y", "z"))


def _planning_bounds(blueprint, observation):
    """Minimal centered scan of a declared work box, never route authority.

    A one-cell shell covers supports and static/dynamic neighbors of *every*
    desired cell, including the upper door half. Cavity acceptance neighbors
    and explicit access/body/support/sweep cells extend that box. Routes and
    rays may only use known cells inside the returned complete scan; a detour
    outside it is unsupported rather than presumed traversable.
    """
    from .observation_profiles import _vector, _HORIZONTAL_MARGIN
    blueprint = VersionedBlueprint.parse(blueprint)
    origin, _, _ = legacy._geometry(observation)
    lo, hi = blueprint.region.minimum, blueprint.region.maximum
    required = {Pos(x, y, z)
        for x in (lo.x-1, hi.x+1) for y in (lo.y-1, hi.y+1) for z in (lo.z-1, hi.z+1)}
    required.update(_audit_targets(blueprint))
    # Completed full cubes and integer-top treads are real route surfaces. The
    # existing _routes step-up test reads target-stand+2, i.e. block-top+3.
    # Include that future body/head/sweep envelope before choosing scan bounds.
    top_stands = [p.offset(y=1) for p, block, props in blueprint.entries
                  if _full((block, props)) or block in STAIRS
                  or block in SLABS and props["type"] == "top"]
    for point in [origin] + top_stands + [Pos.parse(p) for p in blueprint.value["access_points"]]:
        required.update(point.offset(dx, dy, dz)
            for dx in (-1, 1) for dy in (-1, 2) for dz in (-1, 1))
    player = observation.player
    box = player.get("bounding_box")
    require(isinstance(box, dict) and set(box) == {"min", "max"}, "building_planning_body_unknown")
    low = _vector(box["min"], "building_planning_body_unknown")
    high = _vector(box["max"], "building_planning_body_unknown")
    position = tuple(player[k] for k in ("x", "y", "z"))
    require(all(a < b for a, b in zip(low, high)) and all(low[i] <= position[i] <= high[i] for i in range(3))
            and abs(low[1]-position[1]) <= 1e-7, "building_planning_body_unknown")
    # Same geometric allowance used by fresh dry-flat profiles: actual body,
    # .56 native clearance, .23 arrival tolerance and .07 coasting allowance.
    body_low = tuple(math.floor(low[i] - (_HORIZONTAL_MARGIN if i != 1 else 0)) for i in range(3))
    body_high = tuple(math.floor(high[i] + (_HORIZONTAL_MARGIN if i != 1 else 0)) for i in range(3))
    required.update((Pos(body_low[0], body_low[1]-1, body_low[2]), Pos(*body_high)))
    minimum = Pos(*(min(getattr(p, k) for p in required) for k in ("x", "y", "z")))
    maximum = Pos(*(max(getattr(p, k) for p in required) for k in ("x", "y", "z")))
    radius = max(1, *(abs(getattr(p,k)-getattr(origin,k)) for p in (minimum,maximum) for k in ("x","z")))
    vertical = max(2, abs(minimum.y-origin.y), abs(maximum.y-origin.y))
    require(radius <= 16 and vertical <= 8, "building_planning_region_outside_bounded_survey")
    return origin, minimum, maximum, radius, vertical


def planning_survey(runtime, blueprint):
    """Acquire one genuine size-matched historical proposal, without effects.

    The seed is sizing only. No terrain is dropped, relabelled or synthesized;
    the real mailbox/HTTP limits and per-step fresh execution guards remain.
    Large or unusually verbose regions can still exceed the transport limit.
    There is no automatic larger-scan fallback or observation/action retry.
    """
    from .observation_profiles import _known_collision
    blueprint = VersionedBlueprint.parse(blueprint)
    seed = runtime.observe(terrain=False, entity_radius=48)
    identity = _planning_identity(seed)
    origin, minimum, maximum, radius, vertical = _planning_bounds(blueprint, seed)
    survey = runtime.validate_survey(runtime.survey(radius=radius, vertical=vertical, entity_radius=48))
    require(_planning_identity(survey) == identity and survey.tick >= seed.tick,
            "building_planning_context_epoch_or_position_changed")
    require(_planning_bounds(blueprint, survey) == (origin, minimum, maximum, radius, vertical),
            "building_planning_returned_body_or_required_bounds_changed")
    require(survey.terrain.get("origin") == origin.json()
            and survey.terrain.get("radius") == radius and survey.terrain.get("vertical") == vertical,
            "building_planning_scan_bounds_changed")
    _, source = _terrain(survey, historical=True)
    require(len(source) == (2*radius+1)**2*(2*vertical+1), "building_planning_scan_incomplete")
    for x in range(minimum.x, maximum.x+1):
        for y in range(minimum.y, maximum.y+1):
            for z in range(minimum.z, maximum.z+1):
                cell = source.get(Pos(x,y,z))
                require(cell is not None and _known_collision(cell), "building_planning_required_cell_unknown")
    return survey


def plan_build(runtime, blueprint, *, max_steps=64):
    require(type(max_steps) is int and 1 <= max_steps <= 64, "invalid_build_navigation_budget")
    blueprint = VersionedBlueprint.parse(blueprint)
    observation = planning_survey(runtime, blueprint)
    plan = execution_plan(blueprint, observation, max_steps=max_steps, historical=True)
    plan.pop("existing")
    return {"format": "capability-building-plan-v3", "blueprint": blueprint.spec(), "executed": False,
            "executable": False, "construction_authority": False, "requires_fresh_execution_preflight": True,
            "observed_tick": observation.tick, "context": list(observation.context), "historical_region_plan": True, "simultaneous_snapshot": False, **plan}


def _item_id(block):
    return {"minecraft:wall_torch": "minecraft:torch", "minecraft:soul_wall_torch": "minecraft:soul_torch"}.get(block, block)


def material_requirements(blueprint):
    """Exact total item bill, independent of inventory and existing-world credit."""
    blueprint = VersionedBlueprint.parse(blueprint)
    counts = Counter(_item_id(block) for _, block, props in blueprint.entries if not (block in DOORS and props["half"] == "upper"))
    return {"blueprint_identity": blueprint.value["identity"], "items": dict(sorted(counts.items())),
            "blockstate_cells": len(blueprint.entries), "placement_items": sum(counts.values()),
            "existing_world_credit": False, "construction_authority": False}


def _record(pos, state):
    return {"position": pos.json(), "block": state[0], "properties": dict(state[1])}


def _record_states(records):
    require(isinstance(records, list) and len(records) <= MAX_CELLS, "invalid_build_checkpoint_cells")
    result = {}
    for row in records:
        require(isinstance(row, dict) and set(row) == {"position", "block", "properties"}, "invalid_build_checkpoint_cell")
        pos = _position(row["position"])
        require(pos not in result, "duplicate_build_checkpoint_cell")
        result[pos] = (row["block"], _properties(row["block"], row["properties"]))
    return result


def _load(path, blueprint, observation):
    import json
    digest = legacy._digest(blueprint.spec())
    if not path.exists():
        return {"schema_version": 3, "blueprint_sha256": digest, "blueprint": blueprint.spec(), "context": list(observation.context), "completed": [], "pending": None, "status": "ready", "placements": 0}
    require(path.stat().st_size <= 8 * 1024 * 1024, "building_checkpoint_too_large")
    try:
        data = json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, OSError) as exc:
        raise SkillError("building_checkpoint_unreadable:" + type(exc).__name__) from None
    require(isinstance(data, dict) and data.get("schema_version") == 3 and data.get("blueprint_sha256") == digest and data.get("blueprint") == blueprint.spec(), "building_checkpoint_blueprint_mismatch")
    require(data.get("context") == list(observation.context), "building_checkpoint_context_changed")
    desired = {p: (b, props) for p, b, props in blueprint.entries}
    completed = _record_states(data.get("completed"))
    require(all(pos in desired and _static_equal(state, desired[pos]) for pos, state in completed.items()), "building_checkpoint_cell_identity_mismatch")
    require(type(data.get("placements")) is int and 0 <= data["placements"] <= MAX_CELLS, "invalid_build_checkpoint_placement_count")
    if data.get("status") == "complete":
        _read_audit_segments(path, path.stem[len("building-"):], data)
    return data


def _checkpoint_capacity(data, blueprint, placements):
    """Prove the fully populated hot checkpoint fits before the first action.

    Audit cells live in bounded immutable segments; this is an exact encoding of
    all future completed cells plus the largest proposed intent and a reserved
    upper bound for 128 segment references and receipt metadata.
    """
    probe = deepcopy(data)
    probe["completed"] = [_record(p, (b, props)) for p, b, props in blueprint.entries]
    probe["pending"] = max(placements, key=lambda value: len(json.dumps(value,sort_keys=True,separators=(",", ":"))), default=None)
    encoded = len(json.dumps(probe,sort_keys=True,separators=(",", ":"),allow_nan=False).encode())
    reserved = 128 * 1024 + 64 * 1024
    require(encoded + reserved <= 8 * 1024 * 1024, "building_checkpoint_capacity_insufficient_before_start")
    return encoded + reserved


def _save_audit_segment(runtime, job_id, data, record):
    require(len(record["positions"]) <= 729, "building_local_audit_segment_cell_budget")
    payload = {"schema_version": 1, "job_id": job_id, "blueprint_sha256": data["blueprint_sha256"],
               "context": data["context"], **record}
    digest = legacy._digest(payload)
    name = "building-" + job_id + "-audit-" + digest + ".json"
    path = Path(runtime.journal_directory) / name
    require(not path.is_symlink(), "building_audit_segment_symlink_rejected")
    if path.exists():
        require(path.stat().st_size <= 512 * 1024 and legacy._digest(json.loads(path.read_text())) == digest, "building_existing_audit_segment_corrupt")
    else:
        atomic_write(path, payload)
    return {"file": name, "sha256": digest, "window_index": record["window_index"], "cells": len(record["positions"]),
            "stand": record["stand"], "ticks": record["ticks"], "request_ids": record["request_ids"]}


def read_build_audit(runtime, *, job_id):
    """Read and integrity-check persisted per-cell evidence without observing the game."""
    path = legacy._path(runtime, job_id)
    require(path.exists() and path.stat().st_size <= 8 * 1024 * 1024, "building_completed_checkpoint_required")
    data = json.loads(path.read_text())
    return _read_audit_segments(path, job_id, data)


def _read_audit_segments(path, job_id, data):
    require(data.get("schema_version") == 3 and data.get("status") == "complete" and data.get("pending") is None, "building_completed_checkpoint_required")
    blueprint = VersionedBlueprint.parse(data["blueprint"])
    require(data.get("blueprint_sha256") == legacy._digest(blueprint.spec()), "building_checkpoint_blueprint_mismatch")
    refs = data.get("final_audit_segments")
    require(isinstance(refs, list) and 1 <= len(refs) <= 128, "building_audit_segment_manifest_required")
    cells, seen = [], set()
    for index, ref in enumerate(refs):
        require(isinstance(ref, dict) and ref.get("window_index") == index, "building_audit_window_identity_mismatch")
        digest = ref.get("sha256")
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "invalid_building_audit_hash")
        name = "building-" + job_id + "-audit-" + digest + ".json"
        require(ref.get("file") == name, "building_audit_segment_path_mismatch")
        segment = path.parent / name
        require(not segment.is_symlink() and segment.exists() and segment.stat().st_size <= 512 * 1024, "building_audit_segment_missing_or_unsafe")
        value = json.loads(segment.read_text())
        require(legacy._digest(value) == digest and value.get("schema_version") == 1 and value.get("job_id") == job_id and value.get("window_index") == index and value.get("blueprint_sha256") == data["blueprint_sha256"] and value.get("context") == data["context"], "building_audit_segment_integrity_failed")
        require(value.get("ticks") == ref.get("ticks") and value.get("request_ids") == ref.get("request_ids") and value.get("stand") == ref.get("stand"), "building_audit_segment_reference_mismatch")
        require(isinstance(value.get("positions"),list) and len(value["positions"]) == ref.get("cells") <= 729, "building_audit_segment_count_mismatch")
        require(len(value.get("ticks",[])) == 2 and all(type(t) is int for t in value["ticks"]) and value["ticks"][0] < value["ticks"][1], "building_audit_segment_ticks_invalid")
        require(len(value.get("request_ids",[])) == 2 and all(isinstance(v,str) and 1 <= len(v) <= 128 for v in value["request_ids"]), "building_audit_segment_requests_invalid")
        require(len(value.get("captured_at",[])) == 2 and all(type(t) in (int,float) and math.isfinite(t) for t in value["captured_at"]) and value["captured_at"][0] <= value["captured_at"][1], "building_audit_segment_capture_times_invalid")
        for pos_json in value["positions"]:
            pos = _position(pos_json)
            require(pos not in seen, "building_audit_duplicate_position")
            seen.add(pos)
            cells.append({"position": pos_json, "ticks": value["ticks"], "request_ids": value["request_ids"], "captured_at": value["captured_at"]})
    require(seen == _audit_targets(blueprint) and data.get("final_audited_cells") == len(seen), "building_audit_coverage_incomplete")
    return {"job_id": job_id, "blueprint_sha256": data["blueprint_sha256"], "cells": cells,
            "simultaneous_region_snapshot": False, "game_observations_performed": False}


def _check_completed(data, observation, *, historical=False, local_only=False, skip=()):
    _, source = _terrain(observation, historical=historical)
    for pos, state in _record_states(data["completed"]).items():
        if pos in skip or local_only and pos not in source:
            continue
        require(_exact(source, pos, state), "previously_completed_build_cell_changed_no_repair_replay")


def _final_goal(blueprint, observation, *, historical=False):
    terrain, source = _terrain(observation, historical=historical)
    require(all(_exact(source, pos, (block, props)) for pos, block, props in blueprint.entries), "building_final_exact_state_verification_failed")
    _verify_clearance(blueprint, terrain)
    # A declared cavity must be enclosed in observed non-air cells. Interior and
    # access clearances deliberately have different semantics.
    cavities = {Pos.parse(row["position"]) for row in blueprint.value["clearance"] if row["purpose"] == "cavity"}
    for pos in cavities:
        for delta in legacy.FACES.values():
            neighbor = pos.offset(*delta)
            if neighbor not in cavities:
                require(terrain.get(neighbor).kind == "solid", "building_cavity_boundary_not_closed_full_cube")
    for check in blueprint.value["light_checks"]:
        value = source.get(Pos.parse(check["position"]), {}).get("block_light")
        require(type(value) is int and check["min_block_light"] <= value <= 15, "building_requested_light_level_not_observed")
    return True


def _fresh(runtime):
    observation = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=48)
    ambient_policy = getattr(runtime, "ambient_policy", None)
    if ambient_policy is not None:
        from building_controller.ambient_entities import classify_ambient_entities
        report = classify_ambient_entities(observation.state, ambient_policy)
        require(report.ok, "building_ambient_observation_blocked:" + ",".join(report.blockers))
    return observation


def _checkpoint_next(data, pending):
    current = _record_states(data["completed"])
    for row in pending["footprint"] + pending["neighbor_updates"]:
        current[Pos.parse(row["position"])] = (row["block"], dict(row["properties"]))
    return [_record(p, state) for p, state in sorted(current.items())]


def build(runtime, blueprint, *, job_id, max_placements=8192, max_moves=8192, max_steps=64, hotbar_slot=0):
    """Execute imported exact-state cells. Never start the game or choose a design.

    Unknown actions stay durably pending; a later call never resubmits them.
    Material counts refer to items, so one door item covers both observed halves.
    Every placement must consume exactly one item and preserve support evidence.
    """
    from .inventory import ensure_hotbar
    from .mobility import navigate_loaded
    require(type(max_placements) is int and 1 <= max_placements <= MAX_CELLS, "invalid_build_placement_budget")
    require(type(max_moves) is int and 0 <= max_moves <= MAX_CELLS and type(max_steps) is int and 1 <= max_steps <= 64, "invalid_build_movement_budget")
    require(type(hotbar_slot) is int and 0 <= hotbar_slot <= 8, "invalid_build_hotbar_slot")
    blueprint = VersionedBlueprint.parse(blueprint)
    path = legacy._path(runtime, job_id)
    survey = planning_survey(runtime, blueprint)
    data = _load(path, blueprint, survey)
    require(data.get("pending") is None, "interrupted_build_placement_requires_read_only_reconciliation_no_replay")
    _check_completed(data, survey, historical=True)
    # This exact immutable opt-in retains the original whole-case envelope.
    # No callback or caller-filtered entity snapshot is accepted.
    ambient_policy = getattr(runtime, "ambient_policy", None)
    first = execution_plan(blueprint, survey, max_steps=max_steps, historical=True,
                           ambient_policy=ambient_policy)
    audit_stand = Pos(*(math.floor(survey.player[k]) for k in ("x", "y", "z")))
    _initial_budget(runtime, first, audit_stand, max_placements=max_placements,
                    max_moves=max_moves, max_steps=max_steps)
    # Adopt initial exact stage states once. These cells also become protected
    # against later disappearance; an interrupted build cannot silently rebuild.
    prior = _record_states(data["completed"])
    prior.update(first["existing"])
    data["completed"] = [_record(p, state) for p, state in sorted(prior.items())]
    capacity = _checkpoint_capacity(data, blueprint, first["placements"])
    atomic_write(path, data)
    placements, moves, ids = 0, 0, []
    for proposed in first["placements"]:
        observation = _fresh(runtime)
        require(observation.context == survey.context, "building_context_changed_since_survey")
        _check_completed(data, observation, local_only=True)
        require(placements < max_placements, "build_placement_budget_exhausted")
        entry = deepcopy(proposed)
        target, stand = Pos.parse(entry["position"]), Pos.parse(entry["stand"])
        centered = math.hypot(observation.player["x"] - stand.x - .5, observation.player["z"] - stand.z - .5) <= .23 and abs(observation.player["y"] - stand.y) <= .15
        movement_actions, movement_seconds = (0, 0) if centered else _navigation_budget(runtime, entry["route"], max_steps)
        _audit_budget(runtime, first["audit_windows"], first["audit_return_route"], max_steps=max_steps,
            current_actions=3 + movement_actions,
            current_seconds=movement_seconds + _placement_seconds(runtime))
        if not centered:
            require(moves < max_moves, "build_move_budget_exhausted")
            outcome = navigate_loaded(runtime, stand.json(), **_navigation_limits(entry["route"], max_steps))
            ids.extend(outcome.request_ids)
            runtime.require_success(outcome)
            moves += 1
        outcome = ensure_hotbar(runtime, entry["item"], hotbar_slot=hotbar_slot)
        ids.extend(outcome.request_ids)
        runtime.require_success(outcome)
        observation = _fresh(runtime)
        _check_completed(data, observation, local_only=True)
        terrain, source = _terrain(observation)
        require(target in source, "building_target_outside_fresh_local_scan")
        states = _states(source)
        desired = {p: (b, props) for p, b, props in blueprint.entries}
        footprint = {Pos.parse(row["position"]) for row in entry["footprint"]}
        projected, updates, affected = _stage_changes(footprint, desired, states)
        require(all(terrain.get(p).kind in ("clear", "solid", "obstacle", "tread") for p in affected), "building_fresh_footprint_neighbors_unknown_or_unsafe")
        entry["footprint"] = [_record(pos, updates[pos]) for pos in sorted(footprint)]
        entry["neighbor_updates"] = [_record(pos, state) for pos, state in sorted(updates.items()) if pos not in footprint]
        entry["properties"] = updates[target][1]
        here, eye_height, reach = legacy._geometry(observation)
        raw_state = (entry["block"], entry["properties"])
        candidate = _placement_candidate(target, raw_state, terrain.cells, _states(source), {here: (here,)}, eye_height, reach, tuple(observation.player["eye_position"][k] for k in ("x", "y", "z")), required_positions=affected)
        require(candidate is not None, "building_no_current_visible_oriented_support")
        entry.update({k: candidate[k] for k in ("support", "face", "stand", "route", "placement_hit", "placement_yaw")})
        support = Pos.parse(entry["support"])
        desired_states = _record_states(entry["footprint"] + entry["neighbor_updates"])
        for row in entry["footprint"]:
            require(terrain.get(Pos.parse(row["position"])).kind == "clear", "building_footprint_no_longer_air")
        fresh_blockers = state_blockers(observation.state, terrain, list(footprint),
                                        ambient_policy=ambient_policy)
        require(not fresh_blockers, "building_fresh_preflight_blocked:" + ",".join(fresh_blockers))
        before_counts = Counter(parse_inventory(observation.state))
        wanted = before_counts.copy()
        wanted[entry["item"]] -= 1
        require(wanted[entry["item"]] >= 0, "building_material_disappeared")
        wanted = +wanted
        command = {"op": "action", "action": "place_block", "support": support.json(), "face": entry["face"],
            "hotbar_slot": observation.player["selected_slot"], "jump": False, "sneak": source[support]["id"] in STATIONS | {"minecraft:crafting_table"}, "timeout_ms": 5000,
            "expected_support_id": source[support]["id"], "expected_support_properties": dict(source[support]["properties"]),
            "expected_target_id": source[target]["id"], "expected_target_properties": dict(source[target]["properties"]),
            "expected_block_id": entry["block"], "expected_block_properties": dict(entry["properties"]),
            "placement_hit": dict(entry["placement_hit"]), "placement_yaw": entry["placement_yaw"],
            "placement_footprint": [{"position": row["position"], "expected_id": source[Pos.parse(row["position"])]["id"],
                "expected_properties": dict(source[Pos.parse(row["position"])]["properties"]), "block_id": row["block"], "properties": dict(row["properties"])} for row in entry["footprint"]]}
        pending = dict(deepcopy(entry), before_tick=observation.tick, status="intent_persisted", request_ids=[])
        data.update(pending=pending, status="in_progress")
        atomic_write(path, data)
        def verified(_before, after):
            _, raw = _terrain(after)
            counts = +Counter(parse_inventory(after.state))
            return (all(_exact(raw, p, state) for p, state in desired_states.items())
                    and _exact(raw, support, (source[support]["id"], source[support]["properties"])) and counts == wanted)
        outcome = runtime.execute("building.place_oriented", command, verified, before=observation)
        pending.update(status=outcome.status, request_ids=list(outcome.request_ids), reason=outcome.reason)
        ids.extend(outcome.request_ids)
        atomic_write(path, data)
        observation = runtime.require_success(outcome)
        data.update(completed=_checkpoint_next(data, pending), pending=None, placements=data["placements"] + 1)
        atomic_write(path, data)
        placements += 1
    # Only fresh local Observation windows certify final cells. Historical
    # surveys remain proposal evidence even after all placements are complete.
    audits, audited_cells = [], 0
    for window in first["audit_windows"]:
        observation = _fresh(runtime)
        stand = Pos.parse(window["stand"])
        if not _at_stand(observation, stand):
            require(moves < max_moves, "build_audit_move_budget_exhausted")
            outcome = navigate_loaded(runtime, stand.json(), **_navigation_limits(window["route"], max_steps))
            ids.extend(outcome.request_ids)
            runtime.require_success(outcome)
            moves += 1
        before_audit = _fresh(runtime)
        require(before_audit.context == survey.context, "building_audit_context_changed")
        samples = []
        tick = before_audit.tick
        positions = {Pos.parse(p) for p in window["positions"]}
        for _ in range(8):
            runtime.sleeper(.05)
            after = _fresh(runtime)
            require(after.context == survey.context and _at_stand(after, stand), "building_audit_pose_or_context_changed")
            _verify_window(blueprint, after, positions)
            if after.tick > tick:
                samples.append(after)
                tick = after.tick
                if len(samples) == 2:
                    break
        require(len(samples) == 2, "building_fresh_audit_stable_ticks_missing")
        record = {"window_index": len(audits), "stand": stand.json(), "positions": window["positions"],
                  "request_ids": [a.request_id for a in samples], "ticks": [a.tick for a in samples],
                  "captured_at": [a.captured_at for a in samples]}
        audits.append(_save_audit_segment(runtime, job_id, data, record))
        audited_cells += len(window["positions"])
        data.update(final_audit_segments=audits, final_audited_cells=audited_cells)
        atomic_write(path, data)
    observation = _fresh(runtime)
    if not _at_stand(observation, audit_stand):
        require(moves < max_moves, "build_audit_return_move_budget_exhausted")
        outcome = navigate_loaded(runtime, audit_stand.json(), **_navigation_limits(first["audit_return_route"], max_steps))
        ids.extend(outcome.request_ids)
        runtime.require_success(outcome)
        moves += 1
    final = _fresh(runtime)
    require(final.context == survey.context and _at_stand(final, audit_stand), "building_final_context_or_exit_changed")
    _check_completed(data, final, local_only=True)
    stable = [final]
    data.update(status="complete", final_tick=stable[-1].tick)
    atomic_write(path, data)
    return runtime.result("building.build_v3", stable, job_id=job_id, blueprint_sha256=data["blueprint_sha256"],
        blueprint_identity=blueprint.value["identity"], exact_cells_verified=len(blueprint.entries),
        placements_this_call=placements, moves_this_call=moves, completed_placements=data["placements"],
        action_request_ids=ids, requested_properties_exact=True, multi_cell_footprints_verified=True,
        light_checks_verified=len(blueprint.value["light_checks"]), clearance_checks_verified=len(blueprint.value["clearance"]),
        simultaneous_region_snapshot=False, final_verification="two_later_tick_fresh_local_samples_per_cell",
        final_audit_segments=audits, final_audited_cells=audited_cells, checkpoint_reserved_bytes=capacity, final_exit_stand=audit_stand.json(),
        progress_retained=True, no_replayed_placements=True)


def reconcile_build_progress(runtime, blueprint, *, job_id):
    """Read-only exact presence adoption; Runtime unknown-ID latch remains authoritative."""
    blueprint = VersionedBlueprint.parse(blueprint)
    path = legacy._path(runtime, job_id)
    require(path.exists(), "building_progress_not_found")
    first = _fresh(runtime)
    data = _load(path, blueprint, first)
    pending = data.get("pending")
    require(isinstance(pending, dict) and "footprint" in pending and "neighbor_updates" in pending, "building_has_no_pending_placement")
    next_records = _checkpoint_next(data, pending)
    desired = {p: (b, props) for p, b, props in blueprint.entries}
    states = _record_states(next_records)
    require(all(pos in desired and _static_equal(state, desired[pos]) for pos, state in states.items()), "invalid_pending_build_identity")
    _, source = _terrain(first)
    required = _record_states(pending["footprint"] + pending["neighbor_updates"])
    _check_completed(data, first, local_only=True, skip=set(required))
    require(all(_exact(source, pos, state) for pos, state in required.items()), "pending_build_target_not_exact_no_replay")
    runtime.sleeper(.05)
    second = _fresh(runtime)
    _, source = _terrain(second)
    require(second.tick > first.tick and all(_exact(source, pos, state) for pos, state in required.items()), "pending_build_target_not_stable")
    data.update(completed=next_records, pending=None, status="ready", reconciliation={"original_request_ids": pending.get("request_ids", []), "after_tick": second.tick, "causation_confirmed": False})
    atomic_write(path, data)
    return runtime.result("building.reconcile_v3", (first, second), job_id=job_id, exact_presence_verified=True, presence_scope="pending_footprint_and_expected_neighbor_updates", distant_completed_revalidated=False, causation_confirmed=False, actions_replayed=0)
