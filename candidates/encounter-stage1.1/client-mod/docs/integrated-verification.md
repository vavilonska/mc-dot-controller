# Integrated terrain + guarded-action build verification

Verified 2026-10-05. Base: Campione01/MineClient-Bridge v1.1.5,
commit `60e78940f7e7fa06116cf4fbc58df346ad617531`, original MIT license retained.
Includes terrain review fixes and the final guarded-action lifecycle fixes.

## Passed

- Full mod compile, test compile, JAR/sources-JAR packaging, test/check/build tasks
- Java 21.0.12.1, Gradle 8.14.3, official ModDevGradle 2.0.148
- Minecraft 1.21.1 / NeoForge 21.1.255
- Official binary-dependency pipeline (`-Pbridge.noRecompile=true`); this compiles the
  complete mod and applies the configured access transformers without rebuilding
  Minecraft's own sources
- All 14 JUnit cases passed, zero failures/errors/skips
- Terrain core: 37,371 assertions; terrain dispatch: 13 checks; guarded actions: 150 checks
- Static terrain safety audit passed
- Guard adapter compiled without mapping/API failures

The narrow integration retained TerrainDispatch and its timeout-admission fix.
The only extra access transformer exposes the existing Minecraft.startAttack()Z
method used after execution-time validation. No new mixins were added.

## Artifact identity

- Version: `1.1.5-terrain-guard.1`
- JAR: `mineclient-bridge-neoforge-1.21.1-1.1.5-terrain-guard.1.jar`
- Size: 149,312 bytes
- SHA-256: `e6a628934b493ea50f0ef24a8dc7a40750880418f8b0060a3fd074623b531b9c`
- Sources JAR SHA-256: `bab36f4c8f28947ac443cd79198bb4bd5f19292b2e0d8ac13b7494df94eee52b`

Build:

```sh
JAVA_HOME=/path/to/jdk-21 bash gradlew --no-daemon --max-workers=1 \
  -Dorg.gradle.parallel=false -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
```

## Runtime gates remain

No installation, game launch, live HTTP probe, or combat action was performed as
part of this build verification. Preserve the known-working profile and use a
separately approved isolated test profile. Do not install both bridge JARs together.

The guard endpoint is default-disabled. Enabling requires the reviewed JVM flag
and a separately authorized test. It is restricted to an unpublished local Survival
world with one player, the narrow hostile allowlist, and plain unenchanted vanilla
axes. It does not make legacy input routes guarded and does not provide multiplayer
or arbitrary-mod safety acceptance. Combat decisions remain external.

See [guarded-action contract and acceptance checklist](guarded-actions.md) and
[terrain API semantics](terrain-api.md). This source snapshot contains no tokens,
private profiles, game files, runtime logs, or Minecraft/NeoForge dependencies.
