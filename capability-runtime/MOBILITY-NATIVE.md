# Loaded mobility and native increment

This source adds reusable bounded actions; it is not a fixed validation route, a game start, or a live gameplay result. No commands, teleport writes, creative inventory, second writer or multiplayer connection are introduced.

## Local movement

`mobility.navigate_loaded(runtime, goal, max_segments=128, max_steps=32, min_health=12)` runs bounded fresh local route segments. Its breadth-first local planner only traverses fully observed dry supported cells. Cardinal step-up/down is at most one block. Unknown cells, diagonal corner gaps, unsupported headroom, exhausted exploration budget and unavailable frontiers stop the goal. Goal arrival requires actual grounded settled pose. New native `capability_route` rechecks the current segment's support/headroom and deviation every tick. It never extends a route through unloaded terrain.

Full-cube dry natural/building surfaces are supported. Exact vanilla stairs can be used at their integer-height top tread through cardinal normal jump movement; top/double slabs also supply integer-height stands. Bottom slabs are not promoted into integer floors, and arbitrary fractional-height routes are not supported. No offline test proves that any particular live staircase has been traversed.

`pillar_up` performs one normal jump and one underfoot placement. It requires centered stance, observed upper clearance, a safe held block and actual one-item consumption plus settled one-level ascent. `pillar_down` mines one exact block underfoot only with an independently observed full lower support, bound tool and centered pose; native lower support remains guarded. `bridge_step` makes one ordinary sneak-controlled edge approach and support-face placement, verifies block/item evidence, then starts a separately observed route onto that block. Only caller-bounded composition can extend a tower/bridge. A failed/unknown mutation never replays.

End movement requires an actually equipped carved pumpkin. Native callback checks retain that helmet, health reserve, no levitation, no nearby aggressive Enderman, bullet or breath cloud. This is conservative cancellation, not a complete evasion policy.

## Boats

`boat_mount` uses the exact visible ordinary boat identity, an exact empty hand selected via the guarded selector, and one normal entity interaction. `boat_travel` replans finite loaded water segments. Every planned hull column needs two source-water layers and three clear air layers; water's native `hazards:["water"]` is explicitly recognized only in the two water layers. Native boat geometry, speed, passengers, obstacles, deadlines and input release remain authoritative. `boat_dismount` requires the actual vanilla predicted landing to have observed dry support before one bounded sneak action and then verifies grounded unmounted state.

The opt-in capability envelope is accepted by the existing strict boat request parsers. The legacy schemas are unchanged without that envelope. The implementation does not place boats, cross rapids, travel on ice or carry extra passengers.

## Gateway pearl

`gateway_pearl` consumes one actual pearl aimed at a uniquely observed loaded End gateway. Native gateway discovery reads loaded chunk block entities only and exposes truncation. The native shot accepts only a close stationary supported pose where a discrete vanilla trajectory can fit its entire launch-spread envelope inside the gateway aperture at an integer tick. Math uses actual pearl spawn eye-minus-.1, speed 1.5, float-.99 air drag, .03 gravity, bounded triangular launch spread, inherited known player movement and a numeric error margin. Loaded collision/fluid/entity sweeps cover all possible launch envelopes plus the next movement segment, matching collision-before-inside-block checks. Unproved geometry is rejected before the shot.

Native receipt separates `dispatched:false` from an actual shot, records the exact gateway target and trajectory bound, and never claims teleport completion. Python requires that original proof, one-pearl inventory loss, same-context 128..4096-block displacement, health reserve and two later settled dry loaded landing observations. This remains client-observed evidence; it is not server confirmation or a proof of arbitrary pearl flight safety. No-shot failures may be reviewed for a separately authorized return movement; an unknown shot may not be retried.

## Oriented blocks and read-only observations

The new exact placement path is only admitted with `capability_guard`. Original legacy placement methods remain byte-preserved. Requests bind the target and support, a real face hit/yaw and a one/two-cell footprint. The actual vanilla item's updated placement context and placement-state method are used, including wall-torch variants. The exact state is recomputed after the final mod hook before dispatch, and real renderer reach/line-of-sight remains required. All primary and footprint states plus material consumption must subsequently match.

Terrain exports actual block/sky lighting. Entity snapshots include actual Enderman aggression, shulker open-shell state, entity line of sight, and ordinary-boat passenger facts. Radius above48 is an explicit wider read scope with a128-entity cap; smaller legacy snapshots keep64. Missing/truncated evidence blocks higher-level discovery.

Historical wide survey is a distinct read-only mode: at most16 radius,8 vertical,15 seconds,256 pages and320 ticks, retaining every page's original tick/time. It never populates the navigation terrain cache, never refreshes a mutation preflight, and cannot be passed as a fresh action observation. Ordinary scan budgets and native action admission remain unchanged (800ms/five ticks).

## Validation boundary

Python tests cover planner safety, real native-schema water facts, empty-hand selection, no-replay and evidence predicates. Actual checked-in IntentClient→Watchdog→Resident tests cover gateway success, unknown-response latch and survey metadata, replacing only the native endpoint. Native tests exercise request policies and the discrete trajectory bounds. Official-loader placement tests, where available, are separately labeled engine-with-synthetic-world tests. None of these are live Minecraft movement, building, boat or End acceptance.
