# V6 native finite history capacity — offline gate

Run `python run-offline.py --out <new-results-directory>`. The runner compiles all production Java using the already-pinned local Java 21 / AT classpath, then runs the focused capacity tests, independent predecessor/candidate F481 receipt and digest oracles, and the unchanged short-input / maintenance V5 / survival V6 regression mains. No Minecraft, world, game process, HTTP, deployment, or original journal write is performed.

## Scope

- `CapacityMode.LEGACY`: 256 total entries / 1 MiB; `MAINTENANCE_V5`: 512 / 1 MiB; `SURVIVAL_V6`: 1024 / 2 MiB. Existing boolean constructors remain legacy/V5 selectors; only explicit V6 startup chooses the new mode for both ledger and FileStore.
- Capacity is total retained history including old profiles, not 1024 new V6 entries. No eviction, rotation, digest migration, unknown unlock, or arbitrary byte-fit admission exists. The 1025th distinct ID is refused even if the file would fit.
- The complete native codec is unchanged. Writes reject count or byte overflow before touching the temporary/persisted file; reads enforce the same mode limits. Previously invalid direct FileStore writes that could create an unreadable over-count or oversized file are now rejected; this is not a claim of identical behavior for such invalid calls.
- All request/profile/TTL/lease/fence/cleanup/status methods and native behavior after construction are source-text identical to C6. Two-second / 40-tick tickets and all action TTLs remain untouched.

## Evidence

`RecoveryCapacityV6Checks` exercises 256/512/1024 and N+1 admission/read/write, exact inclusive 1/2 MiB and +1 byte, old boolean constructors, preserved journal/no temporary file on rejected writes, 481 actual old receipts/digests and binary roundtrip, 543 synthetic appends to reach 1024 with exact retained 481-entry prefix, old-profile UNKNOWN retrieval/global lock/no replay, duplicate at capacity, per-sample durable fence at 1024, and exact physical cleanup after injected oversized persistence failure. Oversized diagnostic strings used to force a byte failure are explicitly synthetic, not a production request route.

`RecoveryCapacityLegacyOracle` is independently compiled against frozen C6 and candidate C7. Full F481 binary, receipt JSON lines, and request-digest lines must compare byte-identically. The original F481 input is pinned before and after at `ff0a3b42b6485fd70d876c11348d144321b3e845a55e46efc58551b131ab998a`; only output-directory copies are opened by FileStore.

The complete native serialization and durable TEMP-file persistence benchmark includes `force(true)`, atomic rename, and parent-directory force. It measures short V6 moves and a conservative supported-record shape using maximum bounded identity/placement fields, 128-character synthetic reason/gameplay strings, and full lease-refusal metadata. It is not a live game/client latency measurement or a guaranteed maximum runtime pause. Retained history with pathological oversized metadata may hit the byte bound before the count bound and fails closed.

## Result selection

Use `results/native-capacity/run-r2/result.json` and `FINAL-NATIVE-CAPACITY-HANDOFF.json`. Run r1 is retained as audit evidence: the capacity test passed, but the newly written independent oracle lacked its test-only ledger injection; the oracle fixture was corrected and the entire focused runner rerun successfully as r2. No production fix was needed for that harness error. No unrelated engine, live loader/game, or deployment suite was run.
