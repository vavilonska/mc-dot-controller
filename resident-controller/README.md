# Real-client resident controller

One external Python process talks to the real NeoForge Minecraft client. It owns
one task queue and one small loaded-world cache. The mod executes continuous
movement/mining/placement on client ticks; Python does not simulate physics,
inventory, networking, or generate 100 ms key pulses.

**Current source:** `1.1.6-loaded-scan.1` pairing, with 109 focused offline resident
checks. A later bounded live scan reported 4,864 tested positions, 41 coal blocks,
79 ms and 3 client ticks. This does not validate maximum scans, every biome/surface
mode, aim accuracy or combat; combat has not been exercised against a live target.
See [verification scope](../client-mod/docs/loaded-scan-verification.md).

## Owner start: once per playing session

Run in the **same actual desktop process/network namespace as Java**, using that
desktop's terminal. A remote shell sharing source files does not necessarily share the desktop's
loopback address, processes, or `/tmp`. The model-side queue commands may run in
another namespace only if the named workspace directory really is shared.

1. Launch the intended Minecraft client and select the intended friend server by
   the existing authorized flow. This controller never launches, logs in, joins,
   reconnects, disconnects, quits, respawns, or changes permissions.
2. Verify the current mod listener URL from its UI/configuration for this session.
   Supply the explicitly verified current port; there is no default, discovery
   assumption or port scanning.
3. From this source directory, run:

   ```sh
   ./owner-start.sh http://127.0.0.1:VERIFIED_PORT /path/to/shared/mailbox
   ```

4. Enter the **existing** bridge bearer at the hidden terminal prompt. It stays in
   process memory. There is no token in command arguments, queue files, logs,
   configuration, or credentials store. Optionally the owner may explicitly select
   their existing private file with `--token-file /owner/selected/private/file`.
   That file is read only on this deliberate start and is not copied or discovered.
   Alternatively append `--choose-token-file`: an optional Tk desktop dialog lets
   the owner select and confirm the existing file before it is read. This needs
   Tk already present on the desktop; it installs nothing and searches no paths.
   If unavailable, use the hidden prompt or explicit owner-selected file path.
5. `session.json` becomes `ready` after the schema/status handshake. `paused` means
   an action was already running; observe it or explicitly take over. Keep this
   foreground process open. Ctrl-C releases inputs and leaves Minecraft connected.

Only Python 3.10+ stdlib is required. No install or boot service is created. Keep
`navigation-controller` (published layout) or `minecraft-navigation-controller`
(local source layout) beside this directory: its existing A* and terrain
parser are imported unchanged. The existing building planner remains unchanged
and may supply placement order/anchors to `action: place_block` calls.

## Model-side calls: no token and no loopback needed

From this directory (or set `PYTHONPATH` to it):

```sh
python3 -m resident_controller --queue /path/to/shared/mailbox status
python3 -m resident_controller --queue /path/to/shared/mailbox submit \
  --json '{"op":"observe","terrain":true,"radius":4,"vertical":2,"frame":true}' --wait 10
```

`submit` returns a request ID immediately unless `--wait SECONDS` is used. Retrieve
that result later:

```sh
python3 -m resident_controller --queue /path/to/shared/mailbox result REQUEST_ID --wait 30
```

Python callers can use `QueueClient(directory).submit(command)`, `.result(id)`,
`.wait(id, timeout)`, and `.session()`. A wait timeout means pending, never failed.
Keep the returned request ID; never retry by inventing a new ID after uncertainty.
Caller-chosen IDs must be unique for new commands. Reusing an ID reads its existing
result and never replays it in the same running controller.

### Direct control is preserved

Each direct command clears queued tasks, cancels/releases the active mod task
atomically on the client thread, and applies its requested input **once**. There
is no separate cancellation then duplicate raw-input call. Subsequent direct
commands retain already held direct keys until their matching `up` or `cancel`.

```json
{"op":"direct","endpoint":"look","body":{"yaw":90,"pitch":0,"relative":false}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.forward","action":"down"}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.jump","action":"down"}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.forward","action":"up"}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.jump","action":"up"}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.hotbar.1","action":"click"}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.attack","action":"down"}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.attack","action":"up"}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.use","action":"click"}}
{"op":"direct","endpoint":"key","body":{"mapping":"key.inventory","action":"click"}}
{"op":"direct","endpoint":"raw-key","body":{"key":"key.keyboard.escape","action":"click"}}
{"op":"direct","endpoint":"mouse","body":{"action":"click","button":0,"x":120,"y":80}}
{"op":"cancel"}
```

Endpoints: `key`, `raw-key`, `look`, `mouse`, `text`, `command`, `release-all`.
They are the existing mod contracts, not OS keyboard/mouse control. `observe`
returns actual screen/menu state; `frame:true` writes the native Minecraft PNG at
`latest.png` in the shared mailbox. There is no image generation or alternate
renderer. The command endpoint is available only for explicitly requested game
commands; it is not used for crafting, teleporting, or building.

### View-only entity lock (source implementation)

The external resident can keep the view centered on **one observed entity's exact
bounding-box center**, using the player's current eye position. It runs at a
best-effort 10 Hz. This is camera tracking, not pathfinding or automatic combat;
it does not require the entity to be attackable or in line of sight.

```json
{"op":"aim_lock"}
{"op":"aim_lock","target_uuid":"OBSERVED-ENTITY-UUID","radius":16}
{"op":"aim_unlock"}
```

- Omit `target_uuid` to lock the current entity crosshair; a miss/block fails
  rather than silently choosing the nearest entity. `radius` is 1–32, default 16.
  UUID comes from the current `observe` result's `nearby.entities` or `crosshair`.
- Direct forward/back/strafe/jump, attack, use and hotbar inputs remain independent.
  Locking, following, losing a target and `aim_unlock` send **no key releases**.
  A previously held attack key remains held after losing the target; explicitly
  send attack `up`, or `cancel` to release all held controls.
- A direct `look` releases the lock before applying the requested view once.
  A change in the actual yaw/pitch also releases it. The mod compares the freshly
  observed view atomically before each guarded update, preventing a read/write
  race from overwriting a newer manual view. The tolerance is 0.01 degrees.
- Target death/disappearance (including outside the radius or a truncated nearby
  list), player death, world/player changes, menus, pause or failed observation
  releases the lock; it never switches targets or reconnects. A transport-ambiguous
  write disables tracking and pauses automatic work, with no replay.
- `cancel`, `shutdown` and direct `release-all` also clear the lock. Semantic tasks
  release it because mining, placement and path steering need their own view.
  Starting a lock while a task is active/queued fails without cancelling that task.
- `session.json` and observations include `aim_lock` with target, center, update
  count and release reason. The initial successful request means tracking was
  admitted and one guarded look dispatched; it is not evidence of live accuracy.
  A controller restart does not restore an old lock.

Requires the updated mod state marker `aim_view_guard_schema_version:1`, exact
`player.eye_position`, `player.alive`, `nearby.entities[].bounding_box:{min,max}`,
`screen_open`, and `paused`. Old mods are rejected **before** any lock write.
The additive `/control/look` `guard` contract is described in the mod's
`docs/entity-aim-lock.md`. Ordinary direct look remains backward compatible.
Both this resident process and the mod/client need a planned restart to load the
new source/build. Offline checks do not establish live aim or combat behavior. The later bounded scan milestone is reported separately.

### Current biome observation (same candidate mod)

The unchanged `observe` operation returns `result.state.world.biome_id`: the
actual registry key at the player's current feet block, or explicit null if
unavailable. For example `minecraft:cherry_grove` distinguishes the biome from
cherry trees planted elsewhere. This is a read-only current-position fact, not
a region scan. It requires the same candidate mod/client restart as view lock;
no separate resident operation or game action is added.

### Automatic melee combat (current source)

`{"op":"combat_start"}` selects and keeps one observed hostile target; optional
`target_uuid`, `radius`, `approach` and `shield` refine that start.
`{"op":"combat_stop"}` stops and releases its inputs. Any direct command takes
control back immediately in the resident loop. Sword/axe swings, short flat
approach and offhand-shield sequencing use ordinary real-client inputs, with
exact entity view lock. Players/pets/neutral types are not chosen as targets.

`session.json.combat` and observations show the phase, reason and input-attempt
counts. These are **not confirmed hits or kills**. Current input lacks atomic
attack target binding and observed cooldown/blocking, so live acceptance and
last-instant collateral risk remain. See [behavior, limits and one-time loading
steps](docs/NATIVE_COMBAT.md). No game process was controlled by the offline work.

### Loaded-world prospecting (current source)

```json
{"op":"scan_start","id":"survey-1","mode":"both","max_results":64}
{"op":"scan_status","id":"survey-1"}
{"op":"scan_cancel","id":"survey-1"}
```

These use the existing authenticated bridge to request a tick-budgeted, read-only
scan of client-loaded data. Optional bounds and ore IDs narrow the request. The
start command returns immediately with a scan snapshot; poll `scan_status` to see
its progress. These commands do not take gameplay input ownership, enter the
semantic-task queue, stop combat/view lock, or move the player. They never replay
an uncertain start/cancel request. Use the returned `scan_id` to check its state.

`scan_cache.json` retains bounded, timestamped observations from the current
resident session and observed world only. Moving yourself and starting another
scan can add newly loaded observations. This is historical client knowledge, not
a live map or a claim that unknown chunks contain nothing. See
[options, cache boundaries, and offline evidence](docs/PROSPECTING.md).

Generic `blocks`, `biomes`, and `surface_sites` modes also accept `block_ids`,
`biome_ids`, optional water proximity, and count/density/distance sorting. For example,
`{"op":"scan_start","id":"cherry-blocks-1","mode":"blocks","block_ids":["minecraft:cherry_log","minecraft:cherry_leaves"],"require_water":true,"water_radius":32,"sort":"count"}`
asks about concentrations of actual cherry blocks without imposing a cherry-grove
biome filter. Original `ores`, `cherry_sites`, and `both` presets remain available.

### Semantic tasks

```json
{"op":"action","action":"follow_path","waypoints":[{"x":12.5,"y":64,"z":8.5},{"x":13.5,"y":64,"z":8.5}],"timeout_ms":15000}
{"op":"action","action":"break_block","target":{"x":14,"y":64,"z":8},"hotbar_slot":0}
{"op":"action","action":"place_block","support":{"x":13,"y":63,"z":8},"face":"up","hotbar_slot":1,"jump":true}
{"op":"action","action":"click_slot","container_id":0,"slot":36,"button":0,"click_type":"pickup"}
{"op":"walk_to","target":{"x":13,"y":64,"z":8},"radius":4,"vertical":2}
{"op":"craft_planks","log_id":"minecraft:oak_log"}
{"op":"pillar","height":2,"block_id":"minecraft:oak_planks"}
```

- `walk_to` refreshes a local terrain cuboid and uses the existing A* once. Its
  current planner supports flat walking and one-block descent, not arbitrary
  jumping, long-range routing, or unknown chunks. The explicit `follow_path`
  action accepts waypoints with optional `jump:true` when a caller has a route.
- `craft_planks` consumes **one** observed log/wood item, making four planks. It
  requires an observed InventoryMenu, empty cursor and 2×2 crafting grid. It uses
  `player_inventory`/`inventory_index` metadata to find the actual source menu slot,
  moves exactly one log to input slot 1, observes output slot 0, quick-moves it once,
  and observes inventory deltas. It does not synthesize recipes or pretend slots
  succeeded. It leaves the UI as it was; failure may leave items in the crafting
  grid/cursor, shown in subsequent observations. Oak/spruce/birch/jungle/acacia/
  dark oak/mangrove/cherry log/wood and their stripped forms are supported.
- `pillar` places 1–8 blocks beneath the centered player, using normal jump + use.
  It finds the material in the observed hotbar or swaps an observed player-storage
  stack into a hotbar slot, then verifies each mod action. Stand within 0.35 blocks
  of the base center first. Optional integer `base:{x,y,z}` is the first placement
  cell; omitted means the current feet block. Optional `hotbar_slot` chooses the
  swap destination when needed. Existing hotbar contents are swapped, not dropped.
- These are sequential tasks. Any failed/cancelled/uncertain task drops the already
  queued dependents, rather than continuing the later build after failed mining.
- Health, death, stale state, or a failed action never disconnects the server. The
  mod stops input on action failure/death; the controller reports the outcome.

## Practical first vertical slice

Use current observations, not the example coordinates or old inventory counts.

1. `observe` with terrain/frame. Locate a loaded log and an adjacent reachable
   standing cell. Use `walk_to` or an explicit known waypoint path.
2. `action: break_block` for that log. Check the returned world result and actual
   inventory. A broken log is not proof its dropped item was collected. Walk near
   the observed drop with a fresh route if collection is needed, then observe.
3. `craft_planks` for one actual inventory log. Require its observed +4/-1 result.
4. Walk to a centered, observed suitable placement base, then `pillar` with two
   planks. Fetch `observe` with `frame:true` for a native view of the result.

The model decides the high-level next step; the mod does every tick. No CUA
keypress loop is required. This guide is not evidence that these live steps ran.

## Mod HTTP contract, action schema 1

- POST `/control/action`: `{action_id,action,timeout_ms?,...}`. Immediate 202 while
  running, 200 for a terminal record. Exactly one mod action can run at a time.
- GET `/control/action/status?action_id=ID`: status of that ID; omit query for
  current/last. Status is `running`, `succeeded`, `failed`, `cancelled`, or `idle`.
- POST `/control/action/cancel`: `{action_id}`. The ID protects a newer action
  against a delayed cancellation of an older one.
- `follow_path`: `waypoints:[{x,y,z,jump?}]`, feet coordinates
- `break_block`: `target:{x,y,z}`, optional zero-based `hotbar_slot`
- `place_block`: `support:{x,y,z}`, `face:up|down|north|south|east|west`, optional
  `hotbar_slot`, `jump`, `sneak`
- `click_slot`: `container_id`, menu `slot`, `button`,
  `click_type:pickup|quick_move|swap|throw|pickup_all|quick_craft`
- Status includes `action_schema_version`, `action_id`, `action`, `status`, `reason`,
  `action_session`, `ticks`, `result`, `input_owner`, `server_confirmed:false`
- State/screen menu includes `menu_class`, `container_id`, `state_id`, `carried`,
  and slots with `menu_index`, `slot_index`, `container_slot`, `player_inventory`,
  optional `inventory_index`, `item`, and `active`

The resident generates one stable action ID per request step. It never resends a
POST after a failed/uncertain exchange. Mod success is **client-observed**, not a
strong server-acknowledgment guarantee. A direct response only proves dispatch;
read actual state/frame to establish its gameplay effect.

## Errors and recovery

Result states: `succeeded`, `failed`, `cancelled`, `uncertain`. Inspect `reason`,
`action`, `result`, and optional cancellation evidence. A failed semantic action
ends that task and clears queued dependents. A transport ambiguity pauses automatic
tasks; `observe` remains available. Use `cancel` or a direct takeover when needed,
or `resume` once the action status is no longer running. Resume admits only **new**
commands; it never retries old requests. A changed Java run/PID/action-session requires a fresh
owner start, rather than reconnecting and replaying tasks. The mod retains its
action registry across same-process HTTP restarts; JVM restart changes the
non-secret action-session UUID.

The mailbox has one lock, at most 32 pending commands, and the latest 256 results.
A consumed-ID set lives only in the resident process; older expired results do not
make the same ID executable again. Restart gives a new session ID and reports old
inbox/working files as uncertain, with no replay. `session.json` is the current
controller status; `observation.json` is the latest explicitly requested observation.
An action reply includes its completion observation. Scan results may be retained
in the bounded historical scan cache; this is not a continually refreshed world
map. No background inventory mirror is maintained by the resident itself. A dead controller can leave stale files; updated_at and its
actual desktop process must be checked, not a PID in another namespace.

Shutdown: `{"op":"shutdown"}` or owner Ctrl-C releases inputs and stops the
controller only. Never send a game quit as unconditional cleanup.

## Focused offline checks

```sh
python3 -m compileall -q resident_controller tests
python3 -m unittest discover -s tests -v
bash -n owner-start.sh
```

Checks use an in-memory fake protocol and temporary files. They establish parsing,
queue sequencing, single dispatch, no replay, takeover, recipe bookkeeping, aim,
combat sequencing and loaded-scan protocol/cache handling;
they do not validate actual movement, vanilla crafting, server synchronization,
placement, the native image, or network/runtime integration.

## Provenance and licensing

This controller is original Python standard-library source. No Minecraft, Aoi,
minecraft-data, or upstream Java code/assets are embedded. The three sibling
navigation package files imported here (`__init__.py`, `terrain.py`, `planner.py`)
are existing original helpers from this project's navigation controller, unchanged.
No license grant has been assigned to these original components. The upstream MIT
license under `client-mod/` does not automatically license this independent code.
The public source allowlist is `PUBLIC-FILES.txt`; it excludes runtime queues,
observations, images, credentials, and generated Python caches.

## Additional gameplay helpers

The separate [gameplay helpers](../gameplay-helpers/README.md) retain shaped
crafting, local up/down route helpers and an explicit local state exporter. They
reuse the same credential-free queue. Their source and reported live recipe
evidence must not be read as automatic authorization to run a new action.
