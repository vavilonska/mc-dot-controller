> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# V6 bounded history-capacity maintenance candidate

Status: OFFLINE IMPLEMENTATION AUTHORIZED; not deployed and not gameplay admission.
Base: the frozen survival-v6 candidate (same V6 wire/action kinds). Actual formal world is cold at F481.

## Exact scope

- New V6 runtime: at most **1024 records**, public file **64 MiB**, native file read **2 MiB**.
- Older active profiles retain their existing 256/512 record and file bounds; stored old requests, receipts, digest and terminal meanings do not change.
- A count ceiling is not a promise that every combination of maximum observations, PLANs and receipts fits. The exact byte/reserve gate can refuse first.
- Preserve all 481 actual records, owner, monotonically increasing generations, global UNKNOWN, same-ID lookup/deduplication, one active action, durable effect fence, and original cleanup semantics. Never reset authority or truncate history.
- No journal, segments, database, new endpoint, credentials, gameplay ability, action timing, or response-size change.
- Observation ticket stays 2000 ms / 40 client ticks. Native deadlines still run absolutely from submit: existing move/action TTLs and consume's separate 4000 ms / 40 tick bound are unchanged.
- Retain the previous JAR/source and F481 for recovery identity. An old reader with lower limits is not a supported downgrade once newer history exceeds those bounds; artifact backup does not authorize replay or world rollback.

## One-start public serialization

The old path serializes the full history four times before POST: provisional room check, projected size, PENDING save, and start exchange room check.

The new path may construct **one final PENDING encoded immutable byte string** in one cooperating-controller call. Exact length must satisfy file maximum and unchanged cleanup/status reserve. Those exact bytes must be written using the original temporary-file, file fsync, atomic replace, and directory fsync before any effect POST.

Any start-exchange capacity proof is private, short-lived, bound to that exact committed PENDING state/action, and consumed once. It cannot authorize a subsequent action, status/stop call, or a changed/failed commit. No long-lived encoded-history cache. No omission of new raw receipt, parsed result, UNKNOWN, stop/status or restart persistence. Existing file ownership/lock/symlink rules remain.

Fault boundaries: encode or over-limit rejection, temporary write, file fsync, replace, or directory fsync failure must not issue POST. A successful durable PENDING followed by an uncertain transport outcome retains the original ID and UNKNOWN/cleanup handling; it is not retried as a fresh effect. Restart must not erase an unfinished action.

## Continuous ordinary-navigation run (separate sidecar contract)

Root approved a first **at-most-five-minute** finite preloaded run, not a silent change to old 90-second wrappers. Concrete route/endpoints and finite fresh-ID pool must be frozen before launch. No on-the-fly engineering while the player waits alive.

- Same-session completed route chapters may proceed to the next preloaded chapter after exact known release, global idle/UNKNOWN checks and a new fresh observation. Normal completion of an intermediate short stage does not require closing Minecraft or changing session.
- Every movement remains subject to the existing local 150-cell geometry/current support/body/target/source/angle/context and native input gates. Unknown terrain outside the current window is not assumed traversable.
- Near-end positive-axis remainder may use the existing one-sample policy. No unapproved reverse, repeated jump, larger arrival tolerance, new combat policy, or automatic action retry.
- Used stage/action budgets accumulate across PLAN hashes and chapters, never reset by a new data file. Existing native absolute TTL remains the input-release boundary, independent of the episode deadline.
- The episode must stop issuing new intents before its finite deadline when insufficient time remains for the original-ID finish and bounded readback. A deadline does not turn UNKNOWN into a known result or authorize another action.
- Final target, actual threat/health/geometry failure, known refusal, or UNKNOWN stops progression and reports the actual result. Closing is an explicitly prepared normal-GUI lifecycle action, not an action replay or world rollback.
- Short CUA supervision remains best effort. Native input release does not guarantee that an idle player is safe from natural game damage. No OS injection, external UI daemon, process kill, or hard-real-time closure claim.

## Required offline evidence

1. Actual 481 native binary re-encoding and full public records unchanged; representative old profile and UNKNOWN/restart/duplicate-ID cases retained.
2. New 1024/1025 count boundaries, new byte/reserve boundaries, and old active-mode limits.
3. Start persistence fault injection at every relevant boundary, one-use/stale capacity-proof negatives, receipt/status/stop/restart not using a stale snapshot.
4. New-candidate real persistence/fake HTTP performance with the actual 481 prefix and realistic 1024-history models; accepted maximum observation/PLAN/receipt byte models must state when they do not fit.
5. No real game HTTP for these tests. Synthetic future history is not an admitted gameplay history. Actual F481 files remain unchanged.
6. Narrow source/paired-byte review before deployment. Continuous-run route/runner/transport/lifecycle data are separately frozen and reviewed before gameplay.

## Why not segmented history in this iteration

Native actual 481 journal is only 207,798 bytes; independent exact FileStore writes on temporary copies measured median 2.996 ms (10 post-warm samples). Public history is 18,495,832 bytes and repeated JSON serialization is the present dominant cost. Correct segmentation would additionally require immutable-base plus update-event lookup, global ID/owner/UNKNOWN indexes, cross-PLAN cumulative accounting, crash-safe tail/seal/index handling, and old-receipt update semantics. None is necessary to remove this iteration's measured duplicate serialization or enable a larger bounded V6 history.
