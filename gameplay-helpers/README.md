# Gameplay helpers

Original Python standard-library helpers for the sibling `resident-controller`.
This directory contains shaped crafting, small gameplay/path wrappers, and a
private state exporter. The frozen v6 crafting source is built and checked offline,
not live-accepted; publication does not establish installation. Imports do not
create queue clients, observe the game,
write state files, or send actions. Callers explicitly select a client or mailbox.

No license grant has been assigned to this original code. The upstream license
in `client-mod/` does not automatically apply to these independent helpers.
No runtime state, observations, mailbox contents, or credentials are included.

## Setup

Use Python 3.10 or newer. From the repository root, make the two source directories
importable (use the platform-specific path separator on Windows):

```sh
export PYTHONPATH="${PWD}/resident-controller:${PWD}/gameplay-helpers"
```

These helpers reuse the existing resident controller and client-actions API;
they do not start the controller, install a mod, or manage authentication.

## Crafting API

The caller supplies its existing credential-free client when it deliberately
wants to craft. While the watchdog owns the queue, use its `IntentClient` so it
remains the sole resident writer. Make `defense-watchdog` importable alongside
the paths above. This is an API usage example, not an automatic startup script:

```python
from intent_client import IntentClient
from crafting_helper import craft_once, CraftStopped

# The caller supplies the verified private control directory.
client = IntentClient(verified_watchdog_control_directory)
result = craft_once(client, "iron_pickaxe", expected_count=1)
```

Supported recipe names: `wooden_pickaxe`, `stone_pickaxe`, `iron_pickaxe`,
`stone_axe`, `iron_axe`, `iron_sword`, `shield`, `furnace`, `iron_helmet`, `iron_chestplate`, `iron_leggings`,
`iron_boots`, `bucket` (alias `iron_bucket`), `stone_hoe`, `iron_hoe`,
`crafting_table`, `stick`/`sticks`, and `torch`/`torches`. A `minecraft:` prefix is
accepted. Sticks and torches yield four; everything else yields one per call.
Iron armor is four separate deliberately invoked recipes, consuming 24 ingots.
The helper does not equip anything.

The existing active vanilla InventoryMenu permits 2×2 recipes. CraftingMenu
permits 3×3 recipes. All equipment/furnace/bucket recipes require CraftingMenu,
including boots and bucket despite their two-row height. The helper never opens
or closes a screen, places a table, moves the player, or changes connections.

Each call observes the actual menu and full player inventory, checks empty cursor,
grid and output, confirms sufficient ingredients, and verifies live storage
`player_inventory`/`inventory_index` metadata. Canonical vanilla grid slots are
validated with `container_slot` and `active` metadata. Actual observed
`menu_index` values are passed to every click.

Each ingredient is moved with ordinary pickup: pick up the observed source stack,
right-click exactly one item into an empty grid slot, return any remainder to its
source. Every intermediate cursor/grid/storage change is verified. The actual
requested output must appear before one quick_move retrieves it. Success requires
the complete expected inventory delta and empty cursor, grid and output in two
later `observe` results with distinct increasing `state.world.game_time` values.
The immediate output-click snapshot and same-tick repeats do not count. A mismatch
resets the confirmation sequence; missing time fails before the first click and
time regression stops without replay.

The result includes `evidence:client_observed_stable`, `output_action_game_time`
and `stable_game_times`. `server_confirmed` remains false: two stable client
observations are not independent server acknowledgment or protection against a
later rollback. World, dimension and player identity must remain the same.

The published gateway state must include an integer `pending` inbox count.
`base_watchdog.run()` adds it to `Watchdog.status()`; the status method alone is
not the published contract. Missing/invalid `pending` fails with
`session_pending_count_missing_or_invalid_requires_published_gateway_state`,
without a `pending=0` fallback. This preserves the actual v5.1-compatible gateway.

Do not interleave this call with other queue writers or manual inventory actions.
The helper detects observed session/menu/world/player/mapping changes and stops;
the external QueueClient protocol does not provide an atomic multi-click lock.
Unknown menu classes, malformed/incomplete observations, missing ingredients,
interference, failed actions and uncertain results stop immediately. Full storage
can prevent the one output move; that is reported without another quick_move.

`CraftStopped` carries `reason`, `request_id`, `request_ids`, and the last observed
`state`. Preserve those IDs. A pending wait means unknown completion, not failure.
Read the existing request result by its same ID; do not rerun the crafting call or
submit replacement mutations after uncertainty. Inspect the current state before
deciding a fresh authorized step. A stop may leave ingredients on the cursor or
in the grid; no automatic cleanup, dropping, cancellation, takeover or replay is
performed. `wait_timeout` (default 30 s) and `settle_timeout` (default 3 s) only
bound waiting for protocol completion/read-only output observations.

## Gameplay wrappers

`play.py` retains the local breadth-first path search, waypoint generation,
incremental travel, look-at, and inventory helpers. It has no command-line runner.
Configure it with a caller-owned client before using a queue-backed function.
The direct `QueueClient` example below applies only when no watchdog owns the
queue; otherwise supply its `IntentClient`:

```python
from resident_controller.ipc import QueueClient
import play

play.configure(QueueClient(verified_mailbox_directory))
# Queue-backed calls happen only when invoked, for example:
observation = play.obs(radius=8)
```

`path(observation, target)` and `inventory(observation)` operate on supplied data
without a client. `obs`, `go`, `look_at`, `travel`, and `run` use the configured
client. Targets are caller-supplied coordinates; no saved route or live location
is bundled. `go` follows one observed local route; `travel` repeats local legs
that make progress toward its target. These small helpers do not replace the
separate navigation controller or add global planning.

## Private state export

`export_dashboard_state.py` submits only `observe` requests to the explicitly
selected resident mailbox. It writes `state.json` to the selected output directory
using a temporary file and replacement. Its output includes the player's name,
dimension, position, orientation, health, food, inventory slots, armor, and offhand.
This is private runtime data, not a public or anonymized dashboard feed. Keep the
output directory outside this repository and out of public hosting or commits.
The requested observation still uses the queue; it is not an offline file reader.

From the repository root, use your own verified paths:

```sh
python3 gameplay-helpers/export_dashboard_state.py --help
python3 gameplay-helpers/export_dashboard_state.py \
  --queue /path/to/existing-mailbox \
  --output-dir /path/to/private-export --once
```

Both path arguments are required. The CLI resolves the checked-in
`resident-controller` sibling relative to its script, regardless of working
directory. `--once` returns success or failure after one observation/export.
Without it, the exporter runs every 10 seconds, records `state-exporter.pid` in
the output directory, and stops when `stop-state-exporter` exists there. The
parent directory must already exist. A newly created output directory is requested
with owner-only permissions; existing directories keep their current permissions,
so the owner must choose a private destination.

Python callers can use `once(client, output_directory)` with an explicit client
and output directory. Importing the module or using `--help` never contacts a
mailbox or exports a snapshot.

## Verification scope

The supplied development record documents live crafting only for
`crafting_table`, `wooden_pickaxe`, `stone_pickaxe`, `furnace`, `stick`,
`stone_axe`, and `torch`. Iron recipes, iron armor, and shield have offline checks
only; no live verification is claimed for the other recipes. Successful crafting
is client-observed and is not an authoritative server acknowledgment.

These recipe reports predate the v6 stable-result contract and do not establish
v6 live acceptance. Loading the standalone helper needs a fresh process/import;
loading changed resident tasks needs an owner-controlled resident reload. Resolve
existing pending IDs first; restart must never act as a retry.

Publication checks use fake clients and synthetic data only. No game, live queue,
credentials, network, or user interface is exercised by the tests below.

## Offline checks

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=resident-controller:gameplay-helpers \
WATCHDOG_CANDIDATE="$PWD/defense-watchdog" \
  python3 -m unittest discover -s gameplay-helpers/tests -v
```

All 37 staged tests pass: 30 crafting/gateway tests and seven retained portability
checks. They cover menu mapping, recipe shapes, one output retrieval, exact deltas,
repeated/regressed ticks, rollback, identity changes and stop/no-replay behavior.
The real staged watchdog run loop and `IntentClient` are exercised with a fake
resident and temporary files, including actual published `pending` counts.
Portability checks cover explicit client/output paths, imports without queue or
write side effects, and CLI help. These do not expand the live evidence above.
The public source allowlist is `PUBLIC-FILES.txt`.

## Running with the defense watchdog

When the independent v6 watchdog (with its retained v5 gateway label) owns the
resident queue, use its `IntentClient`
with these helpers instead of constructing a second direct queue writer. The
watchdog may defer ordinary tasks while combat is active; pending is not failure
and must not trigger a duplicate submission. Persistent walking is provided by
the separate [route cursor](../navigation-cursor/README.md), which retains pending
IDs, route tails and the mandatory defense-epoch guard.
