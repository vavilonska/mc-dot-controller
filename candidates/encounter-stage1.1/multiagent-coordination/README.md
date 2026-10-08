# MDC multi-agent coordination candidate

Status: offline / dry-run only. This independent `parallel-validity.1` candidate
was copied from the integrated candidate on 2026-10-07; that baseline is unchanged. No Java, resident, watchdog, navigation, boat or expedition code
is modified. Python 3.10+ standard library; POSIX local filesystem (`flock`,
`fsync`, `O_NOFOLLOW`). No dependency installation is needed.

This candidate lets multiple cooperative planning roles read one sanitized
observation and prepare bounded next-segment proposals. One privileged owner
arbitrates and dispatches to a fake executor. A pure compiler prepares existing
resident action-shaped dictionaries for inspection. The real adapter rejects
all dispatch, polling and cancellation: **there is no live integration**.

## Try it safely

From this directory:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q mdcoord tests
python3 -m mdcoord demo
python3 -m mdcoord sanitize-result fixtures/recorded_resident_synthetic.json
```

`demo` joins three short-lived cooperative threads, uses a temporary private
journal, and finishes two synthetic native actions. There is no persistent
process or listener. Its fake positions, times and ticks are not game evidence.

`sanitize-result FILE [--goal FILE]` consumes an already completed resident result
and prints a private whitelist view. It does not call `observe`, instantiate a
QueueClient, write dashboard files, or update a goal. Imported observations have
unknown freshness because their original owner-monotonic acquisition interval
cannot be established. Original resident completion wall time is retained and
labeled; reading a file does not refresh it.

`check-proposal FILE` checks the closed JSON schema and explicitly reports
`authorized:false, dispatched:false`. The CLI intentionally has no URL, queue,
token, live, start-watchdog, deploy or resume-execution option.

## Interfaces

- `Coordinator(directory, executor=None, clock=...)`: privileged, explicit owner
  API; default executor is `FakeExecutor`. Construction does not start a loop.
- `owner.activate(Grant(...))`: install one owner-authorized task with exact world,
  player, native action session and resident session, allowed action classes,
  spatial bounds, exact defense target IDs, fixed total duration, execution/action
  budgets and cancellation/preemption limits. A task ID cannot be activated again,
  including after restart; ordinary phases cannot reset its deadline or budget.
- `owner.renew(epoch, expected_revision, lease_ms)`: CAS renewal within the original
  fixed task deadline. Only a continuously valid lease under the same owner epoch,
  lease epoch and immutable authority fingerprint retains queued proposals. Renewal
  changes a private admission token, never original proposal bytes, receipt time,
  capped expiry, task deadline, consumed budget, or referenced observation evidence.
  Newly submitted proposals must use the current CAS revision. Expired, replaced,
  interrupted or changed-authority leases cannot restore old proposals.
- `owner.planner()`: snapshot / submit proposal / result / subscribe / poll /
  unsubscribe only. A planner has no execution, cancellation or grant method.
- `owner.snapshots.publish(context, source_id, sections, Acquisition(...), ttl_ms)`:
  trusted observation-owner entry point. Acquisition records the **original**
  capture interval in this store's monotonic epoch. Collection happens outside
  the cache; this method never initiates a scan or game action.
- `owner.threats.publish(ThreatClearance(...))`: strictly typed owner-only synthetic
  offline threat assessment, bound to exact entities sample and content version.
  No real adapter produces this proof; an empty store denies ordinary navigation.
- `owner.advance()`: one bounded arbitration step, called explicitly by the owner.
  No service or scheduling loop is included.
- `owner.reconcile()`: reads the exact action/request already attempted. Missing,
  running or mismatched evidence does not free the writer or cause replay.
- `owner.cancel_current()`: explicit trusted-owner exact-ID cancellation at most
  once. It is not exposed to planners. Unknown outcomes retain the writer slot.
- `owner.close()`: closes the local owner handle only. It does not claim that game
  inputs were released. An in-flight action remains recorded for recovery.

These are cooperative typed APIs, **not an OS sandbox or authentication system**.
A role is a descriptive label, not authorization. Python callers with owner
object access, the same OS account, or direct access to existing resident queues
are outside this separation. See [integration gates](INTEGRATION.md).

## Snapshot contract

Only `player`, `terrain`, `entities`, `inventory`, `action` and `scan` sections are
accepted. Each section has content_revision (revision is its compatibility alias),
independent sample_id and continuity_revision, exact context, source ID, source tick,
source-time meaning, original capture start/end, monotonic clock epoch, expiry,
quality, freshness, and bounded whitelist payload. Unsupported free text, chat,
player/entity display names, item NBT, authentication, arbitrary config, image/file
paths, URLs and recursive unknown fields are not mirrored.

- Freshness is not file mtime or time of subscription. Unknown original intervals
  stay unknown; expired data stays stale; incomplete/truncated/invalid data is
  never usable for action admission.
- Missing sections are listed explicitly. Updating only player state does not
  refresh terrain or inventory. Context change removes the old sections.
- content_revision changes only for sanitized effective content or quality changes.
  Identical genuine new captures preserve content revisions while updating sample
  identity and original capture/expiry metadata. A content change then reversion
  still creates newer revisions and cannot revive an older proposal.
- Queue entries pin freshness continuity for every referenced and mandatory section.
  Recovery after a stale/unknown/truncated interval creates a new continuity
  generation, even if no reader or arbitration step ran during that gap. Stale
  at-receipt evidence remains invalid after later refresh.
- Re-publishing the exact same source ID cannot refresh a TTL or revision. A changed
  payload under that ID is rejected. Source time/tick regressions are rejected
  atomically, without partially publishing earlier sections. Renaming/reclocking
  an old capture, adding sections, or cycling context cannot launder its expiry.
- Bounded inputs: 256 terrain cells, 32 entities, 46 inventory slots; 3-second maximum
  freshness horizon; at most 32 subscribers, each with 1–16 events. Slow readers
  drop oldest events and receive `resync_required:true` plus the count. Resync is
  another cache read, not another observe/scan.
- Source identity history is bounded to 4,096 entries with no eviction that could
  make an old ID fresh again. Capacity exhaustion requires a deliberate new owner
  session; it does not silently refresh or reset a running task.

`resident_observation` is a pure adapter for a confirmed resident result. Existing
native terrain does not state exhaustive hazard safety, native state does not
certify a target's attackability, and native ownership does not alone certify a
release-all. The adapter therefore does not invent safe terrain/entities or an
input-release proof. A later sole-owner bridge must supply those contracts.

`dashboard_view` returns a private, sanitized view of that same cache. A separate
optional goal record has its own unchanged `updated_at_ms`, `target`, task ID and
status. Goal maintenance time is never replaced by observation time, and a goal
record grants no action authority. No real state/goal export locations are touched.
The historical exporter remains unchanged and is not started by this package.

## Proposal and admission contract

`Proposal.parse` is the authoritative closed schema; see `tests/support.py` for a
complete synthetic example. It requires proposal/task ID, current epoch and lease
revision, role label, exact context, per-section `based_on` revisions, 50–15,000 ms
TTL, typed intent, up to eight prior-current-task dependencies, priority, explicit
player preconditions/expected starting position, and a boolean cancellation marker.
Unknown fields, non-finite values, duplicate JSON keys, arbitrary code/shell/chat,
raw key/command endpoints and unrecognized actions are rejected.

Implemented typed intents are deliberately narrow:

1. `follow_path`: 1–16 centered, adjacent cardinal flat waypoints, maximum 10,000 ms.
   Every start/waypoint must have known, nonfluid, nonhazardous full support and
   passable feet/head cells in the referenced complete terrain section. Fresh actual
   player state must match the plan's expected start. Latest fresh complete entities
   and an independent, current, bounded no-threat proof are mandatory even when a
   planner omits entities from based_on. No diagonals, jumps, drops,
   boats, mining, placement, menu clicks, portals or exploration into unknown cells.
2. `defend_entity`: one explicitly granted/observed supported hostile ID and type,
   maximum 3,000 ms. The prepared native command sets `approach:false, shield:true`.
   The typed request cannot use raw attacks/chat or select players/neutral targets.
   This is fake-executor coverage, not a live collision/friendly-fire guarantee.

A proposal may reference terrain without pinning an obsolete player revision:
actual player state is always independently checked fresh, grounded, alive,
screen-closed, in bounds, healthy enough, and at the concrete expected segment
start. This permits a prepared dependent segment after a new actual arrival
observation while reusing still-valid unchanged terrain. If the player revision
is explicitly included, it must also match. No predicted endpoint is substituted
for the actual observation.

The owner checks authorization, CAS, expiry, dependencies, all referenced revisions,
world/session, total budgets, remaining lease, and safety before admission. It
writes and fsyncs dispatch intent before calling the executor, then rechecks all
expiring guards **after persistence**. An action whose preparation consumed its
conservative action deadline is rejected before dispatch. Execution reservation is
not refunded on rejection/failure, and no normal phase refreshes total duration.

A bounded next segment may be prepared while another executes, but only the
single current action may run. Completion requires a matching action ID, request
ID, kind, world/player/sessions, terminal status and explicit released-input proof.
Success additionally requires observed postconditions. Proposal submission returns `queued`; executor acceptance may return `running`.
Neither is completion, and there is no server-confirmation claim.


### Compatibility and mandatory revalidation

The proposal wire schema still uses `based_on: {section: integer}`. In this
store epoch each integer denotes the section content revision; `revision` is an
explicit alias, so existing readers and dashboard metadata keep working. No old
process queue, lease, grant, proof, or monotonic sample is imported across restart.
This is section-level content comparison, not spatial per-cell dependency tracking:
a changed unrelated terrain cell still invalidates a terrain-dependent plan.

Admission independently reads current player position, health, alive/grounded/menu
flags, current corridor cells, source freshness, dependency results and budgets.
Equal content revisions are never permission to skip those checks. They run again
after durable dispatch preparation under snapshot and threat-store locks.

Navigation proof selection occurs at receipt without pretending a dependent
segment has already arrived. The selected proof ID is frozen and revalidated at
arbitration and after fsync. Proofs bind both entities sample_id and content_revision.
A newly sampled entities section therefore requires a new assessed proof and new
proposal, even when entity content is identical. This deliberately conservative
boundary is stricter than terrain/player content reuse. Negative or incomplete
assessments revoke earlier positives; revocation follows source/start aliases,
and replacing a proof cannot revive old evidence or queued IDs. Capacity overflow
permanently closes navigation admission for that proof store.

Proofs carry original offline acquisition, bounded corridor coverage, explicit
complete/valid/no-threat assertions and a 50–3000 ms TTL; the entities sample must
also still be fresh. These are independent synthetic owner assertions in tests,
never facts inferred from an unchanged entities revision, an empty list, or the
recorded-result adapter. There is no positional live threat adapter here.

Safe renewal keeps the original proposal expiry, including its original lease cap.
It does not extend already queued proposals up to a later lease deadline. It also
does not extend any in-flight action deadline, refund reservation, or recover an
unknown action. This trades some reuse for a simple immutable validity boundary.

## Crash, uncertain results and preemption

- One coordinator owner per journal uses process `flock`; pending proposals and
  receipt identities use bounded, atomic, fsynced local journal writes. New directory
  entries and their parent chain are fsynced; the final directory must be private.
  This assumes a local filesystem honoring POSIX locking/fsync semantics.
- The 4,096 proposal-ID tombstones and 256 task-ID tombstones are never evicted to
  reenable a consumed ID. Duplicate ID/same payload reads existing state;
  changed payload fails. There is no uncertain mutation retry.
- Restart creates a new owner epoch, restores no grant/lease/queue, marks an in-flight
  action unknown and cancels queued plans. No old plan or lease automatically returns.
  A crash between preparation and actual dispatch is conservatively unknown.
- Missing/ambiguous/mismatched results block new work. Read-only reconciliation uses
  the old exact action/request/context; a running or absent response remains blocked.
- Authorized defense may preempt only after full snapshot **and budget** admission
  checks. The exact old action receives at most one cancel. Only confirmed terminal
  release permits a later arbitration step to dispatch defense. A timeout never
  releases the slot or grants another input path.
- Within the same owner epoch, reaching a known deadline may send one separate
  exact-ID safety cancel even while status is unknown. It is never an action replay
  and does not clear the slot without release proof. After restart, the old monotonic
  deadline is incomparable; only explicit owner cancellation/reconciliation is used.
- Native independent timeout/release behavior is required for eventual real use.
  This candidate cannot guarantee a game releases inputs when the owner stops
  calling `advance`, dies, or loses transport. It creates no watchdog as a substitute.

## Latency measurements

`Metrics` retains at most 256 samples/category and bounded model-start markers.
All millisecond durations are differences in the one owner-monotonic clock:
queue receipt-to-dispatch, original observation/scan capture intervals when explicitly
recorded, dispatch-to-observed-terminal interval, and model start-to-end only when
both real boundaries are supplied. The executor's tick count remains a separate
native-domain count. Wall-clock source timestamps are labels, never subtracted
from monotonic time or ticks. Imported observations cannot supply missing timings.

`dispatch_to_terminal_observation` includes response/observation latency and is
**not** pure native execution duration. `native_execution_ms` is null pending a
verified native clock contract. Current `measurement_origin` is dry-run; model
wait is unavailable unless explicitly instrumented. Retry/cancel, duplicate
proposal/scan/observation, read-observation, and dropped-event counters are bounded
in category count. The implementation makes no measured game-latency or speedup claim.

## Verification and scope

The candidate includes the full baseline suite plus new boundary/fault regressions.
Exact final counts and the independent adversarial review are recorded in
[verification details](VERIFICATION.md). Run the tests against your final merged
source rather than treating this count as a deployment certification.

The demo establishes one shared terrain capture serving three roles, two prepared
segments committed only after fake arrival evidence, one fake writer at a time,
and zero actual game actions. This is an architecture/API demonstration only.
No real gameplay, OS input, network, credentials, server, backup, goal registration,
watchdog, boat task, expedition task or GitHub remote was changed.

Original stdlib implementation. No new third-party code, dependencies, license
claims or upstream assets were imported. The repository's existing licensing and
NOTICE distinctions continue to apply.
