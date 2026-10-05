# Guarded movement source/build verification

Verified 2026-10-05. Base: integrated `1.1.5-terrain-guard.1` source, originally
Campione01/MineClient-Bridge v1.1.5 (`60e78940f7e7fa06116cf4fbc58df346ad617531`).
MIT license and existing terrain/combat/input-isolation code retained.

## Passed

- Complete target-version Java compile, test compile, JAR/sources-JAR, check/build
- Java 21.0.12.1, Gradle 8.14.3, official ModDevGradle 2.0.148 binary pipeline
- Minecraft 1.21.1 / NeoForge 21.1.255, using the already cached official tools
- All **35 JUnit cases**, zero failure/error/skip, including **21 new movement tests**
- Dependency-free guarded-action checks: 150
- Terrain core assertions: 37,371; terrain dispatch checks: 13
- Existing terrain static safety-contract audit
- Independent source/race review and target-version event/sprint/physics inspection

The new cases cover one sample per request; release before acknowledgement;
expiry before/during validation; partial mutation failure; cleanup failure retaining
admission; replay rejection and non-evicting budget; stop/restart races; reentrant
screen/world/death/release cancellation; old-ticket isolation; timeout racing
mutation; interrupted HTTP workers; identity/freshness/pose gates; numerical bounds
and monotonic wraparound; one-use/newer observation invalidation; delayed HTTP work
with stalled game ticks; exact observation binding; post-admission observation
expiry; cancellation barriers for not-yet-admitted requests; and source wiring.

Review fixes include near-rest gating, ordinary standing/speed/flight restrictions,
cached speed recheck, read-only queued-auto-jump rejection, post-corridor predicate
and pose checks, and one-use expiring observation IDs invalidated by cancellation.
Interrupted responses retain the completed sample/release outcome. Combat's busy
check is advisory at dispatch, not a common atomic cross-primitive admission gate.

## Reproducible build command

```sh
JAVA_HOME=/path/to/existing/jdk-21 GRADLE_USER_HOME=/path/to/existing/gradle-cache \
  bash gradlew --offline --no-daemon --max-workers=1 -Dorg.gradle.parallel=false \
  -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
```

`bridge.noRecompile` selects the official binary-dependency pipeline, which compiles
the complete bridge and applies its access transformers without rebuilding
Minecraft's own sources. The build reports a deprecated API/Gradle-feature warning;
there are no compile or test failures. No new tools or dependencies were fetched.

## Compiled artifact identity

- Version: `1.1.5-terrain-guard-movement.1`
- JAR: `mineclient-bridge-neoforge-1.21.1-1.1.5-terrain-guard-movement.1.jar`
- SHA-256: `d157fd2ed36ab271c27ded3e54a5884f36239f991f6ec63a48d014742eb8f614`
- Sources JAR SHA-256: `4018c8f87ad62d571a8d85366633d3914b7841225e7e85eec71dffe02b577975`

## Not established

No installation, game launch, live HTTP probe, movement, combat, server acceptance,
controller transport or credential operation was performed for this change.
Default-disabled source and successful offline tests are not live safety approval.

The primitive supplies at most one ordinary half-forward input sample. Its <=100ms
handler-entry lease and <=150ms server-observation freshness are not a held-key
period or physical stopping promise. Vanilla momentum can remain after input
cleanup; a stalled game thread can block completion indefinitely. Arbitrary mods
are unsupported. Existing legacy routes are still unguarded.

Navigation-only turning is absent. A future source change needs a separate bounded,
fresh-state/replay/cancellation guarded yaw primitive, then an external adapter that
uses one-sample semantics and readback/near-rest settling rather than the fake
adapter's duration-to-distance model. Separately approved isolated game testing is
required before any live controller can be enabled. See [full contract](guarded-movement.md).

Final integration correction: only `/control/state` issues an observation ID. `/control/status` now reads lease status without issuing or invalidating a challenge; the status-state-status bracketing regression passes.
