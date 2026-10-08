# External Minecraft combat controller

This directory retains the earlier prototype and algorithm work. The current real-client execution path is [resident-controller](../resident-controller/README.md) with [client-actions](../client-mod/docs/client-actions.md). The A*/terrain helpers here are reused unchanged; prototype-specific runtime gates apply only to their own adapters.

**当前阶段：外置战斗逻辑及受保护接口已接好，默认关闭；这里只完成了离线测试，尚未验收自动战斗。**

A standard-library-only Python controller for a thin Minecraft client bridge.
Decision-making stays outside the mod. The command line remains **offline-only**.
A guarded HTTP adapter is implemented but **disabled by default**. It can be armed
only for explicitly authorized, separately verified isolated local acceptance.
It never falls back to legacy unguarded input routes.

## Run without Minecraft

Requires Python 3.10+; verified here with Python 3.12.

```sh
python -m unittest discover -v
python -m combat_controller          # disabled; zero I/O
python -m combat_controller --demo   # deterministic fake session only
```

Run from this directory. No installation or third-party packages are needed.
These commands never read an existing token or connect to a game.

## Controller behavior

- Disabled-by-default state machine: observe → acquire → bounded aim → fresh
  crosshair check → guarded attack attempt → wait, or halt
- Explicit hostile allowlist: zombie, husk, drowned, skeleton, stray and bogged
- Only vanilla axes; swords and unarmed attacks are rejected. The game-thread
  guard additionally rejects enchantments and sword-sweep capability
- Players, pets, villagers, neutral mobs and unknown entities are never targets;
  nearby protected/unknown entities also stop the session
- Extra danger stop for nearby creepers, wardens, withers, dragons, ghasts,
  blazes, witches and ravagers
- Crosshair UUID **and type** must match the selected target in a fresh snapshot
- Conservative 2.75-block distance guard and 1.5-second default attack cadence
- Bounded yaw/pitch changes and a new observed game tick after every input
- Health below 14/20, food below 12/20, lost air, damage, displacement, GUI changes,
  unclear terrain, stale state or a changed world all stop the session
- No walking, retreating, jumping, chat, commands, crafting, GUI control, direct
  world mutation or arbitrary input
- Default 10-second session, 12 action attempts, 0.75-second snapshot age and
  1-second observation lease; all have hard configuration maxima
- A final cleanup hook always runs. The guarded adapter only reads back neutral
  input, because its actions never hold keys. It never sends unguarded release-all

Attack counts represent **attempts**, not confirmed damage, hits or kills.
The result's legacy `release_confirmed` field means input-clear readback for the
real guarded adapter, not that a release command was sent.

## Terrain and guarded adapter

State/identity reads use the actual MineClient Bridge v1.1.5 schema plus the
companion terrain/world-generation extension. The adapter pins expected run ID,
PID, player UUID and dimension. World generation must agree across observations.

It checks a complete 3×3×5 scan: a narrow allowlist of solid vanilla floor blocks,
empty fluid, known collision and open air above. Unloaded, failed, truncated,
incomplete or unknown data fails closed. Slabs, stairs, ice, modded floors and
fractional standing heights are intentionally rejected. A 2 ms terrain page
budget can cause an otherwise safe scan to be rejected; this is not proof of a
hazard, and this version does not combine stale pages.

Before action, `prepare_guarded()` verifies exact guarded capability schema 1,
local-only restriction, axe-only scope, synchronous attack and no held input.
Both `enabled` and `acceptance_verified` must be explicitly true in the private
connection settings. Defaults are false. These flags are operator attestations,
not automated evidence that build/install/live acceptance has passed.

Only `POST /control/guarded-action` may mutate game state. Each request carries
the observed world generation, player UUID, selected target UUID, crosshair UUID
and a server-receipt TTL capped at 150 ms and local remaining freshness/session
time. The exact snapshot is consumed before sending, even if delivery is
uncertain, preventing an automatic replay. Every response identity is checked.
There are no retries and no legacy input fallbacks.

The transport accepts only fixed read routes and the strict guarded schema. It
uses numeric loopback IPs, no environment proxies, no redirects, bounded JSON,
socket timeouts and a total request watchdog. `ConnectionConfig.from_file` reads
only a caller-selected, user-owned 0600 file. There is no credential discovery,
automatic credential creation or reading of Minecraft's token file.
`config.example.json` contains an empty placeholder, not a credential.

## Acceptance and limits

- **This controller has not passed live automatic-combat acceptance**
- Keep it disabled until the companion guard passes full build/review, isolated
  installation and its local negative/positive endpoint acceptance gates
- The guard is limited to an unpublished integrated local Survival world with
  one player. No multiplayer acceptance or support is claimed
- The game-thread guard validates current generation/player/target/crosshair,
  ordinary range/LOS, local-world readiness and request expiry at execution
- TTL starts at server receipt, not the controller clock. Delayed packets and
  already-started synchronous actions cannot be undone by socket cancellation
- A blocking game/mod callback is not safely preemptible; there is no hard
  real-time completion or exactly-once delivery guarantee. Ambiguity means stop
- State has no attack-cooldown or enchantment field. Fixed cadence is a fallback;
  the guard checks the actual axe's enchantment/sweep behavior on the game thread
- Entity lists are not line-of-sight-filtered. A matching fresh crosshair plus
  the guarded live LOS/reach check is required before an attack attempt
- Terrain checks cover a tiny stationary area, not every status effect,
  projectile, fire state or arbitrary mod interaction
- The observation heartbeat is not a server-side held-input lease. Guarded
  actions create no held input; unrelated pre-existing input is not auto-released
- Stopping cannot guarantee survival. Movement/pathfinding/retreat need separate
  terrain-aware implementation and acceptance

See [guarded integration and acceptance](docs/GUARDED_ACCEPTANCE.md) and
[protocol evidence](docs/PROTOCOL.md).

## Verification and provenance

Current snapshot: **115 unit tests passed**, including fake state, fake
transport, mocked HTTP, temporary dummy configs and the deadline watchdog.
Default-disabled/offline-demo runs and Python compilation also passed. No live
endpoint was contacted by this work.

The original published stage-one snapshot had 90 tests and hard read-only HTTP;
this subsequent revision adds guarded-schema integration, not a live success claim.

Python code here is original project code. Upstream Bridge was consulted for
protocol compatibility; its Java implementation was not copied into this directory.
No license grant has been selected for this original controller. Preserve the
upstream license for any separately redistributed upstream code.
