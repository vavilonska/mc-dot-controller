# Explicit hand and cursor recovery

This additive candidate provides two public version-1 capabilities. It is an offline candidate, not an installed or live-accepted release.

- `clear_hand`: `hand` is `mainhand`, `offhand`, or `both` (default). It requires a closed, exact vanilla InventoryMenu and an empty cursor. A held stack is picked up with an ordinary vanilla left-click and merged/stored in observed player inventory slots. Clearing the offhand is the supported unequip route; armor unequip is outside this batch.
- `recover_cursor`: requires the observed `container_id`, `menu_state_id`, `menu_instance`, `screen_instance`, and `cursor_fingerprint`. The instance references come from `state.menu.recovery_context`; the fingerprint comes from `state.menu.carried.item_fingerprint`. Only the exact current cursor is stored, and the menu stays open.

Supported recovery menus are exact vanilla InventoryMenu (closed), ChestMenu, HopperMenu, DispenserMenu, and ShulkerBoxMenu. Production and modded menus are deliberately unavailable. The destination is always player storage 0–35; crafting, production, armor, external-container and outside/drop targets are never chosen.

Both routes scan all 36 storage slots, merge compatible stacks before empty slots, preserve exact components, and preflight capacity for the complete transaction before the first pickup. Clearing both hands excludes the selected main-hand slot from all destinations. Every step binds the player/world/action session, scoped owner/job/generation, exact menu revision and sync ID, menu and screen instance, selected slot, all 41 inventory stacks, complete menu topology, and cursor. The native guard uses ordinary `handleInventoryMouseClick` with PICKUP/button 0, never direct inventory writes.

A single original job budget covers all clicks and verification reads, including reserved cleanup. Each native terminal/release receipt is independently validated, followed by two increasing-tick observations proving the intended slot/cursor delta and conservation. This is client-observed evidence, not server finality.

Cancellation may leave a partial cursor. No rollback, drop, automatic cleanup placement, or replay is attempted. Recovery is a separate explicit request after the original action and owner release are known. Unknown originals block new recovery and require exact-identity reconciliation. A missing effect under lag does not authorize replay.

`mdc_catalog` exposes prerequisites, native requirements, stable blocked-reason codes, and a nonautomatic ordinary-inventory fallback. Both capabilities require native `inventory-recovery/1` support (`inventory_recovery_schema_version: 1` in scoped capabilities); old JARs cannot advertise them. The ordinary state schema and existing select/equip/craft/smelt routes remain compatible. The menu `recovery_context` is additive, and only the new capabilities require it.

Typical blockers include missing/full inventory coverage, insufficient aggregate capacity, changed window/cursor, and insufficient original action/observation budgets. When blocked, stop and inspect the returned reason; a new manual interaction requires its own authorization. Never use a fallback to reinterpret or replay an unknown original.

## Verification scope

Offline tests cover capacity and multi-stack merging, exact effects/conservation, changed cursor/window, malformed or missing bindings, cancellation, lag, failure, lost receipts, unconfirmed release, ownership/deduplication, Node-to-Python front-door routing, native request parsing/HTTP serialization and strict Resident witness consumption. Native facts in these tests are synthetic. Ordinary-world acceptance, transformed hook behavior, deployment, and saved-world effects remain NOT RUN.

## Outside this bounded batch

Armor unequip; recovery from production or modded menus; bed, torch and portal feature expansion; automatic inventory fallback; and broader crafting/smelting redesign are not included.

Native dispatch additionally uses a one-click/one-send call-stack token. Required
Mixin seams recheck immediately before vanilla `AbstractContainerMenu.clicked` and
before the final `Connection.send`; unavailable seams suppress feature advertisement.
The packet fence checks the exact expected local post-click inventory/cursor delta
and the complete outgoing click packet. Reentrant callbacks, replacement owners,
missing/extra packets, late window changes, and exceptions remain unknown. The
original callback never finishes a replacement owner. These fences cannot roll back
arbitrary third-party mod callback side effects, so late failures never claim no effect.
