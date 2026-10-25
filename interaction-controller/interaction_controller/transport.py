"""Explicit loopback endpoint, no proxies/redirects/retries, bounded receipts."""
from dataclasses import dataclass
import http.client
import math
import time
import socket
import threading
from urllib.parse import urlsplit
from .legacy import Refused, encode

MAX_RESPONSE = 65536


@dataclass(frozen=True)
class RawReply:
    status: int
    body: bytes
    complete: bool = True


class HttpTransport:
    def __init__(self, endpoint, token, timeout=2.0):
        try:
            parsed = urlsplit(endpoint)
            port = parsed.port
        except ValueError:
            raise Refused('invalid endpoint') from None
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1') or not port
                or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise Refused('explicit HTTP loopback IP and port required')
        if not isinstance(token, str) or not token or len(token) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise Refused('invalid selected token')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0.05 <= timeout <= 5:
            raise Refused('invalid timeout')
        self.endpoint = endpoint.rstrip('/')
        self.host, self.port, self._token, self.timeout = parsed.hostname, port, token, timeout

    def request(self, method, path, body=None):
        # The caller supplies only the closed controller paths, never arbitrary URLs.
        if not path.startswith(('/control/recovery-short-input/v1/', '/control/recovery-interaction/v1/')) or method not in ('GET', 'POST'):
            raise Refused('unsupported transport route')
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        received = bytearray()
        status = 0
        active_socket = [None]
        def abort():
            sock = active_socket[0] or conn.sock
            if sock is not None:
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                try: sock.close()
                except OSError: pass
        timer = threading.Timer(self.timeout, abort)
        timer.daemon = True
        timer.start()
        def reply(complete):
            raw = bytes(received[:MAX_RESPONSE])
            # An erroneous endpoint must not persist an echoed authorization secret.
            if self._token.encode('ascii') in raw: return RawReply(status, b'', False)
            return RawReply(status, raw, complete)
        try:
            deadline = time.monotonic() + self.timeout
            conn.request(method, path, body=None if body is None else encode(body), headers={
                'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json', 'Connection': 'close'})
            active_socket[0] = conn.sock
            response = conn.getresponse()
            expected_length = response.length
            status = response.status
            while len(received) <= MAX_RESPONSE:
                remaining = deadline - time.monotonic()
                if remaining <= 0: return reply(False)
                if conn.sock: conn.sock.settimeout(remaining)
                chunk = response.read1(min(4096, MAX_RESPONSE + 1 - len(received)))
                if not chunk: return reply(time.monotonic() < deadline and (expected_length is None or len(received) == expected_length))
                received.extend(chunk)
            return reply(False)
        except (OSError, http.client.HTTPException):
            return reply(False)
        finally:
            timer.cancel()
            conn.close()
