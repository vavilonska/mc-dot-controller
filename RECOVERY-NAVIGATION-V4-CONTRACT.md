> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Recovery navigation v4 — bounded local move/look

Status: independent offline candidate. No deployment, game startup, formal respawn or navigation qualification is implied by this document. The frozen respawn UI pair and the 101 historical actions remain unchanged.

## Deliberate contract separation

`recovery_navigation_v4` is an explicit startup-selected navigation profile. It shares the existing authenticated `/control/recovery-interaction/v3/` transport path, not the v3 profile semantics. The new public consumer requires the v4 profile in every new observation/request/receipt. Historical v3 status and exact stop retain their stored original profile; older roots/readers remain unchanged. A caller cannot relabel an old record, replay an UNKNOWN action, change owner, or start a fresh empty journal to gain navigation authority.

Only `move` and `look` are admitted by v4. Native and public validation reject mining, hotbar selection, placement, attacks and inventory operations. Navigation PLAN version 2 has an explicit navigation kind and no excavation targets. This removes the earlier coupling between a movement floor height and a mining target; it does not invent a harmless-looking block target to pass the old policy.

## Bounded data PLAN

The local, regular, hash-pinned PLAN binds the current native session, world generation, player UUID and original owner. It contains at most 16 explicitly named stages. Each stage supplies a finite source corridor, fractional foot-height bounds, a target foot position, exact view/input direction, and finite action budgets. Fractional heights such as bed top 55.5625 and chest top 55.875 are represented as finite numbers rather than rounded to integer feet. A stage identifier and the original PLAN version/hash are bound into each new request, canonical digest, persisted record and receipt.

Each move has 1–8 input samples and the existing absolute action TTL; a jump stage allows one deliberate move attempt. Ordinary stages have bounded move and look counts. These bounds are authorization limits, not a promise that all listed stages will execute. Stop on UNKNOWN, uncertain transport/effects, invalid context or unmet local policy. A known finite attempt that collides, fails to reach its target, or takes ordinary gameplay damage is not thereby a protocol UNKNOWN and must not be silently repeated.

## Current local geometry, not global risk elimination

V4 adds only bounded actual collision AABBs to the existing 150-cell local observation and reads the actual player AABB and step height. Each cell has at most 16 local AABBs and the window at most 512; all coordinates are finite and bounded. Empty shapes, unloaded cells, read failure and budget overflow remain distinct. Partial/truncated geometry never becomes a complete movement proof. The existing 64 KiB response bound is retained; an over-budget observation does not grant a ticket.

The public policy uses the current body, local supporting surfaces, target landing footprint, nearby immediate-overlap facts, fluids and bounded local fall distance. It rejects a body already intersecting solid geometry and a target without the required observed landing support. The grounded current foot needs an actual top contact, with support no more than one block below the remaining footprint; it need not be entirely covered at one height while straddling a normal seam. The destination landing footprint must have the required complete support. Missing local coverage is a refusal, not an assumption. Source corridors and surfaces come from the PLAN and fresh observations, not hard-coded bed coordinates in the JAR. Ordinary automatic steps are limited by the observed native step height and the small local height change. A jump's destination differs by at most one block in foot height. The route also requires the newly observed sprinting flag to be false; the observer does not change sprint state or promise that future state cannot change.

This does not certify an ideal unobstructed ballistic arc or immunity to future entities/terrain changes. In particular, the real east chest has a low ceiling: a vanilla ceiling collision is possible and must be observed in TEST. The executor may complete a finite input attempt while the gameplay target remains unmet. Neither callback return nor released keys proves a landing or zero velocity; local physical settlement is checked separately before the next decision.

## Unchanged execution integrity

The existing native executor supplies a jump impulse only on the first applied input sample. V4 does not write velocity, teleport, send invented gameplay packets, enlarge the 8-sample movement budget, reset action deadlines, or add another owner. It preserves the original durable dispatch fence, input release, queued-input invalidation, exact stop, single in-flight entry, global UNKNOWN lock and history count/byte reserves. The v3 1000 ms / 20-tick observation-reference lease is reused without extending the original absolute action TTL.

The normal respawn GUI capability remains the already reviewed one-shot native button action. Its v4 startup compatibility must preserve dead-player/DeathScreen/idle-ledger checks, one-shot consumption and pending/unknown UI blocking. A new alive player must be observed before any navigation PLAN is bound.

## Current task and qualification boundary

The only present route candidate is the actual restored bed area to the east doorway. The reviewed cold geometry suggests floor → bed head → bed foot → east down to floor at (-164.5,55,9.5) → south to floor at (-164.5,55,10.5), followed by one bounded eastward jump onto the chest at foot height 55.875 and ordinary stepping onto sandstone at 56. This avoids the crafting table and its one-cell gap. Maintaining the original north-facing view and using forward/backward/strafe may avoid any look action on this route; strafe-only jump uses the same existing first-sample jump primitive. This is a candidate, not a completed route. No excavation or placement is allowed; the covered TNT at y53 must not be exposed or touched.

First test the complete route in a separate copy of the already respawned TEST world, preserving the formal death save and the 101 original records. Verify finite input/known release and fresh physical outcomes at each stage, especially the low-ceiling chest jump. Formal respawn plus the prebuilt route requires parent admission after TEST; do not revive the formal character and leave it waiting while engineering is done.

Prepare scripts and data while cold. During unpaused play, use short-interval current health/position/local-threat observations before the next action. A quiet local frame is not a promise of future safety. Further engineering belongs behind an authorized normal maintenance save/exit boundary, not minutes of unattended gameplay.
