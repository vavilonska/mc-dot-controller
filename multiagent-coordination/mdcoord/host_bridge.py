"""Explicit native-agent host bridge; local bounded files, no server or credentials.

The existing assistant host launches read-only native agents from pending request
JSON, collects their JSON result and calls `complete` with the native task ID.
A Python worker is a transport waiter, not a model; only completed host records
provide native invocation evidence. No request retries or game actions exist.
This spool is cooperative same-user IPC, NOT an authentication/security sandbox.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import time

from .schema import canonical, fields, identifier, loads, require, Rejected


INSTRUCTION = '''Read-only Minecraft planner. Use only the supplied immutable snapshot.
Do not call tools, inspect files, observe the game, submit actions, change settings,
or contact any service. Your role is an alternative route planner. Return JSON
null when no safe useful candidate is apparent, otherwise a JSON object with only
intent, based_on, dependencies, priority and preconditions. The owner alone
validates safety, chooses an alternative and may dispatch. Never assert that a
proposal is an executed action. Plan one short grounded segment within the known
complete terrain, starting at the supplied player location. Consider the role's
route preference, but never invent unknown terrain. Dependencies must be [].
intent is {"kind":"follow_path","timeout_ms":1000,"waypoints":[{"x":...,
"y":...,"z":...}]}; based_on must use the snapshot terrain content_revision.
priority must be 10. preconditions must contain alive:true, grounded:true,
screen_closed:true, min_health:5, expected_position:{x:...,y:...,z:...}.
Role short_route chooses the nearest useful step; role cautious_route chooses a
short known-clear route with the widest support margin; role progress_route
chooses the furthest useful step within two blocks. Return only the JSON value.
'''


def _read(path):
    # No following caller-controlled symlinks. The dedicated spool is owned by
    # the trusted host; filesystem permissions are not broadened here.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'host_file_not_regular')
        return loads(stream.read(64 * 1024 + 1))


def _write_once(path, value):
    encoded = canonical(value)
    temp = path.with_name(path.name + '.pending-' + str(os.getpid()))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        # link is atomic and does not replace an existing completion/request.
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class NativeHostBridge:
    def __init__(self, directory, *, clock=time.monotonic, poll_seconds=.01):
        self.directory = Path(directory)
        require(self.directory.is_dir() and not self.directory.is_symlink(), 'host_spool_required')
        require(.001 <= poll_seconds <= .5, 'host_poll_bound')
        self.clock, self.poll_seconds = clock, poll_seconds

    def compute(self, request):
        payload = request.wire()
        rid = identifier(payload['request_id'])
        request_path = self.directory / (rid + '.request.json')
        response_path = self.directory / (rid + '.response.json')
        require(not response_path.exists(), 'host_unrequested_response')
        # Native tool availability remains the host's responsibility. This
        # instruction does not claim to remove same-user tool capabilities.
        instruction = INSTRUCTION
        if payload.get('result_kind') == 'advice':
            instruction = '''Read-only Minecraft route-goal adviser. Use only the supplied immutable snapshot.
Do not use any tools, inspect files, observe the game, contact services or act.
Return only JSON null or {"kind":"route_goal","goal":{"x":...,"y":...,"z":...},
"based_on":{"terrain":<snapshot terrain content_revision>}}. This is a suggestion,
not an action or authority. The owner must obtain a new independent observation
and recompute the route before any action. Pick a centered, level goal one or two
blocks ahead on known complete supported terrain. short_route prefers the nearest
useful step; cautious_route prefers a conservative one-block step; progress_route
prefers progress within two blocks. Do not return action fields or preconditions.'''
        _write_once(request_path, {'instruction': instruction, 'request': payload, 'host_requested_mono': self.clock()})
        while self.clock() < request.deadline_mono:
            if response_path.exists():
                result = _read(response_path)
                fields(result, ('request_id', 'snapshot_sha256', 'native_task_id', 'candidate', 'origin', 'host_completed_mono'))
                require(result['request_id'] == rid and
                        result['snapshot_sha256'] == payload['snapshot_sha256'], 'host_response_fence')
                require(type(result['native_task_id']) is str and 1 <= len(result['native_task_id']) <= 240,
                        'host_native_task_evidence_required')
                require(result['origin'] == 'native_subagent_host', 'host_origin_required')
                return result['candidate']
            time.sleep(min(self.poll_seconds, max(0, request.deadline_mono - self.clock())))
        raise Rejected('native_host_deadline')


def pending(directory):
    root = Path(directory)
    require(root.is_dir() and not root.is_symlink(), 'host_spool_required')
    paths = sorted(root.glob('*.request.json'))
    require(len(paths) <= 384, 'host_spool_capacity')
    result = []
    for path in paths:
        if path.with_name(path.name.replace('.request.json', '.response.json')).exists():
            continue
        value = _read(path)
        deadline = value['request'].get('inference_deadline_mono')
        result.append({'path': str(path), **value, 'expired': deadline is not None and time.monotonic() >= deadline})
    return result


def complete(directory, request_id, candidate, native_task_id):
    """Called by trusted assistant host AFTER an actual native worker response.

    Never call with a fabricated native task ID or mark a mock result native.
    This records evidence supplied by the host, not a cryptographic attestation.
    """
    root = Path(directory)
    require(root.is_dir() and not root.is_symlink(), 'host_spool_required')
    rid = identifier(request_id)
    request = _read(root / (rid + '.request.json'))['request']
    require(type(native_task_id) is str and 1 <= len(native_task_id) <= 240, 'host_native_task_evidence_required')
    response = {'request_id': rid, 'snapshot_sha256': request['snapshot_sha256'],
                'native_task_id': native_task_id, 'candidate': candidate, 'origin': 'native_subagent_host',
                'host_completed_mono': time.monotonic()}
    _write_once(root / (rid + '.response.json'), response)
    return {'completed': rid, 'native_task_id': native_task_id, 'game_action_sent': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    query = sub.add_parser('pending'); query.add_argument('directory')
    finish = sub.add_parser('complete'); finish.add_argument('directory'); finish.add_argument('request_id')
    finish.add_argument('--result', required=True, help='File with JSON candidate or null from actual native worker')
    finish.add_argument('--native-task-id', required=True)
    args = parser.parse_args(argv)
    try:
        result = pending(args.directory) if args.command == 'pending' else complete(
            args.directory, args.request_id, _read(args.result), args.native_task_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, Rejected):
        print(json.dumps({'error': 'host_bridge_operation_rejected', 'retried': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
