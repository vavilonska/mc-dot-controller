# Source provenance and license notices

## MineClient Bridge

`client-mod/` is a source snapshot based on [Campione01/MineClient-Bridge](https://github.com/Campione01/MineClient-Bridge), tag `v1.1.5`, commit [`60e78940f7e7fa06116cf4fbc58df346ad617531`](https://github.com/Campione01/MineClient-Bridge/commit/60e78940f7e7fa06116cf4fbc58df346ad617531).

The upstream MIT license and copyright notice, **Copyright (c) 2026 Campione01**, are preserved in [`client-mod/LICENSE`](client-mod/LICENSE). Upstream third-party design-reference notices remain in [`client-mod/THIRD_PARTY_REFERENCES.md`](client-mod/THIRD_PARTY_REFERENCES.md). This repository is an independently maintained development snapshot, not an official upstream release.

Local development changes add bounded, read-only nearby terrain observations, world-generation identifiers, timeout-safe terrain admission, and an additive default-disabled guarded local-action endpoint, with API documentation and tests. A separate default-disabled movement primitive now offers one half-forward input sample with release-before-acknowledgement, observation/session binding, and rejection-only replay protection; it is not a held-key pulse or momentum brake. A separately default-disabled yaw primitive shares movement admission and observations, applies bounded float32 rotation, and has no live acceptance. The bridge remains the client-side I/O layer. Planning and control policy remain outside the mod. The current development version is `1.1.5-terrain-guard-navigation.1`. The endpoint validates requests at execution time and is restricted to a separately accepted local Survival test environment; it is not multiplayer or live-combat acceptance.

The source snapshot excludes upstream workflow configuration, screenshots and raw runtime evidence, game files, generated build outputs, and all private runtime state. The small mod icon is the original upstream project resource, not a Minecraft game asset. Any preserved upstream changelogs and verification documents describe upstream historical results, not new verification of this snapshot.

## Gradle wrapper

The unmodified Gradle wrapper JAR and scripts are copied from the pinned upstream source above. Gradle wrapper tooling uses Apache License 2.0. The wrapper JAR carries `META-INF/LICENSE`; an extracted copy is also included at [`client-mod/gradle/wrapper/LICENSE`](client-mod/gradle/wrapper/LICENSE). Script copyright and license headers are preserved. The POSIX wrapper is marked executable for this repository; its file content is unchanged.

- Gradle distribution selected by the wrapper: `8.14.3`
- Wrapper JAR SHA-256: `7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172`
- Wrapper JAR Git blob ID: `1b33c55baabb587c669f562ae36f953de2481846`
- [Pinned upstream wrapper](https://github.com/Campione01/MineClient-Bridge/blob/60e78940f7e7fa06116cf4fbc58df346ad617531/gradle/wrapper/gradle-wrapper.jar)

The wrapper is build tooling. No Minecraft, NeoForge, or compiled client-mod JAR is redistributed here; the build resolves its own dependencies.

## External controller

`external-controller/` is a separate original Python implementation. It consumes the bridge HTTP protocol; it does not embed Minecraft or upstream Java source. No license grant has been assigned to this original controller code; its README records that status. The presence of the upstream MIT license in `client-mod/` does not automatically license every unrelated file in this repository.

## External navigation controller

`navigation-controller/` is separate original Python source for bounded terrain parsing, local A* planning, and fake-only route-following, including a separate one-sample/yaw wire adapter and settling-readback simulation. It includes optional numeric-loopback HTTP/probe source, default read-only and limited to one explicitly accepted local action per transport instance. It has not been used against a game; live route-following remains blocked. No Minecraft source/assets are included. Upstream protocol references are recorded in its documentation. Its one explicitly sanitized captured-terrain JSON fixture replaces identities, translates horizontal coordinates, and rebases ticks; it contains no names, inventories, credentials, URLs, private paths, or raw session data. No license grant has been assigned to this original component; the `client-mod/` upstream license does not automatically apply to it.

## External building planner

`building-controller/` is original Python standard-library source for offline floor/wall blueprints, material accounting and conservative geometric support proposals. Every plan is explicitly non-executable. No placement primitive, network transport or vendored dependency is included. Examples are synthetic; the captured-terrain regression fixture is sanitized and is not a current action observation. No license grant has been assigned to this original component.

## Trademarks

Minecraft and other project names identify compatibility and provenance only. This project is not affiliated with or endorsed by Mojang, Microsoft, NeoForge, or the upstream MineClient Bridge author.
