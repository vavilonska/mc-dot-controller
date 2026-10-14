# Combined mining, collect and combat offline validation

The runner compiles every production Java source from this checkout, then exercises actual policy, witness, projection and HTTP codec code. It does not launch Minecraft, open a socket, dispatch an action, apply mixins, deploy a mod or touch a saved world.

## Run

Supply the trusted Java 21 binaries and the ordered external-library classpath pinned by `../movement-t13/expected-prerequisites.json`. No download, installation, baseline mod JAR or old compiled project classes are allowed. The runner rejects any supplied JAR containing project classes.

```sh
export JAVA_HOME=/path/to/verified/jdk21
export MDC_NATIVE_CLASSPATH=/path/to/compiler-only-game.jar:/path/to/gson-2.10.1.jar:...
export MDC_GSON_JAR=/path/to/gson-2.10.1.jar
python3 -I -B client-mod/validation/mining-collect-combat/run.py /path/to/new-output-directory
```

Use exactly the pinned basenames, hashes and order. The compiler-only game JAR includes the reviewed fire-reader visibility adaptation; it is never a game-runtime or distributed mod artifact. All sources are pinned in `../movement-t13/expected-production.json`. Output must be outside the checkout and must not already exist. No existing attempt is overwritten or retried automatically. Review a failed attempt's terminal receipt before authorizing a separate new attempt.

Compiler and JVM processes use one active processor, a 384 MiB heap ceiling, and finite timeouts. Each child has a start receipt, stdout, stderr and terminal receipt. The outer runner owns its launched process group and kills/reaps only that group on timeout. Unknown process state is recorded as `unknown_no_retry`.

## Coverage

- All production Java is compiled in one invocation with annotation processing and implicit source lookup disabled. Every emitted production class, including inner classes, is checked for fresh output origin and Java 21 class-file version. External jars contain no project classes, so stale mod artifacts cannot hide a source mismatch.
- The T13 ordinary-movement scenarios and actual generated-wire Python consumer still run. Its deliberate combined-source adaptations are documented in `../movement-t13/README.md` and its provenance file.
- `MiningObservedPolicyTest` retains the original finite mining entity-policy and explicit-null serializer assertions, with a newly generated synthetic input.
- The existing collect finite-policy fixture exercises the exact target exception, ordinary movement rejection, grounded item gravity cycles, velocity and position boundaries.
- The existing combat callback fence and closed-intent checks execute real production pure methods without creating a client or applying mixins.
- `CombinedWireChecks` produces original intent/request plus actual production witness/assembly/codec bytes for collect and combat. Collect uses the existing single-authority marker and reference-only status/state placement. Combat preserves its supported inline witness placement. Actual serialized standalone/coherent witnesses must agree; collect rows retain explicit nullable target fields. The 262,144-byte response cap is unchanged.
- Class initialization logs reject accidental real Minecraft, Entity, BridgeServer or ClientActions initialization during native codec/policy checks.

All captured game facts are explicitly synthetic. These checks do not prove mixin transformed application, real combat functional behavior, pickup success, or live-world acceptance. Those stages remain NOT_RUN.

## Results

- `RESULT.json` and `INPUTS.json`: status, child terminal outcomes, source snapshots and scope
- `movement-t13/`: full production class manifest, class-origin checks, T13 dynamics and wire evidence
- `combined-wire/{collect,combat}-{standalone,coherent,intent,request}.json`: freshly serialized codec files plus original inputs for the real cross-language consumer
- `combined-wire/mining-policy-{input,output}.json`: finite mining policy/codec fixture
- `combined-wire/JAVA-WIRE-RESULT.json`: native codec checks and explicit synthetic scope

The separate Python consumer must read the emitted JSON files directly and call the production complete-snapshot and scoped-witness validators. Passing this native runner alone does not claim that separate consumer passed. Commands and compiler paths in output receipts are local evidence; review/sanitize them before sharing. No generated classes, private paths, binary dependencies or results belong in the public source tree.
