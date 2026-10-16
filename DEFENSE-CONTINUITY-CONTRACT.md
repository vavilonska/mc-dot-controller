# Scoped defense observation continuity and retreat execution

This is the r2 independent, offline source candidate based on the frozen T44 runtime.
It is not an installed product or a new live acceptance result. T44's functional
result remains failed; T43's earlier unknown action remains unknown and must not
be replayed. Historical publication inventories in this checkout are not a
manifest or release approval for these new changes.

## Live facts motivating the change

T44 successfully consumed a typed stop proof larger than the former 16 KiB limit,
preempted ordinary movement before motion and started the explicitly requested
`defend_once`. The combat action dispatched one attack and observed a target
health decrease, but no blocking tick. A 161.079773 ms interval between two
healthy client observations latched an observation gap; withdrawal then rejected
a clear first window taking 15.439656 ms against an 8 ms planning budget. Only
one of the required five windows had completed. No unsafe movement was issued.
This establishes the stop-proof repair's live path, not full defense success.

## Scope and unchanged authority

Only native `ScopedCombat` enables observation recovery or the new retreat path.
Legacy bounded combat and encounter mode retain their previous policy. The public
intent/API, supported target types, bound owner/job/world/target, effect-count
limits, action timeout, input release and unknown-outcome rules are unchanged.
No interrupted ordinary task resumes. This candidate neither submits a new public
job nor replays a prior native action.

## Health observation interruption

The existing 150 ms observation and threat-freshness thresholds are not increased.
A wall-time-only health sampling gap with valid clocks, advancing bounded action
ticks and healthy observations enters a separate recovery state instead of
permanently latching a withdrawal cause.

- Recovery requests zero forward input, performs no attack and does not change
  the view. This is not proof that external velocity or knockback is zero.
- Only the explicitly requested shield may be used, through the original scoped
  effect/packet/owner/context/deadline gates. A WAIT is not a claim of no effects.
  Original cleanup and unknown-effect handling still apply.
- A full existing one-second rolling-loss window of fresh advancing client
  observations with strictly advancing action tick, actual ClientLevel game time,
  and monotonic observation time is required before offense can resume. Adjacent advancing samples
  must be at most 150 ms apart; same-tick callbacks cannot advance recovery or
  bridge missing advancing samples. Another gap restarts only this quiet window.
- Every observed loss is retained. Any loss at a gap or during recovery, low
  health, invalid health/clock, missing action ticks beyond the existing bound,
  or a frozen tick irreversibly stops offense for this action. Healing cannot
  erase that latch. The usual risk-remaining withdrawal may still be considered.
- No loss-history reset, new owner, deadline extension, attack-budget refund or
  catch-up attack occurs. After recovery, fresh single-target threat, sweep,
  renderer pick, reach, cooldown and final effect checks are still mandatory.
- Evidence distinguishes current recovery samples from actual irreversible
  latch trigger samples. An unobserved interval remains unproven; neither an
  unchanged current health value nor a shield input proves safety or a block.

## Retreat: scheduling is distinct from execution permission

The previous 8 ms hard-admission semantics intentionally change only for scoped
combat. Eight milliseconds remains a diagnostic scheduling threshold. It is not
replaced by an arbitrary larger planner constant. Work is structurally limited:

1. A pure proposal contains only a heading/goal and candidate index. At most one
   candidate is considered per action tick, with at most 16 candidates total.
2. Each candidate is validated completely from the actual current pose, using
   all 0.65 m windows of the 3 m route (maximum seven). The center terrain,
   expanded envelope, loaded-cell status, hazards, dynamic bodies and clearance
   from every observed threat remain required. No partial clear result resumes
   at a later window on another tick.
3. Candidate geometry may be retained. Its clear verdict and cell cache cannot
   authorize later movement. Every subsequent pre-tick attempt and the final
   movement-input callback independently capture fresh observations and fully
   revalidate the remaining route. The immediate actual-heading envelope is
   checked as well.
4. The original same-callback 50 ms, game-tick, owner/context/target and 150 ms
   snapshot freshness checks are hard boundaries. Pre-tick planning inherits the
   original `tickCombat` callback start; it cannot mint another 50 ms budget.
   Final tick diagnostics are followed by the same original frame check. The
   genuinely separate movement-input callback has its own original start and
   final full-route permit.
5. No mutable scoped guard hook is run after that final input permit. Raw owner,
   input identity and neutral-input checks remain before writing forward input.
6. Ordinary observed geometry refusals may advance the bounded heading cursor on
   another tick, with zero forward input. Unknown/stale data, exceptions,
   unrecognized refusal reasons, hard context/freshness failures and invalid
   clocks stop the attempt. They never cause a retry or inherited permit.
7. The 60-tick / 3-second / 4 m withdrawal limits, 12 m combat area and observed
   progress requirements are unchanged. Retreat still reports risk remaining,
   never guaranteed safety or a server-confirmed combat outcome.

## Offline verification and limits

Reproducible Java checks live under:
- `client-mod/validation/defense-continuity/`: exact T44 health interval, adversarial
  state transitions and unchanged compiled recovery/evidence helper replay.
- `client-mod/validation/scoped-retreat/`: deterministic full-window scheduling,
  boundary/capacity/unknown cases and unchanged compiled movement/frame/tick replay.

The replay uses actual compiled production instruction streams with explicitly
aliased Minecraft, timing, owner and selected effect/environment doubles. Actual
pure health, threat, terrain, envelope and route policies run directly. This is
stronger than source-string assertions but is not Minecraft/FML lifecycle,
network, packet-hook installation, actual shield activation or real-world physics
acceptance. Java compilation does not constitute a release JAR build.

The superseded r1 candidate is blocked: client pre-tick callbacks continue during
`/tick freeze` while source game time does not advance. Its action-only recovery
clock could incorrectly resume offense. r2 binds both decision and final attack
health reads to the actual source world clock; missing-source recovery calls fail
closed. Actual paused-context rejection remains unchanged and a latched action
cannot revive after unpause/unfreeze. Offline pause-like sampling tests are not
claimed as a running client pause lifecycle test.

A separately reviewed, matching runtime and a fresh job in an independent ordinary
singleplayer test copy are still required to establish blocking observation,
healthy-gap recovery, genuine low-health withdrawal and normal cleanup/save.
Existing unknown actions cannot be used for that trial.
