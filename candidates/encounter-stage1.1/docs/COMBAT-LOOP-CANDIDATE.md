# MDC 1.1.7-combat-loop.5 experimental candidate

This revision adds bounded ranged pursuit and exact swept-square corridor checks to the verified .4 source. See [the .5 policy and evidence](PURSUIT-CORRIDOR.md) and [required live checklist](../acceptance/LOOP5-LIVE-CHECKLIST.md). It has not been deployed or live tested.

## Retained .4 candidate record

# MDC 1.1.7-combat-loop.4 experimental candidate

This is an isolated candidate, not a live-accepted release. The source baseline is the recovered 1.1.6-loaded-scan.1 client, deployed v5.1 watchdog and terrain-refresh.1 Python changes. It is not a wholesale replacement of public main/v6. Integrate the patch against the current branch; do not overwrite newer unrelated work.

This revision adds bounded native airborne recovery to the preceding `combat-loop.3` candidate. See [the recovery policy, evidence limits and required live tests](AIRBORNE-RECOVERY.md). No deployment or live acceptance is implied.

## Implemented and checked offline

- Resident terminal reconciliation keeps the exact action ID, action session, kind and launch-world terminal returned by cancellation. It separately reports the original error, incomplete task/postcondition, and known action outcome. A later failed recipe step cannot borrow an earlier success. No uncertain, cancelled or timed-out action is replayed
- Caller-declared world/session guards are preserved and checked before queue dispatch. New client actions also verify world/session on the game thread before taking inputs
- The legacy Python aim/combat loop uses one fresh state read per due combat iteration instead of two. It makes the combat decision against the currently observed ray, then aims for the next tick, avoiding reuse of the pre-look ray as a post-look result
- New Java observation fields expose real attack strength/speed, entity reach, using-item/blocking/use ticks, shield cooldown and target hurt/use/main-hand facts. The Python fallback uses observed cooldown when this exact schema is present; older clients retain clearly labelled fixed timing
- A narrow explicit recovery_close_menu intent closes the GUI deadlock after an observation-delay recovery. It requires confirmed release, fresh matching world/player/action-session, a live player, an observed open screen and no action/combat/held input. It dispatches one Escape click. It does not admit movement, arbitrary keys, attacks, stale commands, STOP, death or manual/uncertain hard pauses
- A new explicit ClientActions combat_entity runs on the client game tick, not on repeated model/tool turns. It is bounded to 50–30,000 ms, one exact entity UUID/id/type and one world/player/session. Existing timeout/death/menu/world-change/direct-takeover paths release movement and owned shield use
- This native action supports zombie/husk/zombie-villager, skeleton/stray/bogged and a non-attacking creeper retreat. It checks the current renderer ray, eye-to-hit reach capped by real reach and 3 blocks, actual attack strength, item-use release and sticky target identity. It observes actual blocking rather than claiming that use-key-down already blocks
- Sword sweep near a protected living bystander selects a present axe or stops. Players, pets, neutral species, witches and bosses are not automatically admitted by this experimental action
- Native approach/retreat checks a small swept, supported, dry corridor from loaded cells every game tick. It does not relax the old 0.25 s external terrain-cache threshold or treat unknown terrain as safe. Creepers are only moved away from until observed separation exceeds 8 blocks; that does not claim blast immunity or a defused fuse
- Action evidence records dispatches, observed health loss/death, shield-blocking ticks and phase tick counts. Dispatches and health changes are not exclusive server hit/kill attribution
- Airborne native combat pauses movement and attacks for a fixed recovery episode, preserving shield policy and the original deadline. It requires two settled grounded samples and a fresh full live corridor before resuming; unsafe/unsupported landings still stop

## Movement correction from the real baseline

A baseline natural-terrain jump route returned path_reached while still airborne, then drifted about 0.53 blocks beyond the final target. This candidate now requires final-target vertical agreement, on-ground status, horizontal speed at most 0.03 blocks/tick and two consecutive settled ticks before success. It does not write velocity/position or teleport. Intermediate waypoints still flow continuously, so the settlement is at the final endpoint rather than every block.

An explicit waypoint jump is consumed once for that waypoint instead of being repeatedly requested on every landing. Ordinary obstacle/rise jump decisions remain distinct. Optional sprint:true on follow_path holds the normal sprint key; the client retains its real food, item-use and collision eligibility. Sprint transitions are compatible with both vanilla hold and toggle options: an already-on key is not pressed repeatedly, and a toggle is explicitly switched off when ordinary key-up is ignored. No user setting is changed. Sprint is released on slowdown and terminal/cancel paths, and state exposes the actual sprinting flag. This is an input request, not a claim that sprint activated.

Cleanup is attempted before the action terminal is registered. Any thrown release failure becomes failed/input_release_unconfirmed, retaining the originally requested terminal for diagnosis; it cannot remain path_reached. The superseded combat-loop.2 build must not be installed.

## Important limitations

combat_entity is an explicit experimental action. The watchdog's combat_start is not silently rerouted to it before real-world acceptance. That existing Python path still uses cross-call input holds; this release does not claim those were converted to native leases. Use the new bounded action for the candidate tests.

Native combat approach is currently flat/dry and short-range, and stops on steps, gaps, water, unknown cells or persistent lack of closing progress. It is not yet a normal-player all-terrain combat/navigation system. Ordinary follow_path already remains available for bounded movement and jump testing. Multi-enemy tactics, neutral hostility attribution, underwater combat, witches, bosses and the Ender Dragon have not been implemented or tested here.

The first baseline sampler deliberately uses the old stationary combat_start with approach:false. Its 20 s timer requests combat_stop through the queue; it is not a hard Java input lease. A blocked resident can delay that stop. The candidate sampler instead uses combat_entity's actual Java-side deadline. Their results must not be mixed.

No real gameplay success, iron/diamond win rate, damage reduction, normal-survival fluency or Ender Dragon capability is claimed by the offline results.

## Local acceptance plan

Use a new ordinary-generation local survival world with cheats enabled, normal difficulty and a recorded seed, never Superflat or the friend's server. The requested first equipment groups are unenchanted full iron with iron sword/shield and full diamond with diamond sword/shield. Record any variation in armor, weapons, effects, food, difficulty, mob gear or terrain.

1. Establish world/profile/control isolation and rollback. Verify native deadline, STOP/direct takeover, GUI interruption, death/world change and release before combat performance claims
2. Record ordinary bounded movement/run-jump/step/water-edge and GUI/material-interaction baselines. Do not use cross-tool down/wait/up holds
3. On the same naturally generated dry patch, repeat single adult zombie tests for both equipment sets; then skeleton and creeper retreat, retaining failures and observed damage. Use at least three comparable trials per group before presenting a success rate
4. Expand to small groups, damage-response target retention, normal-survival workflows and natural terrain only when the previous stages are repeatable
5. Ender Dragon remains a separate later phase requiring appropriate equipment, ranged aiming, pillars and staged real testing. Do not extrapolate its result from a single zombie

`acceptance/BASELINE-COMMANDS.txt` lists explicit test-only setup commands. `baseline_stationary_combat.py` records the old baseline. `client_tick_combat_trial.py` submits one bounded new action and then observes input release. Both use only an explicitly supplied existing resident queue; neither discovers credentials, starts another writer or contacts runtime HTTP endpoints.

## Build and offline verification

Minecraft 1.21.1, NeoForge 21.1.255 and Java 21. Official Gradle 8.14.3 archive verified against SHA256 bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531. Build uses the official NeoForge binary pipeline with bridge.noRecompile=true.

- Java test + build: 149 tests, 0 failures/errors/skips
- Resident: 126 tests passed
- Watchdog: 117 discovered, 116 passed, 1 skipped because the historical frozen comparison source is absent
- Navigation: 254 tests passed
- Gameplay helpers: 30 tests passed
- Acceptance harnesses: 5 tests passed

These include protocol fakes, deterministic predicates and source contracts. They are not a simulated Minecraft performance score. The real game supplies physics, cooldown, hits, collision and server behavior.

No runtime queues, tokens, player identities, real world coordinates, logs, Minecraft assets or saved worlds are included in the source package. Existing licenses and notices are retained.
