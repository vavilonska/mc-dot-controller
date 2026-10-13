"""Reproducible planning benchmark. All observations and actions are synthetic.

`controlled` measures real overlapping callbacks, not LLM inference.
`native` waits for actual native-host completions in a dedicated local spool.
Three-second observation TTL is preserved; late inference is diagnostic only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import time
import uuid

from .advice import PlanningAdvice, route_candidate_from_advice
from .coordinator import Coordinator
from .host_bridge import NativeHostBridge, _read
from .planning import PlannerScheduler, PlannerWorker, seal_advice_candidate
from .safety import preflight
from .schema import Context, Grant, Rejected, canonical
from .snapshots import Acquisition
from .threats import ThreatClearance


ROLES = ('short_route', 'cautious_route', 'progress_route')


def candidate_for(request, *, length=1):
    snapshot = request.wire()['snapshot']
    player = snapshot['sections']['player']['data']
    start = {k: player[k] for k in ('x', 'y', 'z')}
    return {'intent': {'kind': 'follow_path', 'timeout_ms': 1000,
                       'waypoints': [{**start, 'x': start['x'] + n + 1} for n in range(length)]},
            'based_on': {'terrain': snapshot['sections']['terrain']['content_revision']},
            'dependencies': [], 'priority': 10,
            'preconditions': {'alive': True, 'grounded': True, 'screen_closed': True,
                              'min_health': 5, 'expected_position': start}}


def setup_owner(directory):
    fixture = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/synthetic_snapshot.json').read_text())
    context = Context.parse(fixture['context'])
    owner = Coordinator(directory)
    owner.activate(Grant('benchmark-task', context, frozenset({'follow_path'}),
                         (-4, 63, -4, 20, 65, 4), lease_ms=30_000, duration_ms=60_000))
    now = owner.clock()
    acquisition = Acquisition(owner.snapshots.epoch, now, now, 1_700_000_000_000, 10)
    snapshot = owner.snapshots.publish(context, 'benchmark-observation', fixture['sections'], acquisition, 3000)
    owner.threats.publish(ThreatClearance(
        proof_id='benchmark-synthetic-clearance', context=context,
        entities_sample_id=snapshot['sections']['entities']['sample_id'],
        entities_content_revision=snapshot['sections']['entities']['content_revision'],
        acquisition=acquisition, ttl_ms=3000, complete=True, no_threats=True, valid=True,
        bounds=(.5, 64, .5, 2.5, 64, .5)))
    return owner, now, hashlib.sha256(canonical(fixture)).hexdigest()


def new_synthetic_observation(owner):
    """A new simulator capture, never a timestamp edit of the stored sample."""
    fixture = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/synthetic_snapshot.json').read_text())
    context = Context.parse(fixture['context'])
    now = owner.clock()
    generation = getattr(owner, '_benchmark_capture_generation', 0) + 1
    owner._benchmark_capture_generation = generation
    acquisition = Acquisition(owner.snapshots.epoch, now, now, 1_700_000_000_000 + generation * 1000, 10 + generation)
    snapshot = owner.snapshots.publish(context, 'benchmark-new-independent-observation-' + str(generation),
                                       fixture['sections'], acquisition, 3000)
    owner.threats.publish(ThreatClearance(
        proof_id='benchmark-new-independent-clearance-' + str(generation), context=context,
        entities_sample_id=snapshot['sections']['entities']['sample_id'],
        entities_content_revision=snapshot['sections']['entities']['content_revision'],
        acquisition=acquisition, ttl_ms=3000, complete=True, no_threats=True, valid=True,
        bounds=(.5, 64, .5, 2.5, 64, .5)))
    return snapshot


def run_trial(mode, *, source='controlled', spool=None, workers=3, trial=0, budget_ms=1000, result_kind='candidate'):
    with tempfile.TemporaryDirectory(prefix='mdc-planning-bench-') as directory:
        owner, observed, fixture_digest = setup_owner(directory)
        scheduler = PlannerScheduler(owner.planner(), owner.lease_state)
        roles = ROLES[:workers]
        # Rotate serial order so the first serial worker is not always the slowest.
        roles = roles[trial % workers:] + roles[:trial % workers]
        if source == 'native':
            bridge = NativeHostBridge(spool)
            planners = [PlannerWorker(role, bridge.compute, 'native_host') for role in roles]
        else:
            delays = {'short_route': .04, 'cautious_route': .08, 'progress_route': .12}
            def callback(role):
                def compute(request):
                    time.sleep(delays[role])
                    if result_kind == 'advice':
                        snap = request.wire()['snapshot']
                        return {'kind': 'route_goal', 'goal': {'x': 2.5 if role == 'progress_route' else 1.5, 'y': 64, 'z': .5},
                                'based_on': {'terrain': snap['sections']['terrain']['content_revision']}}
                    return candidate_for(request, length=2 if role == 'progress_route' else 1)
                return compute
            planners = [PlannerWorker(role, callback(role)) for role in roles]
        first_safe = first_dispatch = first_candidate = None
        selected = None
        rejected = []
        try:
            batch = scheduler.start(planners, mode=mode, budget_ms=budget_ms,
                                    diagnostic_drain=source == 'native', result_kind=result_kind)
            if source == 'native':
                print(json.dumps({'event': 'batch_started', 'trial': trial, 'mode': mode,
                                  'batch_id': batch.batch_id, 'spool': str(spool),
                                  'observation_ttl_ms': 3000, 'planning_budget_ms': budget_ms, 'result_kind': result_kind}), flush=True)
            while not batch.finished:
                for candidate in batch.collect():
                    if first_candidate is None:
                        first_candidate = (owner.clock() - observed) * 1000
                    if selected is not None:
                        continue
                    try:
                        if type(candidate) is PlanningAdvice:
                            new_synthetic_observation(owner)
                            value = seal_advice_candidate(candidate, owner.planner()).wire()
                        else:
                            value = candidate.wire()
                        # Queued/syntax-valid is not safe. This benchmark uses the
                        # unchanged fixture preflight, then Coordinator rechecks.
                        preflight(value, owner.lease.grant, owner.snapshots.read(), owner.threats)
                        preflight_at = (owner.clock() - observed) * 1000
                        owner.planner().submit(value)
                        owner.advance()
                        if owner.active is not None:
                            first_safe = preflight_at
                            selected = value['proposal_id']
                            first_dispatch = (owner.clock() - observed) * 1000
                            # Simulate terminal/released receipt immediately; a
                            # slow model must not leave a fake action running
                            # beyond its execution budget while peers finish.
                            owner.executor.finish(owner.active['action_id'])
                            owner.advance()
                        else:
                            rejected.append(owner.result(value['proposal_id']))
                    except Rejected as exc:
                        rejected.append({'reason': str(exc)})
                if batch.exhausted:
                    batch.finish('benchmark_all_workers_observed')
                if not batch.finished:
                    time.sleep(.002)
            # A fake running action is explicitly completed and inputs released.
            if owner.active:
                owner.executor.finish(owner.active['action_id'])
                owner.advance()
            result = {'trial': trial, 'mode': mode, 'source': source, 'result_kind': result_kind,
                      'snapshot_input_sha256': fixture_digest, 'batch_id': batch.batch_id,
                      'frozen_snapshot_sha256': batch.snapshot_sha256,
                      'workers': workers, 'role_order': list(roles), 'budget_ms': budget_ms,
                      'quality_budget': {'max_output_tokens': 1024, 'reasoning_effort': 'xhigh'},
                      'observation_to_first_candidate_ms': first_candidate,
                      'observation_to_first_safe_candidate_ms': first_safe,
                      'observation_to_first_fake_dispatch_ms': first_dispatch,
                      'observation_to_batch_end_ms': (owner.clock() - observed) * 1000,
                      'events': batch.events, 'owner_rejections': rejected,
                      'native_host_evidence': [_read(p) | {'candidate': 'omitted_from_summary'}
                           for p in sorted(Path(spool).glob(batch.batch_id + '*.response.json'))] if source == 'native' else [],
                      'independent_observation': 'new_synthetic_capture' if result_kind == 'advice' and selected else None,
                      'fake_dispatches': len(owner.executor.dispatches),
                      'max_writers': owner.executor.max_writers,
                      'native_execution_ms': None, 'real_game_actions': 0}
            return result
        finally:
            scheduler.close()
            owner.close()


def distribution(values):
    values = sorted(x for x in values if x is not None)
    n = len(values)
    # A tiny real-model smoke sample does not provide a reliable tail estimate.
    return {'n': n, 'p50_ms': statistics.median(values) if values else None,
            'p95_ms': values[max(0, __import__('math').ceil(.95 * n) - 1)] if n >= 20 else None,
            'p95_note': None if n >= 20 else 'insufficient_samples_for_tail_estimate'}


def summarize(trials, source):
    result = {'source': source, 'actions': 'fake_executor_only', 'real_game_actions': 0,
              'model_inference_measured': source == 'native' and any(t['native_host_evidence'] for t in trials),
              'planner_timing_includes_host_dispatch_and_response_poll': source == 'native',
              'speedup_claim': None, 'modes': {}}
    for mode in ('serial', 'parallel'):
        group = [t for t in trials if t['mode'] == mode]
        events = [e for t in group for e in t['events']]
        reasons = Counter(e.get('reason', e['status']) for e in events)
        completed = [e for e in events if 'completed_mono' in e]
        advice_completed = [e for e in completed if e.get('status') == 'advice']
        started = [e for e in events if e.get('started_mono') is not None]
        timed_out = sum(e.get('reason') in {'planning_timeout', 'native_host_deadline'} for e in events)
        expired = sum(e.get('reason') in {'planning_observation_expired', 'planning_candidate_expired'} for e in events)
        result['modes'][mode] = {'trials': len(group), 'planner_events': len(events),
            'started_events': len(started), 'completed_events': len(completed),
            'not_started_events': sum(e.get('not_started', False) for e in events),
            'advice_completed_events': len(advice_completed),
            'timeout_rate_unit': 'planned_role_events_not_actual_model_calls',
            'observation_to_first_safe_candidate': distribution(t['observation_to_first_safe_candidate_ms'] for t in group),
            'observation_to_first_fake_dispatch': distribution(t['observation_to_first_fake_dispatch_ms'] for t in group),
            'observation_to_batch_end': distribution(t['observation_to_batch_end_ms'] for t in group),
            'planner_compute': distribution(e.get('duration_ms') for e in events),
            'timeout_rate': timed_out / len(events) if events else None,
            'expired_rate': expired / len(events) if events else None,
            'source_expired_before_advice_return_rate': sum(e.get('source_observation_expired_at_completion', False) for e in advice_completed) / len(advice_completed) if advice_completed else None,
            'event_reasons': dict(reasons),
            'safe_trial_rate': sum(t['observation_to_first_safe_candidate_ms'] is not None for t in group) / len(group) if group else None}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=('controlled', 'native'), default='controlled')
    parser.add_argument('--rounds', type=int, default=24)
    parser.add_argument('--workers', type=int, choices=(2, 3), default=3)
    parser.add_argument('--spool', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget-ms', type=int, default=1000)
    parser.add_argument('--result-kind', choices=('candidate', 'advice'), default='candidate')
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 64 or not 50 <= args.budget_ms <= 30_000:
        parser.error('bounded rounds or budget exceeded')
    if args.source == 'native' and (args.spool is None or not args.spool.is_dir() or any(args.spool.iterdir())):
        parser.error('native requires an empty existing dedicated --spool directory')
    trials = []
    for trial in range(args.rounds):
        # Counterbalance warmup/order effects without changing input or budget.
        modes = ('serial', 'parallel') if trial % 2 == 0 else ('parallel', 'serial')
        for mode in modes:
            trials.append(run_trial(mode, source=args.source, spool=args.spool,
                                    workers=args.workers, trial=trial, budget_ms=args.budget_ms, result_kind=args.result_kind))
            args.output.write_text(json.dumps({'summary': summarize(trials, args.source), 'trials': trials}, indent=2))
    print(json.dumps(summarize(trials, args.source), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
