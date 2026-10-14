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
