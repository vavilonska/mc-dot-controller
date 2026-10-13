"""Opt-in sole-watchdog integration. Importing this module performs no game I/O.

This cooperative owner capability is not an OS sandbox. Planner processes receive
neither this object nor a QueueClient. There is no queue discovery or fallback path.
"""
from copy import deepcopy
from threading import get_ident
import hashlib
import math
import time
import uuid

from .executor import Receipt, compile_resident_command
from .schema import Context, canonical, identifier, require


class WatchdogOwnerBridge:
    def __init__(self, watchdog):
        self.dog, self.thread_id = watchdog, get_ident()
        require(getattr(watchdog, '_coordination_owner', None) is None, 'coordination_owner_already_claimed')
        require(type(getattr(watchdog, 'input_release_latched', None)) is bool
                and type(getattr(watchdog, 'handoff_latched', None)) is bool,
                'release_latch_contract_required')
        require(callable(getattr(watchdog, 'cancel_coordinated', None)), 'exact_cancel_contract_required')
        self.resident_session = None
        self.resident_bridge = None
        self.owner_session = identifier(watchdog.session_id)
        self._sent, self._cancelled = {}, set()
        self.publisher = None
        self.adapter = None
        self._reads, self._read_sequence = {}, 0
        self._next_read_at = {}
        self.confirmed_release = set()
        self.runtime = None
        self.capture_tickets = {}
        self.publisher_fault = False
        self.interrupted = False
        self.interruption_reason = None
        session = self.current_session()
        self.resident_session = identifier(session['session_id'])
        self.resident_bridge = deepcopy(session['bridge_identity'])
        self.ready(new_request=True, session=session)
        watchdog._coordination_owner = self

    def assert_thread(self):
        require(get_ident() == self.thread_id and getattr(self.dog, '_coordination_owner', None) is self,
                'sole_owner_thread_required')

    @staticmethod
    def valid_policy(policy):
        return (type(policy) is dict and type(policy.get('schema_version')) is int
                and policy['schema_version'] == 1 and type(policy.get('requires_handoff')) is bool
                and type(policy.get('input_release_unconfirmed')) is bool)

    def current_session(self):
        """Current root policy, never a prior action receipt, controls admission."""
        try:
            session = self.dog.q.session()
            require(type(session) is dict, 'resident_policy_unconfirmed')
            policy, stamp, identity = (session.get('resident_policy'), session.get('updated_at'),
                                       session.get('bridge_identity'))
            require(self.dog.session_id == self.owner_session
                    and (self.resident_session is None or session.get('session_id') == self.resident_session)
                    and type(session.get('session_id')) is str and bool(session['session_id'])
                    and type(identity) is dict and type(identity.get('run_id')) is str and bool(identity['run_id'])
                    and type(identity.get('process_id')) is int and identity['process_id'] > 0
                    and type(identity.get('action_session')) is str and bool(identity['action_session'])
                    and (self.resident_bridge is None or identity == self.resident_bridge)
                    and type(stamp) in (int, float) and math.isfinite(stamp) and 0 <= time.time() - stamp <= 3
                    and self.valid_policy(policy), 'resident_policy_unconfirmed')
            require(type(session.get('coordination_protocol')) is int and session['coordination_protocol'] == 1,
                    'resident_coordination_contract_required')
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            if not self.dog.input_release_latched and not getattr(self.dog, 'handoff_latched', False):
                self.interrupt('resident_policy_unconfirmed')
                self.dog.handoff_latched = True
            else:
                self.interrupt('resident_policy_unconfirmed')
            raise
        if policy['input_release_unconfirmed']:
            if not self.dog.input_release_latched:
                self.dog.input_release_latched = True
                self.interrupt('owner_input_release_unconfirmed', priority=True)
            else:
                self.interrupt('owner_input_release_unconfirmed')
        elif policy['requires_handoff']:
            if not getattr(self.dog, 'handoff_latched', False) and not self.dog.input_release_latched:
                self.dog.handoff_latched = True
                self.interrupt('encounter_requires_handoff', priority=True)
            else:
                self.interrupt('encounter_requires_handoff')
        return session

    def ready(self, *, new_request=False, capture_id=None, session=None):
        session = self.current_session() if session is None else session
        dog = self.dog
        owner = dog.owner
        rpc = dog.rpc
        owned = owner is None or (owner.get('request_id') in self._sent
                and owner.get('id') == owner.get('request_id') and not owner.get('menu_recovery'))
        own_rpc = rpc is None or rpc.get('id') in self.capture_tickets or rpc.get('id') == capture_id
        active = session.get('active_request_id')
        pending = session.get('pending_request_ids')
        combat, aim = session.get('combat'), session.get('aim_lock')
        resident_owned = (active is None or active in self._sent and
                          session.get('active_action_id') in (None, self._sent[active][0]))
        resident_idle = (session.get('state') == 'ready' and type(session.get('pending')) is int
                         and session['pending'] == 0 and active is None and pending == [])
        conflict = (dog.stopped or dog.stop_requested or dog.input_release_latched
                    or getattr(dog, 'handoff_latched', False) or getattr(dog, 'recover_observation', False)
                    or bool(getattr(getattr(dog, 'environment', None), 'active', False))
                    or getattr(dog, 'ranged_move', None) is not None or not owned or not own_rpc
                    or not resident_owned or type(pending) is not list
                    or any(rid not in self._sent for rid in pending)
                    or type(combat) is not dict or combat.get('active') is not False or combat.get('held_mappings') != []
                    or type(aim) is not dict or aim.get('active') is not False
                    or session.get('state') not in ('ready', 'busy')
                    or not dog.armed or dog.phase != 'watching')
        if conflict:
            self.interrupt('controlled_step_owner_conflict')
        if new_request:
            require(not self.interrupted and not conflict and resident_idle and owner is None
                    and (rpc is None or rpc.get('id') == capture_id), 'sole_owner_not_ready')
        return session

    def capture_fence(self, *, capture_id=None):
        self.assert_thread()
        self.ready(new_request=True, capture_id=capture_id)
        return {'owner_session': self.owner_session, 'resident_session': self.resident_session,
                'defense_epoch': self.dog.defense_epoch}

    def interrupt(self, reason, *, priority=False):
        dog = self.dog
        protected = (dog.stop_requested or dog.stopped or getattr(dog, 'recover_observation', False)
                     or bool(getattr(getattr(dog, 'environment', None), 'active', False))
                     or getattr(dog, 'ranged_move', None) is not None
                     or dog.owner is not None and (dog.owner.get('request_id') not in self._sent
                                                  or dog.owner.get('menu_recovery')))
        was_clear = (dog.armed and dog.phase == 'watching' and not dog.input_release_latched
                     and not getattr(dog, 'handoff_latched', False) and not protected)
        if not self.interrupted:
            self.interrupted, self.interruption_reason = True, reason
            dog.defense_epoch += 1
        if priority:
            self.interruption_reason = reason
        dog.armed = False
        # Do not erase a root latch, menu recovery, STOP or another owner's reason.
        if priority or was_clear:
            dog.phase, dog.reason = 'needs_operator', reason

    def tick_watchdog(self):
        """Narrow opt-in profile: existing writer, reads and exact owned cleanup only.

        Legacy autonomous combat/ranged/release-all branches never run while this
        one-step scope is attached. Native checks remain the immediate input guard.
        """
        self.assert_thread(); dog=self.dog
        try:
            self.ready()
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            return
        if dog.stopped:return
        if dog.stop_requested:self.interrupt('controlled_step_stop_requested')
        if (dog.owner and dog.owner.get('request_id') in self.confirmed_release
                and dog.owner.get('id') == dog.owner.get('request_id') and not dog.owner.get('menu_recovery')):
            dog.owner=None  # Exact request/native terminal release, never another action's receipt.
        if dog.stop_requested and dog.owner is None and self.runtime is not None and self.runtime.owner.active is None:
            dog.stopped=True;return
        if dog.owner and dog.owner.get('request_id') in self._sent and dog.owner.get('id') == dog.owner.get('request_id'):
            original_owner=dog.owner
            rid=original_owner['request_id']; raw=dog.q.result(rid)
            try:
                self.ready()
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                return
            if raw is not None and not self.guard_owner_result(rid,raw) and dog.owner is original_owner:
                dog.completed.append({'intent_id':dog.owner['id'],'session_id':dog.session_id,
                                      'queue_request_id':rid,'result':raw})
                dog.owner=None
        if dog.rpc and dog.rpc.get('id') in self.capture_tickets:
            original_rpc=dog.rpc
            rid=original_rpc['id']; raw=dog.q.result(rid)
            try:
                self.ready()
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                return
            if raw is None:
                if dog.clock()-original_rpc['started']>2:self.interrupt('controlled_step_observation_delayed')
                return
            self.completed_observe(rid,raw)
            if dog.rpc is original_rpc:dog.rpc=None
            if raw.get('status')!='succeeded' or self.publisher_fault:
                self.interrupt('controlled_step_observation_unavailable');return
            dog.latest=raw['result'];dog.observed_at=dog.clock()
            state=dog.latest.get('state',{});p=state.get('player',{});e=state.get('coordination_step',{})
            health=p.get('health')
            if (p.get('alive') is not True or state.get('screen_open') is not False or state.get('paused') is not False
                    or type(health) not in (int,float) or dog.last_health is not None and health<dog.last_health
                    or e.get('singleplayer') is not True or e.get('entity_count')!=0):
                self.interrupt('controlled_step_observed_interruption')
            dog.last_health=health
            dog.next_observe=dog.clock()+dog.interval
        if self.interrupted or dog.input_release_latched or getattr(dog,'handoff_latched',False):
            return
        if dog.rpc is None and dog.owner is None and dog.clock()>=dog.next_observe:
            dog.send('observe',{'op':'observe'})

    def before_observe(self, request_id):
        if self.publisher is not None:
            self.capture_tickets[request_id] = self.publisher.begin(request_id)

    def completed_observe(self, request_id, result):
        ticket = self.capture_tickets.pop(request_id, None)
        if ticket is None or self.publisher is None:
            return
        try:
            self.publisher.complete(ticket, result)
            self.publisher_fault = False
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            self.publisher_fault = True  # Read failures never start a fallback control path.

    def refresh(self):
        """One owner-controlled read, shared by all planners; no planner calls it."""
        self.assert_thread()
        self.ready(new_request=True)
        require(self.dog.rpc is None and self.dog.owner is None and self.dog.phase == 'watching'
                and self.dog.input_release_latched is False, 'observation_owner_busy')
        self.dog.send('observe', {'op': 'observe', 'terrain': True, 'radius': 1, 'vertical': 2,
                                  'coordination_step': True})
        return self.dog.rpc['id']

    def validate(self, binding, context, *, dispatch=False):
        self.assert_thread()
        fence = self.capture_fence()
        require(context.resident_session == self.resident_session
                and all(binding[k] == fence[k] for k in fence), 'owner_epoch_changed')
        session = self.ready(new_request=True)
        require(type(session.get('coordination_protocol')) is int and session['coordination_protocol'] == 1
                and session.get('bridge_identity') == {k: binding[k] for k in ('run_id', 'process_id', 'action_session')},
                'resident_process_changed')
        require(context.wire() == {'dimension': binding['dimension'],
                                  'world_generation': binding['world_generation'],
                                  'player_id': binding['player_uuid'],
                                  'action_session': binding['action_session'],
                                  'resident_session': binding['resident_session']}, 'binding_context_changed')
        if dispatch:
            require(self.publisher_fault is False and self.interrupted is False, 'publisher_requires_fresh_capture')
            require(self.dog.input_release_latched is False and self.dog.armed is True
                    and self.dog.stopped is False and self.dog.stop_requested is False
                    and self.dog.phase == 'watching' and self.dog.rpc is None and self.dog.owner is None,
                    'sole_owner_not_ready')
            require(session.get('state') == 'ready' and session.get('pending') == 0
                    and session.get('active_request_id') is None, 'resident_not_idle')
            require(self.dog.clock() < binding['expires_mono'], 'original_capture_expired')

    def submit_once(self, action_id, request_id, command, context, binding):
        self.validate(binding, context, dispatch=True)
        require(request_id not in self._sent, 'request_never_replayed')
        self._sent[request_id] = (action_id, deepcopy(binding))  # Before the only possible send.
        # Reuse the existing watchdog arbitration and queue writer. Its readiness,
        # threat/defense checks can decline; no alternate resident path exists.
        accepted = self.dog.submit_owner(request_id, {**command,
                           '_navigation_defense_epoch': binding['defense_epoch']}, queue_request_id=request_id)
        require(accepted is True and self.dog.owner == {'id': request_id, 'request_id': request_id},
                'sole_owner_submission_not_confirmed')

    def guard_owner_result(self, request_id, raw):
        """Prevent the legacy watchdog's broad fallback on a coordinated unknown."""
        if request_id not in self._sent or raw is None:
            return False
        action_id, binding = self._sent[request_id]
        context = Context(binding['dimension'],binding['world_generation'],binding['player_uuid'],
                          binding['action_session'],binding['resident_session'])
        try:
            self.ready()
            require(raw.get('request_id') == request_id and raw.get('session_id') == context.resident_session,
                    'resident_result_identity_changed')
            if raw.get('cancellation') is not None:self._cancelled.add(request_id)
            receipt = self.adapter._receipt(raw,action_id,request_id,context,binding,'follow_path')
            require(receipt is not None and receipt.status != 'running' and receipt.inputs_released is True,
                    'coordinated_owner_outcome_unknown')
        except (OSError,ValueError,KeyError,TypeError,OverflowError):
            if not self.dog.input_release_latched:
                self.dog.input_release_latched = True
                self.interrupt('coordinated_owner_outcome_unknown', priority=True)
            return True
        return False

    def _read_native(self, action_id, request_id, context):
        pending = self._reads.get(request_id)
        if pending is not None:
            read_id, _ = pending
            raw = self.dog.q.result(read_id)
            if raw is None:return None
            del self._reads[request_id]
            self._next_read_at[request_id] = self.dog.clock() + .2
            require(all(raw.get(k,False) is False for k in ('unknown_outcome','uncertain','post_uncertain'))
                    and raw.get('request_id') == read_id and raw.get('session_id') == context.resident_session
                    and raw.get('status') == 'succeeded' and raw.get('coordination_status') ==
                    {'request_id':request_id,'action_id':action_id,'action_session':context.action_session},
                    'reconciliation_result_identity_changed')
            return {'request_id':request_id,'session_id':context.resident_session,
                    'status':'uncertain','resolved_action':raw.get('result')}
        if self.dog.clock() < self._next_read_at.get(request_id, 0):return None
        self._read_sequence += 1
        read_id = uuid.uuid5(uuid.UUID(context.resident_session), request_id+':status:'+str(self._read_sequence)).hex
        self._reads[request_id] = (read_id, self.dog.clock())  # Before send; an uncertain read is not reissued.
        self.dog.read_coordinated(self,request_id,action_id,context,read_id)
        return None

    def read_exact(self, action_id, request_id, context, binding):
        self.assert_thread()
        # Defense epoch may advance while cancelling the OLD exact action. It is
        # an admission fence, not permission to discard its release obligation.
        require(self.dog.session_id == binding['owner_session'] == self.owner_session
                and self.current_session().get('session_id') == context.resident_session,
                'owner_lifecycle_changed')
        result = self.dog.q.result(request_id)
        self.ready()
        if result is None:
            session = self.current_session()
            active = session.get('active_request_id') == request_id
            pending = request_id in session.get('pending_request_ids', [])
            if (active and session.get('active_action_id') in (None, action_id)) or pending:
                return {'status': 'running', 'request_id': request_id, 'session_id': context.resident_session}
            return self._read_native(action_id,request_id,context)
        require(type(result) is dict and result.get('request_id') == request_id
                and result.get('session_id') == context.resident_session, 'resident_result_identity_changed')
        if result.get('cancellation') is not None:self._cancelled.add(request_id)
        unresolved = result.get('status') == 'uncertain' or any(result.get(k,False) is not False
                       for k in ('unknown_outcome','uncertain','post_uncertain'))
        if unresolved:
            return self._read_native(action_id,request_id,context)
        return result

    def cancel_once(self, action_id, request_id, context, binding):
        self.assert_thread()
        require(request_id not in self._cancelled, 'cancel_never_replayed')
        require(self.dog.session_id == binding['owner_session']
                and self.current_session().get('session_id') == context.resident_session,
                'owner_lifecycle_changed')
        session = self.ready()
        require((self.dog.owner is None or self.dog.owner == {'id':request_id,'request_id':request_id})
                and session.get('active_request_id') in (None, request_id)
                and all(rid == request_id for rid in session.get('pending_request_ids', [])),
                'coordination_cancel_foreign_owner')
        self._cancelled.add(request_id)
        # Deterministic distinct queue identity; original action/request unchanged.
        cancel_id = uuid.uuid5(uuid.UUID(context.resident_session), request_id + ':coordination-cancel').hex
        self.dog.cancel_coordinated(self, request_id, action_id, context, cancel_id)


class LiveResidentAdapter:
    """Explicit owner-only construction, never enabled by a planner flag or role.

    Default ResidentAdapter remains hard disabled. Actual native admission also
    requires publisher-issued bindings and resident protocol v1; fake snapshots,
    fixture threat clearances and raw command dictionaries cannot enable dispatch.
    """
    dry_run = False

    def __init__(self, bridge):
        require(type(bridge) is WatchdogOwnerBridge, 'sole_watchdog_bridge_required')
        bridge.assert_thread()
        self.bridge, self.publisher = bridge, None
        self._body_origins = {}

    def attach(self, store, threats):
        from .publisher import CompletedObservationPublisher
        require(self.publisher is None and self.bridge.adapter is None and self.bridge.publisher is None,
                'adapter_already_attached')
        self.publisher = CompletedObservationPublisher(store, self.bridge)
        self.bridge.publisher = self.publisher
        self.bridge.adapter = self
        self.threats = threats

    def bind_proposal(self, proposal, snapshot, expires):
        require(self.publisher is not None, 'publisher_required')
        require(proposal['intent']['kind'] == 'follow_path' and len(proposal['intent']['waypoints']) == 1
                and proposal['intent']['timeout_ms'] <= 1000, 'live_single_step_only')
        refs = proposal.get('source_samples')
        require(type(refs) is dict and all(refs.get(name) == snapshot['sections'].get(name, {}).get('sample_id')
                for name in ('player', 'terrain', 'entities')), 'original_source_samples_required')
        require(all(snapshot['sections'].get(name, {}).get('source_time_clock') == 'resident_result_finished_wall'
                    for name in ('player', 'terrain', 'entities')), 'live_safety_evidence_required')
        binding, acquisition = self.publisher.binding(snapshot)
        binding['expires_mono'] = min(binding['expires_mono'], expires)
        require(self.publisher.store.clock() < binding['expires_mono'], 'original_body_expired')
        require(proposal['preconditions']['expected_position'] == binding['origin'], 'original_origin_changed')
        self.bridge.validate(binding, Context.parse(proposal['context']))
        from .threats import ThreatClearance
        route = proposal['intent']['waypoints']
        proof_id = hashlib.sha256(canonical({'source': binding['source_id'], 'route': route})).hexdigest()
        entities = snapshot['sections']['entities']
        proof = ThreatClearance(proof_id, Context.parse(proposal['context']), entities['sample_id'],
                    entities['content_revision'], acquisition,
                    min(800, int((binding['expires_mono'] - acquisition.start_mono) * 1000)),
                    True, True, True, start=tuple(binding['origin'][k] for k in ('x','y','z')),
                    waypoints=tuple(tuple(p[k] for k in ('x','y','z')) for p in route),
                    native_step={'contract': 'controlled_single_step_v1', 'source_id': binding['source_id'],
                                 'source_nano': binding['source_nano'], 'source_tick': binding['source_tick']})
        self.threats.publish(proof)
        binding['endpoint'] = deepcopy(route[-1])
        binding['intent_sha256'] = hashlib.sha256(canonical(proposal['intent'])).hexdigest()
        return binding

    def action_id(self, request_id, context):
        from resident_controller.coordination_contract import native_action_id
        return native_action_id(context.resident_session, request_id)

    def pre_dispatch(self, binding, context):
        self.bridge.validate(binding, context, dispatch=True)

    def dispatch(self, action_id, request_id, value, context, *, binding):
        from resident_controller.coordination_contract import digest_command, envelope
        require(self.action_id(request_id, context) == action_id, 'native_action_identity_changed')
        require(binding.get('intent_sha256') == hashlib.sha256(canonical(value)).hexdigest(), 'original_intent_changed')
        body = compile_resident_command(value, context)
        body['coordination_step'] = {'schema_version': 1, 'source_tick': binding['source_tick'],
                                     'source_nano': binding['source_nano']}
        body.update(expected_player_uuid=context.player_id,
                    expected_navigation_epoch=binding['navigation_epoch'], expected_origin=deepcopy(binding['origin']))
        e = {k: deepcopy(v) for k, v in binding.items() if k not in ('rebind_ready', 'native_status', 'endpoint', 'step_clear', 'intent_sha256', 'terrain_source_id')}
        e.update(schema_version=1, request_id=request_id, native_action_id=action_id,
                 command_sha256=digest_command(body))
        body['_coordination'] = e
        envelope(body, now=self.publisher.store.clock())
        self.bridge.submit_once(action_id, request_id, body, context, binding)
        return Receipt(action_id, request_id, context, value['kind'], 'running', False, False)

    def _receipt(self, raw, action_id, request_id, context, binding, kind):
        if raw is None:
            return None
        self.bridge.ready()
        require(raw.get('request_id') == request_id and raw.get('session_id') == context.resident_session,
                'resident_result_identity_changed')
        require(all(raw.get(k,False) is False for k in ('unknown_outcome','uncertain','post_uncertain')),
                'explicit_transport_uncertainty')
        if raw.get('status') == 'running':
            return Receipt(action_id, request_id, context, kind, 'running', False, False)
        admission = raw.get('coordination_admission')
        if type(admission) is dict:
            require(type(admission.get('schema_version')) is int and admission['schema_version'] == 1
                    and admission.get('admitted') is False and admission.get('uncertain') is False
                    and raw.get('status') in ('failed','cancelled')
                    and all(raw.get(k, False) is False for k in ('unknown_outcome','uncertain','post_uncertain'))
                    and raw.get('action') is None and raw.get('action_id') is None and raw.get('cancellation') is None
                    and admission.get('request_id') == request_id and admission.get('native_action_id') == action_id
                    and admission.get('resident_session') == context.resident_session
                    and admission.get('action_session') == context.action_session
                    and admission.get('source_id') == binding['source_id']
                    and type(admission.get('reason')) is str and admission.get('reason') == raw.get('reason'), 'no_effect_evidence_invalid')
            return Receipt(action_id, request_id, context, kind, raw['status'], True, False)
        nested = raw.get('result')
        native = nested.get('action') if type(nested) is dict else None
        if native is None:
            native = raw.get('resolved_action') or raw.get('action')
        if type(native) is not dict:
            return None
        payload = native.get('result')
        require(all(native.get(k,False) is False for k in ('unknown_outcome','uncertain','post_uncertain')),
                'explicit_native_uncertainty')
        require(type(native.get('action_schema_version')) is int and native['action_schema_version'] == 1 and native.get('action_id') == action_id
                and native.get('action_session') == context.action_session
                and native.get('action') == ('follow_path' if kind == 'follow_path' else 'combat_entity')
                and type(payload) is dict and payload.get('world_generation') == context.world_generation
                and type(payload.get('coordination_step_schema_version')) is int
                and payload['coordination_step_schema_version'] == 1,
                'native_receipt_identity_changed')
        status = native.get('status')
        require(status in ('running', 'succeeded', 'failed', 'cancelled'), 'native_status_invalid')
        from resident_controller.action_safety import native_release_unconfirmed
        released = payload.get('input_release_confirmed') is True and not native_release_unconfirmed(native)
        if status != 'running' and not released:
            if not self.bridge.dog.input_release_latched:
                self.bridge.dog.input_release_latched = True
                self.bridge.interrupt('coordination_terminal_release_unconfirmed', priority=True)
        postcondition = False
        combat = payload.get('combat')
        handoff = (any('requires_handoff' in item and item['requires_handoff'] is not False for item in (raw,payload))
                   or type(combat) is dict and 'encounter' in combat)
        if handoff and released:self.bridge.interrupt('controlled_step_requires_handoff')
        state = nested.get('state') if type(nested) is dict else None
        if status == 'succeeded' and not handoff and type(state) is dict and raw.get('status') == 'succeeded':
            w, p, a = state.get('world', {}), state.get('player', {}), state.get('client_action', {})
            same = (w.get('world_generation') == context.world_generation and w.get('dimension') == context.dimension
                    and p.get('uuid') == context.player_id and a.get('action_session') == context.action_session
                    and a.get('action_id') == action_id and a.get('status') == 'succeeded')
            if same and kind == 'follow_path':
                endpoint = binding.get('endpoint')
                postcondition = endpoint is not None and all(type(p.get(k)) in (int, float)
                                         and abs(p[k] - endpoint[k]) <= .25 for k in ('x', 'y', 'z'))
        ticks = native.get('ticks')
        ticks = ticks if type(ticks) is int and ticks >= 0 else None
        return Receipt(action_id, request_id, context, kind, status, released, postcondition, ticks)

    def poll(self, action_id, request_id, context, *, binding, kind):
        raw = self.bridge.read_exact(action_id, request_id, context, binding)
        receipt = self._receipt(raw, action_id, request_id, context, binding, kind)
        if receipt is not None and receipt.status != 'running' and receipt.inputs_released is True:
            self.bridge.confirmed_release.add(request_id)
        return receipt

    def cancel(self, action_id, request_id, context, *, binding, kind):
        self.bridge.cancel_once(action_id, request_id, context, binding)
        return self.poll(action_id, request_id, context, binding=binding, kind=kind)
