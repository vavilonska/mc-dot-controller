# Integrated diagnostics candidate 1.1.7-integrated.3

This isolated candidate is based on the verified integrated.2 source. The running integrated.2 environment and all earlier candidates remain unchanged. Only the final typed-retreat patch and final resident terrain-latency diagnostics patch are combined. The ranged-primitives branch is not included.

## Exact scope

- Combat Cell cache misses use the reviewed typed TerrainReader path rather than constructing and reparsing a JSON object graph. Typed and full JSON export share the loaded-state, fluid/hazard, collision/context and metadata-preflight safety facts. Callback order, original exception rejection, unknown facts and same-tick cache limits remain guarded. The fast path is wired to Combat only. See TYPED-RETREAT.md.
- Retreat evidence preserves the original completed window result when a subsequent 8 ms budget boundary rejects admission. Bounded candidate/window, stage, cell/cache and decision-return diagnostics distinguish observed work, original rejection and budget rejection. Unknown timing remains unknown; no field explains an unobserved cause. See ../client-mod/docs/retreat-budget-observations.md.
- Resident terrain reads record first/last state, page request roundtrips, reported Java sampling values, actually read response bytes or unknown, assembler/wait stages, original rejections and actual attempts. Failed explicit observe attaches only this scan's diagnostic evidence to that request's failure; pre-scan failures cannot reuse older records. See ../resident-controller/docs/TERRAIN_LATENCY_DIAGNOSTICS.md.

## Separate timing domains and unchanged limits

Combat's typed read path does not replace or accelerate the resident's paged terrain endpoint. It does not establish a fix for the prior 3-second complete-terrain rejection. The full exporter still serves pagination. A 567-cell scan at the 128-cell ceiling requires at least five pages; a smaller probe is not equivalent evidence.

The 3-second shared terrain deadline, 128-cell page ceiling, 2 ms cooperative Java sampling budget, 256 KiB non-frame response cap, 8 ms retreat planning budget and 150 ms health sample-gap policy remain unchanged. Source/world/player/action/vehicle/target identity, complete coverage, chunk availability, tick/freshness, route envelopes and input-release constraints remain intact. Unknown or expired evidence never becomes fresh by reading diagnostics.

Python request roundtrip, Java sampling and Combat decision timing use different domains and may overlap. Roundtrip minus reported Java time is not an established network/queue/CPU attribution. Stage values are not additive proof of total coverage. Diagnostics add overhead and can increase conservative rejection near deadlines. Synchronous reads/hooks are not preempted; fail-closed at sampled boundaries is not a hard real-time upper bound for every instruction or actual input event.

## Merge integrity and retained capabilities

The original patches share only SOURCE_SHA256SUMS.txt. All production and test files in the union remain byte-identical to their reviewed patch outputs. Integration changes only the final version/readme context, this document, a clarification that the resident diagnostics document describes the terrain-latency patch alone, and the regenerated global source manifest. The union retains integrated.2's retreat consistency, health diagnostics, native boat passenger envelope, expedition and single native owner rules. ResidentAdapter dispatch/poll/cancel remain live-hard-rejected; no real multi-agent speedup is claimed.

## Verification boundary

The delivery contains one clean-built integrated.3 runtime JAR, matching sources JAR, complete source archive, exact patch from integrated.2, per-file provenance, Java/Python/Node logs and XML, full replay validation, and an independent union review. Candidate and fresh patch-replay builds are tested independently, with source and JAR byte comparisons. Counts come from actual logs; the inherited unavailable historical-watchdog fixture is explicitly skipped.

This candidate has zero live executions and has not been installed, restarted, deployed, pushed or uploaded. There are no game, UI, real IPC, credential, service, backup or Drive actions in this work. Offline fixtures and reported synthetic benchmarks do not establish Minecraft performance improvement, a field fix, observed escape or server outcomes. Any later deployment or version-verified full read-only preflight requires the owner's separate decision and applicable authorization.
