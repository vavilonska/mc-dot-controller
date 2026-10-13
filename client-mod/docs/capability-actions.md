# Additive private-singleplayer capability envelope

The historical nine client action kinds and their unguarded contracts remain.
Six new actions (`interact_block`, `use_item`, `select_hotbar`, `close_menu`,
`attack_entity`, `shoot_entity`) require the opt-in `capability_guard`. Existing
actions can explicitly opt in to the same envelope. No endpoint, authentication,
credential, persistent access or multiplayer permission is added.

## Binding

Supply the original state sample unchanged:

- `capability_guard`: `{schema_version:1, source_tick, source_nano}`. The nano value
  is a signed decimal string preserving JVM long precision. Admission requires at
  most 800 ms and five game ticks. Age is not reset or reapplied during execution.
- `expected_world_generation`, `expected_dimension`, `expected_player_uuid`,
  `expected_action_session` bind the original context.
- For non-menu actions, `expected_hotbar_slot` is the currently observed selection,
  `expected_held_item` is the full observed item object for the requested hotbar
  slot (or current slot). After admission's optional selection, only the intended
  selected slot is accepted on callbacks.
- Mining and interaction require `expected_block_id` and may bind
  `expected_block_properties`.
- Placement requires `expected_support_id`, `expected_support_properties`,
  `expected_target_id`, `expected_target_properties`, and desired
  `expected_block_id`. Optional desired `expected_block_properties` is verified
  through the existing five stable placed ticks and later Runtime observations.
- Menu clicks/close require `expected_menu_class`, `expected_menu_state_id`, exact
  container and carried stack. Clicks also require `expected_slot_item`; SWAP
  requires `expected_swap_item`. Native menu object identity is retained through
  admission to dispatch, so reopening another menu cannot reuse indices.

Item observations include stable process-local `item_fingerprint` and
`component_fingerprint` handles backed by at most 4096 retained native ItemStack
copies. Exact count and ItemStack.isSameItemSameComponents are compared at dispatch;
components are not approximated by JSON text or a lossy hash. Handles grant no
access and have no persistence or cross-process meaning. Evicted/missing handles
fail closed. `max_stack_size` and bounded `potion_effects` support capacity and
consumable preflight. The legacy itemSnapshot function stays byte-compatible.

## Lifecycle and interaction

Guarded actions require a focused, unpaused, living non-spectator player in an
unpublished integrated singleplayer world at admission and every action callback.
Normal tasks stop on newly observed damage or water/lava/powder-snow/fire;
dedicated recovery/combat actions retain their explicit native safety policies.
Admission additionally requires neutral held input. All guarded terminal receipts
are published after cleanup and include `input_release_confirmed`; failed cleanup
cannot yield success.

`interact_block` takes `target`, exact `face`, and optional selected `hotbar_slot`.
It re-picks the actual face after the mod click hook and uses ordinary useItemOn
exactly once. `interaction_dispatched` is deliberately not a semantic success.
The outer Runtime must verify a new exact menu or another explicit observed goal.

`use_item` requires `hotbar_slot` and bounded `use_ticks` (1–100). Only native EAT
or DRINK animations are supported. It calls ordinary useItem once, owns the use
hold through completion/budget, and releases input. The caller must verify actual
inventory and food/effect changes. It cannot throw pearls or release a bow.

`select_hotbar` uses ordinary inventory selected-slot state, with observed later
selection. `close_menu` uses ordinary closeContainer only with an empty cursor.
`attack_entity`/`shoot_entity` use the separate bounded target adapter; its
restrictions and dispatch evidence remain distinct from proof of damage/death.

Continuous mining and legacy bounded combat preserve selected item/component
identity while allowing ordinary tool durability loss. Mining still checks target
state and vanilla correct-tool eligibility when requested. No mid-hold item swap
is authorized by having dispatched an earlier attack.

## Observation additions

State has `focused`, `private_singleplayer`, `held_inputs` (keys/raw-key count/
world-button count/neutral), `capability_guard`, player `block_interaction_range`
and `mainhand`. Item entities expose their actual `item` stack. Dragon entities
expose `phase_id`, `phase_name`, and bounded ordinary multipart geometry.
`nearby.loaded_chunks` reports loaded status of the observed-radius chunk square;
queries do not load chunks. Entity radius supports at most 48 blocks.
Furnace menus expose normalized `is_lit`, `burn_progress`, `lit_progress`.

Resident `capability_observation:true` explicitly permits real Overworld/Nether/End
terrain stamps and adds original capture/tick/generation metadata. The historical
terrain parser and default output remain unchanged. Opt-in scan bounds are still
local radius 1–8, vertical 2–8, with existing page/time limits. Neither this schema
nor offline compilation proves real-game acceptance or server-confirmed results.
