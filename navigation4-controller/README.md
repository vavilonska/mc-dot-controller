# Explicit finite navigation v4 — offline candidate, not a planner

Profile `recovery_navigation_v4` uses the existing `/control/recovery-interaction/v3/` endpoints with explicit v4 request/response profile. New native runtime flag selects v4; no fallback to older gameplay profiles. Only `move` and `look` are valid new requests. All historical short-input/v1/v2/v3 records retain original readers, request/digest bytes and stored-profile status/stop routes. Same owner/journal/ID namespace,256 count ceiling,8MiB ceiling, pre-intent size/reply reserves, atomic/fsync fence and sticky UNKNOWN apply. Restart/pending uncertainty never authorizes a replacement ID or owner.

CLI: `PYTHONPATH=navigation4-controller python -m navigation4_controller --ledger ... --endpoint ... --plan ... --plan-sha256 ... move --id UUID --stage stage-id --samples 1 --accept-normal-gameplay-risk`. `look` takes the reviewed stage direction, not arbitrary CLI angles. New action TTL100..2000ms, default1000; move samples1..8 and jump only the first input sample. Each invocation is one intent, not an automatic next-stage or retry loop. Existing credential selection is env-name or hidden prompt; no credential/ledger initialization. `report/status/stop` do not need a current PLAN. Exact stop is cancellation only, never outcome certainty or replay permission.

## Navigation PLAN2

Read-only local owner-regular/non-symlink file,≤16KiB, explicit raw SHA256, duplicate/nonfinite JSON rejected. Closed shape:

```
{version:2, kind:"navigation",
 context:{session,world_generation,player_uuid,owner_id},
 stages:[{id,source_bounds:{min_x,min_y,min_z,max_x,max_y,max_z},
          target:{x,y,z},yaw,pitch,forward,strafe,jump_first,
          max_samples,max_moves,max_looks}]}
```

All four current native identities bind the immutable raw/parsed/hash PLAN proof.1..16 reviewed stages; finite ordered source bounds (XZ span≤8,Y span≤2), fractional feet heights supported. Source XZ bounds contain the whole current footprint; source Y bounds contain current feet. Target is a real landing feet center, not a spare safe point. Stage IDs are unique ASCII1..64. Samples1..8; moves1..8 per stage, **jump stages exactly one move attempt**; looks0..2. Every existing same-PLAN/same-stage intent consumes its kind budget, including knownzero. Stage identity is in native request/digest/status/persistence. Switching PLAN cannot clear any global UNKNOWN lock. Changing a PLAN requires new explicit review, not an automatic jump retry.

LOOK must equal the stage yaw/pitch and stay within90 degrees per axis from current view. MOVE input must equal reviewed forward/strafe/jump; current heading within0.1 degree. Direction points toward target with at most0.1 block perpendicular target offset. This supports strafe-only jump without forcing camera turns. Native step height is observed; ordinary upward step is capped at min(actual step_height,0.6), with only numeric epsilon. Target absolute feet-height difference≤1. Finite local horizontal distance≤3 is further constrained by available fresh cells; no distant target can borrow authority from a cold map.

## Actual local geometry, not block-name inference

V4 observation adds actual `step_height`, `sprinting`, `collision_boxes_complete`; each of150 local cells adds `collision_boxes` (≤16 local-coordinate six-number AABBs,≤512 total, finite[-16,16],ordered). Empty shape `[]` is different from unknown `null`. Normal collision flag must equal nonempty shape. Unloaded fields are null; a failed loaded shape can have known id/fluid but null collision/boxes. Missing shape/metadata requires complete=false and ready=false; no-world step/sprint are null. Existing64KiB raw/encoded transport ceiling remains, regardless of theoretical maximum box count.

Current grounded low-velocity, currently-not-sprinting bbox must match the actual pose and not intersect sampled solids. It needs **some actual same-height support contact**, with the rest of its footprint supported downward within1 block: valid bed seams/chest edges are not falsely treated as fully unsupported. Target bbox uses the actual current dimensions translated to the target, requires its entire foot rectangle covered by the union of same-height actual collision top faces (middle holes rejected), and body/head not embedded. Required source/target/projected local cells must be loaded, geometry-known, dry and not TNT. Only the necessary local projection/drop support is checked, not every terrain class or future world state. Immediate nearby living overlap/truncated evidence rejects; other nearby entities are advisory count, not a global immunity claim.

This is **not** an ideal collision-free jump-arc proof. Low-ceiling contact, incomplete displacement or not reaching target remain known tactical/gameplay outcomes if protocol release is known. Native controls do not teleport, set velocity, break blocks, open inventory or attack. Future damage/death remains ordinary gameplay risk. No material-specific new Java authority is introduced; fractional bed/chest support comes from actual shape geometry.

Native SETTLED proves input/call authority invalidated and release, not landing, zero velocity, target arrival or safety. `local_risk.arrival=not_assessed`; CLI labels protocol completion separately and marks zero/partial/unknown non-success. Subsequent stage admission needs a fresh observed stable source and a separately authorized invocation. Native v3 refusal diagnostic integrity rules remain unchanged.

## Offline evidence

Tests use temporary clones of authorized actual101 history and original owner. Synthetic future stages/observations are not live observations. Real Java codec/FileStore fixture bytes are read unchanged and request/digest/receipt/raw-evidence paths checked. Cold NBT-derived shape reconstructions are explicitly synthetic, not current world authority. Unknown, same-ID mismatch, stage budget, PLAN/hash/context, pre-POST fsync, byte/count capacity and old-record immutability are checked. No game HTTP, credentials, deployment or live navigation was performed. Data templates with null context remain intentionally unexecutable pending fresh TEST context and reviewed raw hash.

### Offline evidence boundary
`tests/wire-final-r3` and `tests/observations` preserve the native final-r3
production-codec bytes. The cold geometry inputs are explicitly synthetic models
of exported block states, not live native world captures. Route tests change only
an in-memory synthetic heading/context, never the preserved bytes. The first
seven route source windows pass local admission; the final two southbound source
windows use explicitly separate Python cold-state models, not native codec bytes.
All nine policy replays remain synthetic, not actual movement qualification. The 82,777-byte extreme
fixture is a negative serializer-budget case, not an emitted HTTP response.
`tests/capacity_projection.py` estimates actual 101 historical records plus the
65-stage-budget records with three ordinary receipts each; this is only a byte
projection. Larger receipts or polling histories can exhaust the unchanged 8MiB
limit before the 256-record count ceiling. Production admission reserves cleanup
space before creating any new PENDING intent.
