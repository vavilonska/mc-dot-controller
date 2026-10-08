"""Owner-driven, durable single-writer arbitration. No background thread or listener."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
from threading import RLock
import time
import uuid

from .executor import FakeExecutor, Receipt
from .journal import Journal
from .metrics import Metrics
from .safety import preflight
from .schema import Context, Grant, Proposal, Rejected, canonical, identifier, integer, require
from .snapshots import SnapshotStore
from .threats import ThreatStore

TERMINAL = frozenset({'succeeded', 'failed', 'cancelled', 'rejected'})


@dataclass
class Lease:
    grant: Grant
    epoch: str
    revision: int
    deadline: float
    expires: float
    actions: int = 0
    reserved_ms: int = 0
    cancellations: int = 0


class PlannerPort:
    """Narrow cooperative API, NOT a Python sandbox or identity/authentication layer."""
    def __init__(self, owner):
        self.__owner = owner

    def snapshot(self):
        return self.__owner.snapshots.read()

    def submit(self, proposal):
        return self.__owner.propose(proposal)

    def result(self, proposal_id):
        return self.__owner.result(proposal_id)

    def subscribe(self, capacity=4):
        return self.__owner.snapshots.subscribe(capacity)

    def poll(self, subscription):
        return self.__owner.snapshots.poll(subscription)

    def unsubscribe(self, subscription):
        return self.__owner.snapshots.unsubscribe(subscription)


class Coordinator:
    """Privileged owner API. Constructing this object never starts the game or a loop."""
    def __init__(self, directory, *, executor=None, clock=time.monotonic):
        self._lock = RLock()
        self.clock = clock
        self.metrics = Metrics(clock)
        self.snapshots = SnapshotStore(clock, self.metrics)
        self.threats = ThreatStore(clock, epoch=self.snapshots.epoch)
        self.executor = executor if executor is not None else FakeExecutor()
        require(getattr(self.executor, 'dry_run', False) is True, 'live_executor_disabled')
        self.journal = Journal(directory)
        self.epoch = uuid.uuid4().hex
        self.records = copy.deepcopy(self.journal.data['records'])
        self.task_ids = list(self.journal.data['task_ids'])
        self.active = copy.deepcopy(self.journal.data['active'])
        self.pending = {}
        self.lease = None
        self._lease_authority = None
        self._lease_revoked = False
        self.closed = False
        self.durability_fault = False
        self.recovery_blocked = self.active is not None
        # No old grant, lease, proposal deadline or source monotonic clock is resumed.
        for record in self.records.values():
            require(type(record) is dict and record.get('status') in
                    TERMINAL | {'queued', 'dispatching', 'running', 'cancelling', 'unknown'}, 'journal_invalid')
            if record['status'] not in TERMINAL:
                record.update(status='unknown' if self.active and self.active['proposal_id'] in self.records
                              and self.records[self.active['proposal_id']] is record else 'cancelled',
                              reason='owner_restarted_no_replay')
        if self.active:
            self.active['state'] = 'unknown'
            self.active['recovered'] = True
        try:
            self._save()
        except BaseException:
            self.journal.close()
            raise

    def _save(self):
        try:
            self.journal.save({'schema_version': 1, 'epoch': self.epoch,
                               'records': self.records, 'active': self.active, 'task_ids': self.task_ids})
        except BaseException:
            self.durability_fault = True
            raise

    def _open(self):
        require(not self.closed, 'owner_closed')
        require(not self.durability_fault, 'durability_fault_reconcile_after_restart')

    def planner(self):
        return PlannerPort(self)

    def activate(self, grant):
        """Trusted owner supplies a bounded grant based on actual user authorization."""
        require(type(grant) is Grant, 'owner_grant_required')
        with self._lock:
            self._open()
            require(self.active is None and not self.recovery_blocked, 'unreleased_action_blocks_grant')
            require(grant.task_id not in self.task_ids and len(self.task_ids) < 256, 'task_grant_cannot_restart')
            self.task_ids.append(grant.task_id)
            self._drop_pending('task_replaced')
            now = self.clock()
            self.lease = Lease(grant, uuid.uuid4().hex, 1, now + grant.duration_ms / 1000,
                               now + grant.lease_ms / 1000)
            self._lease_authority = self._authority_signature()
            self._lease_revoked = False
            self._save()
            return self.lease_state()

    def lease_state(self):
        with self._lock:
            if not self.lease:
                return None
            l = self.lease
            return {'task_id': l.grant.task_id, 'epoch': l.epoch, 'revision': l.revision,
                    'expires_mono': l.expires, 'task_deadline_mono': l.deadline,
                    'clock_epoch': self.snapshots.epoch, 'actions': l.actions,
                    'reserved_execution_ms': l.reserved_ms, 'cancellations': l.cancellations}

    def renew(self, epoch, expected_revision, lease_ms):
        """Continuous same-authority CAS renewal; never rewrites proposal evidence."""
        with self._lock:
            self._open()
            self._check_lease(epoch, expected_revision)
            require(not self.recovery_blocked, 'reconciliation_required')
            integer(lease_ms, 50, 30_000)
            # Expired, changed-content, discontinuous and failed-dependency proposals
            # become terminal BEFORE renewal; a fresh sample cannot revive them.
            self._eligible()
            self._check_lease(epoch, expected_revision)
            l = self.lease
            l.expires = min(l.deadline, self.clock() + lease_ms / 1000)
            l.revision += 1
            for entry in self.pending.values():
                # Private admission token follows the uninterrupted authority chain.
                # Original encoded proposal/digest, receipt time and capped deadline
                # are immutable. New submissions still require the current revision.
                entry['validated_lease_revision'] = l.revision
            self._save()
            return self.lease_state()

    def _authority_signature(self):
        l = self.lease
        grant = {**vars(l.grant), 'context': l.grant.context.wire(),
                 'allowed_kinds': sorted(l.grant.allowed_kinds),
                 'allowed_targets': sorted(l.grant.allowed_targets)}
        return hashlib.sha256(canonical({'owner_epoch': self.epoch, 'lease_epoch': l.epoch,
                                         'grant': grant, 'task_deadline': l.deadline})).hexdigest()

    def _check_lease(self, epoch, revision):
        l = self.lease
        if l is not None and (self._lease_authority != self._authority_signature()
                              or self._lease_revoked):
            self._lease_revoked = True
            self._drop_pending('lease_authority_changed')
            self._save()
            raise Rejected('lease_authority_changed')
        require(l is not None and l.epoch == epoch, 'lease_epoch_conflict')
        require(l.revision == revision, 'lease_revision_conflict')
        if self.clock() >= min(l.expires, l.deadline):
            self._lease_revoked = True
            self._drop_pending('lease_expired')
            self._save()
            raise Rejected('lease_expired')

    def _check_entry_lease(self, entry):
        p = entry['proposal']
        require(entry['authority'] == self._lease_authority, 'lease_authority_changed')
        self._check_lease(p['epoch'], entry['validated_lease_revision'])
        require(p['task_id'] == self.lease.grant.task_id
                and p['context'] == self.lease.grant.context.wire(), 'task_or_context_conflict')

    def _observation_basis(self, plan, snapshot):
        """Record continuity, never a predicted player endpoint or safety verdict."""
        required = {'player', 'terrain', 'entities'} if plan['intent']['kind'] == 'follow_path' else {'player', 'entities'}
        names = set(plan['based_on']) | required
        return {name: snapshot['sections'].get(name, {}).get('continuity_revision') for name in sorted(names)}

    def _check_observation(self, entry, snapshot):
        p = entry['proposal']
        require(snapshot['context'] == self.lease.grant.context.wire() == p['context'], 'context_changed')
        require(entry.get('observation_error') is None, entry.get('observation_error'))
        for name, continuity in entry['observation_basis'].items():
            current = snapshot['sections'].get(name)
            require(current is not None and current.get('freshness') == 'fresh',
                    'player_not_fresh' if name == 'player' else 'observation_not_fresh')
            require(continuity is not None and current['continuity_revision'] == continuity,
                    'observation_continuity_broken')
        for name, revision in p['based_on'].items():
            current = snapshot['sections'].get(name)
            require(current is not None and current['content_revision'] == revision, 'revision_conflict')
        if 'threat_proof_id' in entry:
            self.threats.require_clearance(snapshot, p['preconditions']['expected_position'],
                                          p['intent']['waypoints'], proof_id=entry['threat_proof_id'])

    def propose(self, value):
        proposal = Proposal.parse(value)
        data = proposal.wire()
        pid = data['proposal_id']
        digest = hashlib.sha256(proposal.encoded).hexdigest()
        with self._lock:
            self._open()
            if pid in self.records:
                require(self.records[pid]['digest'] == digest, 'proposal_id_payload_conflict')
                self.metrics.count('duplicate_proposals')
                return self.result(pid)
            self._check_lease(data['epoch'], data['lease_revision'])
            grant = self.lease.grant
            require(not self.recovery_blocked, 'reconciliation_required')
            require(data['task_id'] == grant.task_id and data['context'] == grant.context.wire(),
                    'task_or_context_conflict')
            require(data['intent']['kind'] in grant.allowed_kinds, 'intent_not_authorized')
            require(len(self.records) < 4096, 'identity_capacity_start_fresh_only_after_safe_shutdown')
            require(len(self.pending) < 32, 'proposal_queue_full')
            require(all(dep in self.records and self.records[dep]['task_id'] == grant.task_id
                        and self.records[dep]['epoch'] == self.lease.epoch for dep in data['dependencies']),
                    'dependency_not_in_current_task')
            if data['intent']['kind'] == 'follow_path':
                require(data['priority'] <= 90, 'reserved_defense_priority')
                require(all(grant.contains(p) for p in data['intent']['waypoints']), 'outside_authorized_bounds')
            else:
                require(data['intent']['target_uuid'] in grant.allowed_targets, 'target_not_authorized')
            now = self.clock()
            self.records[pid] = {'digest': digest, 'task_id': grant.task_id, 'epoch': self.lease.epoch,
                                 'status': 'cancelled' if data['cancel_requested'] else 'queued',
                                 'reason': 'proposal_cancel_marker' if data['cancel_requested'] else 'awaiting_arbitration',
                                 'server_confirmed': False}
            if not data['cancel_requested']:
                snapshot = self.snapshots.read()
                entry = {'proposal': data, 'received': now,
                         'expires': min(now + data['ttl_ms'] / 1000,
                                        self.lease.expires, self.lease.deadline),
                         'authority': self._lease_authority,
                         'validated_lease_revision': self.lease.revision,
                         'observation_basis': self._observation_basis(data, snapshot)}
                try:
                    self._check_observation(entry, snapshot)
                except Rejected as exc:
                    entry['observation_error'] = str(exc)
                if data['intent']['kind'] == 'follow_path':
                    try:
                        entry['threat_proof_id'] = self.threats.require_clearance(
                            snapshot, data['preconditions']['expected_position'], data['intent']['waypoints'])
                    except Rejected as exc:
                        entry['observation_error'] = entry.get('observation_error') or str(exc)
                self.pending[pid] = entry
            self._save()
            return self.result(pid)

    def result(self, proposal_id):
        identifier(proposal_id)
        with self._lock:
            result = self.records.get(proposal_id)
            if result is None:
                return None
            return {key: copy.deepcopy(value) for key, value in result.items() if key != 'digest'}

    def status(self):
        with self._lock:
            return {'dry_run': True, 'owner_epoch': self.epoch, 'active': copy.deepcopy(self.active),
                    'pending': len(self.pending), 'lease': self.lease_state(),
                    'recovery_blocked': self.recovery_blocked, 'durability_fault': self.durability_fault}

    def _drop_pending(self, reason):
        for pid in self.pending:
            self.records[pid].update(status='cancelled', reason=reason)
        self.pending.clear()

    def _reject(self, pid, reason):
        self.records[pid].update(status='rejected', reason=reason)
        self.pending.pop(pid, None)

    def _eligible(self):
        ready = []
        for pid, entry in list(self.pending.items()):
            if pid not in self.pending:
                continue
            p = entry['proposal']
            try:
                self._check_entry_lease(entry)
                require(self.clock() < entry['expires'], 'proposal_expired')
                self._check_observation(entry, self.snapshots.read())
                dep_states = [self.records[dep]['status'] for dep in p['dependencies']]
                require(not any(s in {'failed', 'cancelled', 'rejected', 'unknown'} for s in dep_states),
                        'dependency_not_succeeded')
                if all(s == 'succeeded' for s in dep_states):
                    ready.append((pid, entry))
            except Rejected as exc:
                if pid in self.pending:
                    self._reject(pid, str(exc))
        ready.sort(key=lambda item: (-item[1]['proposal']['priority'], item[1]['received'], item[0]))
        return ready

    def _check_budget(self, entry):
        p = entry['proposal']
        self._check_entry_lease(entry)
        require(self.clock() < entry['expires'], 'proposal_expired')
        self._check_observation(entry, self.snapshots.read())
        l = self.lease
        require(l.actions < l.grant.max_actions, 'task_action_budget')
        require(l.reserved_ms + p['intent']['timeout_ms'] <= l.grant.execution_budget_ms,
                'task_execution_budget')
        require(self.clock() + p['intent']['timeout_ms'] / 1000 <= min(l.expires, l.deadline),
                'action_exceeds_remaining_lease')

    def advance(self):
        """One bounded arbitration step. Owner calls it; workers never dispatch."""
        with self._lock:
            self._open()
            if self.recovery_blocked:
                self._deadline_cancel_if_needed()
                return self.status()  # Never frees a slot without exact terminal release evidence.
            if self.active:
                self._poll()
                if self.active:
                    if self.recovery_blocked:
                        self._deadline_cancel_if_needed()
                        return self.status()
                    if (self.lease is None or self.clock() >= min(self.lease.expires, self.lease.deadline)
                            or self.clock() >= self.active['deadline']):
                        self._cancel('deadline_or_lease_expired')
                    else:
                        ready = self._eligible()
                        defense = next(((pid, e) for pid, e in ready
                                        if e['proposal']['intent']['kind'] == 'defend_entity'
                                        and e['proposal']['priority'] > self.active['priority']), None)
                        if defense and self.lease.grant.allow_defense_preemption:
                            # Full admission checks before cancelling useful ordinary work.
                            try:
                                self._check_budget(defense[1])
                                preflight(defense[1]['proposal'], self.lease.grant, self.snapshots.read(),
                                          self.threats, defense[1].get('threat_proof_id'))
                                self._cancel('authorized_defense_preemption')
                            except Rejected as exc:
                                self._reject(defense[0], str(exc))
                    self._save()
                    return self.status()  # Even confirmed release hands over only on the NEXT step.
            ready = self._eligible()
            for pid, entry in ready:
                p = entry['proposal']
                try:
                    self._check_budget(entry)
                    l = self.lease
                    # Publication is short and serialized against final admission. Collection happens outside.
                    with self.snapshots._lock, self.threats._lock:
                        preflight(p, l.grant, self.snapshots.read(), self.threats, entry.get('threat_proof_id'))
                        self._dispatch(pid, entry)
                    break
                except Rejected as exc:
                    self._reject(pid, str(exc))
            self._save()
            return self.status()

    def _dispatch(self, pid, entry):
        p = entry['proposal']
        now = self.clock()
        self.active = {'proposal_id': pid, 'action_id': uuid.uuid4().hex, 'request_id': uuid.uuid4().hex,
                       'context': p['context'], 'kind': p['intent']['kind'], 'state': 'dispatching',
                       'priority': p['priority'], 'started_mono': now,
                       'deadline': now + p['intent']['timeout_ms'] / 1000,
                       'owner_epoch': self.epoch, 'cancel_sent': False, 'recovered': False}
        self.pending.pop(pid)
        self.records[pid].update(status='dispatching', reason='durable_before_dispatch')
        self.lease.actions += 1
        self.lease.reserved_ms += p['intent']['timeout_ms']
        self._save()  # If it fails, no executor dispatch occurs.
        # Durable preparation may be slow. Re-check every expiring guard AFTER
        # fsync and immediately before the only executor call. We know no action
        # was sent yet, so a failed guard is a definite rejection, not a replay.
        try:
            self._check_entry_lease(entry)
            require(self.clock() < entry['expires'], 'proposal_expired')
            self._check_observation(entry, self.snapshots.read())
            require(self.clock() < self.active['deadline'], 'action_preparation_deadline')
            require(self.clock() + p['intent']['timeout_ms'] / 1000 <=
                    min(self.lease.expires, self.lease.deadline), 'action_exceeds_remaining_lease')
            preflight(p, self.lease.grant, self.snapshots.read(), self.threats, entry.get('threat_proof_id'))
        except Rejected as exc:
            self.records[pid].update(status='rejected', reason=str(exc))
            self.active = None
            self._save()
            return
        self.metrics.duration('queue', entry['received'], self.clock())
        active = self.active
        active['dispatch_started_mono'] = self.clock()
        try:
            receipt = self.executor.dispatch(active['action_id'], active['request_id'], p['intent'],
                                             Context.parse(active['context']))
        except Exception:
            self._unknown('dispatch_outcome_unknown')
        else:
            self._accept(receipt)

    def _unknown(self, reason):
        self.active['state'] = 'unknown'
        self.records[self.active['proposal_id']].update(status='unknown', reason=reason)
        self.recovery_blocked = True
        self._drop_pending('uncertain_action_requires_replan')

    def _accept(self, receipt):
        a = self.active
        if (type(receipt) is not Receipt or receipt.action_id != a['action_id']
                or receipt.request_id != a['request_id'] or type(receipt.context) is not Context
                or receipt.context.wire() != a['context']
                or receipt.kind != a['kind'] or type(receipt.status) is not str or receipt.status not in {'running', 'succeeded', 'failed', 'cancelled'}
                or type(receipt.inputs_released) is not bool or type(receipt.postcondition_observed) is not bool
                or receipt.server_confirmed is not False or (receipt.native_ticks is not None and
                   (type(receipt.native_ticks) is not int or receipt.native_ticks < 0))):
            self._unknown('receipt_identity_or_schema_mismatch')
            return
        record = self.records[a['proposal_id']]
        if receipt.status == 'running':
            if a['state'] not in ('cancelling', 'unknown'):
                a['state'] = 'running'
                record.update(status='running', reason='accepted_not_completed')
            return
        if receipt.inputs_released is not True:
            self._unknown('terminal_release_unconfirmed')
            return
        status = receipt.status
        reason = 'terminal_client_observed'
        if status == 'succeeded' and receipt.postcondition_observed is not True:
            status, reason = 'failed', 'terminal_without_observed_postcondition'
        record.update(status=status, reason=reason, action_id=a['action_id'], request_id=a['request_id'],
                      postcondition_observed=receipt.postcondition_observed, inputs_released=True,
                      native_ticks=receipt.native_ticks)
        if not a.get('recovered') and a['owner_epoch'] == self.epoch:
            self.metrics.duration('dispatch_to_terminal_observation', a.get('dispatch_started_mono', a['started_mono']), self.clock())
        if receipt.native_ticks is not None:
            self.metrics.native_ticks(receipt.native_ticks)
        self.active = None
        self.recovery_blocked = False
        if status != 'succeeded':
            # Only explicitly authorized defense may survive a confirmed preemption.
            for pid, entry in list(self.pending.items()):
                if entry['proposal']['intent']['kind'] != 'defend_entity':
                    self.records[pid].update(status='cancelled', reason='prior_segment_not_succeeded')
                    self.pending.pop(pid)

    def _poll(self):
        a = self.active
        try:
            receipt = self.executor.poll(a['action_id'], a['request_id'], Context.parse(a['context']))
        except Exception:
            self._unknown('status_unavailable')
        else:
            if receipt is None:
                self._unknown('missing_receipt_never_replay')
            else:
                self._accept(receipt)
        self._save()

    def reconcile(self):
        """Read the exact old request/action. Missing/running results do not authorize replay."""
        with self._lock:
            self._open()
            if self.active:
                self.metrics.count('reconciliations')
                self._poll()
            return self.status()

    def _deadline_cancel_if_needed(self):
        a = self.active
        # An unknown action can still receive ONE distinct exact-ID safety cancel.
        # An old owner clock is incomparable after restart, so recovery never uses it.
        if (a and not a.get('recovered') and a['owner_epoch'] == self.epoch and not a['cancel_sent']
                and (self.clock() >= a['deadline'] or self.lease is not None and
                     self.clock() >= min(self.lease.expires, self.lease.deadline))):
            self._cancel('deadline_or_lease_expired')
            self._save()

    def cancel_current(self):
        """Trusted owner's explicit cancellation, never available on the planner port."""
        with self._lock:
            self._open()
            if self.active:
                self._cancel('owner_cancel_requested')
                self._save()
            return self.status()

    def _cancel(self, reason):
        a = self.active
        if a['cancel_sent']:
            # Cancellation timeout never frees the writer slot or causes another cancel POST.
            self._unknown('cancel_release_unconfirmed')
            return
        # Mandatory deadline release remains permitted even if discretionary preemptions are exhausted.
        if reason == 'authorized_defense_preemption':
            require(self.lease.cancellations < self.lease.grant.max_cancellations, 'cancellation_budget')
        if self.lease:
            self.lease.cancellations += 1
        a['cancel_sent'] = True
        a['state'] = 'cancelling'
        self.records[a['proposal_id']].update(status='cancelling', reason=reason)
        self.metrics.count('cancellations')
        self._save()  # One separate exact-ID cancel; never an action replay.
        try:
            receipt = self.executor.cancel(a['action_id'], a['request_id'], Context.parse(a['context']))
        except Exception:
            self._unknown('cancel_outcome_unknown')
        else:
            if receipt is None:
                self._unknown('cancel_release_unconfirmed')
            else:
                self._accept(receipt)

    def close(self):
        """Close local owner handle only; never claims to release actual gameplay inputs."""
        with self._lock:
            if not self.closed:
                self.journal.close()
                self.closed = True
