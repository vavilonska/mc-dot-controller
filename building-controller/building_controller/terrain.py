"""Offline protocol-2 / terrain-1 page validation, compatible with bridge captures.

Complete means coverage, not an atomic or fresh snapshot. No wall-clock freshness
is fabricated for archived files. Every output remains non-executable.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from .model import AIR_IDS, SUPPORT_IDS, PlanError, Pos, integer, number


def uuid(value):
    if type(value) is not str:
        raise PlanError("invalid_generation")
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except ValueError:
        raise PlanError("invalid_generation") from None
    return value


def protocol(body):
    if (not isinstance(body, dict) or body.get("ok") is not True
            or body.get("protocol") != "mineclient-bridge"
            or type(body.get("schema_version")) is not int or body["schema_version"] != 2):
        raise PlanError("unsupported_protocol")


def unwrap(value):
    if isinstance(value, dict) and "body" in value:
        if type(value.get("status")) is not int or value["status"] != 200:
            raise PlanError("capture_http_response_not_successful")
        return value["body"]
    return value


@dataclass(frozen=True)
class Cell:
    position: Pos
    block_id: str | None
    kind: str  # clear, solid, unknown, fluid, hazard, unsupported
    reason: str

    @classmethod
    def parse(cls, raw):
        pos = Pos.parse(raw)
        block_id = raw.get("id") if type(raw.get("id")) is str else None
        if not -64 <= pos.y <= 319:
            return cls(pos, block_id, "unknown", "outside_supported_world_height")
        if raw.get("status") != "loaded" or raw.get("known") is not True:
            return cls(pos, block_id, "unknown", "terrain_not_known_loaded")
        if any(raw.get(key) is not False for key in
               ("id_truncated", "fluid_truncated", "properties_truncated")):
            return cls(pos, block_id, "unknown", "truncated_or_missing_facts")
        if raw.get("fluid") != "minecraft:empty" or raw.get("fluid_source") is not False:
            return cls(pos, block_id, "fluid", "fluid_or_unknown_fluid")
        if raw.get("hazards") != []:
            return cls(pos, block_id, "hazard", "hazard_or_unknown_hazards")
        # Hazard tags are explicitly non-exhaustive in this schema. An allowlist
        # plus exact collision evidence is still required below.
        if raw.get("hazards_exhaustive") is not False or raw.get("collision_known") is not True:
            return cls(pos, block_id, "unknown", "unsupported_hazard_or_collision_contract")
        props = raw.get("properties")
        valid_props = props == {} or (block_id == "minecraft:grass_block"
                                      and props in ({"snowy": "false"}, {"snowy": "true"}))
        if not valid_props:
            return cls(pos, block_id, "unsupported", "unrecognized_block_properties")
        if (block_id in AIR_IDS and raw.get("air") is True
                and raw.get("collision_empty") is True and raw.get("full_top_support") is False
                and "collision_bounds" not in raw):
            return cls(pos, block_id, "clear", "known_air")
        bounds = raw.get("collision_bounds")
        full_cube = (isinstance(bounds, list) and len(bounds) == 6
                     and all(type(v) in (int, float) for v in bounds)
                     and bounds == [0, 0, 0, 1, 1, 1])
        if (block_id in SUPPORT_IDS and full_cube and raw.get("air") is False
                and raw.get("collision_empty") is False and raw.get("full_top_support") is True):
            return cls(pos, block_id, "solid", "known_allowlisted_full_cube")
        return cls(pos, block_id, "unsupported", "unrecognized_block_or_collision")


@dataclass(frozen=True)
class Terrain:
    cells: object
    world_generation: str
    scan_generation: str
    dimension: str
    first_tick: int
    last_response_tick: int
    origin: Pos
    radius: int
    vertical: int

    def get(self, pos):
        return self.cells.get(pos, Cell(pos, None, "unknown", "outside_observed_scan"))

    @classmethod
    def parse(cls, values):
        """Accept one raw page or an ordered list of raw/HTTP-wrapped pages."""
        if isinstance(values, dict):
            values = [values]
        if not isinstance(values, list) or not 1 <= len(values) <= 160:
            raise PlanError("invalid_page_budget")
        cells, header, first_tick, last_tick, last_response = {}, None, None, None, None
        complete = False
        try:
            for value in values:
                page = unwrap(value)
                protocol(page)
                if complete:
                    raise PlanError("page_after_completed_scan")
                if (type(page.get("terrain_schema_version")) is not int or page["terrain_schema_version"] != 1
                        or page.get("consistency") != "live_pages" or page.get("order") != "x_then_z_then_y"
                        or page.get("read_only") is not True or page.get("loaded_chunks_only") is not True):
                    raise PlanError("unsupported_terrain_schema")
                world_id, scan_id = uuid(page["world_generation"]), uuid(page["generation"])
                if page["dimension"] != "minecraft:overworld":
                    raise PlanError("unsupported_dimension")
                origin = Pos.parse(page["origin"])
                radius, vertical = integer(page["radius"], 0, 16), integer(page["vertical"], 0, 8)
                total = integer(page["total_cells"], 1, 18513)
                width = radius * 2 + 1
                if total != width * width * (vertical * 2 + 1):
                    raise PlanError("invalid_scan_volume")
                new_header = (world_id, scan_id, page["dimension"], origin, radius, vertical, total)
                if header is not None and new_header != header:
                    raise PlanError("mixed_scan_headers")
                header = new_header
                tick = integer(page["game_time"], 0, 2**63 - 1)
                response = integer(page["response_game_time"], tick, 2**63 - 1)
                if first_tick is None:
                    first_tick = tick
                if (response - first_tick > 40 or (last_tick is not None and tick < last_tick)
                        or (last_response is not None and response < last_response)):
                    raise PlanError("incoherent_scan_ticks")
                last_tick, last_response = tick, response
                offset = integer(page["offset"], 0, total)
                returned = integer(page["returned"], 1, 128)
                end = integer(page["next_offset"], 1, total)
                if offset != len(cells) or end != offset + returned:
                    raise PlanError("noncontiguous_pages")
                raw_cells = page["cells"]
                if not isinstance(raw_cells, list) or len(raw_cells) != returned:
                    raise PlanError("invalid_cell_count")
                if type(page.get("complete")) is not bool or page["complete"] != (end == total):
                    raise PlanError("invalid_completion")
                complete = page["complete"]
                cursor = page.get("next_cursor")
                if (complete and cursor is not None) or (not complete and cursor != f"{scan_id}:{end}"):
                    raise PlanError("invalid_cursor")
                if type(page.get("budget_exhausted")) is not bool:
                    raise PlanError("invalid_budget_flag")
                integer(page["read_elapsed_micros"], 0, 2**63 - 1)
                unknown = 0
                for i, raw in enumerate(raw_cells, offset):
                    expected = Pos(origin.x - radius + i % width,
                                   origin.y - vertical + i // (width * width),
                                   origin.z - radius + i // width % width)
                    cell = Cell.parse(raw)
                    if cell.position != expected:
                        raise PlanError("cell_order_mismatch")
                    if raw.get("status") not in ("loaded", "unloaded", "out_of_world", "read_failed"):
                        raise PlanError("invalid_cell_status")
                    if raw.get("known") is not (raw["status"] == "loaded"):
                        raise PlanError("invalid_known_flag")
                    unknown += raw["status"] != "loaded"
                    cells[expected] = cell
                if integer(page["unknown_cells"], 0, returned) != unknown:
                    raise PlanError("invalid_unknown_count")
            if not complete:
                raise PlanError("incomplete_scan")
        except (KeyError, TypeError, AttributeError):
            raise PlanError("malformed_terrain_page") from None
        return cls(MappingProxyType(cells), header[0], header[1], header[2], first_tick,
                   last_response, header[3], header[4], header[5])


def parse_inventory(state):
    """Only complete main inventory evidence; offhand deliberately not credited."""
    try:
        protocol(state)
        player = state["player"]
        if (player.get("inventory_truncated") is not False
                or integer(player.get("inventory_total"), 36, 36) != 36):
            raise PlanError("inventory_incomplete")
        entries = player["inventory"]
        if not isinstance(entries, list) or len(entries) != 36:
            raise PlanError("inventory_incomplete")
        slots, counts = set(), {}
        for entry in entries:
            slot = integer(entry["slot"], 0, 35)
            if slot in slots:
                raise PlanError("inventory_duplicate_slot")
            slots.add(slot)
            count = integer(entry["count"], 0, 2**31 - 1)
            block_id = entry["id"]
            if type(entry.get("empty")) is not bool or type(block_id) is not str:
                raise PlanError("inventory_malformed_entry")
            if entry["empty"]:
                if count != 0 or block_id != "":
                    raise PlanError("inventory_inconsistent_empty")
            elif not block_id or count == 0:
                raise PlanError("inventory_inconsistent_stack")
            else:
                counts[block_id] = counts.get(block_id, 0) + count
        return counts
    except (KeyError, TypeError, AttributeError):
        raise PlanError("inventory_malformed") from None


def state_blockers(state, terrain, targets):
    """Offline evidence gates, never a replacement for fresh action-time reads."""
    if not targets:
        return []
    errors = []
    try:
        protocol(state)
        world, player = state["world"], state["player"]
        if (world["world_generation"] != terrain.world_generation or world["dimension"] != terrain.dimension
                or player["dimension"] != terrain.dimension):
            errors.append("world_or_dimension_mismatch")
        tick = integer(world["game_time"], 0, 2**63 - 1)
        if not terrain.last_response_tick <= tick <= terrain.first_tick + 40:
            errors.append("state_terrain_ticks_incoherent")
        if player.get("gamemode") != "survival":
            errors.append("survival_state_required")
        position = tuple(number(player[k]) for k in ("x", "y", "z"))
        if any(abs(value) > 30_000_000 for value in position):
            raise PlanError("player_position_out_of_bounds")
        nearby = state["nearby"]
        radius = number(nearby["radius"])
        if not 0 <= radius <= 128:
            raise PlanError("invalid_entity_scan_radius")
        total, returned = integer(nearby["total"], 0, 100000), integer(nearby["returned"], 0, 100000)
        if (nearby.get("truncated") is not False or total != 0 or returned != 0
                or nearby.get("entities") != []):
            errors.append("entities_present_or_scan_incomplete")
        import math
        required_radius = max(math.dist(position, (p.x + 0.5, p.y + 0.5, p.z + 0.5)) + 2
                              for p in targets)
        if radius < required_radius:
            errors.append("entity_scan_does_not_cover_blueprint")
        px, py, pz = position
        if any(p.x < px + .35 and p.x + 1 > px - .35 and p.z < pz + .35
               and p.z + 1 > pz - .35 and p.y < py + 2 and p.y + 1 > py for p in targets):
            errors.append("player_overlaps_blueprint")
    except (KeyError, TypeError, AttributeError, PlanError):
        errors.append("missing_or_invalid_state_evidence")
    return errors
