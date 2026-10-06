"""Persistent local routes for the existing watchdog IntentClient.

No imports, discovery, or writes to the resident queue. One tick submits at most
one short owner intent. Importing this module does not touch the game.
"""
from __future__ import annotations
import heapq
from dataclasses import dataclass
import json
import math
import os
import time
from pathlib import Path
import uuid

TERMINAL = {'succeeded', 'failed', 'cancelled', 'uncertain'}


def block(player):
    return tuple(math.floor(player[k]) for k in ('x', 'y', 'z'))


def reached(player, node):
    return (player.get('on_ground') is True
            and math.hypot(player['x'] - node[0] - .5, player['z'] - node[2] - .5) <= .35
            and abs(player['y'] - node[1]) <= .25)


def at_goal(player, target):
    if len(target) == 2:
        return (player.get('on_ground') is True
                and math.hypot(player['x'] - target[0] - .5, player['z'] - target[1] - .5) <= .35)
    return reached(player, target)


def distance(a, b):
    if len(b) == 2:
        return abs(a[0] - b[0]) + abs(a[2] - b[1])
    return abs(a[0] - b[0]) + abs(a[2] - b[2]) + 1.5 * abs(a[1] - b[1])


SAFE_FOOD = frozenset('minecraft:' + name for name in (
    'bread', 'baked_potato', 'cooked_beef', 'cooked_porkchop', 'cooked_chicken',
    'cooked_mutton', 'cooked_rabbit', 'cooked_cod', 'cooked_salmon', 'carrot',
    'apple', 'golden_carrot', 'golden_apple', 'enchanted_golden_apple',
    'melon_slice', 'sweet_berries', 'glow_berries', 'dried_kelp', 'beetroot',
    'beetroot_soup', 'mushroom_stew', 'rabbit_stew', 'pumpkin_pie', 'cookie'))


@dataclass(frozen=True)
class DropPolicy:
    """Small ordinary falls only. Estimates do not assume healing mid-fall."""
    max_blocks: int = 5
    health_reserve: float = 2.0

    def __post_init__(self):
        if type(self.max_blocks) is not int or not 1 <= self.max_blocks <= 5:
            raise ValueError('controlled_drop_limit_must_be_1_to_5')
        if not 0 < self.health_reserve <= 20:
            raise ValueError('invalid_drop_health_reserve')

    def allows(self, height, player):
        if not 1 <= height <= self.max_blocks:
            return False
        # Vanilla ordinary standing falls: ceil(distance - 3). One extra health
        # point is reserved for damage rounding/entry uncertainty on harmful falls.
        damage = max(0, math.ceil(height - 3))
        if not damage:
            return True
        return player.get('health', 0) - damage - 1 >= self.health_reserve

    def cost(self, height, player):
        """Food changes recovery cost, not whether a survivable fall exists."""
        damage = max(0, math.ceil(height - 3))
        supplies = any(i.get('id') in SAFE_FOOD and i.get('count', 0) > 0
                       for i in player.get('inventory', []))
        recovery = (1 if player.get('food', 0) >= 18 and player.get('saturation', 0) > 0
                    else 1.5 if supplies else 2.5)
        remaining = max(1, player.get('health', 0) - damage)
        return 1 + damage * .2 * recovery * (1 + 2 / remaining)



class LocalTerrain:
    """Graph from actual loaded collision facts, including full-support leaves."""
    def __init__(self, observation, drop_policy=None):
        self.player = observation.get('state', {}).get('player', {})
        self.drop_policy = drop_policy or DropPolicy()
        terrain = observation.get('terrain', {})
        if terrain.get('complete') is not True:
            raise ValueError('complete_terrain_observation_required')
        self.cells = {(c['x'], c['y'], c['z']): c for c in terrain['cells']}

    def certain(self, point):
        c = self.cells.get(point, {})
        return (c.get('status') == 'loaded' and c.get('known') is True
                and c.get('collision_known') is True
                and c.get('id_truncated') is False and c.get('fluid_truncated') is False
                and c.get('properties_truncated') is False
                and c.get('fluid') == 'minecraft:empty' and c.get('hazards') == [])

    def clear(self, point):
        return self.certain(point) and self.cells[point].get('collision_empty') is True

    def stand(self, point):
        x, y, z = point
        floor = (x, y - 1, z)
        return (self.clear(point) and self.clear((x, y + 1, z))
                and self.certain(floor) and self.cells[floor].get('full_top_support') is True)


    def ground_anchor(self, player):
        """Normalize a grounded edge stance to known, overlapping full support.

        Bounding boxes, if observed, are authoritative. The current bridge omits
        the player's box, so its ordinary standing/crouching 0.6-block width is
        used only when the observed eye height identifies that vanilla pose.
        No collision-bounds union is treated as a guaranteed support surface.
        """
        if player.get('on_ground') is not True:
            return None
        px, py, pz = (float(player[k]) for k in ('x', 'y', 'z'))
        if not all(math.isfinite(v) for v in (px, py, pz)):
            return None
        box = player.get('bounding_box')
        if box is not None:
            try:
                lo, hi = box['min'], box['max']
                xmin, zmin, xmax, zmax = lo['x'], lo['z'], hi['x'], hi['z']
                height = hi['y'] - lo['y']
                body_min_y, body_max_y = lo['y'], hi['y']
                values = (xmin, zmin, xmax, zmax, height, lo['y'])
                if (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
                        or not xmin < px < xmax or not zmin < pz < zmax
                        or abs(lo['y'] - py) > .04 or not 0 < height <= 3):
                    return None
            except (KeyError, TypeError):
                return None
        else:
            eye = player.get('eye_position', {})
            if not isinstance(eye, dict):
                return None
            ey = eye.get('y')
            if type(ey) not in (int, float) or not math.isfinite(ey):
                return None
            eye_height = ey - py
            if abs(eye_height - 1.62) < .06:
                height = 1.8
            elif abs(eye_height - 1.27) < .06:
                height = 1.5
            else:
                return None  # Swimming, riding, scaled/unknown pose: no guess.
            xmin, xmax, zmin, zmax = px - .3, px + .3, pz - .3, pz + .3
            body_min_y, body_max_y = py, py + height
        # Existing graph nodes are full-block feet heights. A lower neighbor or
        # a partial slab/fence is not invented as a same-height anchor.
        y = round(py)
        if abs(py - y) > .04:
            return None
        candidates = []
        for x in range(math.floor(xmin), math.ceil(xmax)):
            for z in range(math.floor(zmin), math.ceil(zmax)):
                overlap = min(xmax, x + 1) - max(xmin, x)
                overlap *= max(0, min(zmax, z + 1) - max(zmin, z))
                if overlap <= 1e-9 or not self.stand((x, y, z)):
                    continue
                bounds = self.cells[(x, y - 1, z)].get('collision_bounds')
                if (not isinstance(bounds, list) or len(bounds) != 6
                        or not all(type(v) in (int, float) and math.isfinite(v) for v in bounds)
                        or abs(bounds[4] - 1) > 1e-6):
                    continue  # Full top alone does not place a partial shape at y.
                cx, cz = x + .5, z + .5
                # Entire player volume swept into the anchor center must be
                # observed clear. Unknown beside the ledge is not assumed air.
                sxmin, sxmax = min(xmin, cx + xmin - px), max(xmax, cx + xmax - px)
                szmin, szmax = min(zmin, cz + zmin - pz), max(zmax, cz + zmax - pz)
                clear = all(self.clear((bx, by, bz))
                            for bx in range(math.floor(sxmin + 1e-9), math.ceil(sxmax - 1e-9))
                            for bz in range(math.floor(szmin + 1e-9), math.ceil(szmax - 1e-9))
                            for by in range(math.floor(min(body_min_y, y) + 1e-9),
                                            math.ceil(max(body_max_y, y + height) - 1e-9)))
                if clear:
                    candidates.append((math.hypot(cx - px, cz - pz), -overlap, (x, y, z)))
        return min(candidates)[2] if candidates else None

    def edge(self, a, b):
        dx, dy, dz = (b[i] - a[i] for i in range(3))
        if abs(dx) + abs(dz) != 1 or dy > 1 or dy < -self.drop_policy.max_blocks:
            return False
        if not self.stand(a) or not self.stand(b):
            return False
        if dy > 0:
            return self.clear((a[0], a[1] + 2, a[2])) and self.clear((b[0], a[1] + 2, b[2]))
        if dy == 0:
            return True
        # Every loaded cell from the original head height through the landing
        # feet must be clear. The destination's full support was checked above.
        return (self.drop_policy.allows(-dy, self.player)
                and all(self.clear((b[0], y, b[2])) for y in range(b[1], a[1] + 2)))

    def graph(self, start, forbidden):
        previous, costs, todo = {start: None}, {start: 0.0}, [(0.0, start)]
        while todo:
            cost, a = heapq.heappop(todo)
            if cost != costs[a]:
                continue
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                for dy in (0, 1, *range(-1, -self.drop_policy.max_blocks - 1, -1)):
                    b = (a[0] + dx, a[1] + dy, a[2] + dz)
                    if (a, b) in forbidden or not self.edge(a, b):
                        continue
                    weight = self.drop_policy.cost(-dy, self.player) if dy < 0 else 1.25 if dy > 0 else 1.0
                    candidate = cost + weight
                    if candidate < costs.get(b, float('inf')):
                        costs[b], previous[b] = candidate, a
                        heapq.heappush(todo, (candidate, b))
        return previous



@dataclass
class RouteCursor:
    """The cursor advances on arrival, never on slicing or dispatch."""
    nodes: list
    index: int = 1

    def __post_init__(self):
        self.nodes = [tuple(n) for n in self.nodes]
        if not self.nodes or not 1 <= self.index <= len(self.nodes):
            raise ValueError('invalid_route_cursor')

    @property
    def done(self):
        return self.index == len(self.nodes)

    def reconcile(self, player):
        # Later observed arrivals are allowed after action completion or combat.
        # Never rewind to the nearest prefix and never skip by distance-to-goal.
        for i in range(len(self.nodes) - 1, self.index - 1, -1):
            if reached(player, self.nodes[i]):
                self.index = i + 1
                break

    def slice(self, size=2):
        if type(size) is not int or not 1 <= size <= 32:
            raise ValueError('slice_size_must_be_1_to_32')
        end = min(len(self.nodes), self.index + size)
        # Finish a drop as its own boundary. Grounding/health is observed before
        # sending a subsequent waypoint, even if the mod finished just above it.
        for i in range(self.index, end):
            if self.nodes[i][1] < self.nodes[i - 1][1] - 1:
                end = i + 1
                break
        return [{'x': b[0] + .5, 'y': b[1], 'z': b[2] + .5,
                 'jump': b[1] > self.nodes[i - 1][1]}
                for i, b in enumerate(self.nodes[self.index:end], self.index)]

    def observed_slice(self, terrain, start, limit=32):
        """Longest currently verified prefix, retaining the unobserved tail.

        An ordinary one-block step is continuous. Larger drops end the slice
        at the landing so a fresh grounded/health observation gates the tail.
        A changed or unknown later edge ends this slice, not the saved route.
        """
        candidates = self.slice(limit)
        a, size = start, 0
        for b in self.nodes[self.index:self.index + len(candidates)]:
            if b != a and not terrain.edge(a, b):
                break
            size += 1
            a = b
        return candidates[:size]

    def dump(self):
        return {'nodes': self.nodes, 'index': self.index}


class Navigator:
    """Small restart-safe route owner; the watchdog remains the only queue writer.

    tick(target) returns progress, pending, waiting, complete or blocked. Call it
    again with the SAME target to continue. Checkpoints contain route/RPC IDs only.
    A caller stops calling tick to pause; any submitted slice remains owned by the
    watchdog. Never clear/recreate a checkpoint to retry a pending action.
    """
    def __init__(self, gateway, checkpoint=None, *, slice_size=None, radius=4,
                 vertical=4, max_replans=3, drop_policy=None):
        if (slice_size is not None and (type(slice_size) is not int or not 1 <= slice_size <= 32)
                or not 1 <= radius <= 8 or not 2 <= vertical <= 8):
            raise ValueError('invalid_navigation_bounds')
        self.gateway = gateway
        self.checkpoint = Path(checkpoint) if checkpoint else None
        self.slice_size, self.radius, self.vertical = slice_size, radius, vertical
        self.max_replans = max_replans
        self.drop_policy = drop_policy or DropPolicy()
        self.data = {'schema': 2, 'target': None, 'world': None, 'gateway_session': None,
                     'route': None, 'pending': None, 'last_action': None,
                     'forbidden': [], 'completed_legs': [], 'replans': 0, 'blocked': None,
                     'observation_epoch': None, 'force_replan': False,
                     'support_misses': 0, 'anchor_attempts': 0, 'anchor_relocalized': False,
                     'deferred_navigation_action': None}
        if self.checkpoint and self.checkpoint.exists():
            loaded = json.loads(self.checkpoint.read_text())
            if loaded.get('schema') != 2:
                raise ValueError('unsupported_navigation_checkpoint')
            self.data.update(loaded)

    @property
    def route(self):
        return RouteCursor(**self.data['route']) if self.data['route'] else None

    def save(self):
        if self.checkpoint:
            self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temp = self.checkpoint.with_name('.' + self.checkpoint.name + '.' + uuid.uuid4().hex)
            temp.write_text(json.dumps(self.data, allow_nan=False))
            os.chmod(temp, 0o600)
            os.replace(temp, self.checkpoint)

    def result(self, status, reason, **extra):
        self.save()
        route = self.route
        return {'status': status, 'reason': reason,
                'route_index': route.index if route else None,
                'route_nodes': len(route.nodes) if route else None, **extra}

    def stop(self, reason):
        self.data['blocked'] = reason
        return self.result('blocked', reason)

    def submit(self, kind, command, **metadata):
        # Persist BEFORE submitting. An exception after admission cannot create a
        # second action on restart. Resolve the original ID instead of replaying.
        if kind == 'action':
            current = self.gateway.session()
            if (current.get('session_id') != self.data['gateway_session']
                    or current.get('state') != 'ready'
                    or current.get('phase') not in (None, 'watching')):
                return self.result('waiting', 'watchdog_changed_before_action_reobserve')
            if current.get('defense_epoch') != self.data['observation_epoch']:
                self.data['force_replan'] = True
                return self.result('waiting', 'defense_epoch_changed_reobserve')
            command = {**command, '_navigation_defense_epoch': self.data['observation_epoch']}
        request_id = uuid.uuid4().hex
        self.data['pending'] = {'id': request_id, 'kind': kind, **metadata}
        self.save()
        try:
            actual = self.gateway.submit(command, request_id=request_id)
        except Exception:
            return self.stop('submission_uncertain_resolve_saved_request_id')
        if actual != request_id:
            return self.stop('gateway_request_id_mismatch')
        return self.result('pending', kind + '_submitted', request_id=request_id)

    def plan(self, observation, terrain, start):
        target = tuple(self.data['target'])
        forbidden = {(tuple(a), tuple(b)) for a, b in self.data['forbidden']}
        previous = terrain.graph(start, forbidden)
        old = self.route
        if old and old.nodes[-1] in previous:
            end = old.nodes[-1]  # Repair this leg, do not choose a new destination.
        elif target in previous:
            end = target
        else:
            visited = {tuple(n) for n in self.data['completed_legs']}
            candidates = [n for n in previous if n != start and n not in visited
                          and distance(n, target) < distance(start, target)]
            if not candidates:
                return self.stop('no_unvisited_local_progress_route')
            end = min(candidates, key=lambda n: (distance(n, target), distance(start, n), n))
        nodes = [end]
        while previous[nodes[-1]] is not None:
            nodes.append(previous[nodes[-1]])
        nodes.reverse()
        self.data['route'] = RouteCursor(nodes).dump()
        return None

    def process_observation(self, observation):
        state = observation.get('state', {})
        p, world = state.get('player', {}), state.get('world', {})
        if p.get('alive') is not True or p.get('health', 0) <= 0:
            return self.stop('player_not_alive')
        if state.get('paused') or state.get('screen_open'):
            return self.result('waiting', 'game_paused_or_screen_open')
        identity = [world.get('world_generation'), world.get('dimension')]
        if None in identity:
            return self.stop('world_identity_missing')
        if self.data['world'] is None:
            self.data['world'] = identity
        elif self.data['world'] != identity:
            return self.stop('world_changed_start_new_navigation_explicitly')
        if observation.get('combat', {}).get('active') is True:
            return self.result('waiting', 'combat_active_reobserve_before_resume')
        if observation.get('action', {}).get('status') == 'running':
            return self.result('waiting', 'another_action_running')
        if not p.get('on_ground'):
            return self.result('waiting', 'await_grounded_observation')
        target = tuple(self.data['target'])
        if at_goal(p, target):
            return self.result('complete', 'target_arrival_observed', position=block(p))
        if observation.get('terrain', {}).get('world_generation') != identity[0]:
            return self.stop('terrain_world_mismatch')
        terrain, start = LocalTerrain(observation, self.drop_policy), block(p)
        previous_action = self.data.get('last_action') or {}
        was_anchor = previous_action.get('purpose') == 'ground_anchor'
        if not terrain.stand(start):
            if was_anchor and previous_action.get('status') == 'cancelled':
                # Defense cancellation does not count as a failed centering try.
                self.data['anchor_attempts'] = max(0, self.data['anchor_attempts'] - 1)
                self.data['last_action'] = None
            anchor = terrain.ground_anchor(p)
            if anchor is None:
                self.data['support_misses'] += 1
                if self.data['support_misses'] >= 3:
                    return self.stop('grounded_support_unresolved_after_3_observations')
                return self.result('waiting', 'grounded_support_not_yet_resolved',
                                   support_observations=self.data['support_misses'])
            self.data['support_misses'] = 0
            if self.data['anchor_attempts'] >= 2:
                return self.stop('ground_anchor_no_progress_after_2_attempts')
            route = self.route
            if previous_action and not was_anchor:
                self.data['deferred_navigation_action'] = previous_action
            result = self.submit('action', {'op': 'action', 'action': 'follow_path',
                                          'waypoints': [{'x': anchor[0] + .5, 'y': anchor[1],
                                                         'z': anchor[2] + .5, 'jump': False}],
                                          'timeout_ms': 4000},
                                 purpose='ground_anchor', anchor=list(anchor),
                                 start_index=route.index if route else 0,
                                 end_index=route.index if route else 0)
            if result['status'] == 'pending':
                self.data['anchor_attempts'] += 1
                self.save()
            return result
        self.data['support_misses'] = 0
        self.data['anchor_attempts'] = 0
        if was_anchor:
            # Real support is now observed. Centering is not route failure and
            # must never blacklist the untouched next navigation edge.
            deferred = self.data.pop('deferred_navigation_action', None)
            self.data['deferred_navigation_action'] = None
            self.data['last_action'] = deferred
            self.data['anchor_relocalized'] = deferred is None
        route = self.route
        action = self.data.pop('last_action', None)
        self.data['last_action'] = None
        replan_reason = None
        relocated = self.data.pop('anchor_relocalized', False)
        self.data['anchor_relocalized'] = False
        forced = self.data.pop('force_replan', False)
        self.data['force_replan'] = False
        if route:
            old_index = route.index
            route.reconcile(p)
            self.data['route'] = route.dump()
            if route.done:
                end = route.nodes[-1]
                if list(end) in self.data['completed_legs']:
                    return self.stop('repeated_local_leg_without_global_progress')
                self.data['completed_legs'].append(list(end))
                self.data['route'] = None
                self.data['replans'] = 0
                route = None
            elif relocated:
                replan_reason = 'ground_anchor_relocalized'
            elif forced or (action and action['status'] == 'cancelled'):
                replan_reason = 'combat_preempted'
            elif action:
                if (action['status'] == 'failed' and route.index < action['end_index']) or route.index == old_index:
                    replan_reason = 'failed_edge' if action['status'] == 'failed' else 'no_observed_waypoint_progress'
            if route and not replan_reason:
                # Only validate the execution slice; observations are local and
                # must not invalidate an unseen tail that is not executing yet.
                if self.slice_size is None:
                    if not route.observed_slice(terrain, start):
                        replan_reason = 'next_edge_changed_or_displaced'
                else:
                    a = start
                    for b in route.nodes[route.index:route.index + len(route.slice(self.slice_size))]:
                        if b == a:
                            continue
                        if not terrain.edge(a, b):
                            replan_reason = 'next_edge_changed_or_displaced'
                            break
                        a = b
        if replan_reason:
            if replan_reason not in ('combat_preempted', 'ground_anchor_relocalized'):
                self.data['replans'] += 1
            if self.data['replans'] > self.max_replans:
                return self.stop('bounded_alternative_routes_exhausted')
            if route and replan_reason in ('failed_edge', 'no_observed_waypoint_progress'):
                # Exclude the actual failed directed edge. No automatic reversal
                # ban: a valid detour may legitimately begin by walking backward.
                edge = [list(route.nodes[route.index - 1]), list(route.nodes[route.index])]
                if edge not in self.data['forbidden']:
                    self.data['forbidden'].append(edge)
            problem = self.plan(observation, terrain, start)
            if problem:
                return problem
        elif route is None:
            problem = self.plan(observation, terrain, start)
            if problem:
                return problem
        route = self.route
        if route.done:
            return self.stop('empty_local_route_without_target_arrival')
        way = (route.observed_slice(terrain, start) if self.slice_size is None
               else route.slice(self.slice_size))
        if not way:
            return self.stop('no_observed_safe_execution_prefix')
        return self.submit('action', {'op': 'action', 'action': 'follow_path',
                                     'waypoints': way, 'timeout_ms': max(15000, len(way) * 1200)},
                           start_index=route.index, end_index=route.index + len(way))

    def tick(self, target):
        if len(target) not in (2, 3) or any(type(v) is not int for v in target):
            raise ValueError('target_must_be_integer_xz_or_xyz')
        if self.data['target'] is None:
            self.data['target'] = list(target)
        elif list(target) != self.data['target']:
            return self.result('blocked', 'finish_or_explicitly_replace_existing_goal')
        if self.data['blocked']:
            return self.result('blocked', self.data['blocked'])
        session = self.gateway.session()
        if session.get('implementation') not in ('native-defense-watchdog-v2', 'native-defense-watchdog-v3', 'native-defense-watchdog-v5'):
            return self.stop('watchdog_gateway_required_no_direct_queue')
        if type(session.get('defense_epoch')) is not int or session['defense_epoch'] < 0:
            return self.stop('watchdog_v3_defense_epoch_required')
        sid = session.get('session_id')
        if not sid:
            return self.stop('gateway_session_missing')
        if self.data['gateway_session'] is None:
            self.data['gateway_session'] = sid
        elif sid != self.data['gateway_session']:
            return self.stop('gateway_restarted_resolve_old_navigation_explicitly')
        pending = self.data['pending']
        if pending:
            response = self.gateway.result(pending['id'])
            if response is None or response.get('status') == 'pending':
                return self.result('pending', 'same_request_still_pending', request_id=pending['id'])
            if response.get('status') not in TERMINAL:
                return self.stop('invalid_gateway_result_status')
            if response['status'] == 'uncertain':
                return self.stop('action_outcome_uncertain_no_replay')
            self.data['pending'] = None
            if pending['kind'] == 'action':
                self.data['last_action'] = {'status': response['status'], 'reason': response.get('reason'),
                                            'end_index': pending['end_index'],
                                            'purpose': pending.get('purpose', 'navigation')}
                return self.result('progress', 'action_terminal_reobserve_before_cursor_advance')
            if response['status'] != 'succeeded':
                return self.stop('observation_' + response['status'])
            if time.time() - response.get('finished_at', time.time()) > 5:
                return self.result('progress', 'observation_expired_reobserve')
            # Do not act from an observation that finished while defense paused.
            if session.get('state') != 'ready' or session.get('phase') not in (None, 'watching'):
                return self.result('waiting', 'watchdog_preempted_reobserve_before_resume')
            if pending['defense_epoch'] != session['defense_epoch']:
                self.data['force_replan'] = True
                return self.result('progress', 'defense_epoch_changed_reobserve')
            self.data['observation_epoch'] = pending['defense_epoch']
            try:
                return self.process_observation(response.get('result', {}))
            except (KeyError, TypeError, ValueError) as exc:
                return self.stop('invalid_observation_' + str(exc))
        if session.get('state') != 'ready' or session.get('phase') not in (None, 'watching'):
            return self.result('waiting', 'watchdog_defending_or_paused')
        return self.submit('observe', {'op': 'observe', 'terrain': True,
                                      'radius': self.radius, 'vertical': self.vertical},
                           defense_epoch=session['defense_epoch'])
