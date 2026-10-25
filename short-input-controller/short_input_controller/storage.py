"""One cooperating local process, crash-durable writes, no UNKNOWN reset API."""
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import tempfile


class Refused(RuntimeError):
    """Sanitized public error; never include credentials or response contents."""


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refused('duplicate JSON key')
            result[key] = value
        return result
    def constant(_):
        raise Refused('nonfinite JSON')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        def finite(v):
            if isinstance(v, float) and not math.isfinite(v):
                raise Refused('nonfinite JSON')
            if isinstance(v, dict):
                for x in v.values(): finite(x)
            elif isinstance(v, list):
                for x in v: finite(x)
        finite(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Refused('invalid JSON') from None


def encode(value):
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


class Ledger:
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = self.directory.lstat()
        if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077 or st.st_uid != os.getuid():
            raise Refused('ledger directory must be private and user-owned')
        self.lock_fd = os.open(self.directory / 'owner.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.lock_fd)
            self.lock_fd = None
            raise Refused('another local owner holds the ledger') from None
        self.path = self.directory / 'ledger.json'
        try:
            if self.path.exists():
                fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as stream:
                    meta = os.fstat(stream.fileno())
                    if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) & 0o077 or meta.st_uid != os.getuid(): raise Refused('ledger must be private and user-owned')
                    raw = stream.read(self.MAX_BYTES + 1)
                if len(raw) > self.MAX_BYTES:
                    raise Refused('ledger exceeds bound')
                self.data = strict_json(raw)
                if not isinstance(self.data, dict) or set(self.data) != {'version', 'endpoint', 'actions', 'unknown_lock'} or type(self.data['version']) is not int or self.data['version'] != 1 or not isinstance(self.data['actions'], dict) or type(self.data['unknown_lock']) is not bool:
                    raise Refused('invalid ledger; preserve it for inspection')
                for action_id, record in self.data['actions'].items():
                    if not isinstance(record,dict) or record.get('state') not in ('PENDING','UNKNOWN','CLOSED') or not isinstance(record.get('request'),dict) or record['request'].get('id') != action_id or not isinstance(record.get('evidence'),list) or not isinstance(record.get('unknown_reasons'),list) or type(record.get('stop_attempted')) is not bool: raise Refused('invalid original action record')
                    if record['state'] == 'UNKNOWN': self.data['unknown_lock'] = True
                    if record['state'] == 'PENDING':
                        record['state'] = 'UNKNOWN'
                        record['unknown_reasons'].append('restart_with_unsettled_original')
                        self.data['unknown_lock'] = True
                self.save()
            else:
                self.data = {'version': 1, 'endpoint': None, 'actions': {}, 'unknown_lock': False}
                self.save()
        except BaseException:
            self.close()
            raise

    def save(self):
        raw = encode(self.data)
        if len(raw) > self.MAX_BYTES:
            raise Refused('ledger capacity exhausted; no dispatch')
        fd, temp = tempfile.mkstemp(prefix='.ledger-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
            dfd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(dfd)
            finally: os.close(dfd)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
