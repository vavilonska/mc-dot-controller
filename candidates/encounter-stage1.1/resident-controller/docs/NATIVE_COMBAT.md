# Native-client melee combat source

Integration for the Minecraft 1.21.1 resident controller paired with
`1.1.6-loaded-scan.1`. Source tests use temporary queues and in-memory fake
bridges. A later short sword/shield script completed one observed zombie
encounter: four attack dispatches, then target-dead, with player health still 20.
Persistent watchdog threat preemption remains unverified; a successful read-only
scan is not combat acceptance.

## Commands after the coordinated update

```json
{"op":"combat_start"}
{"op":"combat_start","target_uuid":"CURRENT-OBSERVED-UUID","radius":12,"approach":true,"shield":true}
{"op":"combat_stop"}
```

- `combat_start` chooses one currently observed always-hostile vanilla entity,
  nearest first, or the supplied observed UUID. It keeps that UUID/entity ID/type.
  Target loss or death ends this session; it does not silently retarget or claim a
  kill. A new explicit start is needed for a different target.
- `radius` limits initial target selection to 1–32 blocks, default 12. Combat
  observation uses at least five blocks even for a smaller selection radius, so
  sword-sweep checks can see surrounding players and pets.
- The task queue must be idle. Successful admission clears previous held direct
  inputs once and takes ownership of view, forward movement and optional use.
- Combat stays off until started. There is no local-server-only gate, separate
  acceptance flag, axe-only rule, ten-second cap, high-health cutoff or danger
  blacklist. Existing authentication and transport/session checks are unchanged.
- Players, pets, villagers, unknown types and conditionally neutral species are
  not selected. For example, spiders, endermen, piglins, wolves, bees and iron
  golems are excluded because the state schema does not expose their hostility.

## What the loop actually does

1. Reuses the external 10 Hz exact AABB-center `EntityAimLock` and its guarded
   look updates. Aim and combat decisions remain outside the client mod.
2. Keeps a selected vanilla sword/axe if available. Otherwise selects an observed
   hotbar sword/axe and waits for a newer state confirming that selection. It
   never fabricates inventory, swaps storage, or crafts equipment.
3. Until the target is actually picked or its nearest AABB is within 2.5 blocks,
   checks a short flat collision/support corridor and holds forward. It releases forward before refreshing paginated terrain.
   This accepts known full support rather than the old restricted floor-name
   allowlist. Holes, fluid, obstruction, stairs/slabs, jumps or unknown terrain
   stop this minimal approach. Every column in the swept body rectangle is checked,
   including columns that point samples could skip. It does not implement pursuit
   around obstacles.
4. After closing, releases forward and requires a fresh entity crosshair matching
   UUID, entity ID and type, plus actual eye-to-hit distance within melee reach,
   before each ordinary `key.attack` click. No held
   auto-attack key or synthetic hit/damage result is used.
5. Spaces sword attempts by at least 0.7 seconds and axe attempts by at least
   1.35 seconds. These are deliberate fixed pacing values, not observed attack
   cooldown. There is no attack-cooldown field in the current mod.
6. With an observed offhand shield, attempts use between attacks, lowers it and
   waits for another observed game tick before attacking. It does not press use
   against a block/other-entity crosshair, avoiding obvious axe stripping/chest
   interactions. It reports a shield phase/input attempt, not confirmed blocking.
7. Before a sword attempt, checks for observed protected/unknown living entities
   overlapping the target's possible sweep neighborhood. It switches to an
   observed hotbar axe if available, otherwise stops. An entity-list truncation
   likewise cannot authorize sword sweep.

## Stop and direct takeover

`combat_stop` ends this combat loop, unlocks its view and releases the inputs it
owns. `cancel` releases all controls. Every new direct command, semantic task,
`aim_lock` or `aim_unlock` also stops automatic combat first. The requested direct
command is then applied once; a subsequent owner key-down stays held normally.
Standalone view-only aim behavior is unchanged when combat is inactive.

Manual view changes, death, target disappearance, a menu/pause, identity changes
or failed observation also stop combat. Local stop intent is applied before a
fallible identity read, so a failed stop read cannot make the loop continue.
Mouse-bound shield releases use the acknowledged mouse button's existing release
route, including across menus. A failed cleanup is reported as unconfirmed and
pauses automatic work. Successful explicit release-all clears old ownership.
No old-session key cleanup is sent into a replacement game session.

A newer semantic action has already cleared previous inputs in the mod. Combat
abandons its old input ledger when it observes that ownership change, rather than
sending key-up commands that would cancel the new action.

## Evidence and actual limits

`session.json.combat` and `observe.result.combat` expose the target, phase, stop
reason, held inputs, attack attempts/dispatches and last observed target health.

- `attack_attempts` counts requested input dispatch attempts, including uncertain
  delivery. `attack_dispatches` counts their successful client acknowledgements.
- `server_confirmed:false`, `hits_confirmed:null`, `kills_confirmed:null` are
  intentional. A change in observed health is not attributed to this controller.
- Ambiguous attack dispatch is consumed, never automatically retried.
- The existing ordinary key endpoint has no atomic target-bound attack guard.
  The rendered crosshair/entity position can change between observation and
  processing. The observation checks do not guarantee zero collateral damage,
  especially sword sweep or another entity entering the line at the last instant.
- There is no attack-cooldown, active-blocking or server hit acknowledgement in
  the current observation contract. Mods and server rules can change mechanics.
- Forward/use holds are normal client input. An external process crash, stalled
  transport, terrain change or knockback is not covered by a mod-side input
  lease. This version cannot guarantee instant stopping or survival.
- All rendering remains the existing native Minecraft frame. No alternative
  game renderer, bot protocol, game state mutation, login or connection route
  was introduced. Old `/control/guarded-action` local-only rules are untouched;
  this feature uses the existing authorized direct-input contract instead.

## Current source and verification

Use the matching `1.1.6-loaded-scan.1` mod and full resident source, retaining the
existing sibling navigation helpers. The existing owner-start and verified
session workflow remains; do not run a competing resident or invent new access.

The current combined resident suite passes 109 offline checks. Its earlier combat
subset had 81 cases (34 existing/aim + 47 combat). These tests establish protocol
and control sequencing, not live combat, server hit confirmation, shield blocking
or gameplay success. The separate live script result above is limited to one
encounter; it does not validate every target, approach, menu interruption or
continuous-defense transition.

```sh
python3 -m compileall -q resident_controller tests
python3 -m unittest discover -s tests -v
bash -n owner-start.sh
```

The independent [v5 watchdog](../../defense-watchdog/README.md) uses these existing
operations and has been deployed as the sole defense queue coordinator. This
resident includes `melee_closing_schema_version:2`: entity reach is measured from
observed eye position to the actual hit point; approach checks every swept body
column and keeps closing until the target is picked or the nearest AABB is within
2.5 blocks. Correct identity and the actual eye-to-hit range still gate attacks.
The gateway gives every admitted hostile bounded progress/departure rules. Its
full natural-encounter, blocked-approach and retreat sequence still needs live evidence.
Further separately authorized encounters must verify actual equipment, target records,
ordinary swings, approach, shield release and direct/manual takeover. Dispatch
counts must never be reported as confirmed hits or kills.
