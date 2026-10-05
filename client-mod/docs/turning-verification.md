# Guarded yaw integration verification

Verified 2026-10-05. This source extends corrected movement version
`1.1.5-terrain-guard-movement.1`, published in controller-source commit
`088505b989e59cf2477f50af38bc8eed8cedc585`. Upstream MIT license remains intact.

## Passed

- Full Java compile, test compile, JAR/sources-JAR packaging, check and build
- Minecraft 1.21.1 / NeoForge 21.1.255
- Java 21.0.12.1, Gradle 8.14.3 and official ModDevGradle 2.0.148 binary pipeline
- **54 JUnit cases**, zero failures/errors/skips: all 35 prior cases plus 19 yaw cases
- Existing 150 guard checks, 37,371 terrain assertions and 13 terrain dispatch checks
- Existing terrain static audit
- Independent source/race review; findings fixed and re-reviewed

Yaw regressions cover normal and wraparound steps; actual float32 angle bounds;
TTL bounds; queue/validation expiry; cancelled old callbacks versus replacement
tickets; shared movement/turn exclusion; cross-action nonce/observation reuse;
stop/restart and screen/world/death/release cancellation; reentrant cancellation;
executor rejection; partial mutation failure; timeout and interruption racing
started turns; identity/pose/readiness freshness; and default-off route wiring.
The status-bracketing regression remains: only state issues observations.

Review caught a strict numerical edge where validating a double then casting to
float could exceed 30 degrees by about 0.000008. The exact float-representable
angle is now canonicalized and validated against both expected and live yaw before
application. Final pose equality is checked after recomputing readiness predicates.

## Build

```sh
JAVA_HOME=/path/to/existing/jdk-21 GRADLE_USER_HOME=/path/to/existing/gradle-cache \
  bash gradlew --offline --no-daemon --max-workers=1 -Dorg.gradle.parallel=false \
  -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
```

Cached official tooling was used; no new tool/dependency fetch or game execution.
The final build completed successfully in 11 seconds. Existing deprecated API and
Gradle-feature warnings remain, without compile/test failures.

## Artifacts

- Version: `1.1.5-terrain-guard-navigation.1`
- JAR: `mineclient-bridge-neoforge-1.21.1-1.1.5-terrain-guard-navigation.1.jar`
- JAR SHA-256: `e79e0e43e0b652a2c252ccaec5d72de86db345434f6331f042de356a9f7196be`
- Sources JAR SHA-256: `8deecd681fda7f8a74adbece3bef91f05eca8c43e9ca14179e146b94526415d9`

## Acceptance limits

This is reviewed source plus offline build/test evidence. No installation, live
HTTP, game input, credential operation, multiplayer test or live navigation
acceptance occurred. The external one-sample adapter's fake tests are separate
from this mod's JUnit results and do not establish actual Minecraft physics.

Turning is separately default-disabled, yaw-only, local unpublished Survival,
and at most 30 degrees per dispatch. Both turning and movement share fresh
one-use observations and admission. Movement remains one half-forward input
sample. Neither input release nor yaw alignment brakes residual momentum.
Timeout cancellation cannot undo a setter already started; a stalled synchronous
game callback may block completion. Arbitrary mods and mixed legacy controllers
remain unsupported. The existing combat guard's busy check remains advisory at
dispatch rather than part of the shared turn/movement admission lock.

The [turning contract](guarded-turning.md) specifies exact fields, deadlines,
float32 semantics, cancellation and adapter requirements. Any future installation
or live input requires separate approval and isolated disposable-arena testing.
