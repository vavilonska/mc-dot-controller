"""Small authenticated loopback transport. No credential discovery or retries."""
from __future__ import annotations

import http.client
import json
import re
from urllib.parse import urlsplit

READS = {'/control/status', '/control/capabilities', '/control/state', '/control/screen',
         '/control/keymaps', '/control/terrain', '/control/action/status', '/control/frame',
         '/control/scan/status'}
DIRECT = {'key', 'raw-key', 'look', 'mouse', 'text', 'command', 'release-all'}
WRITES = {'/control/' + x for x in DIRECT} | {
    '/control/action', '/control/action/cancel', '/control/scan', '/control/scan/cancel'}


class BridgeError(RuntimeError):
    def __init__(self, code, *, uncertain=False, status=None):
        super().__init__(code)
        self.code, self.uncertain, self.status = code, uncertain, status


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


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

    def request(self, method, path, body=None):
        # Only actual bytes from this exchange; reset before every request.
        self.last_response_metadata = {'response_bytes_read': None,
                                       'response_bytes_status': 'unknown', 'http_status': None}
        route = urlsplit(path)
        if route.scheme or route.netloc or route.fragment or not path.startswith('/control/'):
            raise BridgeError('invalid_route')
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
            is_frame = route.path == '/control/frame'
            bound = 32 * 1024 * 1024 if is_frame else 256 * 1024
            raw = response.read(bound + 1)
            self.last_response_metadata.update(response_bytes_read=len(raw),
                                               response_bytes_status='observed_read_length')
            if len(raw) > bound:
                self.last_response_metadata['response_bytes_status'] = 'limit_exceeded_prefix'
                raise BridgeError('response_too_large', uncertain=method == 'POST')
            if response.status not in (200, 202):
                # Only a compact machine error code may leave this layer; never raw response text.
                code = 'bridge_http_' + str(response.status)
                try:
                    value = json.loads(raw)
                    candidate = value.get('error') if isinstance(value, dict) else None
                    if isinstance(candidate, str) and re.fullmatch(r'[a-z0-9_]{1,80}', candidate):
                        code = candidate
                except (ValueError, UnicodeError):
                    pass
                raise BridgeError(code, status=response.status,
                                  uncertain=method == 'POST' and response.status >= 500)
            if is_frame:
                if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise BridgeError('invalid_frame')
                return raw
            result = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except BridgeError:
            raise
        except Exception:
            raise BridgeError('transport_failed', uncertain=method == 'POST') from None
        finally:
            conn.close()
