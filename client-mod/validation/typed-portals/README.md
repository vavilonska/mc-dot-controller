# Narrow typed item and prepared portal entry candidate

This is source-only work on the preserved recovery-test.2.5 base, commit
39799603de3372ec30a917a09382684d3593566c. All production additions are independent
modules. Shared integration remains owned by the integration candidate.

## Closed public surface

- `ignite_portal_local`: exactly one selected plain flint-and-steel use on a fully
  observed obsidian frame, followed by separate one-durability and complete
  portal-block outcome checks. Width 2–4, height 3–4; no frame construction.
- `insert_end_eye_local`: exactly one selected plain eye inserted in one explicit
  unfilled inward-facing frame of an observed 12-frame ring. Last-eye activation
  accounts for exactly nine portal cells. No 12-insertion composite.
- `enter_portal_local`: one exact expected dimension pair, one explicit portal
  cell, flat supported dry approach of at most two blocks, no jump/drop and fixed
  original 5–8 second deadline. Input release plus known native transition
  cancellation is retained; it never manufactures native success.

There is no arbitrary item use, raw input, hotbar procurement, general planner,
legacy profile expansion, automatic retry, or resume. Unknown effect or transition
states cannot grant another effect or a delayed transition permit.

## Native integration contract

The integration owner supplies exact active and dynamically scoped terminal-cleanup
owner checks for both guards. The original capture-derived `deadline` is reused.
Item action ticks call `check` then the pure cached `settled`; never redispatch.
Portal steering calls `beforeEffect`, then pure `step` / `atPortal`.

`ScopedItemInteractionDispatch.use` brackets vanilla use with one dynamic token.
Five readiness markers cover game-mode entry, concrete flint, concrete eye, packet
entry and final packet send. Concrete `useOn` HEAD/RETURN checks bind the exact
item, hand, context, face, selected components, hit vector and typed SUCCESS result.
The flint redirect fences both actual `Level.setBlock(BlockPos,BlockState,int)`
call sites; the actual receiver and flags=11 are checked after Forge tool/sound
callbacks, immediately before local mutation. Eye's vanilla client path does no
local block mutation or decrement. Packet HEAD and final `Connection.send` fence
the exact `ServerboundUseItemOnPacket` hand/hit/sequence. Every use/context/local-effect,
result, packet-entry and final-send argument frame is reread after the last external
query and before charging its one-use counter. This includes exact nested hit/position/
location references and scalar bits, hand, sequence, selected slot, context stack,
local receiver/position/state/flags and typed result. A dedicated production fence
poisons mismatch/reentry and forbids further effect or retry. The exact vanilla
UseOnContext.hitResult field is read directly, with fail-closed field availability,
before admitting nested reader classes or calling public delegated getters. Later client observations
verify server-origin durability/count/block changes independently.

`ScopedPortalEntryDispatch.installed()` marks the actual contact observer seam.
Non-cancelling HEAD observer descriptor:
`Entity.setAsInsidePortal(Lnet/minecraft/world/level/block/Portal;Lnet/minecraft/core/BlockPos;)V`
forwards exact `this`, portal and cell to `.contact(Entity,Portal,BlockPos)`.
Contact must belong to the original player/action/source/server/session/owner,
inside the original deadline, with actual body overlap. Nether uses full block
contact, matching vanilla `entityInside`; End uses its exact y=6/16..12/16 shape.
Source-level lifecycle cancellation additionally requires same original player,
current overlap and contact in current/previous world tick. Destination-visible
callbacks still require the actual prior contact and original player's finite positive
health, not dead/dying and not below the original health floor. Legitimate old-player
dimension removal alone is not death. Contact records evidence only. Shared
`finishOwned` may normalize `player_changed` to `world_transition` only for a
cancelled action whose exact `expectedTransition` proof passes; Resident, Runtime
and gateway keep their strict reason sets, so generic death/clone never gains a permit.

Final data readers admit exact vanilla player/world/menu/inventory/food/abilities,
entity-data, attribute and data-container classes before initial reads. Protected
stacks compare item/count plus component-type/value identity without user-defined
`equals`/`hashCode`; equal-but-replaced component values conservatively fail closed.
Selected eye uses exact plain components; flint alone permits exact DAMAGE
normalization. Exact chunk, section and palette classes are admitted before raw
world reads. The last external-controller query is followed by a complete raw
policy check and unchanged block/entity/pose/inventory boundary, including actual
ItemStack references captured by UseOnContext, then the pure owner/context/tick/
original-deadline fence. Admission also binds its original ownership revision. Cleanup needs the exact original
terminal token; no `!ownsInput` fallback.

Resident validates closed intent and witness geometry, exact source bindings,
complete cells/entity coverage, separate outcomes and typed terminal proof.
Gateway retains original request/owner/source/destination/deadline and validates
strict terminal evidence before a delayed permit. Public semantic arrival requires
stable changed-world expected-dimension observations and unchanged protected
inventory with matching original native action/player/session/server/source proof.

## Tests and evidence limits

`JAVA_HOME=<official JDK21> ./run-policies.sh <new-output-dir>` runs real production
pure callback-poison, settlement, contact, reader and component-identity policies,
producer semantics, and emits 21 cross-language closed-intent cases.
`TypedItemArgumentNativeChecks` constructs real vanilla packet/hit/context arguments
without a world or server, invokes the production exact packet/context readers, and
mutates final fields through test-only reflection during the final-query callback.
It checks hand, sequence, hit object, face, position/location identity, inside/miss,
selected slot and context hit replacement, including an overriding nested reader
that must never execute. This is actual argument-object evidence, not native hook
or physics execution. `run-native-probes.sh <compiled-classes> <new-output>` runs
the bounded 256 MiB probe batch against separately compiled integration classes.
`check-argument-source.py` is an additional static seam placement check only.

`TypedPortalIntentChecks` executes production Java intent validators and
`ClientActionRequest.parse` against that generated file using the official named
classpath and compiled classes.

The owner's isolated source compile uses the complete official access-transformed
classpath. Because this disjoint source copy deliberately does not edit shared
ClientActions, its temporary compile copy contains four false-return owner-method
stubs. That proves Java compatibility only. The integration owner must compile and
validate the real shared owner and Mixin wiring before deployment.

`capability-runtime/tests/typed_portals` contains the real public owner chain:
ToolboxService → OwnerRuntimeBackend → Runtime → IntentClient → watchdog → queue →
Resident. Only the native HTTP endpoint is fabricated. Source-tree import guards
prevent accidentally mixing old and integrated watchdog modules. Overlay receipts
state exactly which real shared source and five typed Python modules were tested.
These tests do not execute Minecraft physics, actual Mixin sites, packets or the
integrated server, and do not constitute live gameplay or server proof.

## Explicit limits / remaining gates

- Natural stronghold End drops and credits are unsupported. Prepare a site or add
  a separately reviewed narrow entry contract; this is not universal End entry.
- Existing all-loaded entity exclusion is conservative: any unsupported loaded
  entity can deny admission even far from the corridor. In particular, Nether
  usability is not unconditional. A separate reviewed per-species/projectile
  corridor exclusion policy is needed before claiming broader usability.
- Any unknown class, component replacement, owner transition, elapsed deadline,
  ambiguous effect or unconfirmed release fails closed without replay.
- Actual integrated compilation, Mixin descriptor/coverage verification, offline
  shared suite, independent review, and the authorized controller's ordinary-world
  tests remain required before declaring the combined candidate ready for use.
