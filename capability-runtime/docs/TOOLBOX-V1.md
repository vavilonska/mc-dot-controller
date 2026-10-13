# MDC toolbox v1

The four additive tools are `mdc_catalog`, `mdc_observe`, `mdc_plan`, and
`mdc_job`. The existing eight MCP tools are integrated separately. This module
contains no native transport, direct input writer, endpoint, credential, game
launcher, background strategy, or automatic resume mechanism.

## Public contract

Every call requires `api_version: "mdc.toolbox/1"`. The formal JSON Schema is
`schemas/toolbox-v1.schema.json`, validating `{tool, arguments}`. Exported MCP
input schemas have plain-object top levels and reject additional fields. A
closed operation-specific parser additionally validates `mdc_job` submit,
status, cancel, and reconcile. Domain argument schemas are separately enforced
before admission. JSON objects, nesting, size, finite numbers, string patterns,
array limits, and reserves are bounded. Python callbacks and objects are refused.

`mdc_catalog` works without a configured runtime. All 49 original capability
identifiers remain visible; domain additions are additive. A source function,
registered adapter, negotiated runtime feature, and live acceptance are separate
facts. Missing bindings and unavailable native features never become executable
just because the source exists. The default loader imports a fixed domain module
list; it never accepts caller-selected modules. Per-capability preview support is
explicit. A plan is optional and never conveys action authority.

`mdc_observe` returns only actual backend facts, source clocks, and coverage.
Missing coverage/provenance is labelled unknown, not reconstructed. Unsupported
selectors, profiles, or bounds return unavailable. Fresh observation is refused
while mutation ownership is active or unresolved, avoiding invalidation of another
operation's preflight. Historical/survey output is never admission authority.
Long-running asynchronous read jobs and arbitrary profile conversion are not
implemented by this first façade slice.

## Durable jobs

Construct one `ToolboxService(backend, journal_directory)` for the service lifetime
and call `service.call(tool_name, arguments)`. Construction takes an exclusive
journal lock. SQLite transactions use FULL synchronization. The caller request
ID, payload digest, absolute deadline and budgets are durably stored before
worker dispatch. Accepted IDs are retained (bounded capacity 4096), never expired
and reused. Identical resubmission returns the original job; changed immutable
intent returns `request_conflict`. Transport wait limits are excluded from the
intent digest. A lost response is recovered with exact status, never replacement
submission.

There is one active or uncertain mutation job per bound backend. There is no
implicit queue. Status reads do not call or advance the backend. A separate
thread accepts cancellation without waiting for the execution worker's lock.
Owner-context events are synchronously persisted before native request dispatch;
storage failure propagates, preventing authorization from being fabricated.
Events retain original sequence numbers with a bounded 512-event history and an
explicit gap marker.

The original total includes ordinary, reflex and cleanup lanes. Default reserves
are 0 reflex actions and 1 cleanup action, with 1024 observations. Defaults are
made explicit in persisted/public budgets. A mutating job needs allowance beyond
its reserves: one hotbar operation ordinarily requires `max_actions: 2`, including
one potential in-flight cancellation. Nested operations do not reset totals or
the original deadline. Unsupported metrics are rejected; planned route distance
is not advertised as actual displacement.

`effect_certainty` and `cleanup_certainty` are independent. A known semantic
result survives failed ownership release. A late pending cancel acknowledgement
cannot regress a later clean terminal execution; a genuine unknown cancellation
still remains quarantined. Before-start cancellation proves no dispatch. Running
cancellation is exact-owner only, cannot promise rollback, and settles only from
backend terminal/release evidence. Duplicate cancellation IDs never resend.

Startup converts interrupted accepted work to frozen `interrupted`, or dispatched
unfinished work to `unknown`; it does not create workers for recovered records.
Reconciliation only reads original persisted identities. It cannot introduce a
replacement action or restart work. New work remains blocked while effect or
cleanup ownership is unresolved. There is no public resume operation.

## Backend seam and operator process

`OwnerRuntimeBackend` is the P2 implementation over the existing Runtime →
IntentClient → Watchdog → QueueClient/Resident → native route. Its methods are:

- `describe()`
- `observe(profile, selectors, bounds)`
- `execute(capability, arguments, context)`
- `cancel_exact(job_context, cancel_request_id)`
- `reconcile_original(job_context)`

Execution context contains immutable job/request IDs, original epoch deadline,
shared budget, policy, expected context, and internal-only cancel/event hooks.
Results contain state, separate certainty fields, compact Outcome data, exact
original request IDs, ownership context and evidence. Backend mappings are
validated; nonnull domain results must match the advertised result schema.

The optional fixed CLI `python -B -m mdc_toolbox --control <existing-control>
--journal <toolbox-journal> --runtime-journal <runtime-journal>` is configured only
by the operator. Paths are not playing-AI tool arguments. It is a long-lived
JSON-lines service with `{id, tool, arguments}` requests and `{id, result}` replies,
1 MiB transport messages, and at most 32 concurrent requests. It opens no network
listener and starts no game. EOF/SIGTERM requests a bounded exact-owner stop;
unconfirmed shutdown remains durably unknown. It never retries or restarts itself.
The MCP integrator owns the fixed bridge and legacy-writer exclusion.

## Evidence scope

Focused façade tests use deterministic fake backends to prove lifecycle and
contract invariants. Node tests verify the additive tool module. These do not
prove native engine behavior, ordinary-world gameplay, real cleanup, timing, or
live acceptance. Domain, owner-stack, native and live validations are separate
and reported per capability. Terrain-dependent bindings remain legacy-limited;
only a positively negotiated backend lane can expose them for execution.
