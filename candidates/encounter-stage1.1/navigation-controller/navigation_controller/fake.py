"""Deterministic offline world and movement model; not Minecraft physics."""
from copy import deepcopy
from dataclasses import replace
import math
from .observation import Observation, Position
from .terrain import Block, TerrainAssembler, WorldStamp

WORLD_ID = '00000000-0000-4000-8000-000000000001'
SCAN_ID = '00000000-0000-4000-8000-000000000002'
PLAYER_ID = '00000000-0000-4000-8000-000000000003'


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


def cell(position, kind='air', **changes):
    result = dict(x=position.x, y=position.y, z=position.z, status='loaded', known=True,
                  id='minecraft:' + kind, air=kind == 'air', id_truncated=False,
                  properties={}, properties_truncated=False, fluid='minecraft:empty',
                  fluid_source=False, fluid_truncated=False, hazards=[], hazards_exhaustive=False,
                  collision_known=True, collision_empty=kind == 'air', full_top_support=kind != 'air')
    if kind != 'air':
        result['collision_bounds'] = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    result.update(changes)
    return result


class FakeWorld:
    def __init__(self, floor_y=63):
        self.floor_y = floor_y
        self.overrides = {}
        self.generation = WORLD_ID

    def get(self, pos):
        if pos in self.overrides:
            return deepcopy(self.overrides[pos])
        return cell(pos, 'stone' if pos.y <= self.floor_y else 'air')

    def set(self, pos, kind='stone', **changes):
        self.overrides[pos] = cell(pos, kind, **changes)

    def unknown(self, pos, status='unloaded'):
        self.overrides[pos] = dict(x=pos.x, y=pos.y, z=pos.z, status=status, known=False)

    def pages(self, origin=Block(0, 64, 0), radius=4, vertical=2,
              limit=128, tick=100, tick_per_page=0, scan_id=SCAN_ID):
        positions = [Block(x, y, z) for y in range(origin.y-vertical, origin.y+vertical+1)
                     for z in range(origin.z-radius, origin.z+radius+1)
                     for x in range(origin.x-radius, origin.x+radius+1)]
        pages = []
        for offset in range(0, len(positions), limit):
            cells = [self.get(p) for p in positions[offset:offset+limit]]
            end = offset + len(cells)
            page_tick = tick + len(pages) * tick_per_page
            page = dict(ok=True, protocol='mineclient-bridge', schema_version=2,
                        terrain_schema_version=1, world_generation=self.generation,
                        dimension='minecraft:overworld', generation=scan_id,
                        consistency='live_pages', game_time=page_tick, response_game_time=page_tick,
                        origin=dict(x=origin.x, y=origin.y, z=origin.z), radius=radius, vertical=vertical,
                        order='x_then_z_then_y', offset=offset, next_offset=end,
                        total_cells=len(positions), returned=len(cells), complete=end == len(positions),
                        read_only=True, loaded_chunks_only=True, budget_exhausted=False,
                        read_elapsed_micros=100, retry_after_ms=50,
                        unknown_cells=sum(c['status'] != 'loaded' for c in cells), cells=cells)
            if end < len(positions):
                page['next_cursor'] = f'{scan_id}:{end}'
            pages.append(page)
        return pages

    def grid(self, now=100.0, tick=100, **kwargs):
        stamp = WorldStamp(self.generation, 'minecraft:overworld', tick)
        assembler = TerrainAssembler(stamp, now)
        for page in self.pages(tick=tick, **kwargs):
            assembler.add(page, now)
        return assembler.finish(stamp, now)


class FakeAdapter:
    simulation_only = True

    def __init__(self, clock, world=None):
        self.clock = clock
        self.world = world or FakeWorld()
        self.position = Position(0.5, 64, 0.5)
        self.yaw = 0.0
        self.calls = []
        self.pulses = []
        self.releases = 0
        self.observations = 0
        self.observation_hook = None
        self.fail_pulse = False
        self.fail_release = False
        self.stalled = False
        self.held = False
        self._last = None

    def observe(self):
        self.calls.append('observe')
        self.observations += 1
        tick = 100 + int(round((self.clock.monotonic() - 100) * 20))
        grid = self.world.grid(self.clock.monotonic(), tick, origin=self.position.block(), radius=2)
        observation = Observation(WorldStamp(self.world.generation, 'minecraft:overworld', tick),
                                  'offline-simulation', 1, PLAYER_ID, self.position, self.yaw,
                                  grid, self.clock.monotonic(), neutral_inputs=not self.held)
        if self.observation_hook:
            observation = self.observation_hook(observation, self.observations)
        self._last = observation
        return observation

    def _consume(self, expected):
        if expected is not self._last:
            raise ValueError('stale_fake_action_context')
        self._last = None

    def look(self, yaw, expected):
        self._consume(expected)
        self.calls.append('look')
        self.yaw = yaw

    def pulse_forward(self, duration_ms, expected):
        self._consume(expected)
        if type(duration_ms) is not int or not 1 <= duration_ms <= 100:
            raise ValueError('unbounded_fake_pulse')
        self.calls.append('pulse')
        self.pulses.append(duration_ms)
        self.held = True
        if self.fail_pulse:
            raise RuntimeError('ambiguous fake pulse')
        if not self.stalled:
            distance = 4.0 * duration_ms / 1000
            angle = math.radians(self.yaw)
            self.position = Position(self.position.x - math.sin(angle) * distance,
                                     self.position.y, self.position.z + math.cos(angle) * distance)
        self.clock.sleep(duration_ms / 1000)
        self.held = False  # Independent fake pulse expiry, in addition to cleanup.

    def release_all(self):
        self.calls.append('release')
        self.releases += 1
        if self.fail_release:
            return False
        self.held = False
        return True
