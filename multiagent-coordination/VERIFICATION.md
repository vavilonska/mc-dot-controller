# Offline verification: parallel-validity.1

Date: 2026-10-07. Python 3.12.14, standard library only. This independent candidate
updates only the copied Python coordination module. It is not a game acceptance,
latency benchmark, release deployment, or live integration certification.

## Actual final runs

- Immutable original coordination source: 84 tests passed, 0 failures/skips.
- Original prior-audit source: 17 tests passed independently against the unchanged
  baseline. Those tests reproduce historical shortcomings; they are not claims
  that the shortcomings remain in this candidate.
- Final candidate: 212 tests passed, 0 failures/skips.
- Separate independent adversarial suite: 30 tests passed, 0 failures/skips.
- Syntax compilation: 21 candidate Python files passed; compileall also passed.
- Demo: 2 synthetic actions succeeded, maximum 1 fake writer, 0 real game actions.
- Recorded-result sanitization passed; imported capture remains unknown freshness.
- Protected-source integrity: all 662 files from the prior audit manifest retain
  their original SHA256. The integrated candidate and other existing candidates
  were not overwritten.

The 212 candidate tests consist of the 84-method baseline plus 128 added methods:
45 content/sample tests, 45 threat-admission tests, 21 safe-renewal tests, and 17
converted prior-audit regressions. These are method counts, not unique scenario or
subtest counts. Do not add repeated execution of these suites into a larger total.

One original test fixture was intentionally adapted: revision-conflict rejection
now changes actual terrain content rather than merely republishing unchanged
content. Its purpose remains covered; unchanged-content reuse has positive tests.
The original 84-method suite was separately run unchanged on the original source.

## Reproduce

From this module:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -v
python3 -m compileall -q mdcoord tests
python3 -B -m mdcoord demo
python3 -B -m mdcoord sanitize-result fixtures/recorded_resident_synthetic.json
```

The delivery includes verification/run_final_checks.py and the independent suite.
Running that script from the package root executes the candidate and independent
suites, demo, sanitization, and in-memory syntax compilation. It writes evidence
only under that independent package. Tests use local temporary private journals;
there is no network/game/UI/IPC use. The independent suite blocks socket creation.

## New boundaries and failure coverage

- Stable content_revision and revision compatibility alias, separate sample_id,
  original sampling stamps/expiry, quality changes, content change/revert, and
  freshness continuity broken without a reader observing the gap.
- Renamed/reclocked source, same original start with later finish, changed source
  stamps on old intervals, cross-section omitted-payload replay, and context
  A→B→A cannot lengthen original capture freshness. Atomic regressions, capture
  identity conflicts, and bounded history exhaustion are checked.
- Continuous same-authority renewal retains proposal bytes/digest, receipt time,
  original TTL/capped deadline, dependency evidence and budgets; old CAS for new
  submissions still rejects. Owner/epoch/grant/task-deadline mutations, expiry,
  replacement, restart, unknown dispatch and durability failure cannot resume queue.
- Required player/entities freshness and continuity cannot be omitted by planner
  dependencies. Actual player position/health/alive/grounded/menu and terrain are
  independently checked immediately before dispatch, including after WAL/fsync.
- Ordinary navigation requires typed independent offline clearance with exact
  entity sample AND content revision, context, bounded corridor coverage, original
  acquisition, no-threat/complete/valid assertions and unexpired TTL.
- Missing/stale/incomplete entities, stale or absent proof, same-version threats,
  same-capture entity changes/reversions, expired/revoked aliases, wrong coverage,
  forged/mutated schema, negative hazard latches and proof capacity exhaustion deny.
- Proof validity and snapshot publication are serialized through final dispatch.
  New proof IDs cannot revive revoked source/start evidence or queued proposals;
  genuinely newer evidence may authorize only a new proposal.
- Baseline single writer, dependencies, bounds, total budgets, WAL-before-send,
  post-fsync expiry, exact-ID cancellation, confirmed release, uncertain receipt
  handling, crash recovery/no replay, and both live adapter hard gates remain tested.

## Limits

The coordination module still hard-rejects live executors. No real threat adapter,
watchdog connection, transport owner fence, process authentication, game state or
input-release proof was added. PlannerPort remains a cooperative API, not an OS
security boundary. A new entities sample intentionally requires a new proof and
new proposal even when its content is unchanged. Terrain dependencies remain
whole-section, not per-cell. Safe renewal never extends a queued proposal's old
lease-capped expiry or an in-flight action deadline.

No Java/Node, resident, navigation, boat, expedition or unrelated integrated suites
were rerun for this Python-only change; their source is unchanged. Historical
counts from those suites are not counted here. No deployment, gameplay, UI, IPC,
authentication, service, backup, Drive or remote repository operation occurred.
