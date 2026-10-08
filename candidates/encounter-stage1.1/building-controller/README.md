# External building planner (source-only, experimental)

A Python standard-library companion to the thin MineClient Bridge. It previews
small floor/wall designs, counts materials, compares a blueprint to captured
terrain, and proposes a bounded **geometric** support order outside Minecraft.

**There is no execution adapter, placement primitive, game-input call, network
transport, credential discovery, automatic installation or world modification.**
Every blueprint and plan is `executable: false`; a `provisional_plan` is a review
artifact, never permission or proof that building can safely run.

## Run offline

Python 3.10+; no packages, installation or server needed. Run from this directory:

```sh
python -m unittest discover -v
python -m building_controller --help

# A 3x3 framed floor: eight stone-brick border blocks, one oak-plank center.
python -m building_controller blueprint \
  --template floor --origin 0 64 0 \
  --region-min 0 64 0 --region-max 2 64 2 \
  --width 3 --extent 3 --pattern frame \
  --output /tmp/my-floor-blueprint.json

# Compare the supplied example with explicitly synthetic terrain and inventory.
python -m building_controller plan \
  --blueprint examples/floor-blueprint.json \
  --terrain examples/fake-world.json --terrain-key pages --state-key state

# A 5-wide, 3-high wall running toward positive z, with an accent frame.
python -m building_controller blueprint \
  --template wall --origin 0 64 0 --axis z \
  --region-min 0 64 0 --region-max 0 66 4 \
  --width 5 --extent 3 --pattern frame
```

`--extent` means floor depth or wall height. All coordinates are absolute block
coordinates. `--region-min/max` are inclusive and mandatory; the region bounds
intended new block cells, not ownership or permission to act in that region.
Read-only terrain/support checks can inspect cells outside that target region.

Patterns: `solid`, `checker`, `frame`. Choose `--primary` and `--accent` from the
small full-cube palette shown by `blueprint --help`. Preview JSON contains a
top/front ASCII view, a block legend, each desired cell and exact material totals.
The width/extent limit is 32 each, with at most 512 blueprint blocks. Region spans
are at most 64 blocks per axis. Only the supported vanilla Overworld height range
is accepted. No stateful blocks, gravity blocks, stairs, logs, slabs, doors,
containers, fluids, redstone, modded blocks, rotation properties or scaffolding.

Plan inputs may be raw terrain pages, a list of raw/HTTP-wrapped pages, or a
capture group selected with `--terrain-key`. State may come from `--state FILE`
or a named group in the same terrain file using `--state-key`. Missing state
still produces a useful comparison/material upper bound, but blocks proposals.
Only blueprint definition fields are authoritative; any saved preview cells are
regenerated, not trusted. Output paths are exclusive-create and never overwrite
existing files. Stdout is JSON; invalid inputs emit JSON to stderr.

Exit codes: `0` preview/provisional plan/already complete, `3` blocked review plan,
`2` invalid input or output failure. There is intentionally no `execute` flag.

## What is checked

- Actual bridge protocol schema 2 and terrain schema 1, bounded ordered paging,
  exact coverage, consistent world/scan identity and bounded monotonic game ticks
- Known loaded air only for a new block; plants and other replaceable blocks do
  not count as air. Existing correct full cubes are skipped, not touched
- Any conflicting existing block blocks the entire proposal. No breaking,
  replacing, gathering, crafting or automatic inventory manipulation
- Unknown, unloaded, out-of-world, failed, truncated, contradictory, fluid,
  hazardous and unsupported cell evidence blocks affected cells or their six
  immediate neighbors. Empty non-exhaustive hazard tags never establish safety
- Below/horizontal full-cube anchors, grounded dependency chains and deterministic
  ordering. Floating cycles cannot support one another
- Complete 36-slot main-inventory evidence, correct-block deductions and per-item
  shortages. Offhand, armor, containers and hypothetical crafting are not credited
- Same-world survival state, coherent terrain/state game ticks, declared entity
  scan coverage including a conservative two-block margin, truncation/any-entity
  stops, and conservative player-overlap checks

Every blocker suppresses **all** proposed placements, including otherwise-clear
prefixes. Material `remaining_upper_bound` includes conflicts and unknown cells
because only proven-correct existing blocks are deducted; it is not a shopping,
replacement or gathering instruction. Empty inventory reports shortage, never
consent to obtain resources or alter the world.

## Limits and evidence

Proposed anchors prove adjacency/order only. **Reach, line of sight, navigable
standing positions, unobstructed click faces, correct item selection, movement,
turning, game physics and placement success are not established.** Offline files
cannot establish current freshness. A declared entity snapshot is not proof of
exhaustive live-world perception. Terrain pages are live pages, not an atomic
snapshot; all relevant facts must be reread at action time by a future validated
executor. Surrounding terrain checks are local and intentionally incomplete for
real-world safety, such as distant flowing fluids, falling blocks and mobs.

`tests/fixtures/captured_terrain_schema1.json` preserves sanitized actual captured
one-cell, 27-cell, seven-page and world-boundary response shapes. Identifiers have
been replaced; horizontal coordinates and game ticks have been rebased to synthetic
origins while relative geometry, timing intervals and Y semantics are preserved.
Names/player UUIDs and unrelated status fields are omitted. It proves wire
compatibility only. Its empty inventory, zero-radius entity query
and player-overlapping target deliberately produce a blocked plan, not readiness.

`examples/fake-world.json`, floor/wall blueprints and plans are fully synthetic.
They illustrate support ordering, not a tested Minecraft build or live acceptance.

Read [future acceptance boundary](docs/ACCEPTANCE.md) before implementing any
execution layer. Keep the client mod thin: observation and tightly bounded
primitives belong there; planning, aesthetics and policy remain external.

## Code map

- `model.py`: bounded templates, palette, explicit region, preview and counts
- `terrain.py`: strict captured-page/state parsing and evidence gates
- `planner.py`: comparisons, shortages, fail-closed checks and support order
- `__main__.py`: local-file-only JSON CLI
- `tests/`: unit, CLI, captured-schema and independent-review regressions
- `examples/`: reviewable synthetic input and output examples
