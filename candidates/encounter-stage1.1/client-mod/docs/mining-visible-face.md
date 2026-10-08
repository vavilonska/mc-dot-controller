# Visible-face mining fallback

Included in `1.1.6-loaded-scan.1` alongside aim and loaded-world queries.
This document describes the source correction and geometry evidence; it does
not claim that all mining situations were exercised in the game.

## Regression geometry

A center-directed ray can hit an overhanging block before the requested lower
block even when a different ordinary ray can reach the lower block's visible
face. The public regression uses an origin-relative synthetic two-block fixture;
no captured player position or real-world block coordinates are retained.

A genuinely intervening leaf or solid block must still obstruct mining. The
fallback does not ignore, remove or mine through intervening blocks.

## Minimal change

`ClientActions.mine` first tries exactly its original center aim and real pick.
Only if that fails does `MiningAimPoints` propose centers and four inset points
on each unit-block face oriented toward the current eye. There are at most three
facing planes and **15 fallback points**. Face centers precede inset samples;
the coordinates remain on the target faces, away from ambiguous shared edges.

Every candidate uses the unchanged `pick(mc, pos, null)`: actual renderer picking,
exact target block identity and ordinary block interaction reach are mandatory.
A wrong block, entity, miss or out-of-range hit is rejected. Only then does the
existing continuous mining/input code run. No new endpoint, command, movement,
packet, reach extension or direct world mutation is introduced. Placement and
external controller code are unchanged. If every sample fails, the view is reset
to the original center and the same failure is returned.

The proposals use the unit block faces, while the actual game's pick determines
its real outline. This is bounded practical sampling, not proof that every tiny
exposed fragment or arbitrary modded shape will be found.

## Checks

- Targeted `MiningAimPointsTest` + existing `ClientActionsTest`: 21 passed
- Synthetic origin-relative geometry regressions cover an overhang and also cover
  fully occluded targets, a partly visible face, out-of-reach targets, all six view
  directions, bounded unique inset points, negative coordinates and malformed eyes
- Source-contract checks verify the center fast path, real pick/target/reach checks,
  and that no attack starts inside the candidate-search helper
- Current combined loaded-scan Java suite: 114 passed; the preceding aim/mining suite had 95 cases

These geometry fixtures are not a Minecraft physics/raycast simulation. The Java
adapter compiles against Minecraft 1.21.1 / NeoForge 21.1.255, but actual client input and visual behavior remain distinct from these geometry
checks. Source publication performs no game operation or installation.
