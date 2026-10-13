# Reach, inventory and resource capabilities

These source modules are reusable opt-in capability functions. They require the
shared Runtime and its existing caller-supplied IntentClient; they never discover
queues, start processes, obtain credentials, launch a game or connect to a server.

## Public functions

- `reach.navigate(runtime, goal, max_steps=128)`: integer feet-cell goal, one local
  loaded-terrain A* route. Uses the existing planner and full-cube geometry policy.
  Normal dry Overworld floor IDs plus explicit dry full-cube obsidian/end-stone/
  netherrack/blackstone/basalt variants are accepted by the opt-in adapter. Actual
  dimension identity is preserved. Unknown/unloaded terrain, arbitrary ascent,
  unsafe floor, fluid, and unsupported jumps fail before input. Native follow_path
  and later settled grounded position evidence are both required.
- `reach.interact(runtime, target, face="up", expected_block_id=None,
  expected_menu_class=None, verify=None, hotbar_slot=None)`: one native ordinary
  block use. Requires a semantic menu or caller verifier. Dispatch receipt alone
  cannot succeed. Real renderer pick, range and exact face remain native checks.
- `reach.close_menu(runtime)`: exact menu identity/revision and empty cursor, one
  ordinary closeContainer, later closed player-menu evidence.
- `inventory.select_hotbar(runtime, slot)`: guarded normal hotbar selection with
  later selected-slot and exact stack observation.
- `inventory.ensure_hotbar(runtime, item_id, hotbar_slot=0)`: locate an observed
  item, use observed menu-index/player-inventory-index mapping and vanilla SWAP,
  verify both sides and select. Menu must be closed before this multi-step work.
- `inventory.equip(runtime, item_id, slot=...)`: head/chest/legs/feet/offhand;
  native equipment slot acceptance still decides valid equipment. Every swap is
  exact-bound and separately verified. Closed InventoryMenu is required.
- `inventory.consume(runtime, item_id, effect_id=None, max_use_ticks=40)`:
  explicit ordinary food set, observed timed-effect potion, or milk clearing
  observed effects. Uses one native EAT/DRINK initiation with bounded owned hold.
  Requires inventory consumption plus food increase, matching effect increase and
  bottle return, or effect removal and bucket return. Unsupported instant-effect
  potion goals do not pretend to verify. A use dispatch never proves consumption.
- `resources.find(runtime, block_ids, limit=32)`: loaded local terrain matches,
  with explicit coverage and result truncation.
- `resources.mine(runtime, target, expected_item_id=None, hotbar_slot=None,
  require_drops=False)`: one real mining hold bound to the observed exact block
  properties and held tool. It refuses the player's floor/overhead column and
  immediately observed falling/fluid-above risks. It verifies block absence, not
  collection. `expected_item_id` here constrains the original block registry ID.
  `require_drops=True` asks vanilla hasCorrectToolForDrops before/through mining.
- `resources.collect(runtime, item_id, minimum=1, max_targets=8, max_steps=64)`:
  uses observed item-entity stacks and the same safe loaded A* to approach. Each
  entity receives at most one movement. Bounded later reads cover pickup delay;
  two later increasing ticks must preserve the inventory increase. It never
  treats entity disappearance as pickup or attributes causality to one entity.
- `resources.mine_and_collect(...)`: retains the owned immutable pre-mining
  observation as inventory baseline, then composes mining and independently
  verified pickup. There is no public caller-invented numeric inventory baseline.

## Evidence and limitations

Every mutation is durable-ID journaled by Runtime, submitted only once, checked
against an exact terminal native receipt, and verified with independent later
observations. Unknown outcomes block subsequent mutation until reconciliation;
no module retries gameplay input. Success is client-observed, never a server ack.

The native guard and actual vanilla calls compile against the restored real
Minecraft/NeoForge build dependencies. Python fake-runtime tests verify policy,
command wiring and semantic predicates only. They do not prove ordinary game
physics, mod-hook behavior, UI synchronization, pickup timing, resource yields,
consumption effects, latency feasibility, or real survival. Live acceptance remains
separate and must use the explicitly authorized singleplayer environment/cases.

The 800 ms acquisition and five-tick native admission budgets remain strict.
Default local scans are deliberately small; large scans can fail freshness or
bounded-page budgets. No stale observation is relabeled as fresh to succeed.
