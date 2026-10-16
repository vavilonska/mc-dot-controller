# Bounded composable local route candidate

`navigate_route_local` version 1 is an additive capability using native profile
`movement-local-segment-observed-v1`. It plans a complete, loaded, finite route to
an integer feet-block goal. Each cardinal flat, one-block-up, or one-block-down
edge is a separate freshly admitted `follow_path` action. The caller does not
supply native waypoints, jump controls, terrain attestations, or recenter commands.

`navigate_local` remains the accepted single-flat-block capability;
`navigate_step_down` retains its isolated-pedestal contract. Legacy `navigate`
and `navigate_loaded` remain unavailable through the public Owner backend.

## Public request

Read the current `session_ref` and `context_ref` from `mdc_catalog` and require
`runtime_available: true` for this exact capability. An illustrative request is:

```json
{
  "api_version": "mdc.toolbox/1",
  "operation": "submit",
  "request_id": "route-local-unique-original-id",
  "session_ref": "CURRENT_SESSION_REF",
  "expected_context_ref": "CURRENT_CONTEXT_REF",
  "capability": "navigate_route_local",
  "capability_version": 1,
  "arguments": {
    "goal": {"x": 4, "y": 64, "z": 0},
    "radius": 6,
    "max_segments": 16,
    "min_health": 12
  },
  "policy": {"version": 1, "execution_mode": "request_only", "reactions": "stop"},
  "budgets": {
    "deadline_seconds": 120,
    "max_actions": 17,
    "max_observations": 256,
    "reflex_reserve_actions": 0,
    "cleanup_reserve_actions": 1
  },
  "wait_ms": 10000
}
```

Arguments are closed. Only `goal` is required. Defaults are radius 6, maximum 16
segments, minimum health 12. Radius is an integer 2–8; maximum segments is an
integer 1–16; minimum health is numeric 8–20 and actual health must exceed it.
Feet remain within the original source's horizontal radius and Y±2. Replanning
never moves these original limits, replenishes the shared budget, or explores
unknown frontiers. A full known route is required before every segment.

The planner consumes ordinary production terrain observations with vertical
radius 4. It checks exact known dry full-cube supports and literal-air swept
columns, including upward source headroom through source Y+3. Unknown, partial,
fluid, or unsupported protected geometry is blocked. Native admission captures
its wider context prism independently, so an unobserved surrounding cell can
still cause native refusal. Remote planning is never geometry authority.

## Segment and ownership boundaries

- Request-only private Overworld survival, closed inventory, ordinary dry blocks,
  no global MovementBudget, original world/player/session/navigation epoch.
- One Owner/Runtime job and original deadline/actions/observations across all
  segments. Each action has an independent identity and witness. No alternate
  owner, direct legacy native action route, position writes, or velocity writes.
- One cardinal native waypoint and at most one ordinary jump pulse for an upward
  edge. No sprint, sneak, diagonal, partial-block, ladder, fluid, or fall traversal.
- Native admission source centering is ±.10 per horizontal axis. The native
  controller centers a completed segment within .08 Euclidean radius, at exact
  goal Y±1e−6, grounded and horizontal speed ≤.003. Native terminal input release
  is followed by two increasing-tick Runtime observations before another segment.
- Per-native-action limit is 8 seconds and fewer than 160 action ticks, with a
  bounded 20-action-tick airborne interval. Native context/entity/raw-owner fences
  remain active before effects. Existing acquisition and Runtime freshness guards
  are unchanged; no extra harness capture-age gate is introduced.
- Any refusal, failure, cancellation, unknown result, context change, health or
  inventory change, missing route, or shared-budget exhaustion stops the route.
  Completed segments remain reported. The same movement is never replayed and no
  automatic resume is offered. Query original job/request identity after unknown.

The 150-cell flat or 180-cell elevation witness independently labels support,
clear, and surrounding context cells. Context permits ordinary full cubes, so a
nearby wall or terrace need not invalidate an otherwise clear swept route. The
loaded-entity witness remains complete and conservative. A separate context-only
allowlist additionally admits exact vanilla barrel, furnace, oak leaves, and
birch leaves blocks when native readers confirm their exact block classes,
full-cube collision, dry fluid,
ordinary .6 friction and unchanged block state. These blocks never become route
supports or swept-body clearance. Block entities are not opened or read by
movement. Other leaf IDs, containers, partial blocks, fluids and special blocks remain
outside this slice. Interaction after arrival requires its own exact native
reach/ray admission; movement success does not grant an interaction authority.
Sampled displacement
is diagnostic, not a global all-cause movement meter or future-dynamics guarantee.

## Offline evidence boundary

`test_route_local_contract` verifies closed binding, profile negotiation and
Resident witness consumers. `test_route_local_planner` checks finite planning and
composition with synthetic observations. `test_route_local_frontdoor` starts the
actual production Node MCP executable, sends initialize/tools-list/catalog/public
observe/submit/status/final-observe messages, and exercises the unmodified Python
entry point plus Owner, Runtime, IntentClient, Watchdog, and Resident. Only the
native Bridge endpoint is synthetic. Its success fixture traverses eight segments
around a solid obstacle and over a terrace; it is not game-physics acceptance.

Set `MDC_ROUTE_LOCAL_TEST_RESULTS` to retain complete JSON-RPC wrappers, original
request/reply NDJSON gzip files, terrain responses, native endpoint records and
Runtime/toolbox journals. `test_local_segment_native_wire` separately consumes
original Java-produced serializer bytes named by `MDC_LOCAL_SEGMENT_NATIVE_WIRE`.
That producer must include flat/up/down and an actual native move-hook rejection.
The latter retains the original cancelled receipt and canonical
`unknown_outcome=true` through the Runtime certainty boundary. The separate full
stdio negative verifies public unknown effect/cleanup, original-ID reconciliation,
and no subsequent route segment, retry, cancellation, or combat mutation even
when the rejected native receipt confirms neutral/released input.
Build, installation, ordinary-world acceptance and saved-world restart acceptance
must be reported separately for the actual final artifact bytes.

## Combined explicit defense policy

The default route policy remains `reactions:stop`. The combined public backend also accepts explicit `defend_once` with a caller-selected supported hostile UUID and original reflex/cleanup/observation/health reserves. Route still requires request_only. Only a known damage interruption with confirmed native release and fresh exact-target evidence may enter bounded combat under the same job lease. The route remains interrupted afterward and never resumes. Unknowns, cancellation, deadlines and environmental hazards do not trigger defense. See [terminal defense](../../docs/DEFEND-ONCE.md). This integration has no combined live acceptance yet.
