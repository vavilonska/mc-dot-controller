"""Finite fake-only movement controller. No HTTP implementation exists here.

A future game adapter must implement execution-time world/player/position guards,
expiry and independently enforced key release, then pass explicit game acceptance.
The existing guarded look/attack endpoint cannot provide guarded walking.
"""
from dataclasses import dataclass
import math
from typing import Protocol
from .observation import Observation, Position
from .planner import Route, safe_edge
from .terrain import TerrainError, integer, number


class Clock(Protocol):
    def monotonic(self) -> float: ...


class SimulationAdapter(Protocol):
    simulation_only: bool
    def observe(self) -> Observation: ...
    def look(self, yaw: float, expected: Observation) -> None: ...
    def pulse_forward(self, duration_ms: int, expected: Observation) -> None: ...
    def release_all(self) -> bool: ...


@dataclass(frozen=True)
class ExecutorConfig:
    enabled: bool = False
    pulse_ms: int = 100
    max_pulses: int = 64
    max_seconds: float = 20.0
    max_stalled_pulses: int = 3

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('invalid_enabled_flag')
        integer(self.pulse_ms, 1, 100)
        integer(self.max_pulses, 1, 512)
        integer(self.max_stalled_pulses, 1, 10)
        if not 0 < number(self.max_seconds) <= 60:
            raise ValueError('invalid_execution_duration')


@dataclass(frozen=True)
class ExecutionResult:
    reason: str
    pulses: int = 0
    reached_waypoints: int = 0
    released: bool = True


def wrap_yaw(yaw):
    return (yaw + 180) % 360 - 180


class Navigator:
    def __init__(self, adapter: SimulationAdapter, clock: Clock, config=None):
        self.adapter = adapter
        self.clock = clock
        self.config = config or ExecutorConfig()
        self._busy = False

    def run(self, route: Route):
        if not self.config.enabled:
            return ExecutionResult('executor_disabled')
        if getattr(self.adapter, 'simulation_only', None) is not True:
            return ExecutionResult('live_movement_not_implemented')
        if self._busy:
            return ExecutionResult('executor_already_running')
        self._busy = True
        pulses, reached, reason, released = 0, 0, 'stopped', True
        try:
            if not route.nodes or len(route.nodes) > 129:
                raise TerrainError('invalid_route')
            # A planned drop still needs falling/landing physics acceptance.
            if any(a.y != b.y for a, b in zip(route.nodes, route.nodes[1:])):
                raise TerrainError('step_down_execution_deferred')
            started = number(self.clock.monotonic())
            obs = self.adapter.observe()
            identity = obs.identity
            initial_health = obs.health
            if obs.position.block() != route.nodes[0]:
                raise TerrainError('route_start_mismatch')
            stalled = 0
            for index, destination in enumerate(route.nodes):
                source = route.nodes[max(0, index - 1)]
                while True:
                    now = number(self.clock.monotonic())
                    if not 0 <= now - started < self.config.max_seconds:
                        raise TerrainError('execution_time_budget')
                    obs.require_safe(now)
                    if obs.identity != identity or not route.world.same_world(obs.world):
                        raise TerrainError('world_or_player_changed')
                    if obs.health < initial_health:
                        raise TerrainError('damage_observed')
                    if source != destination and not safe_edge(obs.terrain, source, destination):
                        raise TerrainError('route_edge_became_unsafe')
                    if not in_corridor(obs.position, source, destination):
                        raise TerrainError('position_left_route_corridor')
                    goal = Position(destination.x + 0.5, destination.y, destination.z + 0.5)
                    distance = obs.position.distance(goal)
                    if distance <= 0.12:
                        reached += 1
                        break
                    if pulses >= self.config.max_pulses:
                        raise TerrainError('pulse_budget_exhausted')
                    desired_yaw = math.degrees(math.atan2(-(goal.x - obs.position.x), goal.z - obs.position.z))
                    # Align view with no held movement; re-observe after the look.
                    self.adapter.look(wrap_yaw(desired_yaw), obs)
                    looked = self.adapter.observe()
                    looked.require_safe(self.clock.monotonic())
                    if (looked.identity != identity or looked.world.tick < obs.world.tick
                            or looked.position.distance(obs.position) > 0.01
                            or looked.health < initial_health
                            or abs(wrap_yaw(looked.yaw - desired_yaw)) > 0.1):
                        raise TerrainError('state_changed_after_look')
                    if source != destination and not safe_edge(looked.terrain, source, destination):
                        raise TerrainError('route_edge_became_unsafe')
                    # Stop short enough for a fresh observation; never sprint/jump.
                    duration = min(self.config.pulse_ms, max(1, int(distance / 4.5 * 1000)))
                    remaining_ms = int((started + self.config.max_seconds - number(self.clock.monotonic())) * 1000)
                    if remaining_ms < duration:
                        raise TerrainError('execution_time_budget')
                    before = looked
                    pulses += 1
                    try:
                        self.adapter.pulse_forward(duration, before)
                    finally:
                        if self.adapter.release_all() is not True:
                            released = False
                            raise TerrainError('emergency_release_failed')
                    obs = self.adapter.observe()  # Mandatory after every finite pulse.
                    if obs.world.tick < before.world.tick:
                        raise TerrainError('observation_tick_reversed')
                    moved = obs.position.distance(before.position)
                    if moved > 0.55:
                        raise TerrainError('unexpected_displacement')
                    remaining = obs.position.distance(goal)
                    if remaining > distance + 0.03:
                        raise TerrainError('moving_away_from_waypoint')
                    stalled = stalled + 1 if distance - remaining < 0.01 else 0
                    if stalled >= self.config.max_stalled_pulses:
                        raise TerrainError('movement_stalled')
            reason = 'arrived'
        except Exception as exc:
            # Never publish arbitrary adapter errors or retry ambiguous actions.
            reason = str(exc) if isinstance(exc, TerrainError) else 'adapter_failure'
        finally:
            try:
                released = self.adapter.release_all() is True and released
            except Exception:
                released = False
            self._busy = False
        if not released:
            reason = 'emergency_release_failed'
        return ExecutionResult(reason, pulses, reached, released)


def in_corridor(position, source, target):
    """Stay near the center-to-center segment; 0.6-wide player keeps margin."""
    if abs(position.y - source.y) > 0.03:
        return False
    sx, sz, tx, tz = source.x + 0.5, source.z + 0.5, target.x + 0.5, target.z + 0.5
    dx, dz = tx - sx, tz - sz
    if not dx and not dz:
        return abs(position.x - sx) <= 0.19 and abs(position.z - sz) <= 0.19
    projection = ((position.x - sx) * dx + (position.z - sz) * dz) / (dx * dx + dz * dz)
    nearest = max(0, min(1, projection))
    return (-0.12 <= projection <= 1.12
            and math.hypot(position.x - (sx + nearest * dx), position.z - (sz + nearest * dz)) <= 0.19)
