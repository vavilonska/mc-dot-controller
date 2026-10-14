"""Small authenticated loopback transport. No credential discovery or retries."""
from __future__ import annotations

import http.client
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit

from .capability_snapshot import source_freshness
from .movement_wire import MARKER as MOVEMENT_WIRE_MARKER, load_strict, retain, valid_size_diagnostic

READS = {'/control/status', '/control/capabilities', '/control/state', '/control/screen',
         '/control/keymaps', '/control/terrain', '/control/action/status', '/control/frame',
         '/control/scan/status', '/control/capability-snapshot'}
DIRECT = {'key', 'raw-key', 'look', 'mouse', 'text', 'command', 'release-all'}
WRITES = {'/control/' + x for x in DIRECT} | {
    '/control/pause', '/control/action', '/control/scoped-action', '/control/action/cancel', '/control/scan', '/control/scan/cancel'}
ACQUISITION_ROOT = '/control/terrain-acquisition/v1/'
ACQUISITION_READS = {ACQUISITION_ROOT + k for k in ('status', 'fetch')}
ACQUISITION_WRITES = {ACQUISITION_ROOT + k for k in ('prepare', 'activate', 'cancel')}
READS |= ACQUISITION_READS
WRITES |= ACQUISITION_WRITES


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_acquisition_json_key')
        result[key] = value
    return result


def _acquisition_request(method, route, body):
    """Exact new wire surface. Legacy parsing and transport costs stay unchanged."""
    identifier = lambda v: type(v) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', v) is not None
    digest = lambda v: type(v) is str and re.fullmatch(r'[0-9a-f]{64}', v) is not None
    operation = route.path.removeprefix(ACQUISITION_ROOT)
    if method == 'GET' and route.path in ACQUISITION_READS and body is None:
        pairs = parse_qsl(route.query, keep_blank_values=True, strict_parsing=True)
        data = _unique_object(pairs)
        expected = {'job_id', 'owner_id'} | ({'part', 'sha256'} if operation == 'fetch' else set())
        valid = (set(data) == expected and identifier(data.get('job_id')) and identifier(data.get('owner_id')))
        if operation == 'fetch':
            valid = valid and data['part'] in ('a', 'p0', 'p1', 'p2', 'p3', 'c') and digest(data['sha256'])
    elif method == 'POST' and route.path in ACQUISITION_WRITES and not route.query and type(body) is dict:
        expected = {'acquisition_schema_version', 'job_id', 'owner_id'} | {
            'prepare': {'defense_epoch', 'radius', 'vertical', 'entity_radius'},
            'activate': {'a_sha256'}, 'cancel': {'cancel_id'}}[operation]
        if operation == 'prepare' and body.get('acquisition_schema_version') == 2:
            expected |= {'observation_clock'}
        valid = (set(body) == expected and type(body.get('acquisition_schema_version')) is int
                 and body['acquisition_schema_version'] in (1,2) and identifier(body.get('job_id'))
                 and identifier(body.get('owner_id')))
        if operation == 'prepare':
            valid = valid and (body['acquisition_schema_version'] != 2 or body.get('observation_clock') == 'client-pre-tick-v1')
            valid = valid and all(type(body.get(k)) is int and body[k] == v
                                  for k, v in (('radius', 4), ('vertical', 4), ('entity_radius', 48)))
            valid = valid and (body.get('defense_epoch') is None or type(body['defense_epoch']) is int
                              and 0 <= body['defense_epoch'] <= 2**53-1)
        elif operation == 'activate':
            valid = valid and digest(body.get('a_sha256'))
        else:
            valid = valid and identifier(body.get('cancel_id')) and body['cancel_id'] == body['job_id']
    else:
        valid = False
    if not valid:
        raise ValueError('invalid_acquisition_request')


def _embedded_metadata(raw, names, raw_values=None):
    """Hash the exact UTF-8 JSON value span, never a reserialized Python object."""
    text = raw.decode('utf-8')
    decoder = json.JSONDecoder(object_pairs_hook=_unique_object,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    position = len(text) - len(text.lstrip())
    if text[position:position + 1] != '{':
        raise ValueError('invalid_acquisition_prepare')
    position += 1
    metadata = {}
    while True:
        while position < len(text) and text[position].isspace(): position += 1
        if text[position:position + 1] == '}': break
        key, position = decoder.raw_decode(text, position)
        while position < len(text) and text[position].isspace(): position += 1
        if text[position:position + 1] != ':': raise ValueError('invalid_acquisition_prepare')
        position += 1
        while position < len(text) and text[position].isspace(): position += 1
        start = position
        _, position = decoder.raw_decode(text, position)
        if key in names:
            encoded = text[start:position].encode('utf-8')
            metadata['embedded_' + key + '_sha256'] = hashlib.sha256(encoded).hexdigest()
            metadata['embedded_' + key + '_bytes'] = len(encoded)
            if raw_values is not None:
                raw_values[key] = encoded
        while position < len(text) and text[position].isspace(): position += 1
        if text[position:position + 1] == '}': break
        if text[position:position + 1] != ',': raise ValueError('invalid_acquisition_prepare')
        position += 1
    if any('embedded_' + key + '_bytes' not in metadata for key in names):
        raise ValueError('missing_acquisition_embedded_value')
    return metadata


class BridgeError(RuntimeError):
    def __init__(self, code, *, uncertain=False, status=None, capability_source_freshness=None, capability_source_freshness_status=None,
                 scoped_movement_response_size=None, scoped_movement_response_size_status=None):
        super().__init__(code)
        self.code, self.uncertain, self.status = code, uncertain, status
        self.capability_source_freshness = capability_source_freshness
        self.capability_source_freshness_status = capability_source_freshness_status
        self.scoped_movement_response_size = scoped_movement_response_size
        self.scoped_movement_response_size_status = scoped_movement_response_size_status


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def read_server_timing(response):
    """Reported native phase offsets; never used as freshness or retry authority."""
    getter = getattr(response, 'getheader', None)
    if not callable(getter):
        return None
    try:
        version = getter('X-MDC-Read-Timing-Version')
        if version is None:
            return None
        if version != '1':
            return {'status': 'unsupported_version'}
        phases = ('Dispatch', 'Client-Start', 'Client-End', 'Encode-Start', 'Encode-End')
        offsets = {}
        for phase in phases:
            value = getter('X-MDC-' + phase + '-Offset-Nanos')
            if value is None:
                continue
            if not isinstance(value, str) or re.fullmatch(r'[0-9]{1,19}', value) is None or int(value) > 2**63-1:
                return {'status': 'invalid_offset'}
            offsets[phase.lower().replace('-', '_')] = int(value)
        sequence = list(offsets.values())
        if any(a > b for a, b in zip(sequence, sequence[1:])):
            return {'status': 'invalid_order'}
        reported = getter('X-MDC-Read-Timing-Status')
        if reported not in ('complete', 'partial') or (reported == 'complete' and len(offsets) != 5):
            return {'status': 'invalid_completeness'}
        def interval(first, last):
            return None if first not in offsets or last not in offsets else (offsets[last] - offsets[first]) / 1_000_000
        result = {'schema_version': 1, 'status': 'reported_' + reported,
            'clock': 'java_system_nano_time', 'origin': 'http_handler_entry_not_socket_arrival',
            'offsets_ns': offsets, 'dispatch_to_client_operation_ms': interval('dispatch', 'client_start'),
            'client_operation_ms': interval('client_start', 'client_end'),
            'client_end_to_encoding_ms': interval('client_end', 'encode_start'),
            'json_encoding_ms': interval('encode_start', 'encode_end'),
            'through_encoding_ms': offsets.get('encode_end', 0) / 1_000_000 if 'encode_end' in offsets else None,
            'includes_socket_write_or_transport': False}
        fps = getter('X-MDC-Client-Fps')
        if isinstance(fps, str) and re.fullmatch(r'[0-9]{1,6}', fps):
            result['client_reported_fps'] = int(fps)
        for name in ('Focused', 'Paused'):
            value = getter('X-MDC-Client-' + name)
            if value in ('true', 'false'):
                result['client_' + name.lower()] = value == 'true'
        return result
    except Exception:
        return {'status': 'header_read_failed'}


def read_sample_timing(response):
    """Optional native sampling points. Never an action/rebinding authority."""
    getter = getattr(response, 'getheader', None)
    if not callable(getter):
        return None
    try:
        version = getter('X-MDC-Sample-Timing-Version')
        if version is None:
            return None
        if version != '1':
            return {'status': 'unsupported_version'}
        point = getter('X-MDC-Sample-Point')
        if point not in ('state_world_game_time_read', 'client_actions_start_before_call_not_guard'):
            return {'status': 'invalid_sample_point'}
        def integer(name, signed=False):
            value = getter(name)
            if not isinstance(value, str) or re.fullmatch(r'-?[0-9]{1,19}' if signed else r'[0-9]{1,19}', value) is None:
                raise ValueError('invalid_integer')
            value = int(value)
            if not (-(2**63) if signed else 0) <= value <= 2**63-1:
                raise ValueError('integer_out_of_range')
            return value
        tick = (integer('X-MDC-Sample-Game-Time', True)
                if getter('X-MDC-Sample-Game-Time') is not None else None)
        result = {'schema_version': 1, 'status': 'reported' if tick is not None else 'reported_partial', 'sample_point': point,
                  'nano_time': integer('X-MDC-Sample-Nano-Time', True),
                  'clock': 'java_system_nano_time_same_process_only', 'diagnostics_only': True}
        if tick is not None:
            result['game_time'] = tick
        if getter('X-MDC-Sample-Offset-Nanos') is not None:
            result['sample_offset_ns'] = integer('X-MDC-Sample-Offset-Nanos')
        if getter('X-MDC-Request-Expected-Game-Time') is not None:
            expected = integer('X-MDC-Request-Expected-Game-Time')
            if expected > 2**53-1:
                raise ValueError('expected_tick_out_of_range')
            result['request_expected_game_time'] = expected
            if tick is not None:
                result['sample_minus_expected_ticks'] = tick - expected
        return result
    except Exception:
        return {'status': 'invalid_sample_timing'}


class Bridge:
    """Constructing this object never connects; bearer stays only in memory."""
    def __init__(self, base_url, token, timeout=6.0):
        match = re.fullmatch(r'http://(127\.0\.0\.1|\[::1\]):([0-9]{1,5})', base_url)
        if not match or not 1 <= int(match[2]) <= 65535:
            raise ValueError('base_url_must_be_explicit_numeric_loopback')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._~+/-]{1,4096}=*', token):
            raise ValueError('invalid_bearer')
        self.base_url = base_url
        self.host, self.port = match[1].strip('[]'), int(match[2])
        self._token, self.timeout = token, timeout
        self.last_response_metadata = None
        self.last_capability_wire = None

    def request(self, method, path, body=None):
        # Only actual bytes from this exchange; reset before every request.
        self.last_capability_wire = None
        self.last_response_metadata = {'response_bytes_read': None,
                                       'response_bytes_status': 'unknown', 'http_status': None}
        route = urlsplit(path)
        if route.scheme or route.netloc or route.fragment or not path.startswith('/control/'):
            raise BridgeError('invalid_route')
        acquisition = route.path.startswith(ACQUISITION_ROOT)
        if acquisition:
            try:
                _acquisition_request(method, route, body)
            except (ValueError, TypeError, KeyError):
                raise BridgeError('invalid_acquisition_request') from None
        if method == 'GET' and route.path in READS and body is None:
            payload = None
        elif method == 'POST' and route.path in WRITES and not route.query and isinstance(body, dict):
            payload = json_bytes(body)
            if len(payload) > 64 * 1024:
                raise BridgeError('request_too_large')
        else:
            raise BridgeError('unsupported_request')
        # HTTPConnection neither reads proxy environment variables nor follows redirects.
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            headers = {'Authorization': 'Bearer ' + self._token, 'Accept': 'application/json',
                       'Connection': 'close'}
            if payload is not None:
                headers['Content-Type'] = 'application/json'
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            self.last_response_metadata['http_status'] = response.status
            timing = read_server_timing(response)
            if timing is not None:
                self.last_response_metadata['server_timing'] = timing
            sample = read_sample_timing(response)
            if sample is not None:
                self.last_response_metadata['sample_timing'] = sample
            is_frame = route.path == '/control/frame'
            bound = 32 * 1024 * 1024 if is_frame else 256 * 1024
            if acquisition and route.path.rsplit('/', 1)[-1] in ('status', 'activate', 'cancel'):
                bound = 32 * 1024
            raw = response.read(bound + 1)
            self.last_response_metadata.update(response_bytes_read=len(raw),
                                               response_bytes_status='observed_read_length')
            if len(raw) > bound:
                self.last_response_metadata['response_bytes_status'] = 'limit_exceeded_prefix'
                raise BridgeError('response_too_large', uncertain=method == 'POST')
            if acquisition:
                self.last_response_metadata['response_sha256'] = hashlib.sha256(raw).hexdigest()
            if response.status not in (200, 202):
                # Only a compact machine error code may leave this layer; never raw response text.
                code = 'bridge_http_' + str(response.status)
                freshness = None
                movement_size = None
                try:
                    value = load_strict(raw) if route.path == '/control/scoped-action' else json.loads(raw)
                    candidate = value.get('error') if isinstance(value, dict) else None
                    if isinstance(candidate, str) and re.fullmatch(r'[a-z0-9_]{1,80}', candidate):
                        code = candidate
                    if isinstance(value, dict) and 'capability_source_freshness' in value:
                        valid = source_freshness(value['capability_source_freshness'])
                        self.last_response_metadata['capability_source_freshness_status'] = 'reported' if valid else 'invalid'
                        if valid:
                            freshness = value['capability_source_freshness']
                            self.last_response_metadata['capability_source_freshness'] = freshness
                    if (method == 'POST' and route.path == '/control/scoped-action' and response.status == 409
                            and code == 'scoped_movement_response_evidence_too_large'
                            and isinstance(value, dict) and 'scoped_movement_response_size' in value):
                        valid = valid_size_diagnostic(value['scoped_movement_response_size'])
                        self.last_response_metadata['scoped_movement_response_size_status'] = 'reported' if valid else 'invalid'
                        if valid:
                            movement_size = value['scoped_movement_response_size']
                except (ValueError, UnicodeError):
                    pass
                raise BridgeError(code, status=response.status, capability_source_freshness=freshness,
                                  capability_source_freshness_status=self.last_response_metadata.get('capability_source_freshness_status'),
                                  scoped_movement_response_size=movement_size,
                                  scoped_movement_response_size_status=self.last_response_metadata.get('scoped_movement_response_size_status'),
                                  uncertain=method == 'POST' and response.status >= 500)
            if is_frame:
                if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise BridgeError('invalid_frame')
                return raw
            result = (load_strict(raw) if route.path == '/control/capability-snapshot' else
                      json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                                 **({'object_pairs_hook': _unique_object} if acquisition else {})))
            if not isinstance(result, dict):
                raise ValueError()
            if acquisition and route.path == ACQUISITION_ROOT + 'prepare':
                spans = {}
                self.last_response_metadata.update(_embedded_metadata(raw, ('a', 'manifest'), spans))
                if isinstance(result.get('a'), dict) and MOVEMENT_WIRE_MARKER in result['a']:
                    self.last_capability_wire = retain(spans['a'])
            elif acquisition and route.path == ACQUISITION_ROOT + 'fetch' and dict(parse_qsl(route.query))['part'].startswith('p'):
                self.last_response_metadata.update(_embedded_metadata(raw, ('cells',)))
            if (route.path == '/control/capability-snapshot' or acquisition) and MOVEMENT_WIRE_MARKER in result:
                self.last_capability_wire = retain(raw)
                self.last_response_metadata['response_sha256'] = self.last_capability_wire['sha256']
            return result
        except BridgeError:
            raise
        except Exception:
            raise BridgeError('transport_failed', uncertain=method == 'POST' or acquisition) from None
        finally:
            conn.close()
