"""Pure outer-observer health STOPPED-SAFETY latch for one encounter trial.

This is not the native health guard, a live controller, or a hard-real-time
monitor. It performs no I/O, cancellation, input, sleep, or budget changes.
The caller supplies one identity-bound observation and its local monotonic
request interval at a time, using the same guard for before/running/after.

Any observed decrease, however small and regardless of regeneration or native
health thresholds, latches STOPPED-SAFETY. Invalid/missing evidence also latches.
The optional outer gap limit merely detects obvious observer stalls. A shorter
gap does NOT prove continuous health coverage or absence of intervening damage.
Even an entirely stable sample chain cannot establish full active-AI acceptance.

Typical integration (all transport and stop authority remain with the caller):
    guard = HealthStopGuard(binding, clock=operator.clock)
    guard.record(before, started_monotonic, finished_monotonic, 'before')
    if not guard.report()['ready_to_submit']:  # before submitting any action
        ...
    # Record every running and final observation, including a terminal winner.
    # On observation-request exceptions: guard.mark_unknown('observe_failed').
    # On stop_required: use only an already authorized same-owner stop path.
    report = guard.report(final=True)

The default one-second limit is an outer evidence fail-closed threshold only;
it neither replaces nor changes native 150 ms/8 ms or action/distance budgets.
"""
from __future__ import annotations

from copy import deepcopy
import math
import time
from collections.abc import Mapping


IDENTITY_FIELDS = ('world_generation', 'player_uuid', 'action_session')
PHASES = ('before', 'running', 'after')
DEFAULT_MAX_GAP_SECONDS = 1.0


def _finite_number(value):
    """JSON-number semantics, excluding bool and numeric-looking strings."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


class HealthStopGuard:
    """One-use, monotonic safety latch; reports are isolated JSON-safe copies.

    ``identity`` is a mapping or a Binding-like object with the three fields in
    IDENTITY_FIELDS. It deliberately does not infer identity from the first
    observation. The resident envelope/owner must still be checked externally.

    ``clock`` must be the same monotonic clock used for observation intervals.
    Inject a deterministic callable for offline tests. ``report`` checks for a
    stale baseline or stalled running observer even when no new sample arrives.
    Request intervals and observation values are claims supplied by the caller,
    not independently verified server-tick/capture timestamps.

    No method can reset the latch. An incomplete final report also latches, and
    finalization permanently disallows submitting or appending further samples.
    """

    def __init__(self, identity, *, clock=time.monotonic,
                 max_gap_seconds=DEFAULT_MAX_GAP_SECONDS):
        self._identity = {
            key: identity.get(key) if isinstance(identity, Mapping)
            else getattr(identity, key, None) for key in IDENTITY_FIELDS
        }
        if any(type(value) is not str or not value for value in self._identity.values()):
            raise ValueError('health_expected_identity_missing_or_invalid')
        if not callable(clock):
            raise ValueError('health_clock_must_be_callable')
        if not _finite_number(max_gap_seconds) or max_gap_seconds <= 0:
            raise ValueError('health_outer_gap_limit_invalid')
        self._clock = clock
        self._max_gap_seconds = max_gap_seconds
        self._reasons = []
        self._events = []
        self._samples = []
        self._valid_phase_counts = dict.fromkeys(PHASES, 0)
        self._baseline_health = None
        self._previous_health = None
        self._latest_health = None
        self._phase_index = -1
        self._last_finished = None
        self._last_checked = None
        self._finalized = False
        self._record_calls = 0
        self._decrease_count = 0
        self._timing_invalid = False
        self._action_may_have_started = False

    @property
    def identity(self):
        return deepcopy(self._identity)

    def _latch(self, reason, *, phase=None, detail=None):
        if reason not in self._reasons:
            self._reasons.append(reason)
        event = {'reason': reason, 'phase': phase, 'record_index': self._record_calls}
        if detail is not None:
            event['detail'] = deepcopy(detail)
        self._events.append(event)

    def _check_clock(self, now_monotonic=None):
        if now_monotonic is None:
            try:
                now_monotonic = self._clock()
            except Exception as exc:
                self._timing_invalid = True
                self._latch('health_clock_request_failed', detail={'error_type': type(exc).__name__})
                return
        if not _finite_number(now_monotonic) or now_monotonic < 0:
            self._timing_invalid = True
            self._latch('health_clock_invalid')
            return
        if ((self._last_checked is not None and now_monotonic < self._last_checked)
                or (self._last_finished is not None and now_monotonic < self._last_finished)):
            self._timing_invalid = True
            self._latch('health_clock_reversal')
        # There is no future monitoring claim after the final after-observation.
        # During before/running a delayed report must not reuse a stale baseline.
        if (not self._finalized and self._phase_index < PHASES.index('after')
                and self._last_finished is not None
                and now_monotonic - self._last_finished > self._max_gap_seconds):
            self._timing_invalid = True
            self._latch('health_local_observation_gap', detail={
                'gap_seconds': now_monotonic - self._last_finished,
                'outer_gap_limit_seconds': self._max_gap_seconds,
            })
        self._last_checked = now_monotonic

    def mark_unknown(self, reason, *, phase=None):
        """Latch a missing read, failed request, or other caller-known evidence gap.

        Do this even if the action result concurrently reports success. The
        reason is diagnostic text, never an instruction to run a stop command.
        """
        if type(reason) is not str or not reason:
            reason = 'unspecified_observation_failure'
        if phase is not None and phase not in PHASES:
            self._latch('health_phase_invalid')
            phase = None
        if phase in ('running', 'after'):
            self._action_may_have_started = True
        self._latch('health_observation_unknown', phase=phase, detail={'reason': reason})
        return self.report()

    def record(self, observation, started_monotonic, finished_monotonic, phase):
        """Consume one outer read and immediately return the current guard report.

        Missing, ill-typed, nonfinite, identity-changing or temporally invalid
        reads never replace the baseline or stand in for a no-damage sample.
        The caller must retain full raw observations/receipts separately.
        """
        self._record_calls += 1
        if self._finalized:
            self._latch('health_observation_after_finalization', phase=phase if phase in PHASES else None)
            return self.report()
        if phase not in PHASES:
            self._latch('health_phase_invalid')
            return self.report()
        if phase in ('running', 'after'):
            self._action_may_have_started = True
        phase_index = PHASES.index(phase)
        phase_valid = True
        if phase_index < self._phase_index:
            phase_valid = False
            self._latch('health_phase_reversal', phase=phase)
        if phase != 'before' and self._valid_phase_counts['before'] == 0:
            phase_valid = False
            self._latch('health_before_baseline_missing', phase=phase)
        if phase == 'after' and self._valid_phase_counts['running'] == 0:
            phase_valid = False
            self._latch('health_running_observation_window_missing', phase=phase)
        self._phase_index = max(self._phase_index, phase_index)

        timing_valid = True
        if (not _finite_number(started_monotonic) or started_monotonic < 0
                or not _finite_number(finished_monotonic) or finished_monotonic < 0):
            timing_valid = False
            self._latch('health_observation_timing_invalid', phase=phase)
        elif finished_monotonic < started_monotonic:
            timing_valid = False
            self._latch('health_clock_reversal', phase=phase)
        else:
            if self._last_finished is not None and started_monotonic < self._last_finished:
                timing_valid = False
                self._latch('health_observation_interval_overlap_or_reversal', phase=phase)
            if finished_monotonic - started_monotonic > self._max_gap_seconds:
                timing_valid = False
                self._latch('health_observation_request_too_long', phase=phase, detail={
                    'request_duration_seconds': finished_monotonic - started_monotonic,
                    'outer_gap_limit_seconds': self._max_gap_seconds,
                })
            if (self._last_finished is not None
                    and started_monotonic - self._last_finished > self._max_gap_seconds):
                timing_valid = False
                self._latch('health_local_observation_gap', phase=phase, detail={
                    'gap_seconds': started_monotonic - self._last_finished,
                    'outer_gap_limit_seconds': self._max_gap_seconds,
                })
            self._last_finished = (finished_monotonic if self._last_finished is None
                                   else max(self._last_finished, finished_monotonic))
        if not timing_valid:
            self._timing_invalid = True

        state = observation.get('state') if isinstance(observation, Mapping) else None
        world = state.get('world') if isinstance(state, Mapping) else None
        player = state.get('player') if isinstance(state, Mapping) else None
        client = state.get('client_action') if isinstance(state, Mapping) else None
        actual_identity = {
            'world_generation': world.get('world_generation') if isinstance(world, Mapping) else None,
            'player_uuid': player.get('uuid') if isinstance(player, Mapping) else None,
            'action_session': client.get('action_session') if isinstance(client, Mapping) else None,
        }
        identity_valid = actual_identity == self._identity
        if not identity_valid:
            # Store field names only: arbitrary malformed values need not be JSON serializable.
            self._latch('health_observation_identity_mismatch', phase=phase, detail={
                'mismatched_fields': [key for key in IDENTITY_FIELDS
                                      if actual_identity[key] != self._identity[key]],
            })
        health = player.get('health') if isinstance(player, Mapping) else None
        health_valid = _finite_number(health) and health >= 0
        if not health_valid:
            self._latch('health_value_missing_or_invalid', phase=phase)

        valid = identity_valid and health_valid and timing_valid and phase_valid
        sample = {'record_index': self._record_calls, 'phase': phase, 'valid': valid,
                  'started_monotonic': started_monotonic if _finite_number(started_monotonic) else None,
                  'finished_monotonic': finished_monotonic if _finite_number(finished_monotonic) else None,
                  'health': health if health_valid else None}
        self._samples.append(sample)
        if identity_valid and health_valid:
            # Retain actual decreases even if a timing/phase gap already stopped
            # the trial. Never erase damage by classifying it only as unknown.
            self._latest_health = health
            if health == 0:
                self._latch('health_zero_observed', phase=phase)
            if self._previous_health is not None and health < self._previous_health:
                self._decrease_count += 1
                self._latch('health_decrease_observed', phase=phase, detail={
                    'previous_health': self._previous_health,
                    'health': health,
                    'decrease_hp': self._previous_health - health,
                })
            self._previous_health = health
        if valid:
            self._valid_phase_counts[phase] += 1
            if self._baseline_health is None and phase == 'before':
                self._baseline_health = health
        return self.report()

    def report(self, *, final=False, now_monotonic=None):
        """Return a snapshot; final=True seals and checks all three read phases.

        A native succeeded result cannot clear stop_required. The integration
        must consult this after the final read and give STOPPED-SAFETY precedence
        over any concurrent terminal winner or bounded-clearance claim.
        """
        self._check_clock(now_monotonic)
        if final and not self._finalized:
            for phase in PHASES:
                if self._valid_phase_counts[phase] == 0:
                    self._latch('health_' + phase + '_observation_window_missing', phase=phase)
            self._finalized = True
        baseline_missing = self._baseline_health is None
        stopped = bool(self._reasons) or baseline_missing
        complete = (self._finalized and not stopped
                    and all(self._valid_phase_counts.values()) and not self._timing_invalid)
        reasons = list(self._reasons)
        if baseline_missing and 'health_before_baseline_missing' not in reasons:
            reasons.append('health_before_baseline_missing')
        return deepcopy({
            'schema_version': 1,
            'identity': self._identity,
            'status': ('STOPPED-SAFETY' if self._reasons else
                       'BLOCKED-NO-BASELINE' if baseline_missing else
                       'SAMPLED-HEALTH-ONLY'),
            'stop_required': stopped,
            'stop_latched': bool(self._reasons),
            'reason': reasons[0] if reasons else None,
            'reasons': reasons,
            'ready_to_submit': (not stopped and not self._finalized
                                and self._phase_index == PHASES.index('before')),
            'controller_same_owner_stop_required': stopped and self._action_may_have_started,
            'stop_authority_granted': False,
            'automatic_cancel': False,
            'automatic_escape': False,
            'finalized': self._finalized,
            'baseline_health': self._baseline_health,
            'latest_health': self._latest_health,
            'decrease_observed': self._decrease_count > 0,
            'decrease_count': self._decrease_count,
            'no_decrease_observed': True if complete else None,
            'sampled_health_window_complete': bool(complete),
            'valid_phase_counts': self._valid_phase_counts,
            'sample_count': len(self._samples),
            'samples': self._samples,
            'events': self._events,
            'outer_gap_limit_seconds': self._max_gap_seconds,
            'continuous_health_coverage_proven': False,
            'absence_of_damage_proven': False,
            'hard_realtime_stop_proven': False,
            'controlled_trial_accepted': False,
            'full_active_ai_acceptance': False,
            'requires_handoff': True,
            'risk_remaining': True,
            'safety_assured': False,
            'evidence_limit': ('Outer request timing and finite health samples only; '
                               'stable readings cannot exclude damage and healing between samples.'),
        })
