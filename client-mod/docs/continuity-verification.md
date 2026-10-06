# Continuity v6 source and verification

Current version: `1.1.6-continuity.1`, Minecraft 1.21.1 / NeoForge 21.1.255,
Java 21. This record establishes source/build and offline behavior, not successful
live environment recovery, combat, navigation, crafting or placement.

## Preserved baseline

The Java baseline is the published `1.1.6-loaded-scan.1` source at commit
[`0799d0ee70a25ac91934d2f2139600403fa87c67`](https://github.com/vavilonska/mc-dot-controller/commit/0799d0ee70a25ac91934d2f2139600403fa87c67).
All 38 original main-source/resource files remain: 35 are unchanged, three are
intentionally updated, and `EnvironmentSteering` is added. Changes are confined
to new environment observations, recovery action parsing/execution and stable
placement evidence. Existing routes, scans, aim guards, visible-face mining,
world identity and terrain reading remain. All prior Java test sources remain
byte-identical; four environmental-decision cases are added.

Python retains the v5.1 terminal-recovery correction, ground-anchor-v3 geometry,
old recipe definitions, pending request identity and defense-epoch fencing. The
current increment adds goal-held environment recovery, adaptive observed route
prefixes, later stable crafting evidence and explicit mining-result semantics.
The old prototypes, build records and Git history remain available for comparison
or a deliberate rollback; no running installation is changed by publishing source.

The initial `1.1.5-environment-candidate.1` label was an authoring error, not a
feature rollback. It is superseded. The upstream MineClient Bridge `v1.1.5` label
in licensing/provenance remains correct and is not the current artifact version.

## Checks on the final public layout

- Full offline Java compile/test/build: 118 JUnit cases, no failures/errors/skips
- Official cached Java 21, Gradle 8.14.3 and ModDevGradle 2.0.148 binary pipeline;
  the complete mod compiles without rebuilding Minecraft's own sources
- Defense/recovery: 130 tests run, 129 passed, one historical-old-source comparison
  skipped because that separate historical candidate is not bundled
- Navigation and actual gateway contract: 67 passed
- Crafting/gateway: 30 passed; seven retained portability checks also passed
- Resident: 118 passed
- Changed Python sources compile; CLI help runs without opening live queues

The Python checks use fake residents/bridges, synthetic geometry and temporary
files. A passing input dispatch or stable client observation is not an independent
server acknowledgement. No live game control, credential read, private queue or
chat was used to prepare this publication.

## Artifact identity and licensing

The final frozen candidate's compiled artifact was 251,153 bytes, SHA-256:

`5dc898698ce903a9dc4fd362623d543c16b7512b8aa18b09d244b1825303dd13`

The public source rebuild is 251,872 bytes, SHA-256:

`4226705c9a004ab9da0a4a134f779ade06a456dd69d909d951f11d4f19c3bb08`

The difference is exactly one added `LICENSE` entry: this repository retains the
upstream MIT file and the existing Gradle build includes it in the JAR. Every
entry present in the frozen candidate is byte-identical in the public rebuild;
none is removed or modified. Both embed version `1.1.6-continuity.1`. The license
is retained instead of being deleted merely to reproduce the candidate hash.
No compiled mod JAR, build cache, raw test log or runtime report is published here.

## Current acceptance limits

Earlier versions have limited observed gameplay results, including the small
loaded-world scan and a separate successful sword/shield script. A subsequent
v5 watchdog zombie encounter failed: approach was blocked, no attack was
dispatched, and the player died. That failed encounter is not erased by earlier
success. v5.1 addresses a stale-terminal cancellation loop; v6 retains it, but a
new natural same-target crosshair-to-dispatch-to-health/death sequence is still
needed to establish its real-hit behavior.

V6 environment recovery, continuous route fragments and stable result semantics
are not live-accepted by this record. Ordinary play must establish actual water
or powder exit, fire clearance, subsequent resumption, a longer route, a craft
and a placement. A trapped area with no observed exit remains a blocker. No
random direction, unseen landing, guaranteed rescue, potion immunity, confirmed
critical hit or continuous survival claim is made.

Recovery alone defaults to `timeout_ms:0`: ordinary native input continues until
the observed goal or explicit/context stop. Empty or stalled routes retain
flotation rather than treating a message/observation delay as success. The outer
planner must observe an exit; it cannot provide new plans after process failure.
The operator retains STOP/direct takeover and the normal life/menu/world stops.
