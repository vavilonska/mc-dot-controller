# Versioned exact-state building

`mdc_skills.building` dispatches schema 1/2 to the retained full-cube executor and schema 3 to `building_v3`. There is no prewritten house design, coordinate teleport, excavation, server command, terrain-flattening path, process launch, connection, credential handling or automatic repair.

## Blueprint input

The import format is `schemas/building-v3.schema.json`. A schema-3 object has exactly:

- `schema_version: 3`
- `identity`: `blueprint_id`, exact external `revision`, `source`, `content_sha256`
- explicit `region` with `min` and `max`, no dimension wider than 64 cells
- `cells`: 1–8192 exact `{position, block, properties}` entries
- `clearance`: explicit air cells, with purpose `interior`, `access` or `cavity`
- `light_checks`: explicit `{position, min_block_light}` observations
- `access_points`: explicit integer full-height stand positions for an exit check

`seal_blueprint(spec)` computes the SHA256 of the canonical JSON object containing only `region`, `cells`, `clearance`, `light_checks` and `access_points`. It then runs the exact parser. It does not invent a source revision or approve a design. Any later content change invalidates the digest. `VersionedBlueprint.parse` rejects unsupported state fields, fluid/waterlogged cells, duplicate/out-of-region positions and incomplete or inconsistent door pairs.

`material_requirements(spec)` produces an exact item bill without crediting the world or inventory. One door item accounts for two block cells; wall torches use the corresponding standing torch inventory item. Existing cell credits and current stock are resolved separately by the read-only survey plan.

The palette includes the retained dry full cubes, wood planks, axis-oriented logs/wood, ordinary glass, glass panes, glowstone/sea lantern, crafting tables, oriented unlit furnace/blast furnace/smoker, listed vanilla stairs, top/bottom slabs, paired closed doors, fences, standing and wall torches. State fields are exact. Double slabs, trapdoors, redstone, fluids, gravity placement and arbitrary modded blocks are rejected. Neighbor-driven fence/pane connectivity, adjacent stair sturdy faces, and all five stair shapes are computed for each placement stage, including two-hop fence updates when a neighboring stair changes corner shape. The engine independently checks its actual placement-state prediction.

## Historical region planning versus fresh action admission

A 16-radius, 8-vertical scan contains 18,513 cells. At 128 cells per page and the existing 50 ms page interval, that cannot be a sub-800 ms fresh action sample. The executor therefore uses the distinct owned `Runtime.survey` type for global material/support/access planning. It preserves original page provenance and times, has no mutation authority and cannot be passed to `Runtime.execute` or `Runtime.result` as a fresh observation.

The global plan simulates a bounded support/placement order and reachable work stands without mutating the game. It can use historical surveyed geometry as a proposal only. Every actual navigation segment uses fresh local terrain through `mobility.navigate_loaded`; every placement separately acquires a fresh 4-radius, 4-vertical observation. Local target, all footprint neighbors, support, held item, exact current states, pose, reach, hit point and orientation are checked before dispatch. The native engine independently predicts the BlockItem placement state from its actual renderer pick. Original context, source tick/nano, 800 ms admission, exact item components and input-release requirements are unchanged.

The planned view must cover the entire explicit design and safety neighbors. Otherwise planning blocks rather than treating missing terrain as empty. Larger worlds are not automatically scanned or merged. No surrounding mountain is flattened.

## Placement and resumption

Each request supplies a real support face, world-coordinate hit point and ray-consistent yaw, exact primary target state, and one- or two-cell footprint. Door hinge selection uses the vanilla 1.21.1 neighbor-solid/double-door/lateral-hit rules, checked against the restored official compiled `DoorBlock.getHinge`. Top/bottom slab placement and log axis select the appropriate hit face/height. Wall-torch item-to-block mapping remains explicit.

Before dispatch, the full placement intent is persisted. After dispatch, exact footprint cells, expected neighbor updates, unchanged support and exactly one consumed item must all be observed in independent later samples. A door's upper and lower halves must both match, not merely the lower ID. Existing cells and successful cells are retained in the checkpoint and never silently reconstructed if removed. Every unknown or failed unverified placement remains pending. `reconcile_build_progress` only reads the existing footprint and expected neighbor changes; it never retries input or claims causation. The Runtime's original unknown-request/release reconciliation remains a prerequisite.

## Larger and multilevel access

The schema can express a 13×15, two-story or larger explicit model without a 512-cell format limit. The public `build` wrapper selects the legacy 512-placement/move default for schema 1/2 and the 8192-placement/move default for schema 3. Explicit smaller invocation budgets remain supported and are checked before starting. Door footprints count as one placement. Movement budgets also include returning to the original audit vantage.

Placement planning supports safe cardinal ascent/descent by one full block, walking on completed full-cube floors, and integer-height top-tread stands on dry supported stairs/top slabs. Native mobility independently validates actual collision geometry and forbids diagonal transitions on partial stair treads. Fractional-height bottom-slab destinations remain unsupported. The plan reserves reachable final local-inspection windows and a return to the initial safe exit stand before placing the first block, plus any explicitly declared exit-access check. Access must be possible through observed terrain or cells already present in the supplied exact blueprint; the executor never adds permanent scaffold blocks. Historical geometry can still change, so a later fresh route may correctly stop an already-started job.

## Acceptance evidence

Every placed cell has immediate exact local verification. Historical surveys never certify completion. Final acceptance physically visits a preplanned cover of bounded 4-radius, 4-vertical observation windows. Every specified cell, light check, clearance and cavity boundary must pass two independent, strictly later fresh local observations. Each cell retains its own two request IDs, ticks and capture times in a content-addressed local audit segment. Each segment is bounded to one window (at most 729 positions), tied to the job, exact blueprint hash, context and window index, and persisted before its manifest entry. The checkpoint/result retain segment references and hashes instead of duplicating all per-cell evidence in an 8 MiB checkpoint. `read_build_audit(runtime, job_id=...)` integrity-checks and expands the original per-cell evidence without observing the game. A completed-checkpoint reopen also verifies every segment and exact covered-position set; missing or modified evidence stops work. Main-checkpoint worst-case encoding is checked before mutation, including all eventual completed cells, the largest pending intent and audit-reference/receipt space. The movement budget includes every inspection window and return to the initial safe exit stand; scheduler calls also preserve an explicit worst-case audit action/time reserve from the original goal budget. It reports `simultaneous_region_snapshot: false` and `server_confirmed: false`, because different windows are inspected at different times.

Explicit clearance cells must remain observed air. A `cavity` must have a fully closed, observed full-cube boundary; an open interior or access passage must use its corresponding purpose. Light checks require actual native `block_light` evidence meeting the specified threshold. The presence of a torch alone is never treated as proof of spawn safety. No claim covers unlisted interior cells or an unprovided design.

## Original requested design boundary

The handoff refers to a previously approved 13×15, two-floor house at x=-201..-189, z=74..88, floor y=71, to be built only after all capability optimization and gameplay acceptance. The saved hosted Site was identified as version 1, source commit `1f208219a14af77cf5a275ab19c6a4f0545fbf95`; that identifies Site software, not an approved blueprint revision. The exact owner-approved geometry remains unavailable to this source-only development task. No design aesthetics were inferred and no construction occurred. The generic schema/executor is not evidence that the original exact house has been imported or accepted.

## Offline verification

`tests/test_building_v3.py` covers content/revision integrity, >512-cell multistory format, a reachable 13×15 floor plan that climbs onto completed blocks, oriented actual request payloads, top slabs, horizontal logs, wall torch mapping, paired doors and item accounting, exact upper-half rejection, connected fence updates, stair shape rules, unchanged/unknown no-replay behavior, read-only reconciliation, missing light evidence, bounded access and the real Runtime with long historical survey plus fresh local native guard binding. These are offline synthetic endpoint/geometry tests, not Minecraft gameplay acceptance. The isolated official-loader `PlacementVanillaSemanticsTest` additionally passed four real-engine tests (zero skips): real BlockItem placement predictions for stairs/corners/slab halves, door hinges and the real upper-half placement method, standing/wall torch item mapping, mixed stair-to-fence side support and log axis. Its allocation-only in-memory Level has no game/server/connection or entity collision physics; it is not live gameplay acceptance.
