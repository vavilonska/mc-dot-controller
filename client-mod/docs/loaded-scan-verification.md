# Loaded-scan source and limited runtime evidence

Current source: `1.1.6-loaded-scan.1`, Minecraft 1.21.1 / NeoForge 21.1.255.
The published `gradle.properties` defaults now match this exact tested target.
The compatible dependency range is retained; lower NeoForge versions are not
claimed as tested by this record.

## Offline verification

- Complete offline Java compile/test/build: 114 JUnit cases, zero failures/errors/skips
- Official cached Java 21.0.12.1, Gradle 8.14.3 and ModDevGradle 2.0.148 binary pipeline
- Resident protocol/controller suite: 109 tests, including aim, native combat and loaded scans
- Source archives and publication payload verified by checksums
- Published mining regression fixtures use synthetic origin-relative coordinates;
  the captured gameplay location is not retained, and the normalized tests pass
- Crafting helper: 23 offline fake-queue checks, with explicit pending/busy and no-replay handling

The publication rebuild using the corrected default version/NeoForge metadata
produces the same final mod JAR SHA-256:

`1986b612f1b354ea42c1195e70731f6b63e6fb3eb7b916686599c6ddb5e9776a`

No compiled mod, private build log or raw runtime report is published here.

## Limited observed live results

The updated client connected and a small loaded-world block scan completed:
4,864 positions, 41 coal blocks, 79 ms reported elapsed time, 3 client ticks.
These are aggregate results from that one query. No actual target coordinates,
player identifiers, server addresses, inventory snapshots or world data are
included in this document.

The crafting helper's reported successful live recipes are crafting table,
wooden pickaxe, stone pickaxe, furnace, sticks, stone axe and torches. Other listed
recipe shapes, including iron tools/armor and shield, have offline evidence only.

A later short sword/shield script reported one successful zombie encounter:
four attack dispatches, observed target-dead stop, and player health staying 20.
This is a bounded observed gameplay result, not a server-confirmed attribution.
The independent v5 defense watchdog and external resident melee correction were
later deployed; the loaded melee marker 2 and one armed v5 process were confirmed.
No mod source change was required. Complete v5 natural-encounter, blocked-approach
and retreat acceptance is still pending; the earlier script is not that evidence.

## Not established

Aim/combat dispatch counts are not hit or kill confirmations. Maximum-scale scan latency, frame-time bounds,
every biome/surface/water filter, world-wide completeness and universal mining
visibility are not established by the small query or geometry fixtures.

Loaded scans read only client-loaded data. Unloaded/missing regions remain unknown;
observations age and pages/tick slices are not an atomic world snapshot. Counts,
clusters and candidate sites do not imply ownership, permission, navigability or
build safety. No game action was performed to publish this source update.
