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

### Explicit noncombat capability policy

For a separately approved noncombat capability bundle, the same watchdog can be
started with an explicit execution policy:

```sh
python3 watchdog.py run --queue /path/to/existing/mailbox --control /path/to/private/noncombat-watchdog --execution-policy noncombat
```

This is scheduling policy in the real IntentClient → Watchdog → QueueClient →
Resident chain. It does not bypass the watchdog, change credentials, broaden
access, start a game, or authorize any case. The existing startup prerequisites
still apply: confirm prior writer exit, input release and reconciliation of all
unknown/pending IDs before starting. It cannot retroactively stop an unrelated
writer or an already-running resident combat owner.

The default is `--execution-policy standard`, retaining automatic legacy defense
and environmental recovery. In `noncombat` mode the watchdog stays armed and
publishes fresh read-only observations, so the existing bounded capability lease
can be acquired even when nearby hostiles or environmental hazards are observed.
It never starts unsolicited combat, navigation cancellation, ranged retreat,
environmental recovery or release-all before acquisition, between actions, or
after a confirmed lease release. Unsafe observations and sensor failures pause
the watchdog without issuing a new mutation. The native action's own per-tick
safety checks and correlated cancellation remain unchanged.

Outside a lease, only observation and lease-control intents are accepted.
Mutation intents require an active exact nonempty capability owner and the
existing fresh guards. The noncombat action allowlist is explicit:
`follow_path`, `break_block`, `place_block`, `click_slot`, `boat_drive`,
`boat_mount`, `boat_dismount`, `interact_block`, `use_item`, `select_hotbar`,
`close_menu`, and `gateway_pearl`. Native `use_item` remains consumables-only.
`combat_entity`, `attack_entity`, `shoot_entity`, `recover_environment`, raw/direct
input and future unlisted actions are rejected locally before a resident queue
write. This broad noncombat allowlist is not permission to exceed the user's
case-specific action, terrain, movement, health or time limits.

A local policy rejection has `status:"cancelled"`,
`reason:"noncombat_execution_policy"`, `queue_request_id:null`,
`gameplay_effect_confirmed:false`, and
`policy_rejection:{schema_version:1,execution_policy:"noncombat",dispatched:false}`.
It is positive non-dispatch evidence, not a fabricated native/HTTP receipt. A
handoff, unreleased input or unknown existing owner takes precedence over this
receipt and remains unresolved. Allowed actions still require their later
semantic post-observation before another mutation or lease release.

Verify the actual published state before running a bundle:
`execution_policy_schema_version:1` and `execution_policy:"noncombat"`, together
with the normal fresh watchdog/resident session, context, focus, neutral input
and lease checks. The matching capability Runtime can require that exact policy
with `required_execution_policy="noncombat"`; its CLI exposes
`run-goal --require-noncombat`. Unknown action outcomes retain their original
intent/queue IDs and durable owner checkpoint, without watchdog retry or
automatic takeover. Deadline/heartbeat expiry pauses rather than reverting to
standard defense. Explicit operator STOP is still permitted and issues its
single existing cancellation request, then waits for confirmation.

Before any queue access, first noncombat startup fsyncs a private
`execution-policy.json` pin. Later startup in that same control directory must
explicitly request noncombat. Default/standard startup is refused; corrupt,
oversized, non-regular or symlinked pins and a missing pin after published
noncombat state fail closed. Do not delete a pin to downgrade a running or
unresolved session. Any future standard run requires a separately chosen fresh
control directory after the existing owner-stop/reconciliation procedure. Old
standard directories without a noncombat pin retain their normal default.

These changes are offline-verified only. The dedicated
`capability-runtime/tests/test_noncombat_watchdog.py` uses the actual mailbox
chain with a synthetic Bridge for hostile/hazard startup, acquisition races,
idle gaps, release, combat/raw denial, ordinary select/move semantic samples,
STOP, unknown outcomes, expiry, focus/context and restart quarantine. No live
game or endpoint is exercised by those tests.

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

### Explicit menu recovery

The original observation-recovery path still requires confirmed cancellation
and two fresh increasing-tick samples before rearming. If that recovery is
blocked by an open menu, a caller may submit exactly
`{'op': 'recovery_close_menu'}` through `IntentClient`. It is accepted only in
the currently advertised paused recovery window. The client binds the watchdog
session, defense epoch and a maximum0.8-second age. Old queued intents cannot
be saved for a future recovery period.

The exception dispatches at most one Escape click. It requires fresh matching
world/player/native session, known pause/action states, no held mappings or
current owner, and no release/handoff latch, environment recovery, ranged
operation or STOP. Both the outer action and final state action must be idle or
terminal. A typed current policy takes precedence over historical receipts.

The resident receives a narrowly tagged fixed command. It rechecks current
policy, local owners and native context before and after its reads and before
the single POST. Rejection and unknown outcomes preserve original pending IDs,
bodies and owner state. The menu result path never sends a generic cancel or
release-all; it remains paused on uncertainty. Ordinary explicit direct input
and explicit operator stop retain their existing behavior. A successful native
acknowledgement does not prove a menu closed; fresh observations still gate
rearming. These local checks do not add an atomic native admission guarantee.

This source feature has only offline fixture/real-mailbox-chain verification.
It does not authorize or represent a new game action in a previously closed
case. The MCP, real Windows and NeoForge platform gates are separately recorded.

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


## Capability-runtime ownership (increment-2 source integration)

Capability goals now acquire one bounded logical lease through the same
`IntentClient` inbox before their initial observation. This does not introduce
another resident writer, transport, credential, or game connection. The claim is
bound to the watchdog session and defense epoch, resident session, and observed
world generation, dimension, player UUID and native action session. Original
lifetime is finite (Runtime defaults to two hours, hard maximum one day). One
local-only heartbeat thread renews a three-second liveness interval, never the
original deadline; a missing or uncertain heartbeat ends renewal without retry.
The thread never performs gameplay or contacts a second endpoint.

Only the claimed Runtime's bounded capability observations and supported guarded
native actions are admitted. The claim remains held during CPU-only planning,
expected combat damage, action completion and later semantic observations.
Legacy automatic combat/environment recovery cannot race those owned steps.
Native per-tick focus, private-singleplayer, context, hazard and target checks
remain authoritative. A second mutation requires a new safe post-action sample.

Lease expiry, owner-process death, malformed/current resident policy, unknown
receipts or context loss pause ownership. They do not authorize automatic
cancellation, legacy combat takeover, or replay. Explicit operator STOP still
uses the existing resident cancel/release-all path once. Unresolved owner request
and backing queue IDs stay retained. An fsynced private ownership marker is
written before acquisition acknowledgement and before forwarding each owner
request; restart with an active or unreadable marker remains quarantined.

Successful release requires a fresh matching neutral terminal observation and
current idle same-session resident policy. Its inactive marker is fsynced before
acknowledgement. An explicitly requested expected-dimension transition may arm
exactly one destination observation only after a matching native terminal receipt
with confirmed input release. Only world generation/dimension may then rebind;
player, native session, watchdog epoch, original owner and deadline stay fixed.

Published `pending` counts ordinary intents. `pending_capability_controls` reports
local lease controls separately, so a heartbeat cannot invalidate a semantic
post-observation by pretending to occupy the gameplay queue. Current lease state
is published before its acknowledgement. The new implementation is source-only
and has offline real-adapter-chain evidence; it does not establish installation,
live gameplay acceptance, survival, server damage, or dimension travel.

## Same-owner IPC responsiveness

Only a confirmed live capability lease uses the 10 ms Watchdog inbox/result
poll cadence. Unowned, expired, stopped, paused, handoff and release-uncertain
states retain the existing 50 ms loop. IntentClient checks local result files
at 10 ms only while its own confirmed heartbeat is live; its ordinary cadence
remains 100 ms. These are read-only IPC polling changes, not extra native reads
or submissions. Original deadlines, STOP precedence, exact request correlation,
unknown quarantine and no-replay rules are unchanged.
