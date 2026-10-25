"""Read-only local ordinary-corridor planning from one actual V6 observation.

No transport, world files, ledger, persistence, look, jump, or digging.  A stage
is only a proposal: the unchanged production admission gate remains mandatory
for every fresh move.  ``arrived`` is called ONLY after actual settled arrival
has been independently established; issuing or completing an action is not an
arrival.  ``blocked`` abandons that exact stage, never marking its target visited.

One-cell steps deliberately do not skip observed perpendicular junctions.
Targets are cell centers on the moving axis, preserving the actual other axis
and foot height; this makes the input truly cardinal even after small residuals.
"""
import copy
import math
import re

from navigation4_controller.geometry import (
    box_values, observation_geometry, required, clear_body, support, translated,
)
from navigation4_controller.legacy import Refused
from grounded_contact import current_support, partial, inward_project


DIRECTIONS = {'west': (-1, 0), 'north': (0, -1),
              'south': (0, 1), 'east': (1, 0)}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _node(pose):
    return (math.floor(pose['x']), math.floor(pose['z']))


def _edge(a, b):
    return frozenset((a, b))


def _current(obs):
    """Require actual body, support and stable ordinary movement geometry."""
    p, velocity = obs.get('pose'), obs.get('velocity')
    if (not isinstance(p, dict) or
            any(not _finite(p.get(k)) for k in ('x', 'y', 'z', 'yaw', 'pitch')) or
            not -180 <= p['yaw'] < 180 or not -90 <= p['pitch'] <= 90 or
            not isinstance(velocity, dict) or
            any(not _finite(velocity.get(k)) for k in 'xyz')):
        raise Refused('actual finite pose and velocity required')
    if (obs.get('ready') is not True or
            obs.get('collision_boxes_complete') is not True or
            obs.get('sprinting') is not False or obs.get('on_ground') is not True or
            math.hypot(velocity['x'], velocity['z']) > .03 or abs(velocity['y']) > .1):
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


def _project(pose, bbox, cells, boxes, target):
    """Validate the FULL body and footprint at every <= .25 m projection."""
    if partial(bbox,boxes):return inward_project(pose,bbox,cells,boxes,target)
    distance = math.hypot(target['x'] - pose['x'], target['z'] - pose['z'])
    if not .01 < distance <= 2 or target['y'] != pose['y']:
        raise Refused('ordinary same-height local target required')
    count = math.ceil(distance / .25)
    for i in range(1, count + 1):
        mid = {k: pose[k] + i / count * (target[k] - pose[k]) for k in 'xyz'}
        body = translated(bbox, pose, mid)
        required(cells, [body[0], body[1] - 1, body[2], body[3], body[4], body[5]])
        clear_body(body, boxes)
        # Ordinary same-height walking requires support AT the feet, not a
        # lower surface that merely falls within the old bounded drop window.
        support(body, boxes, body[1], body[1])
    return translated(bbox, pose, target)


class LocalCorridor:
    """Finite-graph depth-first exploration with confirmed-edge backtracking.

    ``visited`` contains initial occupancy and explicitly confirmed arrivals.
    ``observed_sources`` separately records actual sources after abandonment;
    these are not fabricated target arrivals.  Each cell is explored once and
    each tree edge is backtracked at most once, so a finite observed component
    cannot create an infinite same-block loop.  Partial blocked motion can
    disconnect the confirmed tree: restart from that actual source, never
    inventing a traversable edge to the previous location.
    """

    def __init__(self, preferred='west', stop_x=-635.0):
        if preferred not in DIRECTIONS or not _finite(stop_x):
            raise ValueError('cardinal preference and finite stop_x required')
        self.preferred, self.stop_x = preferred, float(stop_x)
        self.visited = set()
        self.observed_sources = set()
        self.blocked_edges = set()
        self.arrivals = []
        self.reason = None
        self._seen, self._stack, self._used_ids = set(), [], set()
        self._pending = None
        self._pending_info = None

    def choose(self, obs, stage_id):
        # In-progress plans are immutable; a new observation is not permission
        # to silently replace the target or reset its production action budget.
        if self._pending is not None:
            return copy.deepcopy(self._pending)
        if not isinstance(stage_id, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,64}', stage_id):
            raise Refused('bounded stage ID required')
        if stage_id in self._used_ids:
            raise Refused('stage ID must not be reused')
        p, bbox, cells, boxes = _current(obs)
        reached = p['x'] >= self.stop_x if self.preferred == 'east' else p['x'] <= self.stop_x
        if reached:
            self.reason = 'goal_reached'
            return None
        source = _node(p)
        if not self._seen:
            self.visited.add(source)  # Actual initial occupancy, not an action.
        self.observed_sources.add(source)
        self._seen.add(source)
        if not self._stack or self._stack[-1] != source:
            # A blocked stage may have partially moved across a cell boundary.
            # Its target has NOT thereby been declared arrived.
            self._stack = [source]

        candidates = {}
        order = [self.preferred] + [d for d in DIRECTIONS if d != self.preferred]
        for direction in order:
            dx, dz = DIRECTIONS[direction]
            dest = (source[0] + dx, source[1] + dz)
            if _edge(source, dest) in self.blocked_edges:
                continue
            target = {'x': dest[0] + .5 if dx else p['x'], 'y': p['y'],
                      'z': dest[1] + .5 if dz else p['z']}
            try:
                landing = _project(p, bbox, cells, boxes, target)
            except Refused:
                continue
            candidates[dest] = (direction, target, landing)

        dest = next((n for n in candidates if n not in self._seen), None)
        mode = 'explore'
        if dest is None and len(self._stack) > 1:
            parent = self._stack[-2]
            if parent in candidates:
                dest, mode = parent, 'backtrack'
        if dest is None:
            self.reason = 'explored_graph_exhausted' if len(self._seen) > 1 else 'no_observed_corridor'
            return None

        direction, target, landing = candidates[dest]
        dx, dz = DIRECTIONS[direction]
        yaw = math.radians(p['yaw'])
        # Inverse of production gate's camera-relative input rotation.
        forward = .5 * (-dx * math.sin(yaw) + dz * math.cos(yaw))
        strafe = .5 * (dx * math.cos(yaw) + dz * math.sin(yaw))
        bounds = {}
        for i, k in enumerate('xyz'):
            bounds['min_' + k] = min(bbox[i], landing[i])
            bounds['max_' + k] = max(bbox[i + 3], landing[i + 3])
        # Production source_bounds Y is a feet-height range, unlike X/Z's
        # whole-footprint envelope.  Body height was verified above throughout.
        bounds['min_y'], bounds['max_y'] = p['y'] - .05, p['y'] + .05
        stage = dict(id=stage_id, source_bounds=bounds, target=target,
                     yaw=p['yaw'], pitch=p['pitch'], forward=forward, strafe=strafe,
                     jump_first=False, max_samples=4, max_moves=8, max_looks=0)
        self._pending = copy.deepcopy(stage)
        self._pending_info = (source, dest, mode)
        self._used_ids.add(stage_id)
        self.reason = 'stage_proposed'
        return stage

    def _original(self, stage):
        if self._pending is None or stage != self._pending:
            raise Refused('exact outstanding original stage required')
        return self._pending_info

    def arrived(self, stage):
        """Record caller-confirmed settled arrival, not mere action completion."""
        source, dest, mode = self._original(stage)
        self.visited.add(dest)
        self._seen.add(dest)
        self.arrivals.append({'stage_id': stage['id'], 'target': copy.deepcopy(stage['target'])})
        if mode == 'backtrack':
            self._stack.pop()
        else:
            self._stack.append(dest)
        self._pending = self._pending_info = None
        self.reason = 'actual_arrival_recorded'

    def blocked(self, stage):
        """Abandon an exhausted/colliding original edge without fake arrival."""
        source, dest, _ = self._original(stage)
        self.blocked_edges.add(_edge(source, dest))
        self._pending = self._pending_info = None
        self.reason = 'original_edge_blocked'
