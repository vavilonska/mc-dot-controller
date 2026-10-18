# Survival workstation placement candidate

Source-only extension of `placement-local-observed-v1`. This candidate has not been deployed or exercised in a live world.

## Public exact contract

`place_local` retains the exact existing arguments and one stationary effect. Selected plain material may be:

- `minecraft:cobblestone` with `{}`
- `minecraft:crafting_table` with `{}`
- `minecraft:furnace` with exactly `{"facing":"north|south|east|west","lit":"false"}`

The caller specifies one actual horizontal furnace facing. Native ordinary placement prediction must obtain that exact state from the actual pose and hit. No caller yaw override, generic properties, material acquisition, hotbar switch, blueprint, retries or auto-resume is added.

Click supports remain the original 12 property-free block IDs. Placement uses separate LEGACY vocabulary constants so mining logs/ores cannot silently become placement supports. The placed vanilla BlockItem and vanilla block class/state are exact. Normal useItemOn remains the only placement path, with one effect, one exact packet and one exact selected-item decrement.

A furnace block entity is accepted only at this action's new target after the single-effect latch and for the exact selected unlit furnace state. It must be exactly FurnaceBlockEntity, with FURNACE type, matching level/position/state, not removed, with three empty inventory slots. All other dependency cells still require no block entity. Existing vanilla crafting tables may appear as unchanged context, but cannot become click or standing supports.

The immutable original intent, exact prism, owner, callback poisoning, reach, health, menu, inventory, deadline, input-release and unknown/no-replay rules remain in force. Client-observed results do not claim server confirmation.

## Composition context

The route planner, native local-segment controller and closed consumer additionally recognize crafting tables and six classic logs (oak, spruce, birch, jungle, acacia, dark oak) as context only. Neither support nor clearance vocabularies expand. Native checks require exact CraftingTableBlock/RotatedPillarBlock class, empty table properties or the sole vanilla AXIS property, full collision cube, ordinary friction and dry state. Every observed table/log state stays exact throughout a segment; no new equivalence rule is introduced.

## Conservative limits

- Preexisting furnace block entities still block placement prisms; only this action's new furnace target is allowed.
- Placement dependency prisms still reject nearby logs, leaves, vines, fluids, unknown geometry and ordinary projected entities. An adequately clear static site is required.
- Route foliage remains limited to the existing oak/birch leaves. Jungle foliage and vines may still block routes.
- Crafting, mining and container capabilities remain separate; this change alone is not an end-to-end dragon-survival implementation.

## Offline evidence

- Fresh compilation of all production Java sources.
- Production native checks: 71 closed intent boundaries, 13 callback boundaries, 15 final-packet identity comparisons, 787 settlement/callback checks.
- Java-emitted production witness/HTTP codec bytes for all three materials, each consumed by 11 Python wire tests. Captured world data and terminal-reader values are explicitly synthetic.
- 33 checks of exact unchanged source method slices for target material classes, target-only furnace entity gates and exact item decrement. Reader objects are synthetic, with source hashes and offsets retained.
- 52 Python producer/schema/witness/route planner tests.
- 11 JS-to-Python owner-chain tests including table/furnace success, cancellation, loss, unknown outcome, wrong inventory decrement and malformed arguments.
- Portable local-segment production controller plus real serializers, source-relation checks and 66 Python frontdoor/native-wire tests. Controller readers are synthetic.

None of these establishes transformed Mixin application, real placement prediction, live furnace creation/settlement, ordinary-world acceptance or deployment.

## Integration

The source-only patch intentionally excludes three baseline mining files changed only to provide compatibility aliases in this isolated candidate. Apply the mining worker's implementation first, providing `scoped_mining.LEGACY_BLOCKS`, `mining_snapshot.LEGACY_BLOCKS/LEGACY_STATIC` and `ScopedMining.LEGACY_TARGETS`. Keep the placement files from this candidate, not the mining candidate's baseline placement files. This candidate does not modify resources.py.
