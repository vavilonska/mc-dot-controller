# External local navigation controller (experimental)

A Python standard-library, source-only companion to the thin MineClient Bridge
terrain extension. Planning and navigation policy run outside Minecraft.

**All action paths are disabled by default.** An optional explicit loopback HTTP
transport and owner-run acceptance CLI are now available as source, but have not
been connected to a game in this implementation task. The demos remain offline
and cannot discover credentials or move a real player. Mock tests are not live
navigation acceptance or a Minecraft physics simulation.

## Run offline

Python 3.10 or later; no installation or third-party dependencies:

```sh
python -m unittest discover -v
python -m navigation_controller
python -m navigation_controller.sample_demo
```

The demonstration plans around a block obstacle, follows the resulting route in a
small deterministic fake, and prints its path, pulse count and release outcome.
This original demonstration uses an abstract duration-based fake, with pulses at
most 100 ms followed by release and observation.

The separate `sample_demo` uses the companion guarded movement/turn wire contract:
one half-forward input sample per action, fresh observation challenges, bounded
yaw steps and settling readback. Its 100 ms value is an admission lease, never a
travel duration or a displacement guarantee. The two fake models are distinct.

## Implemented

- Actual `mineclient-bridge` protocol schema 2 and terrain schema 1 ingestion
- Bounded, ordered paging with a fixed scan generation/origin/bounds, exact cell
  coverage, world generation, monotonic tick and wall-clock freshness checks
- Read-only collection through explicitly supplied callbacks; 50 ms page spacing,
  finite scan/page budgets and no automatic HTTP retries; the collector is separate
  from the optional explicit HTTP transport
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
- `fake.py`: deterministic terrain and original duration-based fixtures; not game physics
- `sample_adapter.py`: guarded one-sample/turn contract with dual live-acceptance gates
- `sample_fake.py`, `sample_demo.py`: wire-shaped fake and separate one-sample demonstration
- `http_transport.py`: explicit numeric-loopback HTTP, strict schemas, auth and response budgets
- `live_probe.py`: owner-run read-only report or exactly one explicitly approved local action
- `tests/`: positive paths and failure-mode regression tests

Read [protocol and evidence rules](docs/PROTOCOL.md), the
[one-sample adapter contract](docs/ONE_SAMPLE_ADAPTER.md), and the
[live acceptance boundary](docs/ACCEPTANCE.md). The
[owner-run probe guide](docs/OWNER_PROBE.md) explains prerequisites and commands;
reading it does not authorize a game action.

## Status

Source and offline checks only. The included test suite passes, including flat
paths, obstacle detours, diagonals/corners, ledges, unknown/no-path terrain,
generation resets, stale snapshots, finite budgets and emergency-release behavior.
No live navigation endpoint has been called or accepted by this implementation.

A sanitized actual-game terrain fixture also passes offline parser/planner
regressions: one-cell, 27-cell cube, seven-page equivalent and world-height boundary.
This establishes wire-format compatibility; it does not enable live movement.
