"""One owner-thread guard job. It never races a second Python action thread."""
from copy import deepcopy
import math
import json
import uuid
from .core import Outcome, SkillError, require
VERSION = 'native-fall-rescue-owner-guard/1'
LEASE_MS = 5000

POLL_SECONDS = .25
RENEW_SECONDS = 1.0


def _exchange(runtime, control, operation, arm_id, revision=None):
    from resident_controller.fall_rescue_control import validate_control_receipt
    with runtime._mutex:
        control.checkpoint()
        require(not runtime.has_unresolved_execution, 'fall_rescue_original_control_unresolved')
        session = runtime._session()
        require(session.get('native_fall_rescue_owner_guard') == VERSION, 'fall_rescue_owner_transport_unavailable')
        context = deepcopy(runtime._lease_info['context'])
        owner = runtime.owner_context()
        proof = {k: owner[k] for k in ('owner_id', 'owner_generation')}
        proof['job_id'] = control.job_id
        body = {'op': 'fall_rescue_control', 'operation': operation, 'arm_id': arm_id,
                'control_owner': proof, 'expected_context': context}
        if operation in ('arm', 'renew'):
            body['ttl_ms'] = LEASE_MS
        if operation == 'renew':
            body['expected_arm_revision'] = revision
        control.consume('observations' if operation == 'status' else 'actions')
        record = runtime._reserve('fall_rescue_control', runtime._owned_command(deepcopy(body), session), skill='fall_rescue_guard')
        # Persistence callbacks may have received cancel; reject a known unsent
        # control here instead of arming after that stop or orphaning its record.
        try:
            control.checkpoint()
            stop = control.stop_reason() if control.lane != 'cleanup' else None
            if stop:
                raise SkillError(stop, status='cancelled' if stop == 'cancel_requested' else 'interrupted')
        except SkillError as exc:
            runtime._finish(record, exc.status, exc.reason, {'submission_outcome': 'stopped_before_dispatch'})
            raise
        # Controls can authorize future effects. Unknown is set before any write.
        if operation != 'status':
            runtime._job_effect_certainty = 'unknown'
        result = runtime._exchange(record)
        if result.get('status') != 'succeeded':
            runtime._unknown(record, 'fall_rescue_control_not_confirmed:' + str(result.get('reason', 'unknown')))
        try:
            require(json.dumps(result.get('control_owner'), sort_keys=True) == json.dumps(proof, sort_keys=True),
                    'fall_rescue_control_owner_receipt_changed')
            checked = validate_control_receipt(result, {**body,
                'expected_resident_session': runtime._lease_info['resident_session']},
                getattr(control, 'fall_rescue_last_status', None))
            control.fall_rescue_last_status = deepcopy(checked)
        except (ValueError, KeyError, TypeError, SkillError) as exc:
            runtime._unknown(record, 'fall_rescue_native_status_unconfirmed:' + str(exc))
        runtime._finish(record, 'succeeded', 'fall_rescue_renew_refused_stopped' if 'fall_rescue_renewal_stop' in result else 'fall_rescue_' + operation + '_observed', checked)
        control.emit('fall_rescue_status', {'arm_id': arm_id, 'control_owner': proof, 'native': checked,
            'standalone_guard': True, 'concurrent_ordinary_job_protection': False})
        return checked


def guard(runtime, control, *, duration_ms=60000):
    require(type(duration_ms) is int and 1000 <= duration_ms <= 600000, 'invalid_fall_rescue_duration')
    require(runtime.required_execution_policy == 'request_only', 'fall_rescue_request_only_policy_required')
    # Every control/read consumes the same original job ledger. The native reflex
    # is one bounded composite effect authorized by the arm, not unlimited work.
    limits = control.budget.snapshot()
    require(limits['remaining']['actions'] >= math.ceil(duration_ms / 1000) + 3,
            'fall_rescue_full_control_action_budget_required')
    require(limits['remaining']['observations'] >= math.ceil(duration_ms / 250) + 3,
            'fall_rescue_full_status_observation_budget_required')
    require(control.budget.remaining_seconds() >= duration_ms / 1000 + 2,
            'fall_rescue_original_deadline_too_short')
    initial = runtime.observe(allow_menu=False)
    feature = initial.state.get('native_fall_rescue', {})
    require(feature.get('schema_version') == 1 and feature.get('native_fences_ready') is True,
            'fall_rescue_native_fences_unavailable')
    require(feature.get('external_controller_unknown') is False, 'fall_rescue_external_controller_unknown')
    require(any(type(row) is dict and type(row.get('slot')) is int and 0 <= row['slot'] <= 8
        and row.get('id') == 'minecraft:water_bucket' and type(row.get('count')) is int and row['count'] == 1
        for row in initial.player.get('inventory', [])), 'fall_rescue_water_bucket_required_in_hotbar')
    arm_id = uuid.uuid4().hex
    armed = False
    last = None
    outcome = None
    started = runtime.clock()
    deadline = started + duration_ms / 1000
    try:
        last = _exchange(runtime, control, 'arm', arm_id)
        armed = True
        deadline = runtime.clock() + duration_ms / 1000
        next_renew = runtime.clock() + RENEW_SECONDS
        while runtime.clock() < deadline:
            control.checkpoint()
            if not last['armed']:
                break
            # The native authorization is renewed by this same owner thread only.
            # A crash/cancel/unknown response stops renewal; it expires within 5s.
            if runtime.clock() >= next_renew:
                last = _exchange(runtime, control, 'renew', arm_id, last['arm_revision'])
                next_renew = runtime.clock() + RENEW_SECONDS
            else:
                last = _exchange(runtime, control, 'status', arm_id)
            runtime.sleeper(min(POLL_SECONDS, max(0, deadline - runtime.clock())))
        completed_window = runtime.clock() >= deadline
        monitoring_end = deepcopy(last)
    finally:
        # Never issue another command after an ambiguous original control, even
        # a read timeout. Preserve its identity and let the bounded native lease expire.
        if armed and not runtime.has_unresolved_execution:
            with control.cleanup():
                last = _exchange(runtime, control, 'disarm', arm_id)
                episode = last.get('last_episode', {})
                runtime._job_effect_certainty = ('known' if episode.get('rescue_confirmed') is True else
                    'unknown' if episode.get('dispatch_attempted') is True else 'none_proven')
    episode = (last or {}).get('last_episode', {})
    if episode.get('rescue_confirmed') is True:
        return Outcome('succeeded', 'server_placement_and_landing_observed', evidence={'native': last})
    if episode.get('dispatch_attempted') is True:
        return Outcome('unknown', 'fall_rescue_attempt_not_confirmed', evidence={'native': last})
    return Outcome('succeeded' if completed_window else 'interrupted',
        'guard_window_ended_without_dispatch' if completed_window else 'native_guard_disarmed_before_window_end',
        evidence={'native': last, 'monitoring_end': monitoring_end, 'fall_prevented': False,
                  'concurrent_ordinary_job_protection': False})
