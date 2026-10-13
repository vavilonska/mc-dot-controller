"""Finite, effect-free local tactical choices and the initial stop-only boundary.

Facts here are a trusted adapter's typed summary, never an admission witness.
Decisions can select a candidate existing skill; they cannot execute one. P2's
initial supervisor supports stop only, so at_boundary always closes/latches the
ordinary task. Entity/terrain transition integration must precede reflex writes.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, dataclass
import math

from .contracts import ToolboxError, integer, obj, validate_schema
from .control import ControlStop


def number(low, high):
    return {'type': 'number', 'minimum': low, 'maximum': high}


_ID = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': '^[A-Za-z0-9_-]+$'}
_POS = obj({'x': number(-30000000, 30000000), 'y': number(-2048, 2048),
            'z': number(-30000000, 30000000)}, ('x', 'y', 'z'))
_BOOL = {'type': 'boolean'}
_REGION = obj({'min': _POS, 'max': _POS}, ('min', 'max'))
POLICY_SCHEMA = obj({
    'version': {'const': 1}, 'goal_id': _ID,
    'mode': {'enum': ['stop', 'avoid', 'defend']}, 'min_health': number(8, 20),
    'region': _REGION,
    'allowed_target_uuids': {'type': 'array', 'items': _ID, 'maxItems': 16, 'uniqueItems': True},
    'allow_ranged': _BOOL, 'allow_environment_recovery': _BOOL,
    'max_reactions': integer(0, 16), 'max_target_distance': number(0, 32),
    'max_route_distance': number(0, 8)},
    ('version', 'goal_id', 'mode', 'min_health', 'region', 'allowed_target_uuids',
     'allow_ranged', 'allow_environment_recovery', 'max_reactions', 'max_target_distance', 'max_route_distance'))
_THREAT = obj({'uuid': _ID, 'position': _POS, 'alive': _BOOL, 'hostile': _BOOL,
    'attacking_player': _BOOL, 'melee_eligible': _BOOL, 'ranged_eligible': _BOOL,
    'required_health_reserve': number(8, 20)},
    ('uuid', 'position', 'alive', 'hostile', 'attacking_player', 'melee_eligible',
     'ranged_eligible', 'required_health_reserve'))
_ROUTE = obj({'kind': {'enum': ['retreat', 'recover_hazard']}, 'target_uuid': _ID,
    'points': {'type': 'array', 'items': _POS, 'minItems': 1, 'maxItems': 8},
    'complete_loaded_safe_corridor': _BOOL, 'improves_safety': _BOOL},
    ('kind', 'points', 'complete_loaded_safe_corridor', 'improves_safety'))
FACTS_SCHEMA = obj({'goal_id': _ID, 'goal_valid': _BOOL, 'context_same': _BOOL,
    'owner_known': _BOOL, 'cleanup_confirmed': _BOOL, 'complete': _BOOL,
    'player_position': _POS, 'health': number(0, 1024),
    'hazard': {'enum': ['none', 'water', 'fire', 'lava', 'powder_snow', 'unsupported']},
    'threats': {'type': 'array', 'items': _THREAT, 'maxItems': 16},
    'routes': {'type': 'array', 'items': _ROUTE, 'maxItems': 8},
    'reactions_used': integer(0, 100000)},
    ('goal_id', 'goal_valid', 'context_same', 'owner_known', 'cleanup_confirmed', 'complete',
     'player_position', 'health', 'hazard', 'threats', 'routes', 'reactions_used'))
BUDGET_SCHEMA = obj({'remaining_seconds': number(0, 86400), 'actions_remaining': integer(0, 100000),
    'observations_remaining': integer(0, 100000), 'reflex_actions_remaining': integer(0, 100000)},
    ('remaining_seconds', 'actions_remaining', 'observations_remaining', 'reflex_actions_remaining'))


@dataclass(frozen=True)
class TacticalDecision:
    action: str
    reason: str
    goal_id: str
    target_uuid: str | None = None
    ranged: bool = False
    path_distance: float = 0.0
    min_health: float = 0.0
    execution_authority: bool = False
    continuation_safe: bool = False

    def as_dict(self):
        return asdict(self)


def _point(value):
    return tuple(value[key] for key in ('x', 'y', 'z'))


def _inside(point, region):
    return all(region['min'][key] <= point[key] <= region['max'][key] for key in ('x', 'y', 'z'))


def decide(policy, facts, budget):
    """Pure deterministic priority choice, bounded to 16 threats and 8 routes.

    Eligibility summarizes existing species/LOS/equipment guards, and never
    substitutes for those guards at dispatch. All returned choices are proposals.
    """
    validate_schema(policy, POLICY_SCHEMA)
    validate_schema(facts, FACTS_SCHEMA)
    validate_schema(budget, BUDGET_SCHEMA)
    region = policy['region']
    if any(region['min'][key] > region['max'][key]
           or region['max'][key] - region['min'][key] > 256 for key in ('x', 'y', 'z')):
        raise ToolboxError('invalid_request', 'Tactical region must be ordered and at most 256 blocks per axis')
    ids = [target['uuid'] for target in facts['threats']]
    if len(set(ids)) != len(ids):
        raise ToolboxError('invalid_request', 'Duplicate tactical target identity')

    def stop(reason):
        return TacticalDecision('stop', reason, policy['goal_id'], min_health=policy['min_health'])

    for flag, reason in (('owner_known', 'owner_unknown'), ('context_same', 'context_changed'),
                         ('cleanup_confirmed', 'cleanup_unconfirmed'), ('complete', 'facts_incomplete'),
                         ('goal_valid', 'goal_requires_fresh_replan')):
        if not facts[flag]:
            return stop(reason)
    if facts['goal_id'] != policy['goal_id']:
        return stop('goal_identity_changed')
    if facts['health'] <= 0:
        return stop('player_not_alive')
    if not _inside(facts['player_position'], region):
        return stop('player_outside_authorized_region')
    if policy['mode'] == 'stop':
        return stop('caller_stop_policy')
    if budget['remaining_seconds'] < .05:
        return stop('original_deadline_exhausted')
    if (budget['actions_remaining'] < 1 or budget['reflex_actions_remaining'] < 1
            or budget['observations_remaining'] < 2 or facts['reactions_used'] >= policy['max_reactions']):
        return stop('original_reflex_budget_exhausted')
    active = [target for target in facts['threats'] if target['alive'] and target['hostile'] and target['attacking_player']]
    active.sort(key=lambda target: (math.dist(_point(facts['player_position']), _point(target['position'])), target['uuid']))
    if not active and facts['hazard'] == 'none':
        return stop('no_observed_local_threat')
    if facts['hazard'] == 'unsupported':
        return stop('unsupported_environment_hazard')

    def route(kind, target=None):
        candidates = []
        for entry in facts['routes']:
            if entry['kind'] != kind or not entry['complete_loaded_safe_corridor'] or not entry['improves_safety']:
                continue
            if target is not None and entry.get('target_uuid') != target['uuid']:
                continue
            if kind == 'recover_hazard' and 'target_uuid' in entry:
                continue
            if target is not None:
                original = math.dist(_point(facts['player_position']), _point(target['position']))
                separation = math.dist(_point(entry['points'][-1]), _point(target['position']))
                if separation < original + .5:
                    continue
            if not all(_inside(point, region) for point in entry['points']):
                continue
            points = [facts['player_position'], *entry['points']]
            distance = sum(math.dist(_point(a), _point(b)) for a, b in zip(points, points[1:]))
            if 0 < distance <= policy['max_route_distance'] and (kind != 'retreat' or distance <= 2):
                candidates.append(distance)
        return min(candidates) if candidates else None

    if facts['hazard'] != 'none':
        distance = route('recover_hazard') if policy['allow_environment_recovery'] else None
        if distance is None:
            return stop('no_authorized_safe_environment_egress')
        return TacticalDecision('recover_hazard', 'immediate_environment_survival', policy['goal_id'],
                                path_distance=distance, min_health=policy['min_health'])
    nearest = active[0]
    # Low health, mixed threats and any unauthorized threat forbid retaliation.
    authorized = all(target['uuid'] in policy['allowed_target_uuids'] for target in active)
    target_reserve = max(policy['min_health'], nearest['required_health_reserve'])
    safe_attack = (policy['mode'] == 'defend' and authorized and len(active) == 1
                   and facts['health'] > target_reserve
                   and _inside(nearest['position'], region)
                   and math.dist(_point(facts['player_position']), _point(nearest['position'])) <= policy['max_target_distance'])
    if safe_attack and (nearest['melee_eligible'] or policy['allow_ranged'] and nearest['ranged_eligible']):
        return TacticalDecision('strike', 'authorized_immediate_counterattack', policy['goal_id'], nearest['uuid'],
            ranged=not nearest['melee_eligible'], min_health=target_reserve)
    distance = route('retreat', nearest)
    if distance is not None:
        return TacticalDecision('retreat', 'avoid_threat_within_region', policy['goal_id'], nearest['uuid'],
                                path_distance=distance, min_health=policy['min_health'])
    return stop('no_authorized_safe_local_response')


def decide_with_control(control, policy, facts):
    """Read the original P2 ledger; do not invent or reset nested allowances."""
    control.checkpoint()
    snapshot = control.budget.snapshot()
    limits, used = snapshot['limits'], snapshot['used']
    decision = decide(policy, facts, {
        'remaining_seconds': min(86400, snapshot['remaining_seconds']),
        'actions_remaining': snapshot['remaining']['actions'],
        'observations_remaining': snapshot['remaining']['observations'],
        'reflex_actions_remaining': max(0, limits['reflex_reserve_actions'] - used['reflex']['actions'])})
    control.emit('tactical_decision', decision.as_dict())
    return decision


def at_boundary(supervisor, policy, facts):
    """Current integration: record a decision, then latch the stop-only supervisor.

    This function deliberately cannot execute a candidate or certify continuation.
    No supplied callback, second Runtime, control writer or native command exists.
    """
    if supervisor.policy.get('reactions', 'stop') != 'stop':
        raise ControlStop('tactical_native_transition_unavailable')
    decision = decide_with_control(supervisor.control, policy, facts)
    supervisor.boundary('tactical_native_transition_unavailable:' + decision.reason,
        cleanup_confirmed=facts['cleanup_confirmed'], facts=deepcopy(decision.as_dict()))
    raise ControlStop('tactical_boundary_must_not_continue')
