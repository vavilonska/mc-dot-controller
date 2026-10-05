# Client actions source verification

Build checked on 2026-10-05. This is source/build verification, not live gameplay acceptance.

- Minecraft 1.21.1 / NeoForge 21.1.255
- Cached official Java 21.0.12.1, Gradle 8.14.3, ModDevGradle 2.0.148
- Offline binary pipeline (`-Pbridge.noRecompile=true`)
- 75 JUnit tests, zero failures, errors or skips (64 existing + 11 focused action checks)
- `compileJava`, `test`, `jar`, `sourcesJar`, `build` successful after the final source edit

Reproduce from the `client-mod/` directory using an existing Java 21 toolchain
and official dependency cache:

```sh
JAVA_HOME=/path/to/jdk-21 GRADLE_USER_HOME=/path/to/gradle-cache \
  bash gradlew --offline --no-daemon --max-workers=1 \
  -Dorg.gradle.parallel=false \
  -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
```

Final JAR:

`build/libs/mineclient-bridge-neoforge-1.21.1-1.1.6-client-actions.1.jar`

SHA-256: `428c250c49cceb3bd3ec7f85806df127eb56fed162edd9362cd7bf5a28b35f29`

Sources JAR SHA-256: `6fca2559a171156a0ed4cb8714e9dd29651f5e67e4ccb9687579cd16b039db00`

Build logs and compiled artifacts are excluded from this public source snapshot.

## Scope

New action parser, outcome/identity registry, tick steering and client executor are implemented. The authenticated HTTP contract, menu snapshots and direct-input takeover are wired in. Legacy experiments remain separate, with ownership exclusion while a new client action is running. Original state/frame/terrain/direct controls and token/loopback authorization are preserved.

The focused checks exercise data parsing, action-ID reuse/cancellation, single ownership, status copies/nulls, per-tick steering/turn/jump decisions and source wiring to vanilla interaction APIs. They do not instantiate Minecraft. Final review also checked actual cached 1.21.1 client bytecode for mining and item-use behavior. An instant-break release prevents the same tick from attacking the block behind the requested target.

No installed profile was modified. No client launch, connection, token read, authenticated live HTTP, game input, world mutation or native viewer validation was performed in this source task. Next coordinated validation is real-client short walking/turn/jump and direct takeover, followed by mining/pickup, observed-menu crafting and one jump-underfoot placement on the authorized friends server. Do not call unit-test success live acceptance.
