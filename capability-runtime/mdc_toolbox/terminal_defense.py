"""Terminal-only reflex transition primitive, activated only by explicit defend_once policy.

The adapter must supply trusted evidence from its exact Runtime native receipt.
This is not admission, a target selector, a new writer, or a retry mechanism.
"""
from copy import deepcopy
from .control import ControlStop
from .supervisor import LocalSupervisor


class TerminalDefensiveSupervisor(LocalSupervisor):
    def defend_once(self, *, reason, cleanup_confirmed, owner_known,
                    context_same, facts=None):
        """Run one registered bounded defense, then terminate the ordinary job.

        Called synchronously only after the ordinary native action returns.
        Keep the same JobControl, Runtime owner and original deadline/ledger.
        Handler owns fresh target/native admission; caller facts grant no authority.
        Never use ordinary boundary(), which requires continuation safety.
        """
        with self._lock:
            if self.latched:
                raise ControlStop('supervisor_boundary_latched')
            # Latch before any callback/checkpoint/event that might throw. A lost
            # acknowledgement must not turn a second call into another attack.
            self.latched = True
            stop = self.control.stop_reason()
            if stop:
                raise ControlStop(stop, status='cancelled' if stop == 'cancel_requested' else 'interrupted')
            if cleanup_confirmed is not True or owner_known is not True:
                raise ControlStop('defense_owner_or_cleanup_unconfirmed', status='unknown')
            if context_same is not True:
                raise ControlStop('defense_context_changed')
            if reason not in ('capability_damage_observed', 'capability_threat_observed'):
                raise ControlStop('defense_trigger_unsupported')
            if self.policy.get('reactions', 'stop') != 'defend_once':
                raise ControlStop('defense_not_opted_in')
            handler = self.reflexes.get('defend_once')
            if not callable(handler):
                raise ControlStop('defense_handler_unavailable')
            previous = self.control.lane
            self.control.lane = 'reflex'
            self.phase = 'survival'
            try:
                self.control.checkpoint()
                budget = self.control.budget.snapshot()
                if (budget['limits']['reflex_reserve_actions'] - budget['used']['reflex']['actions'] < 1
                        or budget['remaining']['actions'] < 1
                        or budget['remaining']['observations'] < 2):
                    raise ControlStop('original_reflex_budget_exhausted')
                self.control.emit('reflex_started', {'reason': reason, 'reaction': 'defend_once'})
                # Registered handler must dispatch via this job's Runtime, which
                # debits the original ledger. No nested budget or owner is made.
                result = handler(deepcopy(facts or {}), self.control)
                if not isinstance(result, dict) or result.get('cleanup_confirmed') is not True:
                    raise ControlStop('defense_cleanup_unconfirmed', status='unknown')
                if result.get('status') == 'unknown':
                    raise ControlStop('defense_effect_unknown', status='unknown')
                if result.get('status') not in ('succeeded', 'failed', 'blocked', 'cancelled', 'interrupted'):
                    raise ControlStop('defense_result_invalid', status='unknown')
                self.control.emit('reflex_completed', {'reason': reason, 'reaction': 'defend_once',
                    'result': deepcopy(result), 'ordinary_resume_allowed': False})
                self.control.checkpoint()
                # Even proven defense success does not complete/resume the old goal.
                raise ControlStop('preempted_before_motion' if (facts or {}).get('preempted_before_motion') is True
                                  else 'ordinary_task_interrupted_after_defense')
            finally:
                self.control.lane = previous
                self.phase = 'stopped'
