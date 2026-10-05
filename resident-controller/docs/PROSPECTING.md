# Loaded-world prospecting

**Source and focused offline protocol checks, plus one bounded live scan.**
The matching loaded-scan.1 build completed a 4,864-position query reporting 41
coal blocks in 79 ms across 3 game ticks. This is one observed result, not a
maximum-scale benchmark, universal accuracy claim or combat test. No player
identity or private coordinates are published. The existing listener/token
workflow is unchanged; see [verification scope](../../client-mod/docs/loaded-scan-verification.md).

## Calls

Submit these through the existing `QueueClient.submit` or resident CLI:

```json
{"op":"scan_start","id":"survey-1","mode":"both","max_results":64}
{"op":"scan_status","id":"survey-1"}
{"op":"scan_cancel","id":"survey-1"}
```

Start options:

- `id`: 1–64 ASCII letters, digits, hyphens or underscores. UUIDs are valid.
  Omit it to use the mailbox request ID, which must then fit the same bound.
- `mode`: `blocks`, `biomes`, `surface_sites`, or the original `ores`,
  `cherry_sites`, and `both` (default) presets.
- `bounds`: optional object with integer `min_x`, `max_x`, `min_z`, `max_z`.
  Optional `min_y` and `max_y` narrow the vertical interval. Omitted Y limits
  use the dimension's legal height bounds. The mod validates/clamps the actual
  world interval and enforces its own scan-work limits.
- `block_ids`: optional array of 1–32 namespaced block registry IDs. Use
  `ore_ids` as the backward-compatible alias for existing calls, but never send
  both fields together.
- `biome_ids`: optional array of 1–32 actual biome registry IDs for the mod's
  biome filtering/annotation. Block names never imply a required biome.
- `require_water`: optional boolean proximity requirement.
- `water_radius`: optional integer 0–128. The mod evaluates water proximity only
  against available client data; unknown coverage is not proof of absent water.
- `sort`: `count` (default), `density`, or `distance`. Generic region results retain their
  reported count, density and distance metrics; the resident never re-ranks or
  substitutes its own metrics.
- `max_results`: integer 1–256, default 64.

Registry IDs require a 1–40-character namespace and a 1–100-character path.
Explicit bounds are limited to 2,048 blocks per horizontal axis and 8,192 chunks.
Surface/water queries must include the legal world top; lower maximum Y is
rejected instead of treating cave water as surface water. Surface sampling occurs
every four X/Z blocks and can miss narrow streams. Water proximity is horizontal
from a reported representative point; it does not establish access or safety.

`biomes` mode requires `biome_ids` and forbids `block_ids`/`ore_ids`; use `blocks`
with `biome_ids` to find specific blocks within specific biomes. Biome results
count sampled 4×4×4 biome cells (including partial boundary cells), not individual
blocks. Their density numerator is explicitly a sampled-cell count. Check each
region's `counts_complete` before comparing partial observations. In
`surface_sites` mode, explicit block IDs restrict candidates to 16×16 regions
containing those observed blocks; they do not imply a biome restriction.

Example bounded request:

```json
{"op":"scan_start","id":"ore-survey-2","mode":"ores","bounds":{"min_x":-64,"max_x":63,"min_z":-64,"max_z":63,"min_y":-64,"max_y":32},"ore_ids":["minecraft:diamond_ore","minecraft:deepslate_diamond_ore"],"max_results":64}
```

The resident forwards only these options, using the existing bearer/listener:

- Start: `POST /control/scan`
- Status: `GET /control/scan/status?id=...`
- Cancel: `POST /control/scan/cancel`, body `{"id":"..."}`

Each mailbox command finishes after one scan request. An outer mailbox
`status:"succeeded"` means that its requested scan exchange was acknowledged.
It does **not** mean the scan has finished. Read `result.status`, which is
`running`, `succeeded`, `cancelled`, or `failed`, and its coverage/reason.

The result preserves the mod's `scan_schema_version:1`, `scan_id`, `dimension`,
`world_generation`, `started_at_ms`, `observed_at_ms`, `finished_at_ms`, coverage,
and results. Generic `results` fields include `block_counts`, `block_clusters`
and `regions`, with `biome_clusters` for biome cells and `surface_sites` for generic surface samples; legacy
`ore_counts`, `ore_clusters`, and `cherry_sites` remain
compatible when supplied by the mod. All result fields pass through unchanged.
The resident never infers hits from missing/unloaded chunks or invents completed
coverage. Retained terminal statuses keep their original world identity.
The mod's 192 KiB detail ceiling can truncate result arrays, explicitly setting
`response_details_truncated`, while keeping aggregate matched counts.

To find actual cherry-block concentrations without restricting the query to the
cherry-grove biome:

```json
{"op":"scan_start","id":"cherry-blocks-1","mode":"blocks","block_ids":["minecraft:cherry_log","minecraft:cherry_leaves"],"require_water":true,"water_radius":32,"sort":"count"}
```

Add `biome_ids` only if that is part of the desired query. For example,
`"biome_ids":["minecraft:plains"]` requests that actual registry biome, even
when the selected block types are cherry logs and leaves. The resident keeps
query fields explicit rather than adding an implicit cherry-grove constraint.

The mod advances its scan across ticks; status reads do not advance it. The
resident does not automatically poll or run an exploration loop. Poll explicitly
at a reasonable interval. To expand knowledge, move normally until another area
is loaded and submit a new scan with a new ID. Neither scan operation moves,
mines, attacks, teleports, requests distant chunk loading, or submits game commands.

## Input independence and uncertain requests

The three scan commands bypass the semantic-task queue and remain callable while
that queue is busy or paused. They do not acquire input ownership, cancel tasks,
disable aim/combat, or release held keys. `scan_cancel` cancels only its named scan;
the ordinary `cancel` command retains its existing input-release meaning.

An uncertain start/cancel response is never retried automatically and does not
pause or clear the gameplay queue. The mailbox result includes the `scan_id`;
use a new mailbox request with `scan_status` and that same scan ID to establish
whether it was admitted. Reusing a mailbox request ID only reads that original
mailbox result, as before. A missing/old mod route is reported without trying a
different endpoint or modifying the game. Bridge identity changes retain the
controller's existing stop/restart protection.

## Bounded historical cache

`scan_cache.json` is private runtime state in the existing mailbox. It is never
included in the public source package. `QueueClient.scan_cache()` reads it without
network access. `session.json`, `observe`, and scan replies include a compact
`scan_cache` summary; scan replies also say whether `result_retained` is true.

- At most 32 latest-per-ID scan snapshots, with a total serialized bound of
  1 MiB. Older least-recently-observed entries are evicted first; refreshing an
  existing ID replaces that snapshot instead of duplicating it.
- Every observation keeps its original dimension, world generation, and mod
  timestamps. `resident_received_at` is the resident's wall-clock receipt time
  in seconds; it is **not** a refreshed block-observation time.
- Only snapshots matching the currently observed dimension and world generation
  enter the cache. Observing a different world/dimension, no world, or a changed
  bridge identity clears old entries. A returned old-world terminal scan remains
  readable in the individual result but cannot enter the new-world cache.
- Every resident start clears this file after acquiring its singleton lock. It
  never hydrates an old process's cache or restarts its scans. A stopped/crashed
  resident can leave stale files; compare the resident session and timestamps.
- `historical_observations_only:true` explicitly labels the file and summaries.
  Scan snapshots have their own age and partial-coverage limits. The cache is not
  a continuously refreshed world database; polling terminal status does not make
  its old observations current. World clearing occurs when the resident next
  observes the change, not through background polling.

## Verification

```sh
python3 -m compileall -q resident_controller tests
python3 -m unittest discover -s tests -v
bash -n owner-start.sh
```

The tests cover scan route allowlisting and existing authentication, option and
response bounds, start/status/cancel dispatch, running versus command completion,
no automatic polling/replay, retained timestamps, cache byte/count bounds,
same-generation dimension changes, world loss/restart isolation, and scan-error
independence from existing tasks, aim, combat and held inputs. They use synthetic
bridge responses and temporary mailboxes, never the actual game or credentials.
