"""Strict terrain schema 1 ingestion. No networking or game mutation."""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


class TerrainError(ValueError):
    pass


class StaleTerrainError(TerrainError):
    """Valid observations have aged out; a caller may start a bounded new scan."""


class TerrainPageError(TerrainError):
    """Keep the legacy public error and an explicit, sanitized rejection cause."""
    def __init__(self, cause):
        super().__init__('invalid_or_stale_terrain_page')
        self.detail = str(cause) if isinstance(cause, TerrainError) else 'malformed_terrain_page'
        self.refreshable = isinstance(cause, StaleTerrainError)


def integer(value, low=None, high=None):
    if type(value) is not int or (low is not None and value < low) or (high is not None and value > high):
        raise TerrainError('invalid_integer')
    return value


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise TerrainError('invalid_number')
    return float(value)


def uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise TerrainError('invalid_uuid') from None
    return value


def protocol(data):
    if (not isinstance(data, dict) or data.get('ok') is not True
            or data.get('protocol') != 'mineclient-bridge'
            or type(data.get('schema_version')) is not int or data['schema_version'] != 2):
        raise TerrainError('unsupported_protocol')


@dataclass(frozen=True, order=True)
class Block:
    x: int
    y: int
    z: int

    def __post_init__(self):
        for value in (self.x, self.y, self.z):
            integer(value, -30_000_000, 30_000_000)

    def offset(self, x=0, y=0, z=0):
        return Block(self.x + x, self.y + y, self.z + z)

    @classmethod
    def parse(cls, obj):
        if not isinstance(obj, dict):
            raise TerrainError('invalid_coordinate')
        return cls(*(integer(obj[k]) for k in ('x', 'y', 'z')))


@dataclass(frozen=True)
class WorldStamp:
    generation: str
    dimension: str
    tick: int

    def __post_init__(self):
        uuid(self.generation)
        if self.dimension != 'minecraft:overworld':
            raise TerrainError('unsupported_dimension')
        integer(self.tick, 0)

    def same_world(self, other):
        return (self.generation, self.dimension) == (other.generation, other.dimension)

    @classmethod
    def parse(cls, world):
        return cls(world['world_generation'], world['dimension'], world['game_time'])


# Match the companion combat controller's conservative vanilla floor allowlist.
SAFE_FLOORS = frozenset('minecraft:' + item for item in (
    'stone', 'dirt', 'grass_block', 'cobblestone', 'deepslate', 'cobbled_deepslate',
    'andesite', 'diorite', 'granite', 'sandstone', 'smooth_stone', 'bricks',
    'stone_bricks', 'oak_planks', 'spruce_planks', 'birch_planks', 'jungle_planks',
    'acacia_planks', 'dark_oak_planks', 'mangrove_planks', 'cherry_planks',
))
AIR_BLOCKS = frozenset({'minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'})


@dataclass(frozen=True)
class Cell:
    position: Block
    clear: bool = False
    support: bool = False

    @classmethod
    def parse(cls, data):
        pos = Block.parse(data)
        # Unloaded, failed, unknown and malformed cell facts are blocked, never air.
        certain = (data.get('status') == 'loaded' and data.get('known') is True
                   and data.get('collision_known') is True
                   and data.get('id_truncated') is False
                   and data.get('fluid_truncated') is False
                   and data.get('properties_truncated') is False
                   and isinstance(data.get('properties'), dict)
                   and data.get('fluid') == 'minecraft:empty'
                   and data.get('fluid_source') is False
                   and data.get('hazards') == []
                   and data.get('hazards_exhaustive') is False)
        if not certain:
            return cls(pos)
        block_id = data.get('id')
        clear = (block_id in AIR_BLOCKS and data.get('air') is True
                 and data.get('collision_empty') is True
                 and data.get('full_top_support') is False)
        bounds = data.get('collision_bounds')
        full_cube = (isinstance(bounds, list) and len(bounds) == 6
                     and all(type(v) in (int, float) and math.isfinite(v) for v in bounds)
                     and bounds == [0, 0, 0, 1, 1, 1])
        support = (block_id in SAFE_FLOORS and data.get('air') is False
                   and data.get('full_top_support') is True
                   and data.get('collision_empty') is False and full_cube)
        return cls(pos, clear, support)


@dataclass(frozen=True)
class TerrainGrid:
    world: WorldStamp
    scan_generation: str
    origin: Block
    radius: int
    vertical: int
    first_tick: int
    last_tick: int
    received_at: float
    cells: Mapping[Block, Cell]
    complete: bool

    def __post_init__(self):
        # Copy to prevent caller mutation after a plan has been validated.
        object.__setattr__(self, 'cells', MappingProxyType(dict(self.cells)))

    def contains(self, pos):
        return (abs(pos.x - self.origin.x) <= self.radius
                and abs(pos.z - self.origin.z) <= self.radius
                and abs(pos.y - self.origin.y) <= self.vertical)

    def clear(self, pos):
        cell = self.cells.get(pos)
        return bool(cell and cell.clear)

    def support(self, pos):
        cell = self.cells.get(pos)
        return bool(cell and cell.support)

    def standable(self, feet):
        return (self.support(feet.offset(y=-1)) and self.clear(feet)
                and self.clear(feet.offset(y=1)))

    def require_fresh(self, current, now, max_age_ticks=40, max_wall_age=3.0):
        number(now)
        if not self.complete:
            raise TerrainError('incomplete_scan')
        if not self.world.same_world(current):
            raise TerrainError('world_generation_changed')
        if not self.first_tick <= self.last_tick <= current.tick:
            raise TerrainError('terrain_from_future')
        if current.tick - self.first_tick > max_age_ticks:
            raise StaleTerrainError('stale_terrain_ticks')
        if now < self.received_at:
            raise TerrainError('terrain_clock_reversed')
        if now - self.received_at > max_wall_age:
            raise StaleTerrainError('stale_terrain_clock')


class TerrainAssembler:
    """Bounded ordered page assembly; a mismatch poisons the entire scan.

    Pass pages in request order. Cursor replay is deliberately not accepted here;
    a transport can retry the same continuation request but must feed its result once.
    Pages are live observations, not an atomic snapshot. Complete only means coverage.
    """
    def __init__(self, expected_world: WorldStamp, now: float, max_pages=160,
                 max_scan_ticks=40, max_scan_seconds=3.0):
        self.world = expected_world
        self.started_at = number(now)
        self.max_pages = integer(max_pages, 1, 18_513)
        self.max_scan_ticks = integer(max_scan_ticks, 0, 200)
        self.max_scan_seconds = number(max_scan_seconds)
        if not 0 < self.max_scan_seconds <= 10:
            raise TerrainError('invalid_scan_duration')
        self.pages = 0
        self.cells = {}
        self.header = None
        self.first_tick = None
        self.last_tick = None
        self.next_cursor = None
        self.complete = False
        self.failed = False

    def add(self, page, now):
        if self.failed:
            raise TerrainError('scan_invalidated')
        try:
            self._add(page, number(now))
        except (TerrainError, KeyError, TypeError, ValueError) as exc:
            self.failed = True
            self.cells.clear()
            raise TerrainPageError(exc) from None

    def _add(self, page, now):
        protocol(page)
        if self.complete:
            raise TerrainError('scan_already_completed')
        if self.pages >= self.max_pages:
            raise TerrainError('scan_page_budget')
        if now < self.started_at:
            raise TerrainError('terrain_clock_reversed')
        if (type(page.get('terrain_schema_version')) is not int or page['terrain_schema_version'] != 1
                or page.get('consistency') != 'live_pages' or page.get('order') != 'x_then_z_then_y'
                or page.get('read_only') is not True or page.get('loaded_chunks_only') is not True):
            raise TerrainError('unsupported_terrain_schema')
        stamp = WorldStamp(page['world_generation'], page['dimension'], page['game_time'])
        if not self.world.same_world(stamp):
            raise TerrainError('world_generation_changed')
        tick = stamp.tick
        response_tick = integer(page['response_game_time'], tick)
        generation = uuid(page['generation'])
        origin = Block.parse(page['origin'])
        radius = integer(page['radius'], 0, 16)
        vertical = integer(page['vertical'], 0, 8)
        width = 2 * radius + 1
        total = integer(page['total_cells'], 1, 18_513)
        header = (generation, origin, radius, vertical, total)
        if total != width * width * (2 * vertical + 1):
            raise TerrainError('invalid_total')
        if self.header is not None and self.header != header:
            raise TerrainError('mixed_scan')
        self.header = header
        offset = integer(page['offset'], 0, total)
        returned = integer(page['returned'], 1, 128)
        next_offset = integer(page['next_offset'], 1, total)
        if offset != len(self.cells) or next_offset != offset + returned:
            raise TerrainError('noncontiguous_page')
        cells = page['cells']
        if not isinstance(cells, list) or len(cells) != returned:
            raise TerrainError('invalid_cell_count')
        complete = page.get('complete')
        if type(complete) is not bool or complete != (next_offset == total):
            raise TerrainError('invalid_completion')
        cursor = page.get('next_cursor')
        if (complete and cursor is not None) or (not complete and cursor != f'{generation}:{next_offset}'):
            raise TerrainError('invalid_cursor')
        if type(page.get('budget_exhausted')) is not bool:
            raise TerrainError('invalid_budget_flag')
        integer(page['read_elapsed_micros'], 0)
        unknown = 0
        for i, data in enumerate(cells, offset):
            expected = Block(origin.x - radius + i % width,
                             origin.y - vertical + i // (width * width),
                             origin.z - radius + (i // width) % width)
            cell = Cell.parse(data)
            if cell.position != expected:
                raise TerrainError('cell_order_mismatch')
            if data.get('status') not in ('loaded', 'unloaded', 'out_of_world', 'read_failed'):
                raise TerrainError('invalid_cell_status')
            if data['status'] == 'loaded' and data.get('known') is not True:
                raise TerrainError('invalid_known_flag')
            if data['status'] != 'loaded':
                if data.get('known') is not False:
                    raise TerrainError('invalid_unknown_flag')
                unknown += 1
            self.cells[expected] = cell
        if integer(page['unknown_cells'], 0, returned) != unknown:
            raise TerrainError('invalid_unknown_count')
        if self.first_tick is None:
            self.first_tick = tick
        if self.last_tick is not None and tick < self.last_tick:
            raise TerrainError('terrain_page_tick_reversed')
        # Validate schema, exact coverage, world and ordering before classifying
        # expiry. A malformed page with an old timestamp is never retryable.
        if tick < self.world.tick or response_tick - tick > self.max_scan_ticks:
            raise StaleTerrainError('stale_terrain_page_ticks')
        if response_tick - self.first_tick > self.max_scan_ticks:
            raise StaleTerrainError('stale_terrain_scan_ticks')
        if now - self.started_at > self.max_scan_seconds:
            raise StaleTerrainError('stale_terrain_clock')
        self.last_tick = tick
        self.next_cursor = cursor
        self.complete = complete
        self.pages += 1

    def finish(self, current: WorldStamp, now: float):
        if self.failed or not self.complete or self.header is None:
            raise TerrainError('incomplete_or_invalidated_scan')
        generation, origin, radius, vertical, _ = self.header
        grid = TerrainGrid(self.world, generation, origin, radius, vertical,
                           self.first_tick, self.last_tick, self.started_at, self.cells, True)
        grid.require_fresh(current, now, self.max_scan_ticks, self.max_scan_seconds)
        return grid
