# Reusable skill contract, version 1

The package uses a caller-supplied existing credential-free IntentClient. It does not discover queues, start processes, handle credentials, connect servers or bypass the existing sole writer.

`Runtime(client, journal_directory)` owns an exclusive durable execution checkpoint. `observe(terrain=False, radius=4, vertical=4, allow_menu=False, entity_radius=8)` returns an owned Observation with original context, tick, acquisition time and request identity. Only the newest safe, unchanged observation can admit mutation. A newer failed or unsafe read invalidates older preflight evidence.

`execute(skill, command, verify, before=..., max_samples=8, stable_samples=2)` submits one finite guarded native action. It binds the original sample/context, exact held/menu items and navigation origin/epoch, persists before submission, correlates gateway/resident/native IDs, requires terminal input-release evidence and checks semantic state in strictly later independent samples. `Outcome` separates succeeded, failed, blocked and unknown. All success is client-observed with server_confirmed false.

Immediately before the Runtime-to-IntentClient `submit` boundary, execution
rechecks the original observation age after durable reservation, final bound
state/session validation and defensive command preparation. The same inclusive
`0 <= age <= max_age` fence applies, with `max_age` still at most 800 ms; reversed
time also blocks. A successfully persisted pre-submit rejection keeps the charged
budget, exact request ID and command hash, marks the reservation blocked and
clears its pending slot without submitting or acquiring replacement evidence.
This is not an age guarantee inside `submit` or at native admission: the existing
downstream fences remain authoritative. Transport-started uncertainty retains
the original unknown/pending behavior. Existing checkpoint-failure semantics are
unchanged; a failed finish write does not establish durable pending cleanup.

Native `capability_guard` carries schema_version1, original source_tick and source_nano. source_nano is a signed64 decimal string. Admission retains 800ms and five game ticks; context/focus/private-singleplayer and task-specific checks continue during execution. Source evidence is never rebound after expiry.

`result(skill, observations, **evidence)` can describe an already-observed goal. Every historical observation must retain ownership and original bytes; the final observation must be current and fresh. Pending/unknown/unverified execution blocks success. `require_success` stops composition on failure. `reconcile` reads the exact original request only and never claims semantic completion or retries it.

Expected portal transitions are narrowly typed: requested destination, same player UUID/native action session/gateway, known released-input terminal receipt, then fresh stable destination observations. A known world-transition cancellation can be eligible; unknown outcomes, arbitrary replacement and subsequent context changes cannot become success.

Capabilities are reusable bounded functions taking Runtime first. The registry maps bounded JSON goals to concrete functions. Scheduler preserves original deadlines, action reservations, dependencies and goal identity across restarts, which freeze incomplete work for explicit revalidation. Historical memory always requires new observations. Unknown mutations and partial production are never automatically replayed.

See README.md for supported skills, exact limitations and the separation between offline evidence, actual-loader platform tests and live gameplay acceptance.

## Historical region surveys and scalable evidence

`survey(radius=16, vertical=8, entity_radius=48)` is an explicitly historical read. Its `Survey` is a different type from `Observation`. It preserves original page ticks/capture times, world/player/native-session identity and the full acquisition interval. It can inform a proposal but can never authorize mutation or anchor a successful goal. Every attempted survey invalidates the older preflight. `validate_survey` verifies ownership/immutability/context only, not freshness. Final large-building acceptance physically visits fresh local observation windows and records each region's actual ticks; no simultaneous whole-building state is claimed.

Exact response receipts are compressed into fsynced digest-addressed files. Terminal execution records move into immutable linked segments only after the segment reaches disk. Pending, unknown and semantically unverified IDs stay active. The manifest is replaced atomically afterward, so interruption leaves either the prior complete checkpoint or the new complete checkpoint; orphaned duplicate evidence is harmless. Reopen and `audit_evidence()` verify confined non-symlink paths, bounded decompression, compressed/decompressed hashes and sizes, schemas, original command digests, correlation identities and segment links. Archival does not erase action history or re-enable an identity.

Scheduler goal arguments above32KB use a content-addressed imported JSON file, with an absolute4MiB input bound. Every use/reopen verifies bytes/hash. Per-goal action budgets are at most32768 and the original deadline is checked before/after reads, before all native mutations and before final success. An enclosing skill can inspect `effective_remaining_budget()` to preserve ascent/return reserves. Resume uses a read-only runtime view; a predicate cannot dispatch a mutation or promote stale evidence.


## Bounded ownership of the existing watchdog

When the supplied client is the actual `IntentClient`, Runtime acquires one logical capability ownership lease through the existing local inbox before its first observation. The original context, defense epoch, owner and request ID are durably saved before submission. This is scheduling arbitration within the existing sole writer, not a credential or permission. The default lifetime is7200 seconds, configurable1–86400; the CLI binds it to its explicit goal deadline plus bounded cleanup time. No automatic reacquisition occurs.

The client sends local control-only heartbeats throughout planning and action waits. Gameplay/read intents and heartbeat counts are published separately. While the lease is active the watchdog does not start competing legacy defense actions, including between a native terminal receipt and later semantic observations. Every capability request is owner/epoch-bound. Native per-tick focus, context, species and hazard guards continue to apply. Unowned intents are refused; STOP retains precedence. Heartbeat loss, original lifetime expiry, restart with unreleased ownership, unknown action outcomes or unsafe resident policy quarantine the owner instead of launching fallback gameplay.

Expected dimension changes require the exact source request/native receipt, known input release, unchanged player/native session and a single fresh neutral destination sample. No arbitrary world switch or new session can renew a lease. Each action requires a fresh owner observation before another action can be submitted.

`close()` obtains a fresh neutral observation and records an exact release control only when no mutation or semantic result remains unresolved. Otherwise it stops heartbeats and retains the unknown ownership for explicit operator reconciliation. Inspect `close_outcome`; a skill can have a genuine completed semantic result even if later ownership cleanup is unconfirmed. CLI reporting occurs after close and never exits successfully when that cleanup is unknown. Control acquisition/release uncertainties are never automatically replayed or used to reactivate a restarted runtime.

## Explicit noncombat execution policy

The watchdog can be started with `--execution-policy noncombat`. Its ordinary default remains `standard`. Noncombat is a scheduling restriction inside the existing watchdog, not a second writer: it prevents legacy automatic combat/retreat/environment mutations outside the capability lease and rejects combat or unleased mutation requests. Observations, exact ownership controls and STOP remain available. A durable noncombat policy pin prevents a later default-mode restart from silently enabling defense in that control directory.

Use `Runtime(..., required_execution_policy='noncombat')` or `mdc_skills run-goal --require-noncombat` when that restriction is part of the case. Every current session and goal-success check requires integer `execution_policy_schema_version:1` and exact `execution_policy:'noncombat'`. Missing, changed or malformed mode evidence blocks the caller before another mutation.

A local pre-queue policy rejection is known no-effect only with the exact cancelled/noncombat_execution_policy receipt, explicit null backing queue identity, false gameplay effect and typed noncombat `policy_rejection` carrying `dispatched:false`. Any uncertainty/handoff flag takes precedence. This rejection does not replay a goal or imply success. Noncombat does not supply materials, daylight, credentials, a safe region or immunity from naturally occurring damage; the operator must still validate every approved case prerequisite.
