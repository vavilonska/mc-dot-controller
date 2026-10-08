> A later isolated offline extension adds bounded singleplayer `boat_mount` / `boat_dismount` primitives; see [BOAT-TRANSFER.md](BOAT-TRANSFER.md). The historical drive-only scope below is preserved. No live acceptance is claimed.

> Historical phase-one design/test record. The current isolated `1.1.7-boat-passenger.1` candidate adds native passenger geometry and passenger-inclusive clearance. See [passenger admission correction](../client-mod/docs/boat-passenger-admission.md) and the candidate verification summary for current limits/counts. No post-fix live acceptance is claimed.

# Continuous boat drive, phase-one offline candidate

Version `1.1.7-boat-drive.1`, isolated from `1.1.7-combat-loop.5`.

This candidate is **not deployed, not game-tested, not live calibrated**. It does not contact Minecraft, resident IPC, UI, or a game server during its development/tests. A successful build or formula-model test is not an in-game safety/performance result.

## Supported scope

Already aboard an ordinary vanilla boat in the controlling seat → supply an explicitly observed, already-loaded still-water route → native client ticks keep driving through ordinary intermediate waypoints → slow ahead of corners/endpoint → stop on clear water and stay aboard.

- One immutable route, 1–64 waypoints, each segment at most 16 blocks, total length including current boat to first point at most 256 blocks.
- Required finite lease: 1,000–120,000 ms. One fixed monotonic action deadline; an identical retry observes its original result. A changed payload under the same ID is rejected. There is no lease renewal or dynamic route append.
- Waypoints are horizontal X/Z; one required `water_surface_y` names the top surface of the water blocks (for water blocks at Y=62, use 63).
- All route water/clearance is checked at admission. Every tick rechecks actual boat identity, passenger order/identity, water state, momentum and heading safety corridors, current blocks, and nearby entities. It does not request new chunks or use coarse four-block terrain samples as a navigability proof.
- Intermediate waypoints advance inside one tick and keep the same action/input owner. The endpoint is a separate settling phase.
- Requesting 256 blocks does not guarantee reaching them within 120 seconds. Unknown, narrow, dangerous, stale-context, changed-passenger, or obstructed routes stop rather than extending scope.

Not implemented: automatic boat placement, mounting, dismounting, picking up a boat, cross-unloaded-chunk travel, streamed/atomic append, ocean-scale destination planner, End exploration, boats on ice, chest/modded boats, currents/waterfalls/bubble columns/submerged travel, amphibious navigation, or automatic combat/escape/dismount. This is a bounded continuous segment capability, not complete long-distance navigation.

## Wire contract

`POST /control/action` accepts a strict new action. Every field shown below is required; no other fields are accepted. Real identities must come from a fresh observation, never copied from this example.

```json
{
  "action_id": "trip-unique-id",
  "action": "boat_drive",
  "boat_schema_version": 1,
  "timeout_ms": 60000,
  "expected_world_generation": "00000000-0000-0000-0000-000000000001",
  "expected_player_uuid": "00000000-0000-0000-0000-000000000002",
  "expected_action_session": "00000000-0000-0000-0000-000000000003",
  "vehicle_uuid": "00000000-0000-0000-0000-000000000004",
  "vehicle_entity_id": 10,
  "vehicle_type": "minecraft:boat",
  "water_surface_y": 63,
  "waypoints": [{"x": 0, "z": 8}, {"x": 0, "z": 16}]
}
```

Use the existing resident `op: action` passthrough only under the already-established single owner. The resident assigns the stable action ID. This change does not permit a second producer to bypass an active watchdog or established queue owner.

Observe through `GET /control/action/status?action_id=<id>`. STOP is the existing explicit `POST /control/action/cancel` with `{"action_id":"trip-unique-id"}`; it cancels only that active ID. Direct API takeover/release-all also cancels the active action before taking input. Do not issue a new action ID because a POST response was lost. Reconcile the named ID and action/process session first; the resident's existing uncertain-result behavior remains unchanged.

The server still reports `server_confirmed:false`: results are client observations. `result.boat.input_released` means the owned boat/input fields were cleared. `result.boat.boat_settled` means four consecutive decision samples met endpoint distance, horizontal-speed and angular-speed limits. Cancellation can validly return `input_released:true`, `boat_settled:false`; releasing input does not freeze momentum. Top-level `result.input_release_confirmed` is the existing combined cleanup result and must also be checked.

## Native control and limits

LocalPlayer.rideTick forwards left/right/up/down to Boat.setInput. Boat.controlBoat uses left/right to change angular velocity; player view/yaw alone is not boat steering. This implementation feeds ordinary movement inputs and reads boat body yaw/angular velocity. It never writes position, velocity, boat rotation, packets, or passenger membership.

Cached official 1.21.1 bytecode shows still-water drag `.9`, forward thrust `.04`, reverse thrust `.005`, and turning-only thrust `.005`. These facts inform deterministic regression models, not a replacement physics engine. Cruise policy uses a conservative `.26` blocks/client-tick target, `.46` observed-speed ceiling, and early slowing. At the endpoint the driver applies bounded ordinary counterthrust and waits for speed ≤ `.025`, angular speed ≤ `.25`, and distance ≤ `.65` for four samples. Countersteering has a larger deadband to avoid one-tick bang-bang angular oscillation. Actual boat ticking consumes the prior ride-tick input, so delayed-input model regressions explicitly preserve that one-tick pipeline. Predictive turn error is not wrapped a second time at ±180 degrees; a reverse-turn direction is latched above 150 degrees and retained until the geometric error falls below 90 degrees, rather than repeatedly changing the shortest side or chattering at a sector boundary. This avoids observed offline reversal/oscillation failures, including delayed-input near-180-degree cases.

Deadline/GUI/death/player/world change/cancel are handled by the existing outer action loop. Cancellation immediately releases owned input on the client thread and never continues braking. A frozen JVM/client thread cannot provide hard real-time release; these checks run when the client thread executes. A GUI opened by vanilla key handling after ClientTick.Pre can allow one boat tick to consume the previously queued input before a later input/post callback notices the screen; GUI cancellation is not an event-instant hard release. Physical keyboard activity is not a new automatic takeover signal, and existing input-isolation behavior is unchanged.

## Water and collision policy

The continuous translated AABB footprint uses actual boat width/depth, not the player footprint. Each intersected column requires two complete still source-water layers and three air layers. Every block's actual boat `CollisionContext` collision shape must be known and empty. Passengers whose current dimensions exceed the fixed clearance envelope are rejected. Nonempty shapes, water plants/other non-water blocks, shallow water, overhead fluid, bridge obstructions, bubble columns, out-of-world/border cells, and unloaded/unknown data fail closed. This policy intentionally rejects some water that a human could traverse.

The initial route has `.2` extra hull clearance. Each local safety corridor uses 1.0 extra hull clearance and a conservative `10 × speed + 2` coasting/observation allowance. Current velocity and intended heading are both checked before command output. This is a candidate conservative policy under ordinary still-water physics, not a proof covering all server lag, modifications, knockback or newly appearing hazards. Runtime route deviation > 2.5 blocks from the current route segment also stops.

All non-passenger entities are protected by conservative hull and 20-tick entity motion envelopes. Nearby hostile mobs/projectiles stop the boat action; it does not attack, flee, or dismount. Unknown/nonfinite or unusually fast observed entity motion (horizontal speed or absolute vertical speed above 1 block/tick) also rejects. The 24-block query padding covers the 20-tick envelopes of entities within those speed bounds; this is protection for queried/observed entities, not omniscience about newly arriving entities outside the loaded observation region. Dynamic blocks/entities are reread, never authorized by the admission-time snapshot alone. No model HTTP loop makes per-tick steering decisions.

## Shared observation / multi-planner audit

The `.5` resident already has an exclusive process flock, bounded queue/results, stable request/session IDs, one active recipe, no replay after restart, shared world/prospecting caches, and chunk-scan cursors. ClientActions has a single active native input owner and a session-wide action result registry. Raw key holds do not have the equivalent boat lease. These primitives do not yet form a public multi-agent ownership/revision protocol.

A minimal next interface can expose one read-only snapshot stream keyed by world/player/action/vehicle identity plus observation tick/revision. Planners can submit bounded proposals referencing that revision, a TTL, route/purpose and priority. One arbiter validates proposals and becomes the only action submitter. Native safety remains independent. The next-segment contract needs compare-and-swap revision, maximum route/tick budgets, immutable action identity, and idempotent append IDs before it can be called safe/implemented. No external agent communications, new credentials, repeated full-terrain scans per planner, or competing raw inputs were added here.

## Verification and integration

See the delivery manifest and retained logs for final counts, checksums, and known skipped checks. New executable tests cover wire/identity/bounds/idempotency, turn/brake/waypoint continuity, deterministic straight/corner formula models, exact hull sweeps, unknown/dynamic block rejection, moving-entity protection and route deviation. Four source-wiring checks assert integration, but do not execute Minecraft. Actual client integration tests: zero.

Only three existing Java integration files change: ClientActionRequest, ClientActions, BridgeServer; boat-specific classes are separate. Access transformers expose three vanilla fields read-only in this code. BoundedCombat and TerrainReader are unchanged from `.5`. Apply the patch relative to `.5`, then resolve only the version/docs manifest with the separate `.6` combat candidate and rerun all tests. Do not silently replace a tested combat candidate with this isolated JAR.
