"""Opt-in, fail-closed classification of a complete raw nearby snapshot.

This is an observation policy, never clearance to act or a replacement for the
native four-block tick guard. It neither removes rows nor rewrites a snapshot.
The caller retains the same immutable full work/route envelope for the whole
case; finished cells do not shrink it. Unknown classes remain blockers at every
distance. Only the pinned exact vanilla passive taxonomy, guarded bees/rabbits,
and empty ordinary boats can qualify. Distances use actual observed AABBs,
including baby/sitting bodies, rather than supplied distance labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import product
import math
import re
from uuid import UUID

from .ambient_taxonomy import PASSIVE_LIVING_TYPES


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _integer(value, low=0, high=2**63 - 1):
    return type(value) is int and low <= value <= high


def _nano(value):
    if (type(value) is not str or re.fullmatch(r"-?[0-9]{1,20}", value) is None
            or not -(2**63) <= int(value) < 2**63):
        raise ValueError("native_living_nano_invalid")
    return int(value)


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _vector(value):
    if not isinstance(value, dict) or not all(_number(value.get(k)) for k in ("x", "y", "z")):
        raise ValueError("invalid_vector")
    result = tuple(value[k] for k in ("x", "y", "z"))
    if any(abs(v) > 30_000_000 for v in result):
        raise ValueError("position_out_of_bounds")
    return result


@dataclass(frozen=True)
class Box:
    minimum: tuple
    maximum: tuple

    def __post_init__(self):
        if (type(self.minimum) is not tuple or type(self.maximum) is not tuple
                or len(self.minimum) != 3 or len(self.maximum) != 3
                or not all(_number(v) and abs(v) <= 30_000_000 for v in self.minimum + self.maximum)
                or not all(a < b for a, b in zip(self.minimum, self.maximum))):
            raise ValueError("invalid_protected_box")

    @classmethod
    def parse(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError("invalid_box")
        return cls(_vector(raw.get("min")), _vector(raw.get("max")))

    @classmethod
    def cell(cls, position):
        point = (position.x, position.y, position.z)
        return cls(point, tuple(v + 1 for v in point))

    def distance(self, other):
        return math.sqrt(sum(max(a - d, c - b, 0) ** 2
            for a, b, c, d in zip(self.minimum, self.maximum, other.minimum, other.maximum)))


@dataclass(frozen=True)
class AmbientPolicy:
    """Exact opt-in: context and complete original work/swept boxes only.

    Thresholds and admitted classes are deliberately not caller-configurable.
    Context order is world generation, dimension, player UUID, action session.
    """
    context: tuple
    protected_boxes: tuple

    def __post_init__(self):
        if (type(self.context) is not tuple or len(self.context) != 4
                or not all(type(v) is str and 0 < len(v) <= 128 for v in self.context)
                or self.context[1] != "minecraft:overworld"
                or type(self.protected_boxes) is not tuple
                or not 1 <= len(self.protected_boxes) <= 512
                or any(type(v) is not Box for v in self.protected_boxes)):
            raise ValueError("invalid_ambient_policy")


@dataclass(frozen=True)
class EntityClassification:
    index: int
    accepted: bool
    reason: str


@dataclass(frozen=True)
class AmbientReport:
    # Original row objects, including malformed rows, retained in original order.
    raw_entities: tuple
    classifications: tuple
    blockers: tuple

    @property
    def ok(self):
        return not self.blockers


class AmbientPhase(Enum):
    NONE = "none"
    OAK_LOG_PICKUP = "oak_log_pickup"
    FURNACE_OUTPUT_XP = "furnace_output_xp"


_CLASSES = {
    **{kind: spec.exact_class for kind, spec in PASSIVE_LIVING_TYPES.items()},
    "minecraft:boat": "net.minecraft.world.entity.vehicle.Boat",
    "minecraft:item": "net.minecraft.world.entity.item.ItemEntity",
    "minecraft:experience_orb": "net.minecraft.world.entity.ExperienceOrb",
}


def _entity_box(row, position):
    box = Box.parse(row.get("bounding_box"))
    if (not all(.05 <= b - a <= 4 for a, b in zip(box.minimum, box.maximum))
            or abs((box.minimum[0] + box.maximum[0]) / 2 - position[0]) > .001
            or abs(box.minimum[1] - position[1]) > .001
            or abs((box.minimum[2] + box.maximum[2]) / 2 - position[2]) > .001):
        raise ValueError("entity_geometry_incoherent")
    return box


def _living(row, state, policy, tick):
    if (not _number(row.get("health")) or not _number(row.get("max_health"))
            or not 0 < row["health"] <= row["max_health"] <= 2048
            or type(row.get("hurt_time")) is not int or row["hurt_time"] != 0
            or row.get("using_item") is not False):
        return "living_metadata_unknown_or_unsafe"
    facts = row.get("native_living")
    if not isinstance(facts, dict):
        return "native_living_unknown"
    if (type(facts.get("schema_version")) is not int or facts["schema_version"] != 1
            or facts.get("known") is not True or facts.get("source") != "integrated_server_tick"
            or facts.get("reason") != "observed"
            or facts.get("alive") is not True or facts.get("coverage_complete") is not True
            or not _integer(facts.get("inspected"), 1, 4096)
            or any(facts.get(key) != value for key, value in (
                ("entity_uuid", row["uuid"]), ("entity_id", row["entity_id"]),
                ("entity_type", row["type"]), ("world_generation", policy.context[0]),
                ("dimension", policy.context[1]), ("player_uuid", policy.context[2])))
            or type(facts.get("entity_id")) is not int):
        return "native_living_binding_unknown"
    if (not _integer(facts.get("source_tick")) or abs(tick - facts["source_tick"]) > 5
            or not _number(facts.get("sample_age_ms")) or not 0 <= facts["sample_age_ms"] <= 250
            or type(facts.get("sample_tick")) is not int or facts["sample_tick"] != tick):
        return "native_living_stale_or_malformed"
    try:
        source_nano, sample_nano = _nano(facts.get("source_nano")), _nano(facts.get("sample_nano"))
        guard = state.get("capability_guard")
        if (not isinstance(guard, dict) or type(guard.get("schema_version")) is not int
                or guard["schema_version"] != 1 or type(guard.get("source_tick")) is not int
                or guard["source_tick"] != tick):
            return "native_living_state_clock_unknown"
        guard_nano = _nano(guard.get("source_nano"))
        age = sample_nano - source_nano
        if (not 0 <= age <= 250_000_000 or not 0 <= sample_nano - guard_nano <= 250_000_000
                or abs(facts["sample_age_ms"] - age / 1_000_000) > .000001):
            return "native_living_clock_or_age_incoherent"
    except ValueError:
        return "native_living_stale_or_malformed"
    if (facts.get("aggressive") is not False or facts.get("current_target_known") is not True
            or "current_target" not in facts or facts["current_target"] is not None):
        return "native_living_aggressive_or_target_unknown"
    species = PASSIVE_LIVING_TYPES[row["type"]]
    if species.server_guard == "bee":
        bee = facts.get("bee")
        if (not isinstance(bee, dict) or bee.get("angry") is not False
                or type(bee.get("remaining_anger_ticks")) is not int or bee["remaining_anger_ticks"] != 0
                or "persistent_anger_target_uuid" not in bee or bee["persistent_anger_target_uuid"] is not None):
            return "bee_angry_or_anger_unknown"
    if species.server_guard == "rabbit":
        rabbit = facts.get("rabbit")
        if (not isinstance(rabbit, dict) or not _integer(rabbit.get("variant_id"), 0, 5)
                or rabbit.get("killer_bunny") is not False
                or rabbit.get("passive_goals_verified") is not True):
            return "rabbit_variant_or_passive_goals_unknown_or_unsafe"
    return None


def _classify(row, state, policy, tick, player_position, boxes, radius, phase):
    if not isinstance(row, dict):
        return "malformed_entity"
    kind = row.get("type")
    if type(kind) is not str or kind not in _CLASSES or row.get("class") != _CLASSES[kind]:
        return "unsupported_entity_type_or_class"
    if (not _uuid(row.get("uuid")) or not _integer(row.get("entity_id"), 0, 2**31 - 1)
            or row.get("alive") is not True or type(row.get("on_ground")) is not bool):
        return "entity_identity_or_life_unknown"
    try:
        position = _vector(row)
        velocity = _vector(row.get("velocity"))
        box = _entity_box(row, position)
    except ValueError as exc:
        return str(exc)
    measured = math.dist(player_position, position)
    if (not _number(row.get("distance")) or row["distance"] < 0
            or abs(row["distance"] - measured) > .05 or measured > radius + .001):
        return "entity_scan_geometry_incoherent"
    speed = math.sqrt(sum(v * v for v in velocity))
    speed_limit = .08 if kind == "minecraft:boat" else 1 if kind in ("minecraft:item", "minecraft:experience_orb") else .35
    if speed > speed_limit:
        return "ambient_entity_too_fast"
    if kind == "minecraft:item":
        item = row.get("item")
        if phase is not AmbientPhase.OAK_LOG_PICKUP:
            return "item_outside_approved_pickup_phase"
        if (not isinstance(item, dict) or item.get("id") != "minecraft:oak_log"
                or item.get("empty") is not False or not _integer(item.get("count"), 1, 64)
                or type(item.get("max_stack_size")) is not int or item["max_stack_size"] != 64
                or type(item.get("damage")) is not int or item["damage"] != 0
                or type(item.get("max_damage")) is not int or item["max_damage"] != 0
                or not all(type(item.get(k)) is str and 0 < len(item[k]) <= 256
                           for k in ("item_fingerprint", "component_fingerprint"))
                or measured > 8):
            return "oak_pickup_evidence_invalid_or_outside_radius"
        return None
    if kind == "minecraft:experience_orb":
        budget = state.get("movement_budget")
        if (phase is not AmbientPhase.FURNACE_OUTPUT_XP or not isinstance(budget, dict)
                or budget.get("furnace_xp_allowed") is not True or measured > 4):
            return "xp_outside_native_approved_furnace_phase"
        return None
    if kind == "minecraft:boat":
        if (row.get("ordinary_boat") is not True or type(row.get("passenger_count")) is not int
                or row["passenger_count"] != 0 or not _number(row.get("yaw_rate"))
                or abs(row["yaw_rate"]) > 1):
            return "boat_not_observed_empty_and_settled"
    else:
        problem = _living(row, state, policy, tick)
        if problem:
            return problem
    margin = PASSIVE_LIVING_TYPES[kind].clearance if kind in PASSIVE_LIVING_TYPES else 8
    if any(box.distance(protected) < margin for protected in boxes):
        return "ambient_entity_near_protected_envelope"
    return None


def classify_ambient_entities(state, policy, *, additional_boxes=(), phase=AmbientPhase.NONE):
    """Return explicit blockers without changing or concealing any input row.

    Nearby scans filter entity positions, not their AABBs. Every scan must cover
    all protected corners plus the twelve-block clearance and five more blocks
    for the bounded entity body (maximum origin-to-corner is sqrt(24) < 5), even
    when no entities were returned. Additional target
    boxes can only enlarge the immutable case envelope, never replace it.
    """
    nearby = state.get("nearby") if isinstance(state, dict) else None
    rows = nearby.get("entities") if isinstance(nearby, dict) else None
    raw = tuple(rows) if isinstance(rows, list) else ()
    errors = []
    results = []
    try:
        if type(policy) is not AmbientPolicy:
            raise ValueError("exact_ambient_policy_required")
        if type(phase) is not AmbientPhase:
            raise ValueError("exact_ambient_phase_required")
        if type(additional_boxes) is not tuple or any(type(b) is not Box for b in additional_boxes):
            raise ValueError("invalid_additional_protected_boxes")
        world, player, action = state["world"], state["player"], state["client_action"]
        context = (world.get("world_generation"), world.get("dimension"), player.get("uuid"), action.get("action_session"))
        if (context != policy.context or player.get("dimension") != context[1]
                or state.get("private_singleplayer") is not True):
            raise ValueError("ambient_context_mismatch")
        tick = world.get("game_time")
        if not _integer(tick):
            raise ValueError("ambient_game_tick_invalid")
        position = _vector(player)
        player_box = _entity_box(player, position)
        boxes = (player_box,) + policy.protected_boxes + additional_boxes
        if (not isinstance(rows, list) or len(rows) > 128 or nearby.get("truncated") is not False
                or not _integer(nearby.get("total"), 0, 128)
                or not _integer(nearby.get("returned"), 0, 128)
                or nearby["total"] != nearby["returned"] or nearby["returned"] != len(rows)):
            raise ValueError("ambient_entity_scan_incomplete")
        radius = nearby.get("radius")
        if not _number(radius) or not 0 < radius <= 128:
            raise ValueError("ambient_entity_scan_radius_invalid")
        required = max(math.dist(position, point) + 17 for box in boxes
                       for point in product(*zip(box.minimum, box.maximum)))
        if radius < required:
            errors.append("ambient_scan_does_not_cover_protected_envelope")
        seen_ids, seen_uuids = set(), set()
        for index, row in enumerate(rows):
            reason = _classify(row, state, policy, tick, position, boxes, radius, phase)
            if isinstance(row, dict) and _integer(row.get("entity_id")) and _uuid(row.get("uuid")):
                if row["entity_id"] in seen_ids or row["uuid"] in seen_uuids:
                    reason = "duplicate_entity_identity"
                seen_ids.add(row["entity_id"])
                seen_uuids.add(row["uuid"])
            results.append(EntityClassification(index, reason is None, reason or "distant_known_ambient"))
            if reason:
                errors.append("ambient_entity_" + str(index) + ":" + reason)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        errors.append(str(exc) if isinstance(exc, ValueError) else "ambient_state_evidence_malformed")
    if len(results) != len(raw):
        results = [EntityClassification(i, False, "unclassified_invalid_snapshot") for i in range(len(raw))]
    return AmbientReport(raw, tuple(results), tuple(errors))


def reacquirable_entity_absence(state, policy, *, phase=AmbientPhase.NONE):
    """Describe only an explicit, distant server-row absence for READ-ONLY wait.

    This never accepts the observation, changes the strict report, removes an
    entity or infers calm. A caller may use it only to obtain bounded NEW samples
    while idle; every remaining entity must fully pass the original classifier
    before any mutation. Identity mismatch, stale facts and danger are not this
    availability condition.
    """
    report = classify_ambient_entities(state, policy, phase=phase)
    if report.ok or type(policy) is not AmbientPolicy:
        return None
    try:
        rows = report.raw_entities
        bad = [item for item in report.classifications if not item.accepted]
        expected = tuple('ambient_entity_' + str(item.index) + ':native_living_binding_unknown'
                         for item in bad)
        if not bad or report.blockers != expected:
            return None
        world, player, action = state['world'], state['player'], state['client_action']
        context = (world['world_generation'], world['dimension'], player['uuid'], action['action_session'])
        if context != policy.context:
            return None
        player_box = _entity_box(player, _vector(player))
        boxes = (player_box,) + policy.protected_boxes
        required = {'schema_version', 'entity_uuid', 'entity_id', 'entity_type', 'dimension',
                    'world_generation', 'player_uuid', 'known', 'source', 'reason',
                    'current_target_known', 'coverage_complete', 'inspected'}
        missing = []
        for item in bad:
            row = rows[item.index]
            facts = row['native_living']
            if (item.reason != 'native_living_binding_unknown'
                    or row['type'] not in PASSIVE_LIVING_TYPES
                    or not PASSIVE_LIVING_TYPES[row['type']].source_absence_reacquirable
                    or type(facts) is not dict or set(facts) != required
                    or type(facts['schema_version']) is not int or facts['schema_version'] != 1
                    or facts['known'] is not False or facts['source'] != 'unavailable'
                    or facts['reason'] != 'entity_not_observed'
                    or facts['current_target_known'] is not False or facts['coverage_complete'] is not True
                    or not _integer(facts['inspected'], 1, 4096)
                    or type(facts['entity_id']) is not int
                    or any(facts[key] != value for key, value in (
                        ('entity_uuid', row['uuid']), ('entity_id', row['entity_id']),
                        ('entity_type', row['type']), ('world_generation', context[0]),
                        ('dimension', context[1]), ('player_uuid', context[2])))):
                return None
            # _classify already proved body/velocity/health/identity metadata.
            # Its normal missing-facts rejection occurs before the margin check,
            # so explicitly retain that unchanged check for this WAIT-only path.
            box = _entity_box(row, _vector(row))
            margin = PASSIVE_LIVING_TYPES[row['type']].clearance
            if any(box.distance(protected) < margin for protected in boxes):
                return None
            missing.append({'index': item.index, 'uuid': row['uuid'], 'entity_id': row['entity_id'],
                            'type': row['type'], 'reason': 'entity_not_observed'})
        return {'schema_version': 1, 'kind': 'distant_entity_source_absence',
                'context': list(context), 'game_tick': world['game_time'],
                'missing_entities': missing, 'classifier_blockers': list(report.blockers),
                'observation_accepted': False, 'read_only_reacquisition_only': True}
    except (KeyError, TypeError, AttributeError, ValueError):
        return None
