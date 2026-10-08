# MDC source handoff, 2026-10-08

This branch publishes an isolated recoverable candidate. It does not replace,
merge into, or deploy the repository-root version. Start in the directories below;
running tests at repository root would select the older main-line components.

## Contents and preservation

- `candidates/encounter-stage1.1/`: frozen `1.1.7-encounter-stage1.1` source,
  built on integrated.3. Native encounter stage 1 remains default-closed and
  offense-disabled. Includes client mod, resident, navigation, cursor, watchdog,
  building, gameplay helpers, older external controller, optional dry-run
  coordination, synthetic tests and acceptance plans.
- `test-tools/encounter-stage1.1-safety-v2/`: a partial, pure/offline harness
  source set. This is not the complete live Operator harness.
- `handoff/verification-20261008.json`: checks actually repeated for publication.
- `handoff/run_offline_checks.py`: portable offline-only test entry point.

The branch parent is main commit
`09e45143dc3e9b1aac5fa59c5a98c1e6a5274f14`. Every pre-existing root path is retained
with its original Git blob and mode. The candidate differs in 44 existing paths,
adds 138 paths, and lacks 11 paths present on main. These divergent versions are
intentionally kept separate; no claim of integrating main's newer terrain and
continuity work is made. A later merge needs explicit source-level review.

## Integrity and no new executable binaries

The frozen original `SOURCE_SHA256SUMS.txt` has 360 entries and SHA-256
`ef78b55d63d141cf8e2aadeaf3744d9fb54363db616b8ba2c8ca54c886a0839b`.
All 360 entries were verified against recovered bytes before selection.

359 original payloads are published unchanged: 358 text source/test/docs files
and one upstream icon already present in this repository. The Gradle wrapper JAR
is omitted from the candidate directory. Its identical existing root counterpart
can be used by the build command below; no new executable binary is published.
`PUBLISHED_SOURCE_SHA256SUMS.txt` checks just the 359 published payloads. The
original manifest is retained for provenance and still lists the omitted wrapper.

From repository root:

```sh
(cd candidates/encounter-stage1.1 && sha256sum -c PUBLISHED_SOURCE_SHA256SUMS.txt)
(cd test-tools/encounter-stage1.1-safety-v2 && sha256sum -c SOURCE_SHA256SUMS.txt)
python3 handoff/run_offline_checks.py
```

## Native build, for an equipped environment

Requires a Java 21 JDK (including javac) and Gradle 8.14.3, plus the normal
NeoForge/Minecraft build dependencies. The existing repository-root wrapper is
used with an explicit candidate project directory:

```sh
./client-mod/gradlew -p candidates/encounter-stage1.1/client-mod \
  --no-daemon --max-workers=1 -Dorg.gradle.parallel=false \
  -Pneo_version=21.1.255 -Pbridge.noRecompile=true clean test build
```

Alternatively use an already installed Gradle 8.14.3 with the same arguments.
Use `--offline` only when its required dependencies are already cached.
This command builds/tests; it does not install a mod or launch Minecraft.
Do not run the candidate's own `gradlew`: its wrapper JAR is intentionally absent.

## Checks actually repeated on 2026-10-08

- Candidate Python: 1,048 discovered, 1,047 passed, 1 skipped. The skip is the
  inherited comparison against an unavailable old-v5 frozen source.
- Node: 50 passed (42 action/encounter contract plus 8 NDJSON framing).
- Selected harness: 287 passed (63 receipt, 111 safety, 113 independent safety).
- Terrain static safety audit passed. Candidate checksum and publication
  allowlist checks passed. No credentials or private runtime data were found
  in the selected new payloads.
- Java compilation/JUnit was not rerun: this recovery workspace has a Java 21
  runtime but no javac or Gradle/dependency cache. The candidate's historical
  470 Java passes remain historical, not a new result or GitHub CI result.
- No game launch, real queue access, installation, live acceptance, backup
  rotation, authentication, account recovery or world restoration was performed.

## Harness omissions and recovery

The public subset keeps the exact receipt/encounter contracts, health guard,
post-trial safety ledger, synthetic fixtures and independently runnable tests.
It deliberately omits `game_operator.py`, `preflight_once.py`, `boat_trial.py`,
`tests/test_operator_flow.py`, `tests/test_recorded_receipts.py`,
`INDEPENDENT-HARNESS-TESTS.py`, `integration_tests/`, inherited-v1 migration tests,
`adaptation_tests/test_v2_compatibility.py`, the Operator-dependent independent
health suite, and private source-contract/baseline/final-delivery/review records.
Some depend on historical private paths and live evidence. No safety guard was
rewritten merely to make those files publishable.

The owner retains the full original harness in their private Library rescue
archive, `mc-pre-migration-rescue-20261007T153423Z.tar.gz`, under the
`mdc-encounter-stage1-live-tools-v2-20261007/` member prefix. The private handoff
provides its access reference. Obtain it from the owner when that fuller context
is authorized; do not reconstruct session evidence from synthetic fixtures.
The 287 current passes are only the published subset, not the old full 479 count.

## Safety and historical documents

Candidate and harness documents are preserved historical source documents.
Statements about earlier deployment/verification have their original time scope;
this publication does not establish current installation or live success.
The public harness subset is POSIX-specific (`fcntl`). Its plans describe future
separately authorized work, not permission to run a trial. All gameplay and full
environment recovery remain paused. Default gates and existing safety checks
are unchanged. Read `docs/ENCOUNTER-STAGE1.md` in the candidate and the subset
README before any later planning.

No world/save data, accounts, tokens, auth files, private relay/IPC configuration,
chat, live observations/reports, Minecraft distributions, mod runtime JARs,
compiled outputs, installers or build caches are added. Existing repository
licenses/notices remain in place; see candidate `NOTICE.md` for component-specific
terms. Publication is not a new blanket license grant.
