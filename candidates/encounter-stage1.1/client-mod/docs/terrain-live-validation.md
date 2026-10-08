# Limited live read-only terrain validation

Verified on 2026-10-05 against the previously installed terrain-only extension in
an isolated Minecraft 1.21.1 client. This is a small read-only interface check,
not runtime acceptance of the current movement extension.

## Passed live scope

- A 27-cell local cube was read successfully
- The equivalent local cube was read over seven pages
- A 17-cell vertical world-height boundary was read successfully, with
  out-of-world cells represented as unknown rather than fabricated air

No movement or combat is implied by these reads. The current movement extension
was not installed or used for this validation.

## Retained public regression evidence

A deliberately sanitized copy of the observed data is included at
[`navigation-controller/tests/fixtures/captured_terrain_schema1.json`](../../navigation-controller/tests/fixtures/captured_terrain_schema1.json).
Its world/scan UUIDs are replaced, horizontal coordinates translated and ticks
rebased. It contains no player names or identifiers, inventory, credentials,
URLs, private paths or raw session metadata.

Offline regression tests validate the captured schema, X/Z/Y cell order,
seven-page reconstruction (4/4/4/4/4/4/3), matching cube/paged local plans, and
blocking of out-of-world cells. These are compatibility checks of historical
responses, not proof that the observations are fresh enough for action.

## Not validated

- Maximum-volume terrain scans or worst-case frame-time behavior
- Navigation, combat, movement, multiplayer use of new primitives or arbitrary mods
- A complete, fresh execution observation suitable for the navigator

The captured state lacks full status brackets, its nearby-entity radius is zero,
and its pose/freshness fail the navigator's stricter action gates. See the
[navigator capture limits](../../navigation-controller/docs/PROTOCOL.md#captured-schema-regression)
and [current movement acceptance boundary](guarded-movement.md).
