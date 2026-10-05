"""Bounded shared-workspace file mailbox. No HTTP or credentials on model side."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
import uuid

from .transport import json_bytes

MAX_COMMAND_BYTES = 64 * 1024
MAX_PENDING = 32
MAX_RESULTS = 256
ID = re.compile(r'[A-Za-z0-9_-]{1,80}')


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(json_bytes(data))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path, limit=MAX_COMMAND_BYTES):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('mailbox_file_too_large')
    data = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(data, dict):
        raise ValueError('mailbox_requires_object')
    return data


class QueueClient:
    def __init__(self, directory):
        self.root = Path(directory)

    def session(self):
        return read_json(self.root / 'session.json')

    def submit(self, command, request_id=None):
        session = self.session()
        if session.get('state') not in ('ready', 'busy', 'paused'):
            raise ValueError('controller_not_running')
        request_id = request_id or uuid.uuid4().hex
        if not ID.fullmatch(request_id):
            raise ValueError('invalid_request_id')
        body = dict(command, request_id=request_id, session_id=session['session_id'], submitted_at=time.time())
        if len(json_bytes(body)) > MAX_COMMAND_BYTES:
            raise ValueError('command_too_large')
        name = request_id + '.json'
        # Caller-chosen repeated IDs observe the original result; they never resubmit a mutation.
        for folder in ('inbox', 'working', 'results'):
            if (self.root / folder / name).exists():
                return request_id
        if len(list((self.root / 'inbox').glob('*.json'))) >= MAX_PENDING:
            raise ValueError('queue_full')
        atomic_json(self.root / 'inbox' / name, body)
        return request_id

    def result(self, request_id):
        if not ID.fullmatch(request_id):
            raise ValueError('invalid_request_id')
        path = self.root / 'results' / (request_id + '.json')
        return read_json(path, 2 * 1024 * 1024) if path.exists() else None

    def wait(self, request_id, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.result(request_id)
            if result is not None:
                return result
            time.sleep(0.1)
        return {'request_id': request_id, 'status': 'pending', 'reason': 'wait_timeout_not_action_failure'}
