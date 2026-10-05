"""Single foreground controller; Minecraft owns continuous tick execution."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import quote

from .ipc import ID, MAX_PENDING, MAX_RESULTS, atomic_json, read_json
from .tasks import make_task
from .transport import BridgeError, DIRECT
from .world import WorldCache

TERMINAL = {'succeeded', 'failed', 'cancelled'}
TASKS = {'action', 'walk_to', 'craft_planks', 'pillar'}


@dataclass
class Running:
    command: dict
    recipe: object
    action_id: str | None = None
    step_number: int = 0
    response: object = None
    last_action_result: object = None
    wake_at: float = 0.0


class Resident:
    def __init__(self, bridge, directory):
        self.bridge, self.root = bridge, Path(directory)
        self.session_id = uuid.uuid4().hex
        self.pending, self.active = deque(), None
        self.cache = WorldCache()
        self.paused = False
        self.reason = None
        self.running = True
        self.bridge_identity = None
        self.started_at = time.time()
        self.last_status = None
        self.last_publish = 0.0
        self.lock = None
        self.owns_lock = False
        self.initialized = False
        self.seen = set()

    def publish(self):
        data = {'schema_version': 1, 'session_id': self.session_id,
                'state': 'stopped' if not self.running else 'starting' if not self.initialized else 'paused' if self.paused else 'busy' if self.active else 'ready',
                'reason': self.reason, 'started_at': self.started_at, 'updated_at': time.time(),
                'base_url': self.bridge.base_url, 'controller_pid': os.getpid(),
                'bridge_identity': self.bridge_identity,
                'active_request_id': self.active.command['request_id'] if self.active else None,
                'active_action_id': self.active.action_id if self.active else None,
                'pending': len(self.pending)}
        atomic_json(self.root / 'session.json', data)
        self.last_publish = time.monotonic()

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        for folder in ('inbox', 'working', 'results'):
            (self.root / folder).mkdir(exist_ok=True)
        self.lock = (self.root / '.controller.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('controller_already_running_for_queue') from None
        self.owns_lock = True
        self.publish()
        # A prior process may have crashed after sending a request. Never replay it.
        for path in list((self.root / 'working').glob('*.json')) + list((self.root / 'inbox').glob('*.json')):
            self.finish({'request_id': path.stem}, 'uncertain', reason='previous_session_not_replayed')
            path.unlink(missing_ok=True)
        status = self.bridge.request('GET', '/control/status')
        if status.get('protocol') != 'mineclient-bridge' or status.get('schema_version') != 2:
            raise ValueError('unsupported_bridge_protocol')
        continuous = self.bridge.request('GET', '/control/action/status')
        if continuous.get('action_schema_version') != 1 or not continuous.get('action_session'):
            raise ValueError('continuous_action_mod_required')
        self.bridge_identity = {'run_id': status.get('run_id'), 'process_id': status.get('process_id'),
                                'action_session': continuous['action_session']}
        self.last_status = status
        self.initialized = True
        if continuous.get('status') == 'running':
            self.paused, self.reason = True, 'preexisting_action_use_observe_or_direct_takeover'
        self.publish()

    def check_identity(self, status):
        actual = {'run_id': status.get('run_id'), 'process_id': status.get('process_id'),
                  'action_session': status.get('client_action', {}).get('action_session')}
        if actual != self.bridge_identity:
            self.paused, self.reason = True, 'bridge_restarted_owner_restart_controller'
            raise ValueError(self.reason)
        self.last_status = status

    def finish(self, command, status, **fields):
        request_id = command['request_id']
        if not ID.fullmatch(request_id):
            return
        atomic_json(self.root / 'results' / (request_id + '.json'),
                    {'request_id': request_id, 'session_id': command.get('session_id', self.session_id),
                     'status': status, 'finished_at': time.time(), **fields})
        (self.root / 'working' / (request_id + '.json')).unlink(missing_ok=True)
        files = sorted((self.root / 'results').glob('*.json'), key=lambda p: p.stat().st_mtime)
        for path in files[:-MAX_RESULTS]:
            path.unlink(missing_ok=True)

    def discard_pending(self, reason):
        while self.pending:
            self.finish(self.pending.popleft(), 'cancelled', reason=reason)

    def end_active(self, status, **fields):
        if self.active:
            self.finish(self.active.command, status, **fields)
            self.active = None
        if status != 'succeeded':
            self.discard_pending('prior_task_stopped')
        self.publish()

    def interrupt_local(self, reason):
        # Caller follows this with the single atomic mod takeover POST.
        self.discard_pending(reason)
        if self.active:
            self.end_active('cancelled', reason=reason, mod_cancel_confirmed=False)

    def snapshot(self, command):
        status = self.bridge.request('GET', '/control/status')
        self.check_identity(status)
        result = {'status': status,
                  'action': self.bridge.request('GET', '/control/action/status')}
        if status.get('in_world'):
            result['state'] = self.cache.observe(self.bridge)
        result['screen'] = self.bridge.request('GET', '/control/screen')
        if command.get('terrain'):
            result['terrain'] = self.cache.scan(self.bridge, command.get('radius', 4), command.get('vertical', 2))
        if command.get('frame'):
            frame = self.bridge.request('GET', '/control/frame')
            path = self.root / 'latest.png'
            temp = path.with_suffix('.tmp.png')
            temp.write_bytes(frame)
            os.replace(temp, path)
            result['frame'] = {'path': str(path), 'captured_at': time.time(), 'source': 'native_minecraft_frame'}
        atomic_json(self.root / 'observation.json', result)
        return result

    def command(self, command):
        operation = command.get('op')
        if operation == 'observe':
            self.finish(command, 'succeeded', result=self.snapshot(command))
        elif operation == 'direct':
            endpoint, body = command.get('endpoint'), command.get('body')
            if endpoint not in DIRECT or not isinstance(body, dict):
                raise ValueError('invalid_direct_command')
            self.check_identity(self.bridge.request('GET', '/control/status'))
            self.interrupt_local('direct_takeover')
            result = self.bridge.request('POST', '/control/' + endpoint, body)
            self.paused, self.reason = False, None
            self.finish(command, 'succeeded', reason='direct_input_dispatched', result=result,
                        gameplay_effect_confirmed=False)
        elif operation == 'cancel':
            self.check_identity(self.bridge.request('GET', '/control/status'))
            self.interrupt_local('cancel_requested')
            # Explicit cancel is release-all, including held direct keys. It never leaves a game.
            result = self.bridge.request('POST', '/control/release-all', {})
            self.paused, self.reason = False, None
            self.finish(command, 'succeeded', result=result)
        elif operation == 'resume':
            self.check_identity(self.bridge.request('GET', '/control/status'))
            result = self.bridge.request('GET', '/control/action/status')
            if result.get('status') == 'running':
                raise ValueError('action_still_running_observe_or_cancel')
            self.paused, self.reason = False, None
            self.finish(command, 'succeeded', reason='ready_for_new_requests_no_replay')
        elif operation == 'shutdown':
            self.command({**command, 'op': 'cancel'})
            self.running = False
        elif operation in TASKS:
            if self.paused:
                raise ValueError(self.reason or 'controller_paused')
            if len(self.pending) >= MAX_PENDING:
                raise ValueError('queue_full')
            self.pending.append(command)
        else:
            raise ValueError('unknown_operation')

    def read_commands(self):
        paths = list((self.root / 'inbox').glob('*.json'))
        # File mtime is only ordering within the mailbox, not cross-namespace process evidence.
        paths.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
        commands = []
        for path in paths[:MAX_PENDING * 2]:
            destination = self.root / 'working' / path.name
            os.replace(path, destination)  # Claim before any side effect.
            command = {'request_id': path.stem}
            try:
                command = read_json(destination)
                if command.get('request_id') != path.stem or not ID.fullmatch(path.stem):
                    raise ValueError('invalid_request_id')
                if command.get('session_id') != self.session_id:
                    raise ValueError('stale_controller_session_not_replayed')
                if (self.root / 'results' / path.name).exists():
                    destination.unlink(missing_ok=True)
                    continue
                if path.stem in self.seen:
                    self.finish(command, 'failed', reason='request_id_already_consumed_result_expired')
                    continue
                self.seen.add(path.stem)
                commands.append(command)
            except Exception:
                self.finish({'request_id': path.stem}, 'failed', reason='invalid_or_stale_command')
        # Direct/cancel commands preempt tasks already admitted this turn too.
        for command in commands:
            if not self.running:
                self.finish(command, 'cancelled', reason='controller_stopped')
                continue
            try:
                self.command(command)
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                self.command_error(command, exc)
        if commands:
            self.publish()

    def command_error(self, command, exc):
        uncertain = isinstance(exc, BridgeError) and exc.uncertain
        reason = safe_reason(exc)
        if uncertain:
            self.paused, self.reason = True, 'uncertain_request_observe_then_resume'
            self.discard_pending('uncertain_request')
        self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason)

    def advance(self):
        if self.active is None:
            if not self.pending or self.paused:
                return
            command = self.pending.popleft()
            try:
                self.check_identity(self.bridge.request('GET', '/control/status'))
                self.active = Running(command, make_task(command, self.cache, self.bridge))
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                self.command_error(command, exc)
                self.discard_pending('prior_task_stopped')
                return
        task = self.active
        if time.monotonic() < task.wake_at:
            return
        sending_action = False
        try:
            if task.action_id:
                result = self.bridge.request('GET', '/control/action/status?action_id=' + quote(task.action_id, safe=''))
                self.accept_action_status(task, result)
                if task.action_id:
                    task.wake_at = time.monotonic() + 0.2
                    return
            step = task.recipe.send(task.response)
            task.response = None
            kind = step['step']
            if kind == 'action':
                task.step_number += 1
                task.action_id = uuid.uuid5(uuid.UUID(self.session_id), task.command['request_id'] + ':' + str(task.step_number)).hex
                sending_action = True
                result = self.bridge.request('POST', '/control/action', {**step['body'], 'action_id': task.action_id})
                self.accept_action_status(task, result)
                task.wake_at = time.monotonic() + 0.1
            elif kind == 'observe':
                task.response = self.cache.observe(self.bridge)
            elif kind == 'wait':
                task.wake_at = time.monotonic() + step['seconds']
            else:
                raise ValueError('invalid_recipe_step')
        except StopIteration as done:
            self.end_active('succeeded', result=done.value)
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            definite_rejection = (sending_action and isinstance(exc, BridgeError)
                                  and exc.status is not None and 400 <= exc.status < 500)
            if definite_rejection:
                task.action_id = None
            uncertain = isinstance(exc, BridgeError) and (exc.uncertain or task.action_id is not None)
            cancel = None
            if task.action_id:
                # Cancelling an action ID is a different request, never a replay of it.
                try:
                    cancel = self.bridge.request('POST', '/control/action/cancel', {'action_id': task.action_id})
                except BridgeError:
                    cancel = {'status': 'unconfirmed'}
            if uncertain:
                self.paused, self.reason = True, 'uncertain_request_observe_then_resume'
            self.end_active('uncertain' if uncertain else 'failed', reason=safe_reason(exc),
                            action_id=task.action_id, action=task.last_action_result, cancellation=cancel)

    def accept_action_status(self, task, result):
        if (result.get('action_schema_version') != 1 or result.get('action_id') != task.action_id
                or result.get('action_session') != self.bridge_identity['action_session']):
            raise BridgeError('action_status_mismatch', uncertain=True)
        task.last_action_result = result
        status = result.get('status')
        if status == 'running':
            return
        if status not in TERMINAL:
            raise BridgeError('unknown_action_status', uncertain=True)
        task.action_id = None
        if status != 'succeeded':
            # Preserve the full compact action status in the task result.
            self.end_active(status, reason=result.get('reason', status), action=result)
            raise TaskEnded()
        task.response = result

    def tick(self):
        self.read_commands()
        if not self.running:
            return
        try:
            self.advance()
        except TaskEnded:
            pass
        if time.monotonic() - self.last_publish > 1:
            self.publish()

    def serve(self):
        try:
            self.start()
            while self.running:
                self.tick()
                time.sleep(0.05)
        except KeyboardInterrupt:
            # Explicit owner Ctrl-C stops input only, never disconnects or quits Minecraft.
            self.interrupt_local('controller_stopped')
            try:
                self.check_identity(self.bridge.request('GET', '/control/status'))
                self.bridge.request('POST', '/control/release-all', {})
            except (BridgeError, ValueError):
                self.reason = 'stopped_input_release_unconfirmed'
        finally:
            self.running = False
            if self.owns_lock:
                self.publish()
            if self.lock:
                self.lock.close()


class TaskEnded(Exception):
    pass


def safe_reason(exc):
    if isinstance(exc, BridgeError):
        return exc.code
    value = str(exc)
    return value if re.fullmatch(r'[a-zA-Z0-9_]{1,100}', value) else 'invalid_command_or_observation'
