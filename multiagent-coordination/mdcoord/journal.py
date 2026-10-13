"""Fsync-before-dispatch journal and one-process-owner flock, on a private local path."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import uuid
import stat

from .schema import require

MAX_JOURNAL_BYTES = 2 * 1024 * 1024


def _fsync_directory(path):
    fd = os.open(path, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_durable_directory(path):
    # Each newly created component must have its entry persisted in its parent.
    # The final path is private; this journal is not intended for shared/untrusted directories.
    path = path.absolute()
    chain = list(reversed((path,) + tuple(path.parents)))
    for component in chain:
        require(not component.is_symlink(), 'journal_symlink')
        if not component.exists():
            component.mkdir(mode=0o700)
        require(component.is_dir(), 'journal_directory_required')
        _fsync_directory(component)
        if component != component.parent:
            _fsync_directory(component.parent)
    require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, 'journal_directory_must_be_private')
    return path


class Journal:
    def __init__(self, directory):
        self.root = _private_durable_directory(Path(directory))
        self.path = self.root / 'coordination.json'
        lock_path = self.root / '.coordination.lock'
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self._lock_file = os.fdopen(fd, 'a')
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_file.close()
            raise ValueError('coordination_owner_exists') from None
        self.closed = False
        try:
            self.data = self._read()
        except BaseException:
            self.close()
            raise

    def _read(self):
        if not self.path.exists():
            return {'schema_version': 1, 'epoch': None, 'records': {}, 'active': None, 'task_ids': []}
        require(not self.path.is_symlink(), 'journal_symlink')
        with self.path.open('rb') as stream:
            raw = stream.read(MAX_JOURNAL_BYTES + 1)
        require(len(raw) <= MAX_JOURNAL_BYTES, 'journal_too_large')
        data = json.loads(raw)
        require(type(data) is dict and data.keys() == {'schema_version', 'epoch', 'records', 'active', 'task_ids'}
                and data['schema_version'] == 1 and type(data['records']) is dict
                and len(data['records']) <= 4096 and type(data['task_ids']) is list and len(data['task_ids']) <= 256 and
                (data['active'] is None or type(data['active']) is dict), 'journal_invalid')
        return data

    def save(self, data):
        require(not self.closed, 'journal_closed')
        raw = json.dumps(data, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
        require(len(raw) <= MAX_JOURNAL_BYTES, 'journal_too_large')
        temporary = self.root / ('.coordination.' + uuid.uuid4().hex + '.tmp')
        try:
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            _fsync_directory(self.root)
        finally:
            temporary.unlink(missing_ok=True)
        self.data = data

    def close(self):
        if not self.closed:
            self._lock_file.close()
            self.closed = True
