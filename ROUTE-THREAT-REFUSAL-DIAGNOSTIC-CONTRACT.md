# Route-threat admission refusal diagnostics

This change adds optional bounded explanatory facts to an already-refused HTTP
409 response for `movement-local-segment-spatial-threat-v1`. It does not change
which action is admitted, any freshness/coverage/owner/effect gate, a stop proof,
an action's known/unknown semantics, cleanup authority, or replay permission.

## Native contract

`route_threat_rejection` schema 1 uses the existing profile and policy and has
exactly `schema_version`, `profile`, `policy`, `rejection_code`, `phase`, `entity`,
`context`, `native`, and `source`. Its complete compact UTF-8 JSON is at most
4096 bytes. The native serializer preserves explicit nullable fields only for
this top-level diagnostic contract. Unrelated existing JSON retains its encoding.

Only these existing row-specific failures carry this diagnostic:

- `route_spatial_native_target_unconfirmed`
- `route_spatial_native_target_stale`
- `route_spatial_clock_invalid`
- `route_spatial_targetless_aggression_unknown`
- `route_spatial_target_unknown`
- `route_spatial_other_target_unknown`

The policy wraps only an already-failed check, retaining its reason and exact row.
The native reader labels `capture`, same-batch `recheck`, or `final_fence`.
These labels identify the reader phase, not admission versus later action lifecycle.
The HTTP error is still the original 409. Other refusals retain their prior shape.

The diagnostic binds the actual row ID/UUID/type, whether it is the selected row,
selected target UUID, player UUID, world generation, dimension, and original frame
clocks. It copies allowlisted native-source reason, coverage, inspected count,
liveness/target-known flags, and clocks that actually exist in the rejected JSON.
Unknown source JSON omits sample/source clocks; diagnostic values remain null.
No later time is relabeled as that missing sample time.

`source` separately describes the exact immutable captured server batch and row,
including row-presence/identity checks and original source row clocks. It never
fetches a replacement batch, retries capture, or weakens a stale witness. At the
final freshness fence, `context.final_check_nano` records the already-sampled `now`
used by the failed predicate. It is null in the other phases. No extra clock or
live game-reader call is introduced to produce the diagnostic.

Optional diagnostic encoding failure omits only the diagnostic. It cannot replace
the original rejection. Raw exception text, complete entity lists, world geometry,
inventory, authentication/configuration data, and request bodies are not included.

## Consumer contract

The Resident accepts this field only on HTTP 409 POST `/control/scoped-action`,
with the same profile, original error code, and exact request dimension/world/
player/selected target binding. Validation is closed-schema, bounded, numeric-type
strict, and rejects impossible presence combinations. Accepted facts are deep-copied
into `action_admission` and preserved through Watchdog/public evidence. They do not
serve as a successful action witness, typed stop proof, or permission to defend.

Absent or invalid diagnostics cannot turn a known HTTP refusal into an uncertain
submission. If deeply nested invalid JSON prevents recovering even the machine
error code, the already-observed HTTP status is retained with `bridge_http_409`;
no request is retried. HTTP 5xx and other uncertain submissions keep their existing
unknown treatment. These facts never authorize automatic replay.

## Evidence limits

T45's original failure had no retained failing row/frame, so this change does not
identify its historical source failure or claim to repair an unproven functional
cause. The previous T43 unknown and T44 failed functional trial remain unchanged.
The continuity r2 recovery/retreat implementation was not reached in T45.

Offline coverage includes actual producer/policy/refusal/HTTP serializer bytes,
production reader/catch/fence methods with explicitly synthetic engine readers,
and unchanged original Java wire bytes through public MCP → Watchdog → Resident.
It does not establish actual game/FML/Mixin operation, live defense success, shield
blocking, source-gap recovery triggering, or the historical T45 failure mechanism.
