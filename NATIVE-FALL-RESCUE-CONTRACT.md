# Native fall rescue v1 candidate

This is an opt-in, private integrated-server survival foundation. It is not a 100% clutch guarantee and is not enabled by ordinary actions or by startup. No game/world has been launched by its implementation or offline checks.

## Wire API

All four endpoints retain the existing loopback/authentication boundary and execute operations on the Minecraft client thread.

- POST `/control/fall-rescue/arm`
- POST `/control/fall-rescue/renew`
- POST `/control/fall-rescue/disarm`
- GET `/control/fall-rescue/status`

The existing capability response includes `native_fall_rescue`. Arm body:

```json
{
  "fall_rescue_schema_version": 1,
  "arm_id": "unique-arm-id",
  "owner_id": "authorized-controller-id",
  "expected_action_session": "from-current-action-status",
  "expected_world_generation": "from-current-world-state",
  "expected_player_uuid": "from-current-player-state",
  "ttl_ms": 60000,
  "max_episodes": 1,
  "permitted_action_ids": ["exact-action-id-that-may-be-interrupted"]
}
```

An empty permitted-action list allows idle rescue only. Preemption is limited to explicitly listed action IDs and the native movement/combat/consume/selection action allowlist. Raw-held inputs, another guarded-movement owner, an unknown external owner, and unsupported action types fail closed. Baritone's presence is conservatively `fall_rescue_external_controller_unknown` in v1 because no verified idle/stop adapter is implemented. This means installed-but-idle Baritone is also refused, not falsely reported as active.

TTL is 1,000–600,000 ms; default 60,000 ms. Max episodes is 1–16; default 1. A renewal supplies schema, same arm_id/owner_id, `expected_arm_revision`, and ttl_ms. Every successful renewal increments arm_revision; a lost response is reconciled through status, never blindly replayed. An expired/stopped arm cannot be renewed or revived by reusing its ID. Disarm supplies schema, arm_id and owner_id. Up to 128 arm IDs are retained per process; history is never evicted to permit replay.

Release-all, close, bridge shutdown, explicit pause, screen opening, disconnect, player clone, world unload, or context drift revoke the lease. Explicit stop returns manual control. The rescue never resumes an interrupted job, restores its aim/slot, retries an unknown native call, or performs an offhand fallback. Ordinary automation admission remains blocked if any effect or predecessor outcome is quarantined. V1 has no quarantine-clear API; investigate and explicitly restart the isolated runtime rather than treating disarm as proof of a known result.

## Native path and scope

Each client Pre/Post tick observes the current player, health, fallDistance and velocity. The bounded 60-step forecast uses ordinary airborne drag/gravity and native `Entity.collideBoundingBox` against actual loaded collision shapes. It refuses side/ceiling collisions, moving collision entities, nonordinary physics/effects, unknown chunks, out-of-range motion, void/unknown landing, Nether, and custom dimensions.

Only Overworld/End, supported inert vanilla full-block top surfaces, and two air cells above the surface are currently supported. The allowlist is in FallRescueGeometry. This deliberately excludes waterlogging, plants/replaceables, slabs/stairs, hazards, fluid landings, modded surfaces and automatic pearls. No velocity, position, fallDistance, health, game rules, block state, or server physics is directly changed by this feature.

The engine can acquire and prepare during a dangerous upward knock-up. It selects an existing one-count vanilla water bucket from the hotbar, cancels the exact permitted old owner, confirms release and mainhand binding, then waits for descent and actual native eye reach/raycast to the supported UP face. A one-shot dynamic token calls `gameMode.useItem(MAIN_HAND)`. It never holds the use key. Existing `use_item` EAT/DRINK and existing grounded placement scopes are unchanged.

The single-input arbiter is acquired before old-owner cleanup. Reentrant/new direct, guarded, movement/combat, aim and slot action admissions are blocked while the rescue owns input. Actual bucket entry, the final vanilla client `Level.setBlock` call, and the ordinary outbound `ServerboundUseItemPacket` send are fenced. Stop revokes the token before cleanup. Old callbacks cannot release a replacement owner.

An airborne episode has at most one native use attempt and a 200-client-tick budget. A thrown call or FAIL return is not proof of no effect and is never retried. Every interrupted active action is annotated unknown/no-auto-resume/requires-reconciliation, since legacy dispatched flags do not prove absence of effects, and quarantines subsequent automation after the rescue. Automatic old-combat terminal-pause is deferred only for this specific authorized preemption; explicit user pause still revokes rescue immediately.

## Outcome evidence

Client water prediction, native return, packet-send fence, server water observation, server bucket transition, and server landed-alive observation are separate fields. Read-only server samples run asynchronously on the integrated-server thread, at most one queued sample per episode, and cannot block the client tick. Before dispatch a server baseline must observe air in the intended water cell and the selected hotbar slot holding a water bucket. After dispatch a later server tick must observe water and bucket transition, followed by alive landing in the target area.

`server_placement_and_landing_observed` means correlated authoritative state was observed. It is not a dedicated protocol acknowledgement, proof of counterfactual death prevention, or a future safety guarantee. Client prediction and native SUCCESS alone never claim rescue confirmation.

## Offline evidence and remaining acceptance

Production compilation, property/fault/Java-wire checks, and bytecode-only Mixin transformation are separate checks. No fake game adapter result is represented as a successful real clutch. Actual NeoForge launch/linkage, tick/network timing, ordinary-world knock-up/fall geometry, interruption by real gameplay hooks, real water placement, landing damage, cleanup and server observation still need acceptance in a clearly labeled independent test copy. The original world remains untouched.
