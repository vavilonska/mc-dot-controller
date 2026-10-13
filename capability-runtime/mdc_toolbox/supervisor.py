"""Serialized decisions inside one owner; never creates an input writer."""
from __future__ import annotations
from contextlib import contextmanager
import threading
from .control import ControlStop


class LocalSupervisor:
    PRIORITY = {'stop': 0, 'survival': 1, 'tactical': 2, 'ordinary': 3, 'observation': 4}

    def __init__(self, control, policy, *, reflexes=None):
        self.control, self.policy = control, dict(policy)
        self.reflexes = dict(reflexes or {})  # Trusted registered domain handlers only.
        self._lock = threading.RLock()
        self.phase = 'ordinary'
        self.latched = False

    @contextmanager
    def ordinary(self):
        with self._lock:
            self.control.checkpoint()
            if self.latched:
                raise ControlStop('supervisor_boundary_latched')
            yield

    def boundary(self, reason, *, cleanup_confirmed, facts=None):
        """Called only after the active native action has returned, never beside it."""
        with self._lock:
            if self.latched:
                raise ControlStop('supervisor_boundary_latched')
            stop = self.control.stop_reason()
            if stop or not cleanup_confirmed:
                self.latched = True
                raise ControlStop(stop or 'supervisor_cleanup_unconfirmed', status='unknown' if not cleanup_confirmed else 'interrupted')
            reaction = self.policy.get('reactions', 'stop')
            handler = self.reflexes.get(reaction)
            if reaction == 'stop' or handler is None:
                self.latched = True
                raise ControlStop('hazard_requires_new_decision:' + reason)
            self.phase = 'survival'
            previous = self.control.lane
            self.control.lane = 'reflex'
            try:
                self.control.checkpoint()
                self.control.emit('reflex_started', {'reason': reason, 'reaction': reaction})
                result = handler(facts or {}, self.control)
                self.control.checkpoint()
                if not isinstance(result, dict) or result.get('cleanup_confirmed') is not True or result.get('continuation_safe') is not True:
                    self.latched = True
                    raise ControlStop('reflex_continuation_not_proven')
                self.control.emit('reflex_completed', {'reason': reason, 'reaction': reaction})
                return result
            except BaseException:
                self.latched = True
                raise
            finally:
                self.control.lane = previous
                self.phase = 'ordinary'
