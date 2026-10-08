# Isolated v18 source publication preparation

This candidate is prepared against the GitHub refs read on 2026-10-08:

- `main`: `09e45143dc3e9b1aac5fa59c5a98c1e6a5274f14`
- `mdc-handoff-20261008`: `68dd012841aa84a5d4caf1115aba1623093239cd`

It updates the existing isolated `candidates/encounter-stage1.1` layout. All 234
root/main blobs and modes remain unchanged. No main integration, pull request,
remote publication, deployment or game action is performed by preparing this
snapshot. A later publication does not itself deploy or authorize gameplay.

## Selected content

The source increment includes callback/read timing, retreat-window bounded-work
improvements, active encounter interruption evidence, explicit terminal pause,
boat mount/dismount contracts and the accompanying synthetic regressions. The
public safety subset also includes generic dependency-injected registered-case
entrypoints, no-retry unknown-effect handling and append-only closeout evidence
validation. None contains a configured live Operator.

The v18 source selection preserves exact source bytes. The public harness README
and its checksum manifest are regenerated because the environment-specific
Operator closeout how-to is deliberately omitted. Existing license, copyright
and third-party reference notices are retained. No new blanket license grant is
made for independent components; see `NOTICE.md` and the candidate notice.

New/changed payloads are UTF-8 source, synthetic tests, documentation and checksum
metadata. The selection excludes world/save/profile data, real observations,
player/entity/server data, chat, account/auth/token/relay configuration, private
Library references, private case paths, third-party game assets, runtime JARs,
compiled outputs, installers and build caches. Fixed zero-prefixed UUIDs and
obvious synthetic-token sentinels in tests are intentionally synthetic.
No actual credential file was read to validate this source selection.

The existing main-line wrapper JAR and upstream icon remain inherited repository
files; no new executable binary or game asset is added. Raw build/test logs are
not part of the public payload because they contain local filesystem paths.

## Checks repeated on the selected source

- Candidate Python: 1,091 discovered; 1,090 passed and one inherited historical
  source-comparison skip.
- Node: 66 contract tests plus 8 NDJSON framing tests passed.
- Public harness: 343 tests passed, using temporary files and synthetic clients.
- Java 21 / Gradle 8.14.3: 534 tests passed; offline `test build` succeeded with
  the already available dependency cache. This is not a cold-cache guarantee.
- Java HTTP codec to actual resident mailbox to harness: 7 offline wire-contract
  tests passed. These use generated synthetic observations and temporary queues.
- Candidate/harness manifests and terrain static safety audit passed.

The standard runner is `python3 handoff/run_offline_checks.py`. For the Java
build, use an installed Java 21 JDK and Gradle 8.14.3 with:

```
gradle --offline --no-daemon --max-workers=1 -Dorg.gradle.parallel=false \
  -Pbridge.noRecompile=true \
  -p candidates/encounter-stage1.1/client-mod test build
```

Omit `--offline` only when fetching official dependencies is separately allowed.
The separate wire test documents its `JAVA_HOME` and `MDC_NATIVE_CLASSPATH`
requirements. The ordinary runner's final statement excludes Java/gameplay
because it does not invoke them; the Java results above come from separate runs.
These are local offline results, not GitHub CI or live acceptance.

## main integration audit

Comparing the candidate subtree to current main gives 174 identical files,
48 changed paths, 162 candidate-only paths, and 12 main-only paths. Counts include
source manifests and documentation; they do not include local build products.
The full path classification is `main-v18-differences.json`.

An overlay was made solely for compatibility testing: candidate implementation
files plus main's original tests, with separate import roots and no game access.
Main's four selected suites passed on main (one inherited skip). They are not
all compatible with the candidate:

- Resident: main's 142 checks yield 2 failures and 9 errors on the candidate.
  Missing mining result evidence and stable crafting contracts are real
  differences. One terrain test deliberately disagrees with the candidate's
  bounded fresh-read treatment of page game-time reversal.
- Cursor: main's 67 checks yield 7 failures and 21 errors. The candidate lacks
  ground anchors and adaptive observed route slices.
- Watchdog: the candidate cannot import main's environment recovery tests because
  the module is absent; a ranged-tactics fixture also assumes a different update
  contract. That run discovers 112 checks, with 2 errors and one skip, versus
  main's 130 checks. Do not interpret the smaller run as full coverage.
- Gameplay helpers: main's 37 checks yield 7 failures and 1 error, including
  stable crafting observations, time-regression rejection and recipe-set drift.

Native source review separately confirms that the candidate drops main's
`recover_environment` action and observations, `EnvironmentSteering`, and
stable-placement confirmation. Candidate Java passes alone do not establish
compatibility with those main-line features.

Terrain refresh itself is substantially preserved: the candidate adds read
instrumentation to main's bounded refresh/cache invalidation code. Its parser's
intentional semantic difference is classifying a page tick reversal as a stale
batch eligible for a fresh complete GET scan under the existing budget. Strict
world/identity/integrity rejection and no POST replay must remain intact.

## Minimum safe integration path

1. Save/review this isolated candidate increment first. Keep all root/main files
   unchanged; do not replace main with the candidate subtree.
2. Start an integration branch from the rechecked current main HEAD. Port shared
   wire/nullable contracts, timing instrumentation and pure native helper classes
   in small reviewed increments, retaining both suites.
3. Resolve native action dispatch, request validation, player environment
   observations and stable placement explicitly. Preserve main's environment
   recovery while adding encounter/boat actions, identity guards and pause
   contracts. Resolve zero-lifetime recovery deadlines separately from bounded
   encounter deadlines rather than copying the candidate dispatcher wholesale.
4. Preserve main's watchdog environment recovery and cursor ground-anchor /
   adaptive-slice behavior. Add candidate menu recovery and navigation guards
   without dropping those contracts. Reconcile stable mining/crafting evidence
   in resident and helpers, including the differing recipe surface.
5. Restore all missing main regression files. Update only the specifically
   reviewed page-tick-reversal expectation to the approved bounded fresh-read
   contract; retain all other corruption/context/no-replay assertions.
6. Run the full main and candidate Python suites, Node contracts, native JUnit,
   wire tests and focused cross-feature checks on the merged source. Any later
   live validation remains separately scoped and authorized.

A Git merge of the namespaced handoff branch could preserve all root files
without a textual conflict, but that would only save `candidates/`; it would not
upgrade or reconcile root production components. The counts above are source
differences under path remapping, not a claim that Git reported 48 conflicts.

The production integration is not a safe small automatic merge. No conflicting
production source was silently edited as part of the publication preparation.
