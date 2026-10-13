# Portable finite TerrainReader differential kit

This directory is ready to live at client-mod/validation/terrain-adapter. It has
no hard-coded workspace paths or dependency on an adjacent publication checkout.
The portable packaging was compiled and executed against the final mainline
project on 2026-10-08: 115 four-path scenarios (460 actual entry executions),
25 wrapper/metrics scenarios and 3,896 assertions passed. This includes the two
additional null-fluid wrapper cases. The exact final fixture bytes were rerun
at 15:42:37–15:42:44 UTC; no production or test code changed afterward.

## Inputs and reproducible commands

Use an existing Java 21 installation and existing Gson 2.11.0 JAR. No Gradle,
Minecraft launch, network access, new dependency, or registry bootstrap is needed.
Before invoking each script, obtain the coordinated serial JVM window.

    bash compile.sh /path/to/project /path/to/gson-2.11.0.jar /path/to/jdk21
    bash run.sh /path/to/gson-2.11.0.jar /path/to/jdk21

The supplied project root must contain client-mod/src/main/java and
client-mod/src/test/java. The scripts write only this kit's ignored .build/
directory. Compile uses a 256 MiB max heap; each of four sequential test JVMs uses
192 MiB. All have one effective processor, SerialGC and a 45-second timeout.
These are JVM configuration bounds, not measured peak RSS or CPU affinity.

## Exact source provenance

- Candidate TerrainReader and its five companion classes come from the supplied
  project's current sources. SHA-256 pins must match expected-source-pins.json.
- baseline/TerrainReader.java is the original pre-refactor JSON reader, SHA-256
  e2d83921a6527598c9ef5e1951b8398aa61ef3460dfc81445046d50009f0fd5d.
  Treat it as immutable. Its only generated-source transformation renames the
  class and constructor to LegacyTerrainReader. The transformation is reversed
  and checked before compiling. It is never reconstructed from v18 helper logic.
- The frozen target reader SHA-256 is
  c75fdef8a218197860421e1110f2107bdd46a612b3a749b0e7eba0fcd4c6aafe.
- The unchanged pure Core, Dispatch and FlatStep check sources come from the
  supplied project and are recorded individually in .build/executed-source-pins.json.
- The exact existing Gson 2.11.0 artifact is SHA-pinned too.
- Test fixture source hashes, input locations and every generated source hash are
  recorded in .build/executed-source-pins.json. .build/results.json retains all
  four-path observations, not only pass counts.

Do not change pins to conceal a changed source. A deliberate production revision
needs explicit source review and a new recorded comparison against that revision.

## Real entrypoints and finite fixtures

Every raw case uses fresh equivalent fixtures for old LoadedSource.availability /
readLoaded, new LoadedSource.availability / readLoaded, new flatCellSource(mc), and
new flatCellSource(mc, metrics). Both returned typed sources execute actual read.
The finite shells provide only imported type signatures and configured callbacks.
They implement no physics, network, real registry, client bootstrap or game loop.
The configured face-full result tests adapter propagation/failure handling, not
Minecraft's Block.isFaceFull geometry implementation.

The assertions compare full JSON including omitted/null keys, all seven typed
Cell fields, raw failure classes, and ordered callback traces. Metrics-on and
metrics-off must preserve facts, failures and callbacks. Runtime exception message
differences are retained without normalization and summarized separately; a
semantic pass does not mean all diagnostic strings are byte-for-byte equal.

Actual public wrapper cases cover world/thread guards, page unknown serialization,
raw metadata failure to read_failed/cell_read_failed translation, corridor cell
references, initial origin after movement, live response tick versus sampled tick,
and cached cursor replay without world reads. Independent page comparisons omit
only UUID identities and elapsed duration; generation/cursor relationships and
replayed elapsed evidence are separately asserted. The static page clock remains
unchanged; actual read calls are paced by 60 ms.

## Evidence boundaries

Initial finite-kit evidence: 115 four-path scenarios, 460 adapter executions,
23 wrapper/metrics scenarios, 3,868 assertions, no Cell/JSON/callback/failure-class
mismatch. Nine raw NPE-message differences represent three inputs on three new
paths: null property name, null property value, null FluidState. The two property
inputs and null FluidState now all have passing page and corridor wrapper
checks in the final-project 25-case wrapper/metrics run. Public failures remain
read_failed and cell_read_failed respectively; raw NPE text differences remain
visible in results.json.

All 32 planned categories have finite representatives, which is not exhaustive
Minecraft input coverage. Real block geometry, mod registry behavior, gameplay,
latency and HTTP transport are outside these finite fixtures. Retain the existing
BridgeServer serializer and 256 KiB response-cap tests in the main build.

No production file is modified by this kit. Only after the exact reader is
integrated into the intended mainline and this kit passes on that project's
current source can the final-mainline adapter gate be called closed.
