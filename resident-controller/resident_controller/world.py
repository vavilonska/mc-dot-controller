"""One small loaded-terrain cache and an adapter to the existing A* planner."""
from __future__ import annotations

import math
from pathlib import Path
import sys
import time

# Reuse the source beside this controller; do not fork Minecraft physics/path planning.
ROOT = Path(__file__).resolve().parents[2]
NAVIGATION = next((ROOT / name for name in ('navigation-controller', 'minecraft-navigation-controller')
                   if (ROOT / name / 'navigation_controller' / 'planner.py').is_file()), None)
if NAVIGATION is None:
    raise ImportError('Keep the existing navigation-controller source beside the resident controller')
if str(NAVIGATION) not in sys.path:
    sys.path.insert(0, str(NAVIGATION))
from navigation_controller.planner import plan
from navigation_controller.terrain import Block, TerrainAssembler, WorldStamp


class WorldCache:
    def __init__(self):
        self.state = None
        self.grid = None
        self.cells = {}
        self.received_at = 0.0
        self.terrain_received_at = 0.0

    def observe(self, bridge):
        state = bridge.request('GET', '/control/state?radius=8')
        old_world = self.state.get('world', {}) if self.state else {}
        if old_world.get('world_generation') != state['world'].get('world_generation'):
            self.grid, self.cells = None, {}
            self.terrain_received_at = 0.0
        self.state, self.received_at = state, time.monotonic()
        return state

    def scan(self, bridge, radius=4, vertical=2):
        if type(radius) is not int or not 1 <= radius <= 8 or type(vertical) is not int or not 2 <= vertical <= 4:
            raise ValueError('terrain_bounds_radius_1_to_8_vertical_2_to_4')
        first = self.observe(bridge)
        assembler = TerrainAssembler(WorldStamp.parse(first['world']), time.monotonic(),
                                     max_pages=32, max_scan_seconds=3.0)
        path = f'/control/terrain?radius={radius}&vertical={vertical}&limit=128'
        cells = {}
        while True:
            page = bridge.request('GET', path)
            assembler.add(page, time.monotonic())
            for cell in page['cells']:
                if cell.get('status') == 'loaded':
                    cells[(cell['x'], cell['y'], cell['z'])] = cell
            if assembler.complete:
                break
            time.sleep(0.05)
            path = '/control/terrain?cursor=' + assembler.next_cursor
        last = self.observe(bridge)
        self.grid = assembler.finish(WorldStamp.parse(last['world']), time.monotonic())
        self.cells = cells  # At most 2,601 local cells; no inventory or entity simulation.
        self.terrain_received_at = time.monotonic()
        return {'origin': vars(self.grid.origin), 'radius': radius, 'vertical': vertical,
                'world_generation': self.grid.world.generation,
                'cells': list(cells.values()), 'complete': self.grid.complete}

    def route(self, bridge, target, radius=4, vertical=2):
        self.scan(bridge, radius, vertical)
        player = self.state['player']
        start = Block(*(math.floor(player[k]) for k in ('x', 'y', 'z')))
        result = plan(self.grid, start, Block.parse(target),
                      WorldStamp.parse(self.state['world']), time.monotonic())
        if result.route is None:
            raise ValueError('path_' + result.reason)
        return [{'x': p.x + 0.5, 'y': p.y, 'z': p.z + 0.5} for p in result.route.nodes[1:]]
