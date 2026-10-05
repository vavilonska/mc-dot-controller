# Terrain and observation contract

## Source of truth

The companion terrain API adds observation fields to upstream MineClient Bridge
v1.1.5. Upstream protocol 2 alone does not establish terrain support. Source review
used the actual companion `TerrainReader`, `TerrainScan` and `BridgeServer`
implementations and their terrain API document. This component does not modify
the Java bridge or the separate combat controller.

The terrain and state contracts use the same common fields as the companion
external combat controller: protocol `mineclient-bridge`, schema version `2`,
terrain schema version `1`, world dimension and `world_generation`. The exact
vanilla floor allowlist also matches the combat controller. Code is kept independent
so neither controller has to import or arm the other's execution adapter.

## Paged observation

Initial read: `/control/terrain?radius=4&vertical=2&limit=128`.
Continuation: `/control/terrain?cursor=<server-generated-next-cursor>`.
The collector passes only these read paths to a caller-provided callback. It has
no HTTP implementation, token discovery or credential configuration. Supplied
read callbacks need their own finite I/O timeouts: collection-age checks cannot
interrupt a blocking caller function. The collector checks its elapsed budget
both before a read and when accepting its result.

Cells are ordered with X fastest, then Z, then Y. Every page must be contiguous
and match the initial origin, radius, vertical extent, total cells and scan
`generation`. Exact expected coordinates prevent duplicate, missing and shuffled
cells from being accepted. Final cursor may be absent or null. A page ending early
because its cooperative budget was exhausted is valid only when paging continues
through the complete scan. Missing final coverage rejects the scan.

`generation` identifies a scan. `world_generation` identifies a ClientLevel lifetime.
They are not interchangeable. A new scan intentionally uses a new generation;
any world-generation change invalidates plans and observations.

`consistency: live_pages` is required. Pages are sampled sequentially, never
interpreted as an atomic world snapshot. Default planning limits are a 40-tick
oldest sample and a three-second local capture span/age. A paused game does not
bypass wall-clock expiry. Movement simulation demands new local observations
with no more than two ticks and 0.3 seconds of terrain age before each action.
A large slow scan can fail these limits even if all pages arrived correctly.

Only a completed scan becomes a grid. Explicit unknown cells within that scan
remain blocked. A complete grid does not mean every cell is loaded or safe.
No rows, columns or chunks are inferred from neighbors.

## Geometry policy

A standable integer feet position requires:

1. Its floor cell is known, loaded, untruncated, dry and hazard-free under the
   supported allowlist; collision is a full cube with full top support
2. The feet and head cells are recognized vanilla air with empty known collision
3. Required cells are present in the scan; uncertainty is blocked

Slabs/stairs, leaves, ice, falling blocks, modded cells, plants and nonempty
fluid are not accepted by this first implementation. Collision bounds are only an
envelope; no path is inferred through a nonempty shape. Vanilla block allowlists
are a conservative policy for a limited supported environment, not a guarantee
against arbitrary gameplay mods changing familiar block behavior.

Diagonal movement also requires both orthogonal corner positions to be standable.
One-block cardinal descent requires its destination and destination's old-head-height
cell to be clear. Deeper drops and diagonal descents are blocked. Upward full-block
steps require a jump and are deferred.

## Planning budgets

Defaults: 2,048 expansions, 4,096 frontier entries, 128 path edges and 0.1 seconds.
A failed budget is a stop, not permission to return an unchecked partial route.
Nondominated cost/depth labels preserve valid paths within the edge-count cap;
a cheaper but longer arrival must not erase a feasible shorter arrival.

## State/status observation

Actual fields are `status.screen.present`, `status.mouse.grabbed`,
`status.held_mappings`, player feet `x/y/z`, player `on_ground`,
`state.world.game_time` and `state.world.world_generation`.
Status → state → status identity and ticks must agree. Both status player positions
and yaw must agree with state so a within-bracket displacement cannot leave old
geometry looking current. Every numeric value used for movement is finite.

Nearby entity shapes are not exposed. The initial fake-only execution policy
requires no nearby entities within an observation radius of at least four blocks.
No claim is made that `nearby` is an exhaustive server-side perception system.
The status schema does not prove unpublished singleplayer mode; this is one of
several reasons no live movement adapter is provided.
