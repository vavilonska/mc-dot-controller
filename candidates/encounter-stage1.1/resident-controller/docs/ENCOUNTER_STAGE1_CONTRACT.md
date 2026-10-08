# Stage-1 two-zombie retreat contract (offline candidate)

This is an explicit optional mode of the existing single `combat_entity` native
client action. It does not start `combat_start`, loop attack requests, or enable
a runtime feature. Native admission is gated by the boolean JVM system property
`mineclientBridge.encounterRetreatStage1Enabled`; its default is false. A disabled
admission is HTTP 409 `encounter_stage1_disabled`. This candidate does not set it.

## Request

The existing combat target and world/player/action-session identities remain
required. Add both fields:

- `encounter_mode`: exactly `two_zombie_retreat_v1`.
- `encounter_scope`: exactly two closed objects, each containing only `entity_id`,
  `uuid`, and `type`. IDs are nonnegative native 32-bit integers; UUIDs are
  lowercase canonical strings; type is exactly `minecraft:zombie`.
- Both IDs and both UUIDs must be distinct. One entire identity must match
  `target_entity_id`, `target_uuid`, and `target_type`; that target is a zombie.
- `approach:false` and `shield:false` must be explicit. `hotbar_slot`, `jump`,
  `sneak`, and `sprint` are forbidden, including false or null values.
- Existing optional paired `expected_navigation_epoch` / `expected_origin` are
  accepted. `timeout_ms` remains 50–30000; the resident/native default is 15000.
  The MCP wrapper still requires its existing explicit timeout and action ID.

Scope without mode, unknown mode, invalid identity types, unknown request fields,
and mode on a different operation fail closed. Resident validation runs before
command-side bridge reads or input takeover, in the semantic recipe, and again
before native dispatch. Resident-owned per-request action IDs remain unchanged.

Legacy requests with neither field retain their prior validation and behavior.
Nothing infers this mode from a second zombie or silently opts old callers in.

## Receipt

For this mode, the resident binds every running or terminal receipt to the same
native action ID/session/type/launch world and exact originally submitted scope
in the same order. It validates `result.combat.encounter`:

- `encounter_schema_version:1`, exact mode/scope, `offense_disabled:true`.
- `risk_remaining:true`, `requires_handoff:true`, `safety_assured:false` at every
  stage, including limited observed-clearance completion.
- `danger_radius:8`, integer `clearance_observations` from 0 to 3.
- `outcome_scope:null` while running or failed/cancelled.
- Terminal `terminal_status` and `terminal_reason` match the outer receipt.

Existing `result.combat` target identities must still match. Its attack dispatch
count remains zero; attack completion, target-dead observation, confirmed hits,
server confirmation, and safety assurance remain false. Existing combat risk
remains true. Outer server confirmation is also false.

A successful native action is accepted only for
`reason:encounter_clearance_observed`, confirmed input release, a consecutive
native-observed clearance count of 3, and
`outcome_scope:two_scoped_living_zombies_beyond_8_for_3_samples`. Its
`scoped_living_threats` must contain exactly the same ordered two identities,
each with `known:true`, `alive:true`, and finite `clearance > 8`. Clearance is
horizontal center separation minus the observed entity radius. Missing, dead,
unknown, changed or nearby scope cannot substantiate that success. These are
native-client observations, not independently reproduced gameplay evidence.

Even this limited success leaves two living enemies and does not establish
survival, a kill, a safe destination, server acknowledgement, or present/future
safety. Every resident result involving the opt-in fields, including admission
failure or uncertain transport, reports risk remaining and required handoff.

The MCP parser exposes the same closed request schema. Its submit response is
checked against the submitted scope. A separate stateless status/cancel call can
validate the returned encounter's internal evidence but has no original request
body to independently compare its scope with; callers must retain that original
request. Session/action ID checks still apply. A malformed POST response or lost
POST is reported uncertain and never automatically retried with any ID.

## Failure and replay rules

The existing action remains one native POST followed by GET status polls. A
resident transport ambiguity may use its existing one-shot cancellation of that
same ID; this is not replay, a new action, or an additional retreat segment.
Reconciliation requires the full valid encounter receipt. Invalid evidence
cannot be promoted to resolved success. A known 4xx resident rejection is not
retried or cancelled. Terminal native failure discards pending recipes. Consumed
queue requests cannot be resubmitted even after their retained result expires.

## Offline verification

From the source root:

```sh
PYTHONPATH=resident-controller python3 -m unittest discover -s resident-controller/tests -v
node --test client-mod/mcp/client-action-test.mjs client-mod/mcp/encounter-contract-test.mjs
```

The new tests use temporary synthetic mailboxes and in-memory fake bridges. They
cover strict entry, truthful terminal claims, scope changes, missing/dead/near
observations, ambiguity, disabled gate, cancellation, preserved immutable IDs,
and no replay. They do not access a real queue, game, installed mod, transport,
credentials, or UI, and do not demonstrate runtime/gameplay acceptance.
