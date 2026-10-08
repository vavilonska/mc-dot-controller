# Isolated typed-terrain / retreat-diagnostics candidate

Candidate: `1.1.7-integrated.typed.1`; baseline: `1.1.7-integrated.2`.

This candidate is local and offline only. It is not deployed, and has zero post-optimization live executions. Its scope is budget-result preservation and eliminating the terrain JSON intermediate without weakening loaded terrain, collision, fluid, hazard, threat, or tick-freshness rules.

The 8,000,000 ns planning limit remains fail-closed. Boundary timing cannot interrupt a synchronous Minecraft shape hook or guarantee a hard real-time upper bound. Timing and cache counters are diagnostic evidence, not proof of real-client latency. The previously recorded rejected terrain contains no admissible route among the 16 bounded candidates; performance changes alone cannot establish an escape.

Implementation details and final verification are recorded with the isolated candidate report. The repository's existing historical acceptance notes do not certify this candidate.

## What changed

- `TerrainReader` has a direct typed Cell path. Its JSON exporter shares raw block/fluid/hazard/collision helpers. The bounded property/isAir/isSource preflight remains to preserve legacy callback exceptions; the unchanged property regex is compiled once. This removes JSON graph construction/decoding, without deleting terrain safety checks or property enumeration.
- `CombatCellCache` retains the same per-captured-tick, 1,024-entry, no-eviction cache including null/unknown entries, and adds primitive attempt counters.
- Retreat evidence retains candidate/window durations, the original window return/rejected cell when budget wins, cooperative deadline stages, and scoped stage/cache/read counters. See [field semantics and deadline limits](../client-mod/docs/retreat-budget-observations.md).
- The 0.65 window, 0.1 clearance gain, full short-tail probe, all dynamic/center/four-corner checks, freshness, world/player identity, progress and release conditions remain. Extra observation work can revoke an admission if it consumes the existing budget.

## Offline validation

The final candidate aggregate runs 441 Java tests (all passed), 1,010 Python tests (1,009 passed, one pre-existing frozen-v5 comparison unavailable), and 30 Node tests (all passed), plus terrain/guarded helpers, static audit, and complete offline clean test/build. Two old source-string checks were updated to assert direct typed dispatch and the same loaded/shared-safety contracts rather than require the removed JSON adapter.

The companion validation kit compares actual candidate TerrainReader to immutable integrated.2 source with controlled Minecraft fixtures and real Gson: 155 scenarios / 4,285 assertions, including all Cell fields, full export JSON, callback order/counts and exceptional/unknown contexts. Independent checks cover additional adversarial contexts, 5,000 deterministic route fixtures, 451 clock probes, and the unchanged 16-candidate rejection on recorded terrain. These checks supplement, not replace, a real Minecraft run.

Counterbalanced fixture benchmarks retain all raw rounds and compare frozen JSON, refactored JSON, typed metrics off, and typed metrics on. Their allocation and per-round mean time statistics are synthetic diagnostics, never per-cell in-game tail latency or proof of the 8 ms target. The frozen comparison includes both regex reuse and JSON elimination; the refactored JSON comparator helps distinguish the contributions. No live improvement has been measured.
