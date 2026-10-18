# Bounded atomic compact observation, display-only v1

## Public access and coverage

Use the existing `mdc_observe` tool with `profile: "compact"`, an optional durable `request_id`, and `bounds: {"radius": 1}` (radius 1 or 2). This is an opt-in summary, not a replacement for full capability observations. The existing durable observation job/owner lifecycle applies. Exact request/job lookup, unknown shutdown behavior, and no replay after a lost outcome remain unchanged.

The native authenticated loopback endpoint is `GET /control/compact-observation?request_id=<exact queue request ID>&radius=1`. It captures bounded player, inventory and menu summaries, control state, an action summary, and one complete coordinate page of nearby loaded-client terrain. Radius 1 means 45 coordinates; radius 2 means 125; vertical extent is fixed at 2. Unknown or unreadable cells remain explicit unknown rows. The response is limited to 64 KiB; oversized responses fail rather than truncate silently.

Entities, menu slot topology, full item components, terrain collision/physics facts, and full action receipts are explicitly omitted. Coverage states `entities_captured=false`, `menu_slots_captured=false`, `terrain_physics_omitted=true`, `action_details_captured=false`, and `inventory_recovery_complete=false`. This summary cannot authorize inventory recovery, navigation, placement or another mutation. Full original action receipts remain available through their existing action/request IDs and archives. Additive `menu.recovery_context`, external-controller status and native fall-rescue status are retained when the integrated producer supplies them; absent controller/rescue data says `unavailable` and is never inferred safe.

## Atomicity and budgets

One Minecraft client-thread callback samples the existing `client-pre-tick-v1` clock and exact world/player/game-mode/menu/screen context, reads a fresh isolated terrain page, then captures coherent state/action/screen siblings. The complete operation must finish in the same clock generation/count/context and world game tick. The isolated scan never consumes or invalidates a paged acquisition cursor. A partial terrain page, clock/context change, unsupported clock, or page sampled ahead of final state is a failure. Neither legacy future-page guards nor the full capability validation contract is relaxed. No cached page is re-stamped.

The ID-only loaded-terrain scan has an 8 ms cooperative budget and a fixed 45/125-cell cap. The outer callback has a 100 ms cooperative budget checked around capture and projection. These are rejection budgets, not hard real-time guarantees: a stalled third-party getter cannot be preempted inside the client callback. Global rendered-entity enumeration is skipped for this compact profile. Worst-case live scheduling/latency still requires independent-world acceptance.

The native response carries the original producer clock, exact queue request ID, context and a native cost sample captured before the final size-encoding check. Bounded phase durations and the nested external-controller read cost are diagnostic only. Python independently validates types, identity, complete coordinate coverage with no duplicates, terrain/final-state ordering, response bound, and clock continuity. Python never manufactures a native timestamp or compares the native epoch directly with its own monotonic clock.

## No execution authority

`execution_authority=false`, `read_only=true`, and `server_confirmed=false` are mandatory. The Watchdog preserves the exact observation owner lifecycle but does not use compact data to replace its authoritative world observation or clear a post-mutation observation barrier. The Runtime does not install compact data as an execution preflight. Existing owner cleanup can perform its separate full neutral-state observation before releasing the lease. Unknown delivery keeps the original request and owner reconciliation barrier; no fallback read or second native request is issued automatically.

## Offline evidence

The validation harness compiles every native source with a 384 MiB maximum JVM heap and runs the production compact projection plus the actual `BridgeJson` HTTP codec without starting Minecraft. Positive/negative cases cover same epoch, changed generation/count, page-ahead-final failure, incomplete terrain, mixed siblings, byte/time budgets and query validation. Python consumes the actual Java bytes and tests strict faults including duplicate JSON keys and duplicate terrain coordinates. Actual Node MCP → owner Runtime → Watchdog → Resident tests use a synthetic native endpoint to verify success, invalid future terrain, and lost response with exact-ID reconciliation/no replay.

No successful real-world capture, native scheduling latency, server acknowledgement, or gameplay effect is claimed by these offline fixtures. Live acceptance must use an independent labeled test world and the final integrated artifact.
