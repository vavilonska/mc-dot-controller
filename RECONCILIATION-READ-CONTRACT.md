# Explicit lease-free reconciliation observation

Call the existing public tool `mdc_observe` with `profile: "reconciliation"`, a unique diagnostic `request_id`, the retained original job's `session_ref`, and `original_job_id`. Optional bounds are only `{"radius":1}`. Selectors, acquisition profiles and custom wait durations are rejected. This is a distinct advertised schema profile, not a hidden option on a normal execution observation.

The original job must exist in the durable Toolbox JobStore. The response includes its exact job/request/session identity, owner generation and retained owner ID/context, original state and effect/cleanup certainty before and after the read. Up to the last32 original request IDs are included, with explicit total/omitted counts and the exact original-status lookup when the list is longer. The read never saves, reconciles, cancels, resumes or releases that job. It grants no execution, inventory-recovery, preflight or replay authority. A successful diagnostic leaves an UNKNOWN original job UNKNOWN.

## Existing serialized route, separate read bookkeeping

Toolbox uses an explicit diagnostic method on the existing IntentClient. A separate bounded mailbox is processed by the existing Watchdog thread, forwarded through its existing resident QueueClient, and intercepted by an exact read-only Resident command before all takeover and error-cleanup branches. Resident calls only the existing native compact GET endpoint. There is no direct model-native transport, additional game thread, credential discovery, lease acquisition, Runtime begin/finish-job call, capability capture, authoritative cache update or mutation command.

Diagnostic reads remain available when normal Runtime ownership is quarantined, the capability heartbeat has failed, or the Watchdog/Resident is paused. They do not clear those faults. The current gateway/native context may differ from the retained original job's context; both are labeled and `session_changed` is explicit. Such a difference is evidence for an operator, never permission to settle old work. A stopped/unreachable daemon or an unavailable native world yields an explicit unavailable/unknown diagnostic. The read does not restart it.

## Bounds and immutable identity

- One diagnostic query in flight; cross-client submission uses a nonblocking file lock.
- Fixed radius1/vertical2,45 native coordinates; compact native response remains bounded64KiB with one client-clock epoch and existing future-terrain rejection.
- A query expires after5 seconds; public result polling is bounded5.5 seconds. Its exact original request and digest travel to Resident, which verifies the same immutable deadline immediately before the GET and rejects a response received after expiry. Queue delay never extends the deadline. Late or failed delivery does not cancel anything or issue a fallback read.
- At most256 retained diagnostic records in each gateway and resident diagnostic result store, each bounded128KiB. Resident diagnostic receipts use a separate directory and never invoke execution-result pruning, including malformed, stale-session, startup, seen-ID and stopped-controller paths. Derived resident IDs use a reserved reconcile_ namespace which ordinary commands cannot submit or execute. Full capacity is an explicit refusal; no retained evidence is silently dropped or overwritten. Commands elsewhere remain64KiB and session reads remain1MiB.
- Diagnostic request IDs bind original job ID, gateway session, exact request digest and one derived resident queue ID. Repeated IDs return the original query/result; changed binding is rejected. A claimed query after daemon restart becomes UNKNOWN and is never replayed. A new independently requested diagnostic is allowed, but no original gameplay action is repeated.
- Reusing an old query ID after a gateway restart is a binding error. Use a new diagnostic ID to read current context while continuing to reference the unchanged old job.

The native compact snapshot remains display-only, with current external-controller and fall-rescue status where supplied. It omits full terrain physics, entities, menu slot topology and full action receipts. Completed cached query results include age and are labeled historical after1 second. Wall timestamps describe mailbox/result age; they do not replace or manufacture the native observation clock.

## Offline evidence

Tests exercise production Node MCP → Toolbox → IntentClient → Watchdog → Resident after a genuinely lost second movement response. The original action/job stays UNKNOWN, original request IDs remain unchanged, the diagnostic performs one compact GET, and native POST count does not increase. Additional tests cover paused/quarantined owners, heartbeat fault preservation, duplicate/conflicting IDs, old job/new gateway context, strict public scope, future terrain, malformed proof, capacity exhaustion, original-owner preservation, claimed-query restart and lost-read no-replay behavior. Native endpoint effects and timing in a running world remain live-acceptance work.

## R2 review closure

The R1 review reproduced a delayed GET after gateway timeout and diagnostic-triggered pruning of an older successful execution receipt. R2 forwards the original deadline and full digest-bound request; validates the final GET boundary; and stores every diagnostic terminal in isolated immutable resident receipts. Full diagnostic capacity is an explicit refusal. Existing execution receipt retention is unchanged, and diagnostic traffic cannot remove execution evidence. A corrupted reserved diagnostic file is rejected within the diagnostic namespace. Tests cover both reproduced failures, callbacks crossing the deadline, startup/stale/seen/stopped/malformed paths, reserved-ID mutation rejection, digest/derived-ID changes, duplicate terminal immutability and saturation.
