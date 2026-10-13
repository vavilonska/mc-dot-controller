# Submission-boundary fix, revision 2

## Why a relative TTL was insufficient

The original add-on produced a raw Proposal at collection time with a relative
remaining TTL. A caller could retain it, publish a later same-content observation
and submit after the original observation had expired. Coordinator previously
started that relative TTL on receipt. A fresh cache therefore revived the old
candidate. The previous test run did not cover this collect-to-submit gap.

## Enforced contract

`PlannerPort.capture_planning_source()` captures the actual owner snapshot and
lease atomically and returns `{source_id, snapshot, lease, issued_mono}`. The
owner keeps its own immutable copy. First use turns on the planning receipt gate
for that Coordinator instance. From then on, a raw/receiptless Proposal is not
accepted, regardless of role or origin text. Existing Coordinators that never
enter planning mode retain the legacy interface.

`PlannerPort.seal_planning_proposal(proposal, source_id, absolute_deadline)`
validates that source against the actual current owner sample and records an
immutable Proposal digest, original absolute deadline, session/clock/lease and
source sample/continuity metadata in the owner registry. The returned wire value
contains `planning_fence`. A new role label, a supplied deadline, a fabricated
receipt, a removed receipt, a changed body/TTL, or rebinding the same Proposal ID
to a newer source cannot substitute for an issued receipt.

The Coordinator validates that receipt again at submit and during arbitration /
pre-dispatch. A pending entry's expiry is capped by the sealed absolute deadline,
not just receipt-time plus TTL. Same-content NEW samples are intentionally a new
lineage and require a new candidate, even if the old sample has not expired.
This is stricter than content revision equality. The native `source_samples`
contract can remain independently enforced by the live adapter.

`batch.finish()` revokes every issued candidate that has not already been
submitted. Submit the chosen candidate before finishing the batch. Already
submitted candidates keep their original immutable deadline; finishing never
extends it. A legal continuous lease renewal after acceptance is supported by the
existing private renewal chain, without extending the source deadline. Renewal
between capture/collection and submission requires a new candidate.

The registry is owner-local, bounded and non-persistent. Restart cannot replay a
receipt because its issuing registry and grant/lease identity do not resume.
Task replacement clears old receipts but leaves the gate enabled. This protects
freshness lineage, not authentication: cooperative same-user Python is still not
a sandbox, and worker roles never confer authority.

## Live owner integration

Import `seal_advice_candidate` from `mdcoord.planning`.

After independently publishing the new player/terrain/entities observation:

`candidate = seal_advice_candidate(advice, owner.planner(), budget_ms=500,
max_waypoints=1, include_source_samples=True)`

Then use the existing owner preflight/authorization and:

`owner.planner().submit(candidate.wire())`

The helper performs source capture, fresh replanning and sealing before returning.
It gives the new Proposal a new identity and the current lease; it never submits
or dispatches. `include_source_samples=True` copies all three sample IDs from the
SAME sealed fresh snapshot. It requires the separately integrated optional
`source_samples` Proposal schema. The offline legacy base uses False.

Do not use the low-level `route_candidate_from_advice` dictionary as a submit-ready
artifact and later attach whichever snapshot happens to be newest. The enabled
gate rejects such raw wrapping. Direct candidates emitted by `batch.collect()`
are already sealed and must not be edited after collection.

Minimal changes to existing core files are supplied in
`owner-submission-fence.patch`: Coordinator/PlannerPort registry integration and
an optional closed `planning_fence` schema. Merge these hunks into the live-owner
branch; do not overwrite its native adapter or `source_samples` changes.

## Additional benchmark repairs

Independent synthetic recaptures now have unique source/proof IDs and increasing
source stamps. A bad first Advice no longer prevents a later good alternative
from being replanned. Completed-advice source-expiry statistics use completed
valid Advice outputs as the denominator; no returned Advice means null, not 0%.
Started, completed and not-started event counts are separate. The timeout rate is
explicitly a planned-role-event rate, not an actual-model-call timeout rate.

New regression coverage includes the original audit reproduction; delayed submit
with and without finishing; same-content new samples before/after expiry; queued
absolute-deadline enforcement; missing/forged/edited receipts; resealing the same
identity; lease renewal timing; owner replacement; fresh-Advice submission delay;
valid direct/Advice paths; the bad-first/good-second benchmark case; and empty
completion denominators. The complete test suite currently passes 263 tests.
