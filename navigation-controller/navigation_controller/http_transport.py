"""Optional, explicitly configured loopback HTTP transport. No automatic execution.

Source and mocked tests do not establish live navigation acceptance. The caller
supplies the token in memory; this module never discovers or persists credentials.
Writes require two independent opt-ins and only allow the guarded one-sample/yaw
contracts, with at most one admitted POST per transport instance. A movement duration is an admission lease, never held-key travel time.
There are no retries, redirects, proxy support, DNS lookups or legacy input calls.

The timer shuts down the local socket at the total operation deadline, including
slow response headers/body; socket timeouts additionally bound individual waits.
This is not a hard real-time guarantee under arbitrary OS/thread scheduling.
Closing a socket cannot retract a delivered action, brake motion, or verify game
cleanup. Any failed action exchange remains ambiguous to the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import json
import math
import re
import socket
import struct
import threading
import time


MAX_JSON_BYTES = 256 * 1024
_BASE_URL = re.compile(r'http://(127\.0\.0\.1|\[::1\]):([1-9][0-9]{0,4})')
_UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
_TERRAIN = re.compile(r'/control/terrain\?radius=(0|[1-9][0-9]?)&vertical=(0|[1-9])&limit=([1-9][0-9]{0,2})')
_CURSOR = re.compile(r'/control/terrain\?cursor=(' + _UUID + r'):([1-9][0-9]{0,4})')
_READ_PATHS = frozenset(('/control/capabilities', '/control/status',
                         '/control/state?radius=0', '/control/state?radius=4'))
_WRITE_PATHS = frozenset(('/control/guarded-movement', '/control/guarded-turn'))
_IDENTITIES = frozenset(('session', 'request_id', 'observation_id',
                         'expected_world_generation', 'expected_player_uuid'))
_COMMON_FIELDS = _IDENTITIES | frozenset(('action', 'expected_tick', 'expected_x',
                                        'expected_y', 'expected_z', 'expected_yaw', 'ttl_ms'))


class TransportError(ValueError):
    """Sanitized transport failure; never contains server body or credentials."""


@dataclass(frozen=True)
class LoopbackConfig:
    base_url: str
    token: str = field(repr=False)
    enabled: bool = False
    acceptance_verified: bool = False
    timeout_s: float = 0.5
    _host: str = field(init=False, repr=False)
    _port: int = field(init=False, repr=False)

    def __post_init__(self):
        match = _BASE_URL.fullmatch(self.base_url) if type(self.base_url) is str else None
        if match is None or not 1 <= int(match[2]) <= 65535:
            raise TransportError('invalid_loopback_base_url')
        # RFC 6750 token syntax also excludes CR/LF and all header injection.
        if (type(self.token) is not str or not 1 <= len(self.token) <= 4096
                or re.fullmatch(r'[A-Za-z0-9._~+/-]+=*', self.token) is None):
            raise TransportError('invalid_caller_token')
        if type(self.enabled) is not bool or type(self.acceptance_verified) is not bool:
            raise TransportError('invalid_transport_flags')
        if (type(self.timeout_s) not in (int, float)
                or not 0.05 <= self.timeout_s <= 2.0):
            raise TransportError('invalid_transport_timeout')
        object.__setattr__(self, '_host', match[1].strip('[]'))
        object.__setattr__(self, '_port', int(match[2]))


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise TransportError('invalid_request_integer')
    return value


def _number(value, low, high, *, exclude_high=False):
    # Check the bounded value before conversion so arbitrarily large ints fail safely.
    if (type(value) not in (int, float) or not low <= value <= high
            or (exclude_high and value == high)):
        raise TransportError('invalid_request_number')
    return float(value)


def _validate_body(path, body):
    movement = path == '/control/guarded-movement'
    fields = _COMMON_FIELDS | ({'movement_schema_version', 'duration_ms'} if movement
                              else {'turn_schema_version', 'target_yaw'})
    if type(body) is not dict:
        raise TransportError('invalid_request_fields')
    # Snapshot the exact plain dictionary before validating/serializing it.
    body = body.copy()
    if body.keys() != fields:
        raise TransportError('invalid_request_fields')
    schema = 'movement_schema_version' if movement else 'turn_schema_version'
    _integer(body[schema], 1, 1)
    if type(body['action']) is not str or body['action'] != ('forward_sample' if movement else 'yaw'):
        raise TransportError('invalid_request_action')
    for key in _IDENTITIES:
        if type(body[key]) is not str or re.fullmatch(_UUID, body[key]) is None:
            raise TransportError('invalid_request_identity')
    _integer(body['expected_tick'], 0, 9_007_199_254_740_991)
    for key in ('expected_x', 'expected_y', 'expected_z'):
        _number(body[key], -30_000_000, 30_000_000)
    yaw = _number(body['expected_yaw'], -180, 180, exclude_high=True)
    ttl = _integer(body['ttl_ms'], 1, 250 if movement else 100)
    if movement:
        _integer(body['duration_ms'], 1, min(100, ttl))
    else:
        target = _number(body['target_yaw'], -180, 180, exclude_high=True)
        applied = struct.unpack('!f', struct.pack('!f', target))[0]
        if applied >= 180:
            applied -= 360
        if abs((applied - yaw + 180) % 360 - 180) > 30:
            raise TransportError('invalid_request_turn_step')
    return json.dumps(body, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _validate_read(path):
    if path in _READ_PATHS:
        return
    match = _TERRAIN.fullmatch(path)
    if match is not None:
        _integer(int(match[1]), 0, 16)
        _integer(int(match[2]), 0, 8)
        _integer(int(match[3]), 1, 128)
        return
    match = _CURSOR.fullmatch(path)
    if match is not None:
        _integer(int(match[2]), 1, 18513)
        return
    raise TransportError('read_not_allowlisted')


def _reject_constant(_):
    raise TransportError('invalid_response_json')


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise TransportError('invalid_response_json')
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TransportError('invalid_response_json')
        result[key] = value
    return result


def _response_json(raw):
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant, parse_float=_finite_float)
        if type(result) is not dict:
            raise TransportError('invalid_response_json')
        return result
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise TransportError('invalid_response_json') from None


class _NumericLoopbackConnection(http.client.HTTPConnection):
    """HTTP framing from stdlib; direct numeric sockets instead of getaddrinfo."""

    def __init__(self, host, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._socket_lock = threading.Lock()
        self._deadline_socket = None
        self._aborted = False

    def connect(self):
        family = socket.AF_INET6 if self.host == '::1' else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        with self._socket_lock:
            if self._aborted:
                sock.close()
                raise TransportError('operation_deadline')
            self.sock = self._deadline_socket = sock
        sock.settimeout(self.timeout)
        address = (self.host, self.port, 0, 0) if family == socket.AF_INET6 else (self.host, self.port)
        sock.connect(address)

    def set_remaining_timeout(self, seconds):
        self.timeout = seconds
        # getresponse() may clear HTTPConnection.sock for Connection: close while
        # HTTPResponse still owns the file object. Retain its socket for shutdown.
        with self._socket_lock:
            sock = self._deadline_socket
        if sock is not None:
            sock.settimeout(seconds)

    def abort(self):
        with self._socket_lock:
            self._aborted = True
            sock = self._deadline_socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                try:
                    sock.close()
                except OSError:
                    pass


def _validate_headers(response):
    headers = {}
    for key, value in response.getheaders():
        key = key.lower()
        if key in ('content-type', 'content-length', 'content-encoding', 'transfer-encoding'):
            if key in headers:
                raise TransportError('invalid_response_headers')
            headers[key] = value.strip().lower()
    if re.fullmatch(r'application/json(?:;\s*charset=utf-8)?', headers.get('content-type', '')) is None:
        raise TransportError('invalid_response_content_type')
    if headers.get('content-encoding', 'identity') != 'identity':
        raise TransportError('invalid_response_encoding')
    if headers.get('transfer-encoding', 'chunked') != 'chunked':
        raise TransportError('invalid_response_encoding')
    if 'content-length' in headers:
        length = headers['content-length']
        if 'transfer-encoding' in headers or re.fullmatch(r'[0-9]{1,6}', length) is None:
            raise TransportError('invalid_response_length')
        if int(length) > MAX_JSON_BYTES:
            raise TransportError('response_too_large')
        return int(length)
    return None


class LoopbackHttpTransport:
    """Explicitly constructed transport. Construction itself does not connect."""

    simulation_only = False

    def __init__(self, config: LoopbackConfig):
        if type(config) is not LoopbackConfig:
            raise TransportError('invalid_transport_config')
        self.config = config
        self._state_lock = threading.Lock()
        self._inflight = threading.Lock()
        self._closed = False
        self._post_consumed = False
        self._active = None

    def close(self):
        """Permanently close local admission and sockets; send no cancellation.

        An already delivered action may still execute. This is not release-all,
        cleanup confirmation, or braking. The caller must treat it as ambiguous.
        """
        with self._state_lock:
            self._closed = True
            active = self._active
        if active is not None:
            active.abort()

    def stop(self):
        self.close()

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        with self._state_lock:
            if self._closed:
                raise TransportError('transport_closed')
        if type(method) is not str or type(path) is not str:
            raise TransportError('invalid_request_type')
        if method == 'GET':
            if body is not None:
                raise TransportError('get_body_forbidden')
            _validate_read(path)
            payload = None
        elif method == 'POST':
            if not self.config.enabled or not self.config.acceptance_verified:
                raise TransportError('mutation_not_accepted')
            if path not in _WRITE_PATHS:
                raise TransportError('write_not_allowlisted')
            payload = _validate_body(path, body)
        else:
            raise TransportError('method_not_allowlisted')
        if not self._inflight.acquire(blocking=False):
            raise TransportError('transport_busy')
        connection = response = timer = None
        timer_started = False
        expired = threading.Event()
        deadline = time.monotonic() + self.config.timeout_s
        try:
            with self._state_lock:
                if self._closed:
                    raise TransportError('transport_closed')
                if method == 'POST':
                    if self._post_consumed:
                        raise TransportError('single_action_budget_exhausted')
                    # Commit admission before constructing/dispatching anything.
                    # Errors, timeouts and ambiguous outcomes never refund it.
                    self._post_consumed = True
            connection = _NumericLoopbackConnection(self.config._host, self.config._port,
                                                    self.config.timeout_s)
            with self._state_lock:
                if self._closed:
                    raise TransportError('transport_closed')
                self._active = connection

            def expire():
                expired.set()
                connection.abort()

            def remaining(*, update_timeout=True):
                seconds = deadline - time.monotonic()
                with self._state_lock:
                    closed = self._closed
                if closed:
                    raise TransportError('transport_closed')
                if expired.is_set() or seconds <= 0:
                    raise TransportError('operation_deadline')
                if update_timeout:
                    connection.set_remaining_timeout(seconds)

            timer = threading.Timer(max(0, deadline - time.monotonic()), expire)
            timer.daemon = True
            timer.start()
            timer_started = True
            remaining()
            headers = {'Authorization': 'Bearer ' + self.config.token,
                       'Accept': 'application/json', 'Connection': 'close'}
            if payload is not None:
                headers['Content-Type'] = 'application/json'
            connection.request(method, path, body=payload, headers=headers)
            remaining()
            response = connection.getresponse()
            remaining()
            if type(response.status) is not int or response.status != 200:
                # Do not read/include error bodies or follow any Location header.
                error = TransportError('unexpected_http_status')
                if type(response.status) is int and 100 <= response.status <= 599:
                    error.http_status = response.status
                raise error
            expected_length = _validate_headers(response)
            raw = response.read(MAX_JSON_BYTES + 1)
            remaining(update_timeout=False)
            if type(raw) is not bytes:
                raise TransportError('invalid_response_type')
            if len(raw) > MAX_JSON_BYTES:
                raise TransportError('response_too_large')
            if expected_length is not None and len(raw) != expected_length:
                raise TransportError('truncated_response')
            result = _response_json(raw)
            remaining(update_timeout=False)
            return result
        except TransportError:
            raise
        except Exception:
            # In particular, HTTP/socket exceptions can contain peer-controlled
            # bytes. Never put them (or the bearer header) in user-visible errors.
            raise TransportError('request_failed') from None
        finally:
            if timer is not None:
                timer.cancel()
                # The callback performs no blocking I/O; joining prevents stale
                # cleanup callbacks surviving into a future request.
                if timer_started:
                    timer.join()
            # Cleanup failures must not replace a sanitized error with raw peer
            # or socket details, nor strand local admission in the busy state.
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass
            with self._state_lock:
                self._active = None
            self._inflight.release()
