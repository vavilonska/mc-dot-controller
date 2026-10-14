# T13 movement: focused offline validation

This is a repo-relative port of the action-tick and wire regression tests. It reads production Java and Python files directly from this checkout. It does not build or run Minecraft, dispatch an action, contact a server, create a mod release, or alter a saved world.

## Run

Supply existing, trusted Java 21 and compiler-only prerequisites; the runner downloads and installs nothing:

```sh
export JAVA_HOME=/path/to/verified/jdk21
export MDC_NATIVE_CLASSPATH=/path/to/compiler-only-game.jar:/path/to/baseline-client.jar:...
export MDC_GSON_JAR=/path/to/gson-2.10.1.jar
python3 -I -B client-mod/validation/movement-t13/run.py /path/to/new-output-directory
```

The complete ordered dependency list, expected file names and SHA-256 hashes are in `expected-prerequisites.json`. The historical compiler-only game jar and baseline client jar are required inputs, not included deliverables. The compiler-only game jar exposes a verified fire-state reader solely for compilation. It must never be installed or used as a game runtime. Supply the listed basename for each jar even if its parent directory differs. The exact trusted Java binaries are also pinned; a different build requires an explicit prerequisite review and pin update. `expected-production.json` pins this T13 source checkpoint.

The output directory must not exist. Existing attempts are never overwritten or automatically rerun. Each child gets stdout/stderr and a terminal receipt. A timeout only terminates and reaps that runner's own compiler/test process; it does not retry. Commands in output receipts can contain local prerequisite paths, so review those before sharing them. Keep generated classes, JSON fixtures and receipts outside the source checkout.

## What it verifies

1. Direct source wiring, native effect fences, original monotonic deadline, action-owned lifetime, and five unchanged historical lifecycle method bodies. The synthetic driver contains four exact, freshly extracted production owner-query methods.
2. Fresh native compilation of the seven changed production source families, plus five supporting policy/codec families. Annotation processing and implicit source compilation are disabled. The test verifies all 12 top-level classes resolve from the fresh output before producing wire fixtures. All emitted production classes must be Java 21 class-file major 65.
3. Real production response assembly, single-authority projection, witness creation and serialization with explicitly synthetic captured facts. Fresh fixtures cover 0, 3, 32, 64, 128 and 180 entity rows, legacy inline equivalence, four legacy profiles, exact UTF-8 reserved-size boundaries and the actual size-refusal wrapper.
4. Actual movement, entity, registry and codec logic compiled against synthetic engine readers. Fifteen scenarios cover ages 0 through 159 and refusal at 160, regressions/gaps, same-callback and between-callback world-time changes, owner/context changes, original deadlines, capture budgets, atomic displacement accounting, entity safety, terrain/input refusal and cleanup evidence.
5. The actual Python complete-reply consumer and a detached driver predicate validate the freshly generated terminal. The native-generated action stays `cancelled / fixture_end / ticks=1`. Only a separately labelled copied envelope becomes synthetic success for the status/pose predicate. Historical private T12 receipt data is not required or included; an explicitly synthetic legacy cancellation tests the equivalent negative condition.

The engine test does not execute the real `ClientActions.preTick`, start, input or finish lifecycle. Source assertions bind those call sites, but are not dynamic Minecraft lifecycle evidence. Real codec tests reject initialization of `Minecraft`, `Entity`, `BridgeServer` and `ClientActions`; loading metadata without initialization is allowed. `System.nanoTime()` boundary tests use actual time and bounded waits, not a substitute clock or a claim of hitting one exact nanosecond.

Passing this suite is focused offline evidence, not a complete Gradle/NeoForge build, real client-tick or movement success, future-dynamics guarantee, server confirmation, deployment or live-world acceptance.

## Outputs and consumers

- `RESULT.json`: child exit statuses and scope
- `source-relation-results.json`: direct source checks
- `native-class-manifest.json`: generated production class hashes and Java major versions
- `wire-fixtures/`: fresh complete wire cases and `producer-case-sizes.json`
- `action-fixtures/`: actual synthetic-engine terminal, fresh native-serialized witness/replies and consumer results

Set `MDC_MOVEMENT_WIRE_FIXTURES` to the generated `wire-fixtures` directory for the separate Python/Node regression under `resident-controller/tests/movement_t13`. All fixture facts are synthetic. No binary or generated evidence is installed into production.

`PORT-PROVENANCE.json` records the retained source origins and transformations. These origin names are provenance labels, not runnable paths or dependencies on an old working tree.
