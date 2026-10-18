> Publication context (2026-10-18): Recovery 2.5 source and its version-qualified acceptance are now recorded in [the current publication note](docs/recovery-2026-10-18/README.md). The text below is the historical candidate/change record; its unpushed or live-pending statements describe that earlier checkpoint. Historical failures and UNKNOWN outcomes remain unchanged.

# Queued cancellation / completed original boundary

Declared base: frozen recovery TEST2.4, manifest b200a1fa0e9586fe4534eac6ab970ddf2fdbb2fd2f13b91bf05a34d5940b63ec. This is a separate Python-only correction; native sources, limits and historical receipts are unchanged.

## Observed boundary

In the TEST2.4 cursor run, the second original click finished about 23.88 ms after cancellation was requested. The queued Resident cancel was consumed about 77.70 ms after that request, after the original task had cleared. Resident returned `failed/exact_cancel_target_not_active` before any native cancel POST. Watchdog correctly refused to infer a release proof, converting it to `uncertain/exact_cancel_release_unconfirmed`. The original native success/input-release receipt is archived, but the transfer's second semantic verification is incomplete. Its immediate native menu observation was15 carried dirt and1 chest dirt. The old UNKNOWN remains immutable.

## Narrow proof

Resident remembers only one process-local latest successful one-step scoped ordinary task. It excludes attempted cancellation, UNKNOWN, attached rescue and encounter ownership. Any non-exact-cancel command invalidates that marker. Restart does not restore it. The marker is provenance, not authority to execute or release.

Only the existing target-not-active branch can use it, before setting a native cancellation attempt flag. A new closed binding identifies the exact public cancel, original intent, owner, context, epoch, Resident session and deterministic original action. Resident consumes one proof attempt, reads the immutable original receipt (bounded2MiB), and checks the captured task/command/native result/session/bridge identity and absence of active, pending or other local input owners after that I/O. It publishes a closed original-result/command-digest proof of zero native cancel dispatch. No native GET or POST is made in this branch.

Watchdog independently validates the proof against the exact saved queue command, last original mutation and raw receipt, plus a ready/idle same-session Resident. The persistent ordinary lease must still be active with unchanged owner/context/epoch/last-original and unexpired deadline/heartbeat. Final pure checks follow all reads and the existing persistence checkpoint. A replaced lease or owner is never cleared or paused by this proof's failure path.

IntentClient validates the closed public wrapper; Runtime binds it again to the actual original receipt and reserved world context. Original native receipt verification remains required. The proof confirms only that this queued control made no native cancellation attempt and its original action has a known native success/release receipt. It does not establish whole-transfer completion, physical safety or fresh gameplay readiness. Existing fresh neutral cleanup and exact ordinary release remain mandatory. A fresh menu read and cursor recovery are separate new requests after that release.

## Fail-closed boundaries

- No proof from an arbitrary cached terminal without the current process-local marker.
- No new proof for a possibly POSTed cancel, unknown/failed original, missing/lost/malformed result, stale session, prior attempt or replacement owner.
- No second cancel, original replay, rollback, implicit recovery, timeout extension or freshness relaxation.
- Duplicate IDs retain the first receipt. A second proof identity cannot reuse a consumed marker.
- No historical UNKNOWN is rewritten, and the proof does not recover across a process restart.

Offline tests use the actual public/Runtime/Intent/Watchdog/Resident mailbox chain with a modeled native endpoint. They cover completion before and after the public cancel, delayed queue consumption, lost and malformed evidence, possible native dispatch, duplicate IDs, post-read/post-checkpoint replacement, and separate fresh-menu/cursor recovery after confirmed cleanup. Live acceptance of this new correction is pending.
