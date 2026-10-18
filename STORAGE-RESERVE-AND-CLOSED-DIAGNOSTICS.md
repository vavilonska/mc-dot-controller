# Storage admission and closed diagnostic archives

Declared base: accepted TEST1 plus reconciliation R3 and attached fall policy R2,
pinned per file in the accompanying declared-base inventory. No native Java code
or game-loop I/O is added. This slice does not alter the first live test pair.

## Admission

Default operator thresholds:
- Warn when available filesystem bytes are below 1 GiB.
- Refuse a NEW ordinary mutating job below 512 MiB.
- Refuse a NEW ordinary mutating job once serialized public event history reaches
  64 MiB. Exact SQL byte accounting does not delete or compact any event.

The immutable original request lookup occurs before admission checks. A known ID
still returns its existing record; low space never forgets idempotency history.
The worker rechecks storage immediately before dispatch to close a queued-job
race. Once dispatch has started, no storage threshold interrupts the native
operation, its emergency rescue, or cleanup. Query capabilities, fresh read-only
observations, status, exact cancel and reconciliation have no reserve gate.

Catalog runtime_binding_availability.storage_admission reports thresholds,
current available bytes, current event bytes and the precise refusal/warning.
A failed free-space probe refuses new mutations but does not gate safety reads.
These are admission thresholds, not disk reservations or hard mid-action quotas.
Concurrent external writers and actual ENOSPC may still prevent a durable write;
that does not prove the effect outcome and never permits replay. Existing job
records, request IDs and UNKNOWN receipts remain authoritative.

Python service flags configure the thresholds:
--storage-warn-free-bytes, --storage-min-free-bytes,
--event-history-admission-bytes. All require positive safe integers, and warning
must be at least the refusal floor. ToolboxService also accepts StorageReserve.
The version-1 operator Node configuration optionally accepts the closed object
storage_policy with all three corresponding underscore names. Existing six-field
configuration and its exact child argv remain unchanged when it is omitted.
This setting is operator configuration; the gameplay AI cannot override it.

Public events keep their existing 512-record history contract and 4 MiB JSON
bound; this slice does not silently shrink custom backend evidence. The new
aggregate accounting stops new mutation admission at the configured threshold.
Resident session diagnostics already have 2 MiB/document and 256-file limits;
those limits and full-evidence-on-capacity-failure behavior are unchanged.

## Explicit lossless archive

Run only against a stopped Resident queue, after its controller lock is released
and inbox/working are empty:
python -B -m resident_controller.diagnostic_archive archive --queue QUEUE
  --archive OUTSIDE_QUEUE.zip

Default behavior keeps all source diagnostics. The sole eligible files are
immutable diagnostics/<sha256>.json documents with the exact diagnostic schema.
Worlds, source trees, backups, jobs databases, mailbox results, and UNKNOWN/identity
receipts are never selected. Live logs are not guessed to be closed or archived.

To reclaim space explicitly, add --replace-verified-closed-diagnostics. The tool
holds the stopped-controller lock, exclusively creates the archive, verifies every
member and the complete archive hash, rechecks every original byte/signature, and
persists a restore manifest before unlinking only those verified diagnostics.
Any failure preserves the one-shot partial archive and does not authorize retry.
No existing archive is overwritten. Original references can be restored exactly:
python -B -m resident_controller.diagnostic_archive restore --queue QUEUE
  --archive ARCHIVE.zip --expected-archive-sha256 EXACT_RECORDED_SHA256

Restore verifies the exact archive pin and every bounded member, refuses traversal,
extra/duplicate members and different existing files, and never overwrites them.
The stored bytes and original content-addressed names are restored. Historical
references are readable again after explicit restoration; no receipt is rewritten.
Memory use is bounded to a small manifest plus one document, not the whole archive.

Offline validation includes simulated ENOSPC, admission/dispatch races, exact cancel
and read availability at low space, idempotent old IDs, event accounting without
loss, source-change refusal, live-lock refusal, and exact restoration. It does not
fill a live filesystem or provide a live-game acceptance claim.

## Archive race contract

The explicit inactive-diagnostics command coordinates participating writers with the stopped Resident lock and an archive descriptor lock. Hashing and ZIP parsing share one retained file descriptor; restore also reads that exact descriptor. Path/device/inode/size/mtime/ctime identity is checked around the proof. Every source is revalidated, a durable restore receipt is written, and the archive hash and member proof are repeated immediately before replacement. Cheap descriptor/path signatures and exact source signatures are rechecked for every unlink. An observed swap, corruption, changed source, symlink ancestor, or failed final proof refuses replacement and retains the untouched sources. Partial failures preserve their evidence and are not automatically replayed.

This is a closed, cooperative-writer contract. Advisory locks do not prevent arbitrary hostile same-user writes, and a finite final check does not establish absolute filesystem immutability. No security setting or filesystem permission expansion is attempted. The default retains every original. The opt-in replacement is for explicitly inactive diagnostics whose writers follow the same contract; identity/UNKNOWN receipts, worlds, backups and source are never candidates.
