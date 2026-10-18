# Managed walking waypoint, version 1

## Public entry point

`mdc_job` capability `navigate_managed_walk`, capability version 1. Use the ordinary `request_only` owner chain. Obtain the running catalog and context first; availability requires the actual supported input-fence Mixin, not just a mod being present.

Arguments:

- `goal`: integer `x`, `y`, `z`, the destination feet block.
- `max_distance`: 1–200 horizontal blocks from admission, default 200. The goal must also be within 64 vertical blocks.
- `timeout_ms`: 1,000–120,000, default 60,000. This is the original native route deadline. One native safe-interrupt attempt has at most 10 further seconds to establish actual idle.
- `min_health`: 6–20, default 12. Any health decrease from admission also requests interruption.

For the default 60-second waypoint, use at least `deadline_seconds: 75`, `max_actions: 3`, `max_observations: 285` and one cleanup reserve. For 120 seconds use at least 135 seconds and 525 observations. The service default of 1,024 observations is sufficient. Very tight deadlines can expire during setup, so practical callers should allow a few extra seconds. A sample submission uses ordinary toolbox fields:

```json
{
  "api_version": "mdc.toolbox/1",
  "operation": "submit",
  "request_id": "one-unique-route-request",
  "session_ref": "FROM_CURRENT_CATALOG",
  "expected_context_ref": "FROM_CURRENT_CATALOG",
  "capability": "navigate_managed_walk",
  "capability_version": 1,
  "arguments": {
    "goal": {"x": 100, "y": 64, "z": 100},
    "max_distance": 200,
    "timeout_ms": 60000,
    "min_health": 12
  },
  "policy": {"version": 1, "execution_mode": "request_only", "reactions": "stop"},
  "budgets": {"deadline_seconds": 80, "max_actions": 3, "max_observations": 300},
  "wait_ms": 0
}
```

The coordinates are illustrative, not a certified destination. The playing AI chooses safe waypoints from current observations. Normal chunk loading is permitted, but the route explicitly reports `unloaded_terrain_certified: false`.

Cancel through `mdc_job` using the original `job_id`, `session_ref` and one `cancel_request_id`. Poll the original job; do not submit a second route or external stop while this owner is unresolved. The same original submission ID returns the durable job record and never starts another route.

## Ownership and effects

1. Acquire the ordinary sole-owner lease only while the actual external controller is proven idle. Unmanaged active work requires the separate explicit external-stop capability first.
2. Bind the original operation/job/owner generation, action session, world generation, player UUID, dimension, source tick/nanotime, deadline and exact goal. Persist this binding before submission.
3. On the native client thread, verify private single-player survival, the exact original player/world/owner revision and supported official Baritone API. Native fall rescue must be disarmed and no other MDC input owner may exist.
4. Temporarily install a fixed conservative walking configuration. Only this route's exact `CustomGoalProcess` and exact `GoalBlock` object are accepted. There is one `setGoalAndPath` attempt.
5. The optional actual `InputOverrideHandler.setInputForceState` Mixin blocks attack/use, including door interactions. Movement requests require the exact owned input handler and a fresh active-original-process/goal/context proof, followed by a pure original-owner/deadline check. It rejects new forced inputs during UNKNOWN. Forced-false releases always pass. The getter is unchanged and never hides existing forced keys.
6. One `cancelEverything` attempt may follow cancellation, route deadline, blocked interaction or observed health/environment/focus/mode hazard. A Boolean acknowledgement does not release control. No `forceCancel`, arbitrary command string or global input clear is used.
7. Bridge shutdown closes input admission before blocking work and immediately quarantines the exact token. The captured token is passed to client-thread cleanup so a delayed callback cannot stop a replacement. Its client-thread callback may request the one same-owner bounded stop; subsequent native ticks can prove cleanup even after the endpoint closes. The token retains its closure flag, so native tick still initiates original cleanup if a callback was delayed or lost. Restart cannot make that old token usable. An already-UNKNOWN route retains its original phase, reason and attempt history without a cancel retry.
8. Two strictly later distinct native ticks must prove actual API idle and neutral controls. Restore settings only while exactly owned and every installed value is unchanged. Then publish settled control release. A user-changed value is never overwritten.

The setter proof uses the supported pinned read-only API implementations and cooperative vanilla context getters. It does not claim immunity to arbitrary hostile transformations or mod hooks. Any unsupported/custom process, version or missing setter transformation is unavailable or UNKNOWN.

## Terminal evidence

The production payload, endpoint wrapper and exact JSON codec carry original identities, start/stop attempt flags, nullable cancellation acknowledgement, original admission/current sample ticks, remaining original route time, goal result, settings restoration, control release and the closed external-controller proof. Both Resident and Runtime validate the same original binding and monotonic status.

- Success: the exact goal feet block is observed, grounded, actual idle is proved and settings are restored.
- Interrupted/cancelled: actual idle and settings restoration are proved, with the explicit reason. A hazard, native stop or public stop takes precedence even if the goal was reached simultaneously; `goal_reached` remains observed evidence. A blocked door/use request reports `managed_navigation_door_or_nonwalking_input_blocked`.
- UNKNOWN: a mutation receipt is lost, ownership/goal/context changes, settings change, proof is malformed, or actual idle cannot be proved. The original job/lease and native quarantine remain. No retry, new owner or automatic resume follows.

UNKNOWN blocks new forced inputs, but does not fabricate release of keys already held or overwrite a replacement user's controller. It is not a promise of physical safety. The public result distinguishes control release from physical safety; the handoff observation remains the place to inspect current hazards.

## Scope and prerequisites

Supported artifact: official API-neoforge Baritone 1.11.3, SHA-256 `7f9f40952c49e78388e4e9ceaa6fd91a5b662238e06c997b3de5438177f99d8d`. This optional API artifact replaces the standalone variant; do not install both. Unknown binaries fail closed. This change does not itself deploy or replace a mod.

Walking only, including ordinary jumps and one-block descent under the constrained planner. No mining, placement, inventory manipulation, attacks, use, swimming, boats, flight, portal traversal or attached fall-rescue policy. Door interaction can be requested separately by the playing AI after verified release.

Existing public boat and portal interfaces remain separate. There is no standalone public swimming-route backend. Cross-mode itinerary/waypoint planning stays with the playing AI.

Read-only managed status is available in full native state and its exact owner endpoint. This patch does not add a new lease-free public reconciliation profile; existing reconciliation must not be treated as settlement authority for this route.

## Review and tests

Canonical fixtures use the production lease and response model, then `BridgeServer.ActionResponses.result`, expected HTTP status assertions and `BridgeJson.toJson`. The exact bytes pass through real loopback HTTP transport, Resident and Runtime validation.

The actual pinned Baritone setter is transformed by production Mixin configuration. An inactive original process with null goal remains valid for terminal idle sampling but cannot authorize a fresh movement write. Its real transformed setter/getter/clear/handler bodies are executed in a minimal carrier without Minecraft-dependent construction. Direct and public API/user-forced variants are covered, including replacement during the proof callback. This is an offline setter-seam test, not a live instantiated Baritone route.

Live acceptance remains separate: supported API and actual Mixin readiness; short ordinary goal then useful longer waypoint; exact cancellation/idle; blocked door; owner replacement/lost response without replay. Record original operation/job/action IDs and physical state. Never conduct these cases in the preserved original world or while another public owner is active.


## Original owned source before start (TEST2.1 follow-up)

The Runtime acquires its ordinary execution owner once, then performs one authoritative
`Runtime.observe(entity_radius=8)` under that same owner. It never derives start freshness
from the cached `session.managed_navigation_source`. The immutable read must match the
lease context, owner, defense epoch and complete pinned idle proof. Its original native
source tick/nano pair is sent unchanged. The read identity and capture age are retained
in `managed_navigation_source` evidence; the start journal binds its before-context/tick.

After reservation and the final job checkpoint, Runtime revalidates that original read,
source binding and owner. A local 750ms conservative acquisition-age check starts before
the read is submitted; existing Runtime exchange checks also include later preparation.
Native admission still independently requires the original nano age <=750ms and tick
delta <=5 at both original admission fences. No clocks are refreshed or mixed. A fresh
read improves the path but does not guarantee queue delivery within five native ticks.

This adds one budgeted ordinary observation, with no reacquisition loop or start retry.
A known local pre-submit rejection retains `none_proven` and may use the existing exact
owner cleanup/release path. Once a start or read is uncertain, its original IDs and owner
remain unresolved. This slice does not classify native refusal as no-effect, settle the
historical TEST2.1 UNKNOWN job, or alter Java, packet gates, deadlines or schemas.
