# Execution recovery P0 (offline candidate)

This change covers Python owner lifecycle and Node stdio delivery only. It does not
start or deploy Minecraft, change credentials, replay a request, resolve a historic
UNKNOWN, or establish live gameplay acceptance.

## Observation ownership is durable

`mdc_observe` accepts an optional immutable `request_id`. Supplying it is recommended:
if a transport reply is lost, query `mdc_job` with operation `status`, the same
`session_ref`, and that `request_id`. Never mint another request to retry an unknown
read: the existing observation path acquires a real owner lease.

The historical local `memory` profile remains a lease-free, query-only read and
does not create a runtime/job record. For live profiles, before backend work
begins the service persists the observation in the same
`JobStore` as mutation jobs. The record has `job_kind: observation`; owner context,
lease acquisition, observation, cleanup read, and release IDs are persisted through
the existing event callback. Observation I/O runs outside the service lock, and the
in-flight thread is registered for bounded shutdown. Lost acquisition, read, release,
or shutdown proof leaves the original job UNKNOWN. It prevents competing work and
survives a service restart. Exact reconciliation only reads original receipts.

For compatibility a successful observation retains its existing flat `state` object
and native `request_id`; new `job_id`, `job_request_id`, `job_state`, `request_ids`,
and `cleanup_certainty` fields identify its durable lifecycle. A blocked or unknown
observation returns the standard job envelope, including its original IDs, error,
result (when obtained), and cleanup evidence. `mdc_job status` always returns the
standard job envelope. Repeating an already admitted observation `request_id` only
returns that record and never reacquires a lease.

This does not create a lease-free live telemetry API. Leased observation remains
blocked during active or unknown work. The existing exact job status/reconciliation
operations are available for recovery without minting a second owner.

## Last dispatch boundary

The final owner checkpoint may block on session I/O. Immediately after it returns,
stop/deadline and original immutable observation age are checked locally before
`submit`. The age origin is never refreshed, the 800 ms bound is unchanged, and a
known unsubmitted stale action is journaled as blocked without setting the mutation
certainty latch to UNKNOWN. A transport-started exception remains UNKNOWN.

## Lossless errors and process exit

Node treats child `exit` as the start of a bounded stdout drain. Complete final
frames are consumed until child `close`, or a 2-second drain deadline. No new calls
are dispatched while draining. Missing proof remains UNKNOWN; request/job/session
identity is retained on transport failure. No kill, restart, resend, or replay is
performed. Late timed-out responses cannot satisfy a different request.

Python `check_response(response)` raises `ToolboxResponseError` for non-null errors.
The exception keeps a deep-copied complete `response`, plus `job_id`, `request_id`,
`request_ids`, and `session_ref`. Callers can record the exact recovery identity even
when checking an error. The helper performs no I/O and no automatic recovery.
Oversized stdio replies return a compact error with original job/request identity,
known state/certainty, and bounded request IDs. If that list must be shortened,
`request_ids_truncated` is explicit; the durable original record remains intact.

## Tests and limitations

New deterministic regressions cover lost acquire/read/release, exact-ID observation
replay rejection, restart, bounded shutdown during a read, error identity retention,
stop/deadline/reversed-clock/TTL expiry inside the last owner checkpoint, oversized
reply identity, and exit-before-final-stdout ordering. Runtime, durable journals,
service, JSON-lines framing, and Node bridge are production code; transport and
native data are synthetic. Aggregate test outcomes are recorded separately,
including failures and skipped tests. These tests are not native or live acceptance.
