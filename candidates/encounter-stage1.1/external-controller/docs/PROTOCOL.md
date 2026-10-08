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

## Guarded actions replace legacy input

The earlier source-only controller modeled legacy look and exact attack-key
clicks but hard-disabled real HTTP mutation. The current adapter never sends
those routes: queued unguarded inputs can execute after a timeout/world change.

The companion `/control/guarded-action` endpoint supplies narrow execution-time
validation and a synchronous ordinary attack path. This is an additive extension,
not an upstream v1.1.5 feature. Its schema and acceptance restrictions are detailed
in [GUARDED_ACCEPTANCE.md](GUARDED_ACCEPTANCE.md). No real automatic-combat test
was performed by the external controller implementation task.

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

The guarded source and adapter are implemented and mock-tested. They still need
full target-version build/review, isolated installation and actual local endpoint
acceptance before arming the external controller. Follow the explicit gates in
[GUARDED_ACCEPTANCE.md](GUARDED_ACCEPTANCE.md). The default scope is unpublished
local Survival with an unenchanted vanilla axe; multiplayer remains unsupported.

Movement, pathfinding and retreat need their own terrain-aware acceptance and
are outside this stage. The thin mod exposes guarded observations/actions;
combat strategy belongs in this external process.
