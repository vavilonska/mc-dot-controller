# Bounded combat detour planner

`CombatDetour` is a pure policy helper. One instance belongs to one combat action.
It neither reads Minecraft nor sends inputs, jumps, changes height, constructs a
global route, or grants movement permission.

## Existing modules reviewed

- `navigation-controller/navigation_controller/planner.py` supplied useful ideas:
  bounded search, immutable output, complete edge admission, and admitting lateral
  or temporarily non-progressing motion when the complete route makes progress.
  Its block-grid A*, optional step-down policy, 128-step default and conservative
  grid-corner rule are not suitable to call directly from this tiny flat client
  action. They are deliberately not imported or ported wholesale.
- `resident-controller/resident_controller/world.py` separates bounded loaded
  observations from route execution. No Python transport, cache, terrain scan or
  global route is introduced into combat.
- `FlatStepCorridor` remains the terrain authority: every live adapter edge must
  be segmented to at most .65 blocks and checked with its full continuously swept
  axis-aligned square footprint, loaded dry full support, empty feet/head space,
  and existing unknown/fluid/hazard exclusions. Its geometry is reused directly
  by the executable planner test adapter; no circular footprint or endpoint-only
  substitute is used.
- `CombatPursuit`/`CombatRecovery` keep cumulative action budgets across local
  clearing or recovery. The detour planner similarly has no attempt-reset API.
- `PathSteering` was reviewed but not reused: its collision/height jump permission
  and general path semantics do not meet this flat, no-jump combat policy.

## Contract and bounds

`plan(start, target, EdgeCheck)` returns a complete safe local plan or none.
`EdgeCheck` receives two X/Z endpoints at the caller's one grounded Y and must
check the entire terrain sweep and complete bounded entity/threat neighborhood.
Its finite nonnegative clearance margin contributes to ranking; binary callers
can use zero. Missing, exceptional, incomplete or nonfinite edge evidence denies
the edge. The live adapter must revalidate current terrain and threats before
every input sample. A returned plan is not a lease on future safe movement.

- At most 3 planning calls per action, including failed/invalid attempts.
  `clear()` and `rebaseAfterRecovery()` discard the plan without refunding attempts.
- At most 32 local candidate points and 8 candidate local goals.
- Radius at most 3 blocks from the planning start; each route edge at most 2 blocks.
- At most 2 intermediate waypoints, plus the final local goal.
- Every complete goal improves target distance by at least .4 blocks and remains
  at least 1.3 blocks from its center; entity collision checks remain authoritative.
  The nominal forward goal is at most 2.75 blocks; alternate goals can use the
  full 3-block local radius.
- At most 512 route evaluations and 192 memoized directed edge checks. Geometric
  generation is also finite: no more than 8 × (1 + 32 + 32 × 31) route tuples,
  filtered before route allocation, with geometry-distance reuse and monotonic
  checks while generating. No asynchronous retry or automatic budget reset exists.
- Planning uses an 8 ms monotonic cooperative deadline. JVM scheduling, class
  initialization, garbage collection and a caller-supplied edge callback cannot
  be hard-preempted. Time is checked during generation and before/after callbacks.
  A callback returning after the deadline or a reversed clock prevents admission.
  Expiry between callbacks can keep an earlier fully checked route. After the
  first fully safe route, optimization examines at most 4 more candidates or 8
  more edges, avoiding exhaustive optimization of a valid route.

Routes are first ordered by geometric target progress and length. Unsafe routes
are rejected entirely; safe alternatives are scored by minimum clearance, net
progress, length and waypoint count. Intermediate points need not be closer to
the target. Absolute block centers supplement target-relative candidates so a
narrow safe passage beside a trunk is not missed solely due to sampling angle.
This intentionally incomplete search may safely report no route even when a
different or larger route exists.

## Executable checks and limitations

`CombatDetourTest` contains 22 JUnit cases using the actual pure square-sweep
helper. They cover pit/tree detours, reflected and diagonal geometry, a lateral
first step farther from the target, alternate safe goals, target-body exclusion,
no-route barriers, wet/hazardous/unloaded/unknown terrain, complete-threat denial,
all fixed bounds, immutable output, unchanged lifetime attempts across clearing
and recovery, exceptional edge evidence, and monotonic deadline behavior.

The retained tree coordinates (player 17.9743191721, 28.2788554407; later target
18.63265, 31.02466; log column 17, 29) are explicitly a non-atomic geometry fixture,
not an exact reenactment or live acceptance. Tests preserve known-safe block
centers 18.5, 28.5 and 18.5, 29.5 and include a blocking target-body AABB.

Offline tests and synthetic timing probes do not establish real Minecraft
movement, entity completeness, collision timing, reach, combat success or a hard
real-time JVM guarantee. Cold JVM attempts can exhaust the deadline safely.
No game process, IPC endpoint, desktop or deployment is accessed by this work.
