# MDC combat-loop.5: bounded pursuit and swept corridor candidate

Version: `1.1.7-combat-loop.5`. Offline candidate only; not installed, not live tested, and not an accepted combat-performance release. The source was extracted into a new isolated directory from the verified `.4` candidate archive (SHA-256 `6981b7a4128e2a43fd172fac077cc32c7e717b827c1433e4e2bd9624f1998ebf`); all 243 baseline source checks passed before changes.

## Why this candidate exists

The retained `.4` live evidence has six skeleton failures: iron 0/3 target deaths and diamond 0/3, with four `no_closing_progress` and two `local_flat_corridor_blocked`. Two observed airborne episodes recovered in the same action, each using 11 recovery ticks; all six actions released their inputs. These are observations, not equipment capability conclusions. Diamond trial 1 was clear; the other five skeleton setups and matching-action samples were raining/thundering. The weather correction remains authoritative, so these trials are not a weather-controlled armor comparison.

The historical-minimum distance watchdog could stop renewed closing that had not beaten its all-time best. One retained trace moves from 3.452 blocks to above 4.3 and then back to 3.563 at failure. The continuous shield hold during out-of-reach pursuit also applies ordinary item-use movement slowdown. No projectile interception or actual win-rate improvement is asserted here.

Two supplied grounded pose/direction reconstructions expose the swept-rectangle corner error. The old rectangle includes column (15,21); the continuous translated square covers only (14,21), (14,22), and (15,22). The supplied grass block at (15,64,21) consequently should not reject those mathematical paths. The position, later yaw, and terrain observations were not atomic, so this is a deterministic geometry reproduction, not proof of the exact failing live tick.

## Changed behavior

### Limited ranged approach rhythm

Only `skeleton`, `stray`, and `bogged`, with the requested available offhand shield, alternate an 8-client-tick stationary shield request and a 12-client-tick unshielded normal-forward approach. Each cycle starts defensive. These numbers are uncalibrated candidate policy, not an optimized timing claim. A skipped tick consumes its place in the cycle; calls do not restart it. Shield cooldown/absence removes the defensive stop. Actual item-use/blocking observations remain separate from requests.

No sprint is introduced. Unshielded approach waits rather than advancing if item use remains active after owned shield release. Defensive approach checks the actual stationary footprint, and forward approach checks a fresh .65-block corridor. Fresh in-reach target selection immediately returns to the existing cooldown, shield-lowering, ray/reach and protected-bystander attack path. Existing melee approach shielding and creeper retreat policy remain unchanged.

### Recent, bounded progress

`CombatPursuit` evaluates one-second observation windows using current player and sticky-target positions. A distance reduction of at least .04 blocks is recent closing, even if it does not beat an older minimum. At least .10 blocks of net player displacement projected toward the window's initial target is own forward progress; target displacement along the same bearing distinguishes retreat. These thresholds are conservative offline values that still need live calibration.

Three seconds with neither recent closure nor own forward progress terminates as `approach_stalled`. Movement without closure or observed target retreat terminates as `no_closing_progress`. Observed player advance plus target retreat permits at most six seconds without closure (`target_retreat_no_closure`). Separately, cumulative windows classified as non-closing have a six-second per-action budget (`pursuit_no_closure_budget`), never refunded by later progress, target reach, window changes, or recovery.

Verified landing rebases only local motion references. Its unfinished pursuit window, including recovery waiting time, is conservatively charged to the cumulative budget. Genuine fresh target pick/reach may finish an unclassified partial window as actual closing evidence; it does not refund earlier charged windows. The cumulative budget is enforced on the next approach sample. Recovery WAIT does not cancel immediately when that budget expires, but remains zero-forward/no-attack and subject to its unchanged 20-tick episode limit and the original action deadline. The original action deadline (at most 30 seconds) and 12-block area guard remain independent and unchanged.

### Exact continuous square sweep

`FlatStepCorridor` clips the center segment against each cell expanded on both axes by the ±.31-block square footprint (Minkowski sum). Both axes share one time interval over [0,1]. This is a translated axis-aligned square, not a circle or endpoint-only sample. Broad-phase diagonal corner cells are removed only if no common time intersects both axes. Outward epsilon 1e-7 and closed bounds retain tangencies conservatively.

Every intersected column still requires all three loaded layers: full top support below, empty feet/head collision, known collision, empty fluid and no listed hazard. Invalid/unloaded/unknown/out-of-world cells, shape-context failure, partial-height landings and unsafe cells fail closed. No cached terrain page or chunk loading is introduced. `TerrainReader.flatStepClear` remains a compatibility wrapper; only native combat uses the new structured result.

## Evidence additions

Existing schema remains compatible; `pursuit_diagnostics_schema_version:1` identifies additions.

- `combat_tick`, `decision_phase`, `requested_forward`, `decision_pose`, `shield_owned`, `using_item_after_decision`, `blocking_after_decision`: current client-thread decision facts. Decision input is not proof of the subsequent physics result or terminal cleanup.
- `motion_since_previous_decision`: player/target dx/dy/dz, forward projection and distance change, attributed explicitly to the previous decision phase.
- `phase_motion_observed`: accumulated observed player/target horizontal distance, forward projection and interval counts per previous phase. Displacement includes ordinary momentum/knockback; it is not causal input attribution.
- `pursuit`: local closing, own/target projected displacement, cycle tick, local no-closing/no-advance times, cumulative charged no-closing time and diagnostic classification.
- `corridor`: clear/reason, actual pose/yaw, requested dx/dz, direction (-1 retreat, 0 stationary, 1 advance), and exact rejected cell x/y/z/layer/id when applicable.
- `corridor.evaluated_tick` and `pursuit.evaluated_tick` identify their last check; retained evidence must not be mistaken for a new check during a later attack/recovery phase. `decision_pose` is current.

Cell rejection reasons include `unloaded`, `out_of_world`, `unknown_cell`, `collision_unknown`, `fluid`, `hazard`, `missing_support`, `feet_collision`, `head_collision`, and `cell_read_failed`. Pose/step failures are separately named. The enclosing action still uses `local_flat_corridor_blocked` or the existing recovery landing refusal, preserving established terminal handling.

## Safety and scope preserved

`CombatRecovery.java` and `ClientActions.java` are byte-identical to `.4`: 20-tick bounded recovery, zero-input/no-attack waiting, two settled samples, fresh landed corridor, fixed deadline, cancel/direct takeover/manual view, GUI/death/world/player changes, sticky entity identity, protected sword sweep and cleanup remain. Ordinary `follow_path`, endpoint settlement/sprint behavior, and Python watchdog/controller code are untouched. The legacy Python combat airborne limitation, sustained creeper disengagement/explosion safety, multi-enemy strategy and Ender Dragon are not repaired or accepted by this work.

## Verification

See `manifest.json` in the delivery package and included logs for exact final counts and hashes. New tests execute deterministic pursuit and swept-geometry/cell-policy helpers. Source-contract tests assert integration ordering and unchanged guards but do not execute Minecraft. Dense-path reference sampling is additional regression evidence, not a proof replacing the continuous intersection derivation.

Final clean Java test/build: 186 tests, zero failures/errors/skips. New coverage is 16 executable pursuit-helper tests, 17 executable corridor-helper tests and 4 source-string wiring tests; actual Minecraft client integration tests: zero. Eight Python suites discovered 768 tests, 767 passed and one skipped. (The earlier .5 delivery summary totals 868/867 were an arithmetic error; the individual preserved suite logs were correct.) Standalone audits passed 37,371 terrain-core, 13 terrain-dispatch and 150 guarded-action checks; 8 Node framing tests passed. The full existing Java test/build, Python suites and standalone core/terrain audits were run offline. One historical watchdog comparison test remains skipped because its frozen old source is absent. The unchanged Windows-path MCP launch/registration self-test was not run on this Linux host; framing tests do not replace that platform-specific suite. The first wrapper attempt could not download Gradle; the already-cached official 8.14.3 distribution was then checksum-verified and used offline successfully. No game process, input/IPC queue, credential, backup lock or publication allowlist was used or changed.

Required live acceptance is in `acceptance/LOOP5-LIVE-CHECKLIST.md`. Installation and live testing require separate operator authorization; this document does not grant it.
