"""Explicit offline demonstration using synthetic cells and fake native receipts."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import time

from .coordinator import Coordinator
from .schema import Context, Grant
from .snapshots import Acquisition
from .threats import ThreatClearance


def run_demo():
    fixture = json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'synthetic_snapshot.json').read_text())
    context = Context.parse(fixture['context'])
    with tempfile.TemporaryDirectory(prefix='mdcoord-demo-') as tmp:
        owner = Coordinator(tmp)
        try:
            lease = owner.activate(Grant('demo-task', context, frozenset({'follow_path'}),
                                        (-4, 63, -4, 20, 65, 4), lease_ms=5000))
            now = time.monotonic()
            capture = Acquisition(owner.snapshots.epoch, now, now, 1_700_000_000_000, 10)
            snapshot = owner.snapshots.publish(context, 'demo-observation', fixture['sections'], capture, 3000)
            # Independent synthetic simulator assessment: the listed zombie is
            # outside this corridor and cannot threaten it. Entity version/list
            # equality alone never yields this assertion; no live evidence exists.
            owner.threats.publish(ThreatClearance(
                proof_id='demo-synthetic-clearance', context=context,
                entities_sample_id=snapshot['sections']['entities']['sample_id'],
                entities_content_revision=snapshot['sections']['entities']['content_revision'],
                acquisition=capture, ttl_ms=3000, complete=True, no_threats=True, valid=True,
                bounds=(.5, 64, .5, 2.5, 64, .5)))
            def plan(pid, start, end, dependencies):
                snapshot = owner.planner().snapshot()
                return {'proposal_id': pid, 'task_id': 'demo-task', 'epoch': lease['epoch'],
                        'lease_revision': lease['revision'], 'role': 'route_planner',
                        'context': context.wire(), 'based_on': {'terrain': snapshot['sections']['terrain']['revision']},
                        'ttl_ms': 3000, 'intent': {'kind': 'follow_path', 'timeout_ms': 1000,
                                                 'waypoints': [{'x': end, 'y': 64, 'z': .5}]},
                        'dependencies': dependencies, 'priority': 10, 'cancel_requested': False,
                        'preconditions': {'alive': True, 'grounded': True, 'screen_closed': True, 'min_health': 5,
                                          'expected_position': {'x': start, 'y': 64, 'z': .5}}}
            owner.planner().submit(plan('first-segment', .5, 1.5, []))
            with ThreadPoolExecutor(max_workers=3) as workers:
                next_segment = workers.submit(owner.planner().submit, plan('second-segment', 1.5, 2.5, ['first-segment']))
                map_view = workers.submit(owner.planner().snapshot)
                resource_view = workers.submit(owner.planner().snapshot)
                next_segment.result(); map_view.result(); resource_view.result()
            owner.advance()
            owner.executor.finish(owner.active['action_id'])
            # Explicitly simulate the fresh arrival observation; no submit-success shortcut.
            new_player = dict(fixture['sections']['player'], x=1.5)
            now = time.monotonic()
            owner.snapshots.publish(context, 'demo-arrival', {'player': new_player},
                                    Acquisition(owner.snapshots.epoch, now, now, 1_700_000_000_100, 11), 3000)
            owner.advance()
            owner.executor.finish(owner.active['action_id'])
            owner.advance()
            return {'mode': 'offline_synthetic_only', 'roles': ['route_planner', 'map_reader', 'resource_reader'],
                    'dispatch_count': len(owner.executor.dispatches), 'max_writers': owner.executor.max_writers,
                    'receipts': [owner.result(pid) for pid in ('first-segment', 'second-segment')],
                    'metrics': owner.metrics.snapshot(), 'live_integration': False,
                    'speedup_verified': False, 'real_game_actions': 0}
        finally:
            owner.close()
