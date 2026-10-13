# Typed terrain adapter prerequisite: final-root tests passed, review pending

Base: accepted local position-binding commit
172b51161bf2c674a5d0337d21907858bb761262. Branch: mainline-typed-terrain.
No game deployment, remote write, combat action or dispatcher change.

## Small production scope

Only TerrainReader.java changes, byte-identical to frozen v18 source hash
c75fdef8a218197860421e1110f2107bdd46a612b3a749b0e7eba0fcd4c6aafe.
It adds the actual flatStepResult/flatCellSource/ReadMetrics prerequisites and
shares block/fluid/collision facts with the existing JSON exporter. Its read and
clear methods remain byte-identical to main. Query/Scan/Dispatch/WorldGeneration/
FlatStepCorridor remain unchanged. Python page-tick reversal is untouched.

The companion finite test kit is at client-mod/validation/terrain-adapter. It is
outside Gradle's production and test source sets. Its fake Minecraft types must
never enter the mod JAR; final archive inspection is an explicit gate.

## Actual adapter coverage, not only pure planner tests

The first isolated run executed four real source entry paths for 115 parameter
cases: old-main LoadedSource.readLoaded, new LoadedSource.readLoaded, actual
flatCellSource, and its metrics overload. It also executed 23 actual wrapper and
metrics cases, 3,868 assertions and zero semantic failures. This is a measured
preliminary fixture run, not the still-pending final-root run.

The 29-file portable kit contains only the finite fixture signatures/callbacks,
reflection oracle, checks, scripts, pins and the immutable old reader. It needs
only the caller-selected current project, existing Java21 and real Gson2.11.0.
No sibling candidate checkout is required. Only the old reader's class and
constructor names change in a generated test copy; reversing the rename must
recover its exact pinned bytes. Test compilation clears only its own generated
src/classes directories and refuses symlinked outputs to prevent stale classes.

The portable final version adds null-fluid page and corridor wrapper checks.
It was actually compiled and run against final root: 115 four-path cases,
25 wrapper/metrics cases, 3,896 assertions, zero semantic failures. UTC
15:28:38–15:28:44; compilation 2.868 s, execution 3.115 s. The original Core
37,371 checks, Dispatch13 and Corridor17 also passed. The following actual
no-build-cache single-worker Gradle test/build passed all 429 tests and ended
15:29:15 (Gradle29 s, process30.712 s). No test fixtures appear in the mod JAR.
After removing one harness trailing space, the exact final kit was recompiled
and rerun at 15:42:37–15:42:44: compile3.994 s, run3.537 s, same 3,896 assertions
and zero semantic failures. Production Java was unchanged, so no redundant
Gradle rebuild was performed.

## Known diagnostic differences, retained explicitly

Nine raw NPE message differences are three malformed inputs across three candidate
paths: null property name, null property value, and null FluidState. The first two
reflect String.matches -> Pattern.matcher; the third reflects a local-variable
slot number in JVM diagnostic text. Exception type, ordered callbacks, complete
successful JSON and all seven Cell fields agree in the executed cases. The
property failures already had public read_failed/cell_read_failed translations
checked; the two added final-wrapper tests cover null FluidState too.

No exception message is silently normalized away. This is tested public fact/
failure semantics equivalence with documented raw diagnostic-text differences,
not an assertion that every internal exception byte is identical.

## Final verification and remaining gate

1. Portable kit compiled/ran against the final root; all input pins and raw observations retained.
2. All 429 existing actual Java/JUnit tests passed, including the real in-memory
   BridgeServer serializer/response-cap tests. No tests were dropped or weakened.
3. Terrain source audit passed; the mod JAR contains no fixture Minecraft classes,
   differential oracle, LegacyTerrainReader or Trace. Original main test bytes,
   exact v18 reader and source manifest are verified by the handoff metadata.
4. Independent review and frozen patch/source handoff remain before acceptance.


Finite fixtures validate adapter propagation and rejection, not Minecraft's real
VoxelShape/registry implementation, physics, live performance or a safe route.
The next combat/encounter/pause and resident/MCP integration remains open.
