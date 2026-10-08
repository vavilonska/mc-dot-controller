# Independent safety review: parallel-validity.1

Scope: the isolated Python coordination candidate, compared with the unchanged
integrated source and earlier 17-case audit. Live adapter gates remain closed.
The final independent review and SHA256-locked test evidence are packaged under
independent-review/. This document summarizes findings and their resolution.

## Findings resolved during review

1. A threat proof bound only to sample_id could survive changed entity content
   under the same original capture. Proofs now also bind content_revision; changed
   content and change/reversion reject, including after durable preparation.
2. Authority equality against a referenced frozen Grant was insufficient for
   fault-injected in-place mutations. Owner/lease epoch, full grant/context and
   original task deadline now use an immutable canonical SHA256 authority key.
3. A context switch or a previously omitted section could launder an old capture
   into a larger TTL. Global bounded original-capture anchors and per-context
   provenance high-water marks now preserve expiry and reject regressions.
4. Threat evidence could be relabeled using a later capture finish and changed
   source stamp while retaining the original start. Threat expiry anchors use the
   original start, in addition to source provenance; this cannot refresh TTL.
5. Capacity exhaustion could reject a new negative assessment before revoking
   old positives. Proof-store overflow now permanently closes navigation admission
   for that store; it does not leave old clearance usable.
6. ID-local revocation allowed identical evidence to return under a new proof ID.
   Revocation now follows captured-source and original-start aliases. Only genuinely
   new evidence can support a new proposal; pinned old proposals cannot revive.

## Final checks and retained safety limits

The final candidate suite passes 212 tests; a separate independent adversarial
suite passes 30 tests. Original baseline84 and prior audit17 passed separately.
The independent suite covers concurrency, CAS, post-WAL player/proof/expiry guards,
restart/no replay, live hard gates, budget/receipt invariants and all findings above.
See VERIFICATION.md and the packaged final independent report for exact evidence.

These checks establish offline behavior only. No live input ownership, dynamic
collision or threat collection, real input-release behavior, game timing or speedup
has been verified. Existing resident/old watchdog code is untouched. The typed
threat proof accepts only fixture provenance and cannot be produced by the current
real-result adapter. Do not remove live gates on the strength of this review.
