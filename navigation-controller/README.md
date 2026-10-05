# External local navigation controller (experimental)

A Python standard-library, source-only companion to the thin MineClient Bridge
terrain extension. Planning and navigation policy run outside Minecraft.

**No live movement transport exists. The executor is disabled by default and only
accepts the offline simulation adapter contract.** Running the demo cannot connect
to Minecraft, discover credentials, or move a player. Fake tests are not live
navigation acceptance or a Minecraft physics simulation.

## Run offline

Python 3.10 or later; no installation or third-party dependencies:

```sh
python -m unittest discover -v
python -m navigation_controller
```

The demonstration plans around a block obstacle, follows the resulting route in a
small deterministic fake, and prints its path, pulse count and release outcome.
Every movement pulse is at most 100 ms and is followed by release and observation.

## Implemented

- Actual `mineclient-bridge` protocol schema 2 and terrain schema 1 ingestion
- Bounded, ordered paging with a fixed scan generation/origin/bounds, exact cell
  coverage, world generation, monotonic tick and wall-clock freshness checks
- Read-only collection through explicitly supplied callbacks; 50 ms page spacing,
  finite scan/page budgets and no automatic HTTP retries or transport implementation
- A* over known loaded support and headroom, with expansion/frontier/time/path budgets
- Flat cardinal and diagonal walking, with both corner columns checked for diagonals
- One-block cardinal descent planning with swept headroom at the original height;
  descent execution is deferred pending falling/landing acceptance
- Explicit unknown/unloaded/failed/malformed cell blocking; no chunk-load assumptions
- Full cube floor support and a small vanilla block allowlist; empty hazard tags alone
  never establish safety; fluid, damage, slowdown and truncated facts are blocked
- Default-disabled, fake-only execution, finite pulses, fresh local terrain checks,
  post-look and post-pulse observation, progress budgets and emergency release
- World/player changes, damage, stale reads, active effects, nearby entities, open UI,
  held input, uncertain standing height and unexpected movement stop execution

No jumping, upward full-block steps, sprinting, swimming, block breaking/placing,
Nether routing, entity avoidance or arbitrary modded-block support is implemented.
The planner targets an exact integer feet block inside its observed cuboid. It does
not extrapolate a route through an unseen chunk or provide global navigation.

## Code map

- `terrain.py`: strict schema parser, immutable grid and page assembler
- `reader.py`: optional paced, read-only page orchestration over caller-supplied functions
- `planner.py`: conservative graph and bounded A* with cost/depth labels
- `observation.py`: actual status/state parsing and safe observation gates
- `executor.py`: fake-only finite-pulse navigation state machine
- `fake.py`: deterministic terrain and movement fixtures; not game physics
- `tests/`: positive paths and failure-mode regression tests

Read [protocol and evidence rules](docs/PROTOCOL.md) and the
[live acceptance boundary](docs/ACCEPTANCE.md) before implementing any adapter.

## Status

Source and offline checks only. The included test suite passes, including flat
paths, obstacle detours, diagonals/corners, ledges, unknown/no-path terrain,
generation resets, stale snapshots, finite budgets and emergency-release behavior.
No live navigation endpoint has been called or accepted by this implementation.

A sanitized actual-game terrain fixture also passes offline parser/planner
regressions: one-cell, 27-cell cube, seven-page equivalent and world-height boundary.
This establishes wire-format compatibility; it does not enable live movement.
