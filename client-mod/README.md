# MineClient Bridge: client-actions source

Current development version: `1.1.6-client-actions.1`, based on [Campione01/MineClient-Bridge v1.1.5](https://github.com/Campione01/MineClient-Bridge/tree/60e78940f7e7fa06116cf4fbc58df346ad617531). Original MIT notices are preserved.

## Current path

This client-only NeoForge mod runs ordinary Minecraft movement and interaction each tick. The external resident process chooses tasks and routes; it does not simulate game physics or inventory.

The authenticated loopback API adds:

- `POST /control/action`: `follow_path`, `break_block`, `place_block`, `click_slot`
- `GET /control/action/status`: current or named action status
- `POST /control/action/cancel`: cancel exactly the named action
- Observed menu/slot data for external crafting decisions

Existing key/raw-key/look/mouse/text/command controls remain available with atomic direct-input takeover. Action IDs, recorded outcomes and process-session identity prevent blind replay. Outcomes are client-observed; `server_confirmed:false` is deliberate.

The new action path supports ordinary compatible multiplayer. It does not impose the older guarded-local experiments' singleplayer, full-health or half-forward-sample policies. Minecraft's normal reach, interactions and server permissions still apply. Old experimental classes/routes remain separate and cannot own input while a new client action owns it.

Read [the complete action contract](docs/client-actions.md) and [the resident controller guide](../resident-controller/README.md).

## Build and evidence

Requires Java 21. From this directory:

```sh
JAVA_HOME=/path/to/jdk-21 GRADLE_USER_HOME=/path/to/gradle-cache \
  bash gradlew --no-daemon --max-workers=1 -Dorg.gradle.parallel=false \
  -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
```

Use `--offline` only when the official dependencies are already cached. The binary-dependency pipeline compiles the complete mod without rebuilding Minecraft's own sources.

The final source build passed 75 JUnit cases against Minecraft 1.21.1 / NeoForge 21.1.255. No installed profile, token, client launch or live gameplay was used by the source implementation task. Installation/native-client restoration and real gameplay milestones are separate. See [verification](docs/client-actions-verification.md).

No compiled mod JAR is published here. The unchanged Gradle wrapper is build tooling.

## Existing observation and experiments

[Terrain API](docs/terrain-api.md), [limited earlier live terrain reads](docs/terrain-live-validation.md), MCP integration, previous guarded-local prototypes and their verification records remain available. Their historical acceptance boundaries should not be treated as the new client-actions contract.

[Security](SECURITY.md), [MIT license](LICENSE), [design references](THIRD_PARTY_REFERENCES.md) and [repository provenance](../NOTICE.md).
