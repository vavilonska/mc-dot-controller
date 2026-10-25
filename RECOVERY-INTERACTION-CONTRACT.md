> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Bounded recovery interaction — offline candidate contract

New explicit profile `recovery_interaction_v1`, independent recovery TEST version `1.1.8-recovery-interact-test.1-from-input1`. This contract describes the offline implementation; it is not installation, loader or gameplay qualification. The previous input1 source/JAR and 57 known originals remain preserved.

## Small capability set

- `move`: existing finite movement authority, at most 8 native input samples; no increased movement budget.
- `look`: one finite absolute yaw/pitch update, bounded angular delta; no old-angle restoration during cleanup.
- `select_hotbar`: one selection in existing hotbar 0..8 with observed stack binding; no inventory transfer, item creation or direct packet fabrication. Current task needs slot 2, not the diamond pickaxe in main inventory.
- `break_block`: one exact visible block position/face/state and observed tool, at most 32 native start/continue calls with the original deadline no longer than 2000 ms. No batch mining. This prototype only supports the two exact dry cobblestone targets (-636,60,33) and (-636,61,34), above the player's foot layer, never the current support column. Both native and public layers enforce that task-specific pair; this is not a generic mining catalogue. Movement, view, selection and break are separate original IDs with observable results.

No placement, entity attack, use-item, generic inventory interaction, block-state write, creative authority, teleport, velocity manipulation or combat subsystem is added. Legacy guard semantics are not widened.

## Two-layer meaning

The execution layer proves bounded dispatch and control ownership, not harmless gameplay. It retains the single session/world/player/owner/generation/action identity, single in-flight action, immutable kind-specific payload digest, durable pre-effect fence, queue revocation, exact stop, original monotonic deadline and persistent UNKNOWN lock.

A finite mining attempt may end without breaking the block. Normal damage, slowed mining, predicted block removal, tool durability change, item drops or later server application of already-requested vanilla work are gameplay outcomes, not automatically protocol UNKNOWN. Known terminal means no new calls may be scheduled by this action, an already-entered synchronous call has returned, and exact local mining state/input is released. It does not retract packets, reverse world changes, guarantee server quiescence or restore old view/slot.

Stop invalidates new calls immediately; already-entered vanilla calls may unwind normally. In particular a STOP packet that follows an already-requested local predictive destruction must not be swallowed merely because cancellation arrived. Throwing callbacks, uncertain dispatch, wrong cleanup owner or unverified local release remain UNKNOWN. A stuck game thread cannot be called physically released by a watchdog; deadline bounds future call admission, not an arbitrary synchronous mod callback's execution time.

Mining must account for vanilla's `continueAttack(false)` automatic abort. Any routing applies only to the exact captured mining owner and disappears after its cleanup; unrelated or replacement owners retain vanilla behavior. The generic `Minecraft.startAttack` entity branch is not used.

## Same journal, no history washing

A versioned journal at the existing native ledger path may add typed operations, but must read the original format and preserve all 57 legacy requests, digests and known terminal fields. All profiles share action-ID collision detection, generation and UNKNOWN/in-flight authority. Legacy status/exact stop remains routed by the stored original profile; old start cannot become a hidden fallback. Existing unfinished/UNKNOWN data blocks the new profile. No new empty ledger, owner, endpoint, file deletion or profile change can clear uncertainty. Old and new record replay is prohibited. Downgrade after a new journal format is not a reset procedure.

The new standalone public controller uses the original private owner/ledger directory and endpoint, validates legacy records through the legacy closed schema, preserves their contents and raw evidence, and adds only explicit new requests. Original native 256 / public 128 history caps and existing transport byte limits stay unchanged.

## Local strategy, not global proof

The new observation minimally adds actual player box, target/selection facts and the additional top terrain slice needed by the one-step jump policy: x/z offsets -2..2, y offsets -2..3 (150 cells). Old 125-cell readers stay unchanged. The original 64 KiB response limit is not raised. Known source time/pose/world bindings remain fresh; static cold geometry selects targets but cannot authorize a live effect.

The current two-target plan is documented in `RECOVERY-INTERACTION-ROUTE.md`. It is not permission to dig a downward shaft or remove any y<=59 support in this scene. Every target is separately aimed, observed, attempted, stopped and inspected. The ordinary +1 jump requires its own complete independent TEST qualification, including whole-player-box source placement and fresh headroom/landing observations; it does not inherit qualification merely because native jump input existed in input1.

## Acceptance gates

Offline: exact legacy57 roundtrip/owner/generation, injected legacy UNKNOWN, payload-kind collisions, duplicate/lost receipts, cancel and expiry at effect seams, same-owner cleanup, replacement-owner isolation, ordinary failed mining as known, and actual production wire through the strict public consumer. Exact original journals are copied into isolated fixtures; tests never mutate live or frozen originals.

Independent TEST: load/readiness; bounded look; hotbar2 selection; each of the two cobblestone targets independently mined/stopped/read back; at least one demonstrably ACTIVE mining cancellation with exact release (other expiry/owner/transport seam cases may remain offline tests, not an endless demand for live fault permutations); whole-box staging and one +1 jump; observed landing and short local platform step. Preserve all original IDs and journals. Only after independent review and this full TEST may the parent admit the narrowly scoped changes to formal RECOVERY. No combat or further route expansion is implied.
