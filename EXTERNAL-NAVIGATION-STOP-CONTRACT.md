# Explicit external-navigation stop

This separate source delta is based on recovery TEST1 manifest SHA256 `073c5447c88863194ab5bc6edd1ab483dd815ac04e215d78eeb91ee006f45bf0`. It does not contain reconciliation R3 or attached fall-policy stage two.

## Public call

Use the existing `mdc_job` submit operation with capability `stop_external_navigation`, version1, arguments `{"timeout_ms":5000}`, and policy `{"version":1,"execution_mode":"request_only","reactions":"stop"}`. Supply the current catalog session/context references and an original request ID. Budget at least three actions, `ceil(timeout_ms/100)+3` observations, and `timeout_ms/1000+3` seconds. Timeout is bounded1000–10000ms. Query/cancel the returned original job ID. Duplicate submit IDs return that same job; an unknown stop is never resubmitted.

The capability appears only when the gateway/native stop-only protocol and the pinned supported Baritone API are advertised. The previously verified official API-neoforge1.11.3 jar is required; unsupported or unknown implementations stay unavailable. No installation or game testing is performed by this patch.

## Ownership and effects

The existing Runtime → IntentClient → Watchdog → Resident route acquires a durable, explicitly typed `external_stop` lease. It admits only this bounded control and later cleanup observation. It cannot admit ordinary movement, combat, inventory effects, fall arming, or arbitrary Baritone commands. An already active/UNKNOWN MDC owner, quarantine, or paused/handoff gateway still blocks admission. An armed request-only gateway may publish `external_controller_stop_only_ready` when its only known busy owner is the supported external controller; this does not change ordinary lease admission, which continues to require actual idle. No paused task is rearmed.

Native code installs the exact operation/owner/generation/job/session/world/player lease before calling the official `IPathingBehavior.cancelEverything()` once. It does not call `forceCancel`, clear keys, start a route, change settings, or resume the cancelled task. Original native source tick/nanotime are rechecked after all reflective/context reads immediately before claim/cancellation. A pure captured player/level/gameMode/session/generation/owner fence then excludes replacement by the last callback. The same order guards every settlement sample. Any callback failure after attempt quarantines the original operation.

A Boolean cancellation return is diagnostic only. Completion requires two distinct native ticks strictly later than the captured admission tick proving the pinned external controller has no path, planner, retained goal, active controlling process or forced input, and native controls are neutral in the same player/world/session. Original deadline, owner replacement, context change, or uncertain proof cannot be turned into a released owner. A process-lifetime UNKNOWN fence prevents later ordinary input even if Baritone eventually becomes idle. Logical owner release additionally requires the existing full fresh neutral observation and exact release acknowledgement.

Status receipts bind every original identity and the closed production external proof. Nested schema/count types, adapter identity and all path/planner/goal/process/input facts must agree with derived idle. They cannot erase an attempted cancellation, change its acknowledgement, regress native tick, or claim settled without the two-sample idle proof. Current player physical safety remains separate; no survival or server acknowledgement is inferred from idle input.

Cancelling the public stop job sends no second native cancellation. The same owner may perform its already-budgeted status verification and release if actual idle is proven. A lost write or lost status receipt preserves UNKNOWN and original IDs. Native timeout is independent of Python continuing to run; no retry follows a crash or timeout.

## Scope and limits

- Explicit safe stop only. Managed route start/handoff is a separate next delta.
- Native retained controls are bounded128 and never evicted to admit new work. Full capacity refuses admission.
- Polling/read failure is conservative UNKNOWN. There is no automatic operator adjudication or quarantine reset.
- A live client tick is needed for native settlement. Paused/stalled game timing may therefore end in UNKNOWN rather than fabricate idle.
- An acquisition racing an already-issued gateway observation remains in its original inbox until that read drains. It creates no lease or native mutation while waiting, and does not reset the original acquire timeout or replay a request.
- Offline tests use real public Python/Node mailboxes with a synthetic native endpoint, plus full production Java compilation and pure native lease checks. Actual in-game cancellation latency and Baritone safe-interruption behavior remain live acceptance work.

## R3 actual HTTP encoding
Native status is produced by ExternalNavigationResponses from the original lease.
ActionResponses adds exactly protocol=mineclient-bridge and integer schema_version=2;
Resident and Runtime accept and remove only that complete pair, or accept the raw
embedded model. Missing/partial/Boolean/extra wrapper fields are rejected.
BridgeJson preserves the explicit nullable cancel_accepted field only in the
schema-1 external-navigation root or exact external_navigation_status subtree.
It never manufactures an omitted field; validators still require the field.
The canonical fixture crosses the actual response wrapper and HTTP serializer,
then real loopback Bridge transport, Resident execution, and Runtime validation.
