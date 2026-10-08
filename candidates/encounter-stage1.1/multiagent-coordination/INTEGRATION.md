# Integration gates and timing sequences

This directory is an independent offline update to the integrated coordination
module. Its patch applies only to that module, never a live installation.
It must remain optional/default dry-run when combined with other candidates.
`ResidentAdapter.dispatch/poll/cancel` deliberately raise
`live_adapter_not_integrated`. Do not remove that gate based on offline tests.

## Before any authorized live integration

1. Verify the actual resident, watchdog and Java run/session/source pairing and
   current native action support. `.6` combat, boat and expedition candidates have
   independent review/acceptance status. This package does not merge their code.
2. Establish one real input owner. The existing watchdog is the sole resident
   queue writer while armed; `IntentClient` and navigation defense-epoch fencing
   are not automatically replaced by this journal's flock. Do not run a second
   coordinator alongside an input-owning watchdog or submit directly to resident.
3. Establish one observation publisher with original capture intervals, native
   source tick/time and per-section context. Use the pure completed-result adapter
   for consumers rather than running one exporter/observe call per consumer.
   Do not treat `scan_cache.json` save time, old cursor time or subscription time
   as live-world freshness. Missing source metadata must remain unknown.
4. Bind task grants to actual user-authorized scope outside role labels or webpage,
   chat, result/goal text. Trusted owner operations must not be exposed as ordinary
   planner RPCs. This package does not authenticate workers or isolate same-OS-user
   code; a future IPC layer needs process permissions/capabilities and bounded ingress.
5. Supply actual atomic endpoint/session fencing, ownership/release evidence and
   observed per-segment postconditions. Current resident `cancel` and terminal
   records are not automatically equivalent to this candidate's Receipt contract.
   Its QueueClient ID is not the native action ID. The actual adapter must reconcile
   both identities without new IDs or replay after uncertain transport.
6. Connect verified corridor/terrain safety and actual native support. The compiler
   preserves native `follow_path` continuity but does not add native physics, dynamic
   collision checking or terrain acquisition. Current whitelist raw observation
   conversion deliberately cannot certify exhaustive terrain safety or attackability.
7. Implement an independently verified live threat-assessment contract before any
   ordinary navigation. Current ThreatClearance deliberately accepts only fixture
   provenance, binds exact sample plus content, and is never produced by the real
   result adapter. Missing/stale/incomplete entities or missing/expired/revoked proof
   are hard admission failures. Do not infer clearance from unchanged entity versions.
8. Preserve action, task, lease, native timeout and total retry/cancellation budgets.
   A phase transition must not call activate with a disguised new authorization to
   reset an existing task. Native action cancellation must release inputs before a
   new owner action. Unknown transport cannot authorize a second control path.
9. Add real source-domain timing instrumentation before latency claims. Queue and
   response latency cannot be relabeled native execution time. Native tick counts
   cannot be multiplied by an assumed fixed tick period to claim measured latency.
10. Perform separate authorized live acceptance, including pause/menu, world/player/
   process replacement, terrain changes, contention, transport uncertainty, input
   release, death and bounded shutdown. No such acceptance occurred here.

## Normal preplanning sequence (text timing diagram)

```text
Owner observation collector  -> Cache: publish one explicitly completed scan A
Offline threat assessor      -> Owner: explicit bounded synthetic clearance E
Map / Resource / Route roles -> Cache: read A (no observe / scan side effect)
Route role                  -> Coordinator: proposal segment 1, terrain revision A
Route role                  -> Coordinator: proposal segment 2, depends on segment 1,
                                           expects actual start at segment-1 endpoint
Owner advance               -> Journal: durable dispatch intent, fixed IDs
Owner advance               -> Coordinator: recheck TTL, lease, deadline, snapshot
Owner advance               -> Fake executor: start native-shaped segment 1 once
Fake executor               -> Coordinator: running; not a completion receipt
Owner observation collector -> Cache: publish fresh actual player arrival B
Owner advance               -> Fake executor: poll exact segment 1 IDs
Fake executor               -> Coordinator: succeeded, observed, inputs released
Owner advance               -> Coordinator: verify dependency + actual player B +
                                           terrain A content/continuity/TTL + exact proof E
Owner advance               -> Journal / Fake executor: commit segment 2 once
```

The second action does not require a new model decision if its previously prepared
intent remains valid. A missing/wrong endpoint, stale terrain, changed revision,
failed dependency or expired lease rejects it. No claim of real speedup follows.

## Bounded defense sequence

```text
Defense role -> Coordinator: typed target proposal inside same authorized task
Owner        -> Coordinator: verify target, fresh source, priority, remaining budgets
Owner        -> Journal: persist cancel_sent for exact current action ID
Owner        -> Executor: cancel exact current action once
Executor     -> Owner: terminal and released? otherwise UNKNOWN/BLOCKED
Owner        -> Journal: persist confirmed terminal receipt
Next advance -> Executor: start defense only after released slot + revalidation
```

No waiting timeout grants an input owner. A lost cancel response causes a blocked
state, read-only reconcile of the same old action, and no duplicate cancel POST.

## Crash and recovery sequence

```text
Owner A -> Journal: dispatching(action X, request R, old exact context), fsync
Owner A -> Executor: possibly sends X, then process stops
Owner B -> Journal: obtains same flock, new epoch; old active UNKNOWN
Owner B -> Planners: no old lease / queued plan / old-monotonic freshness resumes
Owner B -> Executor: read-only poll of X/R/context
           missing/running/mismatch => continue BLOCKED, never resend X or invent X2
           matching terminal + release => persist outcome; clear old owner slot
Owner B -> Authorized owner flow: a NEW bounded task grant may be explicitly installed
```

A crash before the actual send can leave an unresolvable prepared action. That is
intentionally fail-closed. The candidate supplies no “forget unknown” or alternate
queue escape hatch. Live recovery must establish actual release under the real
input owner's approved contract rather than delete the journal to bypass it.
