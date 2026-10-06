# Native defense watchdog, v6 continuity candidate

Original Python source for a single operator-started coordinator around the existing
resident queue. This frozen v6 source was built and checked offline; it is not
live-accepted, and publication does not establish installation. An earlier deployed
v5 encounter failed: approach was blocked, zero attacks were dispatched, and the
player died. The corrections below must not be read as a successful retest.

Requires Python 3.10+ on a POSIX system (`fcntl`) and the sibling
`resident-controller` source. While running, this process must be the only resident
queue writer; ordinary tasks use its IntentClient. The control-directory lock
cannot exclude clients using another directory or unrelated queue writers.

## v5.1 correction retained

Terminal combat failures are handled once per observed event, preventing a stopped
resident result from repeatedly cancelling navigation and renewing suppression.
A later fresh crosshair hit on the same hostile UUID, entity ID and type can admit
in-range melee with `approach:false`; body distance alone cannot authorize it.
Losing that fresh hit preserves encounter history and never reopens blind approach.
The runtime combat trace is bounded and freezes on death. Its private control-directory
`combat-trace-*.json` files contain gameplay observations and are not public source.

## v6 environmental recovery

The source requires the matching client-mod `environment_schema_version:1` fields
and `recover_environment` action. It recognizes observed water, submerged eyes,
lava, powder snow and fire. The watchdog remains the sole queue writer: it first
requires confirmed cancellation, then lets one native client action hold flotation
continuously while Python obtains fresh state and chooses a loaded local route.
A delayed or repeated-tick observation does not release that action's flotation.
The client still checks death, menus, world/session changes and ownership every tick.

Routes use only complete observed collision/headroom/support facts. There is no
random escape heading or invented landing; new lava cells, unknown geometry and
unsupported dry nodes cannot form an exit. Burning on otherwise dry ground may
seek observed reachable water. With no observed exit, the native action maintains
flotation while waiting for new observations; this does not guarantee escape or
survival. A changed route is installed only after confirmed cancellation, preserving
request identity and never replaying an uncertain movement write.

Recovery finishes only after native action completion and later advancing dry,
grounded observations with non-increasing frozen ticks. It then changes the defense
epoch and requires fresh navigation observation. These are client observations;
`server_confirmed` remains false. Recovery does not wait for full health or assume
that previously dry ground remains safe after a new hazard entry.

## Why bounded approach is needed

A stationary loop can hold a hostile target outside attack range with zero
attacks and monopolize the queue. v5 applies approach and progress budgets to
every admitted target in the existing hostile allowlist. It retains target
identity while useful progress continues and stops/replans when progress fails.
Players, pets, neutral types and unknown species remain excluded.

This version uses ordinary existing melee controls instead of waiting at range:

- Every admitted hostile target requests `approach:true`; the resident follows the entity
  view lock and advances only through its observed dry, flat, supported corridor
- The witch path requests `shield:false`. Raising a shield is not a guarantee
  against thrown potions, and holding use while closing slows ordinary movement
- Valid target crosshair and normal sword/axe pacing still gate each attack
- No-closing progress for 2.5 seconds, zero dispatched attacks for five seconds,
  repeated distinct target-loss sessions with zero attacks, or six seconds
  without a new observed target-health low ends the engagement
- These counters persist across same-UUID reacquisition; losing/reentering the
  target cannot reset the encounter forever
- Falling player health while still outside melee after the first second also
  permits disengagement. This is a defensive response, not damage-source attribution

After disengagement, cancellation must be positively acknowledged. The same
unreachable melee UUID is excluded for 10 seconds; ranged threats retain the
30-second exclusion. It cannot immediately seize the navigation queue again.
Other observed hostile targets remain eligible. Normal nearby combat with ongoing
attack and health progress retains its UUID and is not interrupted just because
other enemies appear. Inherited hostile locks outside the lightweight entity list
also have a deadline, using explicit combat identity/type metadata without inventing
a position. The `engagement` status field reports `scope:all_observed_hostiles`;
the historical `ranged` status key remains a compatibility alias.

## Short observed retreat, otherwise release navigation

After stopping combat, the watchdog reads a small terrain patch and a separate
fresh state. If facts support it, it dispatches at most two cardinal flat retreat
waypoints that increase separation or put an observed full block across a
representative AABB-to-eye straight line. It avoids moving closer to other
observed hostile entities.

All swept body columns need observed collision/headroom, solid support, no fluid
and no reported hazards. The full swept rectangle is checked, rather than a
finite sample that can skip a corner lava/unknown cell. No jump, drop, water
crossing or invented landing location is used. `on_ground` alone is insufficient.

Late data, changed world/player/action session, new held inputs, a newer action,
a menu/pause or incomplete terrain cannot authorize this movement. If no route
is established, automatic movement is skipped, the reason is reported and
navigation is released. The helper does not pretend the current position is safe.
A straight-line obstruction does not guarantee potion interception or protection
from splash damage; no projectile simulation is claimed.

The short retreat is observed while it runs. Continued poison ticks do not
cancel that already verified retreat. A subsequent owner-supplied route moving
away from the observed ranged threat may receive up to four seconds of relief
from the unknown-damage cancellation branch, only while each current observation
shows increasing separation. Stationary or inward movement does not qualify.
A new eligible hostile can still interrupt it. Manual cancellation/context loss
stays a hard pause; uncertain movement is never replayed.

## Integrated resident reach correction

The sibling `resident-controller` already includes:

1. Reach measured from observed `player.eye_position` to `crosshair.location`
2. Continue closing until the correct target is actually picked, or the nearest
   AABB is within 2.5 blocks, avoiding an unattackable edge-of-range stop
3. Continuous swept-rectangle clearance for approach, including between-sample
   hazardous columns
4. `combat.melee_closing_schema_version:2` checked before enabling approach
5. Regression coverage using the actual synthetic hit-location field

Minecraft Java 1.21.1 entity picking measures reach from the eye. The bridge's
legacy `crosshair.distance_euclidean` uses the entity position/feet and must not
replace actual eye-to-hit range. Both needed positions are already available;
no new mod fields or client restart are required.

The watchdog refuses hostile approach without the loaded marker and follows its
bounded disengagement path. It does not silently fall back to old sampled checks.

## Owner startup and task routing

At a safe point, stop any previous watchdog, establish `stopped:true`,
`cancel_confirmed:true` and process exit, and resolve old pending intents without
replaying them. If upgrading an older resident source, load the matching sibling
resident through its established owner-start flow; authentication stays there.
This helper neither reads credentials nor creates another access route. Observe
melee marker 2 and an alive player before explicitly starting one watchdog.
The retained melee correction alone does not need a JVM restart. The new v6
environment fields/action require the matching client-mod to be loaded by an
owner-controlled JVM reload; load the changed resident once and replace the
watchdog once, never with two writers. Resolve pending IDs before any reload.

```sh
python3 watchdog.py run --queue /path/to/existing/mailbox --control /path/to/private/watchdog
python3 watchdog.py stop --control /path/to/private/watchdog
```

Only `watchdog.py` is the entry point; `base_watchdog.py` is a library. Verify
`implementation:"native-defense-watchdog-v5"` plus
`watchdog_revision:"v6-environment-continuity-candidate"`, a fresh session/heartbeat,
armed status and the loaded melee marker. The v5 implementation label is retained
for gateway compatibility; it is not a v6 installation check by itself. Private control folders must remain outside
version control. A previous STOP marker is removed only by an explicit owner
choice after confirming old process exit and input release.

Use this package's `IntentClient` for `submit`, `wait`, `result` and `session`.
The actual `base_watchdog.run()` publication adds an integer `pending` inbox count,
`updated_at` and `pid` to `Watchdog.status()`. A bare `status()` stub lacks the
published gateway contract; callers must not invent `pending=0`.
The sibling navigation cursor already accepts v5 and requires the atomic
`_navigation_defense_epoch` guard. Stale pre-fight routes are cancelled locally
instead of running after combat. STOP takes precedence; uncertain movement is
never replayed. A new session requires fresh observation and replanning.

```python
from intent_client import IntentClient
client = IntentClient('/path/to/private/watchdog')
request_id = client.submit({'op': 'observe'})
result = client.wait(request_id, timeout=10)
```

Stopping requires confirmed cancellation and process exit before direct queue
control is resumed. An unconfirmed release is reported for operator recovery.
The helper never reconnects, quits, respawns or changes game rules.

## Verification and remaining live work

```sh
python3 -m unittest discover -s . -v
```

- 130 watchdog checks run: 129 pass; one old-v5 comparison is skipped because its
  historical source is intentionally absent from this isolated publication
- All 118 sibling resident tests pass; all 67 navigation tests pass with this
  actual Watchdog/IntentClient source, temporary gateway files and a fake resident
- All 37 gameplay-helper tests pass, including 30 crafting/gateway checks and
  seven retained portability checks
- Source verification does not access a live endpoint, queue, credential or game

Earlier limited live evidence includes a separate sword/shield script with four
attack dispatches, observed target-dead stop and player health remaining 20, plus
an older watchdog heartbeat and short navigation intents. A later actual v5
encounter failed with blocked approach, zero attack dispatches and player death.
Neither the isolated successful encounter nor offline v6 checks establish v6
closing, retreat, environmental recovery, navigation continuity, server hits or
ongoing survival. V6 live acceptance remains outstanding.

Optional axe jump criticals are deliberately separate. See `CRITICAL_HITS_1_21_1.md`.
No blind timed jump is described as a confirmed critical hit.

This is original Python project source and tests, using standard-library code and
the existing sibling resident package. No Minecraft/NeoForge source or binaries
are embedded, and no new license grant is introduced.
