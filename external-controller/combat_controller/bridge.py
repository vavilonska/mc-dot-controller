"""Read-only loopback HTTP adapter plus fake-test input schema for stage one.

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

from .core import Config, Entity, RealClock, Snapshot, Vec3, Clock


class BridgeError(RuntimeError):
    """Sanitized error; never embeds a response body or credential."""


class JsonTransport(Protocol):
    def request(self, method: str, path: str, body: dict | None = None) -> dict: ...


@dataclass(frozen=True)
class ConnectionConfig:
    base_url: str = 'http://127.0.0.1:38121'
    token: str = field(default='', repr=False)
    enabled: bool = False
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
        if (type(self.enabled) is not bool or type(self.timeout) not in (int, float)
                or not math.isfinite(self.timeout) or not 0.05 <= self.timeout <= 1):
            raise ValueError('invalid connection limits')
        if self.expected_identity is not None:
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
        if not isinstance(data, dict) or set(data) - {'base_url', 'token', 'enabled', 'expected_identity', 'timeout'}:
            raise ValueError('unexpected connection configuration field')
        if data.get('expected_identity') is not None:
            data['expected_identity'] = tuple(data['expected_identity'])
        return cls(**data)


def _invalid_constant(_: str) -> None:
    raise ValueError('non-finite JSON number')


class HttpTransport:
    MAX_JSON_BYTES = 256 * 1024
    READ_PATHS = frozenset({'/control/status', '/control/state?radius=16',
                            '/control/terrain?radius=1&vertical=2&limit=128'})

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._url = urlsplit(config.base_url)

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        if method == 'GET':
            if path not in self.READ_PATHS or body is not None:
                raise BridgeError('read_not_allowlisted')
        elif method == 'POST':
            if not self.config.enabled:
                raise BridgeError('adapter_disabled')
            allowed = (
                (path == '/control/key' and body == {'mapping': 'key.attack', 'action': 'click', 'exact': True})
                or (path == '/control/release-all' and body == {})
                or (path == '/control/look' and isinstance(body, dict) and set(body) == {'yaw', 'pitch', 'relative'}
                    and body['relative'] is False
                    and all(type(body[k]) in (int, float) and math.isfinite(body[k]) for k in ('yaw', 'pitch'))
                    and -180 <= body['yaw'] < 180 and -90 <= body['pitch'] <= 90)
            )
            if not allowed:
                raise BridgeError('input_not_allowlisted')
            # v1.1.5 may run queued input AFTER this client's timeout or a world
            # change. Only a server-side guarded action can close that race.
            # No flag/config can enable real HTTP mutation in this stage.
            raise BridgeError('live_input_requires_guarded_bridge_endpoint')
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
            return result
        except BridgeError:
            raise
        except Exception:
            raise BridgeError('request_failed') from None
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()


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
        return Snapshot(
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

    def look(self, yaw: float, pitch: float) -> None:
        result = self.transport.request('POST', '/control/look', {'yaw': yaw, 'pitch': pitch, 'relative': False})
        if result.get('ok') is not True:
            raise BridgeError('look_failed')

    def attack_click(self) -> None:
        result = self.transport.request('POST', '/control/key', {'mapping': 'key.attack', 'action': 'click', 'exact': True})
        if result.get('ok') is not True or result.get('mapping_down') is not False:
            raise BridgeError('attack_release_unconfirmed')
        delivery = result.get('mod_input_event', {})
        if (delivery.get('probe_installed') is not True or delivery.get('event_fired') is not True
                or delivery.get('event_cancelled_by_mod') is not False):
            raise BridgeError('attack_delivery_unconfirmed_or_cancelled')
        # The acknowledgement proves input delivery only, never damage or a kill.

    def release_all(self) -> bool:
        result = self.transport.request('POST', '/control/release-all', {})
        if result.get('released') is not True:
            return False
        status = self.transport.request('GET', '/control/status')
        # Release remains attempted even after a world change. Do not send actions
        # to a new world; status verification only reports whether input is clear.
        return (not status.get('held_mappings') and not status.get('mouse', {}).get('held_world_buttons')
                and all(status.get('mouse', {}).get(k) is False for k in ('left_pressed', 'right_pressed', 'middle_pressed')))
