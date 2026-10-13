# Controlled single-step owner integration

This candidate is opt-in and offline-verified only. It starts no game, resident,
watchdog, queue, browser, service or connection. No live acceptance occurred.
The original ResidentAdapter remains disabled; normal Coordinator construction
still uses FakeExecutor. The ordinary watchdog and follow_path behavior are
unchanged unless the explicit owner attachment / coordination_step action is used.

## Narrow executable scope

An authorized owner may attach ControlledStepRuntime to the existing Watchdog
through base_watchdog.run(..., coordination_factory=...). The factory receives
that existing watchdog; it does not create another QueueClient. It supplies a
Grant with follow_path only, max_actions=1 and no defense preemption, and 2–3
read-only PlannerWorker callbacks. Callback provenance is recorded honestly:
controlled fixtures are not native-host inference. The host spool is only a
bounded handoff for read-only advice; no planner receives owner, queue, lease
activation, cancel or dispatch operations.

The runtime obtains one shared completed scan, runs bounded parallel goal advice,
then obtains a genuinely independent scan and deterministically plans one new
cardinal block. The owner alone assigns a new proposal identity, current lease,
original source sample IDs and bounded TTL. The owner-local PlanningFenceStore
seals the exact proposal digest, source samples and original absolute deadline
before submission; collecting later or removing the fence cannot restart TTL. Alternatives are discarded after one
selection. No continuation, retries, combat, jumping, sprinting or inventory work
is enabled. Legacy watchdog combat/ranged/generic-release branches are suspended
while this narrow attachment exists. Any interruption stops or exactly cancels
this one action; attachment closure does not re-arm legacy behavior.

Native action restrictions:
- Private integrated singleplayer only; LAN-published and multiplayer reject
- One centered, cardinal, level block; timeout at most 1000 ms
- No jump, sprint, sneak or hotbar selection
- Ground support limited to stone, cobblestone, dirt or grass_block; feet/head exactly air
- Loaded/known/fluid-free cells and the existing continuous FlatStepCorridor
  sweep are checked before ownership and on every context callback
- Every other client-loaded entity in the conservative 8-block AABB is rejected,
  including items, projectiles, boats, animals and players; only self is excluded
- Pause, focus loss, screen, passenger/spectator, death, shape/motion changes,
  new hurt_time or an observed health drop stop the step

This is a controlled-floor step, not universal navigation or enemy safety. Native
checks use client-loaded observations. Passing tests does not establish real
Minecraft geometry, timings, server confirmation or task completion speedup.

## Evidence and clocks

Opt-in GET /control/state?coordination_step=1 publishes the raw signed JVM
System.nanoTime value as a decimal string at world.game_time sampling. The action
echoes it unchanged. Native admission rejects future/older-than-800-ms samples,
as well as a source tick more than five ticks old. It does not compare Java nano
time with Python monotonic time. No token registry or new credentials exist.
The diagnostic sample itself is not authority.

The resident retains original same-host monotonic request capture intervals.
Opt-in scan results use the scan's already collected final state C, with terrain
having its own original scan interval. A publisher ticket predates the request;
completed request IDs are consumed once. Cache reads, imports, save times and
new IDs cannot refresh old captures. Only original live sample IDs can bind a
proposal. A fresh player-only observation cannot borrow a prior scan as the new
independent same-scan terrain required by live admission.

Raw terrain is passed through the existing strict terrain Cell parser and a
narrow four-floor/air whitelist. Real native empty-entity evidence creates a
native_controlled_single_step ThreatClearance for the exact current entities
sample/content and one waypoint. Fixture clearance cannot substitute for it.

## Identity, uncertainty and release

The coordinator WAL records the existing resident mapping before submission:
request_id and UUIDv5(UUID(resident_session), request_id + ':1') native action ID.
The watchdog intent ID deliberately equals this request ID in this opt-in path;
ordinary IntentClient's three identity layers are unchanged. Result readers
validate the original queue request/session and exact native action/session/kind/
world, then require the native coordination marker and input_release_confirmed
is True. Completion additionally requires a same-context actual endpoint sample.
Explicit unknown_outcome/uncertain/post_uncertain never become successful task
receipts. A definite pre-input rejection has separately bound no-admission
proof; it is not inferred from a reason string alone.

Cancel is a distinct, single, exact-ID/session operation. Existing resident auto
cancel attempts are retained, so the owner cannot unknowingly issue a second
cancel POST. Missing/uncertain outcomes keep the slot blocked. Read-only
coordination_status can reconcile the same native ID through the existing writer,
with one read in flight and a bounded poll rate. It never retries an action.
A reconciled release does not erase the watchdog's input-release latch or re-arm
combat. Restart never resumes old monotonic freshness, grants or queued actions.

## Still required before deployment

Independent review of the final merged source; complete offline suites and wire
round trips; exact deployed resident/watchdog/native source identities; existing
sole operator authorization for the narrow scene; and separate live acceptance
of normal completion, entity/terrain change, menu/focus, cancellation, stale
sample, restart, uncertainty and confirmed release. Never mix this candidate's
JAR with an older runtime merely to acquire one new capability.
