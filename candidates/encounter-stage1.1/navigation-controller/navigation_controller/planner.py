"""Bounded local A*: flat walking and optionally a single-block step down."""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import itertools
import math
import time
from .terrain import Block, TerrainGrid, TerrainError, WorldStamp, integer, number


@dataclass(frozen=True)
class PlanConfig:
    diagonals: bool = True
    step_down: bool = True
    max_expansions: int = 2048
    max_frontier: int = 4096
    max_path_steps: int = 128
    max_seconds: float = 0.1

    def __post_init__(self):
        if type(self.diagonals) is not bool or type(self.step_down) is not bool:
            raise ValueError('invalid_policy')
        integer(self.max_expansions, 1, 18_513)
        integer(self.max_frontier, 1, 37_026)
        integer(self.max_path_steps, 1, 512)
        if not 0 < number(self.max_seconds) <= 2:
            raise ValueError('invalid_time_budget')


@dataclass(frozen=True)
class Route:
    nodes: tuple[Block, ...]
    world: WorldStamp
    scan_generation: str
    cost: float
    expansions: int


@dataclass(frozen=True)
class PlanResult:
    reason: str
    route: Route | None = None
    expansions: int = 0


def safe_edge(grid, source, target, diagonals=True, step_down=True):
    """Require full swept headroom; diagonal corner columns must also be safe.

    Full block ascent needs a jump and is intentionally unsupported. Descent is
    cardinal only and at most one block, with clear space at the OLD head height.
    """
    if not grid.standable(source) or not grid.standable(target):
        return False
    dx, dy, dz = target.x - source.x, target.y - source.y, target.z - source.z
    if max(abs(dx), abs(dz)) != 1 or dy not in (0, -1):
        return False
    diagonal = bool(dx and dz)
    if diagonal:
        return (diagonals and dy == 0
                and grid.standable(source.offset(x=dx))
                and grid.standable(source.offset(z=dz)))
    if dy == -1:
        return step_down and grid.clear(target.offset(y=2))
    return True


def neighbors(grid, pos, config):
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
        diagonal = bool(dx and dz)
        if diagonal and not config.diagonals:
            continue
        target = pos.offset(x=dx, z=dz)
        if safe_edge(grid, pos, target, config.diagonals, config.step_down):
            yield target, math.sqrt(2) if diagonal else 1.0
        elif not diagonal and config.step_down:
            lower = target.offset(y=-1)
            if safe_edge(grid, pos, lower, config.diagonals, config.step_down):
                yield lower, 1.25


def heuristic(a, b):
    # Admissible for 8-neighbor walking; ignoring Y underestimates descent cost.
    dx, dz = abs(a.x - b.x), abs(a.z - b.z)
    return max(dx, dz) + (math.sqrt(2) - 1) * min(dx, dz)


def plan(grid: TerrainGrid, start: Block, target: Block, current: WorldStamp,
         now: float, config: PlanConfig | None = None, clock=time.monotonic):
    config = config or PlanConfig()
    try:
        grid.require_fresh(current, now)
    except TerrainError as exc:
        return PlanResult(str(exc))
    if not grid.contains(start) or not grid.contains(target):
        return PlanResult('target_or_start_out_of_bounds')
    if not grid.standable(start):
        return PlanResult('start_not_supported_or_unknown')
    if not grid.standable(target):
        return PlanResult('target_not_supported_or_unknown')
    if target.y > start.y:
        return PlanResult('jump_required_unsupported')
    started = number(clock())
    serial = itertools.count()
    initial = (start, 0)
    frontier = [(heuristic(start, target), next(serial), initial, 0.0)]
    costs, previous = {initial: 0.0}, {}
    # A cheaper route can use MORE edges. Preserve nondominated cost/depth
    # labels so the finite path-length budget does not discard a valid detour.
    labels = {start: {0: 0.0}}
    expansions = 0
    while frontier:
        elapsed = number(clock()) - started
        if elapsed < 0 or elapsed >= config.max_seconds:
            return PlanResult('time_budget_exhausted', expansions=expansions)
        _, _, state, cost = heapq.heappop(frontier)
        if cost != costs.get(state):
            continue
        node, depth = state
        if node == target:
            path = [node]
            while state in previous:
                state = previous[state]
                path.append(state[0])
            path.reverse()
            return PlanResult('path_found', Route(tuple(path), current, grid.scan_generation, cost, expansions), expansions)
        if expansions >= config.max_expansions:
            return PlanResult('expansion_budget_exhausted', expansions=expansions)
        expansions += 1
        if depth >= config.max_path_steps:
            continue
        for candidate, weight in neighbors(grid, node, config):
            new_depth, new_cost = depth + 1, cost + weight
            remaining_edges = max(abs(candidate.x - target.x), abs(candidate.z - target.z))
            if new_depth + remaining_edges > config.max_path_steps:
                continue
            existing = labels.setdefault(candidate, {})
            if any(d <= new_depth and c <= new_cost for d, c in existing.items()):
                continue
            if len(frontier) >= config.max_frontier:
                return PlanResult('frontier_budget_exhausted', expansions=expansions)
            for d, c in tuple(existing.items()):
                if d >= new_depth and c >= new_cost:
                    del existing[d]
                    costs.pop((candidate, d), None)
            child = (candidate, new_depth)
            existing[new_depth] = new_cost
            costs[child] = new_cost
            previous[child] = state
            heapq.heappush(frontier, (new_cost + heuristic(candidate, target), next(serial), child, new_cost))
    return PlanResult('no_path_within_budget', expansions=expansions)
