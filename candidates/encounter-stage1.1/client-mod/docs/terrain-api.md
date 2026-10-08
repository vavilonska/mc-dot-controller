# Bounded nearby terrain API (experimental)

This terrain endpoint is based on upstream v1.1.5 and adds observation only.
Planning, material bills, navigation and combat policy remain external to the Java
bridge; separately documented guarded input primitives do not change this read API.
The complete mod compiled and passed its Gradle test/build tasks against NeoForge
21.1.255 on 2026-10-05 using the official binary-dependency pipeline. The preceding
terrain-only extension passed small read-only live checks: a 27-cell cube, equivalent
seven-page scan, and 17-cell vertical boundary. Maximum scans, navigation, combat
and the current movement extension remain unvalidated. See [build verification](terrain-verification.md)
and [limited live terrain evidence](terrain-live-validation.md).

## Request

`GET /control/terrain?radius=8&vertical=4&limit=64`

The existing loopback-only and bearer-token checks apply unchanged. Only GET is
accepted. The center is the player's current block position on the Minecraft thread;
arbitrary coordinates are not accepted. Defaults are radius 8, vertical 4, and limit 64.
The inclusive cuboid is `(2*radius+1)^2 * (2*vertical+1)` cells, including air.

- `radius`: integer 0–16 (X/Z)
- `vertical`: integer 0–8 (Y)
- `limit`: integer 1–128 cells per page
- Maximum scan volume: 18,513 cells
- Unknown parameters, duplicate parameters, malformed encoding, fractions, negative
  values, and oversized query strings are rejected with HTTP 400

Continue using `GET /control/terrain?cursor=<next_cursor>`. Do not combine a cursor
with other parameters. Only one scan is retained; a new initial query replaces it.
The anchor and bounds stay fixed while the player moves. Cursors expire after 30
seconds and are invalidated when the ClientLevel changes (dimension/reconnect).
Expired, superseded, out-of-order, or wrong-world cursors return 409.
Retrying the most recent continuation cursor returns the same page without rereading
blocks. An initial request has no replay token; retrying it starts a new scan.

Only one terrain game-thread task is queued/in flight at a time. New page reads are limited
to one per 50 ms. A concurrent or too-fast call returns 429 and `Retry-After: 1`.
The response also exposes `retry_after_ms: 50` for clients pacing successful pages.
The existing Minecraft dispatch timeout remains 5 seconds. A timed-out queued task is
skipped; a running callback retains the single-request admission until it actually
exits, so a slow callback cannot create additional queued terrain work.

## Response

The normal `ok`, `protocol`, and `schema_version` fields remain. Terrain adds:

- `terrain_schema_version: 1`
- `world_generation`: UUID for the current ClientLevel, also exposed by
  `/control/state` and `/control/status` under `world.world_generation`
- `dimension`: dimension identifier
- `generation`: UUID identifying this particular scan; not a world revision
- `consistency: "live_pages"`: pages are sampled sequentially, **not an atomic snapshot**
- `game_time`: sampling tick of this page, retained on cursor replay
- `response_game_time`: current tick when this response is assembled
- `origin: {x,y,z}`, `radius`, `vertical`
- `order: "x_then_z_then_y"`: X increments fastest, then Z, then Y
- `offset`, `next_offset`, `total_cells`, `returned`, `complete`, `next_cursor`
  (`next_cursor` is omitted once complete; consumers should treat absent/null as no continuation)
- `read_only: true`, `loaded_chunks_only: true`
- `budget_exhausted`, `read_elapsed_micros`, `unknown_cells`, `cells`

Each cell has `x,y,z`, `status` (`loaded`, `unloaded`, `out_of_world`, or `read_failed`), and `known`.
An unloaded/out-of-world/failed-read cell has `known:false`, and **no fabricated air, collision,
support, or block ID data**. Loaded cells additionally include:

- `id`, `air`, `properties`, `properties_truncated`
- `fluid`, `fluid_source`
- `hazards`: basic vanilla labels `lava`, `water`, `contact_damage`, `powder_snow`, `slowdown`
- `hazards_exhaustive:false`: an empty list is not proof of safety, especially with mods
- `collision_known`; when true, `collision_empty`, `full_top_support`, and, for a
  non-empty shape, `collision_bounds: [minX,minY,minZ,maxX,maxY,maxZ]` in block-local coordinates
- When collision is unknown, `collision_unknown_reason` and no support/shape claims

Properties are capped at 8 entries; unusual or over-32-character property keys/values
are omitted with `properties_truncated:true`. Identifiers are capped at 160 characters
with `id_truncated`/`fluid_truncated` flags. The existing 256 KiB JSON response guard remains. Collision bounds
are an enclosing box, **not a complete shape or a pathfinding guarantee**. Full-top
support is a conservative shape fact, not permission to move. Slabs/stairs and hazards
require external interpretation. No block entities, inventories, or NBT are exposed.

## Safety and performance

All world reads run on the Minecraft thread. The adapter calls the client chunk
cache with `getChunk(..., ChunkStatus.FULL, false)`, never forces loads, sends server
requests, or writes blocks. Missing chunks are explicit unknowns. Collision callbacks
receive a read-only BlockGetter allowing at most 64 reads in a one-block neighborhood.
Missing/outside-context/block-entity-dependent shapes are marked unknown. Runtime
exceptions from modded collision callbacks and nonfinite bounds are reported as
unknown collision, without partial support/shape claims. This is not a sandbox for
arbitrary mod code: collision context still refers to the real player, as required
for entity-dependent shapes. The extension itself performs no world writes.

Each page has a hard 128-cell limit and a **cooperative** 2 ms sampling budget checked
between cells. A single modded callback cannot be interrupted safely, so 2 ms is not
a hard frame-time guarantee. JSON assembly and dispatch overhead are additional.
The HTTP gate, 50 ms spacing, and small page cap bound normal request pressure.
Cursors keep only one page of data and use weak world references.

Consumers must reject stale or mismatched `world_generation`, dimension, sampling
age, partial evidence, and unknown terrain where those matter for the proposed action.
Before movement/building/combat, re-read the relevant local cells; never interpret
`complete` as evidence that the world has remained unchanged.

The existing upstream MCP wrapper is unchanged; use authenticated HTTP directly for terrain.

## Other additive fields

The existing `crosshair.distance` field is retained unchanged (squared distance).
New `crosshair.distance_squared` and `crosshair.distance_euclidean` make units explicit.

## Validation

Dependency-free tests (Java 21):

```sh
JAVA_HOME=/path/to/jdk-21 bash scripts/terrain-core-test.sh
```

Full build and all tests with the target client's NeoForge version:

```sh
JAVA_HOME=/path/to/jdk-21 bash gradlew -Pneo_version=21.1.255 test build
npm --prefix mcp test
```

Before a live test, preserve the current known-working mod/profile and explicitly
approve installation of the separately versioned `1.1.5-terrain.1` development build.
Test first in a separate disposable local world: no-world response, auth rejection,
loaded/unloaded boundary, cursor replay/expiry, dimension change, shape uncertainty,
page latency, and absence of outbound/world-write behavior. Do not claim server
compatibility until the same build is actually loaded and tested.

## Memory-constrained build hosts

ModDevGradle is updated to 2.0.148, matching the official Minecraft 1.21.1 template.
The normal source/decompiler pipeline remains the default. Where Minecraft source
decompilation exceeds available memory, use the officially supported binary pipeline:

```sh
JAVA_HOME=/path/to/jdk-21 bash gradlew -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
```

This still compiles the complete mod and runs its tests, applying the configured
access transformers to the game dependencies. It omits rebuilding Minecraft's own
sources. See [ModDevGradle's documented build mode](https://github.com/neoforged/ModDevGradle#disabling-decompilation-and-recompilation).
