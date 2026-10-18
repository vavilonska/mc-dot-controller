# Finite survival-drop collection increment

This isolated candidate expands only the vocabulary accepted by the existing public `collect_local` capability. It has no live-world acceptance, deployment, installation or publication claim. All inherited historical receipts remain historical and do not certify this candidate.

## Exact supported vocabulary

There are 33 exact vanilla item IDs:

- Existing materials: stone, cobblestone, dirt, coal, stick, iron_nugget.
- Logs and planks for exactly oak, spruce, birch, jungle, acacia and dark_oak. Oak planks were already supported.
- raw_iron, charcoal, crafting_table and furnace.
- apple, bread, beef, cooked_beef, porkchop, cooked_porkchop, chicken, cooked_chicken, mutton, cooked_mutton and baked_potato.

All names have the `minecraft:` namespace. The public input schema derives its enumeration and human-readable count from the skill allowlist. Java and the independent resident validator retain their own explicit sets and are checked for exact agreement through actual Java-emitted wire bytes.

The eleven food registrations use exact vanilla `Item`, ordinary food defaults and no custom stack-size change. Logs, planks and workstations use exact vanilla `BlockItem`. Static registration-bytecode inspection is evidence about the tested Minecraft mapping, not a claim that any dropped stack was observed in a running game. The native guard continues to require a nonempty exact `Item` or exact `BlockItem`, maximum stack size 64, an empty component patch, exact item/component fingerprints, unchanged count and room for the entire target stack. A furnace's default empty-container component is permitted; a nondefault container/component patch is still rejected. Custom subclasses, renamed/modified stacks, tools, buckets, potions, carrot/potato `ItemNameBlockItem` objects and unlisted IDs remain outside this contract.

## Unchanged execution and evidence

- Exactly one explicit observed item UUID, one adjacent cardinal cell and one flat native movement.
- Grounded, resting, pickup-ready target; all original class, identity, velocity, position, lifetime and world/owner fences remain intact.
- Other item entities, XP orbs, projectiles and living entities do not receive a new exception. Any old refusal continues to apply. Multiple nearby drops or experience orbs can still prevent a collect action.
- No path search, diagonal movement, current-cell pickup controller, automatic repositioning, replanning or retry.
- The entire exact target stack must fit, even when the requested minimum is smaller.
- Only the already-supported known target-absence cancellation can proceed to independent stable typed inventory-delta verification. Unknown effect or cleanup stays unknown and is never replayed.
- Input release and original action/owner identity remain mandatory. Observed inventory acquisition does not assert causal attribution to a particular drop or server-final confirmation.
- This change does not provide food hunting, crop harvesting, recipes, consumption, tool crafting or an Ender Dragon workflow. Coal collection remains an existing allowed ID; XP-producing coal extraction is not enabled here.

## Offline verification

Focused Python coverage exercises every allowed item through the actual public toolbox, owner, resident and skill chain with synthetic native responses. Negative tests retain capacity, typed components, unsupported IDs, geometry, entity class, stale clocks, cancellation, input release and unknown-no-replay behavior.

The native producer in `client-mod/validation/mining-collect-combat/CombinedWireChecks.java` emits standalone and coherent production-codec bytes for every Java allowlisted ID plus the existing collect/combat fixtures. `capability-runtime/tests/mining_collect/test_native_wire.py` reads those exact files, checks Java/public/resident set agreement and applies the complete production snapshot, scoped-witness and retained-wire consumers. Captured game facts are synthetic. The native finite-policy fixture also checks the exact vocabulary and unchanged pickup-target exception.

A fresh full compile and these offline checks do not prove mixin-transformed runtime behavior, ordinary-world terrain usability, a successful pickup or game saving. Live validation requires a separately bound candidate artifact and authorized ordinary-world run.
