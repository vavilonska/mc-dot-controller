# Closed-session rollover in the same fixed ledger

This narrowly supports a normal client/resident restart after all prior cases have
been formally closed. It does not restore an unfinished action, renew a budget,
reconcile an unknown result, grant a new case, or create a new ledger. There is no
new native API, credential, access grant, transport, or game action.

## Entry

Construct `PostTrialSafety` with the new actual operator identities and the exact
existing fixed ledger directory. The QueueClient root must be the ledger's parent
(the same fixed queue); aliases or another queue are rejected. Call:

`rollover_session(authorization_ref=..., same_save_evidence_ref=...)`

Only an already authorized restart/continuation and verified independent operator
evidence may supply these references. The method reads current state through the
existing operator queue; it performs no input, cleanup, restart, or pause command.
The caller must already have the private test world paused and all inputs released.

Native state currently exports a session world-generation UUID and dimension,
not a persistent save identifier. Therefore the method can verify the current
new generation, the same player and dimension, actual pause and input release.
It explicitly records same-save continuity as independent operator evidence
(such as the already observed safe SaveQuit and selection of the same test save),
not a machine/native proof of save equivalence. A missing reference rejects.

## Required old closure

The original context, sibling ever-used anchor, case anchors, ordinal sequence,
report pointers and hashes must all validate. Every old case is rechecked under
its own historical identity, not relabelled with the new session.

- Every accepted original action must have its exact known released terminal.
  Unknown/pending/conflicting receipts never become known because the new client
  is idle or the old native registry has disappeared.
- Active cases need the existing formal append-only operator closeout with each
  exact scoped death proof, the verified original release, and known resume/pause
  outcome. Resume is tied to its original UUID5 ID, session, reservation, dispatch and exact Escape command; the native pause echo must equal the original terminal hook. A fallback pause uses the existing strict pause receipt validator and original terminal signature. An unknown native pause or unresolved mutating intent refuses.
- Old NoAI cases retain their original rules: a complete explicit non-admission
  rejection is allowed only with the original verified exact cleanup and pause
  effects. This is not an accepted action or a fabricated native terminal.
- Unsubmitted registered cases, incomplete reservations, orphan sidecars,
  missing records, missing closeouts, and unrecognized/unresolved mutations refuse.
- No existing safety stop, failure result, report, evidence, anchor or checksum is
  rewritten or upgraded. Rollover is never a reset or a repair operation.

## Current observation boundary

The new resident must explicitly be ready with reason:null, with no active request/action, no pending
IDs, and stopped aim/combat automation. A resident paused by any stop or unknown outcome is rejected; no reason-keyword guessing or automatic resume occurs. The fixed queue's actual inbox and working
directories must also be empty before and after the one read; a cached pending=0
is insufficient. Restarting the resident cannot erase a persisted stop: the method
also checks currently retained queue results for known terminal outcomes and the
existing G1 intent/result stores for complete, strictly bound exact-409 rejection
proof. An unfinished claim or uncertain POST rejects even when a new resident
reports ready/null and the mailbox is empty. G1 claim hashes stay bound in the
session link, so later deletion or modification does not reset that evidence.
This checks retained results plus the non-expiring G1 claims; it does not claim to
reconstruct arbitrary already-expired non-ledger history. All registered case
history remains covered separately by its complete immutable ledger.
The observation is subject to the existing bounded read timing,
world/player/action-session binding, complete local entity coverage, and native
input release checks. Actual native pause and a living player are required.
A live old scoped UUID or unregistered living zombie in the observed area refuses.

The ledger's exclusive lock spans validation and commit. It does not freeze the
world or authorize another writer; the existing sole-operator/one-queue-writer
rule remains necessary. Observations certify the checked boundary, not perpetual
future safety or unloaded entities.

## Append-only files and active identity

Each transition appends one `session-NNNNNN.rollover.json` plus checksum under the
same ledger, and one numbered sibling `...session-NNNNNN.anchor.json` plus checksum.
The sibling is written first. A partial write is detected and blocks all normal
use; neither old nor new identity is silently allowed to continue. No automatic
repair or retry is performed.

The record binds the root context hash, previous rollover hash, from/to identities,
the entire verified closed prefix, the last case-anchor hash, new observation,
before/after session/queue evidence, and explicit authorization/evidence references.
Deleted, changed, missing or discontinuous links refuse. Returning to any prior
identity and repeating the same identity refuse before append.

Every normal ledger operation revalidates the current chain head inside that same
lock. Old operator instances become invalid immediately. New case registrations
retain the original ledger-wide ordinal sequence and add a session-link hash and
identity. Historic cases with no session fields retain the original root identity.

A new session cannot act on the last old case. Starting a new case still needs a
new independent case authorization, fresh live registration and its normal exact
two/three-target rules. Rollover authorization and old case/closeout permissions
cannot substitute for that. Any previously recorded request ID cannot acquire a
new native budget in the new session. The old two-target and explicit three-target
paths remain separate.

## Verification boundary

Offline tests use temporary ledgers and fake queues, retaining the production
original-resolution and formal-closeout verifiers. They cover both new two/three
registration paths, legal explicit non-admission NoAI closure, all-case checking,
old instance rejection, old request/authorization reuse, actual inbox/working
races, foreign player/dimension, unpaused/held/running state, missing/modified links,
and partial transition writes. Recorded real-chain evidence was inspected read-only;
no live rollover was appended while implementing or testing this module.
