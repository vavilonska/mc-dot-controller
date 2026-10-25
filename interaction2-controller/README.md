# Finite interaction v2 public controller (offline-qualified prototype)

Python stdlib only. Explicit `recovery_interaction_v2` / `/control/recovery-interaction/v2/`, schema version 1. Requires paired **unchanged** sibling `interaction-controller` and `short-input-controller`, the original nonempty ledger, endpoint and owner. No owner initializer, credentials generator, automatic retry, planner or runtime config writer.

## Reviewed PLAN, not arbitrary targeting

`load_plan(path, expected_sha256)` reads an owner-regular local nonsymlink path, ≤16 KiB. Duplicate/nonfinite JSON, unknown keys, unpinned bytes, missing native context and invalid bounds refuse. Closed shape:

```json
{"version":1,"context":{"session":"UUID","world_generation":"UUID","player_uuid":"UUID","owner_id":"UUID"},"targets":[{"pos":{"x":-635,"y":61,"z":16},"face":"SOUTH","block_id":"minecraft:nether_wart_block","feet_y":60,"min_break_y":61}]}
```

The example UUID placeholders are deliberately not executable. Current reviewed task is **only one wart**, not permission for eight blocks. The parser permits 1..8 distinct exact positions, fixed cobblestone/wart materials, canonical faces, integral heights, `min_break_y > feet_y`, `target.y >= min_break_y`. Future changes require a newly reviewed PLAN and explicit raw SHA pin; no source/JAR coordinate rewrite or network config fetch. Parent-owned `source/plans/` supplies the current unbound template and operator context procedure.

`Controller(directory, transport, plan=None)` permits report/status/exact stop without a current PLAN. New effects require a loaded immutable `Plan`, exact session/world/player/owner context, request `plan_version=1` and `plan_sha256`. Raw UTF-8, parsed PLAN and hash are archived in each new durable record before POST. Same ID with changed PLAN/payload refuses. Historical v2 proof is verified without reopening the source file. Old UNKNOWN and PENDING-restart locks survive profile/world/PLAN changes.

CLI global options `--ledger`, `--endpoint`, `--plan`, `--plan-sha256`, `--token-env` precede the subcommand. New effect commands are `move`, `look`, `select_hotbar`, `break_block`, one explicit ID and risk acknowledgment. Exact break CLI coordinates/face must exist in PLAN; material is resolved from PLAN, not arbitrary input. Never pass token value in argv. Use an explicitly selected existing token environment variable or hidden prompt. `report` does not prompt/read credentials. `status`, `stop`, `report` need no PLAN flags.

## Finite control and local risk

Move ≤8 samples, **no jump**; look absolute yaw [-180,180), pitch [-90,90], per-axis change ≤90°; select slot 2 current stone pickaxe; break one actual current ray target/face, ≤32 calls and ≤2000 ms. Tool eligibility uses observed `max_damage - damage >= 1`, while native binds the exact original stack/fingerprint. No damage104..106 or max131 assumption. Normal damage, death and incomplete break remain gameplay risks. A bounded break can finish protocol-known with target unchanged; this is not UNKNOWN and not a successful block removal. Protocol terminal does not prove server settlement, zero velocity or safe gameplay.

One shared global ID/owner/ledger, one in-flight intent. Atomic fsync ledger precedes first potentially effectful POST. Lost response, invalid receipt, uncertain dispatch or restart pending produce persistent UNKNOWN. Original-ID status appends evidence but cannot erase UNKNOWN; exact stop cancels only original authority and is not an effect retry. Bounded polling prefers natural completion, with one exact stop reserved for unresolved completion.

MAX_ACTIONS 256 is only a count ceiling. The original **8 MiB** bound and three bounded response reserves remain. Full proposed observation/request/PLAN proof is included in preflight before adding PENDING. Existing evidence is never pruned. Actual94→synthetic256 shape extrapolation includes profiles, PLAN and max_damage; median fits but p95 with tail reserve and max do not. Admission may refuse before256.

## Offline evidence

From candidate `source/`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=interaction2-controller python -m unittest discover -s interaction2-controller/tests -v
```

Tests use a temporary clone of authorized `results/legacy94-fixtures`, in-memory transport, and controlled ephemeral loopback only. The actual fixture remains untouched. Native wire bytes under `tests/fixtures` originate from `results/native/offline-r2/wire-fixtures` (production parse/digest/serializer); their identities and e×64 PLAN hash are offline harness values, not an operator PLAN. Hotbar formatter fixtures use synthetic inputs. Durable wire test injects those records only inside a temporary transport-reader fixture; it does not claim matching approved PLAN or issue effect POST. Capacity projections are byte-volume models, not runnable future records or live movement evidence. No game test is claimed here.
