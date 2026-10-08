"""One explicitly registered active-AI case, followed by one non-toggling pause.

No fixture setup, cleanup, replay, credentials or transport construction. Explicit
resume authorization permits one Escape from a freshly verified native pause,
after the baseline and all claims are complete. Read evidence stays in memory
until native-hook reconciliation or fallback pause. This is cooperative software,
not a hard-real-time stop or proof that the integrated server already paused.
"""
from copy import deepcopy
from pathlib import Path
import time
import uuid

from encounter_health import HealthStopGuard
from post_trial_safety import SafetyHalt, MAX_OBSERVE_SECONDS, _load, _ref, _require, _write
from receipt_binding import _uncertain
from resident_controller.pause_contract import validate_pause_receipt


def run_registered_active_case(safety, binding, trial_name, *, resume_authorization_ref=None,
                               clock=time.monotonic):
    operator = safety.o
    _require(binding.encounter_request.get('encounter_pause_on_terminal') is True,
             'active_case_requires_native_terminal_pause')
    _require(_ref(resume_authorization_ref), 'active_resume_authorization_required')
    with safety._locked():
        case = safety._current()
        registration = _load(case / 'registration.json')
        _require(registration.get('active_ai_supported') is True,
                 'active_pause_first_entry_requires_explicit_active_case')
        _require(not (case / 'SAFETY-STOP.json').exists(), 'case_safety_stopped')
    command = {'op': 'action', **binding.encounter_request}
    safety.reserve_trial(binding, command, trial_name)
    output = Path(operator.out)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / (trial_name + '.json')
    pause_body = {'pause_schema_version': 1,
        'expected_action_session': binding.action_session,
        'expected_world_generation': binding.world_generation,
        'expected_player_uuid': binding.player_uuid,
        'expected_action_id': binding.expected_action_id}
    pause_id = uuid.uuid5(uuid.UUID(binding.resident_session), binding.request_id + ':pause').hex
    pause_command = {'op': 'encounter_pause', 'expected_resident_session': binding.resident_session,
                     'body': pause_body}
    # Reserve the one possible pause before the original action can be sent.
    _write(case / 'active-pause-reservation.json', {'request_id': pause_id,
        'owner_request_id': binding.request_id, 'command': pause_command,
        'authorization_ref': registration['pause_authorization_ref'], 'automatic_retry': False})
    resume_id = uuid.uuid5(uuid.UUID(binding.resident_session), binding.request_id + ':resume').hex
    resume_command = {'op': 'direct', 'endpoint': 'raw-key',
        'body': {'key': 'key.keyboard.escape', 'action': 'click'}}
    _write(case / 'active-resume-reservation.json', {'request_id': resume_id,
        'command': resume_command, 'authorization_ref': resume_authorization_ref,
        'only_from_verified_native_pause': True, 'automatic_retry': False})
    health = HealthStopGuard(binding, clock=clock)
    report = {'name': trial_name, 'request_id': binding.request_id,
        'binding': binding.wire(), 'command': command, 'before': None, 'after': None,
        'samples': [], 'raw_observations': [], 'response': None, 'interrupt_proof': None,
        'active_ai_case': True, 'pause_first': True, 'main_submit_attempted': False,
        'resume': {'request_id': resume_id, 'command': resume_command, 'response': None}}
    pause = {'request_id': pause_id, 'command': pause_command, 'response': None,
             'native_pause_observed': False, 'native_release_observed': False,
             'automatic_retry': False}
    stopped = None
    pause_attempted = False

    def observe(phase, *, released=False):
        """Check this read immediately; persist its raw evidence after the stop call."""
        started = clock()
        session = safety._session(binding.request_id if phase != 'before' else None)
        read_id = uuid.uuid4().hex
        body = {'op': 'observe', 'frame': False}
        raw = {'request_id': read_id, 'command': body, 'session_before': session,
               'started_monotonic': started, 'receipt': None}
        report['raw_observations'].append(raw)
        _require(operator.c.submit(body, request_id=read_id) == read_id, 'observation_submit_id_mismatch')
        receipt = operator.c.wait(read_id, 20)
        finished = clock()
        raw.update(receipt=receipt, finished_monotonic=finished)
        _require(type(receipt) is dict and receipt.get('request_id') == read_id
            and receipt.get('session_id') == binding.resident_session
            and receipt.get('status') == 'succeeded' and not _uncertain(receipt),
            'fresh_observation_receipt_unknown_or_failed')
        _require(0 <= finished - started <= MAX_OBSERVE_SECONDS, 'fresh_observation_too_slow')
        observation = receipt.get('result')
        safety._validate_observation(observation, binding, released=released)
        report['samples'].append({'phase': phase, 'started_monotonic': started,
            'finished_monotonic': finished, 'observation': deepcopy(observation)})
        health.record(observation, started, finished, phase)
        return observation

    def pause_first(reason):
        nonlocal pause_attempted, stopped
        _require(not pause_attempted, 'active_pause_already_attempted_no_retry')
        pause_attempted = True
        pause['first_stop_reason'] = reason
        pause['first_stop_observed_monotonic'] = clock()
        # A bound native hook attempt consumes the pause even when its effect is
        # unknown. Do not turn idempotence into permission to repeat that action.
        candidates = []
        response = report.get('response')
        if isinstance(response, dict):
            nested = response.get('result')
            if isinstance(nested, dict):
                candidates.append(nested.get('action'))
            candidates.extend(response.get(k) for k in ('action', 'resolved_action', 'cancellation'))
        candidates.extend(s['observation'].get('action') for s in report['samples'])
        for raw in report['raw_observations']:
            receipt = raw.get('receipt')
            if isinstance(receipt, dict) and isinstance(receipt.get('result'), dict):
                candidates.append(receipt['result'].get('action'))
        for action in candidates:
            if (isinstance(action, dict) and action.get('status') in ('succeeded', 'failed', 'cancelled')
                    and binding.native_problem(action) is None):
                hook = action.get('result', {}).get('encounter_terminal_pause', {})
                if hook.get('attempted') is True:
                    pause.update(source='native_terminal_hook', native_hook=deepcopy(hook),
                        fallback_skipped_prior_native_attempt=True)
                    if hook.get('outcome') != 'screen_installed':
                        stopped = stopped or 'native_terminal_pause_unconfirmed_no_retry'
                    return
        # One durable dispatch claim, then submit immediately. No native pre-read,
        # report serialization, cleanup chain or state-dependent Escape toggle.
        _write(case / 'active-pause-dispatch.json', {'request_id': pause_id,
            'command': pause_command, 'reason': reason, 'reserved_before_submit': True,
            'automatic_retry': False})
        pause['dispatch_started_monotonic'] = clock()
        _require(operator.c.submit(pause_command, request_id=pause_id) == pause_id,
                 'active_pause_submit_id_mismatch')
        receipt = operator.c.wait(pause_id, 20)
        pause.update(response=receipt, response_observed_monotonic=clock())
        _require(type(receipt) is dict and receipt.get('request_id') == pause_id
            and receipt.get('session_id') == binding.resident_session
            and receipt.get('status') == 'succeeded' and not _uncertain(receipt),
            'active_pause_response_unknown_no_retry')
        result = receipt.get('result')
        validate_pause_receipt(result, pause_body, binding.encounter_request)
        if result['expected_action_present']:
            _require(binding.native_problem(result['client_action']) is None,
                     'active_pause_original_action_mismatch')

    try:
        report['before'] = observe('before', released=True)
        before = report['before']
        _require(safety._paused(before), 'active_case_requires_paused_fresh_baseline')
        for entity in registration['entities']:
            actual = safety._find(before, entity)
            _require(actual is not None and actual['alive'] is True, 'active_scope_not_freshly_observed')
        _require(health.report()['ready_to_submit'] and health.report()['baseline_health'] == 20,
                 'health_baseline_blocks_submit')
        # Burn all claims while paused, so no disk preflight or large observation
        # lies between the known resume dispatch and the one original submit.
        safety.claim_trial_dispatch(binding.request_id, command)
        _write(case / 'active-resume-dispatch.json', {'request_id': resume_id,
            'command': resume_command, 'reserved_before_submit': True, 'automatic_retry': False})
        report['resume']['dispatch_started_monotonic'] = clock()
        _require(operator.c.submit(resume_command, request_id=resume_id) == resume_id,
                 'active_resume_submit_id_mismatch')
        resumed = operator.c.wait(resume_id, 1)
        report['resume'].update(response=resumed, response_observed_monotonic=clock())
        _require(type(resumed) is dict and resumed.get('request_id') == resume_id
            and resumed.get('session_id') == binding.resident_session
            and resumed.get('status') == 'succeeded' and not _uncertain(resumed)
            and resumed.get('reason') == 'direct_input_dispatched'
            and resumed.get('result', {}).get('ok') is True
            and resumed['result'].get('key') == 'key.keyboard.escape'
            and resumed['result'].get('action') == 'click'
            and resumed['result'].get('down') is False, 'active_resume_unknown_main_not_submitted')
        _require(health.report()['ready_to_submit'], 'paused_baseline_expired_during_resume')
        report['main_submit_started_monotonic'] = clock()
        report['resume_to_main_submit_seconds'] = (report['main_submit_started_monotonic']
            - report['resume']['response_observed_monotonic'])
        report['resume_to_native_admission_is_not_atomic'] = True
        deadline = clock() + command.get('timeout_ms', 15000) / 1000
        report['observer_deadline_monotonic'] = deadline
        report['main_submit_attempted'] = True
        _require(operator.c.submit(command, request_id=binding.request_id) == binding.request_id,
                 'trial_submit_id_mismatch')
        while True:
            report['response'] = operator.c.result(binding.request_id)
            if report['response'] is not None:
                pause_first('original_response_observed')
                break
            observation = observe('running')
            if health.report()['stop_required']:
                stopped = 'health_stop_requires_operator_handoff'
                pause_first(stopped)
                break
            relation = binding.classify_observation(observation)
            if relation['relation'] == 'bound' and relation['action']['status'] != 'running':
                pause_first('original_terminal_observation')
                break
            if clock() >= deadline:
                stopped = 'observer_deadline_not_action_failure'
                pause_first(stopped)
                break
    except Exception as exc:
        stopped = str(exc)
        report['error'] = {'type': type(exc).__name__, 'reason': stopped}
        health.mark_unknown(stopped)
        if not pause_attempted:
            try:
                pause_first(stopped)
            except Exception as pause_error:
                pause['error'] = {'type': type(pause_error).__name__, 'reason': str(pause_error)}
        else:
            pause['error'] = {'type': type(exc).__name__, 'reason': str(exc)}

    # Only reads follow the one pause attempt, including when its outcome is unknown.
    try:
        report['after'] = observe('after', released=True)
        _require(safety._paused(report['after']), 'active_pause_effect_unverified')
        pause['native_pause_observed'] = True
        pause['native_release_observed'] = True
    except Exception as exc:
        pause['effect_error'] = {'type': type(exc).__name__, 'reason': str(exc)}
        stopped = stopped or str(exc)
        health.mark_unknown(str(exc), phase='after')
    try:
        if report['response'] is None and report['main_submit_attempted']:
            report['response'] = operator.c.result(binding.request_id)
    except Exception as exc:
        stopped = stopped or str(exc)
        report['result_error'] = {'type': type(exc).__name__, 'reason': str(exc)}
    if report['response'] is None:
        report['response'] = {'request_id': binding.request_id,
            'status': 'pending' if report['main_submit_attempted'] else 'not_submitted',
            'reason': 'original_action_outcome_still_unknown' if report['main_submit_attempted']
                      else 'resume_not_confirmed_original_never_submitted'}
    report['health'] = health.report(final=True)
    if report['health']['stop_required']:
        stopped = stopped or 'health_stop_requires_operator_handoff'
    report.update(stopped_reason=stopped, controlled_trial_accepted=False, live_acceptance_proven=False,
                  pause=pause, automatic_cleanup=False)
    _write(report_path, report)
    _write(case / 'active-pause-result.json', pause)
    result = {'report_path': str(report_path), 'health': report['health'], 'resolution': None,
        'pause': pause, 'closeout': [], 'stopped_reason': stopped,
        'controlled_trial_accepted': False, 'live_acceptance_proven': False}
    try:
        result['resolution'] = safety.record_trial(report)
    except Exception as exc:
        result['record_trial_error'] = {'type': type(exc).__name__, 'reason': str(exc)}
        result['stopped_reason'] = result['stopped_reason'] or str(exc)
    # No next case or ordinary mutation may follow even a known paused terminal.
    try:
        safety._stop(case, 'active_case_requires_separate_operator_closeout',
                     pause_observed=pause['native_pause_observed'], stopped_reason=result['stopped_reason'])
    except SafetyHalt:
        pass
    _write(output / (trial_name + '.closeout.json'), result)
    return result
