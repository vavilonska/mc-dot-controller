"""Closed, bounded wire schemas. Role labels and text NEVER confer authority."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re

MAX_WIRE_BYTES = 64 * 1024
ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
RESOURCE = re.compile(r"[a-z0-9_.-]{1,40}:[a-z0-9/._-]{1,100}\Z")
SECTIONS = frozenset({'player', 'terrain', 'entities', 'inventory', 'action', 'scan'})
HOSTILES = frozenset({'minecraft:zombie', 'minecraft:husk', 'minecraft:zombie_villager',
                     'minecraft:skeleton', 'minecraft:stray', 'minecraft:bogged', 'minecraft:creeper'})
KINDS = frozenset({'follow_path', 'defend_entity'})


class Rejected(ValueError):
    """Errors are stable codes, never interpolated untrusted data."""


def require(condition, code):
    if not condition:
        raise Rejected(code)


def identifier(value):
    require(isinstance(value, str) and ID.fullmatch(value) is not None, 'invalid_identifier')
    return value


def number(value, low, high):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            'invalid_number')
    return value


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, 'invalid_integer')
    return value


def fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= value.keys()
            and value.keys() <= set(required) | set(optional), 'schema_fields')
    return value


def canonical(value):
    try:
        data = json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
    except (ValueError, TypeError, RecursionError):
        raise Rejected('invalid_json') from None
    require(len(data) <= MAX_WIRE_BYTES, 'wire_too_large')
    return data


def loads(data):
    require(type(data) in (str, bytes) and len(data) <= MAX_WIRE_BYTES, 'wire_too_large')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Rejected('invalid_json')))
    except (ValueError, RecursionError):
        raise Rejected('invalid_json') from None


@dataclass(frozen=True)
class Context:
    dimension: str
    world_generation: str
    player_id: str
    action_session: str
    resident_session: str

    def __post_init__(self):
        require(isinstance(self.dimension, str) and RESOURCE.fullmatch(self.dimension), 'invalid_dimension')
        for value in (self.world_generation, self.player_id, self.action_session, self.resident_session):
            identifier(value)

    def wire(self):
        return dict(vars(self))

    @classmethod
    def parse(cls, value):
        fields(value, ('dimension', 'world_generation', 'player_id', 'action_session', 'resident_session'))
        return cls(**value)


def point(value):
    fields(value, ('x', 'y', 'z'))
    return {k: number(value[k], -30_000_000 if k != 'y' else -2048,
                       30_000_000 if k != 'y' else 2048) for k in ('x', 'y', 'z')}


def intent(value):
    fields(value, ('kind', 'timeout_ms'), ('waypoints', 'target_uuid', 'target_entity_id', 'target_type'))
    require(type(value['kind']) is str and value['kind'] in KINDS, 'intent_not_allowed')
    timeout = integer(value['timeout_ms'], 50, 10_000)
    if value['kind'] == 'follow_path':
        fields(value, ('kind', 'timeout_ms', 'waypoints'))
        require(type(value['waypoints']) is list and 1 <= len(value['waypoints']) <= 16, 'waypoint_bound')
        return {'kind': 'follow_path', 'timeout_ms': timeout, 'waypoints': [point(p) for p in value['waypoints']]}
    fields(value, ('kind', 'timeout_ms', 'target_uuid', 'target_entity_id', 'target_type'))
    require(value['target_type'] in HOSTILES, 'hostile_not_allowed')
    require(timeout <= 3000, 'defense_timeout_max_3000')
    return {'kind': 'defend_entity', 'timeout_ms': timeout,
            'target_uuid': identifier(value['target_uuid']),
            'target_entity_id': integer(value['target_entity_id'], 0, 2**31 - 1),
            'target_type': value['target_type']}


@dataclass(frozen=True)
class Proposal:
    """A planning suggestion; owned immutable bytes prevent post-validation edits."""
    encoded: bytes

    @classmethod
    def parse(cls, value):
        try:
            return cls._parse(value)
        except (TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            raise Rejected('invalid_schema') from None

    @classmethod
    def _parse(cls, value):
        fields(value, ('proposal_id', 'task_id', 'epoch', 'lease_revision', 'role', 'context',
                       'based_on', 'ttl_ms', 'intent', 'dependencies', 'priority', 'preconditions',
                       'cancel_requested'))
        for key in ('proposal_id', 'task_id', 'epoch', 'role'):
            identifier(value[key])
        integer(value['lease_revision'], 1, 2**31 - 1)
        Context.parse(value['context'])
        refs = value['based_on']
        require(type(refs) is dict and refs and refs.keys() <= SECTIONS, 'invalid_revisions')
        for revision in refs.values():
            integer(revision, 1, 2**63 - 1)
        integer(value['ttl_ms'], 50, 15_000)
        action = intent(value['intent'])
        require(type(value['dependencies']) is list and len(value['dependencies']) <= 8, 'dependency_bound')
        for dep in value['dependencies']:
            identifier(dep)
        require(len(set(value['dependencies'])) == len(value['dependencies'])
                and value['proposal_id'] not in value['dependencies'], 'invalid_dependency')
        integer(value['priority'], 0, 100)
        conditions = value['preconditions']
        fields(conditions, ('alive', 'grounded', 'screen_closed', 'min_health', 'expected_position'))
        if action['kind'] == 'follow_path':
            point(conditions['expected_position'])
        else:
            require(conditions['expected_position'] is None, 'defense_position_must_be_null')
        require(all(conditions[x] is True for x in ('alive', 'grounded', 'screen_closed')), 'required_safety')
        number(conditions['min_health'], 1, 20)
        require(type(value['cancel_requested']) is bool, 'invalid_cancel_marker')
        clean = {**value, 'intent': action}
        return cls(canonical(clean))

    def wire(self):
        return json.loads(self.encoded)


@dataclass(frozen=True)
class Grant:
    """Created only by the trusted owner after authorization, never from a proposal."""
    task_id: str
    context: Context
    allowed_kinds: frozenset[str]
    bounds: tuple[float, float, float, float, float, float]
    allowed_targets: frozenset[str] = frozenset()
    max_actions: int = 32
    execution_budget_ms: int = 30_000
    duration_ms: int = 60_000
    lease_ms: int = 5000
    allow_defense_preemption: bool = False
    max_cancellations: int = 4

    def __post_init__(self):
        identifier(self.task_id)
        require(type(self.context) is Context, 'invalid_context')
        require(type(self.allowed_kinds) is frozenset and self.allowed_kinds and self.allowed_kinds <= KINDS,
                'invalid_allowed_kinds')
        require(type(self.allowed_targets) is frozenset and len(self.allowed_targets) <= 32, 'target_bound')
        for target in self.allowed_targets:
            identifier(target)
        require(type(self.bounds) is tuple and len(self.bounds) == 6, 'invalid_bounds')
        for i in range(3):
            number(self.bounds[i], -30_000_000, 30_000_000)
            number(self.bounds[i + 3], self.bounds[i], 30_000_000)
        integer(self.max_actions, 1, 256)
        integer(self.execution_budget_ms, 50, 600_000)
        integer(self.duration_ms, 50, 600_000)
        integer(self.lease_ms, 50, min(30_000, self.duration_ms))
        integer(self.max_cancellations, 0, 32)
        require(type(self.allow_defense_preemption) is bool, 'invalid_preemption')

    def contains(self, p):
        return all(self.bounds[i] <= p[key] <= self.bounds[i + 3] for i, key in enumerate(('x', 'y', 'z')))
