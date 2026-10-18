> Current publication: [Recovery 2.5 source and bounded acceptance](docs/recovery-2026-10-18/README.md). All records below remain historical to their own checkpoints.

> 历史源码记录：本文各项结论仅适用于其原始截点。2026-10-16 当前交付、安装入口和验证边界见[工具箱交付说明](docs/toolbox-2026-10-16/README.md)。本次 Git 发布不改产品代码或继承旧 JAR 的实机验收。

# Combined local-route, terminal-defense and delivery source

This integration starts from published T34 commit
`d06a085baa2fbe315db84f8c26905c2c1d6316cf`. It adds bounded
`navigate_route_local`, explicit same-owner `defend_once`, and a documented
12-tool MCP delivery interface. The backend allowlist contains 20 capabilities;
actual availability remains per-profile negotiation through `mdc_catalog`.

The route and reactive-defense changes have source/offline evidence only.
A combined installed runtime, composed ordinary-world workflow and reactive
encounter remain pending. No historical microtrial is promoted to acceptance
of this new integration. Earlier T17/T32/T34 qualifications and unknown/HOLD
outcomes remain unchanged. Default reactions stay `stop`; explicit defense is
bounded, does not resume the ordinary task, and cannot retry an unknown action.

See [quickstart](docs/TOOLBOX-QUICKSTART.md),
[route contract](capability-runtime/docs/NAVIGATE-ROUTE-LOCAL.md),
[terminal defense](docs/DEFEND-ONCE.md) and
[capability status](docs/CAPABILITY-STATUS.md).
Public and runtime inventories remain separately frozen; no private trials,
worlds, credentials or generated artifacts belong in this source tree.

## Historical T34 consolidation

# Source consolidation with bounded descent

This update preserves the published T32 documentation baseline
`ade1df19b661701c96c6ffa088bc1df709fd3979` and starts from the reviewed 25-file
descent source, tests and contract-documentation delta. Final public integration
and test-portability edits are separately identified in the publication record.
Earlier diagnostic, representable-ray and consume-completion fixes, public
portable tests, and T17 and T32 acceptance qualifications are retained.
Runtime-only version metadata, raw private trial artifacts and installed game
state are not imported.

The explicit `navigate_step_down` capability selects
`movement-step-down-observed-v1`; existing flat movement, collection and legacy
navigation contracts retain their own scope. See
[scoped descent source](docs/SCOPED-STEP-DOWN.md),
[T34 qualified acceptance](docs/T34-DESCENT-ACCEPTANCE.md),
[earlier bounded fixes](docs/BOUNDED-RAY-AND-CONSUME-FIXES.md),
[T29–T31 acceptance](docs/T29-T31-ACCEPTANCE.md),
[T32 barrel withdrawal](docs/T32-CONTAINER-ACCEPTANCE.md), and
[capability status](docs/CAPABILITY-STATUS.md).

T34 acceptance belongs to its separately bound descent runtime. The original
case report failed its constant bbox/roof-height comparison; independent narrow
source-derived geometry review and saved endpoint verification support the
qualified result without changing that report or replaying gameplay. The source
integration does not claim deployment or live acceptance of a newly rebuilt
integrated artifact. Source, offline checks, live evidence, closure and saved
results remain distinct. `PUBLICATION-MANIFEST.json` and `SOURCE_SHA256SUMS.txt`
enumerate the reviewed public tree; runtime-source manifests are separate.

## Published predecessor evidence

The r2 source consolidation was published as commit
`f09382b4fd1a3e7324ad3af466b3a8b082de59a3`, with successful
[three-language CodeQL analysis](https://github.com/vavilonska/mc-dot-controller/actions/runs/38704084001).
The later documentation-only T32 commit
`ade1df19b661701c96c6ffa088bc1df709fd3979` preserved production/test source and also
passed its [CodeQL analysis](https://github.com/vavilonska/mc-dot-controller/actions/runs/38706299826).
Those results concern the named published predecessors, not this later source
integration. They are not full Gradle/NeoForge builds or new gameplay acceptance.
The earlier publication hold is historical. No credential/access expansion,
paused-task resumption or unknown-action replay is part of this update.

The sections below describe historical integrations; their file counts and
NOT_RUN statements belong to those historical checkpoints.

---

# Mainline integration: scoped mining, collect and combat source

This integration starts from published commit
`9bfd430ee5b7667ae6a036e42df03b1c5d503bac`, preserving its earlier fixes.
See [current evidence and capability boundaries](docs/MINING-COLLECT-COMBAT.md).

- Mining source: accepted preview freeze
  `983e40170b33dd4fd74adbc92d85d2adc297f4302891925ac8d8f15b690b6728`.
- Collect source: accepted offline freeze
  `c8630710c97f11f09809d5d6e79869af4fc8a731bb76adf1df58d957d8593fe0`.
- Combat source: reviewed offline delta freeze
  `9aba7055079fec2537698aa6360099b90e759bcea1b0523740afc225dcca9498`.
- Shared merges were reviewed by both source owners. A confirmed standalone
  collect null-serialization omission was fixed narrowly and covered with actual
  Java-emitted bytes validated by the real Python consumers. Response limits are
  unchanged. Main's adapter-copy and test portability fixes are preserved.
- All 128 production Java sources compiled into 321 freshly verified classes
  against pinned external dependencies, without a prior project JAR. Focused
  native policy/codec, cross-language, broad Python and existing Node checks
  passed; exact counts and the separately covered discovery skip are documented.
- This is not a complete Gradle/NeoForge build or transformed-mixin validation.
  Collect and combat remain offline-only; native combat functional and live
  tests are NOT_RUN. Cross-action reactions remain stop-only.
- T15/T16 mining functional/saved evidence is distinct from automation closure:
  T15 missed its bound; T16's automatic marker path retained HOLD, with manual
  completion in 145.707 seconds. Consult current evidence before interpreting
  any mining result as full automation acceptance.
- No artifact was deployed by this publication. Original worlds, paused tasks,
  credentials and configuration are unchanged. No raw private runtime evidence,
  worlds, binaries or dependencies are included.

## Previous T13 checkpoint (historical)

### T13 observed movement

This source-only integration starts from main commit
`27f3539a7ecd5adffe31d8b68611c7c054a1aa50` and preserves its prior adapter
consistency, test portability and discovery fixes. It adds the exact reviewed
15-file production delta: bounded single-authority movement-wire encoding and
strict consumer validation, plus action-owned tick lifetime/displacement checks.
See [protocol, tests and verification boundaries](docs/MOVEMENT-T13.md).

## Current evidence

- The frozen candidate has 748 source files; source-manifest SHA-256:
  `091ea46c4dfcddff3949f006f97ed655862b03ce8c77904f07d8a5cbd4ecd6ba`.
- The previously installed and live-tested artifact SHA-256 is
  `81d5b0d470516cf530223411c4d39cbd516ed2711694cd70533a3457a0a3c4c4`.
  That binary is not part of this source publication.
- T13's public request and native action succeeded for one cardinal flat-block
  movement. Native action tick was 13 with 34 completed continuation checks;
  observed displacement was 0.9276863 blocks, within the 0.23-block goal tolerance.
  Health and inventory remained conserved. Normal closure took 51.382848 seconds.
- Independent stopped-world verification accepted both saved-player mirrors at
  the exact stable observed destination, goal error 0.0743125 blocks. Saved health,
  inventory and equipment were conserved; original world and prior copy stayed
  unchanged. The closed-success seal SHA-256 is
  `074b6ba0d345757ca7687b85d6cded35c3062995a1b95750776403b44c050d71`.
- No broader pathfinding, future-dynamics guarantee, multiplayer/server-confirmed
  result, or completion of all 49 toolbox cases is claimed.
- T10 remains a known pre-admission size refusal without movement acceptance;
  its closure exceeded its bound. T12 remains an admitted action cancelled at
  native tick 1 with no successful continuation check; its rejected world tick
  was not captured, so the cause is not retrospectively established.
- Fresh integration checks passed: Resident 410, cursor 83, gameplay 64, toolbox
  57 and capability 651 Python tests; 131 existing Node tests; synthetic platform;
  37 native source checks, 168 synthetic-policy assertions, 52 generated-consumer
  checks; 8 codec, 6 full-reply Python tests and 38 Node boundary cases. All seven
  changed Java families and five support families compiled freshly. See
  docs/MOVEMENT-T13.md for retained retry and scope disclosures. These are not a
  full Gradle build or CI pass. Publication does not deploy or restart the game.

## Preservation and publication scope

Production files are copied byte-for-byte from the pinned active candidate.
Existing main-only publication metadata is regenerated deliberately; stale
candidate README/test files and generated artifacts are not copied over main.
No global health threshold is lowered: the exclusive predecessor of 20 used by
T13 is a case-only request boundary while health must remain exactly 20.

No credentials, account/profile data, private configuration, live queues, world
saves, raw runtime logs, screenshots, compiled binaries or dependencies are
published. Only reviewed source, portable synthetic tests and summarized evidence
are included. Preserve the original world; do not resume paused tasks, join
multiplayer, or retry actions with unknown outcomes.

## Earlier main integration record (historical R4)

#### R4 source integration

Source integration dated 2026-10-13, based on main commit
`09e45143dc3e9b1aac5fa59c5a98c1e6a5274f14`. Current source is integrated at the
normal repository package paths, not nested in a backup directory. Existing
main history, licenses, unrelated content and Gradle bootstrap are preserved.
Publication itself does not deploy or run the game.

### Snapshot and verification boundaries

- Immutable input: 746 files; source-manifest SHA-256
  `ae3d31eb02ce2f58f6ac05ad816e5eeed2911c8b736f8d9753a327296514342c`.
- The independently reviewed original R4 run accepted a genuine native compile,
  218 policy assertions, 157 codec assertions and 16 Python methods, including
  actual Java wire output consumed by Resident. These are prior focused R4
  checks, not a new full Gradle build or GitHub CI result for this integration.
- Original R4 artifact SHA-256:
  `f8371c9c6a129fc578423bdd13d7b849ba7cb6ef03ba0fe3941a26df640508da`.
  Its 309-member binary is intentionally not published in this source commit.
- T10 reached the public navigate_local route but native admission refused with
  `scoped_movement_response_evidence_too_large`. No movement occurred: this is
  a known no-effect refusal, not accepted live movement. Normal closure completed
  in 220.051 seconds, exceeding its 180-second bound by 40.051 seconds.
- All 49 toolbox cases have not been live-accepted. Previously accepted public
  hotbar and inventory-transfer cases do not establish R4 movement acceptance.
- The integrated tree's first broad offline pass collected 2,725 Python tests:
  2,721 passed, one failed, two errored and one historical check skipped. The
  failures exposed adapter-copy drift and nonportable fixture paths. The Node
  pass had 129/131 passes plus a separate platform-sandbox dependency failure.
- Finite integration fixes preserve Resident's observation-clock read-only guard
  in all three standalone adapters, add a cross-adapter regression, pin historical
  domain comparison to independently checked R2 hashes, make native-wire input
  optional when absent, and repair test discovery, tool lists and sandbox modules.
- After these fixes, affected Python suites reran: Resident 410, cursor 83,
  gameplay 64 and toolbox 57 passed; coordination 322 collected, 321 passed and
  one optional native-wire comparison skipped. All 131 Node tests passed; the
  Linux synthetic platform gate passed. The prior 651-test capability run and
  other unchanged suites were not unnecessarily rerun. One unavailable historical
  source comparison also remains skipped. This is local evidence, not GitHub CI.
- All 119 native main-source files remain byte-identical to accepted R4. No fresh
  full Gradle build or actual Windows/PowerShell platform validation was performed
  for this publication. Original focused R4 counts above remain prior evidence.

### Rebuild and tests

Keep sibling packages together. Consult package READMEs for commands. Java uses
Java 21, Minecraft 1.21.1 and the dependency versions pinned in
`client-mod/gradle.properties` and `client-mod/build.gradle`. The existing public
Gradle wrapper JAR and its license remain unchanged; no new JAR is included.
Before the full crystal planner Python suite, regenerate its deterministic
synthetic fixture:

    python3 capability-runtime/tests/fixtures/generate_crystal_worlds.py

That generator needs no saved game world. Generated compressed fixtures,
dependencies and compiled output are excluded. Historical source-comparison
scripts requiring private old working trees are not portable current checks.
Do not interpret historical README/test counts as a current full-suite pass.

### Publication boundaries

`PUBLICATION-MANIFEST.json` maps reviewed public files and publication edits.
`SOURCE_SHA256SUMS.txt` covers all committed files except itself. Native main-source bytes match the immutable R4 snapshot. Python runtime changes
are limited to copying the existing Resident observation-clock rejection into the
cursor and gameplay adapters. Test portability/discovery and publication docs
were adjusted; executable bits from main are preserved.

No credentials, accounts, private relay configuration, live queues, saved worlds,
raw runtime logs, screenshots, newly compiled JARs or dependencies are included.
Synthetic and explicitly sanitized test fixtures remain test data. This
publication does not authorize multiplayer access, resuming paused tasks or
retrying unknown action outcomes. Preserve the original game world.
