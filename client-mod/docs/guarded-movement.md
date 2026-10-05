# Experimental guarded forward sample

**Default disabled. Source and offline tests only. Not installed or live-accepted.**
This additive primitive is deliberately narrower than a duration-based key pulse:
one request may supply **one half-forward (`0.5`) ordinary client input sample**.
It does not press or hold any KeyMapping/raw key, enqueue clicks, emit synthetic
keyboard events, send movement packets itself, teleport, brake, or choose a path.
Vanilla consumes the sample in the ordinary player tick; bridge-owned `Input.up`
and `Input.forwardImpulse` fields are cleared at the end of that client tick.
No movement is guaranteed; `sampled` is not proof of a changed position.

The 100 ms maximum is a **handler-entry-to-input-sample lease**, including request
body parsing. It is not a held-key duration, a travel-time promise, a hard limit
on physics or an end-to-end HTTP deadline. A separate one-use observation ID is
issued from `/control/state` and expires 150 ms after its server-side creation.
Its age is rechecked at admission and immediately before sampling, so an HTTP
exchange delayed in the shared worker queue cannot renew an old observation merely
because world game-time stalled. All timing uses the server monotonic clock.

## Acceptance boundary

An approved future isolated test would use the separate JVM property
`-DmineclientBridge.guardedMovement=true`. The existing guarded combat flag does
not enable movement. Enabling the flag alone is not runtime acceptance.

Every input sample requires:

- Unpublished integrated local Survival world, exactly one client-visible player
- Same world-generation UUID, player UUID and current bridge movement session
- No screen/pause, death, spectator, other camera, item use, riding, sprinting,
  crouching, swimming, fall flight, water/lava, ladder, fire or active effect
- Full health and air, no hurt animation, food >= 6, grounded integer feet height
- Ordinary standing dimensions, no flying/mayfly/noPhysics, both actual cached
  speed and movement-speed attribute positive, finite and <= vanilla 0.1
- Horizontal velocity <= 0.001 and |vertical velocity| <= 0.1; a controller must
  wait for near-rest before a subsequent sample rather than silently weaken this
- Auto-jump disabled in both current option and cached player state, with zero
  queued auto-jump ticks. A narrow read-only access transformer exposes that
  existing counter; the bridge never changes the option or counter
- Completely neutral sampled movement input, no held key mappings, no bridge raw
  or mouse holds, no virtual keys held
- Observed game time no more than one tick behind, position within 0.03 on each
  axis, yaw within one degree including wraparound
- A currently loaded 0.6-block forward swept player corridor, including 0.05
  lateral/back margin and 0.25 entity clearance; full-block support from the
  explicit vanilla ordinary-floor allowlist and two air blocks above each column
- No forced chunk loads, no unknown/modded support, no entity in the corridor

Readiness and neutral-input checks are repeated after corridor inspection; any
change in the pose used for that inspection rejects the request. Request timing
is checked again after these callbacks, immediately before writing input fields.
The half-forward impulse is below vanilla's dry-land 0.8 double-tap sprint
threshold. This was inspected in the cached official target-version binary; it
is not a claim about arbitrary mods that replace input or physics.

## Wire contract

`POST /control/guarded-movement` retains the existing exact path, POST, loopback
and bearer-auth checks. Query parameters, unknown/missing fields and malformed
identity/numeric bounds are rejected. No credential belongs in example files.

First read `/control/state`. Its `guarded_movement` object contains:

- `schema_version: 1`, `enabled`, `session`, `admission_open`, `requests_remaining`
- `owner_request_id` (null if none), `owner_action`, `sampled`, `released`
- `observation_id` (null while a request owns admission), `observation_yaw`
- `max_observation_age_ms: 150`, `max_duration_ms: 100`, `max_ttl_ms: 250`
- `max_input_samples: 1`, `forward_impulse: 0.5`, `held_keys: false`
- `local_unpublished_survival_only: true`, `turn_supported: true`

Capabilities exposes the same status/bounds except the observation fields; it
does not issue observations. Each new `/state` observation invalidates its
predecessor. `/control/status` does not issue or invalidate an observation. Copy the corresponding state world/player/tick/position exactly;
use `guarded_movement.observation_yaw` for the canonical [-180,180) yaw because
Minecraft's ordinary player yaw may accumulate rotations beyond that range.

Example structure only; UUIDs are placeholders and cannot authorize a request:

```json
{
  "movement_schema_version": 1,
  "action": "forward_sample",
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
  "ttl_ms": 150,
  "duration_ms": 100
}
```

`duration_ms` is 1..100 and must be <= `ttl_ms` (1..250); the earlier bound wins.
Only one input sample is allowed even when multiple game ticks fit within it.
No arbitrary key, strafe, jump, sprint, repeated-input, turn or command field is
accepted. `request_id`, `session` and `observation_id` use canonical lowercase UUIDs.

The observation must still be the latest, unconsumed observation and must match
the exact expected world/player/tick/pose fields. A valid observation is consumed
before later admission validation. Successfully admitted, expired and mismatched
requests consume their request UUID; duplicate UUIDs never repeat the input.
Replay history is not evicted: after 4096 consumed UUIDs, the session fails closed
until a bridge restart creates a new session. Restart cannot forget a sampled
lease whose cleanup is still pending. This is rejection-only replay prevention,
not an idempotent response cache or exactly-once network delivery guarantee.

A successful HTTP 200 response contains ordinary protocol schema 2 plus:

```json
{
  "movement_schema_version": 1,
  "request_id": "00000000-0000-0000-0000-000000000002",
  "sampled": true,
  "released": true,
  "movement_confirmed": false
}
```

`ok: true` means the single sample was offered and its owned input fields were
released. It does not prove motion, arrival, zero velocity or no downstream
server/mod effects. Inspect fresh state after every response and stop on damage,
unexpected pose, nonzero residual velocity, changed identity or transport doubt.
Do not blindly retry with either the same or a newly fabricated UUID.

Errors: 400 malformed; 401/403 auth/access; 405 method; 408 expired sample lease;
409 disabled/unsafe/changed/replayed/expired observation/session budget; 429 busy;
500 unexpected internal failure; 503 interrupted worker. Where a ticket existed,
error responses include `sampled`/`released` so a cancelled already-sampled
request is not mistaken for a no-op. Transport failures remain ambiguous.

## Cancellation and cleanup

A single monitor spans validation and the sole input mutation. Cancellation of a
pending ticket removes it before any subsequent input event can consume it.
A sampled ticket retains ownership until game-thread cleanup succeeds, even if
its HTTP wait expires or is interrupted. The HTTP worker does not acknowledge
release before cleanup; cleanup failure retains admission and is retried on later
ticks. A dead/stalled game thread may therefore block the response indefinitely.
There is no unsafe thread interruption and no hard real-time stopping guarantee.

Client tick end clears owned fields. The next tick's pre-event also clears any
residue from an interrupted previous tick. Screen opening, world unload/logout,
player replacement, local-player death, `/control/release-all` and bridge stop
cancel/release on the game thread. Off-thread cancellation closes the logical
lease immediately; the next game-thread cleanup clears owned fields. Cancelling
also invalidates an observation that has not yet reached admission. Old ticket
cancellation cannot affect a new lease. A stopped session rejects handlers that
began before its restart, including delayed body parsing.

Clearing input is **not braking or undoing movement already consumed by vanilla**.
Vanilla inertia and server reconciliation may continue after release. The terrain
margin and near-rest precondition are deliberately conservative; they do not
replace isolated arena testing. Arbitrary additional mods may alter same-tick
input, collision, speed, hooks or world state; those combinations are unsupported.
Legacy input routes remain unguarded, and mixing controllers/native input is not
accepted. Guarded combat rejects movement ownership observed at its dispatch check;
this is not an atomic cross-primitive admission lock. Game mutations remain
serialized, and movement revalidates pose at its later sample.

## Integration limits and next gate

The original external duration fake remains separate and must not map
`pulse_forward(100)` to this route assuming 100 ms of held movement or its fake
4-block/s displacement. A new [offline one-sample adapter](../../navigation-controller/docs/ONE_SAMPLE_ADAPTER.md)
now checks fresh observations, leases/results and near-rest readback using an
explicitly simulated transport. There is no live HTTP implementation. Actual
progress, displacement and settling thresholds still need game acceptance.

A separate default-disabled [guarded player-only yaw route](guarded-turning.md)
now exists in source. It shares this admission owner, observation ID and replay
budget, applies at most 30 degrees, and requires a new observation after every
turn. Existing guarded combat `look` still requires a named hostile and must not
be used for navigation. Never fall back to `/control/look`. A source-only external
adapter can exercise the new wire contract with a fake transport; actual physics,
settling thresholds and live acceptance remain separate gates.

Before any game input: independently review this source, preserve the current
profile/JAR, obtain separate install/test permission, use a disposable local arena
with only NeoForge and the bridge, and verify disabled/auth behavior, obs/session
staleness, queued expiry, every lifecycle cancellation, actual sample/cleanup,
settling displacement and event compatibility. No HTTP controller, installation,
game launch, input, network probe or credential handling was performed here.
