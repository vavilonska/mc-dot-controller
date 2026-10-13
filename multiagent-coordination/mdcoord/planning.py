"""Bounded concurrent, read-only planning; no model client or action authority.

Callbacks receive immutable bytes, never a Coordinator, PlannerPort or executor.
They are cooperative Python code, not a sandbox. The owner consumes candidates
and chooses at most one alternative; this module never submits or dispatches.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from threading import Lock, get_ident
import time
import uuid

from .advice import make_route_advice, route_candidate_from_advice
from .schema import Proposal, Rejected, canonical, fields, identifier, integer, require


@dataclass(frozen=True)
class PlanningRequest:
    encoded: bytes
    deadline_mono: float

    def wire(self):
        return json.loads(self.encoded)

    @property
    def request_id(self):
        return self.wire()['request_id']


@dataclass(frozen=True)
class ReadyCandidate:
    encoded: bytes
    request_id: str
    completed_mono: float

    def wire(self):
        return json.loads(self.encoded)


@dataclass(frozen=True)
class PlannerWorker:
    role: str
    compute: object
    # This is owner-configured provenance, NEVER a model response field.
    origin: str = 'controlled_test'

    def __post_init__(self):
        identifier(self.role)
        require(callable(self.compute), 'planner_not_callable')
        require(self.origin in {'controlled_test', 'native_host'}, 'planner_origin')


class PlannerScheduler:
    """One active batch, at most three outstanding calls, no automatic retry."""
    def __init__(self, planner_port, lease_reader, *, clock=time.monotonic):
        self._port, self._lease_reader, self.clock = planner_port, lease_reader, clock
        self._owner_thread = get_ident()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='mdc-planner')
        self._batch = None
        self._closed = False

    def _owner(self):
        require(get_ident() == self._owner_thread, 'planning_owner_thread_required')
        require(not self._closed, 'planning_scheduler_closed')

    def start(self, workers, *, budget_ms=1000, mode='parallel',
              quality_budget=None, required_sections=('player', 'terrain', 'entities'),
              diagnostic_drain=False, result_kind='candidate'):
        self._owner()
        require(mode in {'serial', 'parallel'}, 'planning_mode')
        require(result_kind in {'candidate', 'advice'}, 'planning_result_kind')
        require(type(workers) in (tuple, list) and 2 <= len(workers) <= 3
                and all(type(w) is PlannerWorker for w in workers), 'planner_count')
        require(len({w.role for w in workers}) == len(workers), 'duplicate_planner_role')
        integer(budget_ms, 50, 30_000)
        require(self._batch is None or (self._batch.finished and self._batch.workers_done),
                'planning_batch_or_worker_still_active')
        receipt = self._port.capture_planning_source()
        snapshot = receipt['snapshot']
        lease = receipt['lease']
        require(type(lease) is dict, 'planning_lease_required')
        require(snapshot['clock_epoch'] == lease['clock_epoch'], 'planning_clock_fence')
        require(snapshot['context'] is not None, 'planning_context_required')
        require(type(required_sections) in (tuple, list) and 1 <= len(required_sections) <= 6,
                'planning_sections')
        require(all(name in snapshot['sections'] for name in required_sections), 'planning_section_missing')
        now = self.clock()
        expiry = [now + budget_ms / 1000, lease['expires_mono'], lease['task_deadline_mono']]
        for name in required_sections:
            section = snapshot['sections'][name]
            require(section['freshness'] == 'fresh' and section['expires_mono'] is not None,
                    'planning_observation_not_fresh')
            expiry.append(section['expires_mono'])
        admission_deadline = min(expiry)
        require(type(diagnostic_drain) is bool, 'planning_diagnostic_flag')
        deadline = min(expiry[:3]) if diagnostic_drain or result_kind == 'advice' else admission_deadline
        require(admission_deadline > now, 'planning_deadline_expired')
        quality = quality_budget or {'max_output_tokens': 1024, 'reasoning_effort': 'xhigh'}
        fields(quality, ('max_output_tokens', 'reasoning_effort'))
        integer(quality['max_output_tokens'], 64, 4096)
        require(quality['reasoning_effort'] in {'low', 'medium', 'high', 'xhigh'}, 'planning_quality_budget')
        frozen = canonical(snapshot)
        self._batch = PlanningBatch(self, workers, snapshot, frozen, dict(lease), now, deadline,
                                    mode, quality, tuple(required_sections), admission_deadline, diagnostic_drain, result_kind, receipt['source_id'])
        return self._batch

    def close(self):
        self._owner()
        if self._batch:
            self._batch.finish('scheduler_closed')
        self._closed = True
        # Arbitrary cooperative callbacks cannot be forcibly killed safely. New
        # batches are blocked until callbacks return; no unbounded replacement.
        self._executor.shutdown(wait=False, cancel_futures=True)


class PlanningBatch:
    def __init__(self, scheduler, workers, snapshot, frozen, lease, started, deadline,
                 mode, quality, required_sections, admission_deadline, diagnostic_drain, result_kind, source_id):
        self.scheduler, self.workers = scheduler, tuple(workers)
        self.started_mono, self.deadline_mono = started, deadline
        self.mode, self.required_sections = mode, required_sections
        self.admission_deadline_mono = admission_deadline
        self.diagnostic_drain = diagnostic_drain
        self.result_kind = result_kind
        self.source_id = source_id
        self.batch_id = uuid.uuid4().hex
        self.snapshot_sha256 = hashlib.sha256(frozen).hexdigest()
        self._snapshot, self._lease = snapshot, lease
        self._requests, self._futures, self._consumed = {}, {}, set()
        self._worker_lock, self._started = Lock(), {}
        self.events = []
        self.finished = False
        for index, worker in enumerate(workers):
            request_id = self.batch_id + '-' + str(index)
            payload = {'schema_version': 1, 'request_id': request_id,
                       'batch_id': self.batch_id, 'role': worker.role, 'result_kind': result_kind,
                       'snapshot_sha256': self.snapshot_sha256, 'snapshot': snapshot,
                       'quality_budget': quality,
                       'budget_ms': max(0, int((deadline - started) * 1000)),
                       'created_mono': started, 'inference_deadline_mono': deadline,
                       'source_expires_mono': admission_deadline,
                       'candidate_schema': (['kind', 'goal', 'based_on'] if result_kind == 'advice' else
                                            ['intent', 'based_on', 'dependencies', 'priority', 'preconditions'])}
            self._requests[index] = PlanningRequest(canonical(payload), deadline)
        if mode == 'parallel':
            for index in range(len(workers)):
                self._launch(index)
        else:
            self._launch(0)

    @property
    def workers_done(self):
        return all(f.done() for f in self._futures.values())

    def _launch(self, index):
        worker, request = self.workers[index], self._requests[index]
        def compute():
            started = self.scheduler.clock()
            with self._worker_lock:
                self._started[index] = started
            if started >= self.deadline_mono:
                return {'started': started, 'ended': started, 'error': 'planning_timeout'}
            try:
                value = worker.compute(request)  # Computation starts INSIDE worker.
                encoded = canonical(value)  # Freeze result before returning to owner.
                return {'started': started, 'ended': self.scheduler.clock(), 'encoded': encoded}
            except BaseException as exc:
                error = 'native_host_deadline' if type(exc) is Rejected and str(exc) == 'native_host_deadline' else 'planner_failed'
                return {'started': started, 'ended': self.scheduler.clock(), 'error': error}
        self._futures[index] = self.scheduler._executor.submit(compute)

    def _fence(self, now):
        require(now < (self.deadline_mono if self.result_kind == 'advice' else self.admission_deadline_mono),
                'planning_observation_expired')
        lease = self.scheduler._lease_reader()
        require(type(lease) is dict and all(lease.get(k) == self._lease[k] for k in
                ('task_id', 'epoch', 'revision', 'clock_epoch')), 'planning_lease_fence')
        require(now < min(lease['expires_mono'], lease['task_deadline_mono']), 'planning_lease_expired')
        current = self.scheduler._port.snapshot()
        require(current['clock_epoch'] == self._snapshot['clock_epoch'] and
                current['context'] == self._snapshot['context'], 'planning_session_fence')
        if self.result_kind == 'advice':
            return  # Advice cannot execute; fresh independent owner replan is mandatory.
        for name in self.required_sections:
            old, new = self._snapshot['sections'][name], current['sections'].get(name)
            require(new is not None and new['freshness'] == 'fresh' and
                    new['content_revision'] == old['content_revision'] and
                    new['continuity_revision'] == old['continuity_revision'], 'planning_snapshot_fence')

    def _candidate(self, value, index, completed):
        if value is None:
            return None
        if self.result_kind == 'advice':
            return make_route_advice(value, self._requests[index], completed, self._lease)
        fields(value, ('intent', 'based_on', 'dependencies', 'priority', 'preconditions'))
        remaining_ms = int((self.admission_deadline_mono - self.scheduler.clock()) * 1000)
        require(remaining_ms >= 50, 'planning_candidate_expired')
        # Owner supplies all authority/fence fields. Output cannot extend deadline,
        # choose a task, forge a worker, request cancellation or replay an ID.
        proposal = {**value, 'proposal_id': self._requests[index].request_id,
                    'task_id': self._lease['task_id'], 'epoch': self._lease['epoch'],
                    'lease_revision': self._lease['revision'], 'role': self.workers[index].role,
                    'context': self._snapshot['context'], 'ttl_ms': min(15_000, remaining_ms),
                    'cancel_requested': False}
        sealed = self.scheduler._port.seal_planning_proposal(proposal, self.source_id, self.admission_deadline_mono)
        return ReadyCandidate(Proposal.parse(sealed).encoded, self._requests[index].request_id, completed)

    def collect(self):
        """Owner-only: fenced typed proposals, NOT safety approval or submission.

        Call owner preflight/authorization, submit only the selected alternative,
        then finish(). All other proposals remain suggestions and never run.
        """
        self.scheduler._owner()
        if self.finished:
            return []
        if self.scheduler.clock() >= self.deadline_mono:
            self.finish('planning_timeout')
            return []
        try:
            self._fence(self.scheduler.clock())
        except Rejected as exc:
            if not self.diagnostic_drain:
                self.finish(str(exc))
                return []
        ready = []
        completed = [(f.result()['ended'], i) for i, f in self._futures.items()
                     if i not in self._consumed and f.done() and not f.cancelled()]
        for _, index in sorted(completed):
            result = self._futures[index].result()
            self._consumed.add(index)
            event = {'request_id': self._requests[index].request_id,
                     'role': self.workers[index].role, 'origin': self.workers[index].origin,
                     'started_mono': result['started'], 'completed_mono': result['ended'],
                     'duration_ms': (result['ended'] - result['started']) * 1000,
                     'source_observation_expired_at_completion': result['ended'] >= self.admission_deadline_mono}
            try:
                self._fence(self.scheduler.clock())
                require('error' not in result, result.get('error'))
                candidate = self._candidate(json.loads(result['encoded']), index, result['ended'])
                event['status'] = self.result_kind if candidate else 'abstained'
                if candidate:
                    ready.append(candidate)
            except (Rejected, TypeError, KeyError, ValueError) as exc:
                event['status'] = 'rejected'
                event['reason'] = str(exc) if isinstance(exc, Rejected) else 'invalid_candidate'
            self.events.append(event)
            if self.mode == 'serial' and index + 1 < len(self.workers):
                self._launch(index + 1)
        return ready

    @property
    def exhausted(self):
        return len(self._consumed) == len(self.workers)

    def finish(self, reason='owner_selected_candidate'):
        self.scheduler._owner()
        if self.finished:
            return
        self.finished = True
        self.scheduler._port.finish_planning_source(self.source_id)
        for index, future in self._futures.items():
            if index not in self._consumed:
                future.cancel()
        for index in range(len(self.workers)):
            if index not in self._consumed:
                event = {'request_id': self._requests[index].request_id,
                         'role': self.workers[index].role, 'origin': self.workers[index].origin,
                         'status': 'discarded', 'reason': reason}
                with self._worker_lock:
                    event['not_started'] = index not in self._started
                    if index in self._started:
                        event['started_mono'] = self._started[index]
                future = self._futures.get(index)
                if future is not None and future.done() and not future.cancelled():
                    result = future.result()
                    event.update(completed_mono=result['ended'],
                                 duration_ms=(result['ended'] - result['started']) * 1000,
                                 source_observation_expired_at_completion=result['ended'] >= self.admission_deadline_mono)
                self.events.append(event)


def seal_advice_candidate(advice, planner_port, *, budget_ms=1000, max_waypoints=1,
                          include_source_samples=False):
    """Capture fresh source, independently replan, and seal one new proposal.

    The caller obtains a genuinely new observation before this call. The owner
    registry captures that exact cache sample BEFORE replanning and preserves its
    deadline/lineage through arbitrary collect-to-submit delays. No action is
    submitted or authorized by this function.
    """
    integer(budget_ms, 50, 3000)
    receipt = planner_port.capture_planning_source()
    snapshot, lease = receipt['snapshot'], receipt['lease']
    candidate = route_candidate_from_advice(advice, snapshot, lease, max_waypoints=max_waypoints)
    deadline = min(receipt['issued_mono'] + budget_ms / 1000,
                   lease['expires_mono'], lease['task_deadline_mono'],
                   *(snapshot['sections'][name]['expires_mono'] for name in ('player', 'terrain', 'entities')))
    proposal_id = uuid.uuid4().hex
    proposal = {**candidate, 'proposal_id': proposal_id, 'task_id': lease['task_id'],
                'epoch': lease['epoch'], 'lease_revision': lease['revision'], 'context': snapshot['context'],
                'role': 'fresh_owner_route_planner', 'ttl_ms': budget_ms, 'cancel_requested': False}
    if include_source_samples:
        proposal['source_samples'] = {name: snapshot['sections'][name]['sample_id']
                                      for name in ('player', 'terrain', 'entities')}
    sealed = planner_port.seal_planning_proposal(proposal, receipt['source_id'], deadline)
    return ReadyCandidate(Proposal.parse(sealed).encoded, proposal_id, receipt['issued_mono'])
