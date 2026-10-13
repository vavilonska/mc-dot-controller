# Opt-in noncombat walking budget

This is a restricted acceptance envelope, disabled until a `movement_budget_start`
action is explicitly submitted through the existing action path. It is not a
world-wide physics limiter or a guarantee against external forces. Default actions
retain ordinary vanilla physics and existing input ownership.

## Exact scope

The cap is 32 blocks of cumulative ordinary AI walking, including detours,
backtracking, and released-input coasting between actions. Sampling begins at the
successful arm action, before any setup walking, and ends only after the finish
action's neutral-input cleanup. `arm_origin`, `started_nano`, and
`covers_armed_interval_only:true` disclose that boundary. Pre-arm motion is NOT
measured; the caller must prove the case has not already performed AI walking.
No endpoint distance, route length, polling approximation, or previous process
ledger is substituted for actual client self-move displacement.

`Entity.move` HEAD/RETURN classify an ordinary SELF move. The observation-only
mixin samples each `Entity.setPosRaw` position-field write immediately after the
write, before onMove callbacks. It captures same-tick out-and-back movement, even
with no intervening state GET. The sum is the 3-D polyline length of those actual
position changes. A second position write within one ordinary move, an unobserved
position mismatch, a non-SELF move, a correction outside move, reentry, invalid
coordinates, context loss, manual/direct input, hazards or an envelope violation
permanently invalidate the ledger. Accepted native keyboard/mouse callbacks
invalidate at callback time, including brief press/release and effective mouse look/scroll.
Mouse rotation is observed at actual nonzero LocalPlayer Entity.turn calls; AI
look uses direct ordinary yaw/pitch setters. Ignored cursor recenter callbacks
produce no turn, and zero-delta turns do not invalidate;
blocked isolated callbacks and synthetic Bridge callbacks retain existing behavior. Invalid telemetry is not accepted distance
proof; known displacements may remain as diagnostic evidence.

This narrow scope requires private singleplayer, the original exact level/player
objects and action session, focus, dry grounded integral-height walking, no mount,
flight, effects, damage, sprint or jumps. Known ordinary full-block floor IDs are
whitelisted. Every cell under the whole player AABB inflated by .56 horizontally
must be supported by a loaded allowed full cube, with empty two-block clearance.
This rejects edge-cutting and one-block drops before another authorized step.
Nearby entities are rejected except exact vanilla ItemEntity instances holding
OAK_LOG, for the approved resource pickup. Exact vanilla XP orbs become allowed
only immediately before the guarded FurnaceMenu slot-2 QUICK_MOVE of exactly one
observed iron ingot; exact menu, stack and fingerprint are checked. The harmless
XP tail remains allowed through sealing and is exposed as furnace_xp_allowed.
Earlier orbs and all mobs/projectiles remain rejected. Fixtures are retained; breaking fixture
blocks to produce other item drops is outside this case.

## Early-stop reserve

For the pinned vanilla/NeoForge 1.21.1 ground-travel path, normal speed <= .1 and
friction .6 imply ordinary acceleration <= .1 and horizontal damping
`.6 * .91 = .546`. The adapter conservatively admits at most .35 stored horizontal
speed, .2 acceleration allowance, .55 total next-tick displacement, and .55 damping.
It stops issuing owned input at 30 blocks, leaving 2 blocks. One complete next tick
plus all neutral coasting is bounded by `.55 / (1-.55) = 1.22223 < 2`. Vanilla's
small-velocity truncation only reduces this bound. Vertical displacement, unusually
large moves, or aggregate movement exceeding .55 in one client tick invalidate.
The bound assumes the accepted dry-flat envelope continues; unexpected external
motion causes uncertain/stop, never a PASS, and is never prevented by position,
velocity, collision or teleport overrides.

## Wire

Start is an ordinary capability-guarded action with ordinary exact expected
session/world/player/dimension/held-item bindings and:

    action: movement_budget_start
    movement_budget: {schema_version:1,bundle_id:"case-id",max_distance:32,mode:"dry_flat_self_walk_v1"}

Every later ordinary action, including inventory, station setup and cleanup, has
`movement_budget_bundle_id:"case-id"`. Only guarded flat follow_path, stationary
break/place, inventory click, block interaction, selection, close and finish are
admitted. Support mining, bridge/descent, jumps, sprint, recovery, boats, combat,
projectiles and consumables are outside this scope.

Finish is `movement_budget_finish`, with the same bundle binding. It requires
three settled post-tick observations and neutral keys, observes cleanup, then
seals the ledger. All ledger fields remain immutable after seal. There is no
reset/rearm endpoint: changed IDs, timeout, cancel, another action or new start
cannot renew the cap. Process restart changes action session and loses the local
ledger; the caller must reject that rather than re-arm a previous case.

State root `movement_budget`, action status top-level `movement_budget` and terminal
`result.movement_budget` expose identity, actual_distance, cap, reserve, counters,
coverage and status. Terminal receipt snapshots are historic; live top-level
snapshots can add coasting/counters before seal. Only sealed snapshots are expected
to compare equal in all fields. Statuses: unarmed, armed, stopping, invalid, sealed.
`moving_accepted` is a boolean envelope-validity flag, not an acceptance result.
`all_cause_physical_cap:false` explicitly excludes a universal-force guarantee.

## Verification boundary

Pure tests cover wire, exact cap, same-tick reverse movement, cumulative accounting,
reserve, invalidation, no reset, immutable sealing and action deduplication.
Official FML tests inject the exact production observation mixin and execute actual
vanilla Entity.move/setPosRaw on allocation-only LocalPlayer fixtures, without
constructing a game/client/world. Because forgejunitdev is SERVER-side, a test-only
common mixin config activates the otherwise client-only production mixin. These
tests establish hook application and ledger behavior, not live world physics or
completion of the approved acceptance case.
