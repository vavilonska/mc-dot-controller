# Persistent local route cursor, v6 continuity candidate

This module retains a complete local route and its next-waypoint cursor across
execution slices. The frozen v6 source is built and checked offline, not
live-accepted; publication does not establish installation. Adaptive execution
now uses the longest currently observed safe prefix, up to 32 waypoints.
It addresses an outer-loop failure in which selecting a
new destination after every two waypoints discarded the remaining route and could
oscillate when a valid detour began by moving away from the destination.

Dispatching a slice never advances the cursor. A fresh grounded player position
must establish arrival. Local destinations change after the current leg completes,
terrain changes, a bounded failed-edge alternative is needed, or combat interrupts
the task. Combat requires fresh observation and replanning toward the retained
leg destination when it remains reachable. Failed directed edges are excluded;
an RPC success without observed waypoint progress is treated as no progress.

## Integration

Use the watchdog's verified `IntentClient`. The watchdog remains the single
resident-queue writer and owns defense and cancellation. This helper rejects a
direct resident `QueueClient` and requires the atomic `defense_epoch` contract
introduced in watchdog v3. The accepted implementation labels are v2, v3 and v5;
the label alone is insufficient without that contract. The v6 watchdog retains
`native-defense-watchdog-v5` for compatibility and separately reports its v6
revision. Ground-anchor-v3 geometry and checkpoint schema 2 are retained.

```python
from navigation_cursor import Navigator

nav = Navigator(existing_intent_client, '/path/to/private/route-checkpoint.json')
status = nav.tick((12, 8))  # Synthetic X/Z example; use observed terrain height.
# nav.tick((12, 64, 8)) is an exact X/Y/Z goal when Y is known.
```

Call `tick` with the same target until `complete` or `blocked`. `pending` means
poll the retained intent ID. `waiting` means defense, an open screen, falling, or
unavailable support must resolve before a fresh observation. Address the explicit
reason for a `blocked` result. Do not delete the checkpoint to bypass a pending or
uncertain action. Before choosing another goal and checkpoint, establish that the
old intent is terminal. Reusing a checkpoint resumes its cursor and exact pending
ID after a caller restart; changed watchdog or world sessions block replay.

The optional command-line loader requires explicit paths and a target:

```sh
python navigate.py --adapter-dir /path/to/verified/watchdog/source \
  --gateway /path/to/watchdog/control --checkpoint /path/to/private/route.json \
  --target 12 64 8 --radius 4
```

`slice_size=None` and the omitted CLI `--slice-size` select adaptive execution.
An explicit integer 1–32 retains fixed-size behavior; `--slice-size 2` restores
the earlier two-waypoint limit. The timeout grows with longer slices while the
watchdog retains defense preemption.

These are placeholder paths and synthetic coordinates. Running the loader can
submit game actions through the configured watchdog; it is not an offline demo.
Exit codes are 0 for observed arrival, 2 for blocked, and 3 for a paused or stopped
watchdog. It never rearms or restarts a service. If interrupted, the current
slice may remain running under watchdog ownership; resolve its saved intent ID.
Treat checkpoints as private because they contain goal and route coordinates,
session identities and request IDs.

## Ground-anchor-v3 edge stance

A grounded player whose center floors into air may still overlap observed full
support. The helper uses the observed player bounding box, or the standard body
width only when observed eye height identifies an ordinary standing/crouching
pose. It verifies support height and the complete swept body volume before one
short normalization step to an observed support center. Unknown poses, partial
support, missing geometry, fluids and hazards cannot authorize this step.

Normalization keeps the goal and route tail. It preserves the original pending
ID across helper reloads, requires a later grounded observation and does not
consume a failed-edge replan merely for relocalizing. A previous real failed
navigation edge remains failed; normalization cannot erase its evidence.

## Route and terrain limits

- Cardinal walking, adjacent up-steps and controlled 1–5 block drops use observed
  collision facts. Full-top-support leaves are allowed; unknown terrain, fluids
  and hazards are rejected
- Adaptive slices stop before an unknown or changed later edge without deleting
  the unexecuted tail; an invalid immediate next edge still uses bounded replanning
- Slice dispatch and action completion do not themselves advance the route cursor
- The complete local route persists across execution boundaries
- At most three failed-edge or changed-terrain alternative replans are allowed per
  local leg. Failed edges and completed endpoints are retained to bound retries
- Cross-gap jumps are unsupported. The movement contract does not establish
  run-up, takeoff, sprint-jump or airborne-trajectory guarantees; see
  [Jump-edge execution boundary](JUMP-EXECUTION-EVIDENCE.md)
- Every descending edge requires a fully observed clear shaft from original head
  height to landing feet, and full-support landing geometry
- Drops of 4–5 blocks require current health to cover estimated damage, a one-point
  uncertainty margin and a configurable two-point survival reserve. Hunger,
  saturation, carried food and remaining health affect route cost
- Healing is never assumed during a fall. Every multi-block fall ends its
  execution slice and requires a grounded observation before continuing
- Combat cancellations do not consume the failed-route retry budget
- The local-goal heuristic can require a larger scan for long mazes. It does not
  provide global pathfinding through unseen chunks

The helper requests vertical four by default. This normally supplies landing
support for drops up to three blocks; deeper landings require a sufficiently deep,
complete observation. Use `vertical=8` or `--vertical 8` only with a verified
resident wrapper that supports that request. No resident scanning patch is
included or installed by this package. Offline tests supply complete synthetic
terrain directly to `LocalTerrain`; missing deeper support remains blocked.

Use `drop_policy=DropPolicy(max_blocks=1)` to restrict descent to one block. The
checkpoint schema is 2. Schema 1 checkpoints are rejected before any intent;
resolve outstanding requests before explicitly starting a new schema 2 goal.

## Atomic combat admission

The navigator saves `session().defense_epoch` when requesting a fresh observation.
A changed epoch invalidates the observation. Movement intents carry
`_navigation_defense_epoch` as a top-level field. A compatible gateway checks the
epoch atomically before resident dispatch, strips it on acceptance, and returns
`cancelled` / `navigation_defense_epoch_changed` on mismatch without dispatching.
The navigator then observes and replans.

A final local readiness check is also performed, but the gateway's atomic check
is what addresses the read/submit race. A missing or invalid epoch produces
`watchdog_v3_defense_epoch_required` before movement. The error name refers to the
contract's introduction and is retained for compatibility with v5.

A small fall can still lead to watchdog cancellation if damage is detected before
its movement RPC terminates. Navigation resumes from a fresh observation of the
actual landing position.

## Offline verification

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=resident-controller:navigation-cursor \
WATCHDOG_CANDIDATE="$PWD/defense-watchdog" \
  python -m unittest discover -s navigation-cursor/tests -v
```

All 67 tests pass against the exact staged v6 watchdog. The combined tests
instantiate the actual `Watchdog` and `IntentClient` against temporary files and a
fake resident. They check that matching guards are stripped before dispatch and
that combat between submission and admission cancels stale movement, followed by
fresh observation and guarded replanning. The gateway fixture includes the real
publication's integer `pending` inbox count. No live queue is used.

Coverage also includes a negative-prefix detour, partial execution, retained route
tail and cursor, persistent pending ID, combat pause, failed-edge alternatives,
dynamic obstacles, stale and uncertain results, world/session changes, rejected
old checkpoints, unsupported gap jumps, and unknown/fluid support. Terrain
fixtures are synthetic reconstructions, not captured live-world telemetry.

This source publication was checked with offline tests and Python compilation.
Those checks do not establish Minecraft physics or live-game acceptance of every
behavior in this package. Dynamic terrain can change after a verified observation.
The earlier v5 defense encounter failed with blocked approach, zero attacks and
player death; it is not evidence of safe continuous navigation under v6. Preparation did not run the loader or change a running
service. Runtime state, checkpoints, logs and the separate optional resident scan
patch are excluded from this publication.
