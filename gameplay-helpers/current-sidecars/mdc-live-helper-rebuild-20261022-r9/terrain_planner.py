"""Pure 150-cell cardinal terrain proposals; no transport, ledger or world I/O.

The paired, unchanged C8 geometry and PLAN validator are used directly. A stage
is not an authorization: the caller must still bind its production PLAN and run
the original production gate against a fresh observation before each action.
There is no invented jump arc, apex clearance, health or inventory invariant.
Only the caller may report an independently observed settled arrival.
"""
import copy
import math
import re

from navigation4_controller.geometry import (
    box_values, observation_geometry, required, clear_body, support, translated,
)
from navigation4_controller.legacy import Refused
from grounded_contact import current_support, partial, inward_project
from navigation4_controller.plan import validate as validate_navigation_plan

DIRECTIONS = {'west': (-1, 0), 'north': (0, -1),
              'south': (0, 1), 'east': (1, 0)}
_ID = re.compile(r'[A-Za-z0-9._:-]{1,64}')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sid(value):
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise Refused('bounded stage ID required')
    return value


def _node(pose):
    return (math.floor(pose['x']), math.floor(pose['y'] + 1e-5),
            math.floor(pose['z']))


def _edge(a, b):
    return frozenset((a, b))


def _context(obs):
    return {k: obs.get('bound_owner_id' if k == 'owner_id' else k)
            for k in ('session', 'world_generation', 'player_uuid', 'owner_id')}


def _validate_stage(stage, context):
    validate_navigation_plan(dict(version=2, kind='navigation',
                                  context=context, stages=[stage]))


def _current(obs):
    if not isinstance(obs, dict):
        raise Refused('actual observation required')
    p, velocity = obs.get('pose'), obs.get('velocity')
    if (not isinstance(p, dict) or set(p) != {'x', 'y', 'z', 'yaw', 'pitch'} or
            any(not _finite(p[k]) for k in p) or
            not -180 <= p['yaw'] < 180 or not -90 <= p['pitch'] <= 90 or
            not isinstance(velocity, dict) or set(velocity) != set('xyz') or
            any(not _finite(velocity[k]) for k in 'xyz')):
        raise Refused('actual finite pose and velocity required')
    if (obs.get('ready') is not True or
            obs.get('collision_boxes_complete') is not True or
            obs.get('sprinting') is not False or obs.get('on_ground') is not True or
            math.hypot(velocity['x'], velocity['z']) > .03 or
            abs(velocity['y']) > .1):
        raise Refused('grounded slow complete current geometry required')
    bbox = box_values(obs.get('player_bbox'))
    if (abs(bbox[1] - p['y']) > 1e-5 or
            abs((bbox[0] + bbox[3]) / 2 - p['x']) > 1e-5 or
            abs((bbox[2] + bbox[5]) / 2 - p['z']) > 1e-5 or
            any(bbox[i + 3] - bbox[i] > 4 for i in range(3))):
        raise Refused('actual bbox/pose or bounded source height mismatch')
    cells, boxes = observation_geometry(obs)
    required(cells, [bbox[0], bbox[1] - 1, bbox[2], bbox[3], bbox[4], bbox[5]])
    clear_body(bbox, boxes)
    current_support(bbox, boxes)
    return p, bbox, cells, boxes


def _project(pose, bbox, cells, boxes, target, jump, step_height):
    """Use exactly C8's landing/body and <= .25m projected support predicates.

    The production predicate does not clear a linearly interpolated full body
    for an ascent (that would falsely reject a normal step), nor simulate an
    ideal jump arc. A supported one-block drop is not an unsupported gap.
    """
    if partial(bbox,boxes):
        if jump:raise Refused('edge recovery requires short same-height inward step')
        return inward_project(pose,bbox,cells,boxes,target)
    dy = target['y'] - pose['y']
    distance = math.hypot(target['x'] - pose['x'], target['z'] - pose['z'])
    if abs(dy) > 1 or not .01 < distance <= 3:
        raise Refused('local target displacement/drop bound exceeded')
    if not jump and dy > min(step_height, .6) + 1e-6:
        raise Refused('target above actual native step height')
    landing = translated(bbox, pose, target)
    required(cells, [landing[0], landing[1] - 1, landing[2],
                     landing[3], landing[4], landing[5]])
    clear_body(landing, boxes)
    support(landing, boxes, landing[1], landing[1])
    count = math.ceil(distance / .25)
    for i in range(1, count + 1):
        f = i / count
        mid = {k: pose[k] + f * (target[k] - pose[k]) for k in 'xyz'}
        foot = translated(bbox, pose, mid)
        required(cells, [foot[0], min(pose['y'], target['y']) - 1,
                         foot[2], foot[3], max(pose['y'], target['y']) + .01,
                         foot[5]])
        support(foot, boxes, min(pose['y'], target['y']) - 1,
                max(pose['y'], target['y']))
    return landing


def _build(obs, sid, target, jump, max_moves, current):
    p, bbox, cells, boxes = current
    if (not isinstance(target, dict) or set(target) != set('xyz') or
            any(not _finite(target[k]) for k in 'xyz')):
        raise Refused('closed finite xyz target required')
    if type(jump) is not bool or type(max_moves) is not int or not 1 <= max_moves <= 8:
        raise Refused('explicit jump and bounded move budget required')
    dx, dz = target['x'] - p['x'], target['z'] - p['z']
    if (abs(dx) > 1e-7) == (abs(dz) > 1e-7):
        raise Refused('one-axis cardinal target required')
    landing = _project(p, bbox, cells, boxes, target, jump, obs['step_height'])
    distance = math.hypot(dx, dz)
    edge = partial(bbox,boxes)
    magnitude = 1. if not edge and not jump and abs(target['y']-p['y'])<1e-7 else .5
    wx, wz = magnitude * dx / distance, magnitude * dz / distance
    yaw = math.radians(p['yaw'])
    bounds = {}
    for i, k in enumerate('xyz'):
        bounds['min_' + k] = min(bbox[i], landing[i])
        bounds['max_' + k] = max(bbox[i + 3], landing[i + 3])
    # The production Y corridor is a feet range, NOT a full-body envelope.
    bounds['min_y'] = min(p['y'], target['y']) - .05
    bounds['max_y'] = max(p['y'], target['y']) + .05
    stage = dict(id=_sid(sid), source_bounds=bounds, target=copy.deepcopy(target),
                 yaw=p['yaw'], pitch=p['pitch'],
                 forward=-wx * math.sin(yaw) + wz * math.cos(yaw),
                 strafe=wx * math.cos(yaw) + wz * math.sin(yaw),
                 jump_first=jump, max_samples=4 if edge else (8 if jump or abs(target['y']-p['y'])<1e-7 else 4),
                 max_moves=1 if jump else max_moves, max_looks=0)
    _validate_stage(stage, _context(obs))
    return stage


def manual_target(obs, sid, target, jump=False, max_moves=8):
    """Return a pure, exact C8 stage for a closed finite local cardinal target.

    A jump always has one move and eight samples, even if max_moves defaults to
    eight. No action, settlement, arrival, authorization or retry is implied.
    """
    _sid(sid)
    return _build(obs, sid, target, jump, max_moves, _current(obs))


def _high_boundary(p, bbox, cells, boxes, target):
    """Recognize observed supported surfaces outside ±1, without walking there."""
    for height in sorted({b[4] for b, _ in boxes}):
        if abs(height - p['y']) <= 1 + 1e-7:
            continue
        candidate = dict(target, y=height)
        landing = translated(bbox, p, candidate)
        try:
            required(cells, [landing[0], landing[1] - 1, landing[2],
                             landing[3], landing[4], landing[5]])
            clear_body(landing, boxes)
            support(landing, boxes, height, height)
        except Refused:
            continue
        return dict(target=candidate, height_delta=height - p['y'])
    return None


class TerrainPlanner:
    """Finite observed-cell DFS, with actual-arrival-only tree advancement.

    Encountering an observed >1-height frontier with no new traversable cell is
    a checkpoint, not a command to walk all the way back to the starting point.
    Blocked/partial motion never fabricates a confirmed edge or target arrival.
    """
    def __init__(self, preferred='west', stop_x=-635):
        if preferred not in DIRECTIONS or not _finite(stop_x):
            raise ValueError('cardinal preference and finite stop_x required')
        self.preferred, self.stop_x = preferred, float(stop_x)
        self.visited, self.observed_sources, self.blocked_edges = set(), set(), set()
        self.arrivals, self.boundaries = [], []
        self.reason = None
        self._seen, self._stack, self._used_ids = set(), [], set()
        self._pending = self._pending_info = self._pending_context = None

    def choose(self, obs, sid):
        if self._pending is not None:
            return copy.deepcopy(self._pending)
        _sid(sid)
        if sid in self._used_ids:
            raise Refused('stage ID must not be reused')
        current = _current(obs)
        p, bbox, cells, boxes = current
        reached = p['x'] >= self.stop_x if self.preferred == 'east' else p['x'] <= self.stop_x
        if reached:
            self.reason = 'goal_reached'
            return None
        source = _node(p)
        if not self._seen:
            self.visited.add(source)
        self.observed_sources.add(source)
        self._seen.add(source)
        if not self._stack or self._stack[-1] != source:
            self._stack = [source]
        candidates, self.boundaries = {}, []
        order = [self.preferred] + [d for d in DIRECTIONS if d != self.preferred]
        for direction in order:
            dx, dz = DIRECTIONS[direction]
            target = dict(x=source[0] + dx + .5 if dx else p['x'],
                          y=p['y'], z=source[2] + dz + .5 if dz else p['z'])
            direction_valid = False
            for dy in (0, 1, -1):
                candidate = dict(target, y=p['y'] + dy)
                dest = _node(candidate)
                if _edge(source, dest) in self.blocked_edges:
                    continue
                try:
                    stage = _build(obs, sid, candidate, dy > 0, 8, current)
                except Refused:
                    continue
                candidates[dest] = stage
                direction_valid = True
            if not direction_valid:
                boundary = _high_boundary(p, bbox, cells, boxes, target)
                if boundary is not None:
                    self.boundaries.append(dict(direction=direction, **boundary))
        dest = next((n for n in candidates if n not in self._seen), None)
        mode = 'explore'
        if dest is None and self.boundaries:
            self.reason = 'high_difference_boundary_checkpoint'
            return None
        if dest is None and len(self._stack)>1:
            parent=self._stack[-2]
            if parent not in candidates and abs(parent[0]-source[0])+abs(parent[2]-source[2])==2 and parent[1]==source[1]:
                target=dict(x=parent[0]+.5 if parent[0]!=source[0] else p['x'],
                            y=p['y'],z=parent[2]+.5 if parent[2]!=source[2] else p['z'])
                try:
                    from local_corridor import _project as ordinary_project
                    ordinary_project(p,bbox,cells,boxes,target)
                    candidates[parent]=_build(obs,sid,target,False,8,current)
                except Refused:
                    pass
            if parent in candidates:dest,mode=parent,'backtrack'
        if dest is None:
            self.reason = 'explored_graph_exhausted' if len(self._seen) > 1 else 'no_observed_corridor'
            return None
        stage = candidates[dest]
        # Extend only an already valid new flat direction through fully observed
        # ordinary body clearance/support. One-cell fallback stays available.
        if mode == 'explore' and not stage['jump_first'] and abs(stage['target']['y']-p['y'])<1e-7:
            dx,dz=dest[0]-source[0],dest[2]-source[2]
            target=dict(x=source[0]+2*dx+.5 if dx else p['x'],y=p['y'],
                        z=source[2]+2*dz+.5 if dz else p['z'])
            farther=_node(target)
            if (math.hypot(target['x']-p['x'],target['z']-p['z'])<=2
                    and farther not in self._seen and _edge(source,farther) not in self.blocked_edges
                    and _edge(dest,farther) not in self.blocked_edges):
                try:
                    from local_corridor import _project as ordinary_project
                    ordinary_project(p,bbox,cells,boxes,target)
                    stage=_build(obs,sid,target,False,8,current)
                    dest=farther
                except Refused:
                    pass
        self._pending = copy.deepcopy(stage)
        self._pending_info = dict(source=source, dest=dest, mode=mode)
        self._pending_context = _context(obs)
        self._used_ids.add(sid)
        self.reason = 'stage_proposed'
        return stage

    def _original(self, stage):
        if self._pending is None or stage != self._pending:
            raise Refused('exact outstanding original stage required')
        return self._pending_info

    def arrived(self, stage):
        """Caller attests actual settled arrival; action completion is not enough."""
        info = self._original(stage)
        self.visited.add(info['dest'])
        self._seen.add(info['dest'])
        self.arrivals.append(dict(stage_id=stage['id'], target=copy.deepcopy(stage['target'])))
        if info['mode'] == 'backtrack':
            self._stack.pop()
        else:
            self._stack.append(info['dest'])
        self._pending = self._pending_info = self._pending_context = None
        self.reason = 'actual_arrival_recorded'

    def blocked(self, stage):
        info = self._original(stage)
        self.blocked_edges.add(_edge(info['source'], info['dest']))
        self._pending = self._pending_info = self._pending_context = None
        self.reason = 'original_edge_blocked'

    def snapshot(self):
        """JSON data only; no file writes and no automatic game-session resume."""
        info = None if self._pending_info is None else {
            **self._pending_info, 'source': list(self._pending_info['source']),
            'dest': list(self._pending_info['dest'])}
        return copy.deepcopy(dict(
            version=1, preferred=self.preferred, stop_x=self.stop_x,
            visited=[list(n) for n in sorted(self.visited)],
            observed_sources=[list(n) for n in sorted(self.observed_sources)],
            blocked_edges=[[list(n) for n in sorted(e)] for e in sorted(
                self.blocked_edges, key=lambda e: sorted(e))],
            arrivals=self.arrivals, boundaries=self.boundaries, reason=self.reason,
            seen=[list(n) for n in sorted(self._seen)],
            stack=[list(n) for n in self._stack], used_ids=sorted(self._used_ids),
            pending=self._pending, pending_info=info,
            pending_context=self._pending_context))

    @classmethod
    def restore(cls, state):
        """Validate a snapshot without inferring authority, arrival or settlement."""
        keys = {'version', 'preferred', 'stop_x', 'visited', 'observed_sources',
                'blocked_edges', 'arrivals', 'boundaries', 'reason', 'seen',
                'stack', 'used_ids', 'pending', 'pending_info', 'pending_context'}
        if not isinstance(state, dict) or set(state) != keys or type(state['version']) is not int or state['version'] != 1:
            raise Refused('closed terrain snapshot version1 required')
        try:
            out = cls(state['preferred'], state['stop_x'])
        except (ValueError, TypeError):
            raise Refused('invalid terrain snapshot preference/goal') from None

        def node(raw):
            if not isinstance(raw, list) or len(raw) != 3 or any(type(v) is not int or abs(v) > 30000000 for v in raw):
                raise Refused('bounded integer terrain node required')
            return tuple(raw)

        def nodes(raw):
            if not isinstance(raw, list):
                raise Refused('terrain node list required')
            result = [node(n) for n in raw]
            if len(set(result)) != len(result):
                raise Refused('duplicate terrain node')
            return result

        out.visited = set(nodes(state['visited']))
        out.observed_sources = set(nodes(state['observed_sources']))
        out._seen = set(nodes(state['seen']))
        out._stack = nodes(state['stack'])
        if not (out.visited | out.observed_sources | set(out._stack)) <= out._seen:
            raise Refused('inconsistent terrain snapshot seen nodes')
        if not isinstance(state['blocked_edges'], list):
            raise Refused('terrain blocked edge list required')
        for raw in state['blocked_edges']:
            if not isinstance(raw, list) or len(raw) != 2:
                raise Refused('two-node blocked edge required')
            a, b = nodes(raw)
            distance=abs(a[0]-b[0])+abs(a[2]-b[2])
            if (distance not in (1,2) or (a[0]!=b[0] and a[2]!=b[2])
                    or abs(a[1]-b[1])>1 or distance==2 and a[1]!=b[1]):
                raise Refused('local cardinal blocked edge required')
            out.blocked_edges.add(_edge(a, b))
        if not isinstance(state['used_ids'], list):
            raise Refused('used stage ID list required')
        out._used_ids = {_sid(v) for v in state['used_ids']}
        if len(out._used_ids) != len(state['used_ids']):
            raise Refused('duplicate used stage ID')
        if state['reason'] is not None and not isinstance(state['reason'], str):
            raise Refused('terrain reason must be text or null')
        out.reason = state['reason']
        if not isinstance(state['arrivals'], list) or not isinstance(state['boundaries'], list):
            raise Refused('terrain evidence lists required')
        for arrival in state['arrivals']:
            if (not isinstance(arrival, dict) or set(arrival) != {'stage_id', 'target'} or
                    _sid(arrival['stage_id']) not in out._used_ids or
                    not isinstance(arrival['target'], dict) or set(arrival['target']) != set('xyz') or
                    any(not _finite(v) for v in arrival['target'].values()) or
                    _node(arrival['target']) not in out.visited):
                raise Refused('inconsistent actual arrival record')
        for boundary in state['boundaries']:
            if (not isinstance(boundary, dict) or set(boundary) != {'direction', 'target', 'height_delta'} or
                    boundary['direction'] not in DIRECTIONS or not _finite(boundary['height_delta']) or
                    not isinstance(boundary['target'], dict) or set(boundary['target']) != set('xyz') or
                    any(not _finite(v) for v in boundary['target'].values())):
                raise Refused('invalid terrain boundary evidence')
        out.arrivals, out.boundaries = copy.deepcopy(state['arrivals']), copy.deepcopy(state['boundaries'])
        if state['pending'] is None:
            if state['pending_info'] is not None or state['pending_context'] is not None:
                raise Refused('pending terrain state mismatch')
        else:
            stage, info = state['pending'], state['pending_info']
            _validate_stage(stage, state['pending_context'])
            if (not isinstance(info, dict) or set(info) != {'source', 'dest', 'mode'} or
                    info['mode'] not in ('explore', 'backtrack')):
                raise Refused('pending terrain edge required')
            source, dest = node(info['source']), node(info['dest'])
            if (stage['id'] not in out._used_ids or not out._stack or
                    source != out._stack[-1] or dest != _node(stage['target']) or
                    abs(source[0]-dest[0])+abs(source[2]-dest[2]) not in (1,2) or
                    (source[0]!=dest[0] and source[2]!=dest[2]) or
                    (abs(source[0]-dest[0])+abs(source[2]-dest[2])==2 and source[1]!=dest[1]) or
                    abs(source[1] - dest[1]) > 1 or
                    (info['mode'] == 'backtrack' and (len(out._stack) < 2 or dest != out._stack[-2]))):
                raise Refused('inconsistent pending terrain stage')
            out._pending = copy.deepcopy(stage)
            out._pending_info = dict(source=source, dest=dest, mode=info['mode'])
            out._pending_context = copy.deepcopy(state['pending_context'])
        return out
