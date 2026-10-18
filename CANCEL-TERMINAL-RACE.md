# Exact original completion / cancellation race

This correction is based on frozen recovery TEST2.3. It adds no native change, new observer, retry, timing relaxation or automatic recovery.

## Failure and scope

A one-tick inventory click can finish and release its input before the queued public cancellation reaches the Watchdog. The Watchdog then has no current per-action owner, while its persistent ordinary lease still names that exact last mutation. The prior generic owner-mismatch receipt could not prove whether any cancel was dispatched, so Runtime conservatively left the original UNKNOWN before archiving its terminal receipt.

The new acknowledgement is available only when the original is already terminal before any cancellation dispatch. It requires the same active ordinary lease, owner, epoch, full world context, resident session and exact last intent/queue identity. There must be no current owner/RPC, prior cancellation, cleanup/transition or fall/external/managed controller. The original Resident receipt must be terminal with the deterministic native action identity and positive input-release proof, without uncertainty, quarantine or automation-blocked markers. A ready Resident session must have no active or pending work.

All file/session reads and local persistence finish before a pure current-identity/deadline fence. The acknowledgement binds the exact command and complete normalized original receipt by SHA256. This branch submits no Resident command and performs no native cancellation. Client and Runtime validate the closed proof; Runtime also binds its recorded original request, context and receipt, then performs the existing native/scoped witness validation.

## Outcome and cleanup

The individual native action can be known terminal/released while the overall goal's semantic verification remains incomplete. Cancellation stops the goal before further mutations. A transfer does not become successful, conserved or cursor-empty just because its last native click is terminal. Historical `last_observed_carried` remains explicitly the prior observation; it is not relabeled as current state.

Existing fresh neutral cleanup and exact owner release remain mandatory. Only a separately requested new full-menu observation or recovery can proceed afterward. No cursor rollback, automatic storage, automatic menu close, replay or historical UNKNOWN rewrite is added.

Identity-matching original receipts are archived before cancel-result parsing, including malformed/ambiguous cancellation cases. Generic old mismatch receipts, missing originals, replaced authority/context, unsafe native results, timeout, persistence failure and any possibly queued cancel remain UNKNOWN. The distinct race where a cancel was already queued to Resident is not relaxed by this proof.

## Offline evidence

Tests cover the real public Service → Runtime → IntentClient → Watchdog → Resident chain with a modeled native endpoint. The inventory case verifies the first pickup, races completion of the second click with cancellation, retains cursor 15/chest 1, stops after exactly two clicks with incomplete second-click semantics, confirms neutral cleanup, deduplicates the original ID, and permits a separately requested fresh menu read and recovery. Negative tests cover digest/schema/identity/UNKNOWN/quarantine flags, callback authority replacement, expiry and post-persistence failure. These are offline protocol tests, not fresh live acceptance.
