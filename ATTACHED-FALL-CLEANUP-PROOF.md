# Normal attached disarm proof for exact owner cleanup

This integration-only Python delta is based on the merged next source after
paused cleanup R3. It adds no native endpoint, game action, retry, authority
release, or automatic continuation.

A normal attached action already disarms its exact native guard before publishing
its terminal receipt. The previous implementation discarded that successful
status. The strict cleanup-only reader correctly refused to release the owner
without it (`cleanup_original_disarm_proof_missing`). The original pre-closure
production owner-chain failure remains preserved in the integration results.

The Resident now retains a separate closed `fall_rescue_cleanup` receipt with the
exact gateway-derived binding, final native status, and original native action.
It is not the interrupted-action UNKNOWN seal. Validation requires a terminal
same-action receipt with input release confirmed, a strict disarmed/unowned,
unblocked, non-quarantined status, and no unknown/preempted/handoff/reconciliation
or partial-effect markers. A known non-preempted exact cancel retains its cancelled
outcome. Interrupted or unresolved tasks keep their existing UNKNOWN path.

The gateway captures the expected binding before its one queue submission and
validates the returned proof before retaining it on that exact lease. Runtime
archives the original receipt first, verifies the same binding, and stores the
status only on the same current JobControl/owner/generation/job. This supplies
prior evidence to the existing cleanup reader; the reader still takes its own
fresh complete neutral observation and exact release checks.

Missing or altered proof cannot release the owner. Validation/read/persistence
callbacks cannot install the proof on or clear a replacement owner. Later native
state, different arm/context, or evidence regression still invalidates cleanup.
The original semantic result is not rewritten to success by a cleanup proof.

Tests use production Resident/gateway/Runtime/Toolbox paths with a modeled native
endpoint and the accepted native status fixtures. They cover normal completion,
non-preempted exact cancellation, missing/foreign/UNKNOWN proof, closed-schema
faults, replacement callbacks, and the existing interrupted/partial rescue and
paused cleanup suites. They do not establish live Minecraft behavior.
