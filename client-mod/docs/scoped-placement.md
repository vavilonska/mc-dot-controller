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

The footprint deliberately rejects many otherwise ordinary situations, including unrelated inventory changes during settling. Before ordinary use returns, the admission menu revision must remain exact. After confirmed return with one effect, one packet and the exact selected-stack decrement, settlement permits only that revision or its single successor modulo 32768. The successor is committed only after a complete successful callback check; rollback and further progression are rejected. Exact menu/inventory/slot/container identities and protected stack components remain mandatory. Live ordinary-world acceptance is still required before this profile can be represented as a proven working placement capability.

## Verification limits

The offline gate compiles all production Java against pinned genuine Minecraft/NeoForge binaries, exercises production pure intent/callback/packet identity logic, checks the selected capability branch in source and compiled bytecode, verifies the legacy placement body unchanged, and inspects genuine game bytecode for injection targets. The existing movement/mining/collect/combat offline suite remains applicable.

These tests do not start Minecraft, apply mixins, use a real world, demonstrate a successful block placement, deploy a mod, or prove arbitrary asynchronous third-party-mod behavior. Do not describe them as live acceptance.


## T22 observation and bounded settlement correction

The first ordinary-world microtrial recorded one effect attempt and one packet,
with selected count 5→4, then stopped at action tick 2 with
`placement_input_context_unconfirmed` and unconfirmed release. Its original
unknown outcome is preserved and must not be replayed or reclassified as success.
Admission menu revision 1 and later revision 2 were observed, with only the
expected selected stack decrement. The original caught exception detail was not
retained, so these observations do not establish a unique cause.

An offline reproduction executes genuine vanilla menu revision methods and the
exact old guard: the ordinary revision transition is rejected. The correction
allows the bounded post-return transition described above. It adds specific guard
and cleanup reasons under `result.placement_diagnostics`, and reports physical
input neutrality, exact release binding and semantic cleanup separately. Failed
semantic cleanup cannot produce success; an attempted uncertain action remains
unknown even if physical input release is confirmed. The closed placement terminal
schema is unchanged.

Tests cover exact extracted old/new menu checks, modulo wrap, rollback, jumps,
replaced menu/inventory/slot/container, changed protected contents/components,
owner loss, cancellation and poisoned callbacks. Exact extracted cleanup blocks
are exercised with the real action registry and synthetic observations. This is
an offline-reviewed fix; a fresh packaged artifact and bounded live validation
remain required. It does not establish T22 success or authorize retrying T22.
