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
from navigation_controller.terrain import (Block, TerrainAssembler, TerrainError,
                                          TerrainPageError, StaleTerrainError, WorldStamp)
from .transport import BridgeError
from .terrain_diagnostics import ScanDiagnostics

SCAN_SECONDS = 3.0
SCAN_ATTEMPTS = 2
SCAN_PAGES = 32
PAGE_INTERVAL = 0.05


def scan_identity(state):
    player, action = state.get('player'), state.get('client_action')
    if not isinstance(player, dict) or not isinstance(action, dict):
        raise TerrainError('invalid_terrain_state_context')
    identity = player.get('uuid'), action.get('action_session')
    if not all(isinstance(value, str) and value for value in identity):
        raise TerrainError('invalid_terrain_state_context')
    return identity


class WorldCache:
    def __init__(self):
        self.state = None
        self.grid = None
        self.cells = {}
        self.received_at = 0.0
        self.terrain_received_at = 0.0
        self.terrain_read = {'outcome': 'not_scanned', 'attempts': 0}

    def invalidate_terrain(self):
        self.grid, self.cells = None, {}
        self.terrain_received_at = 0.0

    def observe(self, bridge, *, diagnostics=None, phase=None):
        state = (bridge.request('GET', '/control/state?radius=8') if diagnostics is None
                 else diagnostics.request(bridge, phase, '/control/state?radius=8'))
        if not isinstance(state, dict) or not isinstance(state.get('world'), dict):
            raise TerrainError('invalid_terrain_state_world')
        old_world = self.state.get('world', {}) if self.state else {}
        if old_world.get('world_generation') != state['world'].get('world_generation'):
            self.invalidate_terrain()
        self.state, self.received_at = state, time.monotonic()
        return state

    def scan(self, bridge, radius=4, vertical=2):
        if type(radius) is not int or not 1 <= radius <= 8 or type(vertical) is not int or not 2 <= vertical <= 4:
            raise ValueError('terrain_bounds_radius_1_to_8_vertical_2_to_4')
        # Never leave the previous successful scan available after a failed refresh.
        self.invalidate_terrain()
        started = time.monotonic()
        deadline = started + SCAN_SECONDS
        self.terrain_read = {'outcome': 'reading', 'attempts': 0, 'pages': 0,
                             'last_rejection': None, 'elapsed_ms': 0}
        diagnostics = ScanDiagnostics(time.monotonic, started, deadline)
        self.terrain_read['diagnostics'] = diagnostics.data
        initial_world = None
        initial_identity = None
        previous_world = None
        for attempt in range(1, SCAN_ATTEMPTS + 1):
            self.terrain_read['attempts'] = attempt
            diagnostics.enter_attempt(attempt)
            try:
                diagnostics.at('attempt_deadline')
                if time.monotonic() >= deadline:
                    raise StaleTerrainError('stale_terrain_clock')
                first = self.observe(bridge, diagnostics=diagnostics, phase='initial_state')
                diagnostics.at('initial_state_validation')
                world = WorldStamp.parse(first['world'])
                identity = scan_identity(first)
                if initial_world is None:
                    initial_world, initial_identity = world, identity
                elif not initial_world.same_world(world) or identity != initial_identity:
                    raise TerrainError('terrain_refresh_context_changed')
                elif world.tick < previous_world.tick:
                    raise TerrainError('terrain_state_tick_reversed')
                previous_world = world
                diagnostics.at('initial_state_deadline')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StaleTerrainError('stale_terrain_clock')
                diagnostics.attempt['assembler_budget_ms'] = round(remaining * 1000, 3)
                with diagnostics.stage('assembler_init'):
                    assembler = TerrainAssembler(world, time.monotonic(),
                                                 max_pages=SCAN_PAGES, max_scan_seconds=remaining)
                path = f'/control/terrain?radius={radius}&vertical={vertical}&limit=128'
                cells = {}
                while True:
                    diagnostics.at('page_deadline')
                    if time.monotonic() >= deadline:
                        raise StaleTerrainError('stale_terrain_clock')
                    if assembler.pages >= SCAN_PAGES:
                        raise TerrainError('scan_page_budget')
                    page = diagnostics.request(bridge, 'terrain_page', path, assembler.pages + 1)
                    self.terrain_read['pages'] += 1
                    with diagnostics.stage('assembler_add_and_collect', assembler.pages + 1):
                        assembler.add(page, time.monotonic())
                        for cell in page['cells']:
                            if cell.get('status') == 'loaded':
                                cells[(cell['x'], cell['y'], cell['z'])] = cell
                    if assembler.complete:
                        break
                    with diagnostics.stage('page_interval'):
                        time.sleep(PAGE_INTERVAL)
                    path = '/control/terrain?cursor=' + assembler.next_cursor
                diagnostics.at('final_state_deadline')
                if time.monotonic() >= deadline:
                    raise StaleTerrainError('stale_terrain_clock')
                last = self.observe(bridge, diagnostics=diagnostics, phase='final_state')
                diagnostics.at('final_state_validation')
                if scan_identity(last) != initial_identity:
                    raise TerrainError('terrain_refresh_context_changed')
                last_world = WorldStamp.parse(last['world'])
                if last_world.same_world(world) and last_world.tick < world.tick:
                    raise TerrainError('terrain_state_tick_reversed')
                previous_world = last_world
                with diagnostics.stage('assembler_finish'):
                    grid = assembler.finish(last_world, time.monotonic())
                diagnostics.at('completion_deadline')
                if time.monotonic() > deadline:
                    raise StaleTerrainError('stale_terrain_clock')
                self.grid, self.cells = grid, cells
                # Freshness starts with the new attempt, not the last page's arrival.
                self.terrain_received_at = grid.received_at
                self.terrain_read['outcome'] = 'complete' if attempt == 1 else 'recovered'
                finished = time.monotonic()
                self.terrain_read['elapsed_ms'] = round((finished - started) * 1000, 3)
                diagnostics.end_attempt(finished, self.terrain_read['outcome'])
                return {'origin': vars(grid.origin), 'radius': radius, 'vertical': vertical,
                        'world_generation': grid.world.generation,
                        'cells': list(cells.values()), 'complete': grid.complete}
            except (TerrainError, BridgeError, KeyError, TypeError, ValueError) as exc:
                self.invalidate_terrain()
                if isinstance(exc, TerrainPageError):
                    reason, refreshable = exc.detail, exc.refreshable
                elif isinstance(exc, StaleTerrainError):
                    reason, refreshable = str(exc), True
                elif isinstance(exc, BridgeError):
                    reason = exc.code
                    refreshable = (not exc.uncertain and (exc.code, exc.status) in {
                        ('stale_terrain_cursor', 409), ('terrain_rate_limited', 429)})
                else:
                    reason = str(exc) if isinstance(exc, TerrainError) else 'malformed_terrain_page'
                    refreshable = False
                finished = time.monotonic()
                self.terrain_read.update(outcome='failed', last_rejection=reason,
                                         elapsed_ms=round((finished - started) * 1000, 3))
                diagnostics.end_attempt(finished, 'failed', reason, exc)
                if not refreshable:
                    if isinstance(exc, TerrainPageError):
                        raise TerrainError('invalid_terrain_page_' + reason) from None
                    raise
                if attempt == SCAN_ATTEMPTS or time.monotonic() + PAGE_INTERVAL >= deadline:
                    raise TerrainError('terrain_refresh_exhausted_' + reason) from None
                # New state, assembler, generation, cells and initial GET next time.
                # Never continue or replay the poisoned cursor, and never retry POST.
                with diagnostics.stage('retry_interval'):
                    time.sleep(PAGE_INTERVAL)

    def route(self, bridge, target, radius=4, vertical=2):
        self.scan(bridge, radius, vertical)
        player = self.state['player']
        start = Block(*(math.floor(player[k]) for k in ('x', 'y', 'z')))
        result = plan(self.grid, start, Block.parse(target),
                      WorldStamp.parse(self.state['world']), time.monotonic())
        if result.route is None:
            raise ValueError('path_' + result.reason)
        return [{'x': p.x + 0.5, 'y': p.y, 'z': p.z + 0.5} for p in result.route.nodes[1:]]
