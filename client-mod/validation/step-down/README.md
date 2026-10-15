# Standalone one-block descent candidate

`movement-step-down-observed-v1` authorizes one cardinal move from a centered stationary source to the adjacent cell exactly one block lower. The source is an isolated safe full-cube pedestal over a complete ordinary lower floor. The 6 × 5 × 6 (180-cell) loaded footprint requires a safe lower plane, the single source pedestal, and literal dry air everywhere else. No general cliff, stairs, slab, obstacle detour, jump, sprint, pickup, chaining or distance-ledger expansion is included.

The existing flat/collect controllers and entity policy/readers remain byte-for-byte unchanged. The new controller reuses the immutable rectangular bounds record only to feed the existing complete entity reader. A separate ClientActions owner field, capture profile, footprint, terminal witness and wire diagnostic version are used.

The source must have a neutral closed inventory, private Overworld survival, an exact ordinary player body and attributes, no automatic jump, no gravity override, no active effect/hazard, unchanged food at least 6, and health above the supplied minimum. The MovementBudget ledger must be unarmed both at admission and before every effect. Unknown outcome, rejection, failed settlement or cancellation is never retried or resumed.

One action is limited to 8 seconds and 160 native action Pre ticks. The descent phase may last at most 20 native action ticks. Observed Y may only decrease and cannot go below the goal; the body cannot intersect the pedestal. Downward velocity and per-action-tick sampled drop are limited to .5; fall distance is limited to 1.01. These limits are conservative candidate guards, not proven maximum bounds for every vanilla or modded execution. The source-inspected ordinary gravity recurrence uses .08 gravity and the promoted binary32 .98 drag. The tests prescribe that sequence and do not execute Minecraft physics.

Native success requires two exact lower-Y grounded samples, horizontal goal radius .23, horizontal velocity at most .003, ordinary residual vertical velocity in [-.09, 0], and neutral input cleanup. The terminal `landed` flag records observed landing phase; a cancelled action may be landed without being stopped. The public skill independently requires later stable settled observations. Cancellation while airborne releases input but cannot stop gravity or certify stopped velocity.

## Offline checks

Use existing trusted Java 21/Gson/native dependencies, and new output directories outside this checkout:

- `python -B run_engine.py --output /new/engine --java /jdk/bin/java --javac /jdk/bin/javac --gson /deps/gson.jar`
- `python -B run_native.py --output /new/native --engine-output /new/engine --java /jdk/bin/java --javac /jdk/bin/javac --classpath-file /deps/compile-classpath.txt`
- `python -B check_source_relation.py`

The first runner freshly compiles the actual new policy/controller, existing entity reader/policy, native Entry registry and JSON codec against explicit synthetic engine readers. Its four owner-query methods are extracted unchanged from current ClientActions. It checks geometry, phase/velocity/drop limits, per-action tick lifetime, hook changes, gravity/auto-jump/food/budget refusals, terrain and neutral cancellation. It does not execute actual followPath/input/finish dispatch or vanilla collision/gravity.

The second runner freshly compiles all production Java files. The wire producer uses actual `ScopedNativePreflight` witness/digest, `ActionRegistry.Entry`, `BridgeServer.ActionResponses`, `CapabilitySnapshot`, `ScopedMovementWire` and `BridgeJson` code over the first runner's captured synthetic footprint and terminal. Source-relation assertions cover the new callback integration and preserve accepted flat/collect source hashes. They do not establish game lifecycle correctness.

No artifact, launcher, installation, network, FML/Mixin bootstrap, ordinary world, renderer or live gameplay is invoked. Genuine ordinary-world acceptance remains a separate gate.

## Portable complete runner

From the repository root, run:

```sh
python -B client-mod/validation/step-down/run_all.py \
  --repo . --output ../step-down-check \
  --java /your/jdk-21/bin/java --javac /your/jdk-21/bin/javac \
  --gson /your/dependencies/gson-2.10.1.jar \
  --classpath-file /your/dependencies/compile-classpath.txt
```

Python 3, a trusted Java 21 JDK and Node.js on PATH are required. The controller-only stage needs Gson 2.10.1. The full compile/serializer stage needs the project's ordinary offline native compile classpath: a NeoForge/Minecraft 1.21.1 mapped compile game JAR, Gson 2.10.1, Brigadier 1.3.10, bus 8.0.5, loader 4.0.45, Log4j API 2.22.1, Guava 32.1.2-jre, DataFixerUpper 8.0.16, Authlib 6.0.54, Netty buffer/common/codec 4.1.97.Final, JOML 1.10.5, mergetool API 2.0.0, LWJGL core/GLFW 3.3.3, Commons Lang 3.14.0, Sponge Mixin 0.16.4+mixin.0.8.7, fastutil 8.5.12, ASM core/tree/commons 9.10.1, SLF4J API 2.0.9 and Mojang logging 1.2.7. The classpath file is one native-platform classpath line (`:` on Linux/macOS, `;` on Windows) of existing local JAR paths. Nothing is downloaded or installed. Dependency hashes are recorded in local evidence. The normal offline compile game JAR may have compilation-only access adjustments; this stage is not a pristine runtime launch.

All runners accept `--repo` so staged test sources can be checked against the final integrated production tree. They require fresh external output directories and never overwrite or automatically retry an existing result. The source-only shared test helpers `movement-t13/prepare_engine_fixtures.py`, `WireV1Fixture.java` and `WireV1Facts.java` are read from that tree. Existing public Python fixture/support modules and accepted flat/collect source hashes are reused. No private generated native fixture directory is required or bundled.

The native test geometry has source feet `(.5, 1, .5)`, goal `(1.5, 0, .5)`, pedestal `(0, 0, 0)` and floor Y=-1. It is an origin-translated synthetic fixture. The separate Python examples around `(.5, 64, .5)` are already source-defined illustrative fixtures. Generated clocks/identities belong only to temporary offline tests. No saved world, live observation or installed-runtime identity is read.

The complete runner freshly compiles eight unchanged controller/policy/registry/codec production files plus four unchanged extracted ClientActions owner-query methods against explicit reader doubles, runs all 15 controller scenarios, freshly compiles the full production Java tree, emits new native wire, checks source relations, then runs 24 public-contract/MCP-frontdoor/native-wire-consumer tests. The native producer checks its controller/owner/harness source hashes before consuming the newly generated fixture. The frontdoor launches the actual Node MCP and Python toolbox with an isolated temporary operator configuration; the fake Bridge is an in-process endpoint and transport uses stdio/filesystem queues. There is no external network or game endpoint.

`result.json`, `engine/engine-result.json`, `native/result.json`, `native/source-sha256.json` and stage logs hold the evidence. Generated classes, wire, owner journals and transcripts are confined to output/temporary test directories and must not be bundled with these public source tests. Local command logs can contain operator-local paths. Neither this runner nor its source-relation checks establish real ClientActions input/finish dispatch, engine physics, FML/Mixin lifecycle, artifact deployment or ordinary-world success.
