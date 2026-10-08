# Guarded null-ownership wire correction

Verified 2026-10-05. Source version `1.1.5-terrain-guard-navigation.2` extends
reviewed `1.1.5-terrain-guard-navigation.1`; the prior source tree is preserved.
This is a narrow HTTP-response encoding change, not a guard-policy relaxation.

## Reproduced defect

`GuardedGameMovement.status()` puts explicit JSON nulls in `owner_request_id` and
`owner_action` when idle. `observedStatus()` also uses explicit null for an
unavailable `observation_id`. The previous Gson encoder omitted null object
members while writing HTTP bytes. Checking the pre-serialization JsonObject was
therefore insufficient: actual wire JSON did not contain the keys required by
the strict external adapter.

Minimal offline reproduction:

```json
{"sampled":false,"released":true}
```

Corrected encoding preserves the status facts:

```json
{"owner_request_id":null,"owner_action":null,"sampled":false,"released":true}
```

The adapter remains strict. Missing fields are still malformed/unknown, and are
not interpreted as idle. A non-null owner is still busy even if `released` is
true. An unavailable observation stays explicit null and cannot authorize input.

## Narrow implementation

`BridgeJson` uses Gson's public JsonElement adapter with a fresh JsonWriter for
each response. Null serialization is enabled only while writing the top-level
`guarded_movement` object. Other top-level objects, sibling null fields, array
handling, HTML/string escaping and configuration-file serialization keep their
previous behavior. No null facts are invented when an input object lacks a key.
The normal response and response-too-large fallback both use this codec.

No authentication, route permission, admission, observation lifetime, replay,
movement, turning, timeout, cancellation or input-state code was weakened. The
separate feature flags remain default-disabled.

## Verification

- Full offline target-version compile, test compile, JAR/sources-JAR and build passed
- **64 JUnit cases**, zero failures/errors/skips: 54 prior plus 10 serialization cases
- Tests reproduce the old bytes, round-trip the fixed idle/owned/null-observation
  response, preserve non-null values, retain unknown/missing facts, compare legacy
  escaping and array-null behavior, assert no source-object mutation or writer
  state leakage, encode actual pure-core lease statuses, and check HTTP wiring
- Independent review found no remaining source blocker. Cached Gson 2.10.1 and
  2.11.0 each passed 1,018 compatibility comparisons, including 1,000 concurrent
  encodes across eight threads; ordinary nonfinite-number handling also matches
  the previous encoder. These checks did not initialize Minecraft
- Existing 150 guarded-action checks, 37,371 terrain assertions, 13 dispatch checks
  and the static terrain audit passed
- Minecraft 1.21.1 / NeoForge 21.1.255, Java 21.0.12.1, Gradle 8.14.3,
  official ModDevGradle 2.0.148, cached offline binary pipeline

Build:

```sh
JAVA_HOME=/path/to/existing/jdk-21 GRADLE_USER_HOME=/path/to/existing/gradle-cache \
  bash gradlew --offline --no-daemon --max-workers=1 -Dorg.gradle.parallel=false \
  -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
```

Artifact identity:

- JAR: `mineclient-bridge-neoforge-1.21.1-1.1.5-terrain-guard-navigation.2.jar`
- JAR SHA-256: `bcb9e892089bbc286f22f8d67e01e237361c495fd354993354e743b1df20a5c8`
- Sources JAR SHA-256: `11b50d35f5a512630c5d070b8879d4945595297d69ff800b612e7e937d50e9a5`

## Explicit limits

This defect would block guarded-action preflight against the strict adapter. It
has **not** been established as the cause of a separate generic read-only probe
failure; that needs its own sanitized stage/status evidence. No live HTTP probe,
credential read, installed-file replacement, restart, game input or world change
was performed for this correction. Successful source tests are not live acceptance.
Existing movement/turning scope and [runtime limitations](guarded-turning.md) remain.
