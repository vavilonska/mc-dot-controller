"""Default-disabled guarded one-sample contract over an explicitly selected transport.

Live transport requires separate explicit acceptance in both adapter and transport.
No credentials or legacy input routes are handled here. The included fake is not
Minecraft physics; 100 ms is an admission lease, never a movement duration.
"""
from dataclasses import dataclass
import math
import struct
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4
from .executor import in_corridor, wrap_yaw
from .observation import Observation, Position, from_wire
from .planner import Route, safe_edge
from .terrain import Block, TerrainAssembler, TerrainError, WorldStamp, integer, number, protocol, uuid


class SampleError(TerrainError):
    pass


class OfflineTransport(Protocol):
    simulation_only: bool
    def request(self, method: str, path: str, body: dict | None = None) -> dict: ...


@dataclass(frozen=True)
class SampleConfig:
    enabled: bool = False
    acceptance_verified: bool = False
    max_actions: int = 192
    max_samples: int = 96
    max_seconds: float = 30.0
    settle_seconds: float = 1.0
    settle_reads: int = 16

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.acceptance_verified) is not bool:
            raise ValueError('invalid_enabled')
        integer(self.max_actions, 1, 512)
        integer(self.max_samples, 1, 256)
        integer(self.settle_reads, 2, 40)
        if not 0 < number(self.max_seconds) <= 60 or not .1 <= number(self.settle_seconds) <= 2:
            raise ValueError('invalid_sample_budget')


@dataclass(frozen=True)
class SampleContext:
    observation: Observation
    session: str
    observation_id: str
    canonical_yaw: float
    state_started_at: float
    requests_remaining: int
    floor_ids: object


@dataclass(frozen=True)
class SampleResult:
    reason: str
    actions: int = 0
    samples: int = 0
    reached_waypoints: int = 0
    cleanup_verified: bool = True


# Exact narrower bridge-side movement corridor floor set.
MOVEMENT_FLOORS = frozenset('minecraft:' + s for s in (
    'stone', 'cobblestone', 'dirt', 'grass_block', 'granite', 'diorite', 'andesite',
    'deepslate', 'cobbled_deepslate', 'oak_planks', 'birch_planks', 'spruce_planks'))


def require_fields(data, expected, code):
    if not isinstance(data, dict):
        raise SampleError(code)
    for key, value in expected.items():
        if key not in data:
            raise SampleError(code)
        actual = data[key]
        if type(actual) is not type(value) and not (type(value) is float and type(actual) in (int, float)):
            raise SampleError(code)
        if actual != value:
            raise SampleError(code)


def movement_status(data, session=None):
    require_fields(data, {'schema_version': 1, 'enabled': True, 'admission_open': True,
                         'owner_request_id': None, 'owner_action': None, 'sampled': False, 'released': True,
                         'max_duration_ms': 100, 'max_ttl_ms': 250, 'max_input_samples': 1,
                         'forward_impulse': .5, 'held_keys': False,
                         'local_unpublished_survival_only': True, 'turn_supported': True},
                   'movement_capability_or_ownership_mismatch')
    actual_session = uuid(data['session'])
    if session is not None and actual_session != session:
        raise SampleError('movement_session_changed')
    integer(data['requests_remaining'], 1, 4096)
    return actual_session


def turn_status(data):
    require_fields(data, {'schema_version': 1, 'enabled': True, 'max_ttl_ms': 100,
                         'max_yaw_step': 30.0, 'held_input': False,
                         'local_unpublished_survival_only': True, 'shared_movement_observation': True,
                         'pitch_supported': False}, 'turn_capability_mismatch')


def swept_corridor(context):
    """Mirror the bridge's 0.6-forward, 0.05-margin dry full-block corridor."""
    obs = context.observation
    p = obs.position
    radians = math.radians(context.canonical_yaw)
    end_x, end_z = p.x - math.sin(radians) * .6, p.z + math.cos(radians) * .6
    feet_y = round(p.y)
    for x in range(math.floor(min(p.x, end_x) - .35), math.floor(max(p.x, end_x) + .35) + 1):
        for z in range(math.floor(min(p.z, end_z) - .35), math.floor(max(p.z, end_z) + .35) + 1):
            feet = Block(x, feet_y, z)
            if (not obs.terrain.standable(feet)
                    or context.floor_ids.get(feet.offset(y=-1)) not in MOVEMENT_FLOORS):
                return False
    return True


class GuardedSampleAdapter:
    READ_PATHS = frozenset({'/control/capabilities', '/control/status', '/control/state?radius=4',
                           '/control/terrain?radius=1&vertical=1&limit=128'})
    WRITE_PATHS = frozenset({'/control/guarded-movement', '/control/guarded-turn'})

    def __init__(self, transport, clock, expected_identity, config=None, nonce_factory=None, expected_movement_session=None):
        self.transport, self.clock = transport, clock
        self.config = config or SampleConfig()
        if len(expected_identity) != 4:
            raise ValueError('expected run/process/player/world identity required')
        run, pid, player, world = expected_identity
        if not isinstance(run, str) or not run or len(run) > 160:
            raise ValueError('invalid_expected_run')
        integer(pid, 1); uuid(player); uuid(world)
        self.expected_identity = tuple(expected_identity)
        self.expected_movement_session = (None if expected_movement_session is None else uuid(expected_movement_session))
        self.nonce_factory = nonce_factory or (lambda: str(uuid4()))
        self._session = None
        self._latest = None
        self._faulted = False
        self._seen_requests = set()
        self.actions = self.samples = 0
        self.cleanup_verified = True

    def _request(self, method, path, body=None):
        if getattr(self.transport, 'simulation_only', None) is not True:
            live_config = getattr(self.transport, 'config', None)
            if (self.config.acceptance_verified is not True
                    or getattr(live_config, 'acceptance_verified', None) is not True
                    or self.expected_movement_session is None):
                raise SampleError('live_acceptance_required')
            if method == 'POST' and getattr(live_config, 'enabled', None) is not True:
                raise SampleError('live_transport_disabled')
        if self._faulted:
            raise SampleError('adapter_fault_latched')
        if method == 'GET':
            cursor_path = False
            if isinstance(path,str) and path.startswith('/control/terrain?cursor='):
                cursor = path.removeprefix('/control/terrain?cursor=')
                try:
                    generation, offset = cursor.rsplit(':',1)
                    uuid(generation)
                    cursor_path = str(integer(int(offset),1,18_513)) == offset
                except (ValueError,TypeError):
                    cursor_path = False
            if (path not in self.READ_PATHS and not cursor_path) or body is not None:
                raise SampleError('read_not_allowlisted')
        elif method == 'POST':
            if not self.config.enabled:
                raise SampleError('sample_adapter_disabled')
            if path not in self.WRITE_PATHS:
                raise SampleError('legacy_or_unknown_input_forbidden')
        else:
            raise SampleError('method_not_allowlisted')
        try:
            result = self.transport.request(method, path, body)
            protocol(result)
            return result
        except Exception:
            self._faulted = True
            self._latest = None
            if method == 'POST':
                self.cleanup_verified = False
                raise SampleError('ambiguous_action_response') from None
            raise SampleError('read_failed') from None

    def stop(self):
        """Close local admission; never send an unguarded network release.

        A sent action may remain ambiguous. Bridge cleanup still owns release;
        this method does not brake a player or prove remote input is neutral.
        """
        self._latest = None
        self._faulted = True
        close = getattr(self.transport, 'close', None)
        if callable(close):
            close()

    def prepare(self):
        data = self._request('GET', '/control/capabilities')
        try:
            self._session = movement_status(data.get('guarded_movement'), self.expected_movement_session)
            turn_status(data.get('guarded_turn'))
        except (TerrainError, KeyError, TypeError):
            self._faulted = True
            raise SampleError('guarded_capabilities_unavailable') from None
        self._latest = None

    def _status(self, data):
        protocol(data)
        if data.get('in_world') is not True or data.get('bridge_running') is not True:
            raise SampleError('not_in_world')
        if data['world'].get('present') is not True or data['player'].get('present') is not True:
            raise SampleError('missing_player_or_world')
        world = WorldStamp.parse(data['world'])
        identity = (data['run_id'], integer(data['process_id'], 1), uuid(data['player']['uuid']), world.generation)
        if identity != self.expected_identity:
            raise SampleError('unexpected_identity')
        movement_status(data['guarded_movement'], self._session)
        turn_status(data['guarded_turn'])
        if (data['screen'].get('present') is not False or data['mouse'].get('grabbed') is not True
                or data.get('held_mappings') != [] or data['mouse'].get('held_world_buttons') != []
                or any(data['mouse'].get(k) is not False for k in ('left_pressed', 'right_pressed', 'middle_pressed'))):
            raise SampleError('ui_or_held_input')
        return world

    def _state(self, state, before, after, *, moving=False):
        first, last = self._status(before), self._status(after)
        protocol(state)
        world = WorldStamp.parse(state['world'])
        p = state['player']
        if (not first.same_world(world) or not last.same_world(world)
                or p['uuid'] != self.expected_identity[2] or p['dimension'] != world.dimension):
            raise SampleError('state_identity_mismatch')
        if not first.tick <= world.tick <= last.tick or last.tick - first.tick > 3 or last.tick - world.tick > 1:
            raise SampleError('stale_status_bracket')
        gm = state['guarded_movement']
        movement_status(gm, self._session)
        turn_status(state['guarded_turn'])
        require_fields(gm, {'max_observation_age_ms': 150}, 'observation_capability_mismatch')
        uuid(gm['observation_id'])
        canonical = number(gm['observation_yaw'])
        if not -180 <= canonical < 180 or abs(wrap_yaw(canonical - number(p['yaw']))) > .001:
            raise SampleError('noncanonical_observation_yaw')
        position, velocity = Position.parse(p), Position.parse(p['velocity'])
        if (p.get('gamemode') != 'survival' or p.get('on_ground') is not True
                or number(p['health']) != number(p['max_health']) or number(p['health']) <= 0
                or integer(p['food'], 0, 20) < 8
                or integer(p['air'], 0) != integer(p['max_air'], 1)
                or p.get('effects') != [] or p.get('effects_truncated') is not False
                or integer(p['effects_total'], 0) != 0 or integer(p['effects_returned'], 0) != 0
                or abs(position.y - round(position.y)) > .001 or abs(velocity.y) > .1):
            raise SampleError('unsafe_player_state')
        nearby = state['nearby']
        if (nearby.get('truncated') is not False or nearby.get('entities') != []
                or integer(nearby['total'], 0) != 0 or integer(nearby['returned'], 0) != 0
                or number(nearby['radius']) < 4):
            raise SampleError('entities_or_unknown_nearby')
        speed = math.hypot(velocity.x, velocity.z)
        if not moving and speed > .001:
            raise SampleError('player_not_settled')
        for status in (before, after):
            q = status['player']
            if abs(wrap_yaw(number(q['yaw']) - canonical)) > .1:
                raise SampleError('yaw_changed_in_bracket')
            if not moving and Position.parse(q).distance(position) > .01:
                raise SampleError('position_changed_in_bracket')
        return world, position, canonical, speed

    def observe(self):
        self._latest = None
        if self._session is None:
            raise SampleError('prepare_required')
        started = number(self.clock.monotonic())
        try:
            before = self._request('GET', '/control/status')
            before_world = self._status(before)
            assembler = TerrainAssembler(before_world,started,max_pages=27,max_scan_ticks=2,max_scan_seconds=.3)
            path = '/control/terrain?radius=1&vertical=1&limit=128'
            floor_ids = {}
            while True:
                if number(self.clock.monotonic())-started >= .3:
                    raise SampleError('terrain_observation_deadline')
                page = self._request('GET',path)
                assembler.add(page,self.clock.monotonic())
                floor_ids.update({Block.parse(c): c.get('id') for c in page['cells']})
                if assembler.complete:
                    break
                if number(self.clock.monotonic())+.05-started >= .3:
                    raise SampleError('terrain_observation_deadline')
                self.clock.sleep(.05)
                path = '/control/terrain?cursor='+assembler.next_cursor
            state_started = number(self.clock.monotonic())
            state = self._request('GET', '/control/state?radius=4')
            after = self._request('GET', '/control/status')
            world, position, yaw, speed = self._state(state, before, after)
            now = number(self.clock.monotonic())
            if not 0 <= now - state_started < .1:
                raise SampleError('observation_local_deadline')
            grid = assembler.finish(WorldStamp.parse(after['world']), now)
            obs = from_wire(before, state, after, grid, started)
            obs.require_safe(now)
            gm = state['guarded_movement']
            context = SampleContext(obs, self._session, gm['observation_id'], yaw, state_started,
                                    integer(gm['requests_remaining'], 1, 4096),
                                    MappingProxyType(floor_ids))
            self._latest = context
            return context
        except Exception:
            self._latest = None
            self._faulted = True
            if self.actions:
                self.cleanup_verified = False
            raise SampleError('invalid_or_unsafe_observation') from None

    def _envelope(self, context, deadline):
        if (getattr(self.transport,'simulation_only',None) is not True
                and (self.config.max_actions != 1 or self.config.max_samples != 1
                     or self.config.max_seconds > 5)):
            raise SampleError('live_single_action_scope_required')
        if not self.config.enabled:
            raise SampleError('sample_adapter_disabled')
        now = number(self.clock.monotonic())
        if self._faulted or context is not self._latest:
            raise SampleError('consumed_or_unrecognized_observation')
        context.observation.require_safe(now)
        if (context.observation.identity != self.expected_identity or context.session != self._session
                or not 0 <= now - context.state_started_at < .1):
            raise SampleError('action_context_stale')
        if not now + .1 <= number(deadline):
            raise SampleError('action_deadline_exhausted')
        if self.actions >= self.config.max_actions or context.requests_remaining < 1:
            raise SampleError('action_budget_exhausted')
        request_id = uuid(self.nonce_factory())
        if request_id in self._seen_requests:
            raise SampleError('request_id_reused')
        self._seen_requests.add(request_id)
        obs = context.observation
        return {'session': context.session, 'request_id': request_id, 'observation_id': context.observation_id,
                'expected_world_generation': obs.world.generation, 'expected_player_uuid': obs.player_uuid,
                'expected_tick': obs.world.tick, 'expected_x': obs.position.x, 'expected_y': obs.position.y,
                'expected_z': obs.position.z, 'expected_yaw': context.canonical_yaw, 'ttl_ms': 100}

    def _submit(self, path, body, expected):
        self._latest = None  # Consume before dispatch; ambiguous requests are never retried.
        self.actions += 1
        self.cleanup_verified = False
        result = self._request('POST', path, body)
        try:
            require_fields(result, expected | {'request_id': body['request_id'], 'released': True}, 'action_result_mismatch')
        except TerrainError:
            self._faulted = True
            raise
        self.cleanup_verified = True

    def turn(self, context, target_yaw, deadline):
        target_yaw = number(target_yaw)
        if not -180 <= target_yaw < 180 or abs(wrap_yaw(target_yaw - context.canonical_yaw)) > 30:
            raise SampleError('turn_step_out_of_bounds')
        # Minecraft stores yaw as float32. Validate the angle actually applied.
        target_yaw = wrap_yaw(struct.unpack('!f', struct.pack('!f', target_yaw))[0])
        if abs(wrap_yaw(target_yaw - context.canonical_yaw)) > 30:
            raise SampleError('rounded_turn_step_out_of_bounds')
        body = self._envelope(context, deadline)
        body.update(turn_schema_version=1, action='yaw', target_yaw=target_yaw)
        self._submit('/control/guarded-turn', body,
                     {'turn_schema_version': 1, 'dispatched': True, 'turn_confirmed': False})
        try:
            fresh = self.observe()
            self._verify_readback(context, fresh, max_distance=.03, expected_yaw=target_yaw)
            if number(self.clock.monotonic()) >= deadline:
                raise SampleError('turn_readback_deadline_exhausted')
            return fresh
        except Exception:
            self._latest = None
            self._faulted = True
            self.cleanup_verified = False
            raise

    def forward_sample(self, context, deadline):
        if self.samples >= self.config.max_samples:
            raise SampleError('sample_budget_exhausted')
        if not swept_corridor(context):
            raise SampleError('forward_corridor_unsafe')
        body = self._envelope(context, deadline)
        body.update(movement_schema_version=1, action='forward_sample', duration_ms=100)
        self.samples += 1
        self._submit('/control/guarded-movement', body,
                     {'movement_schema_version': 1, 'sampled': True, 'movement_confirmed': False})
        try:
            return self._settle(context, deadline)
        except Exception:
            self._latest = None
            self._faulted = True
            self.cleanup_verified = False
            raise

    def _verify_readback(self, old, new, max_distance=.35, expected_yaw=None):
        a, b = old.observation, new.observation
        if (b.identity != a.identity or b.world.tick < a.world.tick
                or b.position.distance(a.position) > max_distance or abs(b.position.y - a.position.y) > .001
                or b.health < a.health or b.horizontal_speed > .001
                or abs(wrap_yaw(new.canonical_yaw - (old.canonical_yaw if expected_yaw is None else expected_yaw))) > .1):
            raise SampleError('unsafe_action_readback')

    def _settle(self, reference, deadline):
        started = number(self.clock.monotonic())
        end = min(number(deadline), started + self.config.settle_seconds)
        previous_rest = None
        for _ in range(self.config.settle_reads):
            if not started <= number(self.clock.monotonic()) < end:
                raise SampleError('settling_deadline_exhausted')
            before = self._request('GET', '/control/status')
            state = self._request('GET', '/control/state?radius=4')
            after = self._request('GET', '/control/status')
            world, position, yaw, speed = self._state(state, before, after, moving=True)
            anchor = reference.observation
            for q in (position, Position.parse(before['player']), Position.parse(after['player'])):
                if q.distance(anchor.position) > .35 or abs(q.y - anchor.position.y) > .001:
                    raise SampleError('unexpected_settling_displacement')
            if (world.tick < anchor.world.tick or number(state['player']['health']) < anchor.health
                    or abs(wrap_yaw(yaw - reference.canonical_yaw)) > .1):
                raise SampleError('unsafe_settling_state')
            now = number(self.clock.monotonic())
            if not started <= now < end:
                raise SampleError('settling_deadline_exhausted')
            if speed <= .001:
                if previous_rest is not None:
                    tick, prior = previous_rest
                    if world.tick > tick and position.distance(prior) <= .005:
                        fresh = self.observe()
                        if self.clock.monotonic() >= end:
                            raise SampleError('settling_deadline_exhausted')
                        self._verify_readback(reference, fresh)
                        return fresh
                previous_rest = (world.tick, position)
            else:
                previous_rest = None
            if now + .05 >= end:
                raise SampleError('settling_deadline_exhausted')
            self.clock.sleep(.05)
        raise SampleError('settling_read_budget_exhausted')


class SampleNavigator:
    """One-sample route following; no duration-to-distance conversion anywhere."""
    def __init__(self, adapter):
        self.adapter = adapter
        self._busy = False

    def run(self, route: Route):
        adapter = self.adapter
        if not adapter.config.enabled:
            return SampleResult('sample_adapter_disabled')
        if getattr(adapter.transport,'simulation_only',None) is not True:
            return SampleResult('live_route_following_not_accepted')
        if self._busy:
            return SampleResult('navigator_busy')
        self._busy = True
        reached, stalled = 0, 0
        try:
            started = number(adapter.clock.monotonic())
            deadline = started + adapter.config.max_seconds
            if not route.nodes or len(route.nodes) > 129 or any(a.y != b.y for a, b in zip(route.nodes, route.nodes[1:])):
                raise SampleError('flat_bounded_route_required')
            adapter.prepare()
            context = adapter.observe()
            if context.observation.position.block() != route.nodes[0]:
                raise SampleError('route_start_mismatch')
            for index, destination in enumerate(route.nodes):
                source = route.nodes[max(0, index-1)]
                while True:
                    obs = context.observation
                    if not route.world.same_world(obs.world):
                        raise SampleError('route_world_changed')
                    obs.require_safe(adapter.clock.monotonic())
                    if adapter.clock.monotonic() >= deadline:
                        raise SampleError('navigation_deadline_exhausted')
                    if not in_corridor(obs.position, source, destination):
                        raise SampleError('left_route_corridor')
                    if source != destination and not safe_edge(obs.terrain, source, destination):
                        raise SampleError('route_edge_unsafe')
                    goal = Position(destination.x+.5, destination.y, destination.z+.5)
                    distance = goal.distance(obs.position)
                    if distance <= .12:
                        reached += 1
                        break
                    yaw = wrap_yaw(math.degrees(math.atan2(-(goal.x-obs.position.x), goal.z-obs.position.z)))
                    delta = wrap_yaw(yaw-context.canonical_yaw)
                    if abs(delta) > .1:
                        target_yaw = wrap_yaw(context.canonical_yaw + max(-29.99, min(29.99, delta)))
                        context = adapter.turn(context, target_yaw, deadline)
                        continue
                    context = adapter.forward_sample(context, deadline)
                    remaining = goal.distance(context.observation.position)
                    if remaining > distance + .02:
                        raise SampleError('sample_moved_away')
                    stalled = stalled + 1 if distance - remaining < .005 else 0
                    if stalled >= 3:
                        raise SampleError('sample_progress_stalled')
            reason = 'arrived'
        except Exception as exc:
            reason = str(exc) if isinstance(exc, TerrainError) else 'sample_controller_failure'
            adapter._latest = None
            adapter._faulted = True
        finally:
            self._busy = False
        return SampleResult(reason, adapter.actions, adapter.samples, reached, adapter.cleanup_verified)
