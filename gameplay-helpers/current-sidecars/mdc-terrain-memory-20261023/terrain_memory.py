"""Bounded, historical terrain memory. No IO, movement, freshness grants or retries.

Accepts the existing TerrainReader schema 1/2 wire pages. Completion means spatial
coverage, not an atomic snapshot or current safety. Only complete scans commit.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import math
import re
from uuid import UUID

Pos = tuple[int, int, int]
MAX_CELLS = 18_513
MAX_COUNT = 2**53 - 1


class MemoryError(ValueError):
    """Invalid evidence; caller must not silently repair or retry actions."""


def require(condition, reason):
    if not condition:
        raise MemoryError(reason)


def integer(value, low=0, high=MAX_COUNT):
    require(type(value) is int and low <= value <= high, "invalid_integer")
    return value


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), "invalid_number")
    return value


def uuid(value):
    require(type(value) is str, "invalid_uuid")
    try:
        require(str(UUID(value)) == value, "invalid_uuid")
    except (ValueError, AttributeError):
        raise MemoryError("invalid_uuid") from None
    return value


def position(value):
    require(isinstance(value, (tuple, list)) and len(value) == 3, "invalid_position")
    return tuple(integer(n, -30_000_000, 30_000_000) for n in value)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Context:
    world_generation: str
    dimension: str

    def __post_init__(self):
        uuid(self.world_generation)
        require(type(self.dimension) is str and re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", self.dimension), "invalid_dimension")


def clock_stamp(value, context):
    """Return immutable domain/count; never compare counts across domains."""
    require(type(value) is dict and set(value) == {"contract", "clock_generation", "origin_nano", "context", "count"}, "invalid_clock")
    require(value["contract"] == "client-pre-tick-v1", "invalid_clock_contract")
    uuid(value["clock_generation"])
    nano = value["origin_nano"]
    require(type(nano) is str and re.fullmatch(r"0|-?[1-9][0-9]{0,18}", nano) and -(2**63) <= int(nano) < 2**63, "invalid_clock_origin")
    ctx = value["context"]
    require(type(ctx) is dict and set(ctx) == {"run_id", "process_id", "integrated_server_instance", "world_generation", "dimension", "player_uuid", "action_session"}, "invalid_clock_context")
    integer(ctx["process_id"], 1)
    for key in ("run_id", "integrated_server_instance", "dimension"):
        require(type(ctx[key]) is str and bool(ctx[key]), "invalid_clock_text")
    for key in ("world_generation", "player_uuid", "action_session"):
        uuid(ctx[key])
    require((ctx["world_generation"], ctx["dimension"]) == (context.world_generation, context.dimension), "clock_context_mismatch")
    domain = encoded({k: v for k, v in value.items() if k != "count"})
    return (domain, integer(value["count"]))


@dataclass(frozen=True)
class CellRecord:
    context: Context
    position: Pos
    raw_json: str
    scan_generation: str
    source_game_time: int
    response_game_time: int
    source_clock_json: str | None
    response_clock_json: str | None
    received_at: float
    order: int

    def facts(self):
        """Detached facts AS OBSERVED, never claims current chunk availability."""
        return json.loads(self.raw_json)

    @property
    def planning_state(self):
        return "historical" if self.facts()["status"] == "loaded" else "unknown"


@dataclass(frozen=True)
class Window:
    origin: Pos
    radius: int
    vertical: int
    scan_generation: str
    first_source: int
    last_source: int


@dataclass(frozen=True)
class HistoricalRoute:
    context: Context
    points: tuple[Pos, ...]
    evidence_id: str
    observed_at: float
    # No reverse-route inference: a walked descent need not be ascendable.
    revalidation_required: bool = True


class Scan:
    """One ordered page assembly; failed/incomplete input never changes memory."""
    def __init__(self, memory, received_at):
        self.memory, self.context, self.epoch = memory, memory.context, memory.epoch
        self.started_at = self.received_at = number(received_at)
        self.cells = []
        self.header = self.domain = self.window = None
        self.last_response = self.first_source = None
        self.complete = self.failed = self.committed = False

    def add(self, page, *, received_at):
        require(not self.failed and not self.committed, "scan_closed")
        try:
            self._add(page, number(received_at))
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            self.failed = True
            self.cells.clear()
            raise MemoryError(str(exc)) from None
        return self.complete

    def _add(self, page, received_at):
        require(self.epoch == self.memory.epoch and self.context == self.memory.context, "context_changed")
        require(not self.complete, "scan_already_complete")
        require(received_at >= self.received_at, "receive_clock_reversed")
        require(type(page) is dict and len(encoded(page).encode()) <= 256 * 1024, "invalid_page_size")
        require(Context(page["world_generation"], page["dimension"]) == self.context, "context_changed")
        schema = integer(page["terrain_schema_version"], 1, 2)
        require(page.get("consistency") == "live_pages" and page.get("order") == "x_then_z_then_y"
                and page.get("read_only") is True and page.get("loaded_chunks_only") is True, "invalid_page_profile")
        game_time = integer(page["game_time"])
        response_time = integer(page["response_game_time"])
        source_json = response_json = None
        if schema == 2:
            require(page.get("observation_clock_profile") == "read_only", "invalid_clock_profile")
            domain, source = clock_stamp(page["source_clock"], self.context)
            response_domain, response = clock_stamp(page["response_clock"], self.context)
            require(domain == response_domain and response >= source, "clock_domain_or_order")
            source_json, response_json = encoded(page["source_clock"]), encoded(page["response_clock"])
        else:
            require(not any(k in page for k in ("source_clock", "response_clock", "observation_clock_profile")), "mixed_clock_profile")
            domain, source, response = "schema1_game_time", game_time, response_time
            require(response >= source, "clock_order")
        require(self.domain is None or self.domain == domain, "mixed_clock_domain")
        require(self.last_response is None or source >= self.last_response, "page_clock_reversed")
        require(self.memory.domain is None or self.memory.domain == domain, "memory_clock_domain_changed_reset_required")
        generation = uuid(page["generation"])
        origin = position(tuple(page["origin"][k] for k in ("x", "y", "z")))
        radius, vertical = integer(page["radius"], 0, 16), integer(page["vertical"], 0, 8)
        width, total = 2 * radius + 1, integer(page["total_cells"], 1, MAX_CELLS)
        require(total == width * width * (2 * vertical + 1), "invalid_total")
        limit = 128
        capability = "capability_page_schema_version" in page
        if capability:
            require(type(page["capability_page_schema_version"]) is int and page["capability_page_schema_version"] == 1, "invalid_capability_schema")
            limit = integer(page["page_limit"], 1, 1024)
            require(type(page["payload_budget_exhausted"]) is bool, "invalid_payload_budget")
        header = (generation, origin, radius, vertical, total, schema, capability, limit)
        require(self.header is None or self.header == header, "mixed_scan")
        offset, returned = integer(page["offset"], 0, total), integer(page["returned"], 1, limit)
        end = integer(page["next_offset"], 1, total)
        require(offset == len(self.cells) and end == offset + returned, "noncontiguous_page")
        require(type(page["cells"]) is list and len(page["cells"]) == returned, "cell_count")
        require(type(page["complete"]) is bool and page["complete"] == (end == total), "invalid_completion")
        require(page.get("next_cursor") == (None if end == total else f"{generation}:{end}"), "invalid_cursor")
        require(type(page["budget_exhausted"]) is bool, "invalid_budget")
        integer(page["read_elapsed_micros"])
        records, unknown = [], 0
        for index, cell in enumerate(page["cells"], offset):
            expected = (origin[0] - radius + index % width, origin[1] - vertical + index // (width * width), origin[2] - radius + (index // width) % width)
            require(type(cell) is dict and position(tuple(cell[k] for k in ("x", "y", "z"))) == expected, "cell_order")
            status = cell.get("status")
            require(status in ("loaded", "unloaded", "out_of_world", "read_failed"), "invalid_cell_status")
            require(cell.get("known") is (status == "loaded"), "invalid_known")
            if status == "loaded":
                # ID-only compact observations are NOT full TerrainReader evidence.
                require(all(k in cell for k in ("id", "properties", "fluid", "hazards", "collision_known", "air",
                                               "id_truncated", "properties_truncated", "fluid_truncated", "fluid_source", "hazards_exhaustive")), "incomplete_cell_facts")
                require(type(cell["id"]) is str and type(cell["fluid"]) is str and type(cell["properties"]) is dict
                        and type(cell["hazards"]) is list and all(type(cell[k]) is bool for k in
                            ("collision_known", "air", "id_truncated", "properties_truncated", "fluid_truncated", "fluid_source", "hazards_exhaustive")), "invalid_cell_facts")
                if cell["collision_known"]:
                    require(type(cell.get("collision_empty")) is bool and type(cell.get("full_top_support")) is bool,
                            "incomplete_collision_facts")
            else:
                unknown += 1
            records.append(CellRecord(self.context, expected, encoded(cell), generation, game_time, response_time,
                                      source_json, response_json, received_at, source))
        require(integer(page["unknown_cells"], 0, returned) == unknown, "unknown_count")
        self.header, self.domain = header, domain
        self.cells.extend(records)
        self.first_source = source if self.first_source is None else self.first_source
        self.last_response, self.received_at, self.complete = response, received_at, end == total
        self.window = Window(origin, radius, vertical, generation, self.first_source, source)

    def commit(self):
        require(not self.failed and not self.committed and self.complete, "incomplete_or_closed_scan")
        result = self.memory._commit(self)
        self.committed = True
        self.cells.clear()
        return result


class TerrainMemory:
    def __init__(self, context, *, max_cells=65_536, max_routes=32):
        self.max_cells = integer(max_cells, MAX_CELLS, 1_000_000)
        self.max_routes = integer(max_routes, 1, 1024)
        self.epoch = 0
        self.reset(context)

    def reset(self, context):
        """Caller binds a newly observed context; also explicit clock-domain reset."""
        require(isinstance(context, Context), "invalid_context")
        self.context, self.domain = context, None
        self.epoch += 1
        self.cells, self.routes = OrderedDict(), OrderedDict()
        self.window = None

    def begin_scan(self, *, received_at):
        return Scan(self, received_at)

    def _commit(self, scan):
        require(scan.epoch == self.epoch and scan.context == self.context, "context_changed")
        require(self.domain is None or self.domain == scan.domain, "memory_clock_domain_changed_reset_required")
        # Same-tick contradictory observations have no safe ordering: reject all.
        for cell in scan.cells:
            old = self.cells.get(cell.position)
            require(old is None or old.order != cell.order or old.raw_json == cell.raw_json, "same_source_conflict")
        changed = ignored = 0
        for cell in scan.cells:
            old = self.cells.get(cell.position)
            if old is not None and old.order >= cell.order:
                ignored += 1
                continue
            self.cells[cell.position] = cell
            self.cells.move_to_end(cell.position)
            changed += 1
        while len(self.cells) > self.max_cells:
            self.cells.popitem(last=False)
        self.domain = scan.domain
        if self.window is None or scan.window.last_source >= self.window.last_source:
            self.window = scan.window
        return {"merged": changed, "ignored_older_or_same": ignored, "historical_only": True,
                "execution_authority": False, "atomic_snapshot": False}

    def lookup(self, pos):
        return self.cells.get(position(pos))

    def remember_walked(self, points, *, context, evidence_id, observed_at):
        """Caller supplies ACTUALLY observed trace and terminal evidence reference."""
        require(context == self.context, "route_context_changed")
        require(type(evidence_id) is str and 0 < len(evidence_id) <= 256, "invalid_evidence_id")
        require(isinstance(points, (list, tuple)) and 2 <= len(points) <= 512, "invalid_trace")
        trace = tuple(position(p) for p in points)
        require(all(0 < max(abs(x-y) for x, y in zip(a, b)) <= 1 for a, b in zip(trace, trace[1:])), "nonadjacent_trace")
        route = HistoricalRoute(self.context, trace, evidence_id, number(observed_at))
        old = self.routes.get(evidence_id)
        require(old is None or old == route, "route_evidence_conflict")
        self.routes[evidence_id] = route
        while len(self.routes) > self.max_routes:
            self.routes.popitem(last=False)

    def candidate_routes(self, start, goal):
        """Exact forward historical routes only; not a new path/movement controller."""
        start, goal = position(start), position(goal)
        return tuple(route for route in self.routes.values() if route.points[0] == start and route.points[-1] == goal)

    def prefetch_advice(self, pos, *, speed=0.0, scan_seconds=1.0, stopping_margin=2.0, minimum_margin=6):
        pos = position(pos)
        require(all(number(n) >= 0 for n in (speed, scan_seconds, stopping_margin)), "negative_prefetch_parameter")
        margin = max(integer(minimum_margin, 0, 1024), math.ceil(speed * scan_seconds + stopping_margin))
        if self.window is None:
            return {"needed": True, "reason": "no_complete_window", "execution_authority": False}
        w = self.window
        horizontal = min(w.radius - abs(pos[0]-w.origin[0]), w.radius - abs(pos[2]-w.origin[2]))
        vertical = w.vertical - abs(pos[1]-w.origin[1])
        needed = horizontal <= margin or vertical <= 1
        widths = (2*w.radius+1, 2*w.vertical+1, 2*w.radius+1)
        overlap = math.prod(max(0, n-abs(a-b)) for n, a, b in zip(widths, pos, w.origin)) / math.prod(widths)
        return {"needed": needed, "reason": "edge_or_outside" if needed else "inside_window",
                "margin_blocks": margin, "suggested_center": pos, "radius": w.radius, "vertical": w.vertical,
                "overlap_fraction": overlap, "read_mode": "existing_api_player_centered_full_window",
                "execution_authority": False}

    def summary(self):
        return {"world_generation": self.context.world_generation, "dimension": self.context.dimension,
                "historical_cells": len(self.cells), "historical_routes": len(self.routes),
                "execution_authority": False, "current_loaded_status": "unknown_without_fresh_observation"}
