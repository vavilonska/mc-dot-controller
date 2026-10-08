"""Conservative geometric construction plan, intentionally without an executor."""
from collections import Counter

from .model import Blueprint, PlanError
from .terrain import Terrain, parse_inventory, state_blockers, unwrap


# Position of an anchor relative to a target, and face clicked on that anchor.
# Only below and horizontal full-cube anchors are proposed in this first version.
ANCHORS = ((0, -1, 0, "up"), (-1, 0, 0, "east"), (1, 0, 0, "west"),
           (0, 0, -1, "south"), (0, 0, 1, "north"))
NEIGHBORS = tuple((x, y, z) for x, y, z, _ in ANCHORS) + ((0, 1, 0),)


def plan(blueprint: Blueprint, terrain: Terrain, state=None):
    """Produce a JSON-serializable review artifact. Never call any game service."""
    desired = blueprint.cells()
    total = Counter(block for _, block in desired)
    existing, remaining, candidates, assessments = Counter(), Counter(), {}, []
    blockers = []
    for pos, block in desired:
        cell = terrain.get(pos)
        if cell.kind == "solid" and cell.block_id == block:
            existing[block] += 1
            status, reason = "already_correct", "skip_existing_correct_block"
        else:
            remaining[block] += 1
            if cell.kind == "clear":
                status, reason = "candidate_air", "known_air_not_yet_reachability_validated"
                candidates[pos] = block
            elif cell.kind == "solid":
                status, reason = "conflict", "existing_block_must_not_be_broken_or_replaced"
            else:
                status, reason = "blocked", cell.reason
            if status != "candidate_air":
                blockers.append({"code": reason, "position": pos.json()})
        assessments.append({"position": pos.json(), "desired": block, "observed": cell.block_id,
                            "classification": status, "reason": reason})

    # Checking six immediate neighbors is intentionally conservative. It does not
    # claim to establish all hazards or a walkable / reachable work position.
    envelope_errors = set()
    for pos in candidates:
        for dx, dy, dz in NEIGHBORS:
            neighbor = pos.offset(dx, dy, dz)
            cell = terrain.get(neighbor)
            if cell.kind not in ("clear", "solid") and neighbor not in envelope_errors:
                envelope_errors.add(neighbor)
                blockers.append({"code": "unsafe_or_unknown_adjacent_cell", "position": neighbor.json(),
                                 "detail": cell.reason})

    if state is not None:
        state = unwrap(state)
    for error in state_blockers(state, terrain, [pos for pos, block in desired
                                               if not (terrain.get(pos).kind == "solid"
                                                       and terrain.get(pos).block_id == block)]):
        blockers.append({"code": error})
    inventory, inventory_reason = None, None
    try:
        inventory = parse_inventory(state)
    except PlanError as exc:
        inventory_reason = str(exc)
    materials = []
    for block in sorted(total):
        needed = remaining[block]
        available = inventory.get(block, 0) if inventory is not None else None
        shortage = max(0, needed - available) if available is not None else None
        materials.append({"block": block, "blueprint_total": total[block],
                          "already_correct": existing[block], "remaining_upper_bound": needed,
                          "observed_main_inventory": available, "shortage": shortage})
    if sum(remaining.values()):
        if inventory is None:
            blockers.append({"code": "inventory_evidence_unavailable", "detail": inventory_reason})
        elif any(item["shortage"] for item in materials):
            blockers.append({"code": "insufficient_materials"})

    # Support graph is geometric only. Every new block must connect to a known
    # full cube directly or through earlier proposed placements; floating cycles
    # never count as support. Deterministic bottom-up ordering favors the ground.
    pending = dict(candidates)
    planned, ordered = {}, []
    while pending:
        progress = False
        for pos in sorted(pending, key=lambda p: (p.y, p.z, p.x)):
            anchor = None
            for dx, dy, dz, face in ANCHORS:
                support = pos.offset(dx, dy, dz)
                if terrain.get(support).kind == "solid":
                    anchor = {"position": support.json(), "face": face, "source": "observed_full_cube"}
                    break
                if support in planned:
                    anchor = {"position": support.json(), "face": face, "source": "earlier_proposed_block",
                              "depends_on_index": planned[support]}
                    break
            if anchor is not None:
                index = len(ordered)
                planned[pos] = index
                ordered.append({"index": index, "position": pos.json(), "block": pending.pop(pos),
                                "anchor": anchor, "reach_and_line_of_sight": "unverified"})
                progress = True
        if not progress:
            blockers.append({"code": "unsupported_floating_cells", "positions": [
                pos.json() for pos in sorted(pending)]})
            break

    # All-or-nothing proposal: conflicts or uncertain evidence suppress every
    # placement, including otherwise-safe prefixes. No partial work is suggested.
    proposals = ordered if not blockers else []
    already_complete = sum(existing.values()) == len(desired)
    status = "blocked" if blockers else "already_complete" if already_complete else "provisional_plan"
    return {"format": "building-plan-v1", "status": status, "provisional": True,
            "executable": False, "execution_enabled": False, "blueprint": blueprint.spec(),
            "evidence": {"source": "offline_files", "live_freshness": "not_established",
                         "world_generation": terrain.world_generation, "scan_generation": terrain.scan_generation,
                         "dimension": terrain.dimension, "first_tick": terrain.first_tick,
                         "last_response_tick": terrain.last_response_tick,
                         "consistency": "live_pages_not_atomic"},
            "summary": {"blueprint_cells": len(desired), "already_correct": sum(existing.values()),
                        "known_air_candidates": len(candidates), "remaining_upper_bound": sum(remaining.values()),
                        "proposed_placements": len(proposals), "blocker_count": len(blockers)},
            "materials": materials, "assessments": assessments, "blockers": blockers,
            "proposed_placements": proposals,
            "required_before_any_real_placement": [
                "Implement and independently accept a bounded placement primitive",
                "Accept guarded navigation and turning, then prove reachable stand positions and line of sight",
                "Reobserve world, inventory, complete entity coverage and target/support cells at action time",
                "Verify item selection, placement properties, reach and exact hit face",
                "Stop and release on any conflict, state change, damage, hazard or unexpected result",
                "Observe the result after each single placement; never break, replace, craft or gather automatically",
            ]}
