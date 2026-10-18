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

from fall_rescue_adjudication import OPS as ADJUDICATION_OPS
CONTROL_OPS = frozenset({'external_stop_acquire', 'capability_acquire', 'capability_heartbeat', 'capability_release', 'capability_cancel'}) | ADJUDICATION_OPS
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
        if 'managed_navigation' in s or 'managed_navigation_status' in s:
            navigation=s.get('managed_navigation_status')
            if (not isinstance(navigation,dict) or type(navigation.get('managed_navigation_schema_version')) is not int
                    or navigation.get('managed_navigation_schema_version')!=1 or navigation.get('input_owned') is not False
                    or navigation.get('unknown_outcome_quarantined') is not False):return False
        if 'external_navigation' in s or 'external_navigation_status' in s:
            navigation=s.get('external_navigation_status')
            if (not isinstance(navigation,dict) or type(navigation.get('external_navigation_schema_version')) is not int
                    or navigation.get('external_navigation_schema_version')!=1 or navigation.get('input_owned') is not False
                    or navigation.get('unknown_outcome_quarantined') is not False):return False
        if 'external_controller' in s:
            external=s['external_controller']
            if (not isinstance(external,dict) or type(external.get('schema_version')) is not int
                    or external.get('schema_version')!=1 or external.get('idle_proven') is not True
                    or external.get('world_generation')!=s['world'].get('world_generation')
                    or external.get('player_uuid')!=p.get('uuid')
                    or external.get('action_session')!=s['client_action'].get('action_session')
                    or external.get('source_tick')!=s['world'].get('game_time')):
                return False
        if 'native_fall_rescue_status' in s or 'native_fall_rescue' in s:
            rescue=s.get('native_fall_rescue_status')
            if (not isinstance(rescue,dict) or type(rescue.get('fall_rescue_schema_version')) is not int
                    or rescue.get('fall_rescue_schema_version')!=1 or rescue.get('input_owned') is not False
                    or rescue.get('unknown_outcome_quarantined') is not False):
                return False
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
                 'last_mutation': deepcopy(lease.get('last_mutation')) if lease else None,
                 'fall_rescue_arm': deepcopy(lease.get('fall_rescue_arm')) if lease else None,
                 'owner_mode': lease.get('owner_mode', 'ordinary') if lease else None,
                 'external_navigation': deepcopy(lease.get('external_navigation')) if lease else None,
                 'managed_navigation': deepcopy(lease.get('managed_navigation')) if lease else None,
                 'managed_navigation_cancel_submitted': lease.get('managed_navigation_cancel_submitted',False) if lease else False,
                 'cleanup_release_pending': deepcopy(lease.get('cleanup_release_pending')) if lease else None}

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
            visible['owner_mode'] = lease.get('owner_mode', 'ordinary')
            visible.update(remaining_ms=max(0, int((lease['deadline'] - self.clock()) * 1000)),
                heartbeat_remaining_ms=max(0, int((lease['heartbeat'] - self.clock()) * 1000)),
                post_observation_required=lease['post_observation_required'],
                cleanup_only=lease.get('cleanup_started') is True)
        return {'capability_cleanup_observation_schema_version': 1,
                'capability_lease_schema_version': 1, 'capability_lease': visible,
                'capability_cancel_schema_version': 1,
                'managed_navigation_owner_control': 'managed-navigation-owner-control/1',
                'managed_navigation': deepcopy((self.latest or {}).get('state', {}).get('managed_navigation')),
                'managed_navigation_source': deepcopy((self.latest or {}).get('state', {}).get('external_controller')),
                'external_navigation_owner_control': 'external-navigation-owner-control/1',
                'external_navigation': deepcopy((self.latest or {}).get('state', {}).get('external_navigation')),
                'external_navigation_source': deepcopy((self.latest or {}).get('state', {}).get('external_controller')),
                'native_fall_rescue_owner_guard': 'native-fall-rescue-owner-guard/1',
                'fall_rescue_original_adjudication': 'native-fall-rescue-original-adjudication/1',
                'explicit_new_job_only': getattr(self,'explicit_after_adjudication',False),
                'native_fall_rescue_attached_policy': 'native-fall-rescue-attached-policy/1',
                'native_fall_rescue': deepcopy((self.latest or {}).get('state', {}).get('native_fall_rescue')),
                'scoped_native_preflight': deepcopy((self.latest or {}).get('state', {}).get('scoped_native_preflight')),
                'private_singleplayer': (self.latest or {}).get('state', {}).get('private_singleplayer') is True,
                'capability_context': context_of((self.latest or {}).get('state'))}

    def external_stop_ready(self):
        from external_navigation_owner import admission_ready
        return admission_ready(self)

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
        if op in ADJUDICATION_OPS:
            from fall_rescue_adjudication import submit
            return submit(self,intent_id,command)
        if op == 'capability_cancel':
            return self.capability_cancel(intent_id, command)
        allowed = {'op', 'owner_id', 'expected_defense_epoch'}
        if op in ('capability_acquire', 'external_stop_acquire'):
            allowed |= {'expected_context', 'duration_ms'}
        if set(command) != allowed or not isinstance(command.get('owner_id'), str) or not re.fullmatch(r'[0-9a-f]{32}', command['owner_id']):
            return self.capability_complete(intent_id, 'failed', 'invalid_capability_control')
        lease = getattr(self, 'capability_lease', None)
        if lease:
            self.capability_expired()
        reason = None
        # Only values evaluated by the original short-circuit admission gate are
        # recorded. Proof construction performs no read, callback or new check.
        from resident_controller.acquisition_refusal import CHECKS, make_proof, valid_command, valid_readiness
        refusal_command = deepcopy(command)
        refusal_session = self.session_id
        admission_checks = dict.fromkeys(CHECKS)
        admission_age = None
        def admission_check(name, value):
            admission_checks[name] = bool(value)
            return value
        if self.stop_requested or self.stopped:
            reason = 'watchdog_stopping_or_stopped'
        elif self.input_release_latched or self.handoff_latched or not self.armed:
            reason = 'capability_owner_requires_handoff'
        elif type(command['expected_defense_epoch']) is not int or command['expected_defense_epoch'] != self.defense_epoch:
            reason = 'capability_defense_epoch_changed'
        elif op in ('capability_acquire', 'external_stop_acquire'):
            duration = command['duration_ms']
            context = context_of((self.latest or {}).get('state'))
            if lease is not None:
                reason = 'capability_owner_already_claimed'
            elif type(duration) is not int or not 100 <= duration <= MAX_DURATION_MS:
                reason = 'invalid_capability_duration'
            elif context is None or command['expected_context'] != context:
                reason = 'capability_context_changed'
            elif (not admission_check('no_coordination_owner', getattr(self, '_coordination_owner', None) is None)
                  or not admission_check('no_owner', not self.owner)
                  or not admission_check('watching', self.phase == 'watching')
                  or not admission_check('no_started_target', not self.started_target)
                  or not admission_check('read_only_rpc', not self.rpc or self.rpc['kind'] in ('observe', 'fresh'))
                  or not admission_check('no_ranged_move', not getattr(self, 'ranged_move', None))
                  or not admission_check('no_environment_action', not getattr(getattr(self, 'environment', None), 'active', False))
                  or not admission_check('observation_present', self.observed_at is not None)
                  or not admission_check('observation_fresh', 0 <= (admission_age := self.clock() - self.observed_at) <= .8)
                  or not admission_check('idle_predicate', self.external_stop_ready() if op == 'external_stop_acquire' else safe_idle(self.latest))):
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
                        'state': 'active', 'owner_mode': 'external_stop' if op == 'external_stop_acquire' else 'ordinary',
                        'post_observation_required': False}
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
            cleanup = lease.get('cleanup_observation')
            if lease.get('cleanup_started'):
                return self.capability_release_cleanup(intent_id, command, lease, cleanup)
            current = self.q.session()
            if (current.get('session_id') != lease['resident_session']
                    or not safe_policy(current.get('resident_policy'))
                    or current.get('state') != 'ready' or current.get('pending') != 0
                    or current.get('active_request_id') is not None):
                self.capability_pause('capability_release_resident_not_idle')
                reason = 'capability_release_resident_not_idle'
            elif (self.owner or self.rpc or lease.get('fall_rescue_arm') is not None or lease['post_observation_required']
                    or self.observed_at is None or not 0 <= self.clock() - self.observed_at <= .8
                    or context_of((self.latest or {}).get('state')) != lease['context'] or not safe_idle(self.latest)):
                reason = 'capability_release_needs_fresh_idle_observation'
            else:
                self.capability_checkpoint(None)
                self.capability_lease = None
                self.phase, self.reason = 'watching', 'capability_owner_released'
                self.next_observe = 0
        if reason:
            readiness = {'checks': admission_checks, 'observation_age_ms':
                         admission_age * 1000 if admission_age is not None else None,
                         'max_observation_age_ms': 800}
            if (reason == 'capability_admission_not_idle' and lease is None
                    and valid_command(refusal_command) and valid_readiness(readiness)
                    and self.capability_lease is None and self.session_id == refusal_session
                    and self.defense_epoch == refusal_command['expected_defense_epoch']
                    and context_of((self.latest or {}).get('state')) == refusal_command['expected_context']
                    and command == refusal_command):
                # This branch never installed a lease or submitted a Resident
                # command. Do not use absence in a later snapshot as this proof.
                proof = make_proof(refusal_command, intent_id, refusal_session, readiness)
                return self.capability_complete(intent_id, 'failed', reason,
                    capability_lease=None, acquisition_refusal=proof)
            return self.capability_complete(intent_id, 'failed', reason)
        return self.capability_complete(intent_id, 'succeeded', op + '_acknowledged',
                                       capability_lease=self.capability_status()['capability_lease'])

    def capability_release_cleanup(self, intent_id, command, lease, proof):
        """Persist intent, fence after blocking I/O, release locally, persist commit.

        The temporary local latch prevents admission during the durable commit.
        Neither failed I/O nor a callback may clear a replacement or resume play.
        """
        queue = self.q
        binding = {key: deepcopy(lease.get(key)) for key in
                   ('owner_id','context','resident_session','defense_epoch')}
        expected_proof = deepcopy(proof)
        pending = {'intent_id': intent_id, **deepcopy(binding)}

        def resident_idle(session):
            return (isinstance(session, dict) and session.get('session_id') == binding['resident_session']
                and safe_policy(session.get('resident_policy')) and session.get('state') == 'ready'
                and type(session.get('pending')) is int and session['pending'] == 0
                and session.get('active_request_id') is None)

        def before_release(session):
            now = self.clock()
            return (self.capability_lease is lease and self.q is queue
                and all(lease.get(key) == value for key, value in binding.items())
                and lease.get('state') == 'active' and lease.get('cleanup_started') is True
                and lease.get('cleanup_release_pending') == pending
                and lease.get('cleanup_observation') is proof and proof == expected_proof
                and isinstance(proof, dict) and type(proof.get('paused')) is bool
                and proof.get('context') == binding['context']
                and all(isinstance(proof.get(key), str) and proof[key] for key in ('intent_id','queue_request_id'))
                and type(proof.get('observed_at')) in (int, float)
                and 0 <= now - proof['observed_at'] <= .8
                and all(type(lease.get(key)) in (int, float) and now < lease[key]
                        for key in ('deadline','heartbeat'))
                and self.defense_epoch == binding['defense_epoch'] == command['expected_defense_epoch']
                and lease.get('fall_rescue_arm') is None and lease.get('transition') is None
                and lease.get('external_navigation') is None and lease.get('managed_navigation') is None
                and not self.owner and not self.rpc and not self.stop_requested and not self.stopped
                and self.armed and not self.input_release_latched and not self.handoff_latched
                and resident_idle(session))

        def fail_before(reason):
            # Do not mutate a replacement lease, overwrite a stop, or retry a write.
            if self.capability_lease is lease and not self.stop_requested and not self.stopped:
                self.capability_pause(reason)
            return self.capability_complete(intent_id, 'uncertain', reason)

        if lease.get('cleanup_release_pending') is not None:
            return fail_before('capability_cleanup_release_already_attempted')
        lease['cleanup_release_pending'] = deepcopy(pending)
        try:
            self.capability_checkpoint(lease)
            current = queue.session()
        except (OSError, ValueError, TypeError):
            return fail_before('capability_cleanup_release_prepare_unconfirmed')
        # All durable preparation and session reads are over. No blocking work
        # occurs between this exact fence and clearing this specific local owner.
        if not before_release(current):
            return fail_before('capability_cleanup_release_final_fence_failed')
        token = object()
        self._cleanup_release_commit = token
        self.capability_lease = None
        self.armed, self.handoff_latched = False, True
        self.phase, self.reason = 'cleanup_release_committing', 'capability_cleanup_release_commit_pending'
        try:
            self.capability_checkpoint(None)
            current = queue.session()
        except (OSError, ValueError, TypeError):
            return self.capability_complete(intent_id, 'uncertain', 'capability_cleanup_release_commit_unconfirmed')
        # Commit may also block or observe a stop/replacement. Never clear its
        # state or restore active admission based on the earlier snapshot.
        if (getattr(self, '_cleanup_release_commit', None) is not token or self.capability_lease is not None
                or self.q is not queue or self.defense_epoch != binding['defense_epoch']
                or self.owner or self.rpc or self.stop_requested or self.stopped
                or self.armed is not False or self.handoff_latched is not True or self.input_release_latched
                or self.phase != 'cleanup_release_committing' or self.reason != 'capability_cleanup_release_commit_pending'
                or not resident_idle(current)):
            return self.capability_complete(intent_id, 'uncertain', 'capability_cleanup_release_commit_state_changed')
        self._cleanup_release_commit = None
        if expected_proof['paused']:
            self.attention('capability_owner_released_while_game_paused')
        else:
            self.armed, self.handoff_latched = True, False
            self.phase, self.reason = 'watching', 'capability_owner_released'
            self.next_observe = 0
        return self.capability_complete(intent_id, 'succeeded', 'capability_release_acknowledged',
            capability_lease=None, cleanup_observation_intent_id=expected_proof.get('intent_id'))

    def capability_cancel_terminal(self, intent_id, command):
        """One exact completed original; never infer settlement from an absent owner."""
        from resident_controller.cancel_terminal import valid_command, normalized, make_proof, validate, REASON
        if not valid_command(command):
            return False
        captured_command = deepcopy(command)
        lease = getattr(self, 'capability_lease', None)
        if not lease:
            return False
        binding = {k: deepcopy(lease.get(k)) for k in
                   ('owner_id', 'context', 'defense_epoch', 'resident_session', 'last_mutation')}
        gateway_session = self.session_id
        last = binding['last_mutation']
        def bound(now):
            return (self.capability_lease is lease and self.session_id == gateway_session
                and command == captured_command and self.owner is None and self.rpc is None
                and lease.get('state') == 'active' and lease.get('owner_mode', 'ordinary') == 'ordinary'
                and not self.stop_requested and not self.stopped and self.armed
                and not self.handoff_latched and not self.input_release_latched
                and not lease.get('cleanup_started') and not lease.get('transition')
                and lease.get('fall_rescue_arm') is None and lease.get('external_navigation') is None
                and lease.get('managed_navigation') is None
                and all(lease.get(k) == v for k, v in binding.items())
                and self.defense_epoch == binding['defense_epoch'] == captured_command['expected_defense_epoch']
                and binding['owner_id'] == captured_command['owner_id']
                and binding['context']['action_session'] == captured_command['expected_action_session']
                and context_of(self.latest.get('state', {})) == binding['context']
                and now < lease['deadline'] and now < lease['heartbeat'])
        try:
            if (type(last) is not dict or set(last) != {'intent_id', 'queue_request_id', 'resident_session'}
                    or last['intent_id'] != captured_command['expected_intent_id']
                    or last['resident_session'] != binding['resident_session']
                    or lease.get('cancel_control') or not bound(self.clock())):
                return False
            original = self.q.result(last['queue_request_id'])
            session = self.q.session()
            if (type(original) is not dict or original.get('request_id') != last['queue_request_id']
                    or original.get('session_id') != binding['resident_session']
                    or original.get('status') not in ('succeeded', 'failed', 'cancelled') or unsafe_result(original)
                    or session.get('session_id') != binding['resident_session'] or not safe_policy(session.get('resident_policy'))
                    or session.get('state') != 'ready' or 'active_request_id' not in session
                    or session['active_request_id'] is not None or type(session.get('pending')) is not int or session['pending'] != 0):
                return False
            value = normalized(original, last['intent_id'], gateway_session, last['queue_request_id'])
            proof = make_proof(captured_command, intent_id, gateway_session, binding['context'], value)
            ack = {'status': 'succeeded', 'reason': REASON, 'gameplay_effect_confirmed': False,
                   'exact_cancel_terminal': proof, 'request_id': intent_id, 'session_id': gateway_session,
                   'queue_request_id': None, 'queue_session_id': None}
            if not validate(ack, captured_command, intent_id, gateway_session, original=value, context=binding['context']):
                return False
            # Complete all reads before the exact current authority check. No queue write occurs.
            now = self.clock()
            if not bound(now) or lease.get('cancel_control'):
                return False
            token = {'intent_id': intent_id, 'queue_request_id': None, 'original_intent_id': last['intent_id'],
                     'state': 'terminal_no_dispatch', 'proof': deepcopy(proof)}
            lease['cancel_control'] = token
            self.capability_checkpoint(lease)
            now = self.clock()
            if not bound(now) or lease.get('cancel_control') is not token:
                return False
            return self.capability_complete(intent_id, 'succeeded', REASON, exact_cancel_terminal=proof)
        except (KeyError, TypeError, ValueError, AttributeError, OSError):
            return False  # Never acknowledge an incomplete proof/persistence boundary.

    def capability_cancel(self, intent_id, command):
        """Cancel only the currently bound capability intent through its resident."""
        if self.owner is None:
            if self.capability_cancel_terminal(intent_id, command):
                return True
            return self.capability_complete(intent_id, 'failed', 'exact_cancel_owner_or_target_mismatch')
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
        body['terminal_proof_binding'] = {'schema_version': 1, 'request_id': intent_id,
            'gateway_session': self.session_id, 'command': deepcopy(command), 'context': deepcopy(lease['context'])}
        lease['cancel_control'] = {'intent_id': intent_id, 'queue_request_id': qid,
            'original_intent_id': owner['id'], 'state': 'reserved', 'command': deepcopy(command),
            'resident_command': deepcopy(body), 'gateway_session': self.session_id}
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

    def capability_cancel_queued_terminal(self, lease, cancel, result):
        """A queued control is settled only by exact Resident proof and current lease."""
        from resident_controller.queued_cancel_terminal import validate_resident, public_proof, validate, REASON
        from resident_controller.cancel_terminal import normalized
        body = deepcopy(cancel.get('resident_command'))
        binding = {k: deepcopy(lease.get(k)) for k in
            ('owner_id', 'context', 'defense_epoch', 'resident_session', 'last_mutation')}
        original_owner = self.owner
        gateway_session = cancel.get("gateway_session")
        owner_snapshot = deepcopy(original_owner)
        original_cancel = deepcopy(cancel)
        def bound(now, state='submitted'):
            return (self.capability_lease is lease and lease.get('cancel_control') is cancel
                and cancel == {**original_cancel, 'state': state} and self.session_id == gateway_session
                and cancel.get('gateway_session') == gateway_session and self.owner is original_owner
                and self.owner == owner_snapshot
                and (original_owner is None or original_owner.get('id') == cancel['original_intent_id']
                    and original_owner.get('request_id') == body['expected_request_id']
                    and original_owner.get('capability_owner') == binding['owner_id'])
                and self.rpc is None and lease.get('state') == 'active' and lease.get('owner_mode','ordinary') == 'ordinary'
                and not self.stop_requested and not self.stopped and self.armed
                and not self.handoff_latched and not self.input_release_latched
                and not lease.get('cleanup_started') and not lease.get('transition')
                and lease.get('fall_rescue_arm') is None and lease.get('external_navigation') is None
                and lease.get('managed_navigation') is None and all(lease.get(k) == v for k,v in binding.items())
                and self.defense_epoch == binding['defense_epoch'] == cancel['command']['expected_defense_epoch']
                and cancel['command']['owner_id'] == binding['owner_id']
                and context_of(self.latest.get('state',{})) == binding['context']
                and now < lease['deadline'] and now < lease['heartbeat'])
        try:
            last = binding['last_mutation']
            if (type(last) is not dict or set(last) != {'intent_id','queue_request_id','resident_session'}
                    or last != {'intent_id':cancel['original_intent_id'],'queue_request_id':body['expected_request_id'],
                                'resident_session':binding['resident_session']}
                    or body['terminal_proof_binding'] != {'schema_version':1,'request_id':cancel['intent_id'],
                        'gateway_session':gateway_session,'command':cancel['command'],'context':binding['context']}
                    or not bound(self.clock())):
                raise ValueError('queued_cancel_owner_changed')
            original = self.q.result(last['queue_request_id'])
            session = self.q.session()
            if (not validate_resident(result,body,cancel['queue_request_id'],original=original)
                    or session.get('session_id') != binding['resident_session']
                    or session.get('state') != 'ready' or session.get('active_request_id','missing') is not None
                    or type(session.get('pending')) is not int or session['pending'] != 0
                    or not safe_policy(session.get('resident_policy'))):
                raise ValueError('queued_cancel_resident_proof_unconfirmed')
            proof = public_proof(result,original)
            value = {'status':'succeeded','reason':REASON,'gameplay_effect_confirmed':False,
                'exact_queued_cancel_terminal':proof,'request_id':cancel['intent_id'],'session_id':gateway_session,
                'queue_request_id':cancel['queue_request_id'],'queue_session_id':binding['resident_session']}
            if not validate(value,cancel['command'],cancel['intent_id'],gateway_session,
                    original=normalized(original,last['intent_id'],gateway_session,last['queue_request_id']),context=binding['context']):
                raise ValueError('queued_cancel_public_proof_unconfirmed')
            now = self.clock()
            if not bound(now):raise ValueError('queued_cancel_owner_changed_after_read')
            cancel['state'] = 'confirmed'
            self.capability_checkpoint(lease)
            now = self.clock()
            if not bound(now,'confirmed'):raise ValueError('queued_cancel_owner_changed_after_persistence')
            self.completed.append({'intent_id':cancel['intent_id'],'session_id':gateway_session,
                'queue_request_id':cancel['queue_request_id'], 'result':{
                    'request_id':cancel['queue_request_id'],'session_id':binding['resident_session'],
                    'status':'succeeded','reason':REASON,'gameplay_effect_confirmed':False,
                    'exact_queued_cancel_terminal':proof}})
            return
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            # Never pause, clear or change a replacement lease/owner after a blocking read.
            if (self.capability_lease is lease and lease.get('cancel_control') is cancel
                    and self.session_id == gateway_session and self.owner is original_owner and self.owner == owner_snapshot
                    and all(lease.get(k) == v for k,v in binding.items())
                    and (original_owner is None or original_owner.get('id') == original_cancel['original_intent_id']
                        and original_owner.get('capability_owner') == binding['owner_id'])):
                cancel['state'] = 'unknown'
                self.capability_pause('exact_queued_cancel_terminal_proof_unconfirmed')
            self.completed.append({'intent_id':original_cancel['intent_id'],'session_id':gateway_session,
                'queue_request_id':original_cancel['queue_request_id'], 'result':{
                    'request_id':original_cancel['queue_request_id'],'session_id':binding['resident_session'],
                    'status':'uncertain','reason':'exact_queued_cancel_terminal_proof_unconfirmed'}})

    def capability_cancel_tick(self, lease):
        cancel = lease.get('cancel_control')
        if not cancel or cancel.get('state') != 'submitted':
            return
        result = self.q.result(cancel['queue_request_id'])
        if result is None:
            return
        if isinstance(result, dict) and 'exact_cancel_no_native_dispatch' in result:
            self.capability_cancel_queued_terminal(lease, cancel, result)
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
            if 'capability_cleanup' in command:
                return self.capability_complete(intent_id, 'cancelled', 'capability_cleanup_owner_proof_required')
            if command.get('op') in ('fall_rescue_control', 'external_navigation_control', 'managed_navigation_control'):
                return self.capability_complete(intent_id, 'cancelled', 'fall_rescue_owner_proof_required')
            return None
        if (not lease or owner_id != lease['owner_id'] or self.capability_expired()
                or self.stop_requested or self.stopped or not self.armed
                or self.input_release_latched or self.handoff_latched):
            return self.capability_complete(intent_id, 'cancelled', 'capability_owner_unavailable')
        if lease.get('cleanup_started'):
            return self.capability_complete(intent_id, 'cancelled', 'capability_cleanup_only_no_new_work')
        if self.owner or self.rpc:
            return False
        body = deepcopy(command)
        body.pop('_capability_owner_id', None)
        epoch = body.pop('_navigation_defense_epoch', None)
        expected_dimension = body.pop('_capability_expected_dimension', None)
        cleanup_requested = 'capability_cleanup' in body
        cleanup = body.pop('capability_cleanup', None)
        if cleanup_requested and (cleanup is not True or body != {'op': 'observe', 'capability_observation': True, 'entity_radius': 8}
                or expected_dimension is not None or lease.get('transition') is not None):
            return self.capability_complete(intent_id, 'cancelled', 'invalid_capability_cleanup_observation')
        if epoch != lease['defense_epoch'] or type(epoch) is not int or self.defense_epoch != epoch:
            return self.capability_complete(intent_id, 'cancelled', 'capability_defense_epoch_changed')
        op = body.get('op')
        if lease.get('owner_mode', 'ordinary') == 'external_stop' and op not in ('external_navigation_control', 'observe'):
            return self.capability_complete(intent_id, 'cancelled', 'external_stop_lease_is_not_mutation_authority')
        if lease.get('managed_navigation') is not None and op != 'managed_navigation_control':
            return self.capability_complete(intent_id, 'cancelled', 'managed_navigation_original_route_unsettled')
        if lease.get('external_navigation') is not None and op != 'external_navigation_control':
            return self.capability_complete(intent_id, 'cancelled', 'external_navigation_original_stop_unsettled')
        if lease.get('fall_rescue_arm') is not None and op != 'fall_rescue_control':
            return self.capability_complete(intent_id, 'cancelled', 'fall_rescue_standalone_guard_owns_lease')
        if op == 'managed_navigation_control':
            from managed_navigation_owner import prepare
            valid, binding = prepare(self, lease, body, expected_dimension)
        elif op == 'external_navigation_control':
            from external_navigation_owner import prepare
            valid, binding = prepare(self, lease, body, expected_dimension)
        elif op == 'fall_rescue_control':
            from resident_controller.fall_rescue_control import validate
            try:
                proof, context = validate(body)
                valid = (expected_dimension is None and proof['owner_id'] == lease['owner_id']
                    and context == lease['context'] and getattr(self, 'execution_policy', 'standard') == 'request_only'
                    and not lease['post_observation_required'])
                binding = {'arm_id': body['arm_id'], 'control_owner': deepcopy(proof)}
                if body['operation'] == 'arm':
                    feature = (self.latest or {}).get('state', {}).get('native_fall_rescue', {})
                    valid = (valid and lease.get('fall_rescue_arm') is None
                        and feature.get('schema_version') == 1 and feature.get('native_fences_ready') is True
                        and feature.get('external_controller_unknown') is False
                        and safe_idle(self.latest) and self.observed_at is not None
                        and 0 <= self.clock() - self.observed_at <= .8)
                else:
                    valid = valid and lease.get('fall_rescue_arm') == binding
                if valid:
                    body['expected_resident_session'] = lease['resident_session']
            except (ValueError, KeyError, TypeError):
                valid = False
        elif op == 'observe':
            valid = (expected_dimension is None and body.get('capability_observation') is True
                and set(body) <= {'op', 'capability_observation', 'capability_survey', 'terrain', 'radius', 'vertical', 'entity_radius'}
                and type(body.get('entity_radius', 8)) is int and 1 <= body.get('entity_radius', 8) <= 128
                and type(body.get('radius', 4)) is int and 1 <= body.get('radius', 4) <= 16
                and type(body.get('vertical', 4)) is int and 2 <= body.get('vertical', 4) <= 8)
            if body.get('compact_observation') is True:
                valid=(expected_dimension is None and body.get('capability_observation') is True
                    and set(body)<= {'op','capability_observation','compact_observation','radius'}
                    and type(body.get('radius',1)) is int and 1<=body.get('radius',1)<=2)
        elif op == 'action':
            context = lease['context']; guard = body.get('capability_guard')
            scoped = body.get('scoped_native_preflight')
            if (getattr(self, 'execution_policy', 'standard') == 'request_only'
                    and (not isinstance(scoped, dict) or not isinstance(scoped.get('profile'), str))):
                return self.capability_complete(intent_id, 'cancelled', 'capability_command_out_of_scope')
            scoped_valid = scoped is None or (isinstance(scoped, dict)
                and set(scoped) == {'version', 'profile', 'owner_id', 'owner_generation', 'job_id', 'defense_epoch'}
                and scoped.get('version') == 'scoped-native-preflight/1'
                and scoped.get('owner_id') == lease['owner_id']
                and type(scoped.get('defense_epoch')) is int and scoped['defense_epoch'] == lease['defense_epoch']
                and type(scoped.get('owner_generation')) is int and scoped['owner_generation'] > 0
                and isinstance(scoped.get('job_id'), str) and 0 < len(scoped['job_id']) <= 80
                and scoped.get('profile') in (self.latest or {}).get('state', {}).get('scoped_native_preflight', {}).get('profiles', {}))
            if getattr(self, 'execution_policy', 'standard') == 'request_only':
                profiles = (self.latest or {}).get('state', {}).get('scoped_native_preflight', {}).get('profiles', {})
                scoped_valid = (scoped_valid and isinstance(scoped, dict)
                    and isinstance(profiles.get(scoped.get('profile')), list)
                    and body.get('action') in profiles[scoped['profile']])
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
        if op == 'action' and ('fall_rescue_policy' in body or 'fall_rescue_binding' in body):
            try:
                from resident_controller.fall_rescue_attached import validate_envelope
                envelope=validate_envelope(body)
                feature=(self.latest or {}).get('state',{}).get('native_fall_rescue',{})
                status=(self.latest or {}).get('state',{}).get('native_fall_rescue_status',{})
                valid=(valid and envelope is not None and 'fall_rescue_binding' not in body and expected_dimension is None
                    and self.clock()*1000+envelope['ttl_ms'] <= envelope['authorization_deadline_monotonic_ms']
                    and envelope['authorization_deadline_monotonic_ms'] <= int(lease['deadline']*1000)
                    and feature.get('native_fences_ready') is True and feature.get('external_controller_unknown') is False
                    and status.get('armed') is False and status.get('input_owned') is False
                    and status.get('automation_blocked') is False and status.get('unknown_outcome_quarantined') is False)
            except (ValueError,KeyError,TypeError):
                valid=False
        if not valid:
            return self.capability_complete(intent_id, 'cancelled', 'capability_command_out_of_scope')
        session = self.q.session()
        if session.get('session_id') != lease['resident_session'] or not safe_policy(session.get('resident_policy')):
            self.capability_pause('capability_resident_session_or_policy_changed')
            return self.capability_complete(intent_id, 'cancelled', 'capability_resident_session_or_policy_changed')
        request_id = queue_request_id or uuid.uuid4().hex
        if op == 'action' and 'fall_rescue_policy' in body:
            from resident_controller.fall_rescue_attached import binding_for
            body['fall_rescue_binding'] = binding_for(body,request_id,lease['resident_session'])
        self.owner = {'id': intent_id, 'request_id': request_id, 'capability_owner': owner_id,
                      'resident_session': lease['resident_session'], 'capability_op': op,
                      'expected_dimension': expected_dimension,
                      'external_navigation_operation': body.get('operation') if op == 'external_navigation_control' else None,
                      'fall_rescue_operation': body.get('operation') if op == 'fall_rescue_control' else None,
                      'compact_observation': body.get('compact_observation') is True,
                      'cleanup_observation': cleanup is True,
                      'attached_fall_binding': deepcopy(body.get('fall_rescue_binding')),
                      'attached_fall_action': body.get('action') if 'fall_rescue_binding' in body else None}
        if cleanup is True:
            # One read followed only by exact release; never refresh dispatch authority.
            lease['cleanup_started'] = True
        if expected_dimension is not None:
            self.owner['transition_deadline'] = min(lease['deadline'], self.clock() + body['timeout_ms'] / 1000)
            self.owner['transition_source'] = deepcopy(lease['context'])
        if op == 'managed_navigation_control':
            if body['operation'] == 'start': lease['managed_navigation'] = binding
            if body['operation'] == 'cancel': lease['managed_navigation_cancel_submitted'] = True
        if op == 'external_navigation_control' and body['operation'] == 'stop':
            lease['external_navigation'] = binding
        if op == 'fall_rescue_control' and body['operation'] == 'arm':
            lease['fall_rescue_arm'] = binding
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

    def capability_capture_cleanup(self, payload, owner):
        """No latest/preflight/target refresh and no action, cancel, or unpause."""
        from resident_controller.cleanup_proof import validate_cleanup
        lease = self.capability_lease
        try:
            if (unsafe_result(payload) or not safe_policy(payload.get('resident_policy'))
                    or owner.get('capability_owner') != lease['owner_id']
                    or owner.get('resident_session') != lease['resident_session']):
                raise ValueError('cleanup_owner_or_policy_unconfirmed')
            proof = validate_cleanup(payload, lease['context'], last_fall=lease.get('cleanup_fall_status'),
                                     owner_id=lease['owner_id'])
            lease['cleanup_observation'] = {**proof, 'observed_at': self.clock(),
                'intent_id': owner['id'], 'queue_request_id': owner['request_id']}
            return True
        except (ValueError, KeyError, TypeError):
            self.capability_pause('capability_cleanup_observation_unconfirmed')
            return False

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
        from fall_rescue_adjudication import tick
        if tick(self):return True
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
            if 'fall_rescue_cleanup' in result:
                try:
                    from resident_controller.fall_rescue_attached import verify_cleanup
                    proof = verify_cleanup(result['fall_rescue_cleanup'], owner.get('attached_fall_binding'),
                                           owner.get('attached_fall_action'), result)
                    if (self.owner is not owner or self.capability_lease is not lease
                            or proof['binding']['owner_id'] != lease['owner_id']
                            or proof['binding']['resident_session'] != lease['resident_session']
                            or proof['binding']['request_id'] != owner['request_id']):
                        raise ValueError('fall_rescue_cleanup_original_owner_changed')
                    lease['cleanup_fall_status'] = deepcopy(proof['native_status'])
                    self.capability_checkpoint(lease)
                    if self.owner is not owner or self.capability_lease is not lease:
                        return True  # Never clear a replacement after persistence.
                except (ValueError,KeyError,TypeError):
                    if self.owner is owner and self.capability_lease is lease:
                        self.capability_pause('fall_rescue_cleanup_proof_unconfirmed')
                    return True
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
            if owner['capability_op'] == 'managed_navigation_control' and result['status'] == 'succeeded' and result.get('result', {}).get('state') == 'settled':
                lease.pop('managed_navigation', None)
                lease.pop('managed_navigation_cancel_submitted', None)
                self.capability_checkpoint(lease)
            if owner['capability_op'] == 'external_navigation_control' and result['status'] == 'succeeded' and result.get('result', {}).get('state') == 'settled':
                lease.pop('external_navigation', None)
                self.capability_checkpoint(lease)
            if owner['capability_op'] == 'fall_rescue_control' and owner.get('fall_rescue_operation') == 'disarm' and result['status'] == 'succeeded':
                lease['cleanup_fall_status'] = deepcopy(result.get('result'))
                lease.pop('fall_rescue_arm', None)
                self.capability_checkpoint(lease)
            if owner['capability_op'] == 'observe' and result['status'] == 'succeeded':
                if owner.get('cleanup_observation'):
                    self.capability_capture_cleanup(result.get('result', {}), owner)
                elif not owner.get('compact_observation'):
                    self.capability_capture(result.get('result', {}))
                # Compact reads retain the owner lifecycle but cannot refresh dispatch authority.
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
