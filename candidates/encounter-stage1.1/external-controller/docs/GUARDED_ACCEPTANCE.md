# Guarded adapter integration

## Current boundary

The ordinary CLI runs fake data only. The Python API can construct a guarded
adapter, but no config was armed and no live endpoint was contacted during this
implementation. Build/install/game acceptance is a separate parent-owned task.

The companion guarded endpoint uses a synchronous ordinary game attack instead
of posting a key click to be consumed later. It checks the current world/player,
selected hostile target, crosshair, LOS/reach, readiness, axe and expiry on the
game thread. Never substitute legacy look/key/mouse routes if this endpoint fails.

## Required operator gates

Before arming:

1. Verify the guard's full target-version build/tests and reviewed source
2. Install in an explicitly approved isolated/disposable client, preserving the
   existing profile and mod; only NeoForge plus the reviewed bridge is in scope
3. Complete the guard endpoint's disabled/auth/wrong-generation/crosshair/GUI/
   expiry/ordinary-action acceptance and verify neutral input afterward
4. Explicitly authorize one bounded local unpublished Survival controller session;
   prepare a flat known floor, one eligible hostile and an unenchanted vanilla axe
5. Provide the already authorized token through a private caller-selected config,
   plus the exact run ID/PID/player UUID/dimension; never put it in source or logs
6. Only then set the connection's `enabled` and `acceptance_verified` flags true

Both flags are attestations from the caller, not proof synthesized by the code.
The game guard also defaults disabled and enforces local-world restrictions.

## API wiring

After these gates, a caller can construct `ConnectionConfig`, `HttpTransport`,
`MineClientBridge` and `Controller` through their Python APIs. Use the same clock
for adapter and controller. Call `bridge.prepare_guarded()` before the session;
this is a read-only capabilities check. Pass the exact expected identity from the
explicit config to `MineClientBridge`, and use `Config(enabled=True)` only for the
single authorized bounded session. No live CLI is supplied.

The `Bridge` interface now receives an `ActionContext` for both look and attack:

- The exact most recent `Snapshot` object
- The explicitly selected `Entity` from that snapshot
- A local monotonic deadline capped by snapshot freshness and session end

The adapter consumes its reference to that snapshot before POST. Reusing it after
success, failure or an uncertain response is rejected. The controller stops on
all transport/protocol errors; no retry, alternate input path or re-arming occurs.

## Wire contract

`POST /control/guarded-action` fields:

- `guard_schema_version`: integer 1
- `action`: `look` or `attack`
- `expected_world_generation`, `expected_player_uuid`, `expected_target_uuid`:
  canonical lowercase UUID strings
- `expected_crosshair_uuid`: canonical UUID, or null only for look acquisition
- `ttl_ms`: integer, this adapter chooses 1–150; server supports 1–250
- Look only: finite absolute `yaw` in [-180,180), `pitch` in [-90,90]

Attack requires target UUID == expected crosshair UUID. Extra fields are refused.
The controller uses at most 20° yaw/12° pitch per step; server limits are 30°/20°.

Accepted replies must carry Bridge protocol/schema2 and guard schema1, matching
action/world/player/target, `dispatched:true`, `damage_confirmed:false`, and valid
angles. Look angles must match the requested result within float tolerance.
A key/mouse `mod_input_event` acknowledgement is neither expected nor fabricated.

Capability preflight requires exact schema1 bounds and these true flags:
`enabled`, `local_unpublished_survival_only`, `single_flight`,
`synchronous_attack_attempt`, `unenchanted_axe_only`; `held_input` must be false.
The target allowlist must exactly match the six supported vanilla hostile types.

HTTP 408/409/429/500/503, any transport ambiguity, mismatched reply, cancellation
or stale context ends the controller session. An input-clear read is attempted
in `finally`; a failed read is reported as unconfirmed. No unguarded release-all
POST is sent, since the guarded backend never creates held keys.

## Important time semantics

The local deadline bounds when this client admits a request. The server TTL begins
at handler receipt and bounds queued/validated admission to mutation. Neither is
an absolute cross-machine timestamp. Socket timeout cannot retract a started
synchronous action, and an exceptionally slow mod callback cannot safely be
preempted. Treat a missing reply as uncertain and stop. Do not claim a kill or
successful hit from `dispatched:true`.
