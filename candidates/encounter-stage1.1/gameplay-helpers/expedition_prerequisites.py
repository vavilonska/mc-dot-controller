"""Offline, no-I/O expedition safety protocols.

These classes do not open a queue, send keys, dispatch pearls or open containers.
The native trajectory verifier and the live container transaction adapter are
intentionally absent. Every state machine uses a single owner and finite budget.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import math


class Stopped(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise Stopped(reason)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    z: float

    def __post_init__(self):
        require(all(finite(v) and abs(v) <= 30_000_000 for v in (self.x, self.y, self.z)), "invalid_position")

    def distance(self, other):
        return math.dist((self.x, self.y, self.z), (other.x, other.y, other.z))


@dataclass(frozen=True)
class Identity:
    session: str
    world: str
    player: str
    dimension: str

    def __post_init__(self):
        require(all(type(v) is str and 0 < len(v) <= 128 for v in
                    (self.session, self.world, self.player, self.dimension)), "invalid_identity")


@dataclass(frozen=True)
class PearlIntent:
    action_id: str
    owner: str
    identity: Identity
    epoch: int
    slot: int
    item_id: str
    expected_count: int
    origin: Position
    landing: Position
    yaw: float
    pitch: float
    budget_ms: int = 8000

    def __post_init__(self):
        require(type(self.action_id) is str and 0 < len(self.action_id) <= 128, "invalid_action_id")
        require(type(self.owner) is str and 0 < len(self.owner) <= 128, "invalid_owner")
        require(isinstance(self.identity, Identity), "invalid_identity")
        require(type(self.epoch) is int and self.epoch >= 0, "invalid_epoch")
        require(type(self.slot) is int and 0 <= self.slot <= 8, "invalid_slot")
        require(self.item_id == "minecraft:ender_pearl", "unsupported_single_use_item")
        require(type(self.expected_count) is int and 1 <= self.expected_count <= 16, "invalid_count")
        require(isinstance(self.origin, Position) and isinstance(self.landing, Position), "invalid_target")
        require(.5 <= self.origin.distance(self.landing) <= 32, "landing_outside_short_crossing_budget")
        require(finite(self.yaw) and -180 <= self.yaw <= 180 and finite(self.pitch) and -90 <= self.pitch <= 90,
                "invalid_aim")
        require(type(self.budget_ms) is int and 500 <= self.budget_ms <= 10000, "invalid_budget")


@dataclass(frozen=True)
class UseObservation:
    identity: Identity
    epoch: int
    owner: str
    position: Position
    slot: int
    item_id: str
    count: int
    speed: float
    grounded: bool
    supported: bool
    loaded: bool
    screen_open: bool = False
    alive: bool = True
    connected: bool = True
    cooldown: bool = False

    def __post_init__(self):
        require(isinstance(self.identity, Identity) and isinstance(self.position, Position), "invalid_observation_identity")
        require(type(self.epoch) is int and self.epoch >= 0, "invalid_epoch")
        require(type(self.owner) is str and 0 < len(self.owner) <= 128, "invalid_owner")
        require(type(self.slot) is int and 0 <= self.slot <= 8, "invalid_slot")
        require(type(self.count) is int and 0 <= self.count <= 64, "invalid_count")
        require(type(self.item_id) is str and len(self.item_id) <= 128
                and (self.item_id.startswith("minecraft:") if self.count else self.item_id == ""), "invalid_item_id")
        require(finite(self.speed) and self.speed >= 0, "invalid_speed")
        require(all(type(flag) is bool for flag in (self.grounded, self.supported, self.loaded,
                self.screen_open, self.alive, self.connected, self.cooldown)), "invalid_observation_flags")


@dataclass(frozen=True)
class TrajectoryProof:
    """Internal verifier output, never a user-supplied 'verified':true wire flag.

    A production verifier must account for vanilla launch uncertainty, swept
    collision, entities, gateway behavior and the entire possible landing region.
    This candidate supplies no production issuer, so native launch stays disabled.
    """
    intent: PearlIntent
    observation: UseObservation
    issued_ms: int
    expires_ms: int
    ray_target: str
    verified_loaded_sweep: bool
    verified_landing_region: bool


class UnavailableTrajectoryVerifier:
    def verify(self, intent, observation, now_ms):
        raise Stopped("native_trajectory_verifier_not_implemented")


class OneShotPearl:
    """Pure one-use budget. DISPATCH_ONCE is a proposal, not a game operation."""
    def __init__(self, intent, now_ms, verifier=None):
        require(type(now_ms) is int and now_ms >= 0, "invalid_clock")
        self.intent = intent
        self.deadline = now_ms + intent.budget_ms
        self.last_ms = now_ms
        self.verifier = verifier or UnavailableTrajectoryVerifier()
        self.phase = "prepared"
        self.reason = None
        self.dispatches = 0
        self.release_required = False

    def _clock(self, now_ms):
        require(type(now_ms) is int and now_ms >= self.last_ms, "clock_regressed")
        self.last_ms = now_ms
        if now_ms >= self.deadline:
            self.stop("deadline_exceeded")
            raise Stopped(self.reason)

    def _context(self, observation):
        require(isinstance(observation, UseObservation), "invalid_observation")
        if (observation.identity != self.intent.identity or observation.owner != self.intent.owner
                or not observation.alive or not observation.connected or observation.screen_open):
            self.stop("context_changed")
            raise Stopped(self.reason)
        require(finite(observation.speed) and observation.speed >= 0, "invalid_speed")

    def dispatch_proposal(self, observation, now_ms):
        self._clock(now_ms)
        require(self.phase == "prepared", "no_replay")
        self._context(observation)
        require(observation.epoch == self.intent.epoch, "epoch_changed")
        require(observation.position.distance(self.intent.origin) <= .05 and observation.speed <= .01
                and observation.grounded and observation.supported and observation.loaded, "launch_not_stable")
        require((observation.slot, observation.item_id, observation.count) ==
                (self.intent.slot, self.intent.item_id, self.intent.expected_count), "held_stack_changed")
        require(not observation.cooldown, "item_on_cooldown")
        proof = self.verifier.verify(self.intent, observation, now_ms)
        require(isinstance(proof, TrajectoryProof) and proof.intent == self.intent and proof.observation == observation,
                "trajectory_proof_not_bound")
        require(type(proof.issued_ms) is int and type(proof.expires_ms) is int
                and proof.issued_ms <= now_ms <= proof.expires_ms <= proof.issued_ms + 100,
                "trajectory_proof_stale")
        require(type(proof.ray_target) is str and 0 < len(proof.ray_target) <= 128
                and proof.verified_loaded_sweep is True and proof.verified_landing_region is True,
                "trajectory_or_ray_unverified")
        # Consume before any prospective adapter can send. Exception/lost result
        # leaves this action spent; there is no retry/reset/new-ID helper here.
        self.phase = "observing"
        self.dispatches = 1
        self.release_required = True
        return "DISPATCH_ONCE"

    def observe_landing(self, observation, now_ms):
        self._clock(now_ms)
        require(self.phase == "observing", "not_observing")
        self._context(observation)
        if observation.slot != self.intent.slot:
            self.stop("held_slot_changed")
            raise Stopped(self.reason)
        if (observation.epoch > self.intent.epoch and observation.position.distance(self.intent.landing) <= .25
                and observation.grounded and observation.supported and observation.loaded and observation.speed <= .1
                and observation.count == self.intent.expected_count - 1
                and observation.item_id == (self.intent.item_id if observation.count else "")):
            self.phase = "observed_landing"
            self.reason = "client_observed_not_server_confirmed"
            return True
        return False

    def stop(self, reason):
        if self.phase in ("uncertain", "cancelled", "observed_landing"):
            return
        self.phase = "uncertain" if self.dispatches else "cancelled"
        self.reason = reason
        self.release_required = True

    def confirm_release(self):
        self.release_required = False


def basic_item(raw):
    """Only fully represented plain cargo is eligible for exact verification."""
    require(type(raw) is dict, "invalid_item")
    count = raw.get("count")
    require(type(count) is int and 0 <= count <= 64, "invalid_count")
    if count == 0:
        require(raw.get("empty") is True or raw.get("id") == "", "ambiguous_empty")
        return ("", 0, 0)
    name = raw.get("id")
    require(type(name) is str and name.startswith("minecraft:") and len(name) <= 128, "invalid_item_id")
    require(name != "minecraft:shulker_box" and not name.endswith("_shulker_box"), "nested_shulker_forbidden")
    require(raw.get("identity_complete") is True, "incomplete_item_identity")
    damage = raw.get("damage", 0)
    require(type(damage) is int and damage >= 0, "invalid_damage")
    return name, count, damage


def cargo_slots(rows):
    require(type(rows) in (list, tuple) and len(rows) == 27, "requires_exactly_27_slots")
    return tuple(basic_item(row) for row in rows)


def shulker_contents(raw):
    """Decode the native bounded sparse summary without assuming omitted cargo is empty."""
    require(type(raw) is dict and raw.get("identity_complete") is True, "incomplete_box_identity")
    name = raw.get("id")
    require(type(name) is str and name.startswith("minecraft:")
            and (name == "minecraft:shulker_box" or name.endswith("_shulker_box")), "not_a_shulker_box")
    require(type(raw.get("count")) is int and raw["count"] == 1, "ambiguous_box_stack")
    summary = raw.get("container")
    require(type(summary) is dict and type(summary.get("schema_version")) is int and summary["schema_version"] == 1
            and type(summary.get("capacity")) is int and summary["capacity"] == 27
            and summary.get("slots_truncated") is False and summary.get("nested_containers_supported") is False,
            "incomplete_container_summary")
    extent = summary.get("slot_extent")
    require(type(extent) is int and 0 <= extent <= 27, "invalid_slot_extent")
    rows = summary.get("items")
    require(type(rows) is list and len(rows) <= 27, "invalid_container_items")
    result = [("", 0, 0)] * 27
    used = set()
    for row in rows:
        require(type(row) is dict, "invalid_container_row")
        index = row.get("slot")
        require(type(index) is int and 0 <= index < extent and index not in used, "duplicate_or_invalid_container_slot")
        used.add(index)
        result[index] = basic_item(row)
        require(result[index][1] > 0, "sparse_empty_row")
    return tuple(result)


def inventory_slots(rows):
    require(type(rows) in (list, tuple) and len(rows) == 36, "requires_exactly_36_inventory_slots")
    return tuple(basic_item(row) for row in rows)


def totals(slots):
    result = Counter()
    for name, count, damage in slots:
        if count:
            result[(name, damage)] += count
    return result


class ShulkerCycle:
    """Executable verification reducer for one place/transfer/recover cycle.

    No game adapter is connected. Observations supplied by an eventual adapter
    must be fresh and causally bound to the same action ID; they are not proof
    of server persistence. A recovered item must expose complete component data.
    """
    STEPS = ("place", "open", "transfer", "close", "break", "pickup", "replace", "reopen", "verify")

    def __init__(self, identity, owner, block_position, before, after, now_ms, budget_ms=30000):
        require(isinstance(identity, Identity) and isinstance(block_position, Position), "invalid_identity_or_position")
        require(type(owner) is str and 0 < len(owner) <= 128, "invalid_owner")
        require(type(now_ms) is int and now_ms >= 0 and type(budget_ms) is int and 1000 <= budget_ms <= 60000,
                "invalid_budget")
        self.identity, self.owner, self.position = identity, owner, block_position
        self.before, self.after = cargo_slots(before), cargo_slots(after)
        self.deadline, self.last_ms = now_ms + budget_ms, now_ms
        self.index, self.pending, self.stopped = 0, None, None
        self.ids = set()
        self.menu_id = None
        self.initial_inventory = None
        self.release_required = False

    @property
    def phase(self):
        return self.stopped or (self.STEPS[self.index] if self.index < len(self.STEPS) else "complete")

    def propose(self, action_id, identity, owner, now_ms):
        self._context(identity, owner, now_ms)
        require(self.stopped is None and self.index < len(self.STEPS), "cycle_terminal")
        require(self.pending is None, "pending_result_no_replay")
        require(type(action_id) is str and 0 < len(action_id) <= 128 and action_id not in self.ids, "action_id_reused")
        self.ids.add(action_id)
        self.pending = action_id
        self.release_required = True
        return self.phase

    def _context(self, identity, owner, now_ms):
        require(type(now_ms) is int and now_ms >= self.last_ms, "clock_regressed")
        self.last_ms = now_ms
        if identity != self.identity or owner != self.owner or now_ms >= self.deadline:
            self.stop("context_or_deadline_changed")
            raise Stopped(self.stopped)

    def confirm(self, action_id, identity, owner, now_ms, evidence):
        self._context(identity, owner, now_ms)
        require(self.stopped is None and action_id == self.pending and self.pending is not None,
                "unbound_confirmation")
        require(type(evidence) is dict and evidence.get("fresh") is True, "fresh_observation_required")
        step = self.phase
        if step in ("place", "replace"):
            require(evidence.get("position") == self.position and evidence.get("shulker_block") is True,
                    "placed_block_not_verified")
        elif step in ("open", "reopen"):
            require(evidence.get("menu_class") == "net.minecraft.world.inventory.ShulkerBoxMenu"
                    and type(evidence.get("menu_id")) is int and evidence["menu_id"] > 0
                    and evidence.get("position") == self.position and evidence.get("cursor_empty") is True,
                    "shulker_menu_not_bound")
            require(cargo_slots(evidence.get("slots")) == (self.before if step == "open" else self.after),
                    "opened_contents_mismatch")
            self.menu_id = evidence["menu_id"]
            if step == "open":
                self.initial_inventory = inventory_slots(evidence.get("player_inventory"))
        elif step in ("transfer", "verify"):
            require(evidence.get("menu_id") == self.menu_id and evidence.get("cursor_empty") is True,
                    "menu_changed_or_cursor_not_empty")
            require(cargo_slots(evidence.get("slots")) == self.after, "contents_mismatch")
            if step == "transfer":
                observed_inventory = inventory_slots(evidence.get("player_inventory"))
                require(totals(observed_inventory + self.after) == totals(self.initial_inventory + self.before),
                        "inventory_conservation_failed")
        elif step == "close":
            require(evidence.get("screen_closed") is True and evidence.get("cursor_empty") is True,
                    "close_not_observed")
            self.menu_id = None
        elif step == "break":
            require(evidence.get("position") == self.position and evidence.get("block_absent") is True,
                    "block_absence_not_observed")
        elif step == "pickup":
            require(type(evidence.get("new_matching_boxes")) is int and evidence["new_matching_boxes"] == 1
                    and evidence.get("identity_complete") is True,
                    "pickup_identity_ambiguous")
            require(cargo_slots(evidence.get("slots")) == self.after, "recovered_contents_mismatch")
        self.pending = None
        self.index += 1
        self.release_required = False
        return self.phase

    def stop(self, reason):
        if self.stopped is None:
            self.stopped = "uncertain:" + reason if self.pending is not None else "stopped:" + reason
            self.release_required = True


class OneShotRegistry:
    """Session-scoped bounded tombstones; exhausted registries reject, never evict."""
    def __init__(self, identity, owner):
        require(isinstance(identity, Identity) and type(owner) is str and 0 < len(owner) <= 128,
                "invalid_registry_identity")
        self.identity, self.owner = identity, owner
        self.entries = {}

    def begin(self, intent, now_ms, verifier=None):
        require(intent.identity == self.identity and intent.owner == self.owner, "registry_identity_changed")
        old = self.entries.get(intent.action_id)
        if old is not None:
            require(old.intent == intent, "action_id_payload_mismatch")
            return old
        require(len(self.entries) < 1024, "registry_capacity_reached")
        require(not any(entry.phase == "uncertain" or entry.release_required for entry in self.entries.values()),
                "reconciliation_required")
        require(not any(entry.phase in ("prepared", "observing") for entry in self.entries.values()),
                "single_controller_busy")
        action = OneShotPearl(intent, now_ms, verifier)
        self.entries[intent.action_id] = action
        return action
