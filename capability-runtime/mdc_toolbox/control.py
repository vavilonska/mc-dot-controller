"""Cooperative stop boundaries with a separate mandatory cleanup lane."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import threading
from mdc_skills.core import SkillError
from .budgets import SharedBudget


class ControlStop(SkillError):
    def __init__(self, reason, *, status='interrupted'):
        super().__init__(reason, status=status)


class JobControl:
    def __init__(self, context, *, owner_check=None, budget=None):
        self.job_id = context['job_id']
        self.request_id = context['request_id']
        self.cancel_event = context.get('cancel_event') or threading.Event()
        self._emit = context.get('emit') or (lambda event, payload: None)
        self.budget = budget or SharedBudget(context['budget'], context['deadline_at'])
        self.owner_check = owner_check
        self.lane = 'ordinary'
        self.cancel_request_id = None
        self.latched_reason = None
        self._lock = threading.RLock()

    def stop_reason(self):
        if self.latched_reason:
            return self.latched_reason
        if self.cancel_event.is_set():
            return 'cancel_requested'
        if self.budget.remaining_seconds() <= 0:
            return 'original_deadline_elapsed'
        return None

    def checkpoint(self):
        if self.lane == 'cleanup':
            return
        reason = self.stop_reason()
        if reason:
            raise ControlStop(reason, status='cancelled' if reason == 'cancel_requested' else 'interrupted')
        if self.owner_check is not None:
            self.owner_check()

    def consume(self, kind='actions', amount=1, lane=None):
        self.checkpoint()
        try:
            self.budget.consume(kind, amount, lane or self.lane)
        except SkillError as exc:
            self.latched_reason = exc.reason
            raise ControlStop(exc.reason) from None

    def emit(self, event, payload):
        if type(event) is not str or type(payload) is not dict:
            raise SkillError('invalid_control_event')
        self._emit(event, deepcopy(payload))  # Durable caller callback; never swallow failure.

    def request_cancel(self, request_id):
        with self._lock:
            if self.cancel_request_id is not None and self.cancel_request_id != request_id:
                return False
            self.cancel_request_id = request_id
            self.cancel_event.set()
            return True

    @contextmanager
    def cleanup(self):
        previous = self.lane
        self.lane = 'cleanup'
        try:
            yield
        finally:
            self.lane = previous
