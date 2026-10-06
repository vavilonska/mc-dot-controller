# Resident client actions (schema 1)

This API runs inside the real Minecraft 1.21.1 / NeoForge 21.1.255 client. It is client-only and uses the existing authenticated loopback HTTP server. The server can be a normal compatible multiplayer server; it does not need this mod. There is no protocol bot, teleport, movement-packet generator or world-edit operation.

The external controller chooses routes, targets and crafting combinations. The client handles timing each game tick, ordinary movement input, mining, interaction, inventory prediction and rendering. The old direct key/raw-key/look/mouse/text/command endpoints remain accessible. They take input ownership by cancelling the current action and releasing its input before applying the requested direct operation. Further direct requests preserve existing direct holds, so combinations such as forward+jump still work. Starting a new action clears earlier direct holds once. Deprecated guarded-local experiments remain separate and cannot acquire input while a new action owns it.

## Routes

- `POST /control/action` starts one action; 202 means running, 200 means a repeated ID already has a terminal result
- `GET /control/action/status?action_id=...` reads that action; without an ID it reads the current or most recent action, or idle
- `POST /control/action/cancel` with `{"action_id":"..."}` cancels only that action; a late cancel never cancels a newer one

All routes require the existing loopback check and Bearer authorization. Existing bridge protocol schema remains 2; new action schema is 1.

Common request fields: `action_id` (nonblank string, up to 128 characters), `action`, optional `timeout_ms` (ordinary actions: default 15000, 50–600000;
`recover_environment`: default 0, with 0 meaning goal-or-stop lifetime). One action may run at a time; another ID receives HTTP 409 `action_busy`.

IDs are retained for the Java process lifetime, including world changes and same-process bridge restarts. Repeating the exact same JSON request returns its recorded status without replaying any game input. Reusing an ID with a different body returns 409 `action_id_payload_mismatch`. Never resubmit with a new ID merely because an HTTP response was lost. Query the original ID first. The non-secret UUID `action_session` appears in action status, and the same identity appears at `/control/capabilities` → `client_actions.session`. A new Java process starts a new session; queued work from an old session should not be resumed blindly.

## Follow path

```json
{"action_id":"walk-1","action":"follow_path","timeout_ms":15000,"waypoints":[{"x":10.5,"y":64,"z":20.5},{"x":11.5,"y":65,"z":20.5,"jump":true}]}
```

Waypoints are player feet coordinates (usually block-center X/Z), not block corners. The executor follows up to 512 points, turns on ticks, applies continuous forward input, and uses normal jump input for an upward step, a collision, or an explicit `jump`. It does not pathfind, remove obstacles or assume the floor is safe. The external planner is responsible for the route. It reports `stuck` after roughly three seconds of no progress toward the current waypoint, or `deadline_exceeded` at the requested wall-clock deadline. Normal client physics applies throughout.

## Recover environment

```json
{"action_id":"recover-1","action":"recover_environment","timeout_ms":0,"waypoints":[]}
```

This v6 action uses ordinary per-tick input. Water, lava and powder-snow flags
keep jump pressed. A nonempty route follows at most 512 externally supplied,
currently observed waypoints; the mod does not discover an escape route. An
empty, exhausted or physically stalled route maintains flotation without
claiming success. After 60 no-progress ticks, futile horizontal pressure stops
while flotation remains. The default zero deadline ends only at the observed
goal or an explicit/normal context stop, rather than an external thinking timer.

Five consecutive dry grounded client ticks produce `environment_dry_observed`.
The outer watchdog then requires two later increasing-game-time observations
before resuming ordinary tasks. It does not wait for full health, food, air or
zero frozen ticks. No observed exit remains a blocker, not proof of rescue.
STOP, direct takeover, death, menus, pause and world changes retain their normal
input-release behavior. Failed external reads alone do not release native flotation.

Player state adds `environment_schema_version:1`, `in_water`, `eye_in_water`,
`in_lava`, `in_powder_snow`, `frozen_ticks`, `on_fire` and `fire_ticks`.

## Break block

```json
{"action_id":"log-1","action":"break_block","target":{"x":12,"y":64,"z":20},"hotbar_slot":0,"timeout_ms":20000}
```

`hotbar_slot` is optional (0–8). The client aims at the requested block and uses a continuous ordinary attack hold, including vanilla mining progress and interaction hooks. The actual renderer pick must hit that block within the player's current block-interaction reach. It does not approach the target or collect drops automatically. Follow a path toward observed item entities to collect them normally. Already absent targets return `block_absent`; broken targets return `block_broken_observed`.

## Place block / pillar step

```json
{"action_id":"pillar-1","action":"place_block","support":{"x":10,"y":63,"z":20},"face":"up","hotbar_slot":2,"jump":true}
```

The support block and face identify the clicked surface. Faces are `up`, `down`, `north`, `south`, `east`, `west`. The destination is the adjacent block cell. The selected item must be a BlockItem. `jump` and `sneak` are optional booleans, false by default. Jump-underfoot waits until ordinary movement clears the destination's collision box, interacts once, and then waits for landing when the expected placed block is observed. `sneak:true` requests ordinary sneaking when placing against an interactive support.

In `1.1.6-continuity.1`, success requires five consecutive observed-block ticks
and observed one-item consumption, or creative mode. Jump-underfoot also waits
for landing. Results label this `client_observed_stable`; it is not a server ack.

The real renderer pick, current reach, BlockPlaceContext and vanilla useItemOn govern placement. The executor never repeatedly clicks an uncertain placement. Failure can report `support_face_not_in_reach_or_visible`, `placement_target_not_available`, `placement_rejected` or `placement_not_observed`.

## Inventory slot operation

```json
{"action_id":"slot-1","action":"click_slot","container_id":0,"slot":9,"button":0,"click_type":"pickup"}
```

The currently active `player.containerMenu` is used, including player inventory menu 0 when its GUI is closed. Supply observed container and menu-slot indices. `click_type` supports vanilla `pickup`, `quick_move`, `swap`, `throw`, `pickup_all`, `quick_craft` and their ordinary button encodings. `slot:-999` means the vanilla outside slot. Container changes and out-of-range slot indices fail without a click.

One ordinary `handleInventoryMouseClick` is dispatched. Completion reason is `click_dispatched`, which does not claim a recipe or server-confirmed inventory change. The caller combines clicks and checks later menu observations. No custom recipe framework is embedded in the mod.

## Results and observation

```json
{"ok":true,"protocol":"mineclient-bridge","schema_version":2,"action_schema_version":1,"action_session":"...","action_id":"walk-1","action":"follow_path","status":"succeeded","reason":"path_reached","ticks":23,"input_owner":"direct","server_confirmed":false,"result":{"waypoint_index":2,"waypoint_count":2,"x":11.5,"y":65.0,"z":20.5}}
```

States: `running`, `succeeded`, `failed`, `cancelled`; no accepted action yields `idle` with explicit null `action_id`. `ok:true` means the status operation succeeded; inspect `status` for the action outcome. The snapshot is also available as `client_action` in `/control/status` and `/control/state`.

World/player replacement, loss of a usable current player, a world-action screen opening and cancellation release owned input. Ordinary action stuck detection and finite deadlines also release input; environment recovery has the goal lifetime and flotation exception described above. These conditions stop the action, not the connection. No heartbeat, health threshold, potion-effect restriction, floor whitelist, weapon whitelist or singleplayer requirement is imposed by this API.

Success is **client-observed**, including Minecraft prediction, not a claimed authoritative server acknowledgement. The caller should compare later state/terrain/inventory as needed, and must not blindly replay a placement or slot click after uncertainty.

`/control/state` and `/control/screen` include `menu` whenever the player exists:

- `menu_class`, `container_id`, `state_id`
- `carried`: `{empty,id,count,damage,max_damage}`
- `slots`: `[{menu_index,slot_index,container_slot,player_inventory,inventory_index?,active,item:{empty,id,count,damage,max_damage}}]`
- `slots_total`, `slots_returned`, `slots_truncated`

`inventory_index` appears only when `player_inventory:true`; it is the underlying player inventory index, including armor/offhand indices if present. The existing top-level GUI screen snapshot fields remain unchanged.

## Verification scope

The source is compiled and tested against cached official Minecraft 1.21.1 / NeoForge 21.1.255 binaries with Java 21 and ModDevGradle's binary pipeline. Unit checks cover wire parsing, one-owner action admission, duplicate and cancelled IDs, copied results, null serialization, tick steering, turning, jump selection and endpoint/auth/vanilla-API wiring. These checks do not initialize a game or prove multiplayer gameplay. Installed-profile replacement, launch, connection, live walk/mining/crafting/pillar validation and viewer verification are separate coordinated steps.
