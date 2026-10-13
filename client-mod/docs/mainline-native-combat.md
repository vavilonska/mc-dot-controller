# Mainline frozen-v18 native combat and encounter closure

This offline integration is based on mainline commit
`9325427300b71ff5e61eec458db7ba213a3db4d7`. Its native combat source is the
published frozen v18 `candidates/encounter-stage1.1` snapshot, not the moving
P2 or coordination candidate. No game, deployment, runtime-property change,
multiplayer connection, or external publication is part of this change.

## Explicit new API surface

The eight existing actions remain: `follow_path`, `break_block`, `place_block`,
`click_slot`, `recover_environment`, `boat_drive`, `boat_mount`, and
`boat_dismount`. The only additional action is `combat_entity`.

Single-target combat requires the exact world, player, action session and target
ID/UUID/type bindings, a selected supported weapon, and a 50–30,000ms action
lifetime. It supports only the frozen request allowlist: zombie, husk, zombie
villager, skeleton, stray, bogged, and creeper. Creeper admission is withdrawal
only. This API does not replace mainline's existing resident NativeCombat service,
its all-hostile behavior, or the watchdog's producer and owner policy.

`encounter_mode: "two_zombie_retreat_v1"` is the only encounter mode. Its scope
contains exactly two distinct ordinary zombie ID/UUID/type identities and the
selected target must be in that scope. Both `approach` and `shield` must be
explicitly false. Unknown fields and encounter fields on other actions are
rejected before input takeover. There is no three-zombie or coordination action.

Encounter execution remains default-disabled unless JVM boolean property
`mineclientBridge.encounterRetreatStage1Enabled` is true. The disabled start
returns `encounter_stage1_disabled` before ownership/input mutation. This change
does not set the property or authorize runtime enablement.

A new authenticated `POST /control/pause` route takes exactly:

- `pause_schema_version: 1`
- `expected_action_session`: canonical session UUID
- `expected_world_generation`: canonical world-generation UUID
- `expected_player_uuid`: canonical player UUID
- `expected_action_id`: 1–128 ASCII letters, digits, underscores or hyphens

This is a private-singleplayer-only, identity-bound, non-toggling operation. It
uses the existing game-thread operation boundary and opens `PauseScreen` through
`pauseGame(false)`. It rejects a foreign guarded or native owner before mutation,
rechecks identities and ownership after reentrant screen hooks, and never cancels
a newly installed foreign owner. Opening the screen is not proof that the
integrated server has paused. Late failure is an unknown outcome, not a definite
admission rejection; unknown actions are not retried.

Optional boolean `encounter_pause_on_terminal` belongs only to an encounter.
Its private-singleplayer admission check runs before input takeover. Its native
terminal hook runs only after the original receipt and cleanup result have been
published, at most once, without changing that terminal outcome. A prior attempted
terminal hook cannot trigger a new HTTP screen-opening attempt. An already open
pause screen can be acknowledged without toggling it.

## Lifetime, release and evidence preservation

- Combat computes its one deadline before bounded constructor admission and shares
  it with the encounter. Every old non-combat action still computes its deadline
  in `RuntimeAction`, after input release and registry begin. Recovery's zero
  timeout still maps to `Long.MAX_VALUE`.
- The existing world/player/session/navigation checks precede new ownership. The
  old actions retain their previous world/player rejection reasons; new combat
  uses its frozen `action_world_changed`/`action_player_changed` reasons.
- Pre-tick, movement-input and post-tick retain the position epoch guard. Encounter
  callbacks additionally enforce lifecycle, deadline, wall budget and observation
  freshness before they reuse movement. No check can guarantee physical release
  while the game thread itself is stalled.
- Only the already managed path/boat/discontinuity owners and new combat owners
  use confirmed terminal cleanup. Recovery, ordinary mining/placement and inventory
  actions retain their original terminal ordering and field behavior. Combat
  cleanup failure cannot publish success; it records `input_release_unconfirmed`
  in both the registry and encounter terminal evidence before the pause hook.
- Environment recovery and the complete stable mining/placement method regions
  remain byte-preserved from mainline. The existing sprint, boat release and
  discontinuity attack-release semantics are retained.
- State adds the real observed combat fields advertised by
  `combat_observation_schema_version: 1`: sprint, attack strength/speed, interaction
  range, item-use/blocking/use-tick/shield cooldown, and living-entity hurt/use/mainhand
  fields. All previous environment and bounding-box observations remain present.
- The existing path-scoped `BridgeJson` nullable contract is retained unchanged.
  Unknown encounter outcome, callback clock anchors, pause observations, and absent
  action/release proof remain explicit JSON null at their defined paths. Other
  historical null encoding is not broadened.

Encounter success means only three fresh complete samples of the two exact living
zombies beyond the frozen clearance bound with settled movement and no continuity
or health failure. Every terminal still carries `requires_handoff: true`,
`risk_remaining: true`, and `safety_assured: false`; it is not proof of kills,
server confirmation, general safety, or permission to reacquire combat. The
request-owned resident/watchdog handoff consumer is a separate companion slice
required before broader producer activation.

## Imported source and test accounting

Fourteen complete production classes are copied byte-for-byte: `BoundedCombat`,
`BoundedCombatRequest`, `BoundedEncounter`, `CombatInitialEvidence`,
`CombatRetreatDiagnostics`, `CombatRetreatEvidence`, `CombatRetreatPolicy`,
`CombatRetreatWindow`, `CombatRouteEnvelope`, `CombatRouteMotion`, `CombatRules`,
`EncounterRequest`, `EncounterPause`, and `EncounterTerminalPause`.

Thirteen previously absent frozen combat/encounter/pause test files are imported
in full without removing assertions. Frozen `BridgeJsonTest` and
`BridgeServerContractTest` are additionally retained in full with only class/file
renames to coexist with original mainline regression files. New
`MainlineCombatSliceTest` covers cross-action preservation. Existing intermediate
boat/path/position slice tests update only intentional surface/phase assertions.

The original mainline `BridgeServerContractTest` changes only its explicit
endpoint count from 24 to 25, matching this authorized new route. All its other
assertions remain unchanged. Other original regression files remain untouched.

`IntegratedCandidateContractTest` and `ExpeditionPrerequisitesContractTest` are
explicitly deferred as complete cross-slice contracts: they require the still
absent `BoundedContainerSnapshot` feature. Their container assertions are not
removed or reported as passing. This integration does not claim the full frozen
candidate suite passes. Pure startup class initialization through
`RetreatClassInitialization` is also not included; first-use class loading remains
possible and is not represented as warmed runtime performance.

The offline result and source/file hashes are recorded in the accompanying
integration verification report. JVM tests instantiate pure state/geometry/receipt
helpers and compile the Minecraft adapter; they do not instantiate a real client,
exercise actual input/mod callbacks or prove live physics/AI/pause propagation.

## Verified offline result (2026-10-08)

One coordinated Java21/Gradle 8.14.3 offline `test build` ran from 16:37:14 to
16:37:49 UTC with one worker and `-Xmx768m`: 587 tests across 59 suites,
zero failures, errors or skips. All eight Gradle tasks executed. This count
includes the two complete renamed frozen regression files; it is not a claim
that the two deferred container-wide contracts executed. The production JAR
contains no test/fixture classes. No production source changed after that run.
