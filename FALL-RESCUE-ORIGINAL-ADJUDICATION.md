# Explicit release after an interrupted attached rescue

Version: `native-fall-rescue-original-adjudication/1`. Private unpublished integrated
singleplayer only. No live acceptance claim is made by the offline fixtures.

## Public operation

Use the retained original `job_id` and its `session_ref` with `mdc_job`:

1. `operation: "adjudication_prepare"` reads the retained original receipt and
   returns `adjudication.selector.original_receipt_sha256`. This is a local evidence
   check; `current_release_proof_observed: false` means current native admission has
   not yet been established.
2. Explicitly request `operation: "adjudicate"`, a new bounded
   `adjudication_request_id`, that exact `original_receipt_sha256`, and the exact
   acknowledgment string:
   `release_authority_keep_original_effects_unknown_no_resume`.
3. If the response is lost, pending, or unconfirmed, request only
   `operation: "adjudication_status"` with the same original job, session,
   adjudication ID, digest, and acknowledgment. Do not create a new adjudication ID
   or retry the original gameplay action. Native mutation is attempted once;
   subsequent settlement reads the same native adjudication ID.
4. A refusal may explicitly return `native_write_never_attempted: true` and
   `next_operation: "adjudicate"`. Only this positive retained pre-POST evidence
   permits an explicit same-ID request to continue the first native write after
   the prerequisite is fixed. A status request itself never starts that write.
   Missing, lost, or already-attempted write evidence never authorizes replay.

The original job remains `state: "unknown"`, with its semantic result, effect
certainty, immutable receipt, and action ID retained. The separate
`authority_adjudication` records release of control authority, not success of the
old task. A newly requested job gets a new owner and must pass normal fresh
admission. No old task is resumed or replayed.

## Exact v1 scope

Only an ended attached episode with authoritative confirmed rescue, the exact
original-action quarantine, and a retained original UNKNOWN receipt is eligible.
The original owner ID/generation, job, gateway/Resident/native sessions,
world/player, native action, episode, sealed receipt digest, and arbiter revision
must agree. The native game thread freshly checks private-world context, external
controller idle, no active MDC action, no rescue owner, and neutral input. It then
clears only `native_fall_rescue_original_action_quarantined` by exact-revision CAS.
Callbacks changing owner/world/pause fail closed. A recorded release alone cannot
settle a fresh read when the current context or input proof has changed.

Failed or partial rescue, uncertain input release, a different quarantine,
standalone guard episodes, a replacement controller session, user stop, multiplayer,
Nether, or unknown external control is outside this v1 scope. There is no general
unsafe override, blanket reset, restart-based settlement, or journal-edit workflow.
The release proof explicitly says `physical_safety_guaranteed: false`.

## Serialization and durability

- The normal owner mailbox carries the request; no second gameplay writer or
  parallel owner thread is introduced.
- Native POST `/control/fall-rescue/adjudication` is once-only. Authenticated GETs
  `/prepare` and `/status?adjudication_id=...` are read-only.
- Native records retain 128 exact adjudication IDs without eviction. Resident and
  gateway ledger capacity is 128; Runtime caps read controls at 64 per ID.
- Every layer persists its exact identity before the one write. Lost native,
  gateway, or backend responses are covered by same-ID read recovery tests.
- The gateway releases only the exact paused original lease. It persistently
  suppresses automatic legacy tactics afterward (`explicit_new_job_only: true`),
  while separately requested, scoped capability jobs can be admitted. Stop remains
  higher priority. A later duplicate acknowledgment is cached and cannot touch a
  replacement owner.
- Known HTTP envelopes require exactly `protocol: "mineclient-bridge"` and integer
  `schema_version: 2`. They are normalized before the existing closed payload
  validators; unknown fields and evidence regressions still fail closed.

## Offline evidence

Production native full-source compile is capped at 384 MiB. Pure parser/ledger/CAS
checks run at 128 MiB. The canonical acceptance test passes production Java receipt
and parser output through `ActionResponses`, exact `BridgeJson` bytes, the actual
Python Bridge loopback HTTP transport, then real Resident/gateway/Runtime/public
validation. Other fault tests model only native game observations and effects.
No Minecraft physics, latency, or guaranteed rescue success is inferred from these
fixtures. Integration and sole-operator live QA remain separate gates.

## Final context proof boundary

Adjudication and its read-only inspection sample external idleness and neutral inputs first, then re-read the private survival context, exact integrated server identity/publication, and original player identity. A final pure check binds player/level/game-mode references, fall operation, action owner, arbiter revision, action session, and the existing world generation. The world check never creates or refreshes a generation.

This supports the pinned vanilla leaf getters under cooperative mods. It does not claim protection from an arbitrary injected getter that lies about its own result or changes unrelated private fields after returning. No game-event observer, new access credential, or new controller is installed. Offline callback probes test invalidation at the exposed proof boundaries; they are not a live-game timing claim.

The gateway persists its acknowledgment and explicit-only marker before release, then re-reads Resident readiness and checks exact retained owner/lease/attempt identity and proof age. Only then does it release local authority and checkpoint that release. Delayed persistence or a replaced owner leaves authority unresolved; a new same-ID status read can obtain fresh evidence without a second native write.

## R3: preserve the explicit control lane across inbox scan boundaries

A deterministic offline run reproduced a failed first adjudication in 119.8 ms,
with zero native POSTs. Its original durable gateway receipt was `cancelled /
watchdog_interrupted_replan_required`. This was not a one-second proof-freshness
failure: a control published after the loop's first control scan was consumed by
ordinary inbox cancellation while the original owner was paused.

`cancel_waiting_intents` now leaves only the existing enumerated `CONTROL_OPS`
for the same loop's next validated control scan. It does not move, acknowledge,
execute, or authorize those files. Existing session/operation/owner/context/stop
checks remain authoritative. Ordinary queued gameplay is still cancelled.
Deterministic event barriers exercise the actual run loop, not timing sleeps;
an explicit stop still refuses the preserved adjudication before native POST.
The original failed smoke/final receipts and exact first-control diagnostic are
retained in the results directory. Missing ledger entries or legacy generic
cancelled receipts do not grant a retry. No automatic continuation or replay was
added, and the original UNKNOWN remains historical even after a successful
explicit adjudication.
