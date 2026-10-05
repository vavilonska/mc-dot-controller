# External Minecraft combat controller, stage one

**当前阶段：外置控制逻辑 + 离线测试。尚未在游戏里自动战斗。**

A small, standard-library-only Python controller for a thin Minecraft client
bridge. Decision-making stays outside the mod. The command line is **offline-only**.
The real HTTP transport is **read-only**, even if a configuration says enabled.
Live combat is deliberately blocked until input can be guarded atomically on the
Minecraft main thread.

## Run without Minecraft

Requires Python 3.10+; verified here with Python 3.12.

```sh
python -m unittest discover -v
python -m combat_controller          # disabled; zero I/O
python -m combat_controller --demo   # deterministic fake session only
```

Run these commands from this directory. No installation or third-party packages
are needed. No command above reads an existing token or connects to a game.

## What is implemented

- Disabled-by-default finite state machine: observe → acquire → bounded aim →
  fresh crosshair check → one attack click → wait, or halt and release
- Explicit hostile allowlist: zombie, husk, drowned, skeleton, stray and bogged
- Players, pets, villagers, neutral mobs and unknown entities are never targets;
  nearby protected/unknown entities also block sword-sweep risk
- Extra danger stop for nearby creepers, wardens, withers, dragons, ghasts,
  blazes, witches and ravagers
- Crosshair UUID **and type** must match the selected target in a fresh snapshot
- Conservative 2.75-block distance guard and 1.5-second default attack cadence
- Bounded yaw/pitch changes, a new observed game tick after every input, and
  immutable target-type configuration
- Health below 14/20, food below 12/20, lost air, damage, displacement, GUI changes,
  unknown terrain, stale state or a changed world all stop the session
- No walking, retreating, jumping, chat, commands, crafting, GUI control, direct
  world mutation or arbitrary input
- Default 10-second session, 12 input attempts, 0.75-second snapshot age and
  1-second observation lease; all have hard configuration maxima
- Cleanup in `finally`, including exceptions/KeyboardInterrupt; cleanup failure
  is reported rather than claimed successful

Every attack counter is an **attempted click**, not evidence of damage or a kill.

## Terrain and adapter contract

`MineClientBridge` understands the actual v1.1.5 `/status`, `/state`, `/look` and
`/key` schemas, plus the companion read-only terrain extension. It pins the
expected run ID, process ID, player UUID and dimension. The terrain extension's
`world_generation` must agree across status, state and terrain reads.

It checks a complete player-centered 3×3×5 scan: a narrow allowlist of solid
vanilla floor blocks, empty fluid, known collision and open air above. Unloaded,
failed, truncated, incomplete or unknown observations fail closed. Slabs, stairs,
ice, modded floors and fractional standing heights are intentionally rejected.

The extension's 2 ms page budget can return fewer than 45 cells. Stage one stops
rather than combining potentially stale pages. This can reject otherwise safe
terrain; it is not evidence that the terrain is dangerous.

`HttpTransport` only permits three fixed read URLs and has loopback-IP-only
validation, no proxies, no redirects, bounded JSON, socket timeouts and a total
request deadline watchdog. All real HTTP POSTs are hard-disabled. Input schemas
are exercised through fake transports, not sent to Minecraft.

`ConnectionConfig.from_file` reads only a caller-selected, user-owned 0600 file.
There is no token discovery, automatic credential creation, environment-secret
lookup or reading of Minecraft's token file. `config.example.json` contains an
empty placeholder, not a working credential. Do not put real tokens in this repo.

## What is not yet verified or guaranteed

- No live automatic-combat test has been run for this controller
- The terrain extension must be built, installed and accepted separately
- v1.1.5 input is queued on the game thread without target, world-generation or
  deadline guards. A timed-out POST may execute later or after a world change.
  Client reads and socket cancellation cannot fix this. Therefore live HTTP
  input remains unavailable in this stage
- A Bridge-side action must validate the expected session/world generation,
  target UUID/type, ordinary reach, screen state and deadline **at execution**
  before live combat is enabled; it must drop expired or invalid queued actions
- No observed attack-cooldown field exists in v1.1.5. Fixed cadence is a fallback,
  not proof that cooldown is full or that modded weapons are compatible
- Entity observations have no line-of-sight filter. Only an actual matching
  crosshair permits a fake-policy attack; merely knowing an entity exists does not
- The terrain whitelist covers a tiny stationary area, not projectile safety,
  all mod behavior, all status effects, fire state or comprehensive survival
- The heartbeat is local observation freshness, **not a server-side input lease**
- `finally` cannot run after SIGKILL, power loss or interpreter termination.
  Only click inputs are modeled; no persistent key-down is used. Cleanup is
  best effort and cannot guarantee release after process death
- Stopping is safer than blind retreat, but stopping cannot guarantee survival

## Verification

At the initial stable snapshot: **90 unit tests passed**. Tests use deterministic
fake state, fake transport, mocked HTTP connections, temporary dummy configs and
a mocked blocked read for the deadline watchdog. No live endpoint was contacted.
Default-disabled and offline-demo runs passed, and Python compilation passed.
See `docs/PROTOCOL.md` for source evidence and the squared-distance issue.

## Source and licensing

This Python implementation is original project code. Upstream MineClient Bridge
was consulted for protocol compatibility; its Java implementation was not copied
into this directory. No license grant has been selected for this original
controller yet. Preserve the upstream project's license for any separately
redistributed upstream code; see `docs/PROTOCOL.md` for provenance.
