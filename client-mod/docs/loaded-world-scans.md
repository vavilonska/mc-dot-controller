# Loaded-client-world queries — 1.1.6-loaded-scan.1

This candidate includes all entity-aim.2 features (view-only aim lock, player
biome ID and visible-face mining fallback) plus the read-only scan below. The source build is offline-verified. A later small live scan passed, as recorded
in [current verification](loaded-scan-verification.md); that bounded result does
not establish all query modes, maximum-scale performance or combat accuracy.

## Interface

All routes use the existing authenticated loopback listener and client-thread
marshal. No new port, token, input owner, health or single-player restriction.

- POST `/control/scan`: start one job with an idempotency ID
- GET `/control/scan/status?id=...`: read the named retained job; does not advance it
- POST `/control/scan/cancel` with `{"id":"..."}`: stop this read-only job

One active job, four most recent jobs retained in the mod. Reusing a retained ID
with the same request returns its result; different parameters return
`scan_id_conflict`. A new request while busy returns `scan_busy`. World replacement
or disconnect cancels the active job. Terminal results preserve old world identity
and observation time, so they are historical, never a current-world cache.

`scan_schema_version` is 1. `status` is running/succeeded/cancelled/failed. A 202
start response only means admitted. `started_at_ms`, `observed_at_ms`, and terminal
`finished_at_ms` are separate. Pure postprocessing/cancellation does not refresh
the world observation timestamp. Individual groups and sample surfaces retain
their own observation times.

Request fields:

- `id`: 1–64 ASCII letters, digits, `_` and `-`
- `mode`: blocks, biomes, surface_sites, ores, cherry_sites, both (default)
- `block_ids`: 1–32 registry IDs; `ore_ids` is an exclusive alias
- `biome_ids`: optional 1–32 true registry biome IDs
- `bounds`: min_x, max_x, min_z, max_z and optional min_y, max_y (inclusive)
- `require_water`: boolean, default false except cherry_sites
- `water_radius`: horizontal distance limit 0–128, default 48
- `sort`: count (default), density, distance
- `max_results`: 1–256, default 64

Without bounds, snapshot the actual ClientChunkCache window via read-only access
transformers for center/radius. Missing entries inside it remain unknown. The
window is fixed when the job starts; move normally and start another job to extend
observations. No server state, world save, seed, `/locate` command or force-loading.
Explicit bounds can include missing chunks but are limited to 2,048 blocks per
horizontal axis and 8,192 chunks. Omitted Y means the dimension's legal full build
height. Explicit Y is intersected with legal height; an empty intersection fails.
Surface/water queries must include the legal world top, otherwise they fail with
`site_scan_requires_world_top` rather than mislabeling cave water as a surface.

## General queries and presets

`blocks` matches exact requested block IDs at every scanned block. Omitting IDs
uses the standard ore preset. Optional biome IDs restrict those matched blocks
using their actual client biome data. A planted cherry-log/leaves concentration
is eligible unless an explicit biome restriction excludes it. Presence says
nothing about ownership or permission to remove blocks.

`biomes` matches each intersected 4×4×4 biome cell using a representative block
coordinate (including partial cells at request boundaries). Results are sampled
quart-cell counts, **not counts of individual blocks**. Requires biome_ids; a
block filter belongs in blocks mode and is rejected here. This reads the chunk's
stored noise-biome registry value, not visual trees or a seed-based smoothing
lookup into unavailable chunks.

`surface_sites` samples terrain surfaces every four X/Z blocks. Optional block IDs
restrict candidates to 16×16 regions containing those matches; optional biome IDs
filter actual surface biome. `require_water` adds observed surface-water proximity.

`ores` is the standard ore-ID block preset. `cherry_sites` is the true
minecraft:cherry_grove + nearby-water surface preset, with explicit biome overrides
allowed. `both` scans the default ore set and generic surface candidates; callers
should specify filters for a focused house-site search rather than infer that all
surfaces are good house sites.

Example concentration query through the external resident:

```json
{"op":"scan_start","id":"cherry-water-1","mode":"blocks","block_ids":["minecraft:cherry_log","minecraft:cherry_leaves"],"require_water":true,"water_radius":32,"sort":"count","max_results":32}
```

## Bounded execution and results

The same state machine drives all modes, in nearest-origin chunk order and top-down
columns. Each post-tick slice admits at most 32,768 read/work steps and targets a
2ms best-effort time budget. Empty air sections can skip 16 known-air positions
without reading each block. Air-ID queries disable that shortcut. Sources and
chunk references are refreshed each tick: unloading mid-job marks the unobserved
remainder of that chunk unknown, never air. Time checks are between bounded work
units, not preemption; a water-neighborhood evaluation or status serialization can
exceed 2ms. No hard frame-time guarantee has been measured in the actual client.

`coverage` reports requested bounds, total/scanned positions, skipped known air,
fully scanned chunks, unknown chunks and their unobserved remainder, plus up to 64
unknown examples. Succeeded means the requested scan finished, not that missing
chunks became known. Coverage and all matches are live observations across time,
not an atomic snapshot. Outside bounds is unobserved. Counts may include blocks
changed after their observation.

`results.regions` combines all requested IDs in each intersected 16×16 horizontal
chunk region. It includes exact observed counts, counts_by_id, a few coordinate
examples, matched Y range, region-volume density, origin distance and individual
`counts_complete`. Ranking is by count/density/distance as requested. Density uses
the requested full region volume; partial or unloaded regions are explicitly
incomplete and must not be compared as fully observed. Biome-mode density has a
separate sampled-quart numerator unit. Region counts combine IDs; they are not
connected geological veins or counts of individual trees.

`block_clusters` (or preset `ore_clusters`, biome `biome_clusters`) provides the
first observed same-ID 16×16×16 bins with up to four exact sample positions. It is
bounded separately and may truncate; global counts and region ranking still see
all observed matches. The truncation/ordering and unrepresented-match count are
explicit. A cluster bounding box is not a claim every contained block matches.

Surface extraction ignores logs/leaves/vegetation and selects the top terrain-like
solid or actual water/bubble-column block. Waterlogged solids are not treated as
water bodies. A solid roof above cave water prevents that water becoming a surface
sample. Artificial exposed ponds and planted trees remain legitimate observations;
source/naturalness, ownership, path accessibility and safety are not inferred.
Four-block sampling can miss narrow streams and thin terrain features. Water
proximity is measured from a reported representative surface point, not the
entire region boundary. Terrain relief/height-range and neighbor count are reported;
`local_slope_rise_per_block` is a coarse relief-over-8-block estimate, not a fitted
slope or a guarantee of a buildable footprint. Missing neighbors are marked.

Arrays are capped by max_results. A final 192KiB compact ceiling can omit further
detail and sets `response_details_truncated`; total match counts are preserved.
The existing bridge/resident transport limit remains 256KiB. There is no unbounded
raw-block export or model-facing flood. Status/polling returns partial results
until block and surface/region postprocessing are done.

## Build and verification

From `client-mod/`, with Java 21 and an existing official dependency cache:

```sh
JAVA_HOME=/path/to/jdk-21 GRADLE_USER_HOME=/path/to/gradle-cache \
  bash gradlew --offline --no-daemon --max-workers=1 \
  -Dorg.gradle.parallel=false -Pbridge.noRecompile=true test build
```

The published defaults are version `1.1.6-loaded-scan.1` and NeoForge `21.1.255`.
The source retains aim, native-combat support and visible-face mining. Matching
mod and resident code must be used; an external command alone does not create a
missing mod endpoint. See [current verification and live limits](loaded-scan-verification.md).

Observe a small bounded query before relying on larger results. Status completion
is not proof of ownership, safe access, an atomic world snapshot or maximum-scale
frame-time behavior. No server address, player identity, world save, private
coordinates or raw live results are part of this source document.
