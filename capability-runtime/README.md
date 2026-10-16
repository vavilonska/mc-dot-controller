## Current public integration

The combined public backend allowlists 20 capabilities, including `navigate_route_local`; negotiated availability is authoritative. Explicit `defend_once` is available only with its supported combat profile and original reserves; default remains stop and interrupted jobs never resume. See [quickstart](../docs/TOOLBOX-QUICKSTART.md). Route/reflex combined live acceptance remains pending. Broad source/catalog capabilities below are not automatically enabled runtime capabilities.

# MDC reusable capabilities

This package adds actual guarded execution and reusable bounded skills to the verified diagnostic baseline. It is separate from any prewritten validation scenario. No import, catalog command or test starts Minecraft, a resident process, a connection, a planner service, a backup or an action.

## Implemented layers

1. Reliable execution: exclusive journal owner, fsynced pre-submit request identity and payload digest, exact gateway/resident/native correlation, original freshness and defense epoch, known no-effect handling, unknown-outcome latch, exact-ID read-only reconciliation, two strictly later semantic observations and explicit input-release proof. Complete receipts are fsynced compressed evidence, with hash-verified immutable terminal segments and bounded decompression on restart.
2. Reach/interaction: fresh loaded-terrain path segments, one-block elevation changes and supported stair treads, observed boat mounting/travel/dismounting, native origin/epoch binding, guarded native `interact_block`, actual renderer reach/face/LOS checks, explicit menu/block semantic goal and `close_menu`.
3. Inventory/equipment/consumables: actual menu topology, exact native stack/component snapshot handles, hotbar swaps/selection, armor/offhand equipment, food/potion/milk consumption with observed count and effect evidence.
4. Resource acquisition: observed block selection, safe bounded mining, native correct-tool checks, separately tracked drop entities and actual inventory-gain confirmation. Broken blocks never imply pickup. Recursive inventory-total goals select loaded resources, reserve final and sibling ingredients, craft tools/stations, and return to an observed station before production. Search and mutation budgets are shared across nested helpers.
5. Production: existing recipes plus pinned official1.21.1 building recipes and canonical-grid blaze-powder/Ender-eye recipes; real workstation opening, exact menu clicks, bounded multi-batch output, furnace/blast-furnace/smoker input/fuel/output conservation and collected-output evidence. Partial production stops preserve contents and IDs.
6. Threats/combat: existing bounded native combat and escape planners; guarded single melee/bow actions, observed damage/death, health/hazard/collateral/phase gates. A damage sample is not attribution of all damage to our action.
7. Goal execution/memory: a discoverable concrete skill registry, dependency scheduler, fixed deadlines and action reservations, restart revalidation, loaded-world resource/station/fuel discovery, provenance-bound historical memory. Memories never replace fresh observations.
8. Building: versioned content-hashed explicit blueprints, including stairs, slabs, logs, paired doors, fences, panes, workstations and torches; material/support/access/visible-stand planning, exact vanilla placement prediction and footprint evidence, durable progress, physical fresh local audit-window visits and exact final cell/light/clearance verification.
9. Dimensions/End: actual portal ignition/frame activation and narrowly verified expected-dimension transition; an observation-selected expedition handles crystal towers/cages, physical ascent/bridging/return, perched dragon damage/death, an ordinary gateway pearl, outer-End exploration, shulker/projectile combat, actual shell pickup and shulker-box crafting.

## Explicit boundaries

All new native capabilities require the opt-in guard and a private singleplayer world, current focus, live player, matching world/player/action session and fresh native sample (800 ms and five game ticks at admission). Ordinary baseline actions retain their original policy. New ongoing actions stop on focus/context loss; ordinary tasks also stop on new damage/environmental hazards. Dedicated combat/recovery use their own bounded safeguards.

This is a bounded implementation, not a promise of arbitrary-world completion. Navigation uses freshly observed loaded geometry; unknown cells remain blocked. Production is limited to the explicit audited recipe/fuel vocabulary. Full material bills must fit actual inventory; arbitrary large-blueprint inventory staging is not implemented. The builder needs the caller's exact versioned blueprint and never invents design approval or terrain. Its historical region survey only proposes work; every mutation and final per-cell acceptance uses fresh local evidence.

The End goal starts in an already-entered End with a living dragon and observed ordinary equipment/material prerequisites. It dynamically chooses its targets and stations, reserves returns, and can eat/rest only at verified safe positions. It does not claim universal city discovery, guaranteed drops, elytra flight, a dragon respawn ritual or inaccessible-target excavation. Species-specific combat and mob-drop goals have their own exact equipment, roof, fuse, charge and effect requirements. New failures and unknown outcomes stop the goal. See the module documents for precise prerequisites and remaining unsupported cases.

No live game validation was performed in this development task. Offline tests use synthetic endpoint/menu/world responses and genuine compiled production code; official NeoForge-loader tests separately check platform snapshots and actual vanilla placement-state/door/neighbor semantics in an allocation-only synthetic level; they are not gameplay. All success remains client-observed with `server_confirmed:false`.

## Noncombat acceptance mode

For a case that forbids combat, start the same watchdog with `--execution-policy noncombat` and require it in the capability caller with `Runtime(..., required_execution_policy="noncombat")` or CLI `--require-noncombat`. Do not rely only on a temporary lease: the explicit mode covers startup and the period after release too. Its durable policy pin refuses a later default-mode restart in that control directory. All ordinary defaults remain unchanged. Missing safe footing, actual items, daylight or existing authorized runtime access still blocks the case; the policy does not create those prerequisites.

## Optional actual walking-distance budget

`MovementBudgetRuntime(client, journal_directory, bundle_id=...)` is an explicit
subclass of `Runtime` for the reviewed dry-flat noncombat case. It requires the
existing noncombat watchdog policy and native movement-hook support. Call
`start()` once before all AI actions in the case, use the same instance for every
nested skill and authorized cleanup, then call `finish()` once and `close()`.
The ordinary Runtime defaults are unchanged.

The native 32-block meter counts the actual client self-move polyline throughout
the armed interval, including reversals and coasting between actions. It reserves
2 blocks to stop and does not claim to cap arbitrary external displacement.
Manual input, corrections, knockback or incomplete coverage invalidate acceptance.
Python validates exact immutable native bindings, counters and meter evidence in
terminal receipts, internal semantic samples, surveys and fresh preflights;
it never estimates acceptance distance from sampled coordinates. Native sealing
requires neutral settled inputs, followed by two independent later sealed samples.

`start_command()` and `finish_command()` return copies of their semantic commands
for an outer case ledger. Both actions use the same IntentClient → Watchdog →
QueueClient → Resident route and exact request receipts as every other capability.
`binding` is a frozen identity; `movement_budget` returns a copy of the latest
native meter. A durable pre-attempt marker prevents restart/rearm or a replacement
bundle ID. Unknown outcomes and any non-successful mutation stop further actions,
including finish and cleanup. The Resident's existing correlated cancellation and
operator STOP safety path are unchanged. These fixtures are offline adapter tests,
not evidence of native gameplay acceptance.

## Explicit use

Python 3.10+ and the existing sibling source packages are required. From the repository root, use the applicable platform path separator:

```sh
export PYTHONPATH="$PWD/capability-runtime:$PWD/resident-controller:$PWD/navigation-controller:$PWD/navigation-cursor:$PWD/defense-watchdog:$PWD/gameplay-helpers:$PWD/building-controller:$PWD/external-controller:$PWD/multiagent-coordination"
python3 -m mdc_skills catalog
python3 -m mdc_skills check-goal /path/to/goal.json
```

A goal is a bounded data object with exactly `goal_id`, `skill`, `arguments`, `max_actions`, and `deadline_seconds`. Shape validation does not authorize execution. The operator may explicitly invoke `run-goal --control /verified/existing/watchdog --journal /private/checkpoint --file /authorized/goal.json`. It uses the existing IntentClient and never creates an alternate resident writer, starts a process, changes credentials or connects a server. It runs one goal and exits; it has no automatic retry loop.

For applications, construct `Runtime(existing_client, private_directory)` and call a concrete capability, or use `Scheduler(runtime, default_registry())`. The runtime journal lock must remain open for the whole capability. Reuse this one runtime; do not interleave manual inputs or other capability writers.

A failed semantic postcondition is not authorization to replay a mutation. Unknown pending IDs and interrupted verification remain blocked. `Runtime.reconcile()` reads the original ID only and never claims skill completion. Explicit scheduler resume requires fresh goal revalidation, preserves old deadlines/action reservations, and refuses skills that lack a safe re-entry predicate. Production with partial cursor/grid contents requires a newly reviewed plan.

## Verification

`python3 capability-runtime/run_checks.py` runs the final capability suite, all eight existing Python components and the retained Node suites. It writes evidence outside the source directory and never touches a live mailbox. Native default build and true-loader checks are run separately with the pinned restored development dependencies; see the delivery validation report. Original failures and superseded-test diffs are retained for review.

The MCP server advertises the existing eight native/legacy tools plus four additive
toolbox tools: `mdc_catalog`, `mdc_observe`, `mdc_plan`, and `mdc_job`. A configured
long-lived Python backend uses the actual existing resident/gateway owner chain.
Catalog entries without a negotiated executable binding remain unavailable. See
[toolbox setup and call examples](../docs/TOOLBOX-QUICKSTART.md); the Python owner
stack requires POSIX `fcntl`, and no turnkey native-Windows toolbox runtime is
claimed. Existing authentication and ownership boundaries remain unchanged.

## Longer goals and historical surveys

`Runtime.survey()` returns a distinct historical `Survey`, preserving original first/last/page ticks and capture times. It cannot be passed to `execute()` or `result()`, and it invalidates older preflight observations. A fresh local `observe()` is mandatory afterward. `Runtime.audit_evidence()` verifies archived receipt identity, compressed and uncompressed hashes, sizes, schemas and segment links without dispatching gameplay.

The scheduler accepts up to4MiB of bounded JSON goal arguments, storing larger inputs in content-addressed files rather than repeatedly embedding blueprints in its checkpoint. Action reservations may be explicitly bounded up to32768. Original deadlines and counts survive interruption; imported bytes are checked again before use. Resume predicates are read-only and must supply a new owned, unchanged, fresh observation.

See `docs/VERSIONED-BUILDING.md`, `docs/END-EXPEDITION.md` and the material/combat documents for executable goal details. Final validation counts and independent review belong to the delivery report, not this evolving source README.

## Coherent reads and known rejection evidence

Capability observations use the Resident's strict same-callback native bundle.
For terrain, the original A acquisition time stays authoritative and a complete
new C bundle replaces all status/action/state/screen siblings together. Neither
old state nor a delayed action receives a new source timestamp. The existing
0.8-second Runtime fence and native 800 ms/5-tick admission limits still apply.

A proven local/native no-effect rejection now retains the exact compiled command
hash, backing queue ID and native `action_admission` diagnostics in its result and
journal. Diagnostics explain the rejected boundary; they do not authorize retry.
A missing/unknown outcome still preserves pending uncertainty. Offline timed IPC
fixtures measure synthetic 20 TPS callbacks and delayed rejection, not a live
latency guarantee.

### Blueprint-sized historical building survey

Version3 building and construction preflight now derive the smallest supported centered survey from the explicit blueprint region with its neighbor/support shell, cavity/light acceptance cells, access points, the body/head/up-step sweep above planned walkable blocks, and the current observed player body/support/sweep envelope. A separate state-only sizing read never authorizes a mutation. The survey must retain its actual bounds, full cell inventory, original timing and exact context/navigation epoch/player position. Required collision metadata must be loaded and known. The planner's existing standability, ray and support tests still reject unknown paths; fresh local placement and final per-cell checks are unchanged.

This reduces small-job transport size without promising complete route finding or large-region delivery. Out-of-range jobs stop before survey; in-range large or unusually verbose jobs can still exceed the unchanged 2 MiB queue result cap. There is no larger-scan fallback, sparse terrain synthesis, retry or freshness extension.
