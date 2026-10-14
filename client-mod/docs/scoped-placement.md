# Stationary one-block placement (candidate)

Profile `placement-local-observed-v1` admits one `place_block` command. It is separate from the general placement/blueprint paths. It uses the existing capability placement routine and ordinary `MultiPlayerGameMode.useItemOn`; it never writes a block or manufactures an interaction packet itself.

## Narrow contract

- Private integrated singleplayer, overworld, survival; focused, unpaused and no screen.
- An already-selected, plain vanilla cobblestone stack, count 1–64. No selection switch, procurement, movement, jump, sneak, bridge, orientation variants, coordination step or blueprint loop.
- Explicit integer support coordinate, exact supported plain full-cube block ID/properties, face, face-center hit, one exact target footprint. The target must be ordinary `minecraft:air`; the result must be property-free `minecraft:cobblestone`.
- One stationary player pose supported entirely by one static cell; finite loaded bounded geometry (at most 512 cells), no fluids, block entities or unsupported geometry. Exact protected inventory/menu/container/slot identity and selected material count are retained.
- Existing complete loaded-entity observed projection excludes interfering known entities, unknown classes and uncertain motion. This is current observed client evidence, not a guarantee of future dynamics.
- Original native owner/Entry/revision, session/world/integrated-server identity, navigation epoch and immutable scope witness survive every callback. Limit 2 seconds and 40 action ticks; each check is bounded to 250 ms and poisoned after failure or recursion.

The optional fields `hotbar_slot=-1`, `jump=false` and `sneak=false` may be omitted. Unknown intent fields are rejected. Generic capability identity, selected-item and navigation binding fields remain mandatory.

## Effect boundaries

1. The actual capability placement branch validates after click, prediction and ray hooks before opening the dynamic token.
2. `useItemOn` entry rejects reentry or changed player/hand/hit.
3. Plain `BlockItem.placeBlock` is fenced after placement hooks and before its single ordinary `Level.setBlock` invocation. Context, owner and one-effect counters are rechecked after callbacks; the attempt latch is charged before that call.
4. The returned ordinary use packet is bound to its sequence, exact object, support, face and complete hit geometry.
5. A final packet fence runs after NeoForge `NetworkRegistry.checkPacket`, immediately before `Connection.send`. It permits one exact use packet and at most one sync of the already-selected slot before the effect, rejecting other packets and duplicate sends. Fields and counters are checked again after callbacks.
6. The dynamic token is always removed in `finally`. The scoped path omits optional cosmetic swing dispatch outside that token; legacy placement keeps its original behavior.

Readiness is advertised only when all item, use/returned-packet and final-send mixin seams are installed and the existing entity reader is available. All injections are required. A compiled JAR alone does not establish those seams were applied by a running loader.

## Completion and uncertainty

The original placement observer requires five stable client ticks and exactly one material decrement. Cleanup additionally rechecks protected inventory and settled target state before reporting success. Any failed/cancelled/exceptional result after possible local use, including cleanup uncertainty, is unknown and requires handoff; it must not be replayed. A successful result explicitly does not claim server acknowledgement.

The footprint deliberately rejects many otherwise ordinary situations, including menu revision changes or unrelated inventory changes during settling. Live ordinary-world acceptance is still required before this profile can be represented as a proven working placement capability.

## Verification limits

The offline gate compiles all production Java against pinned genuine Minecraft/NeoForge binaries, exercises production pure intent/callback/packet identity logic, checks the selected capability branch in source and compiled bytecode, verifies the legacy placement body unchanged, and inspects genuine game bytecode for injection targets. The existing movement/mining/collect/combat offline suite remains applicable.

These tests do not start Minecraft, apply mixins, use a real world, demonstrate a successful block placement, deploy a mod, or prove arbitrary asynchronous third-party-mod behavior. Do not describe them as live acceptance.
