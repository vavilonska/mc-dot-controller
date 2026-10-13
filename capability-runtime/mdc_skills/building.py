"""Real bounded full-cube blueprint executor with durable per-cell checkpoints.

The historical building_controller planner remains planning-only. This adapter
adds fresh material/stand/face checks, guarded navigation and actual native
placements. A saved plan is never a freshness or execution authorization token.
Unsupported stateful/gravity/fluid blocks fail before mutation.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from itertools import product
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType

from building_controller.model import Blueprint, Pos, Region, PlanError, PALETTE, MAX_BLOCKS
from building_controller.planner import plan as geometric_plan, ANCHORS
from building_controller.terrain import Cell, Terrain, parse_inventory
from .core import SkillError, require, atomic_write

FACES = {"up": (0, 1, 0), "down": (0, -1, 0), "north": (0, 0, -1),
         "south": (0, 0, 1), "east": (1, 0, 0), "west": (-1, 0, 0)}


@dataclass(frozen=True)
class CellBlueprint:
    """Explicit generic full-cube positions, independent of floor/wall templates."""
    region: Region
    entries: tuple

    def cells(self):
        return self.entries

    def spec(self):
        return {"schema_version": 2, "region": self.region.json(), "cells": [
            {"position": p.json(), "block": block, "properties": {}} for p, block in self.entries]}

    @classmethod
    def parse(cls, spec):
        require(isinstance(spec, dict) and set(spec) == {"schema_version", "region", "cells"}
                and type(spec["schema_version"]) is int and spec["schema_version"] == 2,
                "invalid_cell_blueprint_schema")
        try:
            region = Region.parse(spec["region"])
            cells = spec["cells"]
            require(isinstance(cells, list) and 1 <= len(cells) <= MAX_BLOCKS,
                    "cell_blueprint_budget_must_be_1_to_512")
            entries, seen = [], set()
            for entry in cells:
                require(isinstance(entry, dict) and set(entry) == {"position", "block", "properties"},
                        "invalid_blueprint_cell")
                pos = Pos.parse(entry["position"])
                require(pos not in seen and region.contains(pos), "duplicate_or_outside_blueprint_cell")
                require(entry["block"] in PALETTE and entry["properties"] == {},
                        "unsupported_blueprint_block_or_properties")
                seen.add(pos)
                entries.append((pos, entry["block"]))
            return cls(region, tuple(sorted(entries, key=lambda v: (v[0].y, v[0].z, v[0].x))))
        except (PlanError, TypeError, KeyError) as exc:
            raise SkillError("invalid_cell_blueprint:" + str(exc)) from None


def _blueprint(spec):
    if isinstance(spec, Blueprint):
        # Frozen dataclasses can still have been constructed without parse().
        spec = spec.spec()
    if isinstance(spec, CellBlueprint):
        spec = spec.spec()
    try:
        if isinstance(spec, dict) and spec.get("schema_version") == 1:
            return Blueprint.parse(spec)
        return CellBlueprint.parse(spec)
    except PlanError as exc:
        raise SkillError("invalid_blueprint:" + str(exc)) from None


def _terrain(observation, *, extended=False, historical=False):
    raw = observation.terrain
    require(isinstance(raw, dict) and raw.get("complete") is True, "building_complete_terrain_required")
    world = observation.state.get("world", {})
    require(raw.get("world_generation") == world.get("world_generation")
            and raw.get("dimension") == world.get("dimension") == "minecraft:overworld",
            "building_terrain_context_or_dimension_mismatch")
    require(isinstance(raw.get("scan_generation"), str) and bool(raw["scan_generation"]),
            "building_scan_identity_required")
    first, last = raw.get("source_tick"), raw.get("last_tick")
    require(type(first) is int and type(last) is int and first <= last <= observation.tick
            and (historical or observation.tick - first <= 40), "building_terrain_tick_mismatch")
    started, finished = raw.get("capture_started_mono"), raw.get("capture_finished_mono")
    require(type(started) in (int, float) and type(finished) in (int, float)
            and math.isfinite(started) and math.isfinite(finished) and 0 <= finished - started <= (120 if historical else .8),
            "building_original_capture_interval_required")
    require(isinstance(raw.get("cells"), list) and len(raw["cells"]) <= 18513,
            "invalid_building_terrain_cells")
    try:
        origin = Pos.parse(raw["origin"])
        radius, vertical = raw["radius"], raw["vertical"]
        require(type(radius) is int and 1 <= radius <= (16 if extended else 8) and type(vertical) is int and 2 <= vertical <= (8 if extended else 4),
                "building_terrain_bounds_not_supported")
        parsed, source = {}, {}
        for cell in raw["cells"]:
            require(isinstance(cell, dict), "building_malformed_cell")
            value = Cell.parse(cell)
            if extended:
                from .building_v3 import classify
                value = classify(cell, value)
            pos = value.position
            require(pos not in parsed, "building_duplicate_cell")
            require(abs(pos.x - origin.x) <= radius and abs(pos.z - origin.z) <= radius
                    and abs(pos.y - origin.y) <= vertical, "building_cell_outside_declared_scan")
            parsed[pos], source[pos] = value, cell
        terrain = Terrain(MappingProxyType(parsed), raw["world_generation"], raw["scan_generation"],
                          raw["dimension"], first, last, origin, radius, vertical)
        return terrain, source
    except (PlanError, KeyError, TypeError) as exc:
        raise SkillError("building_terrain_invalid:" + str(exc)) from None


def _exact(terrain, source, pos, block):
    cell = terrain.get(pos)
    return cell.kind == "solid" and cell.block_id == block and source.get(pos, {}).get("properties") == {}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _geometry(observation):
    p = observation.player
    require(all(_finite(p.get(k)) for k in ("x", "y", "z")), "building_player_position_missing")
    eye = p.get("eye_position", {})
    reach = p.get("block_interaction_range")
    require(all(_finite(eye.get(k)) for k in ("x", "y", "z"))
            and _finite(reach) and 0 < reach <= 6, "building_observed_reach_required")
    require(p.get("on_ground") is True, "building_requires_grounded_player")
    eye_height = eye["y"] - p["y"]
    require(1.0 <= eye_height <= 1.9, "building_unsupported_player_pose")
    velocity = p.get("velocity", {})
    require(all(_finite(velocity.get(k)) for k in ("x", "y", "z"))
            and math.hypot(velocity["x"], velocity["z"]) <= .08
            and abs(velocity["y"]) <= .1, "building_requires_settled_player")
    return Pos(*(math.floor(p[k]) for k in ("x", "y", "z"))), eye_height, reach


def _standable(cells, pos, blocked):
    def kind(p):
        return cells[p].kind if p in cells else "unknown"
    if pos in blocked or pos.offset(y=1) in blocked:
        return False
    if not (kind(pos) == kind(pos.offset(y=1)) == "clear" and kind(pos.offset(y=-1)) == "solid"):
        return False
    # A one-cell horizontal safety envelope rejects unknown/fluid/hazard cells.
    return all(kind(pos.offset(x=dx, y=dy, z=dz)) in ("clear", "solid")
               for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)) for dy in (0, 1))


def _routes(cells, start, blocked, max_steps):
    require(_standable(cells, start, blocked), "building_start_not_safe_or_overlaps_target")
    paths, pending = {start: (start,)}, deque([start])
    while pending:
        pos = pending.popleft()
        if len(paths[pos]) - 1 >= max_steps:
            continue
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            target = pos.offset(x=dx, z=dz)
            if target not in paths and _standable(cells, target, blocked):
                paths[target] = paths[pos] + (target,)
                pending.append(target)
    return paths


def _face_point(support, face):
    return tuple(v + .5 + FACES[face][i] * .5 for i, v in enumerate((support.x, support.y, support.z)))


def _visible(cells, stand, eye_height, support, face, reach, *, actual_eye=None, hit_point=None):
    eye = actual_eye or (stand.x + .5, stand.y + eye_height, stand.z + .5)
    point = hit_point or _face_point(support, face)
    if math.dist(eye, point) > reach - .05:
        return False
    normal = FACES[face]
    if sum((eye[i] - point[i]) * normal[i] for i in range(3)) <= .001:
        return False
    # Exact voxel-boundary split points, not undersampled ray marching. Require
    # all touched cells to be known air, including ambiguous interior edges.
    # Minecraft independently repeats its real collision/raycast before input.
    crossings = {0., 1.}
    for axis in range(3):
        delta = point[axis] - eye[axis]
        if abs(delta) <= 1e-12:
            continue
        for boundary in range(math.floor(min(eye[axis], point[axis])), math.ceil(max(eye[axis], point[axis])) + 1):
            t = (boundary - eye[axis]) / delta
            if 0 < t < 1:
                crossings.add(t)
    ordered = sorted(crossings)
    samples = [(a + b) / 2 for a, b in zip(ordered, ordered[1:])] + ordered[1:-1]
    for t in samples:
        xyz = tuple(eye[i] + (point[i] - eye[i]) * t for i in range(3))
        indices = []
        for value in xyz:
            low = math.floor(value)
            indices.append((low - 1, low) if abs(value - low) <= 1e-9 else (low,))
        for coordinates in product(*indices):
            pos = Pos(*coordinates)
            if pos == support or pos not in cells or cells[pos].kind != "clear":
                return False
    return True


def _execution_plan(blueprint, observation, *, max_steps=128):
    terrain, source = _terrain(observation)
    try:
        base = geometric_plan(blueprint, terrain, observation.state)
    except (PlanError, KeyError, TypeError) as exc:
        raise SkillError("building_geometric_plan_invalid:" + str(exc)) from None
    require(not base["blockers"], "building_preflight_blocked:" + ",".join(sorted({b["code"] for b in base["blockers"]})))
    if not base["proposed_placements"]:
        return {"material_plan": base["materials"], "placements": [], "already_correct": base["summary"]["already_correct"]}
    start, eye_height, reach = _geometry(observation)
    cells = dict(terrain.cells)
    blocked = {pos for pos, _ in blueprint.cells()}
    remaining = {Pos.parse(p["position"]): p["block"] for p in base["proposed_placements"]}
    ordered = []
    while remaining:
        routes = _routes(cells, start, blocked, max_steps)
        chosen = None
        for pos in sorted(remaining, key=lambda p: (p.y, p.z, p.x)):
            for dx, dy, dz, face in ANCHORS:
                support = pos.offset(dx, dy, dz)
                if support not in cells or cells[support].kind != "solid":
                    continue
                candidates = sorted(routes, key=lambda s: (len(routes[s]), math.dist((s.x, s.y, s.z), (pos.x, pos.y, pos.z)), s))
                stand = next((s for s in candidates if _visible(cells, s, eye_height, support, face, reach)), None)
                if stand is not None:
                    chosen = {"position": pos.json(), "block": remaining[pos], "properties": {},
                              "support": support.json(), "face": face, "stand": stand.json(),
                              "route": [p.json() for p in routes[stand]], "reach": reach}
                    break
            if chosen:
                break
        require(chosen is not None, "building_no_reachable_visible_supported_stand")
        pos = Pos.parse(chosen["position"])
        cells[pos] = Cell(pos, remaining.pop(pos), "solid", "planned_full_cube")
        start = Pos.parse(chosen["stand"])
        ordered.append(chosen)
    return {"material_plan": base["materials"], "placements": ordered, "already_correct": base["summary"]["already_correct"]}


def plan_build(runtime, blueprint, *, max_steps=64):
    """Fresh material/support/flat-stand proposal. No game mutation or success claim."""
    require(type(max_steps) is int and 1 <= max_steps <= 128, "invalid_build_navigation_budget")
    from .building_v3 import VersionedBlueprint
    if isinstance(blueprint, VersionedBlueprint):
        blueprint = blueprint.spec()
    if isinstance(blueprint, dict) and blueprint.get("schema_version") == 3:
        from .building_v3 import plan_build as oriented_plan
        return oriented_plan(runtime, blueprint, max_steps=max_steps)
    blueprint = _blueprint(blueprint)
    before = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=32)
    value = _execution_plan(blueprint, before, max_steps=max_steps)
    return {"format": "capability-building-plan-v1", "blueprint": blueprint.spec(),
            "executed": False, "executable": False, "requires_fresh_execution_preflight": True,
            "observed_tick": before.tick, "context": list(before.context), **value}


def _path(runtime, job_id):
    require(isinstance(job_id, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", job_id) is not None,
            "invalid_build_job_id")
    path = Path(runtime.journal_directory) / ("building-" + job_id + ".json")
    require(not path.is_symlink(), "building_progress_symlink_rejected")
    return path


def _digest(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _load_progress(path, blueprint, observation):
    digest = _digest(blueprint.spec())
    if not path.exists():
        data = {"schema_version": 1, "blueprint_sha256": digest, "blueprint": blueprint.spec(),
                "context": list(observation.context), "completed": [], "pending": None, "status": "ready"}
        atomic_write(path, data)
        return data
    require(path.stat().st_size <= 1024 * 1024, "building_progress_too_large")
    try:
        data = json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, OSError) as exc:
        raise SkillError("building_progress_unreadable:" + type(exc).__name__) from None
    require(isinstance(data, dict) and data.get("schema_version") == 1 and data.get("blueprint_sha256") == digest
            and data.get("blueprint") == blueprint.spec(), "building_checkpoint_blueprint_mismatch")
    require(data.get("context") == list(observation.context), "building_checkpoint_context_changed")
    require(isinstance(data.get("completed"), list) and len(data["completed"]) <= MAX_BLOCKS,
            "invalid_building_checkpoint")
    desired = dict(blueprint.cells())
    seen = set()
    for entry in data["completed"]:
        require(isinstance(entry, dict), "invalid_building_completion_record")
        try:
            pos = Pos.parse(entry["position"])
        except (KeyError, PlanError, TypeError):
            raise SkillError("invalid_building_completion_position") from None
        require(pos not in seen and desired.get(pos) == entry.get("block") and entry.get("properties") == {},
                "invalid_building_completion_identity")
        seen.add(pos)
    return data


def _check_completed(data, observation):
    terrain, source = _terrain(observation)
    for cell in data["completed"]:
        require(_exact(terrain, source, Pos.parse(cell["position"]), cell["block"]),
                "previously_completed_build_cell_changed_no_repair_replay")


def _full_goal(blueprint, observation):
    terrain, source = _terrain(observation)
    return all(_exact(terrain, source, pos, block) for pos, block in blueprint.cells())


def _final_observations(runtime, blueprint, before):
    observations = []
    tick = before.tick
    for _ in range(8):
        runtime.sleeper(.05)
        after = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=32)
        require(_full_goal(blueprint, after), "building_final_exact_block_verification_failed")
        if after.tick > tick:
            observations.append(after)
            tick = after.tick
            if len(observations) == 2:
                return observations
    raise SkillError("building_final_stable_ticks_not_observed")


def build(runtime, blueprint, *, job_id, max_placements=None, max_moves=None, max_steps=64, hotbar_slot=0):
    """Execute one bounded generic blueprint in the current loaded work area.

    Requires an explicit persistent job_id. Re-entry skips freshly verified
    completed cells. Any interrupted/failed placement remains pending and blocks
    all further mutations for that job until read-only reconciliation proves the
    requested block; no operation is replayed to discover its outcome.
    """
    from .building_v3 import VersionedBlueprint
    if isinstance(blueprint, VersionedBlueprint):
        blueprint = blueprint.spec()
    if isinstance(blueprint, dict) and blueprint.get("schema_version") == 3:
        from .building_v3 import build as oriented_build
        return oriented_build(runtime, blueprint, job_id=job_id, max_placements=8192 if max_placements is None else max_placements, max_moves=8192 if max_moves is None else max_moves, max_steps=max_steps, hotbar_slot=hotbar_slot)
    max_placements = 512 if max_placements is None else max_placements
    max_moves = 512 if max_moves is None else max_moves
    from .reach import navigate
    from .inventory import ensure_hotbar
    require(type(max_placements) is int and 1 <= max_placements <= MAX_BLOCKS, "invalid_build_placement_budget")
    require(type(max_moves) is int and 0 <= max_moves <= MAX_BLOCKS, "invalid_build_move_budget")
    require(type(max_steps) is int and 1 <= max_steps <= 128, "invalid_build_navigation_budget")
    require(type(hotbar_slot) is int and 0 <= hotbar_slot <= 8, "invalid_build_hotbar_slot")
    blueprint = _blueprint(blueprint)
    path = _path(runtime, job_id)
    observation = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=32)
    data = _load_progress(path, blueprint, observation)
    require(data.get("pending") is None, "interrupted_build_placement_requires_read_only_reconciliation_no_replay")
    _check_completed(data, observation)
    if data.get("status") == "complete":
        require(_full_goal(blueprint, observation), "completed_blueprint_changed_no_automatic_rebuild")
    first_plan = _execution_plan(blueprint, observation, max_steps=max_steps)
    require(len(first_plan["placements"]) <= max_placements, "build_placement_budget_insufficient_before_start")
    # Worst case one stand movement per placement; a smaller explicit movement
    # budget is accepted only when the whole initial stand sequence fits it.
    current, _, _ = _geometry(observation) if first_plan["placements"] else (None, None, None)
    planned_moves = 0
    for entry in first_plan["placements"]:
        stand = Pos.parse(entry["stand"])
        if stand != current:
            planned_moves += 1
        current = stand
    require(planned_moves <= max_moves, "build_move_budget_insufficient_before_start")
    placements, moves, ids = 0, 0, []
    while True:
        _check_completed(data, observation)
        proposal = _execution_plan(blueprint, observation, max_steps=max_steps)
        if not proposal["placements"]:
            break
        require(placements < max_placements, "build_placement_budget_exhausted")
        next_cell = proposal["placements"][0]
        target, support, stand = (Pos.parse(next_cell[k]) for k in ("position", "support", "stand"))
        player = observation.player
        centered = (math.hypot(player["x"] - (stand.x + .5), player["z"] - (stand.z + .5)) <= .23
                    and abs(player["y"] - stand.y) <= .15)
        if not centered:
            require(moves < max_moves, "build_move_budget_exhausted")
            move = navigate(runtime, stand.json(), max_steps=max_steps)
            ids.extend(move.request_ids)
            runtime.require_success(move)
            moves += 1
        selected = ensure_hotbar(runtime, next_cell["block"], hotbar_slot=hotbar_slot)
        ids.extend(selected.request_ids)
        runtime.require_success(selected)
        # Selection/movement may have changed the world. Recompute the entire
        # proposal from new terrain, then use only a current-position stand.
        observation = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=32)
        _check_completed(data, observation)
        refreshed = _execution_plan(blueprint, observation, max_steps=max_steps)
        require(refreshed["placements"], "building_target_changed_during_preparation")
        next_cell = next((p for p in refreshed["placements"] if Pos.parse(p["position"]) == target), None)
        require(next_cell is not None, "building_target_already_changed_without_verified_placement")
        terrain, source = _terrain(observation)
        here, eye_height, reach = _geometry(observation)
        # Rechoose a support visible from exactly this verified stand. Native
        # repeats range/raycast, target/support state and held-item checks.
        support_face = next(((target.offset(dx, dy, dz), face) for dx, dy, dz, face in ANCHORS
            if terrain.get(target.offset(dx, dy, dz)).kind == "solid"
            and _visible(terrain.cells, here, eye_height, target.offset(dx, dy, dz), face, reach,
                         actual_eye=tuple(observation.player["eye_position"][k] for k in ("x", "y", "z")))), None)
        require(support_face is not None, "building_no_visible_support_from_current_stand")
        support, face = support_face
        require(terrain.get(target).kind == "clear", "building_target_no_longer_air")
        try:
            before_counts = Counter(parse_inventory(observation.state))
        except PlanError as exc:
            raise SkillError("building_inventory_invalid:" + str(exc)) from None
        wanted = before_counts.copy()
        wanted[next_cell["block"]] -= 1
        require(wanted[next_cell["block"]] >= 0, "building_material_disappeared")
        wanted = +wanted
        command = {"op": "action", "action": "place_block", "support": support.json(), "face": face,
                   "hotbar_slot": observation.player["selected_slot"], "jump": False, "sneak": False, "timeout_ms": 5000,
                   "expected_support_id": source[support]["id"],
                   "expected_support_properties": dict(source[support]["properties"]),
                   "expected_target_id": source[target]["id"],
                   "expected_target_properties": dict(source[target]["properties"]),
                   "expected_block_id": next_cell["block"], "expected_block_properties": {}}
        pending = {"position": target.json(), "block": next_cell["block"], "properties": {},
                   "before_tick": observation.tick, "support": support.json(), "face": face,
                   "status": "intent_persisted", "request_ids": []}
        data.update(pending=pending, status="in_progress")
        atomic_write(path, data)
        def verified(_before, after):
            other, raw = _terrain(after)
            try:
                counts = +Counter(parse_inventory(after.state))
            except PlanError:
                return False
            unchanged_support = (raw.get(support, {}).get("id") == source[support]["id"]
                                 and raw.get(support, {}).get("properties") == source[support]["properties"])
            return _exact(other, raw, target, next_cell["block"]) and unchanged_support and counts == wanted
        try:
            outcome = runtime.execute("building.place", command, verified, before=observation)
            pending.update(status=outcome.status, request_ids=list(outcome.request_ids), reason=outcome.reason)
            ids.extend(outcome.request_ids)
            atomic_write(path, data)
            observation = runtime.require_success(outcome)
        except BaseException:
            # The intent is already durable. Never synthesize completion or
            # submit another placement during an exception/restart path.
            raise
        completed = dict(pending, status="client_observed_stable", after_tick=observation.tick)
        data["completed"].append(completed)
        data.update(pending=None, status="in_progress")
        atomic_write(path, data)
        placements += 1
    stable = _final_observations(runtime, blueprint, observation)
    data.update(status="complete", final_tick=stable[-1].tick, pending=None)
    atomic_write(path, data)
    return runtime.result("building.build", stable, job_id=job_id, blueprint_sha256=data["blueprint_sha256"],
        exact_cells_verified=len(blueprint.cells()), placements_this_call=placements, moves_this_call=moves,
        completed_placements=len(data["completed"]), action_request_ids=ids,
        requested_properties_exact=True, progress_retained=True, no_replayed_placements=True)


def reconcile_build_progress(runtime, blueprint, *, job_id):
    """Read-only world reconciliation of a persisted placement; never resubmits.

    The Runtime's exact-ID unknown/release reconciliation must have succeeded
    first. A currently correct block can be adopted as observed presence, never
    as proof this process/server performed that earlier interrupted operation.
    """
    from .building_v3 import VersionedBlueprint
    if isinstance(blueprint, VersionedBlueprint):
        blueprint = blueprint.spec()
    if isinstance(blueprint, dict) and blueprint.get("schema_version") == 3:
        from .building_v3 import reconcile_build_progress as oriented_reconcile
        return oriented_reconcile(runtime, blueprint, job_id=job_id)
    blueprint = _blueprint(blueprint)
    path = _path(runtime, job_id)
    require(path.exists(), "building_progress_not_found")
    observation = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=32)
    data = _load_progress(path, blueprint, observation)
    _check_completed(data, observation)
    pending = data.get("pending")
    require(isinstance(pending, dict), "building_has_no_pending_placement")
    try:
        target = Pos.parse(pending["position"])
        block = dict(blueprint.cells()).get(target)
        require(block == pending.get("block") and pending.get("properties") == {}, "invalid_pending_build_identity")
    except (PlanError, KeyError, TypeError):
        raise SkillError("invalid_pending_build_identity") from None
    terrain, source = _terrain(observation)
    require(_exact(terrain, source, target, block), "pending_build_target_not_exact_no_replay")
    second = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=32)
    other, raw = _terrain(second)
    require(second.tick > observation.tick and _exact(other, raw, target, block), "pending_build_target_not_stable")
    data["completed"].append(dict(pending, status="observed_present_after_interruption",
                                  after_tick=second.tick, causation_confirmed=False))
    data.update(pending=None, status="ready")
    atomic_write(path, data)
    return runtime.result("building.reconcile", (observation, second), job_id=job_id,
        target=target.json(), block=block, exact_presence_verified=True, causation_confirmed=False,
        actions_replayed=0, may_continue_with_new_fresh_preflight=True)
