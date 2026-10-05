# Experimental guarded player-only yaw

**Source and offline tests only. Default disabled. No live acceptance.**
This companion to the [one-sample movement route](guarded-movement.md) aligns the
local player's yaw using ordinary synchronous player rotation setters. It selects
no target, changes no pitch, applies no translation, emits no raw/key/mouse input,
and does not issue movement packets directly. It never uses legacy `/control/look`.

After a separate installation/test approval, the JVM property
`-DmineclientBridge.guardedTurning=true` would enable this route. It is independent
of `guardedMovement` and `guardedActions`; none of those flags enables another.
Both movement and turning remain disabled when their own flag is absent.

## Shared guard and execution

Turning and forward samples use a common admission owner, latest one-use server
observation, movement session UUID and non-evicting 4096-request UUID budget. An
active movement sample blocks a turn until its cleanup finishes; a queued turn
cannot be consumed by a movement-input event. A turn consumes its observation,
so movement after turning always requires a new `/control/state` read.

The same unpublished local Survival, world-generation/player identity, no-screen,
no-pause, alive, ordinary standing/speed, no-flight, full-health/air, no-effects,
near-rest, no-auto-jump, neutral-input requirements protect both primitives.
Turning skips only the forward corridor test because it provides no movement
impulse. Pose used in checks must remain unchanged through those checks. Fresh
execution permits at most one game tick of observation drift, 0.03 position change
per axis and one degree of yaw drift.

Each turn's handler-entry-to-dispatch lease is 1..100 ms, including body parsing
and game-thread queuing. The `/state` observation expires 150 ms after server-side
creation, independently of whether game time advances. Both deadlines are checked
again after live validation and immediately before setters run.

Target yaw is canonical [-180,180), then quantized to the exact float accepted by
Minecraft. A rounded +180 becomes -180. The exact applied angle must be within
30 degrees by shortest-path wrapping of both the expected and fresh live yaw.
A requested raw 30-degree step can round slightly over the limit and be rejected.
Adapters should float32-quantize their target and check the actual bound, or leave
a small margin (for example 29.99 degrees) on intermediate turns. Do not weaken
server guards. Always confirm final yaw with a new observation.

## Request

`POST /control/guarded-turn`, exact method/path, existing loopback and bearer checks.
Unknown/missing fields and any query string are rejected. No target UUID, pitch,
key, duration, repetition, relative-angle or command parameter is accepted.

```json
{
  "turn_schema_version": 1,
  "action": "yaw",
  "session": "00000000-0000-0000-0000-000000000001",
  "request_id": "00000000-0000-0000-0000-000000000002",
  "observation_id": "00000000-0000-0000-0000-000000000003",
  "expected_world_generation": "00000000-0000-0000-0000-000000000004",
  "expected_player_uuid": "00000000-0000-0000-0000-000000000005",
  "expected_tick": 100,
  "expected_x": 0.5,
  "expected_y": 64.0,
  "expected_z": 0.5,
  "expected_yaw": 0.0,
  "target_yaw": 29.99,
  "ttl_ms": 100
}
```

UUIDs above are placeholders. Copy the shared `session`, `observation_id` and
canonical `observation_yaw` from `/control/state.guarded_movement`, together with
that same state's world generation, player UUID, game time and position. The
expected fields must exactly match the issued observation before any live pose
tolerance is considered. A newer state read replaces the old observation.

Only `/control/state` issues or replaces observations. `/control/status` and
`/control/capabilities` read metadata without renewing or invalidating them, so
status → state → status bracketing preserves the state's observation ID.

## Response and discovery

A successful response uses `protocol: "mineclient-bridge"`, `schema_version: 2`,
`ok: true`, and:

```json
{
  "turn_schema_version": 1,
  "request_id": "00000000-0000-0000-0000-000000000002",
  "dispatched": true,
  "released": true,
  "turn_confirmed": false
}
```

`dispatched` means synchronous dispatch was attempted; rotation may have begun.
It is conservative even if the final guard or a setter then failed; it is not confirmation of the final rotation. `released`
means the request owns no held input. A fresh state read must establish actual
yaw, unchanged position and readiness before another turn or movement sample.

State, status and capabilities expose `guarded_turn`:

```json
{
  "schema_version": 1,
  "enabled": false,
  "max_ttl_ms": 100,
  "max_yaw_step": 30.0,
  "held_input": false,
  "local_unpublished_survival_only": true,
  "shared_movement_observation": true,
  "pitch_supported": false
}
```

The shared `guarded_movement` object adds `owner_action`, which is null,
`"forward_sample"` or `"yaw"`, and reports `turn_supported: true`. Support does not
mean enabled; inspect `guarded_turn.enabled`. An idle guard requires a null owner,
not merely `released: true`: a queued turn does not hold a key but still owns
admission.

Errors use existing `ok: false, error: <code>`. Shared lease errors deliberately
retain their `movement_*` names, including busy, expired, replayed, observation,
pose and session errors. Turn-specific errors include `guarded_turning_disabled`,
`invalid_turn_ttl_ms`, `invalid_target_yaw`, `turn_step_too_large` and `turn_failed`.
400 means malformed/bound-invalid request; 408 means dispatch lease expiry; 409
means disabled/changed/unsafe context; 429 means shared owner busy; 503 means the
HTTP worker was interrupted. When an outcome exists, responses include the same
`dispatched`/`released` metadata, including interrupted 503 responses. Transport
ambiguity always requires stopping and re-observing, never blind retry.

## Cancellation and limits

The queued callback retains its exact ticket. A cancelled callback can drain
later but cannot rotate a player or consume a newer ticket. Cancellation before
admission invalidates the old observation. Stop/restart, world/player/screen/death
transitions and release-all use the same barriers as movement. An expired queued
turn is a no-op. Validation and setters share the cancellation monitor.

If mutation has begun, timeout/interruption waits for the synchronous setter
sequence and reports its real dispatch outcome. A stalled game/mod callback may
therefore exceed TTL and block the HTTP response; this is not a hard real-time
100 ms completion guarantee. A performed rotation is not rolled back. Input
cleanup is not physical braking. Arbitrary additional mods and concurrent legacy
controllers remain outside acceptance; guarded combat's busy check is advisory
at dispatch rather than an atomic shared combat-admission lock.

## External adapter and next gate

A navigator must divide larger turns into bounded actions, read new state after
each, and establish that position is unchanged and yaw reached the intended
float-representable target. Turning and moving cannot reuse one observation ID.
The separate movement primitive still means one half-forward sample, not a
100 ms held key; settling and progress thresholds need real physics acceptance.

The external source adapter and fake transport exercise this wire contract
offline. Optional [owner-run HTTP/probe source](../../navigation-controller/docs/OWNER_PROBE.md)
is also available, default read-only and restricted to one explicitly accepted
local test; it has only mocked-socket coverage. No real token, HTTP or input was
used during implementation. Successful fake execution does not establish real
turning/navigation acceptance. Before any live
use, preserve the working profile, obtain separate install/input permission and
run isolated disposable-arena tests with only NeoForge and this bridge, covering
all stop/timeout/identity/observation transitions and actual yaw/momentum readback.
