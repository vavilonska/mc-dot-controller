"""One operator-owned queue writer for short game tasks and always-on enemy checks.

Importing this module does not open a queue or perform game I/O. The game operator
explicitly starts it, then routes ordinary commands through its intent inbox.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import stat
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
from resident_controller.action_safety import task_release_unconfirmed, task_handoff_required, native_release_unconfirmed
from targeting import TargetPolicy
from capability_ownership import CapabilityOwnership, CONTROL_OPS, context_of, safe_idle

TERMINAL = {'succeeded', 'failed', 'cancelled', 'uncertain'}
OWNER_OPS = {'observe', 'direct', 'action', 'walk_to', 'craft_planks', 'pillar',
             'scan_start', 'scan_status', 'scan_cancel', 'recovery_close_menu'} | CONTROL_OPS
EXECUTION_POLICIES = frozenset({'standard', 'noncombat', 'request_only'})
EXPLICIT_POLICIES = frozenset({'noncombat', 'request_only'})
# Deliberately enumerated: a future native action is not silently authorized.
# use_item is restricted to consumables by the native ClientActions handler.
NONCOMBAT_ACTIONS = frozenset({'follow_path', 'break_block', 'place_block', 'click_slot',
    'boat_drive', 'boat_mount', 'boat_dismount', 'interact_block', 'use_item',
    'select_hotbar', 'close_menu', 'gateway_pearl',
    'movement_budget_start', 'movement_budget_finish'})


def recovery_close_command(command):
    return type(command) is dict and command == {'op': 'recovery_close_menu'}


def fresh_menu_request(stamp):
    return type(stamp) in (int, float) and math.isfinite(stamp) and 0 <= time.time() - stamp <= .8


def valid_resident_policy(policy):
    return (type(policy) is dict and type(policy.get('schema_version')) is int
            and policy['schema_version'] == 1 and type(policy.get('requires_handoff')) is bool
            and type(policy.get('input_release_unconfirmed')) is bool)


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


class Watchdog(CapabilityOwnership):
    """Nonblocking orchestration. q is the existing QueueClient or an offline fake."""
    def __init__(self, q, *, clock=time.monotonic, interval=.4, execution_policy='standard'):
        if execution_policy not in EXECUTION_POLICIES:
            raise ValueError('invalid_execution_policy')
        self.execution_policy = execution_policy
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
        self.input_release_latched = False
        self.handoff_latched = False
        self.capability_lease = None

    def poll_interval(self):
        """Bounded local IPC responsiveness while an exact lease is active.

        This changes only the loop sleep, never admission, ownership, expiry,
        native sampling or action retry. Legacy and paused/unknown paths retain
        their ordinary cadence.
        """
        lease = self.capability_lease
        if (not isinstance(lease, dict) or lease.get('state') != 'active'
                or not self.armed or self.stop_requested or self.stopped
                or self.handoff_latched or self.input_release_latched):
            return .05
        now = self.clock()
        bounds = (lease.get('deadline'), lease.get('heartbeat'))
        if (not isinstance(lease.get('owner_id'), str) or not lease['owner_id']
                or any(type(x) not in (int, float) or not math.isfinite(x)
                       or now >= x for x in bounds)):
            return .05
        return .01

    def status(self):
        return {**self.capability_status(), 'schema_version': 3, 'implementation': 'native-defense-watchdog-v3',
                'execution_policy_schema_version': 1, 'execution_policy': self.execution_policy,
                'session_id': self.session_id, 'defense_epoch': self.defense_epoch,
                'state': ('stopped' if self.stopped else 'paused' if not self.armed else 'busy'
                          if self.owner or self.phase in ('combat', 'engaging', 'retaining_target') else 'ready'),
                'active_request_id': self.owner['id'] if self.owner else None,
                'phase': self.phase, 'reason': self.reason, 'armed': self.armed,
                'input_release_latched': self.input_release_latched, 'handoff_latched': self.handoff_latched,
                'stopped': self.stopped, 'cancel_confirmed': self.cancel_confirmed,
                'active_owner_intent': self.owner['id'] if self.owner else None,
                'active_queue_request': self.owner['request_id'] if self.owner else None,
                'pending_control_request': self.rpc['id'] if self.rpc else None,
                'combat_target': self.started_target,
                'targeting': self.targeting.status(self.clock()),
                'observation_recovery': {'eligible': self.recover_observation, 'fresh_samples': self.recovery_samples},
                'menu_recovery': {'can_close': self.menu_close_ready(), 'schema_version': 1},
                'observation_age': None if self.observed_at is None else self.clock() - self.observed_at,
                'combat': (self.latest or {}).get('combat'),
                'player': {k: (self.latest or {}).get('state', {}).get('player', {}).get(k)
                           for k in ('alive', 'health', 'food', 'x', 'y', 'z', 'selected_slot')}}

    def send(self, kind, command):
        if (self.execution_policy in EXPLICIT_POLICIES and command.get('op') != 'observe'
                and not (self.stop_requested and kind == 'stop_cancel' and command == {'op': 'cancel'})):
            # Failure/timeout/death handling may ask for an automatic cancel.
            # This policy pauses instead; only explicit STOP may release input.
            # The exact pending owner/queue IDs are left untouched.
            if self.armed:
                self.attention(self.execution_policy + '_automatic_mutation_suppressed')
            elif self.reason == 'observation_delayed_cancel_requested':
                self.reason = self.execution_policy + '_observation_delayed_no_cancel'
            self.recover_observation = False
            return
        bridge = getattr(self, "_coordination_owner", None)
        if bridge is not None and command.get("op") != "observe":
            bridge.interrupt("controlled_step_disallows_legacy_mutation")
            return
        if ((self.input_release_latched or self.handoff_latched) and command.get('op') != 'observe'
                and not (kind == 'stop_cancel' and command == {'op': 'cancel'})):
            raise ValueError('input_release_unconfirmed_requires_operator' if self.input_release_latched
                             else 'encounter_requires_handoff')
        # Exactly one stable queue ID per request; no automatic replay.
        if kind in ('cancel_threat', 'attention_cancel', 'stop_cancel'):
            self.defense_epoch += 1
        context = None
        if kind in ('observe', 'fresh') and callable(getattr(self.q, 'session', None)):
            try:
                context = self.q.session()
                if not isinstance(context, dict):
                    raise ValueError('resident_policy_unconfirmed')
            except (OSError, ValueError, TypeError):
                self.handoff_latched = True
                self.attention('resident_policy_unconfirmed')
                return
        if bridge is not None and bridge.publisher is not None and command.get('op') == 'observe':
            request_id = uuid.uuid4().hex
            bridge.before_observe(request_id)
            self.q.submit({**command, 'coordination_step': True}, request_id=request_id)
        else:
            request_id = self.q.submit(command)
        self.rpc = {'id': request_id, 'kind': kind, 'started': self.clock()}
        if command.get('watchdog_observation_fallback') is True:
            self.rpc['observation_fallback_session'] = command.get('expected_resident_session')
        if context is not None:
            self.rpc['resident_session'] = context.get('session_id')
            self.rpc['resident_bridge'] = context.get('bridge_identity')

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

    def menu_close_ready(self):
        if (self.input_release_latched or self.handoff_latched or self.armed or self.stopped
                or self.stop_requested or not self.recover_observation or self.cancel_confirmed is not True
                or self.owner or self.latest is None or self.observed_at is None
                or not 0 <= self.clock() - self.observed_at <= .8):
            return False
        state = self.latest.get('state', {})
        policy = self.latest.get('resident_policy')
        if (not isinstance(state, dict) or any(not isinstance(state.get(k), dict) for k in ('world', 'player', 'client_action'))
                or any(not isinstance(self.latest.get(k), dict) for k in ('action', 'combat', 'status'))):
            return False
        context = recovery_context(state)
        terminal = {'idle', 'succeeded', 'failed', 'cancelled'}
        return (valid_resident_policy(policy) and not any((policy['requires_handoff'], policy['input_release_unconfirmed']))
                and alive(state) and state.get('screen_open') is True and type(state.get('paused')) is bool
                and context is not None and context[0] == self.recovery_identity
                and self.latest.get('action', {}).get('status') in terminal
                and state.get('client_action', {}).get('status') in terminal
                and self.latest.get('combat', {}).get('active') is False
                and self.latest.get('status', {}).get('held_mappings') == [])

    def submit_owner(self, intent_id, command, *, queue_request_id=None):
        """Return False to keep a deferred intent in its inbox during combat."""
        if (self.execution_policy in EXPLICIT_POLICIES and command.get('op') not in CONTROL_OPS
                and command.get('op') != 'observe'
                and not (command.get('op') == 'action' and self.capability_lease
                         and self.capability_lease['state'] == 'active'
                         and isinstance(command.get('_capability_owner_id'), str)
                         and bool(command['_capability_owner_id'])
                         and command['_capability_owner_id'] == self.capability_lease['owner_id']
                         and (command.get('action') in NONCOMBAT_ACTIONS if self.execution_policy == 'noncombat'
                              else isinstance(command.get('scoped_native_preflight'), dict)))):
            self.capability_expired()
            if self.input_release_latched or self.handoff_latched:
                return self.capability_complete(intent_id, 'cancelled', 'capability_owner_requires_handoff',
                    requires_handoff=True, input_release_unconfirmed=self.input_release_latched)
            if self.stop_requested or self.stopped:
                return self.capability_complete(intent_id, 'cancelled', 'watchdog_stopping_or_stopped')
            if self.owner:
                return False  # Do not obscure the pending owner's unknown outcome.
            # This is positive local non-dispatch evidence, not an HTTP receipt.
            return self.capability_complete(intent_id, 'cancelled', self.execution_policy + '_execution_policy',
                policy_rejection={'schema_version': 1, 'execution_policy': self.execution_policy, 'dispatched': False})
        capability = self.capability_submit(intent_id, command, queue_request_id=queue_request_id)
        if capability is not None:
            return capability
        if self.input_release_latched or self.handoff_latched:
            return False
        command = dict(command)
        bridge = getattr(self, '_coordination_owner', None)
        if bridge is not None and (queue_request_id != intent_id or intent_id not in bridge._sent
                                   or '_coordination' not in command):
            return False
        expected_epoch = command.pop('_navigation_defense_epoch', None)
        if expected_epoch is not None and (type(expected_epoch) is not int or expected_epoch != self.defense_epoch):
            self.completed.append({'intent_id': intent_id, 'session_id': self.session_id, 'queue_request_id': None,
                                   'result': {'status': 'cancelled', 'reason': 'navigation_defense_epoch_changed',
                                              'gameplay_effect_confirmed': False}})
            return True  # Consume only the stale local intent, never send it.
        if command.get('op') == 'recovery_close_menu':
            stamp = command.pop('_menu_recovery_requested_at', None)
            if not recovery_close_command(command):
                raise ValueError('invalid_recovery_close_menu')
            if expected_epoch != self.defense_epoch or not fresh_menu_request(stamp):
                raise ValueError('stale_menu_recovery_intent')
            if self.rpc or not self.menu_close_ready():
                return False
            session = self.q.session()
            policy = session.get('resident_policy')
            if (not isinstance(session.get('session_id'), str) or not session['session_id']
                    or not valid_resident_policy(policy) or policy['requires_handoff'] or policy['input_release_unconfirmed']
                    or session.get('state') != 'ready'
                    or session.get('bridge_identity', {}).get('action_session') != self.recovery_identity[2]):
                raise ValueError('menu_recovery_resident_not_ready')
            context = dict(zip(('world_generation', 'player_uuid', 'action_session'), self.recovery_identity))
            context.update(game_time=self.latest['state']['world']['game_time'], paused=self.latest['state']['paused'])
            request_id = uuid.uuid4().hex
            self.owner = {'id': intent_id, 'request_id': request_id, 'menu_recovery': True,
                          'resident_session': session['session_id']}
            try:
                self.q.submit({'op': 'direct', 'endpoint': 'raw-key',
                'body': {'key': 'key.keyboard.escape', 'action': 'click'}, 'watchdog_menu_recovery': True,
                'expected_resident_session': session['session_id'], 'expected_menu_context': context,
                'menu_recovery_requested_at': stamp}, request_id=request_id)
            except (OSError, ValueError):
                self.attention('menu_recovery_submission_unconfirmed')
                raise  # Keep the original request ID; never submit an alternative.
            self.recovery_samples = 0
            self.next_observe = 0
            return True
        if self.owner or self.rpc or self.stopped or not self.armed or self.stop_requested:
            return False
        if (self.latest is None or self.clock() - self.observed_at > .8
                or self.phase != 'watching' or self.started_target
                or self.latest.get('combat', {}).get('active') is True):
            return False
        if command.get('op') not in OWNER_OPS:
            raise ValueError('unsupported_owner_intent')
        encounter = (command.get('op') == 'action' and command.get('action') == 'combat_entity'
                     and any(k in command for k in ('encounter_mode', 'encounter_scope', 'encounter_pause_on_terminal')))
        if (self.execution_policy == 'standard' and not encounter
                and self.targeting.choose(self.latest.get('state', {}), self.clock())):
            return False
        request_id = self.q.submit(command, request_id=queue_request_id) if queue_request_id is not None else self.q.submit(command)
        self.owner = {'id': intent_id, 'request_id': request_id}
        if encounter:
            self.owner['encounter_handoff'] = True
        return True

    def read_coordinated(self, claim, request_id, action_id, context, read_request_id):
        if getattr(self, '_coordination_owner', None) is not claim:
            raise ValueError('coordination_read_owner_changed')
        claim.assert_thread()
        return self.q.submit({'op': 'coordination_status', 'expected_request_id': request_id,
                              'expected_action_id': action_id, 'expected_action_session': context.action_session,
                              'expected_resident_session': context.resident_session}, request_id=read_request_id)

    def cancel_coordinated(self, claim, request_id, action_id, context, cancel_request_id):
        if (getattr(self, '_coordination_owner', None) is not claim
                or not self.owner or self.owner.get('id') != request_id
                or self.owner.get('request_id') != request_id):
            raise ValueError('coordination_cancel_owner_changed')
        claim.assert_thread()
        return self.q.submit({'op': 'coordination_cancel', 'expected_request_id': request_id,
                              'expected_action_id': action_id, 'expected_action_session': context.action_session,
                              'expected_resident_session': context.resident_session}, request_id=cancel_request_id)

    def damage_requires_cancel(self, state):
        return True

    def observation_received(self, payload, kind):
        pass

    def persist_telemetry(self, directory):
        pass

    def observe_tactics(self, state, combat, damaged, kind):
        return False

    def latch_input_release(self, reason):
        self.input_release_latched = True
        self.attention(reason)

    def poll_unconfirmed_owner(self):
        if self.stop_requested and self.owner and self.owner.get('capability_owner'):
            return False
        if self.owner and self.owner.get('menu_recovery'):
            return self.poll_menu_recovery_owner()
        if self.owner:
            result = self.q.result(self.owner['request_id'])
            bridge = getattr(self, '_coordination_owner', None)
            if bridge is not None and bridge.guard_owner_result(self.owner['request_id'], result):
                return True
            if task_release_unconfirmed(result):
                self.completed.append({'intent_id': self.owner['id'], 'session_id': self.session_id,
                                       'queue_request_id': self.owner['request_id'], 'result': result})
                self.owner = None
                self.latch_input_release('owner_input_release_unconfirmed')
                return True
            terminal = isinstance(result, dict) and result.get('status') in ('succeeded', 'failed', 'cancelled', 'uncertain')
            if terminal and (self.owner.get('encounter_handoff') or task_handoff_required(result)):
                self.completed.append({'intent_id': self.owner['id'], 'session_id': self.session_id,
                                       'queue_request_id': self.owner['request_id'], 'result': result})
                self.owner = None
                self.handoff_latched = True
                self.attention('encounter_requires_handoff')
                return True
            if self.owner.get('encounter_handoff') and not self.stop_requested:
                return True  # Native scope owns this bounded action; no parallel legacy defense.
        return False

    def poll_menu_recovery_owner(self):
        result = self.q.result(self.owner['request_id'])
        if result is None:
            return not self.stop_requested
        owner = self.owner
        self.completed.append({'intent_id': owner['id'], 'session_id': self.session_id,
                               'queue_request_id': owner['request_id'], 'result': result, 'menu_recovery': True})
        self.owner = None
        policy = result.get('resident_policy') if isinstance(result, dict) else None
        valid = (isinstance(result, dict) and result.get('request_id') == owner['request_id']
                 and result.get('session_id') == owner['resident_session'] and valid_resident_policy(policy))
        if not valid:
            self.attention('menu_recovery_outcome_unconfirmed')
        elif policy['input_release_unconfirmed']:
            self.latch_input_release('owner_input_release_unconfirmed')
        elif policy['requires_handoff']:
            self.handoff_latched = True
            self.attention('encounter_requires_handoff')
        elif (result.get('status') != 'succeeded' or not isinstance(result.get('result'), dict)
              or result['result'].get('ok') is not True
              or any(k in result and result[k] is not False for k in ('unknown_outcome', 'post_uncertain', 'uncertain'))):
            self.attention('menu_recovery_outcome_unconfirmed')
        else:
            self.recovery_samples = 0
            self.next_observe = 0
            if self.recover_observation:
                self.phase, self.reason = 'recovering_observation', 'menu_recovery_awaiting_two_fresh_samples'
        return not self.stop_requested

    def observation_fallback(self, rpc, result=None):
        """Only current, same-session policy can authorize the automatic cancel path."""
        reader = getattr(self.q, 'session', None)
        if not callable(reader):
            return {'op': 'cancel'}  # Original non-mailbox queue interface.
        try:
            current = reader()
            policy = current['resident_policy']
            stamp = current['updated_at']
            valid = (isinstance(rpc.get('resident_session'), str) and bool(rpc['resident_session'])
                     and current.get('session_id') == rpc['resident_session']
                     and isinstance(rpc.get('resident_bridge'), dict)
                     and current.get('bridge_identity') == rpc['resident_bridge']
                     and isinstance(rpc['resident_bridge'].get('action_session'), str)
                     and bool(rpc['resident_bridge']['action_session'])
                     and type(stamp) in (int, float) and math.isfinite(stamp)
                     and 0 <= time.time() - stamp <= 3
                     and type(policy) is dict and type(policy.get('schema_version')) is int
                     and policy['schema_version'] == 1
                     and type(policy.get('requires_handoff')) is bool
                     and type(policy.get('input_release_unconfirmed')) is bool)
            if result is not None:
                valid = valid and result.get('request_id') == rpc['id'] and result.get('session_id') == rpc['resident_session']
            if not valid:
                raise ValueError('resident_policy_unconfirmed')
            if policy['input_release_unconfirmed']:
                self.latch_input_release('owner_input_release_unconfirmed')
                return None
            if policy['requires_handoff']:
                self.handoff_latched = True
                self.attention('encounter_requires_handoff')
                return None
            if current.get('state') not in ('ready', 'busy', 'paused'):
                raise ValueError('resident_policy_unconfirmed')
            return {'op': 'cancel', 'watchdog_observation_fallback': True,
                    'expected_resident_session': rpc['resident_session']}
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            self.handoff_latched = True
            self.attention('resident_policy_unconfirmed')
            return None

    def tick(self):
        bridge = getattr(self, '_coordination_owner', None)
        if bridge is not None:
            return bridge.tick_watchdog()
        if self.stopped:
            return
        if self.capability_tick():
            return
        if (self.input_release_latched or self.handoff_latched) and not self.stop_requested:
            return
        if self.poll_unconfirmed_owner():
            return
        if self.owner and not (self.stop_requested and self.owner.get('capability_owner')):
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
                    fallback = self.observation_fallback(self.rpc)
                    if fallback is None:
                        return
                    self.attention('observation_delayed_cancel_requested')
                    self.send('attention_cancel', fallback)
                return
            rpc = self.rpc
            kind = rpc['kind']
            self.rpc = None
            if kind == 'stop_cancel':
                self.cancel_confirmed = (result.get('status') == 'succeeded'
                                         and result.get('result', {}).get('ok') is True)
                self.stopped, self.phase = True, 'stopped'
                self.reason = 'operator_stop' if self.cancel_confirmed else 'input_release_unconfirmed'
                return
            policy = result.get('resident_policy')
            if (kind == 'attention_cancel' and isinstance(rpc.get('observation_fallback_session'), str)
                    and bool(rpc['observation_fallback_session'])
                    and result.get('request_id') == rpc['id']
                    and result.get('session_id') == rpc['observation_fallback_session']
                    and result.get('status') == 'failed'
                    and result.get('reason') == 'resident_policy_blocks_automatic_release'
                    and type(policy) is dict and type(policy.get('schema_version')) is int
                    and policy['schema_version'] == 1 and type(policy.get('requires_handoff')) is bool
                    and policy.get('input_release_unconfirmed') is True):
                self.latch_input_release('owner_input_release_unconfirmed')
                return
            if kind not in ('observe', 'fresh') and task_handoff_required(result):
                self.handoff_latched = True
                self.attention('encounter_requires_handoff')
                return
            if result.get('status') != 'succeeded':
                fallback = {'op': 'cancel'}
                if kind in ('observe', 'fresh'):
                    fallback = self.observation_fallback(rpc, result)
                    if fallback is None:
                        return
                if kind in ('observe', 'fresh') and not self.armed and not self.recover_observation:
                    self.next_observe = self.clock() + self.interval
                    return  # Sensor failures cannot cancel a manual owner's newer input.
                if (kind == 'start_combat' and result.get('status') == 'failed'
                        and result.get('reason') in ('combat_target_not_observed_hostile', 'combat_no_observed_hostile')):
                    self.phase, self.reason, self.next_observe = 'watching', 'target_changed_before_start', 0
                    return
                self.attention(kind + '_' + str(result.get('reason', result.get('status'))))
                if kind in ('observe', 'fresh', 'start_combat'):
                    self.send('attention_cancel', fallback)
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
                if 'resident_policy' in self.latest:
                    policy = self.latest['resident_policy']
                    if not valid_resident_policy(policy):
                        self.handoff_latched = True
                        self.attention('resident_policy_unconfirmed')
                        return
                    if policy['input_release_unconfirmed']:
                        self.latch_input_release('owner_input_release_unconfirmed')
                        return
                    if policy['requires_handoff']:
                        self.handoff_latched = True
                        self.attention('encounter_requires_handoff')
                        return
                elif ('requires_handoff' in self.latest
                        and self.latest['requires_handoff'] is not False):
                    if native_release_unconfirmed(self.latest.get('action')):
                        self.latch_input_release('owner_input_release_unconfirmed')
                    else:
                        self.handoff_latched = True
                        self.attention('encounter_requires_handoff')
                    return
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
                            or self.latest.get('action', {}).get('status') == 'running'
                            or (self.reason == 'menu_recovery_awaiting_two_fresh_samples'
                                or 'status' in state.get('client_action', {}))
                            and state.get('client_action', {}).get('status') not in ('idle', 'succeeded', 'failed', 'cancelled')):
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
                if self.execution_policy in EXPLICIT_POLICIES:
                    # Keep readiness for bounded lease admission without running
                    # hostile, health-loss, retreat or environmental tactics.
                    if context_of(state) is None or not safe_idle(self.latest):
                        self.attention(self.execution_policy + '_observation_not_safe_idle')
                        return
                    self.phase, self.reason = 'watching', self.execution_policy + '_observation_ready'
                    return
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
        # A submit acknowledgement can be lost after the resident request was
        # written. Claim only that known menu intent, including a result which
        # tick() just moved to completed, before ordinary inbox cancellation.
        claimed_menu = (dog.owner and dog.owner.get('menu_recovery') and dog.owner['id'] == path.stem
                        or any(done.get('menu_recovery') and done['intent_id'] == path.stem for done in dog.completed))
        if claimed_menu:
            destination = directory/'working'/path.name
            if destination.exists():
                raise ValueError('menu_recovery_claim_conflict')
            path.rename(destination)
            continue
        try:
            command = json.loads(path.read_text())
            session = command.pop('_watchdog_session_id', None)
            epoch = command.pop('_navigation_defense_epoch', None)
            stamp = command.pop('_menu_recovery_requested_at', None)
            if (session == dog.session_id and type(epoch) is int and epoch == dog.defense_epoch
                    and fresh_menu_request(stamp) and recovery_close_command(command) and dog.menu_close_ready()):
                continue
        except (ValueError, OSError, TypeError):
            pass
        write_json(directory/'results'/path.name,
                   {'request_id': path.stem, 'session_id': dog.session_id,
                    'status': 'cancelled', 'reason': 'watchdog_interrupted_replan_required'})
        path.unlink()



def pending_intent_counts(directory):
    """Lease heartbeats never occupy the resident gameplay/observation queue."""
    ordinary = controls = 0
    for path in (directory/'inbox').glob('*.json'):
        try:
            command = json.loads(path.read_text())
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            ordinary += 1
            continue
        if isinstance(command, dict) and command.get('op') in CONTROL_OPS:
            controls += 1
        else:
            ordinary += 1
    return {'pending': ordinary, 'pending_capability_controls': controls}

def read_policy_checkpoint(path, limit):
    """Bounded regular-file read; a policy pin must never follow a symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('execution_policy_checkpoint_not_regular')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('execution_policy_checkpoint_too_large')
    return json.loads(raw)


def enforce_execution_policy(directory, execution_policy):
    """An explicit-only control directory cannot switch its pinned policy."""
    if execution_policy not in EXECUTION_POLICIES:
        raise ValueError('invalid_execution_policy')
    path = directory / 'execution-policy.json'
    pinned = False
    if os.path.lexists(path):
        try:
            pin = read_policy_checkpoint(path, 1024)
            if (type(pin) is not dict or type(pin.get('schema_version')) is not int
                    or pin['schema_version'] != 1 or pin.get('execution_policy') not in EXPLICIT_POLICIES):
                raise ValueError('invalid_execution_policy_checkpoint')
            pinned = pin['execution_policy']
        except (OSError, ValueError, TypeError):
            raise ValueError('execution_policy_checkpoint_unconfirmed') from None
    elif os.path.lexists(directory / 'state.json'):
        try:
            prior = read_policy_checkpoint(directory / 'state.json', 128 * 1024)
            if not isinstance(prior, dict):
                raise ValueError('invalid_previous_watchdog_state')
        except (OSError, ValueError, TypeError):
            raise ValueError('execution_policy_previous_state_unconfirmed') from None
        if prior.get('execution_policy') in EXPLICIT_POLICIES:
            raise ValueError('execution_policy_published_' + prior['execution_policy'] + '_pin_missing')
    if pinned and execution_policy != pinned:
        raise ValueError('execution_policy_pinned_' + pinned + '_requires_explicit_flag')
    if execution_policy in EXPLICIT_POLICIES and not os.path.lexists(path):
        # Before any observation or queue dispatch, fsync the policy selection.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'schema_version': 1, 'execution_policy': execution_policy}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def run(queue, directory, watchdog_class=Watchdog, *, coordination_factory=None, execution_policy='standard'):
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    for name in ('inbox', 'working', 'results'):
        (directory/name).mkdir(exist_ok=True)
    lock = (directory/'owner.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (directory/'STOP').exists():
        raise ValueError('remove_previous_STOP_explicitly_before_new_run')
    try:
        enforce_execution_policy(directory, execution_policy)
        if execution_policy in EXPLICIT_POLICIES and coordination_factory is not None:
            raise ValueError(execution_policy + '_coordination_not_supported')
        dog = (watchdog_class(QueueClient(queue), execution_policy=execution_policy)
               if execution_policy != 'standard' else watchdog_class(QueueClient(queue)))
    except BaseException:
        lock.close()
        raise
    dog.capability_directory = directory
    capability_marker = directory/'capability-owner.json'
    previous_state = directory/'state.json'
    if capability_marker.exists():
        try:
            marker = json.loads(capability_marker.read_text())
            if (marker.get('schema_version') != 1 or type(marker.get('active')) is not bool
                    or marker['active']):
                dog.handoff_latched = True
                dog.attention('previous_capability_owner_requires_reconciliation')
        except (OSError, ValueError, TypeError):
            dog.handoff_latched = True
            dog.attention('previous_capability_owner_checkpoint_unconfirmed')
    elif previous_state.exists():
        try:
            prior = json.loads(previous_state.read_text())
            if prior.get('capability_lease') is not None:
                dog.handoff_latched = True
                dog.attention('previous_capability_owner_requires_reconciliation')
        except (OSError, ValueError, TypeError):
            dog.handoff_latched = True
            dog.attention('previous_watchdog_state_unconfirmed')
    coordination = coordination_factory(dog) if coordination_factory is not None else None
    for folder in ('inbox', 'working'):
        for path in (directory/folder).glob('*.json'):
            write_json(directory/'results'/path.name, {'request_id': path.stem, 'session_id': dog.session_id, 'status': 'uncertain', 'reason': 'previous_run_not_replayed'})
            path.unlink()
    try:
        while not dog.stopped:
            if (directory/'STOP').exists(): dog.stop()
            try:
                for control_path in sorted((directory/'inbox').glob('*.json')):
                    control = json.loads(control_path.read_text())
                    if control.get('op') not in CONTROL_OPS:
                        continue
                    control_session = control.pop('_watchdog_session_id', None)
                    if control_session != dog.session_id:
                        dog.capability_complete(control_path.stem, 'cancelled', 'stale_watchdog_session')
                    else:
                        dog.capability_control(control_path.stem, control)
                    control_path.rename(directory/'working'/control_path.name)
                dog.tick()
                if coordination is not None:coordination.tick()
                dog.persist_telemetry(directory)
                cancel_waiting_intents(directory, dog)
                if dog.completed:
                    # Publish the current owner/context before its acknowledgement.
                    # The durable lease marker is already fsynced at acquisition.
                    write_json(directory/'state.json', {**dog.status(),
                        **({'coordination':coordination.status()} if coordination is not None else {}),
                        **pending_intent_counts(directory),
                        'updated_at': time.time(), 'pid': os.getpid()})
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
            write_json(directory/'state.json', {**dog.status(), **({'coordination':coordination.status()} if coordination is not None else {}), **pending_intent_counts(directory),
                                                   'updated_at': time.time(), 'pid': os.getpid()})
            time.sleep(dog.poll_interval())
    except KeyboardInterrupt:
        dog.stop()
        while not dog.stopped:
            dog.tick()
            if coordination is not None:coordination.tick()
            write_json(directory/'state.json', {**dog.status(), **({'coordination':coordination.status()} if coordination is not None else {}), **pending_intent_counts(directory),
                                                   'updated_at': time.time(), 'pid': os.getpid()})
            time.sleep(dog.poll_interval())
    finally:
        lock.close()


if __name__ == '__main__':
    raise SystemExit('Use watchdog.py for the ranged-melee candidate entry point')
