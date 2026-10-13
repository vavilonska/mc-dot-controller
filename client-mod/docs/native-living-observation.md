# Native living observations (offline increment; no live acceptance)

`nearby.entities` retains every legacy raw row, ordering, distance and truncation rule. Mob rows now additionally contain `native_living`. It is factual sampled state, never a prediction of harmlessness or permission to move. The existing movement guard's four-block exclusion remains unchanged.

## Authority and bounds

Minecraft 1.21.1 pinned bytecode shows `Bee.getRemainingPersistentAngerTime()` reads synced `DATA_REMAINING_ANGER_TIME`; `NeutralMob.isAngry()` means that value is positive. `Mob.isAggressive()` reads bit 4 of synced `DATA_MOB_FLAGS_ID`. Conversely, `Mob.getTarget()` and `Bee.getPersistentAngerTarget()` read unsynced ordinary fields. False synced flags cannot establish the absence of a target.

The client thread publishes a context token bound to exact integrated-server instance, client-level instance, dimension and player UUID. The server's post-tick callback reads only server-owned entity state in the exact player's current ServerLevel. It operates only in unpublished singleplayer with one player. It reads the existing loaded-entity iterable, never loads chunks, mutates entities, waits, sends packets or acquires input. It inspects at most 4,096 entities and captures at most 256 Mob rows within 128 blocks. Exhaustion or read failure makes coverage incomplete and every row unknown.

Each immutable native row binds entity UUID, ID, registry type, source game tick and monotonic timestamp. The client accepts a row only for the same context/dimension/exact entity identity, age 0–250ms and absolute client/source game-tick skew at most 5. One immutable batch is captured for the entire nearby-entity serialization. Unload, disconnect, server stop, context replacement and private→published transitions invalidate publication. Atomic publication rejects old in-flight reads after invalidation.

Pinned `IntegratedServer.tickServer` bytecode takes the connected-and-paused branch through `tickPaused`, skipping superclass `tickServer`, whose tail fires `ServerTickEvent.Post`. A normal connected pause therefore stops this authoritative capture. Old observations expire after 250ms and must remain unknown; unpausing requires a subsequent fresh server tick before any calm predicate can be considered. Offline tests do not validate a startup/unpause workflow or authorize one.

## Typed schema

`native_living` always has integer `schema_version:1`, boolean `known`, string `source` and `reason`, identity strings `entity_uuid`, `entity_type`, `dimension`, `world_generation`, `player_uuid`, integer `entity_id`, boolean `coverage_complete`, and boolean `current_target_known`.

Only known records expose:

- `source:"integrated_server_tick"`, `reason:"observed"`, `coverage_complete:true`
- Integer `source_tick` and `sample_tick`; decimal-string monotonic `source_nano` and `sample_nano`
- Numeric `sample_age_ms = (sample_nano - source_nano) / 1e6`
- Boolean `alive` and `aggressive`
- `current_target`: explicit JSON null or `{uuid:string, entity_id:int, type:string}` from the actual server `Mob.getTarget()`
- Exact vanilla Bee only: `bee:{angry:boolean, remaining_anger_ticks:int, persistent_anger_target_uuid:null|string}`

`sample_tick`/`sample_nano` describe client serialization, so a server sample published just after the state's capability header may legitimately have a newer source timestamp than that header. Consumers must validate source<=sample, the stated age, game-tick skew and sample/header proximity. `known:false` has `source:"unavailable"` and no authoritative values; absent target is not a known null. Failed coverage includes its reason. Negative anger time is unknown.

A strict currently nonaggressive Bee predicate requires all exact identity/freshness/coverage gates, alive=true, aggressive=false, known null current target, angry=false, remaining_anger_ticks=0, and known null persistent anger UUID. Distance alone is never evidence for this predicate.

## HTTP null boundary

The production `BridgeJson.toJson` encoder preserves these two explicit null members only at `nearby.entities[*].native_living.current_target` and `nearby.entities[*].native_living.bee.persistent_anger_target_uuid`. The private nearby snapshot is exposed only in the root `/control/state` response. Traversal visits direct object rows of that exact array; it preserves order, heterogeneous elements and non-Mob rows without synthesizing metadata. No global `serializeNulls` setting is enabled. Missing unknown fields stay absent, and unrelated nulls retain legacy omission, including null members inside a non-null target object. Existing action, pause and combat nullable contracts are unchanged.

The pre-fix production encoder omitted both null members even when `NativeLivingSnapshot.json` had added them, so object-only tests were insufficient. See [`validation/native-living-wire`](../validation/native-living-wire/README.md) for production-JAR-first Java-to-Python wire evidence and synthetic input boundaries. This boundary correction does not relax the classifier or constitute a successful live case.

## Verification scope

Default tests cover actual HTTP encoding/parsing, exact nullable path/array boundaries and nonmutation, serialization types, missing/stale/identity-changed sources, time boundaries, immutable publication, cap failures, target retention and atomic invalidation. Dedicated genuine NeoForge/FML tests allocate actual vanilla Bee objects and initialize real SynchedEntityData with vanilla definitions, then exercise actual getters/setters and target identity. They do not fabricate a loader, registries, world or AI loop. Neither suite proves live rendering, full event lifecycle in a running world, real animal behavior or acceptance-case success.
