# Mainline native / MCP action boundary

Run `bash run.sh CLIENT_MOD_ROOT EXISTING_GSON_JAR JDK21_HOME BUILT_CLIENT_JAR`
in an approved serial JVM window, after the integrated production build. The
fourth argument must be that build's actual client JAR. The script records its
SHA-256, Gson SHA-256, relevant production source hashes, and the unchanged Java
emitter / Node checker hashes in `.build/input-sha256.txt`.

The script compiles only the wire emitter against the pinned JAR, runs the real
request parser and action registry from that JAR, and passes all six emitted
cases to the real Node adapter. Parsing now references `CoordinationStepGuard`,
so compiling the former eight-class subset is no longer the correct production
closure. No guard or Minecraft substitutes are used.

Any actual class-linking failure must be recorded before deciding the minimum
additional dependencies. This entrypoint has no fallback classpath or stubs.

The root parser accepts nine actions. `recover_environment` keeps its absent
or explicit zero timeout; a normal path rejects zero. The finite MCP submit
surface accepts the frozen v18 eight actions and rejects recovery before I/O.
The adapter can inspect/cancel the original known root recovery ID using the
native registry's real running/cancelled receipts and exact action session.

This verifies parsing, ID/body ownership, receipt transport and the adapter
boundary. It does not execute `ClientActions` ticks or prove live recovery.
The unchanged runtime zero-timeout deadline (`Long.MAX_VALUE`) remains covered
by the existing source-wiring regression; no fake Minecraft bootstrap is used.
