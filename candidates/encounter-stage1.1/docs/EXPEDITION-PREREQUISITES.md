# Expedition prerequisites candidate 1

Version: `1.1.7-expedition-prereq.1`. Based on the isolated `.5` source and verified source archive SHA-256 `4576f26d08f742d7fb0ad05d8b3b5a51b9664f2a6dae075ac3bd248a68813244`.

This is an offline candidate, not an expedition-ready release. Nothing was installed, deployed, pushed, sent to a game, or added to backup sources. It must be merged and regression-tested with the independent boat and detour candidates before any live acceptance. The baseline historical documents remain historical, not current acceptance claims.

## Implemented and executable

### 1. Native walking-position discontinuity guard

`PositionDiscontinuityGuard` is a pure tested policy; `NavigationPositionGuard` adapts loaded Minecraft observations; `ClientActions` binds each spatial action to its starting epoch.

- The adapter observes every pre-tick including idle periods, and again at action admission, action context/input checks and state snapshots. A queued old path cannot escape merely by waiting until the previous action ended.
- With the same player/level identity, displacement of at least 16 blocks and velocity residual of at least 8 blocks invalidates the epoch. Ordinary motion, jumping and ordinary knockback are below that threshold. A large velocity-consistent fall is not labeled a teleport. The values are conservative candidate thresholds, not a universal classifier.
- A player/level replacement or invalid position also invalidates the prior binding. Existing logout/clone/level/death/GUI/deadline guards remain.
- Active `follow_path`, `break_block`, `place_block` and `combat_entity` with a changed epoch are cancelled through the existing terminal cleanup, which releases their movement, mining, sprint and combat-owned inputs. No position or velocity is written. `boat_drive` is intentionally outside the walking-action applicability switch; it has its own occupancy/water/steering lifecycle.
- Once invalidated, every subsequent spatial action in the session must supply `expected_navigation_epoch` and `expected_origin` (x/y/z), with origin within 0.25 blocks of the current position. The requirement persists after a successful bind, so a later unbound stale queue item is still rejected.
- Rebinding requires three distinct sampled client ticks with finite position/velocity, current collision support, on-ground, loaded footprint, no mount and speed <=0.15 blocks/tick. Repeated GETs in the same tick cannot manufacture readiness. Collision-read failure fails closed.
- `world.navigation_guard` exposes schema, epoch, `fresh_binding_required`, `rebind_ready`, stable-tick count and reason. The terminal action carries its guard snapshot when cancelled for the changed epoch.

After a cancellation: observe anew, wait for `rebind_ready`, discard every old waypoint/cursor, plan from the newly observed terrain, and submit the exact epoch and origin with the fresh route. The existing generic resident `action` forwarding preserves these fields. Automatic `walk_to`/navigation-cursor rebinding is intentionally not added: they fail closed until a fresh planner/adapter is implemented; do not patch the epoch onto cached paths.

Known limits: movements/teleports smaller than 16 blocks can escape this heuristic. There is no authoritative server-teleport sequence hook. A large unusual server correction or heavily modified knockback can conservatively cancel a route. A previously unseen initial position cannot be compared with historical unobserved positions. The guard does not make an End gateway, void crossing, path, landing or bridge safe. It does not preemptively stop the path before entering a gateway: an eventual gateway action must first cancel the old path and confirm release. Physical keyboard takeover is not claimed; existing API direct takeover is retained.

### 2. Strict single-pearl protocol, offline only

`gameplay-helpers/expedition_prerequisites.py` implements immutable identity/intent, one-owner one-flight registry, exact held item/slot/count, finite origin/aim/destination, 32-block short-crossing cap, bounded 0.5–10 second total budget, cooldown/stationary/support/loading checks, short-lived trajectory proof binding, consume-before-dispatch semantics and result-uncertainty tombstones. Same IDs return the old state; changed payloads fail; uncertain outcomes or unconfirmed release block a fresh ID. Registry capacity is 1024 retained records, with refusal instead of tombstone eviction.

`DISPATCH_ONCE` is only a pure reducer proposal. There is **no** `use_item_once` action, HTTP endpoint, QueueClient call, native item-use adapter, launch command, externally accepted proof flag, or production trajectory proof issuer. The default verifier always refuses with `native_trajectory_verifier_not_implemented`. A test-only synthetic issuer exercises the protocol; this is not trajectory or game-physics acceptance.

Observed landing additionally requires the same session/player/world/owner, a later navigation epoch, exact one-item count decrease, the bounded target region and supported/loaded/slow grounded observations. The result remains client-observed, never server-confirmed. A lost result, timeout, GUI, owner change, death or disconnect leaves a terminal uncertain/cancelled result and a release requirement; it cannot authorize replay.

Before exposing a real pearl action: implement a native verifier for vanilla launch scatter, initial eye/velocity, entity/block swept collisions, all loaded chunks, impact/gateway semantics, possible landing region and safe support; bind it to the exact same client-tick observation and a single ordinary `useItem` dispatch. Retain native click/mod hooks, fixed hand/stack identity, no offhand fallback, no held-use repeat, a bounded observation period and all terminal cleanup. A few sampled rays, a user `verified:true`, or a guessed destination are insufficient. Gateway exit motion and actual player landing must be observed afresh. No blind pearls or island-to-island flight are enabled.

### 3. Shulker recipe, bounded telemetry and offline lifecycle

- The existing crafting helper supports the vanilla 1.21.1 three-high `shell/chest/shell` shaped recipe, requiring the 3x3 crafting menu, two actual shells and one actual chest. Its existing observed-slot click protocol, exact inventory deltas and no-replay behavior are reused. The fixture independently checks the recipe, output and 2x2 rejection. A chest is an input; automatic chest acquisition is not added.
- `BoundedContainerSnapshot` adds at most four shulker content summaries per snapshot, each capped at 27 slots and one level. `custom_name` is plain text capped at 128 UTF-16 units. There is no arbitrary NBT serialization or recursion. Additional boxes/oversized contents explicitly set `slots_truncated`; the entire identity is incomplete.
- Only represented basic identities qualify as exact. Unknown or removed component patches (including removed DAMAGE), component-bearing cargo and styled/renamed stacks are marked `identity_complete:false`; plain names are informational, not an exact component fingerprint. The pure `shulker_contents` decoder validates native sparse summaries and expands them to exactly 27 slots only when completeness, bounds and uniqueness checks pass. A contained shulker is incomplete. No data is silently treated as a matching enchanted/named/custom item.
- `ShulkerCycle` executes a no-I/O state machine: place → open verified 27-slot ShulkerBoxMenu → transfer with exact basic-cargo/player-inventory conservation → close with empty cursor → break observed → unique complete recovered box → replace → reopen and compare all cargo. Every step has a fixed identity/owner, unique action ID, pending-result barrier and total 1–60 second budget. Load and unload fixture paths execute; break is not treated as pickup.
- No live place/open/click/break/pickup adapter is provided. `fresh`, block/menu binding and unique recovered-box count are evidence fields an eventual adapter must derive from actual observations, not trusted arbitrary user flags. The reducer does not provide atomic multi-click exclusion or prove item provenance. It ends after content inspection with the box placed/open; final closing/recovery needs another explicitly designed cycle. No automatic equipment or named/enchanted cargo handling is claimed.

## Shared-file ownership and integration

Minimal common edits relative to `.5`:

- `ClientActions.java`: runtime `navigationEpoch`; admission guard; context epoch cancellation; idle pre-tick sampling. No boat field or switch edits, no item-use dispatch.
- `BridgeServer.java`: `world.navigation_guard`; independent bounded item component helper; reset helper budgets at menu/screen snapshot entry. No vehicle observation edits.
- `gradle.properties`: unique candidate version. Parent chooses the final integrated version.
- `ClientActionRequest.java`, combat type whitelist, all recovery policy and access transformers remain unchanged.

New native classes are independent of Boat*; the parent must rerun the merged suite, inspect the input/context hook order, and apply the walking guard only to its explicit action list. Source-contract tests verify wiring, not an actual Minecraft event loop.

## Next specialized encounter state machines and required interfaces

These are concrete designs, **not implemented combat controllers**. They must remain outside the generic melee allow-list until their own native adapters, fixtures and live trials pass. All inherit sticky UUID/entity ID/session/world, protected-bystander ray checks, single input owner, finite action budget, no unknown replay, GUI/death/disconnect/direct-API cancellation and cleanup.

### Blaze

States: `survey_cover` → `verify_fireball_lane` → `wait_charge_behind_cover` → `bounded_exposure` → `attack_window` → `return_verified_cover` → `observe_drop` / terminal retreat.

Needed observations: actual Blaze charged flag and target pose/velocity; nearby small-fireball IDs/positions/velocity with bounded truncation indicators; fire/resistance duration and health; loaded cover geometry and a previously checked retreat corridor; current weapon/shield/cooldown. A future ranged primitive must own one draw/release and a verified ray/swept projectile path. Close melee is admitted only from fresh reach/ray observations in the attack window, not as general pursuit of a flying target. Multi-blaze/unknown projectile observations abort exposure. A blaze rod is counted only by inventory/drop observation, never by presumed kill loot. Finding a fortress or using a friend's gold is not part of this candidate.

### Shulker

States: `survey_supported_cover` → `identify_attached_target` → `wait_open_shell_or_deflect_bullet` → `bounded_attack_window` → `reobserve_teleport` → `supported_recovery` → `observe_shell_drop`.

Needed observations: Shulker raw peek/open amount and attachment face; sticky target UUID after relocation; nearby shulker-bullet IDs, pose/velocity and targeting when accessible; levitation amplifier/remaining ticks; support/loading above and beneath the player, ceiling/cover and safe height. The 20-tick generic combat recovery is not reused for a 200-tick levitation episode. Recovery needs a separate finite encounter budget, neutral input/no edge approach, interruption support and repeated effect/support checks. Milk is not an automatic response: it clears slow falling too and is unsafe as a generic high-altitude fix. Shell pickup count is verified; two kills do not imply two shells.

### Ender Dragon

States: `arena_ready` → `survey_crystals_and_exit` → `plan_crystal_window` → `bounded_crystal_action` → `avoid_breath_or_charge` → `wait_perch` → `verify_head_hitbox` → `bounded_perch_attack` → `recover_supported_ground` → `verify_dragon_death_and_exit`.

Needed observations: dragon phase manager/phase ID, multipart head/body hitboxes and IDs, end-crystal positions/cage/support geometry, dragon fireballs and area-effect breath clouds, perch state, knockback/health/effects, loaded terrain and egress zone. A dragon body UUID and generic nearest-entity ray are not sufficient for a valid head attack. No unverified tower climbing, crystal explosions, bed explosions, elytra use or void retreat is permitted. Plan the arena and each window with bounded resources; retreat or terminate when prerequisites vanish. Dragon-death and gateway creation must be observed, not inferred from a disappeared entity.

For eyes: pearls plus blaze powder is a separate verified crafting step. Piglin barter and low-roof Enderman gathering need their own entity/interaction/trade/neutral-aggression policies and observed resource accounting. This candidate spends no gold, barters with nobody, travels nowhere and does not add blaze/enderman/shulker/dragon to generic native combat.

## Evidence and sources

Local official 1.21.1 resources were read from the already cached `neoforge-21.1.255-client-extra-aka-minecraft-resources.jar`; its `data/minecraft/recipe/shulker_box.json` is the independent recipe source. Mapped NeoForge 21.1.255 bytecode was inspected for `EndGatewayBlock.getPortalDestination`, `ThrownEnderpearl`, `EnderpearlItem`, `ItemContainerContents`, `EnderDragon`, `Shulker` and `Blaze`. `EndGatewayBlock` passes the same `ServerLevel` to `DimensionTransition`; this is why dimension identity is not enough. Inspection output is in the candidate evidence. This does not establish unknown server plugin/mod behavior.

Final counts, hashes and independent review status are recorded in the delivery manifest. Actual game/IPC/UI integration tests for this candidate: zero. All offline fake clients and locations are synthetic. Live testing is deferred until the authorized local dragon test is complete and a separately authorized isolated acceptance world is ready.
