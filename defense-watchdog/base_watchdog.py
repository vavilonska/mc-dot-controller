"""One operator-owned queue writer for short game tasks and always-on enemy checks.

Importing this module does not open a queue or perform game I/O. The game operator
explicitly starts it, then routes ordinary commands through its intent inbox.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
# Published layout and original local source layout are both supported.
for name in ('resident-controller', 'minecraft-resident-controller'):
    candidate = ROOT / name
    if (candidate / 'resident_controller' / 'ipc.py').is_file():
        sys.path.insert(0, str(candidate))
        break
from resident_controller.native_combat import HOSTILES, WEAPONS
from resident_controller.ipc import QueueClient
from targeting import TargetPolicy

TERMINAL = {'succeeded', 'failed', 'cancelled', 'uncertain'}
OWNER_OPS = {'observe', 'direct', 'action', 'walk_to', 'craft_planks', 'pillar',
             'scan_start', 'scan_status', 'scan_cancel'}


def hostile(state, distance=6):
    choices = [e for e in state.get('nearby', {}).get('entities', [])
               if e.get('type') in HOSTILES and e.get('alive') is True
               and e.get('health', 1) > 0 and 0 <= e.get('distance', float('inf')) <= distance]
    return min(choices, key=lambda e: e['distance'], default=None)


def alive(state):
    p = state.get('player', {})
    return p.get('alive') is True and p.get('health', 0) > 0


def weapon(state):
    return any(i.get('id') in WEAPONS and i.get('count', 0) > 0
               and type(i.get('slot')) is int and 0 <= i['slot'] <= 8
               for i in state.get('player', {}).get('inventory', []))


def recovery_context(state):
    identity = (state.get('world', {}).get('world_generation'),
                state.get('player', {}).get('uuid'),
                state.get('client_action', {}).get('action_session'))
    tick = state.get('world', {}).get('game_time')
    if not all(isinstance(value, str) and value for value in identity) or type(tick) is not int or tick < 0:
        return None
    return identity, tick


class Watchdog:
    """Nonblocking orchestration. q is the existing QueueClient or an offline fake."""
    def __init__(self, q, *, clock=time.monotonic, interval=.4):
        self.q, self.clock, self.interval = q, clock, interval
        self.session_id = uuid.uuid4().hex
        self.targeting = TargetPolicy(HOSTILES)
        self.defense_epoch = 0
        self.phase, self.reason = 'watching', 'starting'
        self.armed, self.stopped = True, False
        self.rpc, self.owner = None, None
        self.latest, self.observed_at = None, None
        self.next_observe = 0.0
        self.last_health = None
        self.started_target = None
        self.stop_requested = False
        self.cancel_confirmed = None
        self.completed = []
        self.recover_observation = False
        self.recovery_samples = 0
        self.recovery_identity = None
        self.recovery_game_time = None

    def status(self):
        return {'schema_version': 3, 'implementation': 'native-defense-watchdog-v3',
                'session_id': self.session_id, 'defense_epoch': self.defense_epoch,
                'state': ('stopped' if self.stopped else 'paused' if not self.armed else 'busy'
                          if self.owner or self.phase in ('combat', 'engaging', 'retaining_target') else 'ready'),
                'active_request_id': self.owner['id'] if self.owner else None,
                'phase': self.phase, 'reason': self.reason, 'armed': self.armed,
                'stopped': self.stopped, 'cancel_confirmed': self.cancel_confirmed,
                'active_owner_intent': self.owner['id'] if self.owner else None,
                'active_queue_request': self.owner['request_id'] if self.owner else None,
                'pending_control_request': self.rpc['id'] if self.rpc else None,
                'combat_target': self.started_target,
                'targeting': self.targeting.status(self.clock()),
                'observation_recovery': {'eligible': self.recover_observation, 'fresh_samples': self.recovery_samples},
                'observation_age': None if self.observed_at is None else self.clock() - self.observed_at,
                'combat': (self.latest or {}).get('combat'),
                'player': {k: (self.latest or {}).get('state', {}).get('player', {}).get(k)
                           for k in ('alive', 'health', 'food', 'x', 'y', 'z', 'selected_slot')}}

    def send(self, kind, command):
        # Exactly one stable queue ID per request; no automatic replay.
        if kind in ('cancel_threat', 'attention_cancel', 'stop_cancel'):
            self.defense_epoch += 1
        request_id = self.q.submit(command)
        self.rpc = {'id': request_id, 'kind': kind, 'started': self.clock()}

    def attention(self, reason):
        if reason == 'observation_delayed_cancel_requested' and not (self.armed or self.recover_observation):
            return  # A sensor delay must never erase a manual/uncertain/death pause.
        self.defense_epoch += 1
        self.recover_observation = reason == 'observation_delayed_cancel_requested'
        self.recovery_samples = 0
        state = (self.latest or {}).get('state', {})
        context = recovery_context(state)
        self.recovery_identity, self.recovery_game_time = context if context else (None, None)
        self.armed, self.phase, self.reason = False, 'needs_operator', reason

    def stop(self):
        self.stop_requested = True

    def submit_owner(self, intent_id, command):
        """Return False to keep a deferred intent in its inbox during combat."""
        command = dict(command)
        expected_epoch = command.pop('_navigation_defense_epoch', None)
        if expected_epoch is not None and (type(expected_epoch) is not int or expected_epoch != self.defense_epoch):
            self.completed.append({'intent_id': intent_id, 'session_id': self.session_id, 'queue_request_id': None,
                                   'result': {'status': 'cancelled', 'reason': 'navigation_defense_epoch_changed',
                                              'gameplay_effect_confirmed': False}})
            return True  # Consume only the stale local intent, never send it.
        if self.owner or self.rpc or self.stopped or not self.armed or self.stop_requested:
            return False
        if (self.latest is None or self.clock() - self.observed_at > .8
                or self.phase != 'watching' or self.started_target
                or self.latest.get('combat', {}).get('active') is True):
            return False
        if command.get('op') not in OWNER_OPS:
            raise ValueError('unsupported_owner_intent')
        if self.targeting.choose(self.latest.get('state', {}), self.clock()):
            return False
        request_id = self.q.submit(command)
        self.owner = {'id': intent_id, 'request_id': request_id}
        return True

    def damage_requires_cancel(self, state):
        return True

    def observation_received(self, payload, kind):
        pass

    def persist_telemetry(self, directory):
        pass

    def observe_tactics(self, state, combat, damaged, kind):
        return False

    def tick(self):
        if self.stopped:
            return
        if self.owner:
            result = self.q.result(self.owner['request_id'])
            if result is not None:
                self.completed.append({'intent_id': self.owner['id'], 'session_id': self.session_id,
                                       'queue_request_id': self.owner['request_id'],
                                       'result': result})
                self.owner = None
                if result.get('status') == 'uncertain':
                    self.attention('owner_action_uncertain')
                    self.send('attention_cancel', {'op': 'cancel'})
        if self.stop_requested and (not self.rpc or self.rpc['kind'] != 'stop_cancel'):
            self.armed = False
            self.phase, self.reason = 'stopping', 'operator_stop'
            self.send('stop_cancel', {'op': 'cancel'})
            return
        if self.rpc:
            result = self.q.result(self.rpc['id'])
            if result is None:
                # Observing must not silently hold navigation for tens of seconds.
                # Queue processing may itself be blocked, so this is a requested
                # cancellation, never a hard real-time stop guarantee.
                if self.rpc['kind'] in ('observe', 'fresh') and self.clock() - self.rpc['started'] > 2:
                    if not self.armed and not self.recover_observation:
                        self.rpc = None
                        self.next_observe = self.clock() + self.interval
                        return
                    self.attention('observation_delayed_cancel_requested')
                    self.send('attention_cancel', {'op': 'cancel'})
                return
            kind = self.rpc['kind']
            self.rpc = None
            if kind == 'stop_cancel':
                self.cancel_confirmed = (result.get('status') == 'succeeded'
                                         and result.get('result', {}).get('ok') is True)
                self.stopped, self.phase = True, 'stopped'
                self.reason = 'operator_stop' if self.cancel_confirmed else 'input_release_unconfirmed'
                return
            if result.get('status') != 'succeeded':
                if kind in ('observe', 'fresh') and not self.armed and not self.recover_observation:
                    self.next_observe = self.clock() + self.interval
                    return  # Sensor failures cannot cancel a manual owner's newer input.
                if (kind == 'start_combat' and result.get('status') == 'failed'
                        and result.get('reason') in ('combat_target_not_observed_hostile', 'combat_no_observed_hostile')):
                    self.phase, self.reason, self.next_observe = 'watching', 'target_changed_before_start', 0
                    return
                self.attention(kind + '_' + str(result.get('reason', result.get('status'))))
                if kind in ('observe', 'fresh', 'start_combat'):
                    self.send('attention_cancel', {'op': 'cancel'})
                return
            if kind == 'attention_cancel':
                self.cancel_confirmed = result.get('result', {}).get('ok') is True
                if not self.cancel_confirmed:
                    self.attention('input_release_unconfirmed')
                elif self.recover_observation:
                    self.phase, self.reason = 'recovering_observation', 'awaiting_two_fresh_samples'
                    old_target = self.targeting.locked_uuid
                    self.targeting.release(self.clock(), 'observation_interrupted')
                    self.targeting.preferred_uuid = old_target
                    self.started_target = None
                return
            if kind == 'cancel_threat':
                if result.get('result', {}).get('ok') is not True:
                    self.attention('input_release_unconfirmed')
                    return
                self.send('fresh', {'op': 'observe'})
                return
            if kind == 'start_combat':
                combat = result.get('result', {})
                if combat.get('active') is not True:
                    self.attention('combat_start_not_active')
                    return
                self.started_target = combat.get('target_uuid')
                self.targeting.lock(self.started_target, self.clock())
                self.phase, self.reason = 'combat', 'combat_start_acknowledged'
                self.next_observe = 0
            elif kind in ('observe', 'fresh'):
                self.latest = result.get('result', {})
                self.observation_received(self.latest, kind)
                self.observed_at = self.clock()
                self.next_observe = self.clock() + self.interval
                state = self.latest.get('state', {})
                damaged = self.targeting.observe_health(state, self.clock())
                if not alive(state):
                    was_armed = self.armed
                    self.attention('player_dead_or_unavailable')
                    if was_armed:
                        self.send('attention_cancel', {'op': 'cancel'})
                    return
                combat = self.latest.get('combat', {})
                if not self.armed:
                    if not self.recover_observation or self.cancel_confirmed is not True:
                        return
                    context = recovery_context(state)
                    if (context is None or self.recovery_identity is None or context[0] != self.recovery_identity
                            or self.latest.get('action', {}).get('status') == 'running'):
                        self.attention('observation_recovery_context_changed')
                        return
                    if (state.get('screen_open') is not False or state.get('paused') is not False
                            or context[1] <= self.recovery_game_time):
                        self.recovery_samples = 0
                        return
                    self.recovery_game_time = context[1]
                    self.recovery_samples += 1
                    if self.recovery_samples < 2:
                        return
                    self.armed, self.recover_observation = True, False
                    self.phase, self.reason = 'watching', 'fresh_observations_recovered_no_action_replay'
                if self.observe_tactics(state, combat, damaged, kind):
                    return
                decision, detail = self.targeting.assess(state, combat, self.clock())
                if decision == 'error':
                    self.attention('combat_stopped_' + str(detail))
                    return
                if decision == 'wait':
                    self.phase, self.reason = 'retaining_target', self.targeting.reason
                    return
                if decision in ('retarget', 'reacquire'):
                    self.started_target = None
                    self.phase, self.reason = 'engaging', self.targeting.reason
                    self.send('cancel_threat', {'op': 'cancel'})
                    return
                if combat.get('active') is True:
                    if self.started_target is None:
                        self.defense_epoch += 1
                    self.started_target = combat.get('target_uuid') or self.started_target
                    self.phase, self.reason = 'combat', 'observed_combat_active_keep_uuid'
                    return
                self.started_target = None
                target = self.targeting.choose(state, self.clock())
                if kind == 'fresh':
                    if self.latest.get('action', {}).get('status') == 'running':
                        self.attention('navigation_cancel_not_observed')
                        return
                    if not target:
                        self.phase, self.reason = 'watching', ('health_drop_source_unknown_no_hostile'
                                                             if self.targeting.recent_damage(self.clock()) else 'threat_no_longer_observed')
                    elif not weapon(state):
                        self.attention('threat_without_hotbar_weapon')
                    else:
                        self.phase, self.reason = 'engaging', 'fresh_hostile_target'
                        self.send('start_combat', {'op': 'combat_start', 'target_uuid': target['uuid'],
                                                 'radius': 8, 'approach': False, 'shield': True})
                    return
                if target:
                    self.phase, self.reason = 'engaging', ('health_drop_with_observed_hostile'
                                                          if damaged else 'nearby_hostile_cancel_navigation')
                    self.send('cancel_threat', {'op': 'cancel'})
                    return
                if damaged and self.owner and self.damage_requires_cancel(state):
                    self.phase, self.reason = 'engaging', 'health_drop_source_unknown_refresh'
                    self.send('cancel_threat', {'op': 'cancel'})
                    return
                self.phase, self.reason = 'watching', 'no_nearby_hostile'
        if not self.rpc and self.clock() >= self.next_observe:
            self.send('observe', {'op': 'observe'})


def write_json(path, value):
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def cancel_waiting_intents(directory, dog):
    if dog.armed:
        return
    for path in (directory/'inbox').glob('*.json'):
        write_json(directory/'results'/path.name,
                   {'request_id': path.stem, 'session_id': dog.session_id,
                    'status': 'cancelled', 'reason': 'watchdog_interrupted_replan_required'})
        path.unlink()


def run(queue, directory, watchdog_class=Watchdog):
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    for name in ('inbox', 'working', 'results'):
        (directory/name).mkdir(exist_ok=True)
    lock = (directory/'owner.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (directory/'STOP').exists():
        raise ValueError('remove_previous_STOP_explicitly_before_new_run')
    dog = watchdog_class(QueueClient(queue))
    for folder in ('inbox', 'working'):
        for path in (directory/folder).glob('*.json'):
            write_json(directory/'results'/path.name, {'request_id': path.stem, 'session_id': dog.session_id, 'status': 'uncertain', 'reason': 'previous_run_not_replayed'})
            path.unlink()
    try:
        while not dog.stopped:
            if (directory/'STOP').exists(): dog.stop()
            try:
                dog.tick()
                dog.persist_telemetry(directory)
                cancel_waiting_intents(directory, dog)
                for done in dog.completed:
                    write_json(directory/'results'/(done['intent_id']+'.json'), done)
                    (directory/'working'/(done['intent_id']+'.json')).unlink(missing_ok=True)
                dog.completed.clear()
                if dog.latest is not None:
                    write_json(directory/'observation.json', dog.latest)
                if not dog.owner:
                    for path in sorted((directory/'inbox').glob('*.json')):
                        intent = json.loads(path.read_text())
                        intent_session = intent.pop('_watchdog_session_id', dog.session_id)
                        if intent_session != dog.session_id:
                            write_json(directory/'results'/path.name, {'request_id': path.stem, 'session_id': dog.session_id,
                                       'status': 'cancelled', 'reason': 'stale_watchdog_session'})
                            path.unlink()
                            continue
                        if dog.submit_owner(path.stem, intent):
                            path.rename(directory/'working'/path.name)
                        break
            except (ValueError, OSError, KeyError, TypeError) as exc:
                dog.attention(type(exc).__name__)
                # No lost/uncertain request is replayed. Operator sees the blocker.
            write_json(directory/'state.json', {**dog.status(), 'pending': len(list((directory/'inbox').glob('*.json'))),
                                                   'updated_at': time.time(), 'pid': os.getpid()})
            time.sleep(.05)
    except KeyboardInterrupt:
        dog.stop()
        while not dog.stopped:
            dog.tick()
            write_json(directory/'state.json', {**dog.status(), 'pending': len(list((directory/'inbox').glob('*.json'))),
                                                   'updated_at': time.time(), 'pid': os.getpid()})
            time.sleep(.05)
    finally:
        lock.close()


if __name__ == '__main__':
    raise SystemExit('Use watchdog.py for the ranged-melee candidate entry point')
