# Portable ray and consume-completion regressions

This directory contains source-only headless regressions for the quantized block-menu ray and use-item completion ordering fixes. Fixtures are deterministic and synthetic. Geometry is translated to an arbitrary origin: furnace `(2, 0, 0)`, player feet `(.5, 0, .5)`. No saved world, observed action response, private workspace layout, historical build output, runtime identifier, or downloadable dependency is packaged or required.

## Run

Use Python 3 and a Java 21 JDK. Supply a new output directory outside the checkout, the already available local compile dependencies, and the unmodified NeoForge 21.1.255 client overlay JAR:

```sh
python -B client-mod/validation/consolidation/run.py \
  --repo . \
  --output ../consolidation-check \
  --classpath-file ../local-dependencies.txt \
  --engine-jar /your/local/neoforge-21.1.255-client.jar \
  --javac /your/jdk-21/bin/javac \
  --java /your/jdk-21/bin/java
```

`local-dependencies.txt` contains one native-platform classpath line (`:` on Linux/macOS, `;` on Windows), with existing local JAR paths. It must include the project's normal offline production compile dependencies, plus ASM core/tree/commons 9.10.1, SLF4J API 2.0.9, Mojang logging 1.2.7 and Netty codec 4.1.97.Final. The corresponding reviewed baseline also uses Gson 2.10.1, Brigadier 1.3.10, NeoForge bus 8.0.5, loader 4.0.45, Log4j API 2.22.1, Guava 32.1.2-jre, DataFixerUpper 8.0.16, Authlib 6.0.54, Netty buffer/common 4.1.97.Final, JOML 1.10.5, mergetool API 2.0.0, LWJGL core/GLFW 3.3.3, Commons Lang 3.14.0, Sponge Mixin 0.16.4+mixin.0.8.7 and fastutil 8.5.12. Dependencies are not downloaded, installed, or inferred by this runner.

The normal project compile game JAR may contain compilation-only access changes. The engine overlay is separately SHA-256 pinned and its original `Entity`, `Minecraft`, and `ShieldItem` bytes are read directly. The actual runtime Mth/Shapes/Vec3 dependency class bytes are checked against `fixtures/geometry_resource_sha256.json`; these hashes match the original Minecraft 1.21.1 SRG dependency classes. The NeoForge overlay does not contain all vanilla dependency classes. An optional `--runtime-classpath-file` allows runtime dependencies to differ from compile dependencies, while preserving those checks. Unsupported dependency changes fail closed and require reviewing the relevant test contract; there is no pin-bypass flag.

The runner always freshly compiles production and harness sources. It reconstructs and compiles the pre-fix consume control using the two exact source replacements in `fixtures/consume_baseline_replacements.json`. Those replacements reproduce the old source, rather than distributing a historical JAR/class or requiring its path. Source drift fails closed instead of silently weakening the baseline.

All classes, generated fixtures, sine-table bytes, logs and reports go under `--output`. An existing output directory is rejected; failed or inconclusive executions are never automatically retried. Use a new directory only after reviewing the prior outcome. Input source files are never modified. The process only runs explicit compiler/test children and does not invoke a game launcher, server, network client, renderer, GUI, world loader or deployment tool.

## Coverage

- Java quantized ray: 360 geometry rows over all six face orientations, 1,807 assertions, actual unmodified Entity view-vector instructions, engine Mth sine lookup table, Shapes clipping and production helpers. Includes the translated precision counterexample and neighbor, wrong-face, offset, reversed/parallel ray, edge and certified-prism refusals.
- Python/native parity: all 65,536 LUT entries, all generated geometry rows, full synthetic witness acceptance, ten adverse mutations, and seven cross-wrapper/schema/unknown-outcome checks. The reference witness comes exclusively from `FurnaceBlockMenuWire.java` and `SyntheticBlockMenuFixture.java`. The existing source-only state-menu fixture is also checked without modification.
- Wire serialization: real `ScopedNativePreflight` witness factory/digests, `ActionRegistry.Entry`, `BridgeServer.ActionResponses`, `CapabilitySnapshot` and `BridgeJson`; standalone and coherent action/status/state results must match exactly. An ideal-center counterfeit and post-click unknown outcomes must remain inadmissible.
- Consume ordering: 137 assertions across 20 scenarios. The historical control reproduces extra bottle/mainhand then shield/offhand use. The fixed control covers 32 pending ticks, same-count potion/food/bottle completion, count changes, entity-phase Post completion, partial-sync refusal, no Pre dispatch, same-tick refusal, owner/context replacement, cancellation, timeout budget, click/use callbacks and public Entry result equivalence.

`result.json` records completed stages plus source, harness and dependency hashes. `geometry.stdout`, `block-menu-result.json` and `consume-result.json` give detailed counts and cases. Local compiler logs may contain local paths; they are output evidence, not part of this source directory.

## Boundaries

The consume harness executes unchanged selected production method instruction streams with type aliases. It uses the pinned engine's complete `startUseItem`, exact held-key branch slice and real `ShieldItem.use`, plus native enums and the actual Entry serializer. Player/world/context/cleanup/hooks are explicit doubles; potion/food effects and bottle PASS are modeled. This verifies ordering within the declared harness, not arbitrary mod callback behavior.

No FML bootstrap, Mixin transformation, actual native-use dispatch, renderer integration, ordinary-world acceptance, multiplayer behavior, gameplay success, deployment or publication is established here. The geometry checks are pure engine geometry; no Minecraft client or world is instantiated. Cross-runtime atan2/hypot rounding at pathological binary32 boundaries can still fail closed. Independent compile, Mixin, broader repository and authorized ordinary-world gates remain separate.
