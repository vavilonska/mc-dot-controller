# Route default-stop v2 Bee evidence

The v1 route-stop profile and wire remain supported unchanged. A caller must explicitly negotiate `movement-local-segment-spatial-stop-v2`; the corresponding entity policy is `route-spatial-stop-v2`, entity frame schema is 2, scope is `all-client-loaded-route-swept-and-far-passives-and-calm-bees`, and response-size diagnostic schema is 8.

The new profile permits exactly one additional type: exact vanilla Bee/class plus EntityType.BEE. It retains v1 row geometry and `outside_context` verdict and adds `native_living`. That object is the existing closed native-living schema-1 object with both `bee` and a route-only `bee_route` extension:

- `bee`: `angry`, `remaining_anger_ticks`, `persistent_anger_target_uuid`
- `bee_route`: `schema_version: 1`, `server_class: net.minecraft.world.entity.animal.Bee`, `has_stung`, `has_nectar`, `hive_pos`, `flower_pos`
- Positions are explicit null or an exact x/y/z integer object. All nullable targets and positions are retained by genuine action serializers.

Acceptance requires complete current server facts bound to the row UUID/id/type and witness player/world/dimension; known source/reason/current-target coverage; alive, not aggressive, null current target; not angry, zero anger, null persistent anger target; not stung; source age no more than 250 ms and tick skew no more than five. Nectar and destination changes between callbacks are permitted after fresh revalidation. The whole finite projected client body must be strictly outside the context prism. The source remains bounded to its existing 128-block/256-row/4,096-inspection coverage.

A batch is pinned only for one callback. Its final no-hook boundary permits a replacement publication only after an atomic immutable-value check proves the same context/server-level/dimension, complete bounded coverage, matching Bee identity and all semantic fields, with only monotonic fresh source clocks allowed to advance. The original witness and its age limits remain unchanged. Each subsequent callback captures new authority. See `BEE-BATCH-EQUIVALENCE-CONTRACT.md`. Missing, partial, stale, future, class/type-mismatched, angry, stung, targeted or overlapping bees refuse. The final action remains ordinary default-stop, with no combat escalation or retry. Late-motion failure keeps the existing unknown outcome.

Bounded entity diagnostics retain schema 1 when no Bee detail is attached; the closed optional Bee detail uses outer schema 2, as specified in `BEE-REFUSAL-DIAGNOSTIC-CONTRACT.md`. Both bind the requested v2 profile/policy. Added codes are `route_bee_native_unconfirmed`, `route_bee_native_stale`, `route_bee_not_calm` and `route_bee_native_context_changed`. Terrain diagnostics retain `local-segment-terrain-equivalence-v1` and bind the requested route profile.

Validation is in `client-mod/validation/route-stop` (production controller/readers and genuine full-production serializers), and `client-mod/validation/route-bee` (pinned bytecode audit). These are offline tests with explicit synthetic engine inputs, not a live world or physics acceptance claim. See the mechanics audit for lifecycle and coverage limitations.
