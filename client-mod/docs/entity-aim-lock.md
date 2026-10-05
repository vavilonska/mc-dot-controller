# Entity view lock and current biome observation

This additive implementation is included in `1.1.6-loaded-scan.1`. The source
checks establish view-guard and controller behavior, not live aim/combat accuracy.
The separate small read-only scan milestone does not validate these input paths.

The external Python resident owns lock lifetime and 10 Hz tracking. The mod adds
exact geometry observations and one guarded absolute look update. It does not
store a persistent target or hold/release movement, attack or use inputs.

## Observations

`GET /control/state?radius=16` adds:

- `aim_view_guard_schema_version: 1`
- `screen_open` and `paused`
- `world.biome_id`: actual biome registry key at `player.blockPosition()` (feet),
  such as `minecraft:cherry_grove`; explicit JSON null if unavailable. This is
  current-position observation only, not terrain-wide scanning or tree inference
- `player.eye_position:{x,y,z}` from `getEyePosition()` and `player.alive`
- `nearby.entities[].bounding_box:{min:{x,y,z},max:{x,y,z}}` from the actual AABB

`world.biome_id` is added only to `/control/state`; the resident's existing
`observe` returns that state unchanged. The wire serializer preserves only this
new explicit nullable world field and retains legacy omission of other nulls.

The existing entity UUID, ID, `alive`, health and world/action session identify the
target. `GET /control/capabilities` also advertises the guard schema. No endpoint,
listener, credential, permission, login, game command or background service is added.

## Compare-before-write

An ordinary `POST /control/look` stays backward compatible. An external tracker
must first observe the schema marker, then send:

```json
{
  "yaw": -20.4,
  "pitch": 5.0,
  "relative": false,
  "guard": {
    "schema_version": 1,
    "expected_world_generation": "<observed UUID>",
    "expected_player_uuid": "<observed UUID>",
    "expected_action_session": "<observed UUID>",
    "expected_game_time": 100,
    "expected_yaw": -18.0,
    "expected_pitch": 5.0,
    "target_entity_id": 42,
    "target_uuid": "<observed UUID>"
  }
}
```

Inside one Minecraft-thread callback, the guard requires a living player, no menu
or game pause, no semantic/guarded-movement owner, matching session/world/player,
a snapshot no more than 5 world ticks old, and unchanged yaw/pitch (0.01° tolerance,
with yaw wrapping). It resolves the entity ID again and verifies UUID and life so
a removed/dead target or reused ID is rejected before changing the view. Guarded
look does not call direct takeover or release any keys. Success includes
`aim_view_guard_schema_version:1`, and the actual applied float yaw/pitch.

The external controller releases tracking on rejection, target loss/death or a
manual view change. It never resends an ambiguous update, chooses a replacement
target, disconnects, respawns or attacks. A held direct attack remains held until
its own `up` or global `cancel`. The feature aims at the observed center, and does
not claim line of sight, hit validity, server acknowledgement or frame-perfect
tracking of fast moving entities.

## Use with the current source

Use the matching `1.1.6-loaded-scan.1` mod and current resident source, built against
Minecraft 1.21.1 / NeoForge 21.1.255. Retain the prior working source/profile when
performing a separately authorized update, and do not run competing residents.

Submit `{"op":"aim_lock"}` for the currently observed entity crosshair, or
`{"op":"aim_lock","target_uuid":"CURRENT-OBSERVED-UUID","radius":16}`.
`{"op":"aim_unlock"}` stops camera tracking. Direct look takes over immediately;
direct movement/attack remains independent. Runtime aim status stays in the
private mailbox. The view lock itself does not attack.

The current source also retains the bounded [visible-face mining fallback](mining-visible-face.md),
with ordinary renderer-pick, exact-target and reach checks. None of the offline
geometry tests is proof of a live hit, kill or full gameplay acceptance.
