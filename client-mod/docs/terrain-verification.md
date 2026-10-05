# Standalone terrain development build verification

This records the preceding terrain-only artifact. The current combined source also
contains the default-disabled guard; see [integrated verification](integrated-verification.md).

Verified on 2026-10-05. Based on Campione01/MineClient-Bridge v1.1.5,
commit `60e78940f7e7fa06116cf4fbc58df346ad617531`; original MIT license retained.

## Build passed

- Java 21.0.12.1, Gradle 8.14.3
- Official ModDevGradle 2.0.148, NeoForge 21.1.255, Minecraft 1.21.1
- `test build` completed successfully with `-Pbridge.noRecompile=true`
- Full mod Java compilation, metadata generation, JAR packaging, test compilation,
  and all 13 JUnit test cases passed, with zero failures/errors/skips
- Terrain core tests contain 37,371 assertions; dispatch lifecycle tests add 13 checks
- Static terrain safety-contract audit and `git diff --check` passed
- Existing MCP stdio framing tests: 8 passed

The documented official binary-dependency pipeline applies Minecraft/NeoForge
patches and access transformers, then compiles this entire mod. It skips rebuilding
Minecraft's own sources; it does not skip compiling the mod or running its tests.
The older source-decompiler pipeline exceeded this build host's memory. No patched
Minecraft game binaries, dependencies, private runtime files, tokens, or logs are
included in the public source snapshot.

Build command:

```sh
JAVA_HOME=/path/to/jdk-21 bash gradlew --no-daemon --max-workers=1 \
  -Dorg.gradle.parallel=false -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
```

If the build host uses an HTTP proxy, configure it for the build process according
to that host's provided settings. No global proxy or security settings are required.

## Artifacts

- `mineclient-bridge-neoforge-1.21.1-1.1.5-terrain.1.jar`: 130,366 bytes
- SHA-256: `5073d2c876b527c6d736c752b89036984de9c35e41d1d6040b503c37ec36df31`
- Sources JAR SHA-256: `2c9b074f91872ec65c6eb1911f7e3a727083d6a08144f8022b6af0b046cb0986`

The packaged metadata retains client-only dependencies and the original four
MouseHandler access-transformer entries. The terrain API adds no world-writing,
server-command, credential, or listener-setting changes.

## Review fixes included

- A terrain timeout retains admission until the running or skipped game-thread task
  actually exits; no new terrain task can queue behind an overlong callback
- Invalid/nonfinite collision bounds become unknown, preserving valid JSON
- Failed shape callbacks publish no partial collision/support facts
- Final `next_cursor` omission is documented

Independent focused review confirmed these fixes. Five runtime-class-only collision
regression examples passed without starting Minecraft: throwing bounds, infinite
bounds, unavailable context, full cube, and empty shape.

## Remaining verification

- At the time of this build record, no runtime check had been performed. A later
  isolated graphical-client load of this terrain-only JAR reached bridge HTTP startup.
  Live terrain HTTP assertions, server behavior, and frame-time measurements remain
  unverified; this does not validate the newer integrated guard build
- The unchanged upstream MCP full self-test is Windows-oriented and fails Linux
  normalized-Windows-path validation; only its 8 cross-platform framing tests passed here
- Terrain is available through authenticated HTTP; the upstream MCP query wrapper
  has not been extended with a terrain kind
- Basic hazard labels are not exhaustive, collision boxes are enclosing boxes, and
  paging is live sampling rather than a world-atomic snapshot
- This build contains no guarded action endpoint or autonomous combat controller

Use a separately approved isolated profile for initial runtime checks. Preserve the
known-working profile/mod and existing loopback/authentication restrictions. Never
publish tokens or private profile/configuration files.
