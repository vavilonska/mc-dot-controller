# Guarded one-sample external adapter

## Scope and defaults

`GuardedSampleAdapter` and `SampleNavigator` consume the companion guarded forward
sample and guarded yaw contracts through an explicitly supplied offline
transport by default. `SampleConfig.enabled` defaults to false. Optional
`LoopbackHttpTransport` source now supports a real connection only after explicit
adapter and transport acceptance flags, enabled mutation and a pinned movement
session. Caller-supplied auth stays in memory; there is no token discovery,
installation or legacy input route. No real connection was made during this work.
The fake transport marker is an interface contract, not a Python sandbox.

The old `Navigator`/`FakeAdapter` duration-pulse demonstration remains separate.
It is not a live adapter and is never mapped to the one-sample primitive.

## Exact action semantics

Forward request: `POST /control/guarded-movement`, `movement_schema_version: 1`,
`action: forward_sample`. The body carries session, fresh request UUID, latest
observation UUID, expected world generation/player/tick/position/canonical yaw,
`ttl_ms: 100`, and `duration_ms: 100`.

This asks the bridge to offer exactly one ordinary `0.5` forward-input sample.
The duration field bounds handler-entry-to-sampling admission. It does not mean
100 ms of held movement, a velocity, a distance, or an end-to-end HTTP deadline.
The adapter never computes distance from duration. The response must match the
request ID and report schema 1, `sampled: true`, `released: true`, and
`movement_confirmed: false`. Cleared input is not braking or proof of arrival.

Yaw request: `POST /control/guarded-turn`, `turn_schema_version: 1`, `action: yaw`.
It uses the same session/nonce/challenge/expected-pose fields and `ttl_ms: 100`,
plus `target_yaw`; it has no duration or pitch field. The adapter quantizes the
target to Minecraft float32, normalizes a rounded +180 to -180, and checks the
angle actually applied. Route-following intermediate turns use a 29.99-degree
margin within the bridge's 30-degree maximum. The response must report matching
request ID, `dispatched: true`, `released: true`, `turn_confirmed: false`.
A fresh read verifies the actual yaw and unchanged position after every turn.

## Capability and ownership checks

Preflight requires the exact supported movement and turn safety semantics:

- Movement schema 1, enabled/open, at most one sample, impulse 0.5, no held keys,
  maximum duration 100 ms, maximum TTL 250 ms, and local-unpublished-Survival scope
- Canonical movement-session UUID, positive remaining request budget, explicit
  null `owner_request_id` and `owner_action`, not sampled, released
- Turn schema 1, enabled, TTL 100 ms, max yaw step 30, no held input or pitch,
  local-unpublished-Survival scope, and shared movement observation

These are protocol guarantees, not a claim that the external state schema exposes
every execution-time fact. The bridge must independently enforce singleplayer,
auto-jump, ordinary speed/dimensions, pause, liquid and all other local guards at
dispatch. External checks do not replace those bridge checks.

## Fresh observation flow

Each action context is built from status → local 27-cell terrain → state(radius 4)
→ status. Only `/state` issues a movement observation ID. `/status` and capabilities
must preserve it; renewing the ID in a status bracket would invalidate the action.
Movement and turn share the same latest-only, one-use challenge namespace.

The adapter requires matching run/process/player/world/session identity, monotonic
status/state ticks, state no more than one tick behind the final status, unchanged
position/yaw within the idle bracket, complete local terrain and at most two ticks
of terrain age. Budget-truncated terrain pages are followed in order at 50 ms
spacing within the same strict age budget; a slow scan is rejected. State-request start-to-action age must stay below 100 ms locally;
the server separately enforces its 150 ms monotonic observation age. A paused
world does not make an old challenge fresh.

Only full health/air, food >=8, grounded integer feet, no effects, no nearby entities
within radius >=4, neutral input and horizontal speed <=0.001 are accepted. The
external swept corridor mirrors the bridge's 0.6-block forward sweep with 0.05
margins, dry full-cube floor allowlist and two clear air blocks. The narrower
movement floor set is checked separately from the broader planning floor set.
Unknown/truncated terrain, partial pages or unsupported blocks are blocked.

The captured terrain fixture's zero-radius nearby data, old samples and off-center
start remain rejected. No guard was relaxed to make that capture executable.

## Settling and finite behavior

After a forward response, the adapter sends no further action while settling.
It reads status/state/status, checking identity, full health, neutral ownership,
yaw, bounded displacement (<=0.35 blocks), unchanged height and safe player state.
Two near-rest readings must occur on different game ticks and differ in position
by at most 0.005 blocks. Then a new full terrain/state/status observation must pass
all action gates before the next sample. Residual movement is never treated as
permission to send another sample.

Defaults are 192 total actions, 96 samples, 30 seconds of navigation checking,
and at most 16 settling brackets within one second per sample. Stalled progress,
unexpected displacement, damage, stale/unsafe observation, session changes,
unknown action results or failed cleanup confirmation stop the run. Faults latch
the adapter; another observation cannot silently resume it. Old challenges and
request IDs are never retried. No fallback release, key, raw-key, look or command
POST is issued.

Supplied transport calls remain synchronous. The optional HTTP implementation
uses finite socket waits plus a total-request deadline timer that shuts down the
socket; callback implementations must supply their own deadline. Neither timer
scheduling nor request checking is a hard real-time stopping guarantee. Socket
closure cannot retract a delivered action, stop physics, or confirm remote cleanup.

## Offline evidence and remaining acceptance

```sh
python -m unittest discover -v
python -m compileall -q navigation_controller tests
python -m navigation_controller.sample_demo
```

The wire fake models one fixed illustrative sample followed by artificial decay;
it is deliberately not Minecraft physics. Tests cover default-off/no-live gates,
capabilities, challenge preservation/replay, strict ownership fields, float yaw,
readback/settling, freshness, incomplete terrain, hazards/entities, budgets and
fault latching. Independent review findings have regression coverage.

Still required: approved isolated installation of the exact guarded movement+turn
build, execution-time guard acceptance, real sample/cleanup/settling displacement,
and separately authorized owner-run use of the explicit live transport. Source compatibility and
successful fake arrival do not establish live navigation acceptance.

The [owner-run probe guide](OWNER_PROBE.md) separates read-only evidence from
one finite action. `adapter.stop()` and transport `close()` stop local admission;
they never send a legacy release request. A contradictory or failed post-action
readback clears any earlier cleanup claim and latches the adapter closed.

Live adapter scope is limited to one explicit acceptance action: one total action,
one maximum sample and a checking budget no greater than five seconds. The
`SampleNavigator` route runner remains simulation-only even with acceptance flags.

The optional HTTP transport also consumes a permanent one-POST-per-instance budget
before possible dispatch. An error cannot restore write admission; GET readback
remains available. Replacing the transport to retry an ambiguous action is not an
authorized recovery path.
