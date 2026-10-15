# One-block descent candidate

`navigate_step_down` is a separate public capability under
`movement-step-down-observed-v1`. It performs exactly one ordinary-input cardinal
descent from a one-block isolated pedestal to a lower ordinary dry full-cube
floor. It is not general route planning, terrace traversal, step-up or a chained
movement controller. Existing `navigate_local`, `collect_local`, `navigate` and
`navigate_loaded` contracts are unchanged. The legacy navigation implementations
remain unavailable through the current public Owner backend.

## Public request

First obtain the current `session_ref` and `context_ref` from `mdc_catalog` and
confirm the capability is `runtime_available: true`. Given a centered feet pose
at `(0.5,64,0.5)`, the exact illustrative MCP tool arguments are:

```json
{
  "api_version": "mdc.toolbox/1",
  "operation": "submit",
  "request_id": "step-down-unique-original-id",
  "session_ref": "CURRENT_SESSION_REF",
  "expected_context_ref": "CURRENT_CONTEXT_REF",
  "capability": "navigate_step_down",
  "capability_version": 1,
  "arguments": {"goal": {"x": 1, "y": 63, "z": 0}, "min_health": 12},
  "policy": {"version": 1, "execution_mode": "request_only", "reactions": "stop"},
  "budgets": {
    "deadline_seconds": 60,
    "max_actions": 2,
    "max_observations": 64,
    "reflex_reserve_actions": 0,
    "cleanup_reserve_actions": 1
  },
  "wait_ms": 10000
}
```

The public arguments are closed: only the required integer `goal` and optional
`min_health` from 8 through 20 are accepted. Health must exceed the requested
minimum. Goal is one cardinal X/Z block away and exactly Y−1. Public timeout,
waypoints, native profile, jump, sprint, sneak, and replay controls are unavailable.
`wait_ms` controls how long the call waits for a result; it is not an execution
deadline. A continuing job is queried by its original `job_id`. Unknown outcomes
are reconciled by original identity and are never submitted again.

## Bounds and evidence

- Request-only, private Overworld survival, closed inventory, no active global
  MovementBudget. The movement profile is selected only for this capability.
- Native admission and every effect validate the same owner, context, position
  epoch, immutable footprint, ordinary movement envelope and complete loaded
  entity exclusion. Existing production acquisition guards remain unchanged.
- One `follow_path` action, one waypoint, no jump/sprint/sneak, at most 8 seconds
  and 160 native action ticks. Airborne descent is bounded to 20 action ticks.
- Native footprint has 180 cells: a 6×5 horizontal halo and six vertical layers.
  The bottom layer is ordinary supported full cubes. Only the start pedestal
  occupies the next layer; every other cell is literal dry air.
- Source is centered within .10. Endpoint tolerance is the existing .23, exact
  destination feet height within 1e−6, grounded, horizontal speed ≤.003, vertical
  speed in [−.09,0], released inputs and two later increasing-tick observations.
  Health and inventory are independently checked unchanged after the action.
- A successful endpoint is not guaranteed to meet the .10 origin tolerance of
  a subsequent movement. No chaining guarantee is claimed in this slice.
- Sampled horizontal displacement is diagnostic. It is neither a global
  distance meter nor proof of all-cause physical movement. Future entity motion
  and server confirmation are not certified.

## Offline verification boundary

`test_step_down_contract.py` checks the public binding, producer, negotiation and
Resident witness consumers. `test_step_down_frontdoor.py` launches the actual
production Node MCP executable over stdio with its real operator configuration;
that launches the unmodified Python toolbox entry point and real Owner, Runtime,
IntentClient, Watchdog and Resident components. Only the native Bridge endpoint
is synthetic. These tests are not game-physics or live acceptance.

Set `MDC_STEP_DOWN_TEST_RESULTS` to an external results directory to retain exact
MCP request/reply transcripts, native endpoint calls and Runtime/toolbox journals.
Native-generated wire tests are a separate consumer layer and must identify the
actual producer fixture used.
