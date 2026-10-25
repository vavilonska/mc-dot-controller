# Explicit survival v6 public controller (offline candidate)

Only this new directory changes. Existing controllers remain byte-preserved.

```python
from survival6_controller import Controller, load_plan
plan = load_plan(reviewed_local_path, expected_sha256)
controller = Controller(existing_ledger_directory, existing_transport, plan=plan)
```

No credentials, network client, game process, owner or empty ledger is created by
this module. Caller supplies the existing transport and ledger. Original admission,
atomic PENDING/fsync fence, response64KiB and 393216-byte cleanup reserve
remain. This V6 runtime alone admits at most 4096 total retained actions and uses
a 128MiB public ledger subclass; older controllers retain their 24MiB/512 limits.
The count ceiling applies to new start admission and V6 load/save; an overbound
ledger is refused without rewriting or pruning any existing record. Byte+reserve admission is independent of count, so
1024 is not a guarantee that arbitrary bounded histories fit. Two-second ticket and absolute action deadlines are native facts,
not extended by polling. Ordinary damage or no damage/food success does not itself
make protocol UNKNOWN; unresolved dispatch/release still does. UNKNOWN never retries.

## Plans and new authority

Closed PLAN4 root keys: `version`, `kind:"survival"`, four-field `context`,
`navigation`, `survival`. Each array has at most16 stages; at least one is nonempty.
Stage IDs are unique across both arrays. Navigation uses original bounded v4
stage/actual collision-shape rules, including fractional support and one jump.
No worksites or fake mining/placement targets.

Each survival stage fixes one kind and `max_intents:1`:

- Selection: `{id,kind:"select_hotbar",max_intents:1,slot:1|8}`.
  Slot1 must currently contain bread; slot8 usable iron axe; full stack bound.
- Attack: `{id,kind:"attack_blaze",max_intents:1}`. Request binds actual eligible
  combined-ray entity ID/UUID/exact Blaze type and full selected slot8 iron axe.
  Current attack strength must be1.0. Native independently rechecks current ray,
  target, reach and captured control context; old target bbox need not stay still.
- Bread: `{id,kind:"consume_bread",max_intents:1,max_use_ticks:1..40}`. Request
  fixes current selected slot1 bread/full stack and a tick limit no greater than
  the stage. One top-level MAIN_HAND use, at most one item. Only this kind accepts
  action TTL up to4000ms; other kinds remain at most2000ms.

Navigation remains move/look only. Survival has no generic item use, generic entity
attack, block breaking/placement or backpack access. Existing use cannot be adopted.
Alive/context/authority are required; HP20, no hurt/fire and an empty nearby list
are not generic survival requirements. A fully charged strike can still miss or do
no observed damage; one returned use can consume no bread. Returned FAIL is still
one attempted top-level call, not known-zero dispatch.

Same-context stage/kind budgets survive PLAN hash changes, including known-zero.
An entirely new explicitly authorized stage is a new decision, not an automatic
retry or permanent per-UUID ban. New v6 navigation preserves same-context v5/v6
stage history and jump budget; no changing profiles/hashes to discard history.

## Historical proofs and protocol completion

Old profiles use original request/digest/receipt validators. In particular, v5
maintenance and navigation raw PLAN kinds use the original mixed reader, not a
rewritten proof. Same-ID/same-payload calls only report the original record, even
for historical non-survival kinds. Historical status/stop route by stored identity,
without a current PLAN. New effect submission under any old profile is unavailable.
After new v6 records exist, old v5-only Python cannot reopen that mixed ledger;
continue with this reviewed v6 reader or a reviewed successor, never delete records.

Only v6 consume uses `.25s` status polling, original TTL+.5s reporting window,
24 evidence slots and two reserved exact-stop/status slots. Old profiles and every
other kind delegate the original finish implementation. Applied_calls counts the
single top-level use/attack invocation, not held ticks, health damage or eaten
items. ACTIVE/STOPPING/UNKNOWN may legitimately expose a returned result before the
completed-call counter advances; terminal returned result requires count1. Stop
proves release only, not retroactive game-effect certainty. No automatic restart.

PLAN16KiB strict duplicate/nonfinite rejection, full raw/hash/parsed proof and
owner-regular nonsymlink loading are retained. The delivered all-zero-context
example is syntactically valid but not bound to any actual observed session.

## Offline evidence

Run `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v` here.
Tests use exact safe338 history and in-process synthetic observations/receipts.
Durable PENDING is read from a private temp ledger at fake POST entry; no game HTTP.
Native lifecycle guarantees (one vanilla invocation, tick/deadline bound, key
cleanup/repeat suppression) require the separate native tests and actual codec
pairing; Python fake outcomes are not evidence of live mechanics.

V6 observations use the v4 shape DTO plus `survival` and `local_primed_tnt`;
maintenance-only ray-target/latest-target/eye fields are absent. Primed-TNT facts
retain the navigation policy, not a new global no-hazard rule on attack/food.
Incomplete survival facts have explicit null values and cannot grant a ticket.

From the candidate root, additional exact-byte checks are:

```sh
PYTHONDONTWRITEBYTECODE=1 python source/survival6-controller/tests/consume_native_wire.py \
  --wire results/public/native-wire-r4/v6/wire \
  --observations results/public/native-wire-r4/observation-wire
PYTHONDONTWRITEBYTECODE=1 python source/survival6-controller/tests/measure_capacity.py \
  --observation results/public/native-wire-r4/observation-wire/max512-short.json \
  --max-plan-raw
```

The copied r4 fixtures are production-codec output on synthetic inputs, not live
captures. The oversized fixture is deliberately rejected, never an accepted HTTP
body. Earlier r2 DTO bytes and development logs are preserved as historical work,
not final observation-schema evidence. All tests use private temp copies of the
actual338 safe ledger; original runtime files are never opened for writing.

## Same-start persistence optimization (capacity candidate)

The final prospective PENDING ledger is encoded once. Its exact byte length plus
393216 bytes of cleanup reserve must fit before adding the intent in RAM. Those
same immutable bytes are then written, file-fsynced, atomically replaced and
directory-fsynced before POST. A failed write leaves RAM PENDING, never retryable.

Only after successful durability does a short-lived proof permit the inherited
start exchange's first capacity check to avoid another full serialization. It
binds the ledger, save epoch, original action, record identities and new-record
snapshot; it is consumed before transport and cleared on every exit. Every save
attempt invalidates previous proofs. Receipt/raw-evidence saves, status, stop,
UNKNOWN and restart still use the original full-encode persistence path. There
is no cross-call cache, journal or asynchronous persistence. This retains the
original single-cooperating-controller-thread model, not protection against
arbitrary concurrent direct edits to nested `.data`.

Offline verification: `python -m unittest discover -s tests -p 'test*.py'`.
`tests/measure_public_capacity.py` uses unchanged actual481 and explicitly
synthetic realistic complete history records in temporary files with fake HTTP.
No game observation ticket/TTL, response/evidence bound, polling, deduplication,
original-owner or UNKNOWN semantics are changed by these capacity settings.

## C8 capacity-only successor

C8 changes only V6 retained count to 4096, public bytes to 128 MiB and the
count diagnostic. C7 same-start encoding/proof and every durability/uncertainty
rule remain unchanged. Native capacity is independently bounded. Both the count
and actual final-PENDING bytes plus 393216 reserve must fit; 4096 arbitrary
complete records are not guaranteed to fit 128 MiB.

`tests/test_public_capacity.py` now uses the read-only actual996 frozen ledger
for mixed-reader/exact-record/original-ID/known-zero/UNKNOWN regression and
checks 4096/4097 count and the actual 128 MiB final-PENDING reserve boundary.
Previous `measure_public_capacity.py` remains historical C7/actual481 tooling,
not a C8 acceptance or capacity guarantee; the completed external C8 projection
index supplies measurements without rerunning stress comparisons.

Rollback: once retained count exceeds 1024 or public bytes exceed 64 MiB, C7
cannot read the C8 history. Do not prune/reset/rewrite history to force a
downgrade; retain C8 and recover under its complete-history bounds.

Boundary-model qualification: the 4096-count fixture is deliberately storage-
schema-only. The 128 MiB exact/+1 fixture adds explicit test padding to a
previously loaded historical record, then runs real Controller.start and
persistence; it is not a complete typed-history 128 MiB reload/roundtrip claim.
Actual996 separately covers complete mixed-reader validation. The prior
3550/128 MiB refusal projection remains independently recorded in the external
measurement index.
