# Bounded encounter continuation, stage 1

Candidate: `1.1.7-encounter-stage1.1`, independently copied from `1.1.7-integrated.3`.
Offline only. Zero real-game executions, no deployment, no running `.3` changes,
no game/UI/IPC/credential/backup/Drive/GitHub operations. Construction remains deferred.

## What this implements

An explicit `combat_entity` mode, `two_zombie_retreat_v1`, holds one native
`RuntimeAction` and one exact world/player/session/scope. It never invokes
`combat_start`, the old watchdog, or another action to renew its budget. Scope
contains exactly two distinct zombie ID/UUID/type identities, including the
legacy target. Both must be observed alive at the first native snapshot.
Offense and shield choreography are disabled throughout this mode.
Legacy single-target requests with neither new field keep their existing path.

The production `BoundedEncounter` state machine is called from `BoundedCombat`
before the legacy target-missing return. It uses the same actual bounded threat
capture, typed loaded-cell cache, dynamic obstacle boxes, `CombatRetreatWindow`,
`CombatRetreatPolicy`, `CombatRouteMotion`, action registry, and input cleanup.
Java replay calls this actual state machine and window composition with synthetic
observations; it is not a replacement planner or fake live-game acceptance.

A changed threat identity, disappearance/death, or observed clearance decrease
revokes the current route, returns zero input, and retains the same owner. Only
on a later fresh snapshot can a new route be checked. A new out-of-scope zombie
or unsupported dangerous entity terminates the limited scope instead. Creeper
and Enderman refusals preempt a previously latched health cause. No spider,
Enderman, creeper, skeleton or other new offense is admitted.

A missing selected target does not skip the other scoped zombie. The remaining
observed scoped zombie can still inform a legal retreat after revocation. Missing
or dead identities are never credited as kills and cannot establish completion.
No retargeted attack is implemented.

## Shared budgets, deliberately limited capability

- The original action deadline is computed once by `ClientActions` and shared.
- The combat origin remains fixed, with the existing 12-block area bound.
- One `HealthGuard` and its original loss history persist across all segments.
  Its current diagnostic continuity is also checked independently of a latched
  low-health/rapid-loss trigger. Healing does not clear that trigger.
- Entire encounter: at most 60 observed ticks, 3 seconds monotonic wall time,
  and 4 blocks accumulated observed three-dimensional movement. Revocation,
  segment arrival, target loss and replanning do not refund these quantities.
- New segments are at most 1.5 blocks. They shrink against the existing remaining
  distance, reserving the unchanged 0.65 movement probe. An insufficient remainder
  is an explicit failure with risk remaining and a required handoff.
- Every plan/revalidation still uses the original 8ms cooperative check budget;
  the unchanged snapshot maximum age is 150ms. The candidate does not increase
  the cold-start budget or solve its previously observed first-window cost.
- Planning may admit a new movement request in the same tick only after all
  windows and native motion checks pass against that current snapshot within
  that same check deadline. A revocation tick never replans or moves.

This is bounded defensive continuation, not prolonged survival control. All
physical displacement is observed, not simulated or commanded exactly. An
external hit or a stalled client thread can carry the player past an observed
limit before the next check; this code cannot enforce a physical hard stop.

## Completion and handoff

Walking a segment is not success. Completion requires three consecutive fresh,
complete snapshots showing both exact scoped zombies alive with horizontal
clearance above 8 blocks, settled player motion, no scope/clearance continuity
break, and no health interruption. This only substantiates the named finite
postcondition `two_scoped_living_zombies_beyond_8_for_3_samples`.

Even this limited success reports `risk_remaining:true`, `requires_handoff:true`,
`safety_assured:false`, no attack completion, zero attack dispatches, no observed
kill and no server confirmation. The operator remains responsible for the still
living enemies after this finite action. No route, unknown data, unsupported
scope or exhausted budget fails without inventing safety or certain no-route
knowledge. Exact original route rejection maps and diagnostics remain in receipts.

Pause, window-focus loss, cancellation, world/player/navigation identity change,
and unavailable player terminate through normal `ClientActions.finish` cleanup.
Every existing pre/input/post context callback also checks the original deadline,
3-second encounter budget, and actual captured snapshot's 150ms age before it can
reuse an input request. Current health gaps/invalid samples are fail-closed even
when an older health trigger is latched. Cleanup failure downgrades success and
reports `input_release_unconfirmed`; terminal metadata explicitly zeros movement
and labels previous decision fields as historical.

These checks execute when the client thread runs. They do not promise release
within 8ms or 150ms during a stalled thread, and actual OS/physical key release
has not been observed in this candidate.

## Default-closed gate and future enablement

The mode is fully wired into the native action implementation, but its start
requires JVM boolean property `mineclientBridge.encounterRetreatStage1Enabled`
to be true. The default is false, and this candidate does not set it. A disabled
start returns HTTP 409 `encounter_stage1_disabled` before action ownership or
input mutation. Old mode does not inherit this new permission.

After reviewing this candidate and deciding to proceed, the sole authorized
operator would:

1. Verify the artifact/checksums and establish a normal local test world, explicit
   safe-stop plan and the exact two ordinary living zombie identities. NoAI
   results are not substitutes for active-AI acceptance.
2. Stop and verify old automation/input ownership according to the existing
   operator procedure. Keep the old watchdog stopped and multiagent live gate
   closed; never start an additional writer.
3. Separately authorize and perform candidate installation/restart with the
   explicit JVM argument `-DmineclientBridge.encounterRetreatStage1Enabled=true`.
   This document does not perform or authorize that change.
4. Re-observe version, world/player/action session, navigation binding, focus and
   scope. Use the single native action entry with explicit approach/shield false.
   The original request and exact terminal receipt must remain linked.
5. Observe the full action and post-terminal risk. Any admission rejection, missing
   proof, damage, rescue intervention, loss of input-release evidence or unsupported
   scope is a stop/report condition, not a reason to resubmit with a fresh budget.

For request/receipt schema and controller behavior see
`../resident-controller/docs/ENCOUNTER_STAGE1_CONTRACT.md`.

## Verification boundaries and remaining matrix

Offline checks cover production Java state/retreat composition, strict native,
Python and MCP parsing, emitted native receipt validation, dynamic snapshots,
shared distance/time/deadline conservation, health latch/current continuity,
identity replacement/loss, unsupported scope, route refusal, pause/focus/cancel
terminal states, registry cleanup outcome and no automatic action replay.

The native Minecraft adapter compiles but is not instantiated in unit tests.
Actual entity capture, renderer mutation, client event scheduling, physical input
release, active-AI response and game physics remain unexecuted. Some old tests are
source-contract checks; they are not counted as live acceptance. Test totals and
any skipped regression are listed in the accompanying verified test summary.

| Scenario | Current status | Required next evidence |
| --- | --- | --- |
| Two active zombies, same-direction pursuit | Synthetic dynamic replay only | Ordinary local-world active AI; full bounded action and handoff |
| Two active zombies, flank/pincer/obstacle/knockback | Guard/geometry synthetic cases; no gameplay | Dynamic collision/inertia and actual no-route response |
| Cold/warm checks and long client ticks | Existing 8ms cutoff; offline clock probes | Actual cold/warm distribution and delayed callback release |
| Pause/focus/cancel/world change | Native lifecycle/registry code and synthetic probes | Actual game input release on each callback path |
| Zombie + skeleton | Explicitly unsupported by this mode | Separate defensive facing/shield strategy and live arrow evidence |
| Zombie + spider + skeleton + creeper | Stops on unsupported/creeper scope | Later mixed-defense stage; no accidental sweep or explosion-safety claim |
| Spider/Enderman offense or multi-target kills | Not implemented | Separate authorized design and validation |
| Construction | Deferred | All requested optimization/acceptance stages complete first |

Stage 1 passing offline does not mean all requested optimization is complete.
