# Bee refusal evidence

This change adds bounded evidence to existing route-v2 bee refusals and repairs one audited vanilla position-reader incompatibility. Geometry, source coverage, freshness, calmness, action ownership, cleanup, uncertainty and replay rules remain unchanged.

When bee-specific captured evidence is available, `route_entity_rejection` uses schema 2 and adds `native_bee_diagnostic`. Schema 1 remains unchanged when this addition is absent. The new payload is limited to the exact route-v2 profile/policy and bee type.

The payload records the exact captured entity identity and available geometry; native snapshot presence, known/unavailable reason, coverage and available source/sample clocks; route extension presence, captured status and closed read-status enum; immutable source batch/context/row matching flags; and the callback's player/world/clock/context-prism/swept-box provenance. Unavailable facts are explicitly null or classified unavailable, never inferred calm or filled from a later observation. Unrecognized reasons remain non-authorizing.

The current rejection code remains the action outcome. Diagnostic evidence cannot promote admission, success, known settlement or a defense handoff. Old consumers may lack the extra diagnostic schema but must still preserve the original safe refusal/uncertainty semantics.

## Original T40 limit

The retained T40 chain proves a policy-phase `route_bee_native_unconfirmed` HTTP 409, not admitted and not uncertain. No positive bee row or underlying source reason was retained. Existing source can reach this refusal through missing/expired/partial native facts, identity/context mismatch, or an omitted route-only extension. A batch may be incomplete because an unrelated row failed or a coverage limit was reached. These are source-proven possibilities, not a proven T40 cause.

The new evidence is intended to make a future refusal diagnosable without guessing bee distance, anger or server coverage from another observation. No original or unknown action is retried.

## Proven producer incompatibility and narrow repair

Pinned vanilla BeePollinateGoal.findNearestBlock allocates an exact BlockPos.MutableBlockPos and returns that same object; canUse stores it directly as savedFlowerPos. The former exact-BlockPos-only reader therefore omitted the route extension for a legitimate vanilla pollination path. This source-proven bug does not establish which branch T40 took.

The repaired owning-server-thread reader permits only exact vanilla BlockPos and exact vanilla BlockPos.MutableBlockPos after auditing their coordinate getters, and immediately copies coordinates into immutable snapshot values. Other subclasses remain unsupported. Later mutation of the original position must not change captured facts. No hive lookup, goal execution or world mutation is added.
