# Navigation handoff and optional external-controller proof, revision 3

Base: execution-recovery P0 r3, patch SHA256
`031bc6535a97aa021c82a26f37f7f14d629213ed0bf48cfd25f136f14510d02e`.
This is a separate additive patch. No game, world, credentials, campaign history,
installation, or automatic resume is changed by the source patch.

## Public observation and release

`mdc_observe` and successful `Runtime.finish_job` evidence carry
`navigation_handoff` schema 1. Its `source_request_id`, `source_tick`,
`source_context`, and age identify the actual sample. A successful observation's
handoff report can come from its **later cleanup observation**; its source ID is
therefore intentionally distinct from the original observation's native ID.

- `control_released`: neutral controls, terminal native action, matching external
  idle proof, no known rescue quarantine, and a fresh original sample.
- `ownership_released`: exact original runtime lease release was confirmed.
- `physical_safe`: true/false/null for **sampled player hazards only**, not route,
  terrain, enemy, survival, server acknowledgement, or whole-world safety.
- `mode`: walk/swim/boat/airborne/unknown. Water or boat residual velocity is
  reported separately and does not mean a key remains held.
- `selector`: reconcile original owner, observe controls, wait for exact owner
  release, recover from a hazard, or require a fresh owner admission. It grants no
  execution authority, never resumes work, and requires mode capability
  negotiation before dispatch. This patch does not add public swim/boat jobs.

Stale/reversed timestamps, insufficient air, submersion, fire/lava/powder snow,
falling, critical health, invalid boat seat/water status and missing environment
fields never become an affirmative physical-safe handoff. UNKNOWN release marks
handoff unresolved while preserving the original durable job and request IDs.
The watchdog's actual lease-acquisition/release idle gate also consumes native
external-controller and live `native_fall_rescue_status` fields (schema 1), separately from `native_fall_rescue` capability metadata; advertised rescue without live status fails closed; it does not add a velocity-zero rule.

## Optional Baritone API adapter

`ExternalControllerProof` queries real public API objects by reflection. Native
state exposes its same-callback `external_controller` sample. Supported artifact:
[official API-neoforge 1.11.3](https://github.com/cabaletta/baritone/releases/download/v1.11.3/baritone-api-neoforge-1.11.3.jar),
SHA256 `7f9f40952c49e78388e4e9ceaa6fd91a5b662238e06c997b3de5438177f99d8d`.
The installed standalone variant has obfuscated public interfaces and is detected
as **present**, returning `baritone_api_variant_migration_required`; it is never
mistaken for absence. Use only the API variant in a separately approved test copy,
never both variants. Original saved environments remain unchanged.

The adapter checks exact current Minecraft/player/level objects, one primary
instance, isPathing, current and next path, in-progress planning, retained goal,
all registered active processes, and every forced input. `isPathing=false` alone
is insufficient because a path can be paused. Chat acknowledgements are unused.
The volatile in-progress planner is read before current/next paths, preserving the worker publication order during a plan-completion race. Only immutable class fingerprints are cached; idle results are never cached.
Seven API/implementation fingerprints and twelve concrete process fingerprints pin the supported API release. The public API
omits complete process enumeration, so a narrowly scoped read of the pinned
implementation's unique HashSet process registry detects custom processes too. Unknown/custom concrete classes fail closed before their callbacks can run. Follow's pending predicate and Backfill's enabled setting are treated as busy without invoking their potentially side-effecting isActive methods. InventoryPauser is DEFER only when its pause-request flag is false and no manager command/control remains.
Missing/inaccessible/changed registry or API surfaces fail closed. No private
fields are written. No provider/controller is created. No settings are changed.

Published API references:
- [IPathingBehavior](https://github.com/cabaletta/baritone/blob/v1.11.3/src/api/java/baritone/api/behavior/IPathingBehavior.java)
- [IBaritoneProvider](https://github.com/cabaletta/baritone/blob/v1.11.3/src/api/java/baritone/api/IBaritoneProvider.java)
- [PathingControlManager](https://github.com/cabaletta/baritone/blob/v1.11.3/src/main/java/baritone/utils/PathingControlManager.java)

## Native fencing and merge order

Ordinary ClientActions admission, direct takeover, periodic context/input and
capability dispatch checks and GuardedGame* effects consume fresh external idle
proof. A later unknown/busy controller marks the existing action unknown and
handoff-required; it does not grant a new owner or cancel the external process.
The exact GuardedMovement effect ticket and original deadline are rechecked after
external API callbacks. The external guard also rechecks captured player, level, native owner revision, UI, target, aim, held item and input identity after the query. Guarded effects then recheck the native owner and their exact original effect ticket. ClientActions final admission likewise rechecks original
TTL, owner revision, player and level after the final query.

When merging with native fall rescue / native-admission telemetry:
1. Mark HOOKS_POSSIBLE before external API queries.
2. Query external idle before the final pure fall arbiter/owner checks.
3. Recheck original ticket/deadline/context after queries, without refreshing time.
4. Keep the final fall arbiter check immediately before effect/registration.
5. Never clear the fall quarantine or infer release from physics stillness.

## Boundaries and remaining work

This revision provides live API **observation and admission fencing**, not a
Baritone start/stop public capability. Explicit one-shot asynchronous
cancelEverything, durable public stop identity/reconciliation, single-owner route
start, and API-variant live validation are separate follow-on work. No cancellation
acknowledgement may count as idle; it must be verified by later real API samples.
The existing normal guarded runtime remains the suggested backend. No quest or
long-distance route planner is added. Offline tests do not establish game safety.
