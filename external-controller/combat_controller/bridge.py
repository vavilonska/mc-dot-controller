"""Default-disabled guarded loopback adapter; no legacy input fallback.

No auto-discovery, token-file access, retries, redirect following or arbitrary input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import json
import math
import os
from pathlib import Path
import stat
import socket
import threading
import time
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from .core import ActionContext, HOSTILE_TYPES, WEAPONS, Entity, RealClock, Snapshot, Vec3, Clock, wrap_yaw


class BridgeError(RuntimeError):
    """Sanitized error; never embeds a response body or credential."""


class JsonTransport(Protocol):
    def request(self, method: str, path: str, body: dict | None = None) -> dict: ...


@dataclass(frozen=True)
class ConnectionConfig:
    base_url: str = 'http://127.0.0.1:38121'
    token: str = field(default='', repr=False)
    enabled: bool = False
    acceptance_verified: bool = False
    expected_identity: tuple[str, int, str, str] | None = None
    timeout: float = 0.4

    def __post_init__(self) -> None:
        u = urlsplit(self.base_url)
        if (u.scheme != 'http' or u.hostname not in ('127.0.0.1', '::1')
                or u.username is not None or u.password is not None
                or u.path not in ('', '/') or u.query or u.fragment or u.port is None):
            raise ValueError('base_url must be explicit HTTP loopback IP and port')
        if not (1 <= u.port <= 65535):
            raise ValueError('invalid port')
        if (not isinstance(self.token, str) or not self.token
                or len(self.token) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in self.token)):
            raise ValueError('provide a token explicitly in the private local configuration')
        if (type(self.enabled) is not bool or type(self.acceptance_verified) is not bool or type(self.timeout) not in (int, float)
                or not math.isfinite(self.timeout) or not 0.05 <= self.timeout <= 1):
            raise ValueError('invalid connection limits')
        if self.expected_identity is not None:
            object.__setattr__(self, 'expected_identity', tuple(self.expected_identity))
            run, pid, player, dimension = self.expected_identity
            if not run or type(pid) is not int or pid <= 0 or not player or not dimension:
                raise ValueError('invalid expected session identity')
        if self.enabled and self.expected_identity is None:
            raise ValueError('armed adapter requires the expected session identity')

    @classmethod
    def from_file(cls, path: str | Path) -> ConnectionConfig:
        """Read ONLY the explicit caller-selected config; never Bridge token paths."""
        # O_NOFOLLOW prevents symlink substitution. Bound bytes and reject publicly
        # readable config because it contains the caller-provided bearer token.
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077 or st.st_size > 8192:
                raise ValueError('configuration must be a private regular file (0600), at most 8 KiB')
            if hasattr(os, 'getuid') and st.st_uid != os.getuid():
                raise ValueError('configuration must be owned by the current user')
            with os.fdopen(fd, 'r', encoding='utf-8') as handle:
                fd = -1
                data = json.load(handle, parse_constant=_invalid_constant)
        finally:
            if fd >= 0:
                os.close(fd)
        if not isinstance(data, dict) or set(data) - {'base_url', 'token', 'enabled', 'acceptance_verified', 'expected_identity', 'timeout'}:
            raise ValueError('unexpected connection configuration field')
        if data.get('expected_identity') is not None:
            data['expected_identity'] = tuple(data['expected_identity'])
        return cls(**data)


def _invalid_constant(_: str) -> None:
    raise ValueError('non-finite JSON number')


class HttpTransport:
    MAX_JSON_BYTES = 256 * 1024
    READ_PATHS = frozenset({'/control/capabilities', '/control/status', '/control/state?radius=16',
                            '/control/terrain?radius=1&vertical=2&limit=128'})

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._url = urlsplit(config.base_url)
        self._guarded_negotiated = False

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        if method == 'GET':
            if path == '/control/capabilities':
                self._guarded_negotiated = False
            if path not in self.READ_PATHS or body is not None:
                raise BridgeError('read_not_allowlisted')
        elif method == 'POST':
            if not self.config.enabled:
                raise BridgeError('adapter_disabled')
            if path != '/control/guarded-action':
                raise BridgeError('legacy_or_unknown_input_forbidden')
            if not self.config.acceptance_verified:
                raise BridgeError('local_acceptance_not_verified')
            if not self._guarded_negotiated:
                raise BridgeError('guarded_capabilities_not_negotiated')
            validate_guarded_request(body)
        else:
            raise BridgeError('method_not_allowlisted')
        # http.client avoids environment proxies and never follows redirects.
        connection = http.client.HTTPConnection(self._url.hostname, self._url.port, timeout=self.config.timeout)
        deadline = time.monotonic() + self.config.timeout
        timer = None
        try:
            # Connect is itself socket-timeout bounded, using a numeric loopback IP.
            connection.connect()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeError('request_deadline')
            connected_socket = connection.sock

            def abort_socket():
                # Keep this socket reference even if HTTPConnection detaches it
                # for Connection: close. shutdown wakes blocked buffered reads.
                try:
                    connected_socket.shutdown(socket.SHUT_RDWR)
                except (OSError, AttributeError):
                    pass
                try:
                    connected_socket.close()
                except (OSError, AttributeError):
                    pass

            timer = threading.Timer(remaining, abort_socket)
            timer.daemon = True
            timer.start()
            payload = None if body is None else json.dumps(body, allow_nan=False).encode('utf-8')
            connection.request(method, path, body=payload, headers={
                'Authorization': 'Bearer ' + self.config.token,
                'Content-Type': 'application/json', 'Accept': 'application/json',
                'Connection': 'close',
            })
            response = connection.getresponse()
            if response.status != 200:
                raise BridgeError('http_status_' + str(response.status))
            if response.getheader('Content-Type', '').split(';')[0].strip() != 'application/json':
                raise BridgeError('unexpected_content_type')
            raw = response.read(self.MAX_JSON_BYTES + 1)
            if len(raw) > self.MAX_JSON_BYTES:
                raise BridgeError('oversized_response')
            result = json.loads(raw, parse_constant=_invalid_constant)
            if time.monotonic() >= deadline:
                raise BridgeError('request_deadline')
            if not isinstance(result, dict) or result.get('ok') is not True:
                raise BridgeError('invalid_response')
            if method == 'GET' and path == '/control/capabilities':
                self._guarded_negotiated = False
                validate_guarded_capabilities(result)
                self._guarded_negotiated = True
            return result
        except BridgeError:
            raise
        except Exception:
            raise BridgeError('request_failed') from None
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()


def _canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def validate_guarded_request(body: dict) -> None:
    if not isinstance(body, dict):
        raise BridgeError('invalid_guarded_request')
    action = body.get('action')
    fields = {'guard_schema_version', 'action', 'expected_world_generation', 'expected_player_uuid',
              'expected_target_uuid', 'expected_crosshair_uuid', 'ttl_ms'}
    if action == 'look':
        fields |= {'yaw', 'pitch'}
    elif action != 'attack':
        raise BridgeError('invalid_guarded_action')
    if set(body) != fields or type(body.get('guard_schema_version')) is not int or body['guard_schema_version'] != 1:
        raise BridgeError('invalid_guarded_schema')
    if any(not _canonical_uuid(body[k]) for k in ('expected_world_generation', 'expected_player_uuid', 'expected_target_uuid')):
        raise BridgeError('invalid_guarded_identity')
    crosshair = body['expected_crosshair_uuid']
    if crosshair is not None and not _canonical_uuid(crosshair):
        raise BridgeError('invalid_guarded_crosshair')
    if type(body['ttl_ms']) is not int or not 1 <= body['ttl_ms'] <= 250:
        raise BridgeError('invalid_guarded_ttl')
    if action == 'attack' and crosshair != body['expected_target_uuid']:
        raise BridgeError('guarded_attack_requires_target_crosshair')
    if action == 'look' and (any(type(body[k]) not in (int, float) or not math.isfinite(body[k]) for k in ('yaw', 'pitch'))
                             or not -180 <= body['yaw'] < 180 or not -90 <= body['pitch'] <= 90):
        raise BridgeError('invalid_guarded_angles')


def validate_guarded_capabilities(data: dict) -> None:
    _protocol(data)
    guard = data.get('guarded_actions', {})
    expected = {'schema_version': 1, 'enabled': True, 'max_ttl_ms': 250,
                'max_range': 2.75, 'max_yaw_step': 30.0, 'max_pitch_step': 20.0,
                'local_unpublished_survival_only': True, 'single_flight': True,
                'synchronous_attack_attempt': True, 'held_input': False, 'unenchanted_axe_only': True}
    if not isinstance(guard, dict) or any(guard.get(k) != v or
            (type(v) in (bool, int) and type(guard.get(k)) is not type(v)) for k, v in expected.items()):
        raise BridgeError('guarded_capabilities_unsupported_or_disabled')
    targets = guard.get('allowed_target_types')
    if not isinstance(targets, list) or len(targets) != len(HOSTILE_TYPES) or set(targets) != HOSTILE_TYPES:
        raise BridgeError('guarded_target_allowlist_mismatch')


def _number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise BridgeError('invalid_number')
    return float(value)


def _integer(value: Any) -> int:
    if type(value) is not int:
        raise BridgeError('invalid_integer')
    return value


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise BridgeError('invalid_boolean')
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise BridgeError('invalid_identifier')
    return value


def _vector(data: dict) -> Vec3:
    return Vec3(*(_number(data[k]) for k in ('x', 'y', 'z')))


def _protocol(data: dict) -> None:
    if data.get('ok') is not True or data.get('protocol') != 'mineclient-bridge' or data.get('schema_version') != 2:
        raise BridgeError('unsupported_protocol')


def _identity(status: dict) -> tuple[str, int, str, str]:
    _protocol(status)
    if status.get('in_world') is not True or status.get('bridge_running') is not True:
        raise BridgeError('not_in_world')
    return (_text(status['run_id']), _integer(status['process_id']),
            _text(status['player']['uuid']), _text(status['world']['dimension']))


# A deliberately small vanilla floor set, not an inference that no hazard tags
# means safe. Modded blocks, leaves, ice, slabs, stairs and fall-through blocks fail.
SAFE_FLOORS = frozenset('minecraft:' + item for item in (
    'stone', 'dirt', 'grass_block', 'cobblestone', 'deepslate', 'cobbled_deepslate',
    'andesite', 'diorite', 'granite', 'sandstone', 'smooth_stone', 'bricks',
    'stone_bricks', 'oak_planks', 'spruce_planks', 'birch_planks', 'jungle_planks',
    'acacia_planks', 'dark_oak_planks', 'mangrove_planks', 'cherry_planks',
))
AIR_BLOCKS = frozenset({'minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'})


def terrain_check(terrain: dict, state: dict) -> tuple[bool, str]:
    """Check one complete 45-cell scan. Never accumulates stale scan pages."""
    _protocol(terrain)
    world = state['world']
    if (terrain.get('terrain_schema_version') != 1
            or terrain.get('world_generation') != world.get('world_generation')
            or not terrain.get('world_generation') or terrain.get('dimension') != world['dimension']):
        return False, 'terrain_identity_mismatch'
    if abs(_integer(terrain['game_time']) - _integer(world['game_time'])) > 2:
        return False, 'terrain_stale_tick'
    if (terrain.get('complete') is not True or terrain.get('next_cursor') is not None
            or terrain.get('returned') != 45 or terrain.get('total_cells') != 45):
        return False, 'terrain_incomplete'
    origin = tuple(math.floor(_number(state['player'][k])) for k in ('x', 'y', 'z'))
    if tuple(_integer(terrain['origin'][k]) for k in ('x', 'y', 'z')) != origin:
        return False, 'terrain_origin_mismatch'
    # Full-block standing only. Fractional height means stairs/slabs/uncertain pose.
    if abs(state['player']['y'] - origin[1]) > 0.03:
        return False, 'terrain_standing_height_uncertain'
    cells = terrain['cells']
    if not isinstance(cells, list) or len(cells) != 45:
        return False, 'terrain_incomplete'
    indexed = {}
    for cell in cells:
        coord = tuple(_integer(cell[k]) for k in ('x', 'y', 'z'))
        if coord in indexed:
            return False, 'terrain_duplicate_cell'
        indexed[coord] = cell
    ox, oy, oz = origin
    expected = {(x, y, z) for x in range(ox - 1, ox + 2)
                for y in range(oy - 2, oy + 3) for z in range(oz - 1, oz + 2)}
    if set(indexed) != expected:
        return False, 'terrain_coverage_mismatch'
    for (x, y, z), cell in indexed.items():
        if cell.get('status') != 'loaded' or cell.get('known') is not True:
            return False, 'terrain_unloaded_or_unknown'
        if y < oy - 1:
            continue  # Below a verified solid full-support floor.
        if (cell.get('collision_known') is not True or cell.get('hazards') != []
                or cell.get('id_truncated') is not False or cell.get('fluid_truncated') is not False
                or cell.get('fluid') != 'minecraft:empty' or cell.get('properties_truncated') is not False):
            return False, 'terrain_hazard_or_uncertain'
        if y == oy - 1:
            if (cell.get('id') not in SAFE_FLOORS or cell.get('full_top_support') is not True
                    or cell.get('collision_empty') is not False
                    or cell.get('collision_bounds') != [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]):
                return False, 'terrain_unsupported_floor'
        elif cell.get('id') not in AIR_BLOCKS or cell.get('collision_empty') is not True:
            return False, 'terrain_obstruction_or_hazard'
    return True, 'flat_vanilla_test_area'


class MineClientBridge:
    def __init__(self, transport: JsonTransport, expected_identity: tuple[str, int, str, str],
                 clock: Clock | None = None):
        self.transport = transport
        self.expected_identity = expected_identity
        self.clock = clock or RealClock()
        self._guarded_ready = False
        self._last_snapshot = None

    def prepare_guarded(self) -> None:
        """Read-only preflight. Caller must separately authorize local acceptance."""
        self._guarded_ready = False
        self._last_snapshot = None
        capabilities = self.transport.request('GET', '/control/capabilities')
        validate_guarded_capabilities(capabilities)
        self._guarded_ready = True

    def observe(self) -> Snapshot:
        started = self.clock.monotonic()
        before = self.transport.request('GET', '/control/status')
        identity = _identity(before)
        if identity != self.expected_identity:
            raise BridgeError('unexpected_session')
        terrain = self.transport.request('GET', '/control/terrain?radius=1&vertical=2&limit=128')
        state = self.transport.request('GET', '/control/state?radius=16')
        after = self.transport.request('GET', '/control/status')
        _protocol(state)
        if _identity(after) != identity:
            raise BridgeError('session_changed_during_observation')
        p, world, nearby = state['player'], state['world'], state['nearby']
        if (_text(p['uuid']) != identity[2] or _text(world['dimension']) != identity[3]
                or p['dimension'] != identity[3]):
            raise BridgeError('state_identity_mismatch')
        generation = world.get('world_generation')
        if not generation or before['world'].get('world_generation') != generation or after['world'].get('world_generation') != generation:
            raise BridgeError('world_generation_unknown_or_changed')
        before_tick, state_tick, after_tick = (_integer(x['world']['game_time']) for x in (before, state, after))
        if not before_tick <= state_tick <= after_tick or after_tick - before_tick > 3:
            raise BridgeError('inconsistent_observation_ticks')
        safe, reason = terrain_check(terrain, state)
        inventory = p['inventory']
        selected = _integer(p['selected_slot'])
        if not 0 <= selected <= 8 or not isinstance(inventory, list):
            raise BridgeError('invalid_inventory')
        selected_items = [i for i in inventory if i.get('slot') == selected]
        if len(selected_items) != 1:
            raise BridgeError('missing_selected_item')
        item = selected_items[0]
        weapon = '' if item['empty'] is True else _text(item['id'])
        entities = tuple(Entity(_text(e['uuid']), _text(e['type']), _vector(e), _boolean(e['alive']),
                                _number(e['health']) if 'health' in e else None) for e in nearby['entities'])
        if len(entities) > 64 or _integer(nearby['returned']) != len(entities):
            raise BridgeError('invalid_nearby_count')
        crosshair = state['crosshair']
        entity_hit = crosshair.get('type') == 'entity'
        held = False
        screen_open = False
        mouse_grabbed = True
        for status in (before, after):
            screen_open |= _boolean(status['screen']['present'])
            mouse_grabbed &= _boolean(status['mouse']['grabbed'])
            held |= bool(status['held_mappings']) or bool(status['mouse']['held_world_buttons'])
            held |= any(_boolean(status['mouse'][key]) for key in ('left_pressed', 'right_pressed', 'middle_pressed'))
        snapshot = Snapshot(
            captured_at=started, identity=identity, generation=_text(generation), tick=state_tick,
            position=_vector(p), velocity=_vector(p['velocity']), yaw=_number(p['yaw']), pitch=_number(p['pitch']),
            health=_number(p['health']), food=_integer(p['food']), air=_integer(p['air']), max_air=_integer(p['max_air']),
            on_ground=_boolean(p['on_ground']), gamemode=_text(p['gamemode']), weapon=weapon, entities=entities,
            crosshair_uuid=_text(crosshair['uuid']) if entity_hit else None,
            crosshair_kind=_text(crosshair['entity_type']) if entity_hit else None,
            crosshair_location=_vector(crosshair['location']) if entity_hit else None,
            screen_open=screen_open, mouse_grabbed=mouse_grabbed, held_inputs=held,
            entities_truncated=_boolean(nearby['truncated']), terrain_safe=safe, terrain_reason=reason,
        )

        self._last_snapshot = snapshot
        return snapshot

    def _guarded(self, action: str, context: ActionContext, yaw=None, pitch=None) -> None:
        if not self._guarded_ready:
            raise BridgeError('guarded_preflight_required')
        snapshot, target = context.snapshot, context.target
        now = self.clock.monotonic()
        if snapshot is not self._last_snapshot or snapshot.identity != self.expected_identity:
            raise BridgeError('unrecognized_action_snapshot')
        if (not math.isfinite(context.deadline) or now >= context.deadline or now < snapshot.captured_at
                or now - snapshot.captured_at > 0.75):
            raise BridgeError('expired_action_context')
        if target not in snapshot.entities or target.kind not in HOSTILE_TYPES or not target.alive or target.health is None or target.health <= 0:
            raise BridgeError('invalid_action_target')
        if snapshot.weapon not in WEAPONS:
            raise BridgeError('guarded_action_requires_vanilla_axe')
        if snapshot.position.distance(target.position) > 2.75:
            raise BridgeError('action_target_out_of_range')
        # TTL starts at server handler receipt. Bound it by local remaining time,
        # but do not claim this controls network delay or an already-started action.
        ttl_ms = min(150, int((context.deadline - now) * 1000))
        if ttl_ms < 1:
            raise BridgeError('expired_action_context')
        body = {
            'guard_schema_version': 1, 'action': action,
            'expected_world_generation': snapshot.generation,
            'expected_player_uuid': snapshot.identity[2],
            'expected_target_uuid': target.uuid,
            'expected_crosshair_uuid': snapshot.crosshair_uuid,
            'ttl_ms': ttl_ms,
        }
        if action == 'look':
            if abs(wrap_yaw(yaw - snapshot.yaw)) > 30 or abs(pitch - snapshot.pitch) > 20:
                raise BridgeError('guarded_look_step_too_large')
            body.update(yaw=yaw, pitch=pitch)
        validate_guarded_request(body)
        # Consume context before sending: even an ambiguous result must never be
        # replayed from the same observation. Controller stops on all such errors.
        self._last_snapshot = None
        result = self.transport.request('POST', '/control/guarded-action', body)
        _protocol(result)
        expected = {'guard_schema_version': 1, 'action': action, 'dispatched': True,
                    'damage_confirmed': False, 'world_generation': snapshot.generation,
                    'player_uuid': snapshot.identity[2], 'target_uuid': target.uuid}
        if any(result.get(k) != v or (type(v) is bool and type(result.get(k)) is not bool)
               for k, v in expected.items()):
            raise BridgeError('guarded_response_mismatch')
        result_yaw, result_pitch = _number(result['yaw']), _number(result['pitch'])
        # Minecraft may retain an unwrapped yaw after an attack; Java float
        # rounding may also return +180 for a look requested just below +180.
        # Finiteness is checked above; compare look angles modulo 360 below.
        if not -90 <= result_pitch <= 90:
            raise BridgeError('guarded_response_invalid_angles')
        if action == 'look' and (abs(wrap_yaw(result_yaw-yaw)) > 0.001 or abs(result_pitch-pitch) > 0.001):
            raise BridgeError('guarded_look_result_mismatch')

    def look(self, yaw: float, pitch: float, context: ActionContext) -> None:
        self._guarded('look', context, yaw=yaw, pitch=pitch)

    def attack(self, context: ActionContext) -> None:
        self._guarded('attack', context)

    def release_all(self) -> bool:
        """Compatibility cleanup hook: guarded actions cannot hold input.

        Only verify neutral input; never fall back to unguarded release-all.
        A false result needs explicit operator handling, not another legacy POST.
        """
        self._last_snapshot = None
        status = self.transport.request('GET', '/control/status')
        _protocol(status)
        if status.get('process_id') != self.expected_identity[1] or status.get('run_id') != self.expected_identity[0]:
            return False
        return (status.get('held_mappings') == [] and status.get('mouse', {}).get('held_world_buttons') == []
                and all(status.get('mouse', {}).get(k) is False for k in ('left_pressed', 'right_pressed', 'middle_pressed')))
