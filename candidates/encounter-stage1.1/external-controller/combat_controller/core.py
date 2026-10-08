"""Stationary, bounded combat policy. No Minecraft/network dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import time
from typing import Protocol

# Deliberately excludes players, tameable mobs, villagers, neutral mobs and bosses.
HOSTILE_TYPES = frozenset({
    'minecraft:zombie', 'minecraft:husk', 'minecraft:drowned',
    'minecraft:skeleton', 'minecraft:stray', 'minecraft:bogged',
})
DANGEROUS_NEARBY = {
    'minecraft:creeper': 6.0, 'minecraft:warden': 16.0, 'minecraft:wither': 16.0,
    'minecraft:ender_dragon': 16.0, 'minecraft:ghast': 16.0, 'minecraft:blaze': 8.0,
    'minecraft:witch': 8.0, 'minecraft:ravager': 8.0,
}
WEAPONS = frozenset('minecraft:' + material + '_' + tool
                    for material in ('wooden', 'stone', 'iron', 'golden', 'diamond', 'netherite')
                    for tool in ('axe',))


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def distance(self, other: Vec3) -> float:
        return math.dist((self.x, self.y, self.z), (other.x, other.y, other.z))

    def finite(self) -> bool:
        return all(math.isfinite(x) for x in (self.x, self.y, self.z))


@dataclass(frozen=True)
class Entity:
    uuid: str
    kind: str
    position: Vec3
    alive: bool = True
    health: float | None = None


@dataclass(frozen=True)
class Snapshot:
    # captured_at is local monotonic request START, never server wall time.
    captured_at: float
    identity: tuple[str, int, str, str]  # run_id, PID, player UUID, dimension
    generation: str | None            # ClientLevel lifetime; not scan generation
    tick: int
    position: Vec3
    velocity: Vec3
    yaw: float
    pitch: float
    health: float
    food: int
    air: int
    max_air: int
    on_ground: bool
    gamemode: str
    weapon: str
    entities: tuple[Entity, ...]
    crosshair_uuid: str | None = None
    crosshair_kind: str | None = None
    crosshair_location: Vec3 | None = None
    screen_open: bool = False
    mouse_grabbed: bool = True
    held_inputs: bool = False
    entities_truncated: bool = False
    terrain_safe: bool = False
    terrain_reason: str = 'terrain_unknown'


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class ActionContext:
    snapshot: Snapshot
    target: Entity
    deadline: float  # Local monotonic latest admission, not a server clock.


class Bridge(Protocol):
    def observe(self) -> Snapshot: ...
    def look(self, yaw: float, pitch: float, context: ActionContext) -> None: ...
    def attack(self, context: ActionContext) -> None: ...
    def release_all(self) -> bool: ...


class RealClock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    allowed_types: frozenset[str] = HOSTILE_TYPES
    session_seconds: float = 10.0
    action_budget: int = 12
    attack_interval: float = 1.5
    request_timeout: float = 0.4
    max_snapshot_age: float = 0.75
    heartbeat_lease: float = 1.0
    poll_seconds: float = 0.1
    attack_range: float = 2.75
    min_health: float = 14.0
    min_food: int = 12
    max_yaw_step: float = 20.0
    max_pitch_step: float = 12.0
    max_displacement: float = 0.35

    def __post_init__(self) -> None:
        # A frozen dataclass does not freeze a caller-supplied mutable set.
        object.__setattr__(self, 'allowed_types', frozenset(self.allowed_types))
        numeric = (self.session_seconds, self.attack_interval, self.request_timeout,
                   self.max_snapshot_age, self.heartbeat_lease, self.poll_seconds,
                   self.attack_range, self.min_health, self.max_yaw_step,
                   self.max_pitch_step, self.max_displacement)
        if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
               for x in numeric):
            raise ValueError('configuration must contain finite numbers')
        checks = (
            type(self.enabled) is bool,
            bool(self.allowed_types) and self.allowed_types <= HOSTILE_TYPES,
            0 < self.session_seconds <= 30, type(self.action_budget) is int and 1 <= self.action_budget <= 40,
            1.25 <= self.attack_interval <= 10, 0.05 <= self.request_timeout <= 1,
            0.1 <= self.max_snapshot_age <= 1, self.max_snapshot_age <= self.heartbeat_lease <= 2,
            0.05 <= self.poll_seconds <= 0.25, 0 < self.attack_range <= 2.75,
            14 <= self.min_health <= 20, type(self.min_food) is int and 12 <= self.min_food <= 20,
            0 < self.max_yaw_step <= 30, 0 < self.max_pitch_step <= 20,
            0 < self.max_displacement <= 0.5,
        )
        if not all(checks):
            raise ValueError('unsafe configuration')


class Phase(str, Enum):
    DISABLED = 'disabled'
    OBSERVE = 'observe'
    ACQUIRE = 'acquire'
    AIM = 'aim'
    WAIT = 'wait'
    ATTACK = 'attack'
    HALTED = 'halted'


@dataclass(frozen=True)
class Event:
    phase: Phase
    reason: str
    elapsed: float
    target_uuid: str | None = None


@dataclass
class Result:
    reason: str = 'not_started'
    actions: int = 0
    attacks: int = 0
    release_confirmed: bool = False
    events: list[Event] = field(default_factory=list)


def wrap_yaw(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


def bounded_aim(snapshot: Snapshot, target: Entity, config: Config) -> tuple[float, float]:
    # Only upright, grounded, stationary sessions are accepted. Feet-to-torso aim
    # is an estimate; the following fresh crosshair snapshot is authoritative.
    dx = target.position.x - snapshot.position.x
    dz = target.position.z - snapshot.position.z
    dy = target.position.y + 0.9 - (snapshot.position.y + 1.62)
    wanted_yaw = math.degrees(math.atan2(-dx, dz))
    wanted_pitch = -math.degrees(math.atan2(dy, math.hypot(dx, dz)))
    yaw_delta = max(-config.max_yaw_step, min(config.max_yaw_step, wrap_yaw(wanted_yaw - snapshot.yaw)))
    pitch_delta = max(-config.max_pitch_step, min(config.max_pitch_step, wanted_pitch - snapshot.pitch))
    return wrap_yaw(snapshot.yaw + yaw_delta), max(-90.0, min(90.0, snapshot.pitch + pitch_delta))


class Controller:
    """One bounded session. Instances cannot be restarted or silently re-armed."""

    def __init__(self, bridge: Bridge, config: Config | None = None, clock: Clock | None = None):
        self.bridge = bridge
        self.config = config or Config()
        self.clock = clock or RealClock()
        self._used = False
        self._stop_requested = False

    def stop(self) -> None:
        """Cooperative stop. An in-flight request remains bounded by its timeout."""
        self._stop_requested = True

    def run(self) -> Result:
        if self._used:
            raise RuntimeError('create a new controller for an explicitly armed session')
        self._used = True
        c = self.config
        r = Result()
        start = self.clock.monotonic()
        last_fresh_tick_at = start
        last_tick = None
        last_action_tick = None
        last_attack_at = start - c.attack_interval
        baseline = None
        target_uuid = None

        def event(phase: Phase, reason: str, target: str | None = None) -> None:
            # Suppress identical waiting messages and keep bounded session records.
            if not r.events or (r.events[-1].phase, r.events[-1].reason, r.events[-1].target_uuid) != (phase, reason, target):
                r.events.append(Event(phase, reason, self.clock.monotonic() - start, target))

        def halt(reason: str) -> None:
            r.reason = reason
            event(Phase.HALTED, reason, target_uuid)

        def boundary() -> str | None:
            now = self.clock.monotonic()
            if self._stop_requested:
                return 'stop_requested'
            if now - start >= c.session_seconds:
                return 'session_deadline'
            if r.actions >= c.action_budget:
                return 'action_budget'
            if now - last_fresh_tick_at >= c.heartbeat_lease:
                return 'heartbeat_expired'
            return None

        if not c.enabled:
            r.reason = 'disabled'
            event(Phase.DISABLED, 'explicit_enable_required')
            return r  # No reads, credential loading, input or release calls.

        try:
            event(Phase.OBSERVE, 'session_started')
            while True:
                if reason := boundary():
                    halt(reason)
                    break
                s = self.bridge.observe()
                if reason := boundary():
                    halt(reason)
                    break
                reason = self._unsafe(s, baseline, self.clock.monotonic())
                if reason:
                    halt(reason)
                    break
                if baseline is None:
                    baseline = s
                if last_tick is not None and s.tick < last_tick:
                    halt('world_time_reversed')
                    break
                if last_tick is None or s.tick > last_tick:
                    last_fresh_tick_at = self.clock.monotonic()
                last_tick = s.tick

                candidates = [e for e in s.entities if e.alive and e.health is not None and e.health > 0
                              and e.kind in c.allowed_types and e.kind in HOSTILE_TYPES
                              and s.position.distance(e.position) <= c.attack_range]
                target = next((e for e in candidates if e.uuid == target_uuid), None)
                if target is None and candidates:
                    target = min(candidates, key=lambda e: (s.position.distance(e.position), e.uuid))
                    target_uuid = target.uuid
                    event(Phase.ACQUIRE, 'allowed_hostile_in_range', target_uuid)
                if target is None:
                    target_uuid = None
                    event(Phase.OBSERVE, 'no_allowed_hostile_in_range')
                    self.clock.sleep(c.poll_seconds)
                    continue

                # Target races and collateral effects can injure other entities. Refuse
                # mixed groups near the target, not merely a protected crosshair.
                protected = [e for e in s.entities if e.alive
                             and e.kind not in c.allowed_types
                             and (e.position.distance(target.position) <= 3.0
                                  or e.position.distance(s.position) <= 4.5)]
                if protected:
                    halt('protected_or_unknown_entity_nearby')
                    break
                if last_action_tick is not None and s.tick <= last_action_tick:
                    event(Phase.WAIT, 'await_new_tick_after_input', target_uuid)
                elif (s.crosshair_uuid == target.uuid and s.crosshair_kind == target.kind
                      and s.crosshair_location is not None):
                    # The Bridge's crosshair.distance is squared; never use it.
                    # Use feet-to-hit as a stricter-than-eye conservative guard.
                    if s.position.distance(s.crosshair_location) > c.attack_range:
                        event(Phase.WAIT, 'crosshair_outside_conservative_range', target_uuid)
                    elif self.clock.monotonic() - last_attack_at < c.attack_interval:
                        event(Phase.WAIT, 'conservative_cadence', target_uuid)
                    else:
                        if reason := boundary():
                            halt(reason)
                            break
                        if self.clock.monotonic() - s.captured_at > c.max_snapshot_age:
                            halt('stale_snapshot')
                            break
                        r.actions += 1  # Count attempts, including uncertain delivery.
                        r.attacks += 1
                        self.bridge.attack(ActionContext(s, target, min(start + c.session_seconds,
                                                                       s.captured_at + c.max_snapshot_age)))
                        last_action_tick = s.tick
                        last_attack_at = self.clock.monotonic()
                        event(Phase.ATTACK, 'guarded_attack_requested_damage_unverified', target_uuid)
                else:
                    yaw, pitch = bounded_aim(s, target, c)
                    if reason := boundary():
                        halt(reason)
                        break
                    if self.clock.monotonic() - s.captured_at > c.max_snapshot_age:
                        halt('stale_snapshot')
                        break
                    r.actions += 1
                    self.bridge.look(yaw, pitch, ActionContext(s, target, min(start + c.session_seconds,
                                                                           s.captured_at + c.max_snapshot_age)))
                    last_action_tick = s.tick
                    event(Phase.AIM, 'bounded_look_await_fresh_crosshair', target_uuid)
                self.clock.sleep(c.poll_seconds)
        except Exception:
            # Never include transport exceptions, response bodies or credentials.
            halt('observation_or_input_failed')
        finally:
            try:
                r.release_confirmed = self.bridge.release_all() is True
            except Exception:
                r.release_confirmed = False
        return r

    def _unsafe(self, s: Snapshot, baseline: Snapshot | None, now: float) -> str | None:
        c = self.config
        scalars = (s.captured_at, s.yaw, s.pitch, s.health, s.food, s.air, s.max_air)
        if (not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in scalars)
                or not s.position.finite() or not s.velocity.finite()
                or not isinstance(s.tick, int) or s.tick < 0
                or not all(e.position.finite() and (e.health is None or math.isfinite(e.health)) for e in s.entities)
                or (s.crosshair_location is not None and not s.crosshair_location.finite())):
            return 'malformed_snapshot'
        if now < s.captured_at or now - s.captured_at > c.max_snapshot_age:
            return 'stale_snapshot'
        if not s.generation:
            return 'world_generation_unknown'
        if baseline and (s.identity != baseline.identity or s.generation != baseline.generation):
            return 'world_identity_changed'
        if s.gamemode != 'survival':
            return 'not_survival'
        if s.screen_open or not s.mouse_grabbed:
            return 'screen_or_mouse_not_ready'
        if s.held_inputs:
            return 'unexpected_held_input'
        if s.health < c.min_health:
            return 'low_health'
        if baseline and baseline.health - s.health >= 2.0:
            return 'damage_received'
        if s.food < c.min_food:
            return 'low_food'
        if s.air < s.max_air or s.max_air <= 0:
            return 'air_not_full'
        if not s.on_ground or s.velocity.distance(Vec3(0, 0, 0)) > 0.1:
            return 'not_grounded_and_stationary'
        if baseline and s.position.distance(baseline.position) > c.max_displacement:
            return 'unexpected_displacement'
        if any(e.alive and e.kind in DANGEROUS_NEARBY
               and e.position.distance(s.position) <= DANGEROUS_NEARBY[e.kind] for e in s.entities):
            return 'dangerous_mob_nearby'
        if s.entities_truncated:
            return 'entity_observation_truncated'
        if not s.terrain_safe:
            return s.terrain_reason
        if s.weapon not in WEAPONS:
            return 'weapon_not_allowed'
        if len({e.uuid for e in s.entities}) != len(s.entities):
            return 'duplicate_entity_identity'
        return None
