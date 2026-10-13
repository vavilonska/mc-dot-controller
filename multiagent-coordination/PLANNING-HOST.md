# Concurrent read-only planners and explicit native-host bridge

This optional add-on extends the existing SnapshotStore, PlannerPort, Coordinator,
preflight, threat evidence and single-owner executor. It does not replace them.
The original Coordinator remains dry-run. Revision 2 adds a compatible, owner-local
submission fence; see PLANNING-SUBMISSION-FENCE.md. No live adapter, resident, watchdog,
queue, credentials, permissions, model SDK or new network service is changed.

## Two planning layers

1. `result_kind='candidate'`: two or three callbacks execute inside worker threads,
   consuming identical immutable serialized snapshots. The owner's collector
   accepts typed suggestions only while the **original** source observation,
   lease, context/session, revision and continuity fences remain valid. The
   existing three-second observation TTL is unchanged. A refreshed cache cannot
   extend the old candidate's admission window.
2. `result_kind='advice'`: callbacks can produce only a route **goal suggestion**
   with source dependencies. Advice contains no action/timeout/authorization or
   old execution preconditions. It is not parseable as a Proposal. Its compute
   budget may outlast the source observation, up to the bounded current lease.
   Before any action the owner must obtain an independent new player, terrain
   and entities observation, verify task/session lineage, and invoke
   `route_candidate_from_advice(advice, new_snapshot, current_lease,
   max_waypoints=1)`. This recomputes a path from the new actual player position
   using new terrain, returning at most the first step by default. It rejects
   reused sample/capture identities, stale observations, changed context/task,
   unknown terrain, hazards and unreachable goals. It does not provide threat
   clearance or authorization. The owner must create a **new** Proposal identity
   and run the existing current grant, budget, threat and preflight admission.

The second layer is useful when real model latency exceeds three seconds. It
never renews an old Proposal, stamps an old observation with a new time, or sends
stale preconditions to the executor. Dynamic reflex/defense remains native.
Only route-goal advice is implemented here; resource and next-task suggestions
are future separate typed additions, not claimed implemented.

## Owner integration

Imports:
- `mdcoord.planning.PlannerScheduler`, `PlannerWorker`
- `mdcoord.advice.PlanningAdvice`, `route_candidate_from_advice`
- `mdcoord.host_bridge.NativeHostBridge`

Construct `PlannerScheduler(owner.planner(), owner.lease_state)` on the owner
thread. Construct two or three `PlannerWorker(role, compute, origin)` values.
`start(workers, budget_ms=30000, mode='parallel', result_kind='advice')` freezes
one snapshot and its source/lease lineage, then starts computation inside the
workers. Neither Coordinator nor PlannerPort is given to a worker.

On owner ticks, call `batch.collect()`. It returns immutable `ReadyCandidate`
objects or `PlanningAdvice` objects. This operation never submits or dispatches.
Submit at most one admissible sealed alternative, then call `batch.finish()`; discarded
alternatives must not subsequently enter the queue. Only the existing owner
submits and advances. Collection never gives a candidate a new lifetime: its
owner-issued absolute deadline and exact source sample are rechecked at submit
and pre-dispatch. Advice fresh replanning uses `seal_advice_candidate`, which
captures the new source before replanning and seals the resulting new identity.
`collect`, `finish`, start and close enforce owner-thread
use. New batches are blocked while any old cooperative callback is still running,
even after a timeout or discard. At most three callbacks can remain outstanding.
There is no automatic request retry. No uncertain action is retried here.

Callbacks are cooperative Python code, not a sandbox. Frozen bytes prevent
accidental shared mutation; they do not sandbox same-OS-user code or authenticate
native agents. Real host permissions and the existing sole-input-owner boundary
must still be enforced. `origin` is configured by the trusted host, not a model.
Arbitrary stuck Python callbacks cannot be forcibly killed; they block replacing
this scheduler's batch. The supplied native bridge has a bounded wait.

`diagnostic_drain=True` is only for a benchmark of stale direct candidates. It
allows measuring late compute without returning any expired candidate to the
owner. It does not enable execution after observation expiry.

## Actual native-agent host loop

The Python runtime cannot invoke conversation-native subagents itself. This
module supplies an executable explicit host bridge, not a fictitious model API.
The current assistant host performs the following steps using its existing native
subagent tools. No Cloud Codex task is involved.

1. Ensure two native worker slots will be available. Create an empty dedicated
   local spool. Start the benchmark with a short initial process yield:

   `python -m mdcoord.planning_benchmark --source native --result-kind advice
   --rounds 2 --workers 2 --budget-ms 30000 --spool /absolute/empty/spool
   --output /absolute/native-results.json`

2. `python -m mdcoord.host_bridge pending /absolute/spool` returns request
   envelopes. For every **not expired**, not previously dispatched request, call
   the existing native `collaboration.spawn_agent` once with the envelope's
   instruction and exact `request` JSON as data, `fork_turns='none'`, and the same
   requested reasoning effort for all workers. Use a new native agent for each
   request. The worker should return only the candidate JSON or null and perform
   no tools or actions. Never launch an expired request or retry an unknown
   launch. These instructions are a cooperative read-only contract, not a claim
   that native tool permissions were removed.
3. Record the actual returned native task ID for that exact request. When its
   final JSON arrives, save that JSON locally and call:

   `python -m mdcoord.host_bridge complete /absolute/spool REQUEST_ID
   --result /absolute/worker-result.json --native-task-id ACTUAL_TASK_ID`

   Completion uses create-once atomic files. Identity and snapshot digests are
   checked. Do not call complete with a fabricated ID or a mock result; those do
   not constitute a native-model run. A late completion can be retained as
   diagnostic evidence but cannot revive a timed-out batch.
4. Continue the host loop until the benchmark exits. Serial mode publishes one
   request at a time; parallel mode publishes both before either completes.
   The benchmark counterbalances serial/parallel order across rounds. It never
   connects to a game or formal queue.

The 30-second planning/lease budget is real. If the host cannot return within it,
report the timeout and do not fabricate a successful result. There are no tokens,
credentials or general network endpoints in request files. A local same-user
spool is **not** a security boundary. Request IDs, source digests, native task IDs
and host receive times provide inspectable provenance, not cryptographic proof.

## What the benchmark measures

Controlled benchmark:
`python -m mdcoord.planning_benchmark --rounds 24 --workers 3
--result-kind advice --output /absolute/controlled-results.json`

This uses real overlapping callbacks with controlled 40/80/120 ms waits and
synthetic data. Roles and serial first-role order are rotated; all three calls
are observed for the same per-call quality caps and whole-batch time budget.
It is a scheduler/owner-path experiment, **not** an LLM inference benchmark.
It does not establish a live gameplay improvement.

Native benchmark uses actual externally launched native agent completions. Its
worker time includes host queue/launch, model processing, response routing and
local polling; it is not isolated model inference time. Quality budget fields
are the same requested limits, not a claim that an API hard token cap was
available. Actual token use is unknown unless separately supplied by the host.
Both modes use the same semantic fixture hash, role set, quality request and
budget. The unique snapshot hash legitimately differs per batch because capture
identity and clock epoch cannot be reused or falsified.

For advice, the benchmark creates a new independent **synthetic** observation
and clearance after advice return, then replans and sends at most one action to
the FakeExecutor. Thus real model plus synthetic observation/actuation is a
valid label; real gameplay end-to-end measurement is not. Direct-candidate mode
keeps the original three-second window and reports expiry honestly.

Outputs include observation-to-first owner-admissible candidate/fake dispatch,
batch and worker times, timeout/expiry counts, source-expired-before-advice rate,
role order, sample counts, hashes and native-host evidence. Queued or syntactically
valid output is never called a safe candidate. Missing measurements stay null.
For fewer than twenty observations per metric, p95 is null; even larger controlled
samples do not imply reliable real-model tail latency. `speedup_claim` is null.
