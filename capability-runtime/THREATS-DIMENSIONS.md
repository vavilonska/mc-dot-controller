# Threat, dimension, and End capabilities

These are opt-in functions over the caller-owned Runtime and existing IntentClient. They never launch a game/controller, discover credentials, connect servers, issue commands, or write around the watchdog. This delivery is source and offline validation, not an in-world gameplay acceptance claim.

## Threats

- `engage(runtime, target_uuid, timeout_ms=15000, approach=True, shield=True, min_health=10)` uses the existing real `combat_entity` action. `BoundedCombat` retains `CombatThreats`, health, collateral, movement, cooldown, and safety-retreat checks. Success needs a dead observed target or exact-target native death evidence followed by stable absence; a retreat is not victory.
- `strike(runtime, target_uuid, ranged=False, ...)` performs one real native attack or bow release. Later independent observations must show target health loss or explicit death. A target disappearing is not a living-target kill.
- `defeat(..., max_actions=8)` issues a new strike only after the preceding strike's exact terminal receipt and independent semantic success. The first unknown/failure stops the sequence. The budget is explicit and bounded.
- `recover_hazard(...)` reuses the watchdog's loaded collision-based `egress_plan` and the real native `recover_environment` action, with a finite timeout and observed dry-ground/frozen-tick goal. No found route means no movement.
- `retreat(...)` reuses the watchdog's dry two-cell retreat planner and verifies increased actual separation. It does not promise universal safety or potion blocking.

## Native single-target actions

`attack_entity` and `shoot_entity` bind target UUID, numeric entity ID, entity type, world generation, player UUID, and action session. Admission requires a focused, private integrated single-player world and the opt-in capability guard. Context, health, selected weapon, station, view ownership, hazards, collateral, projectiles, effect clouds, loaded trajectory, and action ownership are checked around callbacks. A dispatch is marked before calling vanilla and cannot be repeated after an exception.

- Melee: supported undead plus shulker; a selected sword/axe; exact picked target and <=3-block live reach; live attack cooldown. Dragon melee additionally requires explicit current phase 6 or 7 and an exact head-part ray. Flame phase 5, flying phases, and dragon ranged shots are refused.
- Bow: selected bow and ammunition; 20–40 ticks; actual owned use key during drawing; bounded 4–32-block ballistic path with terrain/entity checks. The trajectory is an approximate lower full-draw arc, so a native release alone never claims a hit.
- Crystal: bow only, >=12-block blast clearance, <=32-block range, no living collateral in the blast radius. Cages/terrain in the firing arc reject the shot.
- Bow interruption: local item use stops before releasing the owned use key. A release call that would fire after a safety cancellation is never used as cleanup. If server-use clearance is unknown, cleanup explicitly fails and the runtime remains blocked for reconciliation; it is not retried.

## Portals and End

- `ignite_nether_portal` verifies a complete existing 2–4 by 3–4 obsidian frame, selects the real flint-and-steel slot, ignites once, and checks the entire aperture's portal cells.
- `activate_end_portal` verifies all 12 inward-facing frames, selects actual eye slot, inserts only missing eyes within its budget, then observes all nine active portal cells. It does not invent a stronghold route or teleport the player. Frames must actually be in reach for each interaction.
- `enter_portal` crosses at most two blocks of observed, flat, dry, full-footprint supported approach into a specific active portal. The runtime allows only the expected destination, same player/action/gateway sessions, a known terminal action with confirmed release, and stable later living/safe observations. Unsupported natural drops, unobserved landings, and credits screens remain explicit gates.
- `open_crystal_cage` mines only explicitly selected observed iron bars within four blocks of the designated crystal, using actual mining and post-mining air checks. It does not claim a clear firing lane; the subsequent bow adapter checks that independently.
- `remove_crystal` fires once from a safe station, then needs complete entity snapshots, unchanged observer position, the original chunk still explicitly loaded, and stable target absence. Its claim is local removal, not attributed destruction or proof that every crystal in the world is gone.
- `discover_end_goals` reads actual nearby entities/loaded chunks and bounded terrain, selects concrete UUIDs, reports observed cage bars/phase/head/portal facts and blockers, and returns the current-station-ready local subset. `clear_observed_crystals` actually executes that discovered subset and stops at the first uncertain/failed action.
- `end_battle` executes caller-scoped crystal goals and optional observed local stations, waits only a bounded number of phase samples, and repeats real head strikes only after actual health loss. It completes only on explicit dragon death; optional exit-portal verification requires an actual portal block after the death animation.

## Deliberate limits

These primitives are complemented by `combat_goals.py` and `expedition.py`. The latter dynamically selects towers/cages/dragon/gateway/outer-End/shulker targets and proves the actual dragon-to-shulker-box chain; see `docs/END-EXPEDITION.md`. Species-specific Enderman shelter and blaze shield/Fire Resistance strategies are described in `docs/MOB-RESOURCE-GOALS.md`. Calm Endermen with verified pumpkin protection are distinguished from active threats.

Bounded loaded exploration does not guarantee a reachable fortress/city, arbitrary drops or an accessible target in every world. Flying-dragon interception, elytra flight, dragon respawn and unsupported portal landings remain outside scope. A missing living target, stale/partial scan, unknown receipt, expired budget, changed context, menu/focus change or uncertain input release is not success. Exact retained native death evidence is distinguished from mere disappearance.

## Focused validation

`python -m unittest discover -s capability-runtime/tests -p test_threats_dimensions.py -v`

The focused suite exercises semantic target outcomes, identity/truncation/health/phase gates, unknown no-replay, the production watchdog egress planner, exact portal selection and supported geometry, real hotbar-slot retention, loaded-chunk crystal removal evidence, discovery/selection and state-machine semantics. It also compiles and executes production pure Java targeting math. `CapabilityTargetActionTest` runs production native request validation and policy checks under the project's normal offline Java test build. No game is started by these tests.
