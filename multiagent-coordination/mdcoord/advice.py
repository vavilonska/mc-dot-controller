"""Two-layer planning: read-only goal advice, then independent fresh replanning.

Advice is not a Proposal. It has no action, timeout, lease, authorization or
execution preconditions. Only a new observation can feed the deterministic owner
route planner; it constructs a new candidate and never refreshes an old one.
"""
from dataclasses import dataclass
from collections import deque
import hashlib
import json
import math

from .schema import canonical, fields, integer, point, require


@dataclass(frozen=True)
class PlanningAdvice:
    encoded: bytes
    request_id: str
    completed_mono: float

    def wire(self):
        return json.loads(self.encoded)


def make_route_advice(value, request, completed, source_lease):
    fields(value, ('kind', 'goal', 'based_on'))
    require(value['kind'] == 'route_goal', 'advice_kind')
    goal = point(value['goal'])
    snapshot = request.wire()['snapshot']
    require(type(value['based_on']) is dict and set(value['based_on']) == {'terrain'}, 'advice_dependencies')
    integer(value['based_on']['terrain'], 1, 2**63 - 1)
    require(value['based_on']['terrain'] == snapshot['sections']['terrain']['content_revision'],
            'advice_source_revision')
    sources = {name: {k: snapshot['sections'][name][k] for k in
                     ('sample_id', 'content_revision', 'capture_started_mono', 'capture_finished_mono')}
               for name in ('player', 'terrain', 'entities')}
    result = {'kind': 'route_goal', 'goal': goal, 'source_context': snapshot['context'],
              'source_clock_epoch': snapshot['clock_epoch'], 'sources': sources,
              'source_task_id': source_lease['task_id'], 'source_lease_epoch': source_lease['epoch'],
              'source_terrain_sha256': hashlib.sha256(canonical(snapshot['sections']['terrain']['data'])).hexdigest(),
              'requires_new_observation': True, 'authorized': False, 'actionable': False}
    return PlanningAdvice(canonical(result), request.request_id, completed)


def route_candidate_from_advice(advice, fresh_snapshot, current_lease, *, max_waypoints=1):
    """Pure owner replan. Returns unprivileged Candidate fields, not authorization.

    This low-level dict is not submit-ready. Use seal_advice_candidate for the
    owner-registry-bound capture/replan/seal path; planner-mode submission rejects
    raw wrapping without that immutable receipt.
    Caller must obtain a genuinely NEW observation, then bind a new proposal ID,
    current lease/context, run threat/preflight/budget checks and choose at most
    one candidate. Missing source capture identities fail closed. Changed terrain
    is fully replanned; no old waypoint, expected position or freshness is reused.
    """
    require(type(advice) is PlanningAdvice, 'typed_advice_required')
    integer(max_waypoints, 1, 16)
    value = advice.wire()
    require(type(current_lease) is dict and current_lease.get('task_id') == value['source_task_id'] and
            current_lease.get('epoch') == value['source_lease_epoch'], 'advice_task_fence')
    require(fresh_snapshot['context'] == value['source_context'] and
            fresh_snapshot['clock_epoch'] == value['source_clock_epoch'], 'advice_session_fence')
    for name in ('player', 'terrain', 'entities'):
        new, old = fresh_snapshot['sections'].get(name), value['sources'][name]
        require(new is not None and new['freshness'] == 'fresh', 'advice_new_observation_not_fresh')
        require(old['capture_started_mono'] is not None and new['capture_started_mono'] is not None and
                new['sample_id'] != old['sample_id'] and
                new['capture_started_mono'] > old['capture_started_mono'], 'advice_independent_observation_required')
    terrain = fresh_snapshot['sections']['terrain']['data']
    require(terrain['complete'] is True, 'advice_terrain_incomplete')
    player = fresh_snapshot['sections']['player']['data']
    start = {key: player[key] for key in ('x', 'y', 'z')}
    goal = value['goal']
    require(start['x'] % 1 == .5 and start['z'] % 1 == .5 and start['y'] % 1 == 0 and
            goal['x'] % 1 == .5 and goal['z'] % 1 == .5 and goal['y'] == start['y'],
            'advice_flat_centered_goal_required')
    cells = {(c['x'], c['y'], c['z']): c for c in terrain['cells']}
    def safe(position):
        x, y, z = position
        for dy in (-1, 0, 1):
            cell = cells.get((math.floor(x), int(y) + dy, math.floor(z)))
            if not cell or cell['loaded'] is not True or cell['hazard'] is not False or cell['fluid'] is not False:
                return False
            if (cell['full_support'] is not True if dy == -1 else cell['passable'] is not True):
                return False
        return True
    origin = tuple(start[k] for k in ('x', 'y', 'z'))
    target = tuple(goal[k] for k in ('x', 'y', 'z'))
    require(origin != target and safe(origin) and safe(target), 'advice_goal_unavailable')
    frontier = deque([(origin, [])])
    seen = {origin}
    while frontier:
        current, path = frontier.popleft()
        if current == target:
            return {'intent': {'kind': 'follow_path', 'timeout_ms': 1000,
                               'waypoints': [dict(zip(('x', 'y', 'z'), p)) for p in path[:max_waypoints]]},
                    'based_on': {'terrain': fresh_snapshot['sections']['terrain']['content_revision']},
                    'dependencies': [], 'priority': 10,
                    'preconditions': {'alive': True, 'grounded': True, 'screen_closed': True,
                                      'min_health': 5, 'expected_position': start}}
        if len(path) >= 16:
            continue
        x, y, z = current
        for neighbor in ((x + 1, y, z), (x - 1, y, z), (x, y, z + 1), (x, y, z - 1)):
            if neighbor not in seen and safe(neighbor):
                seen.add(neighbor)
                frontier.append((neighbor, path + [neighbor]))
    require(False, 'advice_no_safe_route')
