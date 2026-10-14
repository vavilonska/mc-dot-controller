# Scoped placement offline gate

Use the exact trusted Java 21 and external classpath pinned in `../movement-t13/expected-prerequisites.json`. Set `JAVA_HOME` and `MDC_NATIVE_CLASSPATH`, then run:

```sh
python3 -I -B client-mod/validation/scoped-placement/run.py /path/to/new-output-directory
```

The output directory must be new. Each bounded subprocess has start, stdout/stderr and terminal receipts. Existing attempts are never overwritten or automatically retried. Compilation uses all current production sources, annotation processing/implicit lookup disabled, and rejects baseline project classes in dependencies.

Executed checks: 49 closed production intent boundaries, 13 production poisoned-callback boundaries (owner replacement, swallowed recursion, exception, clock/tick changes), and 15 immutable final-packet identity comparisons. Source and compiled-bytecode checks verify the actual `placeCapability` selected branch contains the pre-use check and dispatch token, the entire legacy `place` body retains its baseline hash, and the final packet check surrounds callback-bearing validation. Genuine game bytecode checks confirm the exact single `BlockItem.placeBlock` call and the NeoForge check before `Connection.send`.

Production and lifecycle pin updates in `../movement-t13/` are deliberate additions for this candidate, not disabled checks. The existing synthetic movement reader adds only an inert placement PROFILE constant so the additive serializer branch compiles; movement semantics remain unchanged.

Read `RESULT.json` for scope. Passing this gate does not prove transformed mixin application, live effect fencing, ordinary-world placement success or deployment. Every native placement live stage is NOT_RUN.

## Placement Java-to-Python wire fixture

With the same environment, run `run_wire.py` with a new output directory. It reruns the fresh native gate, then emits admitted and terminal standalone/coherent placement responses using the actual compiled production witness emitter, Entry serializer, coherent-snapshot assembler, compact-witness projection and HTTP JSON codec. Captured geometry, inventory and entity observations are explicitly synthetic; a distant live row retains its nullable target and a removed row is also present.

The successful terminal method currently reads a live player and world. To avoid engine initialization or a production-only-for-test refactor, this fixture extracts its exact, unmodified method body into a separate test receiver whose count and `settled()` readers are explicitly synthetic. `TERMINAL-EXTRACTION.json` records source hash, method hash, character offsets, exact generated receiver hash and this limitation. The coordinate serializer body is likewise copied unchanged. No production class is replaced or shadowed on the codec classpath.

The emitted `wire/` directory includes original intent/request, raw witness/terminal, complete admitted and terminal replies, and Java-generated before/after ordinary inventory payloads. A separate production Python consumer gate must validate those actual bytes and verify the extraction hash; the Java producer alone is not cross-language acceptance. This gate proves serialization/consumer compatibility, not live settlement or transformed mixin behavior.

## Post-use selected-stack settlement regression

`run_settlement.py NEW_OUTPUT BASELINE_SCOPED_PLACEMENT_JAVA LOGGING_JAR SLF4J_JAR`
uses the same pinned Java environment as `run.py`. The baseline is the published
9aed63f4 ScopedPlacement.java, SHA-256
ee48a41de9039740c2acd294399370060e1a8867e3f7e1dd1aa56281ccb360d7.
The two additional, already-installed runtime dependency hashes are fixed in
`settlement-runtime-pins.json`; they only support genuine vanilla menu method
execution in a constructor-bypassed test subclass, never a game launch.

The runner freshly compiles all production source and executes the actual
PlacementSettlementPolicy and PlacementCallbackFence. It extracts exact method
bodies from current and published ScopedPlacement into a fixture with explicitly
synthetic typed slot, count, component and identity readers. Extraction offsets,
whole-source hashes and method hashes are retained in EXTRACTION.json. Actual
vanilla AbstractContainerMenu.setItem/incrementStateId establish revision 1→2 and
32767→0. The exact published raw menu guard rejects revision 1→2/count 5→4;
the candidate permits it only after confirmed use return. Tests reject pre-return
progression, rollback, revision jumps, changed components/other slots, replaced
menu, inventory, slot or container and changed slot indices. Synthetic owner loss,
cancellation, recursion and callback failure prevent revision commit.

The candidate preserves strict original revision throughout dispatch, exact one
effect and packet, unchanged typed inventory/context, and unknown outcomes after
any attempted uncertain action. Physical neutrality is reported independently
from semantic cleanup, with specific guard and cleanup reasons in additive
`result.placement_diagnostics`; the closed `result.placement` schema is unchanged.
Original T22 tick-2 exception detail was not recorded: this reproduces an overly
strict guard, not proof that this was its uniquely observed failure. None of these
tests establish live settlement, transformed mixin behavior or successful gameplay.

The settlement runner also extracts the exact attempted-failure and final placement
cleanup blocks from ClientActions into SettlementCleanupFixture. Its input and
guard observations are synthetic; it executes the real ActionRegistry terminal
and no-replay identity methods. A 96-case truth table covers clean success,
cancellation and failure, attempted or unattempted effects, semantic cleanup loss,
neutral or non-neutral inputs, release-binding loss and earlier release failure.
It checks distinct truthful diagnostics, confirmed release independent of semantic
cleanup, no uncertain success, retained handoff/unknown evidence and unchanged
registry identity. CLEANUP-EXTRACTION.json binds both unchanged source slices.
