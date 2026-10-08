"""One registered encounter, using existing ledger/health/queue components.

No CLI, transport construction, launch, entity setup, retry or automatic cancel.
The caller must first complete the separately approved local-world preflight and
register the two actual adult NoAI entities in the queue-scoped safety ledger.
"""
from pathlib import Path
import time

from encounter_health import HealthStopGuard
from post_trial_safety import SafetyHalt, _write


def run_registered_case(safety, binding, trial_name, *,
                        closeout_authorization=None, clock=time.monotonic):
    """Submit once, retain every observation, and save the immutable report.

    ``safety`` is the existing PostTrialSafety with its operator/queue; ``binding``
    is the exact registered EncounterBinding. No identities or budgets are made
    here. ``trial_name`` names the original report in operator.out.

    Closeout defaults OFF. An explicit authorization reference permits the two
    existing cleanup_uuid calls followed by pause_once only after a known,
    released outcome and a non-stopped health window. Unknown or failed effects
    end the sequence. External operator rescue remains necessary on stops.
    The injected clock must be the monotonic clock used for observation timing.
    """
    operator = safety.o
    safety.require_noai_case()
    command = {'op': 'action', **binding.encounter_request}
    safety.reserve_trial(binding, command, trial_name)
    case = safety._current()
    output = Path(operator.out)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / (trial_name + '.json')
    health = HealthStopGuard(binding, clock=clock)
    report = {'name': trial_name, 'request_id': binding.request_id,
        'binding': binding.wire(), 'command': command, 'before': None,
        'after': None, 'samples': [], 'response': None, 'interrupt_proof': None}
    stopped = None

    def observe(phase):
        started = clock()
        try:
            observation = safety._observe(output, trial_name + '-' + phase, binding,
                owner=binding.request_id if phase != 'before' else None,
                released=phase == 'before')
        except Exception as exc:
            report['observation_error'] = {'phase': phase,
                'type': type(exc).__name__, 'reason': str(exc)}
            raise
        finished = clock()
        report['samples'].append({'phase': phase, 'started_monotonic': started,
            'finished_monotonic': finished, 'observation': observation})
        health.record(observation, started, finished, phase)
        return observation

    try:
        report['before'] = observe('before')
        if not health.report()['ready_to_submit'] or health.report()['baseline_health'] != 20:
            raise SafetyHalt('health_baseline_blocks_submit')
        # This is an outer observation deadline, not a replacement native budget.
        # The native command keeps its original timeout and single action identity.
        deadline = clock() + command.get('timeout_ms', 15000) / 1000
        report['observer_deadline_monotonic'] = deadline
        safety.claim_trial_dispatch(binding.request_id, command)
        if operator.c.submit(command, request_id=binding.request_id) != binding.request_id:
            raise SafetyHalt('trial_submit_id_mismatch')
        while True:
            report['response'] = operator.c.result(binding.request_id)
            observe('running')  # Keep terminal winners as well as running samples.
            if health.report()['stop_required']:
                stopped = 'health_stop_requires_operator_handoff'
                break
            if report['response'] is not None:
                break
            if clock() >= deadline:
                stopped = 'observer_deadline_not_action_failure'
                break
        report['after'] = observe('after')
        if report['response'] is None:
            report['response'] = operator.c.result(binding.request_id)
        if report['response'] is None:
            report['response'] = {'request_id': binding.request_id,
                'status': 'pending', 'reason': 'observer_deadline_not_action_failure'}
    except Exception as exc:
        stopped = str(exc)
        report['error'] = {'type': type(exc).__name__, 'reason': stopped}
        health.mark_unknown(stopped)

    report['health'] = health.report(final=True)
    if report['health']['stop_required'] and stopped is None:
        stopped = 'health_stop_requires_operator_handoff'
    report['stopped_reason'] = stopped
    report['controlled_trial_accepted'] = False
    report['live_acceptance_proven'] = False
    _write(report_path, report)
    result = {'report_path': str(report_path), 'health': report['health'],
        'resolution': None, 'closeout': [], 'stopped_reason': stopped,
        'controlled_trial_accepted': False, 'live_acceptance_proven': False}
    try:
        result['resolution'] = safety.record_trial(report)
    except Exception as exc:
        result['record_trial_error'] = {'type': type(exc).__name__, 'reason': str(exc)}
        if result['stopped_reason'] is None:
            result['stopped_reason'] = str(exc)
        # Incomplete observations may fail before record_trial creates its stop.
        try:
            safety._stop(case, 'single_case_report_unresolved', error=str(exc))
        except SafetyHalt:
            pass
    if result['resolution'] is not None and stopped is None and closeout_authorization is not None:
        try:
            for entity in binding.encounter_request['encounter_scope']:
                result['closeout'].append(safety.cleanup_uuid(entity['uuid'], closeout_authorization))
            result['closeout'].append(safety.pause_once(closeout_authorization))
        except Exception as exc:
            result['stopped_reason'] = str(exc)
    _write(output / (trial_name + '.closeout.json'), result)
    return result
