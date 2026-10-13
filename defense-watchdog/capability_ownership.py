"""Bounded logical ownership of the existing gateway, never another transport.

A lease is tied to a watchdog epoch, resident session and observed game context.
It admits only guarded native actions and explicit capability observations. The
native action still owns per-tick safety. Expiry is a pause, not permission for
legacy defense to take over an unconfirmed input owner.
"""
from copy import deepcopy
import math
import json
import os
import re
import uuid

from resident_controller.action_safety import task_release_unconfirmed, task_handoff_required

CONTROL_OPS = frozenset({'capability_acquire', 'capability_heartbeat', 'capability_release', 'capability_cancel'})
ACTIONS = frozenset({'follow_path', 'break_block', 'place_block', 'click_slot',
    'combat_entity', 'recover_environment', 'boat_drive', 'boat_mount', 'boat_dismount',
    'interact_block', 'use_item', 'select_hotbar', 'close_menu', 'attack_entity', 'shoot_entity', 'gateway_pearl',
    'movement_budget_start', 'movement_budget_finish'})
CONTEXT = ('world_generation', 'dimension', 'player_uuid', 'action_session')
TERMINAL = frozenset({'idle', 'succeeded', 'failed', 'cancelled'})
HEARTBEAT_SECONDS = 3.0
MAX_DURATION_MS = 86400000
TRANSITION_PAIRS = frozenset({('minecraft:overworld', 'minecraft:the_nether'),
    ('minecraft:the_nether', 'minecraft:overworld'), ('minecraft:overworld', 'minecraft:the_end'),
    ('minecraft:the_end', 'minecraft:overworld')})
MAX_TRANSITION_OBSERVATIONS = 128


def context_of(state):
    if not isinstance(state, dict):
        return None
    try:
        values = (state['world']['world_generation'], state['world']['dimension'],
                  state['player']['uuid'], state['client_action']['action_session'])
    except (KeyError, TypeError):
        return None
    return dict(zip(CONTEXT, values)) if all(isinstance(x, str) and x for x in values) else None


def integrated_server_instance_of(state):
    """Native process-local identity, never a caller-supplied save path/name."""
    world = state.get('world') if isinstance(state, dict) else None
    value = world.get('integrated_server_instance') if isinstance(world, dict) else None
    try:
        return value if isinstance(value, str) and value == str(uuid.UUID(value)) else None
    except (ValueError, AttributeError):
        return None


def safe_idle(payload):
    try:
        s = payload['state']; p = s['player']
        return (s.get('focused') is True and s.get('private_singleplayer') is True
            and type(s.get('screen_open')) is bool and s.get('paused') is False
            and p.get('alive') is True and type(p.get('health')) in (int, float)
            and math.isfinite(p['health']) and p['health'] > 0
            and p.get('dimension') == s['world'].get('dimension')
            and s.get('held_inputs', {}).get('neutral') is True
            and s['client_action'].get('status') in TERMINAL
            and payload.get('action', {}).get('status') in TERMINAL
            and payload.get('combat', {}).get('active') is False
            and payload.get('status', {}).get('held_mappings') == [])
    except (KeyError, TypeError):
        return False


def safe_policy(policy):
    return (isinstance(policy, dict) and type(policy.get('schema_version')) is int
            and policy['schema_version'] == 1 and policy.get('requires_handoff') is False
            and policy.get('input_release_unconfirmed') is False)


def unsafe_result(result):
    if not isinstance(result, dict):
        return True
    policy = result.get('resident_policy')
    return (result.get('status') == 'uncertain' or task_release_unconfirmed(result)
        or task_handoff_required(result)
        or any(k in result and result[k] is not False for k in
               ('unknown_outcome', 'post_uncertain', 'uncertain', 'input_release_unconfirmed', 'requires_handoff'))
        or policy is not None and (not isinstance(policy, dict)
            or policy.get('requires_handoff') is not False or policy.get('input_release_unconfirmed') is not False))


class CapabilityOwnership:
    def capability_checkpoint(self, lease):
        directory = getattr(self, 'capability_directory', None)
        if directory is None:
            raise ValueError('capability_durable_directory_missing')
        path = directory/'capability-owner.json'
        temporary = directory/('.capability-owner-' + uuid.uuid4().hex)
        value = {'schema_version': 1, 'active': lease is not None,
                 'watchdog_session': self.session_id,
                 'owner_id': lease['owner_id'] if lease else None,
                 'context': deepcopy(lease['context']) if lease else None,
                 'defense_epoch': lease['defense_epoch'] if lease else None,
                 'resident_session': lease['resident_session'] if lease else None,
                 'integrated_server_instance': lease.get('integrated_server_instance') if lease else None,
                 'active_request_id': self.owner['id'] if lease and self.owner else None,
                 'queue_request_id': self.owner['request_id'] if lease and self.owner else None,
                 'last_mutation': deepcopy(lease.get('last_mutation')) if lease else None}

        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def capability_status(self):
        lease = getattr(self, 'capability_lease', None)
        visible = None
        if lease:
            visible = {k: deepcopy(lease[k]) for k in ('owner_id', 'context', 'defense_epoch', 'resident_session', 'state')}
            visible.update(remaining_ms=max(0, int((lease['deadline'] - self.clock()) * 1000)),
                heartbeat_remaining_ms=max(0, int((lease['heartbeat'] - self.clock()) * 1000)),
                post_observation_required=lease['post_observation_required'])
        return {'capability_lease_schema_version': 1, 'capability_lease': visible,
                'capability_cancel_schema_version': 1,
                'scoped_native_preflight': deepcopy((self.latest or {}).get('state', {}).get('scoped_native_preflight')),
                'private_singleplayer': (self.latest or {}).get('state', {}).get('private_singleplayer') is True,
                'capability_context': context_of((self.latest or {}).get('state'))}

    def capability_complete(self, intent_id, status, reason, **values):
        self.completed.append({'intent_id': intent_id, 'session_id': self.session_id,
            'queue_request_id': None, 'result': {'status': status, 'reason': reason,
                'gameplay_effect_confirmed': False, **values}})
        return True

    def capability_pause(self, reason):
        lease = getattr(self, 'capability_lease', None)
        if lease and lease['state'] == 'active':
            lease['state'] = 'paused'
            lease['reason'] = reason
            self.handoff_latched = True
            self.attention(reason)

    def capability_expired(self):
        lease = getattr(self, 'capability_lease', None)
        if not lease:
            return False
        if lease['state'] != 'active':
            return True
        transition = lease.get('transition')
        if transition is not None and self.clock() >= transition['deadline']:
            self.capability_pause('capability_transition_deadline_expired')
            return True
        if self.clock() >= lease['deadline'] or self.clock() >= lease['heartbeat']:
            self.capability_pause('capability_deadline_expired' if self.clock() >= lease['deadline']
                                  else 'capability_heartbeat_expired')
            return True
        return False

    def capability_control(self, intent_id, command):
        """Consume a same-inbox lease control. It never enters the resident queue."""
        op = command.get('op')
        if op == 'capability_cancel':
            return self.capability_cancel(intent_id, command)
        allowed = {'op', 'owner_id', 'expected_defense_epoch'}
        if op == 'capability_acquire':
            allowed |= {'expected_context', 'duration_ms'}
        if set(command) != allowed or not isinstance(command.get('owner_id'), str) or not re.fullmatch(r'[0-9a-f]{32}', command['owner_id']):
            return self.capability_complete(intent_id, 'failed', 'invalid_capability_control')
        lease = getattr(self, 'capability_lease', None)
        if lease:
            self.capability_expired()
        reason = None
        if self.stop_requested or self.stopped:
            reason = 'watchdog_stopping_or_stopped'
        elif self.input_release_latched or self.handoff_latched or not self.armed:
            reason = 'capability_owner_requires_handoff'
        elif type(command['expected_defense_epoch']) is not int or command['expected_defense_epoch'] != self.defense_epoch:
            reason = 'capability_defense_epoch_changed'
        elif op == 'capability_acquire':
            duration = command['duration_ms']
            context = context_of((self.latest or {}).get('state'))
            if lease is not None:
                reason = 'capability_owner_already_claimed'
            elif type(duration) is not int or not 100 <= duration <= MAX_DURATION_MS:
                reason = 'invalid_capability_duration'
            elif context is None or command['expected_context'] != context:
                reason = 'capability_context_changed'
            elif (getattr(self, '_coordination_owner', None) is not None
                  or self.owner or self.phase != 'watching' or self.started_target
                  or self.rpc and self.rpc['kind'] not in ('observe', 'fresh')
                  or getattr(self, 'ranged_move', None)
                  or getattr(getattr(self, 'environment', None), 'active', False)
                  or self.observed_at is None or not 0 <= self.clock() - self.observed_at <= .8
                  or not safe_idle(self.latest)):
                reason = 'capability_admission_not_idle'
            else:
                session = self.q.session()
                policy = session.get('resident_policy')
                if (not isinstance(session.get('session_id'), str) or not session['session_id']
                        or session.get('state') not in ('ready', 'busy') or unsafe_result({'resident_policy': policy})
                        or not safe_policy(policy)):
                    reason = 'capability_resident_policy_unconfirmed'
                else:
                    now = self.clock()
                    self.capability_lease = {'owner_id': command['owner_id'], 'context': context,
                        'integrated_server_instance': integrated_server_instance_of((self.latest or {}).get('state')),
                        'defense_epoch': self.defense_epoch, 'resident_session': session['session_id'],
                        'deadline': now + duration / 1000, 'heartbeat': min(now + HEARTBEAT_SECONDS, now + duration / 1000),
                        'state': 'active', 'post_observation_required': False}
                    try:
                        self.capability_checkpoint(self.capability_lease)
                    except (OSError, ValueError):
                        self.capability_pause('capability_acquisition_checkpoint_unconfirmed')
                        raise
                    self.reason = 'capability_owner_acquired'
        elif not lease or lease['owner_id'] != command['owner_id']:
            reason = 'capability_owner_mismatch'
        elif op == 'capability_heartbeat':
            lease['heartbeat'] = min(lease['deadline'], self.clock() + HEARTBEAT_SECONDS)
        elif op == 'capability_release':
            current = self.q.session()
            if (current.get('session_id') != lease['resident_session']
                    or not safe_policy(current.get('resident_policy'))
                    or current.get('state') != 'ready' or current.get('pending') != 0
                    or current.get('active_request_id') is not None):
                self.capability_pause('capability_release_resident_not_idle')
                reason = 'capability_release_resident_not_idle'
            elif (self.owner or self.rpc or lease['post_observation_required']
                    or self.observed_at is None or not 0 <= self.clock() - self.observed_at <= .8
                    or context_of((self.latest or {}).get('state')) != lease['context'] or not safe_idle(self.latest)):
                reason = 'capability_release_needs_fresh_idle_observation'
            else:
                self.capability_checkpoint(None)
                self.capability_lease = None
                self.phase, self.reason = 'watching', 'capability_owner_released'
                self.next_observe = 0
        if reason:
            return self.capability_complete(intent_id, 'failed', reason)
        return self.capability_complete(intent_id, 'succeeded', op + '_acknowledged',
                                       capability_lease=self.capability_status()['capability_lease'])

    def capability_cancel(self, intent_id, command):
        """Cancel only the currently bound capability intent through its resident."""
        required = {'op', 'owner_id', 'expected_defense_epoch', 'expected_intent_id', 'expected_action_session'}
        lease, owner = getattr(self, 'capability_lease', None), self.owner
        if (set(command) != required or not lease or not owner
                or lease.get('state') != 'active' or owner.get('reported')
                or command.get('owner_id') != lease['owner_id']
                or owner.get('capability_owner') != lease['owner_id']
                or type(command.get('expected_defense_epoch')) is not int
                or command['expected_defense_epoch'] != lease['defense_epoch']
                or self.defense_epoch != lease['defense_epoch']
                or command.get('expected_intent_id') != owner['id']
                or command.get('expected_action_session') != lease['context']['action_session']
                or owner.get('capability_op') != 'action'):
            return self.capability_complete(intent_id, 'failed', 'exact_cancel_owner_or_target_mismatch')
        existing = lease.get('cancel_control')
        if existing:
            # Never send another cancel after an unknown or acknowledged write.
            return self.capability_complete(intent_id, 'failed', 'exact_cancel_already_attempted')
        session = self.q.session()
        if session.get('session_id') != lease['resident_session'] or not safe_policy(session.get('resident_policy')):
            return self.capability_complete(intent_id, 'failed', 'exact_cancel_resident_changed')
        qid = uuid.uuid4().hex
        body = {'op': 'capability_cancel_exact', 'expected_request_id': owner['request_id'],
                'expected_resident_session': lease['resident_session'],
                'expected_action_session': lease['context']['action_session'],
                'expected_action_id': uuid.uuid5(uuid.UUID(lease['resident_session']), owner['request_id'] + ':1').hex}
        lease['cancel_control'] = {'intent_id': intent_id, 'queue_request_id': qid,
                                   'original_intent_id': owner['id'], 'state': 'reserved'}
        self.capability_checkpoint(lease)
        try:
            if self.q.submit(body, request_id=qid) != qid:
                raise ValueError('exact_cancel_queue_identity_changed')
            lease['cancel_control']['state'] = 'submitted'
            self.capability_checkpoint(lease)
        except (OSError, ValueError):
            lease['cancel_control']['state'] = 'unknown'
            self.capability_pause('exact_cancel_submission_unconfirmed')
            raise
        return True

    def capability_cancel_tick(self, lease):
        cancel = lease.get('cancel_control')
        if not cancel or cancel.get('state') != 'submitted':
            return
        result = self.q.result(cancel['queue_request_id'])
        if result is None:
            return
        good = (isinstance(result, dict) and result.get('request_id') == cancel['queue_request_id']
                and result.get('session_id') == lease['resident_session']
                and result.get('status') == 'succeeded' and not unsafe_result(result)
                and result.get('exact_cancel', {}).get('original_request_id') == lease.get('last_mutation', {}).get('queue_request_id')
                and result.get('exact_cancel', {}).get('input_release_confirmed') is True)
        cancel['state'] = 'confirmed' if good else 'unknown'
        self.capability_checkpoint(lease)
        if not good:
            self.capability_pause('exact_cancel_release_unconfirmed')
        self.completed.append({'intent_id': cancel['intent_id'], 'session_id': self.session_id,
            'queue_request_id': cancel['queue_request_id'],
            'result': {**result, 'status': 'succeeded' if good else 'uncertain',
                       'reason': 'exact_cancel_confirmed' if good else 'exact_cancel_release_unconfirmed'}})

    def capability_submit(self, intent_id, command, *, queue_request_id=None):
        """Return None for legacy work, otherwise a consumed/deferred decision."""
        if command.get('op') in CONTROL_OPS:
            return self.capability_control(intent_id, command)
        lease = getattr(self, 'capability_lease', None)
        owner_id = command.get('_capability_owner_id')
        if lease is None and owner_id is None:
            return None
        if (not lease or owner_id != lease['owner_id'] or self.capability_expired()
                or self.stop_requested or self.stopped or not self.armed
                or self.input_release_latched or self.handoff_latched):
            return self.capability_complete(intent_id, 'cancelled', 'capability_owner_unavailable')
        if self.owner or self.rpc:
            return False
        body = deepcopy(command)
        body.pop('_capability_owner_id', None)
        epoch = body.pop('_navigation_defense_epoch', None)
        expected_dimension = body.pop('_capability_expected_dimension', None)
        if epoch != lease['defense_epoch'] or type(epoch) is not int or self.defense_epoch != epoch:
            return self.capability_complete(intent_id, 'cancelled', 'capability_defense_epoch_changed')
        op = body.get('op')
        if op == 'observe':
            valid = (expected_dimension is None and body.get('capability_observation') is True
                and set(body) <= {'op', 'capability_observation', 'capability_survey', 'terrain', 'radius', 'vertical', 'entity_radius'}
                and type(body.get('entity_radius', 8)) is int and 1 <= body.get('entity_radius', 8) <= 128
                and type(body.get('radius', 4)) is int and 1 <= body.get('radius', 4) <= 16
                and type(body.get('vertical', 4)) is int and 2 <= body.get('vertical', 4) <= 8)
        elif op == 'action':
            context = lease['context']; guard = body.get('capability_guard')
            scoped = body.get('scoped_native_preflight')
            scoped_valid = scoped is None or (isinstance(scoped, dict)
                and set(scoped) == {'version', 'profile', 'owner_id', 'owner_generation', 'job_id', 'defense_epoch'}
                and scoped.get('version') == 'scoped-native-preflight/1'
                and scoped.get('owner_id') == lease['owner_id']
                and type(scoped.get('defense_epoch')) is int and scoped['defense_epoch'] == lease['defense_epoch']
                and type(scoped.get('owner_generation')) is int and scoped['owner_generation'] > 0
                and isinstance(scoped.get('job_id'), str) and 0 < len(scoped['job_id']) <= 80
                and scoped.get('profile') in (self.latest or {}).get('state', {}).get('scoped_native_preflight', {}).get('profiles', {}))
            valid = (scoped_valid and not lease['post_observation_required']
                and body.get('action') in ACTIONS and isinstance(guard, dict)
                and (expected_dimension is None or body.get('action') == 'follow_path'
                     and (context['dimension'], expected_dimension) in TRANSITION_PAIRS
                     and lease.get('integrated_server_instance') is not None
                     and integrated_server_instance_of((self.latest or {}).get('state')) == lease['integrated_server_instance'])
                and guard == (self.latest or {}).get('state', {}).get('capability_guard')
                and type(guard.get('schema_version')) is int and guard['schema_version'] == 1
                and self.observed_at is not None and 0 <= self.clock() - self.observed_at <= .8
                and all(body.get('expected_' + k) == context[k] for k in CONTEXT)
                and type(body.get('timeout_ms', 15000)) is int and 50 <= body.get('timeout_ms', 15000) <= 60000
                and self.clock() + body.get('timeout_ms', 15000) / 1000 <= lease['deadline'])
        else:
            valid = False
        if not valid:
            return self.capability_complete(intent_id, 'cancelled', 'capability_command_out_of_scope')
        session = self.q.session()
        if session.get('session_id') != lease['resident_session'] or not safe_policy(session.get('resident_policy')):
            self.capability_pause('capability_resident_session_or_policy_changed')
            return self.capability_complete(intent_id, 'cancelled', 'capability_resident_session_or_policy_changed')
        request_id = queue_request_id or uuid.uuid4().hex
        self.owner = {'id': intent_id, 'request_id': request_id, 'capability_owner': owner_id,
                      'resident_session': lease['resident_session'], 'capability_op': op,
                      'expected_dimension': expected_dimension}
        if expected_dimension is not None:
            self.owner['transition_deadline'] = min(lease['deadline'], self.clock() + body['timeout_ms'] / 1000)
            self.owner['transition_source'] = deepcopy(lease['context'])
        if op == 'action':
            lease['post_observation_required'] = True
            lease.pop('transition', None)
            lease['last_mutation'] = {'intent_id': intent_id, 'queue_request_id': request_id,
                                      'resident_session': lease['resident_session']}
        # Install exact identity before write; an ambiguous submit cannot lose it.
        try:
            self.capability_checkpoint(lease)
            if self.q.submit(body, request_id=request_id) != request_id:
                raise ValueError('capability_queue_identity_changed')
        except (OSError, ValueError):
            self.capability_pause('capability_submission_unconfirmed')
            raise
        return True

    def capability_capture(self, payload):
        lease = self.capability_lease
        if unsafe_result(payload) or not safe_policy(payload.get('resident_policy')) or not safe_idle(payload):
            self.capability_pause('capability_observation_not_safe_idle')
            return False
        current = context_of(payload.get('state'))
        transition = lease.get('transition')
        awaiting_transition = False
        if transition is not None:
            mutation = lease.get('last_mutation', {})
            state_action = payload.get('state', {}).get('client_action', {})
            action = payload.get('action', {})
            if (self.clock() >= transition['deadline']
                    or transition['observations_remaining'] <= 0):
                self.capability_pause('capability_transition_deadline_expired' if self.clock() >= transition['deadline']
                                      else 'capability_transition_observation_budget_exhausted')
                return False
            if (transition['source_context'] != lease['context']
                    or integrated_server_instance_of(payload.get('state')) != lease.get('integrated_server_instance')
                    or mutation.get('queue_request_id') != transition['request_id']
                    or mutation.get('intent_id') != transition['intent_id']
                    or mutation.get('resident_session') != lease['resident_session']
                    or any(a.get('action_id') != transition['action_id']
                           or a.get('action_session') != lease['context']['action_session']
                           or a.get('status') != transition['native_status']
                           or a.get('result', {}).get('input_release_confirmed') is not True
                           for a in (state_action, action))):
                self.capability_pause('capability_transition_action_binding_changed')
                return False
            transition['observations_remaining'] -= 1
            awaiting_transition = current == lease['context']
        if current != lease['context']:
            if (transition and current and current['dimension'] == transition['dimension']
                    and current['world_generation'] != lease['context']['world_generation']
                    and all(current[k] == lease['context'][k] for k in ('player_uuid', 'action_session'))):
                lease['context'] = current
                lease.pop('transition')
                self.capability_checkpoint(lease)
            else:
                self.capability_pause('capability_observation_context_changed')
                return False
        self.latest, self.observed_at = payload, self.clock()
        self.observation_received(payload, 'capability_observe')
        self.targeting.observe_health(payload['state'], self.clock())
        # A source-world read proves a known terminal action, not the expected
        # crossing. Keep the one-action barrier until that crossing is observed.
        lease['post_observation_required'] = awaiting_transition
        return True

    def capability_tick(self):
        lease = getattr(self, 'capability_lease', None)
        if not lease or self.stop_requested:
            return False
        self.capability_expired()
        self.capability_cancel_tick(lease)
        if self.owner and self.owner.get('capability_owner'):
            owner = self.owner
            result = self.q.result(owner['request_id'])
            if result is None or owner.get('reported'):
                return True
            valid = (isinstance(result, dict) and result.get('request_id') == owner['request_id']
                     and result.get('session_id') == owner['resident_session']
                     and result.get('status') in ('succeeded', 'failed', 'cancelled', 'uncertain'))
            if not valid:
                self.capability_pause('capability_result_identity_unconfirmed')
                return True
            self.completed.append({'intent_id': owner['id'], 'session_id': self.session_id,
                                   'queue_request_id': owner['request_id'], 'result': result})
            owner['reported'] = True
            current_session = self.q.session()
            if (unsafe_result(result) or current_session.get('session_id') != owner['resident_session']
                    or not safe_policy(current_session.get('resident_policy'))):
                if task_release_unconfirmed(result):
                    self.input_release_latched = True
                self.capability_pause('capability_owner_outcome_unconfirmed')
                return True  # Preserve exact owner ID and unknown latch; no cancel/replay.
            if owner['capability_op'] == 'action' and owner.get('expected_dimension'):
                native = result.get('action') or result.get('result', {}).get('action')
                expected_id = uuid.uuid5(uuid.UUID(owner['resident_session']), owner['request_id'] + ':1').hex
                if (isinstance(native, dict) and native.get('action_id') == expected_id
                        and native.get('action_session') == lease['context']['action_session']
                        and native.get('result', {}).get('input_release_confirmed') is True
                        and (native.get('status') == 'succeeded' or native.get('status') == 'cancelled'
                             and native.get('reason') in ('world_changed', 'world_or_player_changed', 'world_transition',
                                 'capability_world_changed', 'capability_dimension_changed'))):
                    lease['transition'] = {'dimension': owner['expected_dimension'], 'request_id': owner['request_id'],
                        'intent_id': owner['id'], 'action_id': expected_id, 'native_status': native['status'],
                        'source_context': deepcopy(owner['transition_source']),
                        'deadline': owner['transition_deadline'], 'observations_remaining': MAX_TRANSITION_OBSERVATIONS}
            if owner['capability_op'] == 'observe' and result['status'] == 'succeeded':
                self.capability_capture(result.get('result', {}))
            elif owner['capability_op'] == 'action' and result.get('action_admission', {}).get('admitted') is False:
                lease['post_observation_required'] = False
            self.owner = None
        if self.rpc:
            # Only an already-issued read can coexist with initial acquisition.
            rpc = self.rpc
            result = self.q.result(rpc['id'])
            if result is not None:
                self.rpc = None
                if result.get('status') != 'succeeded' or unsafe_result(result):
                    self.capability_pause('capability_initial_observation_unconfirmed')
                else:
                    self.capability_capture(result.get('result', {}))
            elif self.clock() - rpc['started'] > 2:
                self.capability_pause('capability_initial_observation_delayed')
        return True
