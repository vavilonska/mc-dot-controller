"""Opt-in single-step runtime attachment for the EXISTING watchdog owner loop.

No process, queue client, thread listener, credentials or game is started here.
The caller supplies an authorized Grant and 2–3 read-only host workers. tick is
called on that same watchdog owner thread after dog.tick; it admits at most ONE
native action, then only reconciles that exact request until terminal/release.
"""
from copy import deepcopy
import uuid

from .advice import route_candidate_from_advice
from .coordinator import Coordinator
from .owner_bridge import LiveResidentAdapter, WatchdogOwnerBridge
from .planning import PlannerScheduler, seal_advice_candidate
from .schema import Grant, Rejected, require


class ControlledStepRuntime:
    def __init__(self, watchdog, directory, grant, workers, *, planning_budget_ms=30_000):
        require(type(grant) is Grant and grant.allowed_kinds == frozenset({'follow_path'})
                and grant.max_actions == 1 and grant.allow_defense_preemption is False,
                'one_step_authorized_grant_required')
        self.bridge = WatchdogOwnerBridge(watchdog)
        self.adapter = LiveResidentAdapter(self.bridge)
        self.owner = Coordinator(directory, executor=self.adapter, clock=watchdog.clock)
        self.owner.activate(grant)
        self.bridge.runtime = self
        self.scheduler = PlannerScheduler(self.owner.planner(), self.owner.lease_state, clock=watchdog.clock)
        self.workers = tuple(workers)
        self.planning_budget_ms = planning_budget_ms
        self.phase, self.reason = 'initial_capture', 'awaiting_shared_scan'
        self.capture_id, self.batch, self.advice, self.proposal_id = None, None, None, None

    def _capture(self):
        if self.capture_id is None:
            dog = self.bridge.dog
            if dog.rpc is not None or dog.owner is not None:
                return None
            self.capture_id = self.bridge.refresh()
            return None
        if self.capture_id in self.bridge.capture_tickets:
            return None
        if self.bridge.publisher_fault:
            raise Rejected('shared_capture_failed_no_action')
        snapshot = self.owner.snapshots.read()
        self.capture_id = None
        return snapshot

    def tick(self):
        self.bridge.assert_thread()
        if self.phase in ('complete', 'blocked', 'closed'):
            return self.status()
        try:
            if self.bridge.interrupted:
                if self.owner.active is not None and not self.owner.active.get('cancel_sent'):
                    self.owner.cancel_current()
                elif self.owner.active is None:
                    self.phase,self.reason='blocked',self.bridge.interruption_reason
                    if self.bridge.dog.stop_requested:self.bridge.dog.stopped=True
                    return self.status()
            if self.phase in ('running', 'unknown'):
                self.owner.reconcile()
                self.owner.advance()  # Enforces one exact-ID deadline cancel, never resubmits.
                if self.owner.active is None:
                    self.phase = 'complete'
                    self.reason = self.owner.result(self.proposal_id)['status']
                    self.bridge.interrupt('controlled_step_complete')
                elif self.owner.recovery_blocked:
                    self.phase, self.reason = 'unknown', 'exact_request_reconciliation_only'
                return self.status()
            lease = self.owner.lease_state()
            require(lease is not None and self.owner.clock() < min(lease['expires_mono'], lease['task_deadline_mono']),
                    'task_lease_expired')
            if self.phase == 'initial_capture':
                snapshot = self._capture()
                if snapshot is not None:
                    self.batch = self.scheduler.start(self.workers, budget_ms=self.planning_budget_ms, result_kind='advice')
                    self.phase, self.reason = 'planning', 'read_only_advice_running'
            elif self.phase == 'planning':
                ready = self.batch.collect()
                if ready:
                    self.advice = ready[0]
                    self.batch.finish()  # Drop alternatives; workers never submit actions.
                    self.phase, self.reason = 'fresh_capture', 'independent_scan_before_new_plan'
                elif self.batch.finished:
                    self.phase, self.reason = 'blocked', 'no_bounded_advice'
            elif self.phase == 'fresh_capture':
                snapshot = self._capture()
                if snapshot is not None:
                    candidate = seal_advice_candidate(self.advice,self.owner.planner(),budget_ms=500,
                                                        max_waypoints=1,include_source_samples=True)
                    proposal = candidate.wire()  # Sealed bytes are never modified after source issuance.
                    self.proposal_id = proposal['proposal_id']
                    self.owner.propose(proposal); self.owner.advance()
                    result = self.owner.result(self.proposal_id)
                    if self.owner.active is not None:
                        self.phase, self.reason = ('unknown' if self.owner.recovery_blocked else 'running'), result['reason']
                    else:
                        self.phase, self.reason = 'blocked', result['reason']
        except (Rejected, ValueError, KeyError, TypeError) as exc:
            self.phase, self.reason = 'blocked', str(exc)
            if self.batch is not None:self.batch.finish()
        return self.status()

    def status(self):
        return {'schema_version':1, 'scope':'controlled_single_step_v1', 'phase':self.phase,
                'reason':self.reason, 'proposal_id':self.proposal_id, 'coordination':self.owner.status()}

    def close(self):
        """Never abandon an unknown/active native action or claim input release."""
        require(self.owner.active is None and not self.owner.recovery_blocked, 'unreleased_action_blocks_close')
        self.scheduler.close()
        self.owner.close()
        self.bridge.interrupt('controlled_step_runtime_closed')
        self.phase='closed'
