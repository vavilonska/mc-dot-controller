> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Interaction v3: bounded observation lease, unchanged reliable executor

Version `1.1.8-recovery-interact-test.3-from-diag1`; explicit profile `recovery_interaction_v3`, route `/control/recovery-interaction/v3/`, startup flag `mineclientBridge.recoveryInteractionV3`. This is a new contract and independent TEST candidate, not a silent relaxation of v2. No live/formal qualification follows from offline tests.

## Small, explicit change

The v3 observation reference is valid for at most **1000 ms and 20 native client ticks**, measured from the original native observation capture. Both bounds apply; negative age/tick deltas reject. Existing short-input, interaction-v1 and interaction-v2 retain their **250 ms / 5 tick** predicates. Age is not reset during serialization, public intent persistence, native submission, queued admission, diagnostics or first execution. A newer observation cannot silently substitute for the request's original observation ID.

The separate request TTL remains the original absolute duration starting at native submission and includes native journal writes, queue residence and execution. The next TEST uses look1000ms and break2000ms, unchanged. Admission or first effect does not restart it. The native live-ticket/owner/stop check still precedes dispatch. A valid observation reference does not make an expired/cancelled/replaced request live.

Current same-player/level/world/session/input owner, position ±0.05, yaw/pitch ±0.1, alive/exclusive context, target state, full tool/selected slot and vanilla combined ray/reach predicates retain their existing roles. Interaction admission and first-effect checks execute against current native facts; v3 does not treat a one-second-old scene as proof that the whole world stayed fixed. Dispatch persistence remains before any effect; mining claim/return/abort and automatic deadline release retain their existing bounded-call semantics. No direct block/velocity/player-position writes, placement, combat, broad mining, new jump or entity-global proof is added. Ordinary damage and a finite unbroken target are gameplay outcomes, not automatically protocol UNKNOWN.

## Why the revision is explicit

Three real look requests (generations95–97) were accepted as QUEUED and then ended known-zero with `observation_stale_or_moved`, no applied calls, `not_started`, `not_needed`, input invalidated/released and no UNKNOWN. Their original evidence remains immutable. Source inspection shows the original capture time precedes terrain/tool assembly and the same lease is checked at observation completion, queued admission and first effect. Public intent persistence and native journal/queue costs consume that window. Existing receipts do **not** identify which predicate or stage failed, so neither timing replay nor this revision is a claim that elapsed time was the uniquely proven cause.

Actual R4/R5 timelines are offline fixtures for accounting and boundary tests only. They cannot prove a new binary would have executed successfully. There is no additional candidate-ID loop to gamble on the old window.

## Bounded refusal diagnostics

V3 alone adds `observation_refusal`, either null or a closed bounded record of native stage, actual age, actual tick delta and predicate mask. It records the existing check's captured values; unavailable source values remain unavailable rather than invented. Predicate semantics explicitly distinguish first-failed/checked-prefix facts from a claim that every predicate was evaluated. The diagnostic is not a new effect, observation authority, retry grant or deadline refresh. It is stored with the existing terminal transition, without a separate writer, unbounded event log or new getter scan. Exact wire/encoding definitions are bound by the native/public tests.

Old-profile receipts do not gain new keys. Only v3 journal entries receive the new conditional tail; request digest continues to cover the original typed action and PLAN payload, not a later diagnostic. Raw evidence and closed public readers preserve original-ID facts and treat missing/malformed new-profile diagnostics as a schema failure rather than falling back to v2.

## Shared immutable history and scope

All profiles share the original native journal, public ledger, owner, ID namespace, generation, single in-flight action and persistent UNKNOWN lock. At the present cold boundary there are97 known entries, including the three v2 known-zero looks. Original request digests, serialized entries and terminal statuses must round-trip unchanged. Historical status/exact-stop routes by stored profile and does not require a new PLAN. No empty journal, replacement owner, record truncation or UNKNOWN replay is permitted. Count256, byte8MiB and status/cleanup evidence reserve remain unchanged; count headroom is not a promise of byte capacity.

V3 reuses the v2 local reviewed PLAN format and two ordinary block categories. The current task PLAN remains the single target `(-635,61,16)`, SOUTH, `minecraft:nether_wart_block`, feet60/min_break_y61. A new TEST must bind its fresh session/world/player/original-owner context. Y≤60 support is not a target. No old cross-session observation/PLAN is reused for effect authority.

## Acceptance boundary

Offline tests cover v2 age251ms rejection vs v3 acceptance for unchanged current facts, v3 age/tick exact boundaries and overruns, negative clocks, source/ID/context/pose/rotation mismatch, ticket-valid but request-expired/stopped/replaced known-zero no-effect, first-effect checks, diagnostics and restart encoding, actual97 byte/digest/terminal preservation, public intent/UNKNOWN/capacity semantics and actual production wire consumption. Old profile suites remain applicable. After independent source/archive review, one new health-preserving isolated FUNCTION fork gets **one look and one break**, each one distinct ID and at most one submission. A known-zero, partial, UNKNOWN or failed scene stops that TEST; there is no automatic next attempt.
