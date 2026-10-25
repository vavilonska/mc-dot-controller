# C8 native finite history — exact 4096 / 4 MiB offline gate

Run `python run-offline.py --out <new-results-directory> --future-jsonl <pinned-future-jsonl>`. The runner compiles all production Java with the existing local Java 21 / AT classpath and executes focused standalone Java tests. It never starts Minecraft, touches a real world/runtime journal, issues game HTTP, or deploys an artifact. FileStore opens only copied or synthetic output files.

## Minimal production change

Exactly one Java file changes from frozen C7: `RecoveryShortInputLedger.java` has two literal changes:

- `SURVIVAL_MAX_HISTORY`: 1024 → 4096.
- `CapacityMode.SURVIVAL_V6.maxFileBytes`: 2,097,152 → 4,194,304.

Reversing those two replacements restores the entire C7 source byte-for-byte. No method, codec, request/profile schema, owner/generation rule, same-ID handling, global UNKNOWN rule, one-active rule, TTL, two-second/40-tick ticket, per-sample durable fence, cleanup, status or native startup code changes. Legacy and V5 remain 256 / 512 entries and 1 MiB. The preexisting explicit V6 mode selection passes the same mode to the ledger and FileStore.

The complete native encoder already checks `bytes.size() > maxFileBytes` before creating or replacing the temporary/persisted file. Reads use that same bound. Exactly 4 MiB is allowed; +1 is rejected before replacement. The count cap remains independent: record 4097 is refused even if bytes would fit. These are total retained-record limits, not 4096 additional entries, and not a guarantee that every possible 4096-record history fits 4 MiB. Byte saturation can fail closed before count saturation; no history is discarded or migrated to make room.

## Focused evidence

- Actual F996 native input (996 settled entries), SHA256 `ecf7ef54ca895c7b17a665ce0c572fcc7ac9eb1c123591f42de107067e16cfc6`, is hashed before/after and opened only as copies. Full binary roundtrip, all 996 complete production receipts and request digests match independently compiled frozen C7 and C8 oracles exactly.
- Actual F996 + 3100 synthetic future requests reaches exactly 4096 records and 1,779,293 complete native bytes. Future input SHA256 `a84e919a55f414640c19ffcbc9f274a20996f230b4c6f7867410414c4902135a` contains generations 997–4096 only, not the original prefix. It was produced through public schema/PLAN/gate checks and is re-parsed through the real native closed-schema codec with canonical UUID / owner / contiguous generation checks. Synthetic settled/no-effect records do not claim those actions occurred. The original 996-record prefix is re-encoded byte-identically after filling history.
- Exact 4096th durable admission, 4097th refusal, direct count-overflow read/write, independent exact 4 MiB and +1-byte read/write, no tmp/replacement on overflow, old boolean/explicit 256/512 and 1 MiB bounds, truncated header/record, trailing bytes, bad magic/tag/state and negative count are checked.
- All original status retrieval / same-ID duplicates remain available. Different payloads are rejected. Old-profile unfinished tickets become global UNKNOWN, remain queryable and duplicate-readable, block new V6 actions, and remain locked across restart. Owner/generation checks remain active.
- At full 4096 history, eight samples each inspect the real persisted fence before a synthetic raw-write callback. Same-tick duplicate effects are refused and normal cleanup persists. An injected oversized metadata write prevents the next effect and preserves global UNKNOWN while exact physical release still runs; the previous durable unfinished journal remains recoverable and locked on restart.
- Original short-input, V5 and V6 checks run unchanged, including TTL / claim / release behavior. Source equality additionally protects all unchanged methods.

The 60,000-character reason strings used to force exact byte boundaries or failures are deliberately synthetic native storage stress, not public-approved action payloads. This gate makes no live-client latency, real interaction, loader or deployment claim. It does not repeat unrelated engine suites or the prior candidate-comparison benchmark.

## Packaging and downgrade boundary

The frozen run fully compiles 254 production sources to 582 classes. Compared with C7, only `RecoveryShortInputLedger.class` and `RecoveryShortInputLedger$CapacityMode.class` change; all other 580 classes are identical and none is added/removed. Source resources remain unchanged. The coordinator separately assigns/binds the explicit C8 artifact version and packaging metadata; these are not Java protocol changes.

C7 supports only its old 1024-record / 2 MiB bounds. A C8 history over either bound cannot be read by that older mode. Never delete, truncate, prune, re-ID, or unlock history to force a downgrade. A compatible old artifact alone is not evidence that a newer history is downgrade-compatible.

Use `results/native-capacity4096/FINAL-NATIVE-CAPACITY4096-HANDOFF.json` and its bound `run-r1/result.json`. No deployment is performed by this gate.
