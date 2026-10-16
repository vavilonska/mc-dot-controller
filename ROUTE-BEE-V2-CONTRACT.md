# Default-stop route bee policy v2

The separately negotiated `movement-local-segment-spatial-stop-v2` profile uses `route-spatial-stop-v2`. Version 1 and explicit defensive, mining, placement and collection profiles retain their original semantics. V2 adds no attack, retry or resume authority.

## Exact bee admission

A live bee must be the exact audited vanilla Bee class and registered bee type. Complete current geometry, velocity and interpolation facts are retained. Its current and projected bounding boxes must be strictly outside the entire terrain-context prism, using the original remaining-action-tick projection. This is a current-facts check, not a guarantee about future flight or acceleration.

An immutable integrated-server batch must identify the same entity and world/player context, be complete, and be no older than 250 ms with at most five ticks of skew. The bee must be alive, nonaggressive, targetless, not angry, with zero remaining anger time, no persistent anger target and no completed sting. Exact server class and sting/nectar/hive/flower facts are retained in a route-only extension. Nectar and destination facts do not themselves authorize movement or attack.

One batch is bound for each callback, including the final context/freshness/publication fence. The next callback captures a new current batch. A publication during a callback invalidates that callback; the action never silently substitutes unvalidated facts.

Missing, stale, partial, inconsistent, stung, angry, targeted or geometrically relevant bee facts refuse. Existing source bounds remain: radius 128, at most 256 rows and 4096 inspected server entities. A rendered bee outside source coverage still refuses. This policy does not promise universal bee support.

## Preserved terrain and ownership boundaries

V2 explicitly inherits the reviewed default-stop terrain equivalence: only audited leaf distance/persistence and exact non-snowy grass/dirt replacement in CONTEXT cells, with fully revalidated physics. Original admission facts remain immutable; same-callback raw identity fences stay strict. Owner replacement, uncertain motion and release failures retain their existing stop/reconciliation behavior.

## Evidence and acceptance

T39's original bounded diagnostic identifies a rejected `minecraft:bee` at type classification before native admission. Its distance, UUID and state were not retained by that diagnostic. The new policy does not retroactively prove those facts or guarantee acceptance of the same scene.

Offline acceptance requires native actual-reader/controller tests, original serializer bytes, independent Python recomputation and public entry tests. Fresh ordinary-world acceptance remains separate.
