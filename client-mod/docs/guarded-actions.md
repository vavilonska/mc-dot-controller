# Experimental guarded local actions

This is an **experimental additive guard**, not a completed combat controller or a
live-accepted release. Combat strategy remains in the external process. The mod
only checks the request and attempts one ordinary look or attack. The endpoint is
disabled by default, even when this source is built. There is no movement,
pathfinding, target selection, repeated attack, held input, world editing,
inventory manipulation, extra reach, or new command interface.

The existing upstream input routes remain unchanged and **are not made safe by
this addition**. A controller requiring execution-time guards must never fall back
to `/control/look`, `/control/key`, or `/control/mouse`.

## Narrow acceptance scope

After separate build review and permission to install, the JVM property
`-DmineclientBridge.guardedActions=true` enables only this experimental route.
Enabling it is not evidence that it is live-tested. Both actions require:

- An unpublished integrated local world, one client-visible player, and Survival
- No open screen, pause, item use, dead/spectator player, or alternate camera
- An unenchanted vanilla wooden/stone/iron/golden/diamond/netherite axe in the main
  hand, without NeoForge's `SWORD_SWEEP` capability; swords and unarmed attacks are
  excluded so the initial guard does not authorize vanilla sweep collateral
- The exact current `world_generation` and player UUID
- The exact caller-selected target UUID, alive, pickable, non-allied, in this world
- A vanilla zombie, husk, drowned, skeleton, stray, or bogged; players, tameable
  mobs, neutral mobs, bosses, and unrecognized/modded types are rejected
- Current line of sight and ordinary entity reach, additionally capped at 2.75
  blocks from player eyes to the target bounding box
- A fresh renderer pick whose entity UUID matches the expected crosshair UUID

Attack additionally requires the selected target to be that fresh crosshair
entity, and its actual ray-hit location to be within the same reach cap. Look may
start with no entity in the crosshair, but only the named, nearby, visible hostile
can be the selected target. The mod does not derive aim angles or choose a target.

The read-only terrain extension's `WorldGeneration.current` provides a UUID tied
to ClientLevel identity. A disconnect/dimension/reconnect does not keep the old
world UUID. Obtain it from `state.world.world_generation`. This is not a revision
number for individual block/entity changes, which are checked at execution.

## HTTP schema

`POST /control/guarded-action` uses the existing loopback restriction and bearer
authentication. Query parameters, unknown JSON fields, and missing fields are
rejected. No token belongs in source, fixtures, logs, command history, or reports.

Attack request (all example UUIDs are placeholders):

```json
{
  "guard_schema_version": 1,
  "action": "attack",
  "expected_world_generation": "00000000-0000-0000-0000-000000000001",
  "expected_player_uuid": "00000000-0000-0000-0000-000000000002",
  "expected_target_uuid": "00000000-0000-0000-0000-000000000003",
  "expected_crosshair_uuid": "00000000-0000-0000-0000-000000000003",
  "ttl_ms": 150
}
```

`action: "look"` has the same fields plus absolute numeric `yaw` and `pitch`.
`expected_crosshair_uuid` is required and may be JSON null only for look, meaning
there was no entity under the freshly sampled crosshair (block/miss are both
non-entity). UUIDs must use canonical lowercase full UUID spelling.

- `ttl_ms`: integer 1–250; measured with the server's monotonic clock from handler
  entry, **including body parsing and game-thread queue time**
- `yaw`: finite, -180 inclusive to 180 exclusive
- `pitch`: finite, -90 to 90 inclusive
- Look changes at most 30 degrees yaw and 20 degrees pitch against live rotation;
  wraparound at +/-180 is handled correctly
- Attack accepts no angle, button, key, command, range, or repetition field

Successful response includes ordinary `protocol: "mineclient-bridge"`,
`schema_version: 2`, `ok: true`, and:

```json
{
  "guard_schema_version": 1,
  "action": "attack",
  "dispatched": true,
  "damage_confirmed": false,
  "world_generation": "00000000-0000-0000-0000-000000000001",
  "player_uuid": "00000000-0000-0000-0000-000000000002",
  "target_uuid": "00000000-0000-0000-0000-000000000003",
  "yaw": 0.0,
  "pitch": 0.0
}
```

`dispatched` means the ordinary synchronous action path was called. It does not
prove damage, a hit, or that a mod accepted the action. `Minecraft.startAttack()`
is the normal client attack routine; its boolean is not an entity-damage result.
The narrow access transformer exposes only that existing routine. This endpoint
does not set a key click to be consumed later and does not emit a physical/raw
keyboard or mouse event. Normal attack cooldown, game-mode, and server handling
remain in the ordinary game path. Consumers must inspect later observations and
must not interpret this response as successful combat.

The first supported acceptance environment has only NeoForge and this bridge in
a disposable local arena with no pets, other players, or protected bystanders.
NeoForge's `startAttack` input hook runs after the adapter's final pre-call guard.
Arbitrary other mods can replace the target, block for a long time, change item
behavior, or create area effects inside ordinary game hooks. Those configurations
are unsupported and are not made safe by this guard. No claim of an atomic guard
across untrusted mod code or all server-side effects is made.

Capabilities adds `guarded_actions` with schema, enabled state, target allowlist,
range/look/TTL bounds, `unenchanted_axe_only: true`, local-world restriction, and synchronous/single-flight flags.
The top-level Bridge protocol remains schema 2.

Errors use the existing `ok: false, error: <code>` form:

- 400 malformed request or unsupported guard schema
- 401/403 authentication or loopback failure; 405 wrong method
- 408 `guarded_action_expired`; no later mutation from this queued request
- 409 disabled endpoint or changed/unsafe live context
- 429 `guarded_action_busy`; a prior callback still owns admission
- 500 internal failure; outcome may be uncertain, so do not replay blindly
- 503 interrupted HTTP worker; its ticket is cancelled and synchronized with any
  running action before the response is attempted

## Timeout and cancellation contract

Only one guarded callback is queued/running at a time. The ticket monitor spans
validation and synchronous mutation. Expiry is checked at callback entry and again
immediately before mutation. HTTP timeout/interruption cancels under that same
monitor. A queued cancelled request cannot act later. Its gate stays occupied
until the actual game callback drains, even after the HTTP error response.
Stopping closes admission atomically and changes a lifecycle epoch before
cancelling. Every handler retains the epoch captured before body parsing; a
request begun before stop cannot slip into a restarted bridge. Restart does not
forget an old callback that still needs to drain.
The exchange's accepting HTTP server must also be the current server, preventing
an old server's delayed handler from inheriting the new epoch.

If mutation has already started, a timeout waits for that synchronous operation
to finish and reports its actual result, rather than sending a timeout response
while the action can still occur. This may exceed the nominal TTL: unsafe thread
interruption is not used. A blocking game/mod callback may stall completion and
the single-flight gate; this is fail-closed, not a hard real-time guarantee.

Network disconnection or a controller's own shorter socket timeout cannot undo
an action already started. This endpoint cannot promise exactly-once delivery or
observe every disconnected socket before acting. There is no replay/idempotency
token. On any transport ambiguity, the external controller must stop, avoid
automatic retries, and re-observe. TTL is a conservative server-receipt lease,
not a client clock timestamp or a promise about when a delayed HTTP packet was
originally created. The external controller must also bound observation age and
its own session/action budget.

## Source checks and remaining gates

Dependency-free Java 21 validation and cancellation tests:

```sh
JAVA_HOME=/path/to/jdk-21 bash scripts/guarded-action-core-test.sh
```

The tests cover UUID/action/angle/TTL bounds, mismatched world/player/target,
crosshair races, player readiness, local-only mode, allowlist/protected targets,
plain-axe/sweep/enchantment exclusions, LOS/reach, changed live look angle, expired queues, expiry during validation,
single-flight retention after timeout, stop/interruption cancellation, executor
rejection, exception cleanup, monotonic wraparound, and a running mutation racing
an HTTP timeout, plus stop/restart admission races. Source-contract assertions check integration wiring. They do
not replace compiling the Minecraft adapter or live game testing.

Before any real controller input:

1. Build and run the full target-version NeoForge/JUnit tests; review this patch
2. Preserve the working mod/profile and approve the separate experimental install
3. In an isolated disposable local Survival world, test disabled/auth behavior,
   wrong generation/player/crosshair, GUI transition, target LOS/reach, queued
   expiry, ordinary attack attempt, and no queued/held key residue
4. Use readback to verify actual game results and record mod-event compatibility
5. Keep the external HTTP transport disabled until these gates pass

No multiplayer acceptance is provided by this source. Its local-only guard would
need a separate reviewed scope change before any server session could use it.

## Integrated compile status

The complete integrated terrain + guard mod compiled and passed all 14 Gradle/JUnit
test cases against NeoForge 21.1.255 on 2026-10-05, including 150 dependency-free
guard checks. This does not establish runtime or combat acceptance. See
[integrated verification](integrated-verification.md).
