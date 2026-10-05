# Protocol evidence and acceptance gates

## Reviewed upstream

- [MineClient Bridge v1.1.5 README](https://github.com/Campione01/MineClient-Bridge/blob/v1.1.5/README.md)
- [BridgeServer.java v1.1.5](https://github.com/Campione01/MineClient-Bridge/blob/v1.1.5/src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java)
- [Upstream MIT license](https://github.com/Campione01/MineClient-Bridge/blob/v1.1.5/LICENSE)

The immutable local v1.1.5 tag was inspected. The read-only terrain extension is
an additive companion change and is not part of upstream v1.1.5. Its exact schema
is represented in the fake transport tests and consumed conservatively here.

## Actual v1.1.5 behavior

Protocol name is `mineclient-bridge`, schema version 2. All control routes require
a bearer token and loopback caller. State reads/input run on the client main
thread. Nearby entity radius defaults to 16, maximum 32, maximum returned count
64. The returned entities have no extra visibility/line-of-sight filter.

Crosshair entity fields are `type: entity`, `uuid`, `entity_type`, `entity_id`,
`location` and `distance`. Player position is at feet. Entity positions in
`nearby.entities` are also feet coordinates; their `distance` is Euclidean.

**Legacy crosshair.distance is squared distance.** Bridge v1.1.5 calls
`HitResult.distanceTo(player)`, which in Minecraft 1.21.1 computes
`dx*dx + dy*dy + dz*dz`, without a square root. This was verified against the local
actual 1.21.1 `client.jar`, Mojang mappings (`HitResult -> exa`,
`distanceTo(Entity) -> a`) and `javap -c exa`. The inspected bytecode subtracts
three coordinates, multiplies each difference by itself, then adds them.
The controller never treats legacy crosshair.distance as blocks: it calculates
Euclidean distance from `location` and player position instead. The terrain
extension additionally names `distance_squared` and `distance_euclidean`.

`POST /control/look` body: `yaw`, `pitch`, `relative: false`. Bridge wraps yaw and
clamps pitch. Policy applies smaller per-step bounds before forming the request.

`POST /control/key` body modeled here:
`{"mapping":"key.attack","action":"click","exact":true}`.
Exact mapping input temporarily borrows an unused keyboard key and allows only
click; it does not reproduce mouse-specific mod events. This avoids activating
unrelated mappings sharing the attack binding. The adapter rejects missing,
cancelled or unconfirmed input-event delivery in fake response testing.

A world mouse click also exists in upstream (`button: 0`, `action: click`), but is
not exposed here. Named attack click is sufficient for this staged vanilla
controller. No other keyboard/mouse actions are permitted by its transport.

## Terrain evidence accepted

Read URL: `/control/terrain?radius=1&vertical=2&limit=128`.
Required terrain schema 1; generation and dimension must match `/state.world`.
The query has exactly 45 possible cells. Complete, known, loaded coverage is
required. Scan `generation` is distinct from stable `world_generation`.
Only current player-block origin is accepted. Sample ticks may differ by at most
2; status → state → status tick span may not exceed 3.

Cell identifiers, fluids and properties cannot be truncated. A basic hazard list
is not exhaustive, so safe floor IDs are explicitly allowlisted rather than
inferred from `hazards: []`. At floor level, full top support and full-cube
collision bounds are required. The three levels above must be known air.

The world-generation field is additive to the companion extension's status and
state schemas. Plain v1.1.5 lacking it and `/terrain` cannot pass this policy.

## Required live-acceptance work

1. Build/install the reviewed read-only terrain extension in an isolated local
   test client, with existing credentials kept private
2. Verify actual status/state/terrain schemas and missing/stale/unloaded behavior
3. Add a narrow game-thread guarded input operation. It must reject expired
   commands, changed session/world generation, mismatched live crosshair entity,
   changed screen/player and out-of-range targets at execution, not before queueing
4. Verify cancellation, wrong-generation, expired-action and GUI-race tests at
   that endpoint. Preserve normal reach and normal game attack mechanics
5. Connect this external controller to that guarded endpoint and test a short
   stationary local Survival session with a harmlessly bounded setup and an
   explicit stop condition. Verify post-run key release and resulting health
6. Only after this, consider a user-authorized server session under that server's
   rules. A source/test pass is not a live-combat pass

Movement, pathfinding and retreat need their own terrain-aware acceptance and
are outside this stage. The thin mod should expose guarded observations/actions;
combat strategy belongs in this external process.
