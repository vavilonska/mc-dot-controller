"""One small loaded-terrain cache and an adapter to the existing A* planner."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

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
                                          TerrainPageError, StaleTerrainError, WorldStamp, CapabilityWorldStamp)
from .transport import BridgeError
from .capability_snapshot import validate_snapshot, exact
from navigation_controller.observation_clock import CONTRACT, PROFILE, ClockStamp
from .terrain_diagnostics import ScanDiagnostics
from .navigation_binding import NativeBindingContext

SCAN_SECONDS = 3.0
SCAN_ATTEMPTS = 2
SCAN_PAGES = 32
PAGE_INTERVAL = 0.05
CAPABILITY_PAGE_LIMIT = 1024


@dataclass(frozen=True)
class _ScanStart:
    """One-use proof of the state read in this very snapshot, never a cache hit."""
    state: dict
    unchanged: dict
    started: float
    finished: float
    entity_radius: int
    bundle: dict
    unchanged_bundle: dict


def _scan_origin(state):
    values = tuple(state['player'][key] for key in ('x', 'y', 'z'))
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise TerrainError('invalid_terrain_state_origin')
    return Block(*(math.floor(value) for value in values))


def _navigation_epoch(state):
    # observe() already validates the native guard, including sticky schema use.
    return state['world'].get('navigation_guard', {}).get('epoch')


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
        self.native_binding = NativeBindingContext()
        self._scan_start = None
        self.state = None
        self.state_capture = None
        self.state_response_metadata = None
        self.capability_bundle = None
        self.grid = None
        self.cells = {}
        self.received_at = 0.0
        self.terrain_received_at = 0.0
        self.terrain_read = {'outcome': 'not_scanned', 'attempts': 0}

    def invalidate_terrain(self):
        self.grid, self.cells = None, {}
        self.terrain_received_at = 0.0

    def observe(self, bridge, *, diagnostics=None, phase=None, coordination=False, entity_radius=8, capability=False, observation_clock=None):
        if observation_clock is not None and (observation_clock != CONTRACT or not capability or coordination):
            raise ValueError('invalid_read_only_clock_options')
        self._scan_start = None
        capture_started = time.monotonic() if coordination or capability else None
        self.state_capture = None
        self.state_response_metadata = None
        self.capability_bundle = None
        if type(capability) is not bool:
            raise ValueError('invalid_capability_observation')
        if type(entity_radius) is not int or not 1 <= entity_radius <= 128:
            raise ValueError('entity_radius_1_to_128')
        endpoint = 'capability-snapshot' if capability else 'state'
        path = f'/control/{endpoint}?radius={entity_radius}' + ('&coordination_step=1' if coordination else '')
        if observation_clock is not None: path += '&observation_clock='+CONTRACT
        value = (bridge.request('GET', path) if diagnostics is None
                 else diagnostics.request(bridge, phase, path))
        capture_finished = time.monotonic() if coordination or capability else None
        response_metadata = deepcopy(getattr(bridge, 'last_response_metadata', None)) if coordination or capability else None
        try:
            bundle = validate_snapshot(value, entity_radius, observation_clock=observation_clock) if capability else None
        except ValueError as exc:
            raise TerrainError(str(exc)) from None
        state = bundle['state'] if capability else value
        if not isinstance(state, dict) or not isinstance(state.get('world'), dict):
            raise TerrainError('invalid_terrain_state_world')
        try:
            self.native_binding.observe(state)
        except ValueError as exc:
            raise TerrainError(str(exc)) from None
        old_world = self.state.get('world', {}) if self.state else {}
        if old_world.get('world_generation') != state['world'].get('world_generation'):
            self.invalidate_terrain()
        self.state, self.received_at = state, time.monotonic()
        self.capability_bundle = bundle
        self.state_capture = ({'started_mono': capture_started, 'finished_mono': capture_finished}
                              if coordination or capability else None)
        self.state_response_metadata = response_metadata
        return state

    def observe_scan_start(self, bridge, *, coordination=False, entity_radius=8, observation_clock=None):
        """Acquire A for a capability snapshot and bind its original read time.

        Every sibling belongs to this A; any further state read invalidates it.
        No state from an earlier snapshot can become a new initial observation.
        """
        started = time.monotonic()
        state = self.observe(bridge, coordination=coordination, entity_radius=entity_radius, capability=True, observation_clock=observation_clock)
        token = _ScanStart(state, deepcopy(state), started, time.monotonic(), entity_radius,
                           self.capability_bundle, deepcopy(self.capability_bundle))
        self._scan_start = token
        return state, token

    def scan(self, bridge, radius=4, vertical=2, *, coordination=False, capability=False, entity_radius=8, survey=False,
             _initial_observation=None, observation_clock=None):
        if observation_clock is not None and (observation_clock != CONTRACT or not capability or survey or coordination):
            raise ValueError('invalid_read_only_clock_options')
        if type(survey) is not bool or survey and not capability:
            raise ValueError('survey_requires_capability_observation')
        if type(capability) is not bool:
            raise ValueError('invalid_capability_observation')
        if type(radius) is not int or not 1 <= radius <= (16 if survey else 8) or type(vertical) is not int or not 2 <= vertical <= (8 if capability else 4):
            raise ValueError('terrain_bounds_radius_1_to_8_vertical_2_to_8' if capability else 'terrain_bounds_radius_1_to_8_vertical_2_to_4')
        if not capability and entity_radius != 8:
            raise ValueError('entity_radius_requires_capability_observation')
        if type(entity_radius) is not int or not 1 <= entity_radius <= 128:
            raise ValueError('entity_radius_1_to_128')
        stamp_type = CapabilityWorldStamp if capability else WorldStamp
        # Never leave the previous successful scan available after a failed refresh.
        self.invalidate_terrain()
        entered = time.monotonic()
        token, self._scan_start = self._scan_start, None
        if _initial_observation is not None:
            if (not capability or not isinstance(_initial_observation, _ScanStart)
                    or _initial_observation is not token or token.state is not self.state
                    or not exact(token.state, token.unchanged) or token.entity_radius != entity_radius
                    or token.bundle is not self.capability_bundle or not exact(token.bundle, token.unchanged_bundle)
                    or not token.started <= token.finished <= entered):
                raise TerrainError('invalid_terrain_initial_observation')
            started = token.started
        else:
            started = entered
        scan_seconds, scan_pages, scan_ticks = (15.0, 256, 320) if survey else (SCAN_SECONDS, SCAN_PAGES, 40)
        deadline = started + scan_seconds
        self.terrain_read = {'outcome': 'reading', 'attempts': 0, 'pages': 0,
                             'last_rejection': None, 'elapsed_ms': 0}
        diagnostics = ScanDiagnostics(time.monotonic, started, deadline)
        self.terrain_read['diagnostics'] = diagnostics.data
        initial_world = None
        initial_identity = None
        previous_world = None
        initial_epoch = None
        for attempt in range(1, (1 if observation_clock is not None else SCAN_ATTEMPTS) + 1):
            self.terrain_read['attempts'] = attempt
            diagnostics.enter_attempt(attempt)
            try:
                diagnostics.at('attempt_deadline')
                if time.monotonic() >= deadline:
                    raise StaleTerrainError('stale_terrain_clock')
                attempt_started = time.monotonic()
                if attempt == 1 and _initial_observation is not None:
                    first = token.state
                    attempt_started = token.started
                    diagnostics.attempt['initial_state_reused'] = True
                    diagnostics.attempt['initial_state_capture'] = {
                        'started_mono': token.started, 'finished_mono': token.finished,
                        'entity_radius': token.entity_radius}
                else:
                    first = self.observe(bridge, diagnostics=diagnostics, phase='initial_state', coordination=coordination,
                                         **({'entity_radius': entity_radius, 'capability': True, 'observation_clock': observation_clock} if capability else {}))
                diagnostics.at('initial_state_validation')
                world = stamp_type.parse(first['world'])
                identity = scan_identity(first)
                if initial_world is None:
                    initial_world, initial_identity = world, identity
                    initial_epoch = _navigation_epoch(first) if capability else None
                elif not initial_world.same_world(world) or identity != initial_identity:
                    raise TerrainError('terrain_refresh_context_changed')
                elif observation_clock is None and world.tick < previous_world.tick:
                    raise TerrainError('terrain_state_tick_reversed')
                if capability and _navigation_epoch(first) != initial_epoch:
                    raise TerrainError('terrain_navigation_epoch_changed')
                expected_origin = _scan_origin(first) if capability else None
                previous_world = world
                diagnostics.at('initial_state_deadline')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StaleTerrainError('stale_terrain_clock')
                diagnostics.attempt['assembler_budget_ms'] = round(
                    (deadline - attempt_started if capability else remaining) * 1000, 3)
                with diagnostics.stage('assembler_init'):
                    assembler = TerrainAssembler(world, attempt_started if capability else time.monotonic(),
                        max_pages=scan_pages, max_scan_seconds=(deadline - attempt_started if capability else remaining),
                        max_scan_ticks=scan_ticks, historical_survey=survey,
                        capability_page_limit=CAPABILITY_PAGE_LIMIT if capability else None,
                        observation_clock=first.get('observation_clock') if observation_clock is not None else None)
                path = (f'/control/terrain?radius={radius}&vertical={vertical}&limit={CAPABILITY_PAGE_LIMIT}&capability=1'
                        if capability else f'/control/terrain?radius={radius}&vertical={vertical}&limit=128')
                if observation_clock is not None: path += '&observation_clock='+CONTRACT
                cells = {}
                source_pages = []
                while True:
                    diagnostics.at('page_deadline')
                    if time.monotonic() >= deadline:
                        raise StaleTerrainError('stale_terrain_clock')
                    if assembler.pages >= scan_pages:
                        raise TerrainError('scan_page_budget')
                    page = diagnostics.request(bridge, 'terrain_page', path, assembler.pages + 1)
                    self.terrain_read['pages'] += 1
                    if capability and not isinstance(page, dict):
                        raise TerrainError('invalid_terrain_page_malformed_terrain_page')
                    source_pages.append({'source_tick': page.get('game_time'), 'response_tick': page.get('response_game_time'),
                        'captured_mono': time.monotonic(), 'offset': page.get('offset'), 'returned': page.get('returned'),
                        **({'source_clock':deepcopy(page.get('source_clock')),'response_clock':deepcopy(page.get('response_clock'))}
                           if observation_clock is not None else {})})
                    with diagnostics.stage('assembler_add_and_collect', assembler.pages + 1):
                        assembler.add(page, time.monotonic())
                        if capability and assembler.header[1:4] != (expected_origin, radius, vertical):
                            raise TerrainError('terrain_requested_region_changed')
                        for cell in page['cells']:
                            if cell.get('status') == 'loaded':
                                cells[(cell['x'], cell['y'], cell['z'])] = cell
                    if assembler.complete:
                        break
                    with diagnostics.stage('page_interval'):
                        time.sleep(PAGE_INTERVAL)
                    path = '/control/terrain?cursor=' + assembler.next_cursor + ('&observation_clock='+CONTRACT if observation_clock is not None else '')
                diagnostics.at('final_state_deadline')
                if time.monotonic() >= deadline:
                    raise StaleTerrainError('stale_terrain_clock')
                last = self.observe(bridge, diagnostics=diagnostics, phase='final_state', coordination=coordination,
                                    **({'entity_radius': entity_radius, 'capability': True, 'observation_clock': observation_clock} if capability else {}))
                diagnostics.at('final_state_validation')
                if scan_identity(last) != initial_identity:
                    raise TerrainError('terrain_refresh_context_changed')
                if capability and _navigation_epoch(last) != initial_epoch:
                    raise TerrainError('terrain_navigation_epoch_changed')
                last_world = stamp_type.parse(last['world'])
                if observation_clock is None and last_world.same_world(world) and last_world.tick < world.tick:
                    raise TerrainError('terrain_state_tick_reversed')
                previous_world = last_world
                with diagnostics.stage('assembler_finish'):
                    grid = assembler.finish(last_world, time.monotonic(),
                        observation_clock=last.get('observation_clock') if observation_clock is not None else None)
                diagnostics.at('completion_deadline')
                if time.monotonic() > deadline:
                    raise StaleTerrainError('stale_terrain_clock')
                if not survey and observation_clock is None:
                    self.grid, self.cells = grid, cells
                # Freshness starts with the new attempt, not the last page's arrival.
                if not survey:
                    self.terrain_received_at = grid.received_at
                self.terrain_read['outcome'] = 'complete' if attempt == 1 else 'recovered'
                finished = time.monotonic()
                self.terrain_read['elapsed_ms'] = round((finished - started) * 1000, 3)
                diagnostics.end_attempt(finished, self.terrain_read['outcome'])
                return {'origin': vars(grid.origin), 'radius': radius, 'vertical': vertical,
                        'world_generation': grid.world.generation,
                        **({'capture_started_mono': grid.received_at, 'capture_finished_mono': finished,
                            'source_tick': grid.first_tick} if coordination or capability else {}),
                        **({'dimension': grid.world.dimension, 'scan_generation': grid.scan_generation,
                            'last_tick': grid.last_tick} if capability else {}),
                        **({'observation_clock_profile':PROFILE,
                            'first_source_clock':grid.first_source_clock.as_dict(),
                            'last_source_clock':grid.last_source_clock.as_dict(),
                            'last_response_clock':grid.last_response_clock.as_dict(),
                            'source_pages':source_pages} if observation_clock is not None else {}),
                        'cells': list(cells.values()), 'complete': grid.complete,
                        **({'historical_survey': True, 'source_pages': source_pages} if survey else {})}
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
                if not refreshable or observation_clock is not None:
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
