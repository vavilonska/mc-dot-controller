# Bounded terrain refresh (terrain-refresh.1)

## Evidence and scope

The restored `1.1.6-loaded-scan.1` resident can stop combat with
`invalid_or_stale_terrain_page`. That original parser message merges invalid
schema/coverage, mixed scans/worlds, clock/tick expiry, and scan-budget failures.
The failed live page was not retained, so its particular rejection cause cannot
be reconstructed. This patch is not a claim that the observed failure was
definitely an expired cursor, slow page, or server tick anomaly.

The old source has two reproducible recovery gaps: an otherwise valid aged page
gets no fresh read attempt, and a failed refresh can leave the preceding terrain
cache available. Synthetic regressions establish both behaviors and the change.
They do not establish live survival, actual terrain freshness under load, or
server-confirmed combat results.

This update is applied to the public v6 source at commit
`249fa6e46ae0fa80cc0a7197c3a5e63ded2359c1`. Its three affected runtime files
match the restored baseline. All other v6 features, including environmental
recovery, stable crafting/placement and adaptive navigation, are retained.
The refresh change does not modify the Java mod or the watchdog.

## Contract

- A scan first discards the preceding cached grid/cells/timestamp
- Page schema, exact coverage, ordering, world and generation validation remain
  strict; malformed old pages are integrity failures, not refresh candidates
- Only a structurally valid aged page/grid, an explicit 409
  `stale_terrain_cursor`, or explicit 429 `terrain_rate_limited` may start one
  whole new scan. It gets a new initial state, assembler, initial terrain GET
  and cells. No invalid/partial page or poisoned cursor is continued
- At most two attempts, 32 terrain-page requests per attempt, 50 ms pacing, and
  a shared 3-second cooperative admission deadline. State and page GETs are not
  started after that deadline. An already-running GET is subject to its existing
  transport timeout and may finish later; this is not a hard 3-second latency cap
- A changed world/player/action session, tick reversal, malformed response,
  authorization error, busy admission, or transport uncertainty is not retried
- State identity sections must be objects with nonempty identity strings;
  malformed state is a controlled failed observation, not an uncaught exception
- All attempts failing still reports failure and leaves an empty cache. There
  is no success substitution, automatic controller restart, or action replay
- Cache freshness is measured from the successful attempt's start, never made
  newer by stamping the final page's arrival
- `walk_to` plans using the newly assembled grid. Native combat still releases
  forward before a scan, returns after refresh, and reobserves/revalidates the
  target and current corridor on a later tick before moving or attacking
- The existing watchdog continues to fail-stop on exhausted refresh or integrity
  errors. It is unchanged; successful refresh no longer becomes a terminal combat
  error. This patch does not automatically rearm an already-disarmed watchdog

Session/observation snapshots gain `terrain_read`: outcome, attempts, pages,
last machine rejection and elapsed milliseconds. It contains no coordinates,
page/cursor contents, world/player IDs, chat, token, or credential. The existing
top-level schemas and backup formats are unchanged. Direct parser consumers keep
the legacy page-error string and may inspect `TerrainPageError.detail` and
`.refreshable`; the resident exposes the more precise cause on failure.

## Loading, verification and rollback

Only these three runtime Python files change:

1. `navigation-controller/navigation_controller/terrain.py`
2. `resident-controller/resident_controller/world.py`
3. `resident-controller/resident_controller/controller.py`

The patch also adds offline tests, this document, and public-file-list entries.
No Java/mod, watchdog, authentication, launch configuration, permissions or
backup schema changes are required.

This deliverable does not deploy itself. The sole existing game operator should
choose a safe, grounded location, stop new intent producers, stop the existing
watchdog, confirm cancellation/input release and that its queue writer exited,
then normally stop the resident and confirm its exit/release. Preserve copies of
the three matching baseline files; verify hashes and dry-run the patch before
applying. Do not overwrite divergent source blindly.

Restart the resident once using the same existing authorized launcher and
authentication flow, without reading/copying credentials into commands or
reports. Verify exactly one resident, a new resident session, and the additive
`terrain_read` field. The game/JVM/mod need no restart or rebuild. If desired,
the existing watchdog can then be started once through its existing sole-writer
procedure and verified armed/fresh. Do not run a second writer, hot-reload a live
Python module, or repeatedly restart to work around recurring failure.

Minimum later live check: on safe level ground, read a small terrain scan and
confirm a complete current grid and diagnostic outcome. A naturally encountered
retry must show a new scan attempt and a later fresh combat/route observation;
normal success alone does not prove the failure path has been exercised. No
high-platform/edge, jumping, or sneaking acceptance is part of this patch.

If the resident cannot load or the smoke check fails, stop it and confirm input
release, restore the three exact baseline files, then use the same existing
launcher once. A rollback should not change game state or authentication. If
release or process ownership is uncertain, leave automation stopped for the
operator instead of starting another controller.

## Offline checks

From the public controller root, with Python 3.10+ and standard library only:

    PYTHONPATH=resident-controller python -m unittest discover -s resident-controller/tests -q
    PYTHONPATH=navigation-controller python -m unittest discover -s navigation-controller/tests -q
    PYTHONPATH=resident-controller python -m unittest discover -s defense-watchdog -p 'test_*.py' -q
    PYTHONPATH=resident-controller:navigation-cursor WATCHDOG_CANDIDATE="$PWD/defense-watchdog" python -m unittest discover -s navigation-cursor/tests -q
    PYTHONPATH=resident-controller:gameplay-helpers WATCHDOG_CANDIDATE="$PWD/defense-watchdog" python -m unittest discover -s gameplay-helpers/tests -q
    (cd building-controller && python -m unittest discover -q)
    (cd external-controller && python -m unittest discover -q)

The final v6 public-layout checks run 828 Python tests: 827 pass and one
historical old-v5 source comparison is skipped because that frozen source is
not bundled. Breakdown: resident 142 (including 24 focused refresh checks),
navigation parser/planner 254, watchdog 130 (129 pass, one skip), route cursor
67, gameplay helpers 37, building planner 83 and combat prototype 115.
Compile checks and resident/navigation/gameplay CLI help also pass.

These are local offline checks, not GitHub CI or live acceptance. No live queue,
game controls, credential files or game endpoints are accessed by the tests.
Java is unchanged and was not rebuilt as part of this patch. The earlier
restored-baseline results (133 resident, 254 navigation and 110 watchdog passes
plus one skip) are separate from these public-v6 verification results.
