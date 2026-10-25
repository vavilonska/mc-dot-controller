# Explicit recovery maintenance v5 (offline qualification)

This independent stdlib controller submits only `recovery_maintenance_v5` at the
existing `/control/recovery-interaction/v3/` route. Historical short/v1/v2/v3/v4
requests retain their original readers, payloads, digests, terminal receipts,
owner and evidence. History is shared: no new owner, empty ledger, ID namespace,
UNKNOWN reset, profile restart, implicit action retry or alternate-ID retry.
Old source directories are not modified.

## Finite actions and PLAN
- `move`: original 1–8 input samples, optional first-sample jump; navigation
  geometry and finite stage admission delegate to frozen v4 rules.
- `look`: one absolute finite yaw/pitch pair, each delta at most 90°.
- `select_hotbar`: only slot 2 stone pickaxe or slot 3 andesite, observed exact
  stack fingerprint. No inventory transfer, crafting or arbitrary slot action.
- `break_block`: one exact current-ray target/face, matching full tool stack;
  cut/chiseled sandstone up to 32 native calls, **stable TNT exactly one call**.
  Current footing cannot be broken. TNT must currently be stable, unpowered and
  without adjacent fire/lava; missing current six-neighbor facts refuses.
- `place_block`: exactly one `MAIN_HAND` vanilla use call with slot 3 andesite,
  exact known air destination and adjacent static anchor/face/actual hit point.
  Anchors: stone, sandstone, cut/chiseled sandstone, andesite. No block entities,
  placement of TNT, igniters, attacks, batch, held use or direct world mutation.

PLAN is read-only owner-regular/no-symlink JSON, at most 16KiB, exact supplied SHA256,
closed keys, duplicate/nonfinite rejection, version 3/kind `maintenance`, and exact
session/world/player/owner context. It contains at most 16 navigation stages and
16 worksites. Navigation uses the frozen v4 stage fields. Each worksite has:
`id`, `source_bounds`, `max_looks` (0–64), `max_selects` (0–16), `break_targets`,
`restore_targets`. Break entries are `x/y/z/face/block_id/max_calls`. Restore entries
are `x/y/z/anchor_x/anchor_y/anchor_z/anchor_block_id/face/hit_x/hit_y/hit_z/item_id`.
Global catalogues are at most 9 TNT, 13 service blocks and 13 restorations; duplicate
operation targets are rejected. PLAN values are an exact reviewed allowlist, not
a command to perform all operations.

Every request binds `plan_version=3`, `plan_sha256` and `stage_id` in its digest.
Each break/place target consumes one intent **across PLANs in the same native
session/world/player context**, including known zero effects. Jump stages similarly
cannot be renewed by changing PLAN hash. Ordinary navigation move/look and worksite look/select budgets also accumulate
by native context/stage/kind across PLANs; derived alignment data cannot reset them.
A new formal world/context does not inherit a TEST skip. PLAN templates with unbound
context are deliberately non-executable. Candidate hit and actual request hit may
vary by at most `1e-4` per axis; the full actual hit doubles remain digest-bound.

## Evidence and ordinary risks
V5 retains the 150-cell actual shape observation and adds only:
- `eye_position`: actual native eye XYZ, not a fixed assumed 1.62 offset; unavailable
  eye means no ready ticket. Operators calculate look from fresh eye, then obtain
  another fresh actual ray before a break/place request.
- `ray_target_witness`: the current actual-ray block's state and current TNT facts,
  not an arbitrary coordinate scan. It may cover a reachable target outside 150.
- `latest_target_witness`: the most recent original v5 break/place target's current
  state in the same native context, keyed by original action ID.
- `local_primed_tnt`: bounded current ±8 AABB count/completeness/overflow. Planned
  construction stops if nonzero/incomplete/overflow, without changing a known
  protocol fact or blocking original-ID status/stop. This is not a future guarantee.

Incomplete captures preserve nullable/partial facts; they do not pretend to prove
state. Existing intact cover over buried stable TNT is an approved task premise,
not a reason to reject all 150 cells. Immediate body/support/nearby hazards are
checked locally. Ordinary collision, damage, death, unfinished mining and failed
placement are gameplay outcomes, not automatically protocol UNKNOWN.

`assessment.assess_target(record, observation)` is pure: it requires a later frame,
original context/action/position, expected air/andesite, current local primed-clear
and no unexpected changes in overlapping sampled terrain. It reports protocol and
current facts separately, does not mutate the ledger or clear UNKNOWN, and cannot
prove global terrain stability, physical settlement or future explosion absence.

## Ownership, capacity and timing
Only this new v5 controller uses an independent 24MiB Ledger subclass and 512-record
count ceiling. Frozen old controllers keep their original 8MiB/128 or 256 limits;
there is no monkeypatch or history truncation. Each new intent checks the entire
request/observation/PLAN plus existing cleanup/status reserve before adding PENDING,
then performs the original atomic write/fsync before any POST. Response size remains
64KiB. Count ceilings are not promises that all records/evidence fit. Once shared
history exceeds old byte limits, use this successor's original-profile routing,
not the older executable to open that larger ledger.

Raw action receipts remain durable original bytes (without auth headers). Lost
response, uncertain dispatch and restart PENDING become persistent UNKNOWN. Stop
is only exact original-ID release/cancellation, not effect retry or outcome proof.
PASS/FAIL/CONSUME from vanilla placement still represents one entered call, not
permission to treat it as zero effect and retry.

The explicit v5 observation ticket is 2000ms/40 native ticks, based on measured
large-history pre-dispatch persistence cost. Older profiles retain their own lease
semantics. Action TTL remains absolute from native submit (normally 1000ms for
look and 2000ms for break), never renewed. Large-ledger encode/fsync
can consume much of the ticket; offline latency measurements are environment-specific
and do not promise live admission. Preserved timing reports compare against the
then-current 1000ms ticket; they are not relabelled as new measurements. Stale known-zero actions stop; no automatic retry.

## Interface
`Controller(existing_directory, transport, plan=load_plan(path, expected_sha256))`
provides `observe`, `start`, `finish_one_step`, `report`, `status`, `stop` as before.
The module CLI handles one exact JSON request (`start --request FILE`) and then
bounded original-ID reads, never an automatic route. It reads only an existing token
from an explicitly selected environment variable or hidden prompt; never argv/token
file creation or credential persistence. For effect requests the file's original
PLAN/context remains pinned and current observation identity is refreshed; the
production gate rechecks context, stack, current ray, bounds and all intent limits.
`report/status/stop` do not require the current PLAN.

Tests use original101 safe fixtures, synthetic scenarios, actual production-codec
fixture bytes and temporary files only. No live game calls, deployment, credentials
or operator scripts are used. Capacity reports distinguish route-model bytes from
accepted maximum-geometry stress; neither is a claim of executed gameplay.
