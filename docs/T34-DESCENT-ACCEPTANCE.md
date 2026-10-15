# T34 qualified single block descent acceptance

T34 establishes one guarded single-block descent in an independent ordinary
singleplayer test copy through the public `request_only` job path. The public
job and native action succeeded, and the saved endpoint was independently
verified. Acceptance is qualified: the original case report failed a protected
state comparison and remains unchanged. A separate, source-backed geometry
review accepted the original evidence without replaying gameplay.

The capability is `navigate_step_down`, under profile
`movement-step-down-observed-v1`. Its integrated source contract is described in
[Scoped one-pedestal descent](SCOPED-STEP-DOWN.md) and the
[public request bounds](../capability-runtime/docs/NAVIGATE-STEP-DOWN.md).
Source integration and this bounded runtime result do not establish a general
navigation release or live acceptance of a newly rebuilt integrated artifact.

## Original action evidence

One original public job and one native movement action completed. The native
terminal was `succeeded` with reason `path_reached` after 21 action ticks.
The horizontal landing error was 0.19436702954779933 blocks, inside the unchanged
0.23-block arrival radius. Grounded, settled landing, two later increasing-tick
stable samples and a final sample were verified. Health and food remained 20;
inventory, armor and offhand were conserved. Neutral inputs and owner release
were confirmed.

The descent used ordinary movement input. No jump, teleport, creative flight or
velocity injection was used. The evidence is client-native observation, with no
independent server acknowledgement. Native callback sampling does not provide
continuous trajectory observation or global physical-distance accounting.

## Preserved original failure and additive geometry review

The frozen case comparator reported `protected_player_inventory_health_food`.
Its protected-state comparison treated six player bounding-box coordinates and
shelter `roof_y` as constants, although the production source derives them from
the moving player's pose. The original failed report, original inputs and
frozen comparator remain intact. The comparator still reproduces the failure.

The separate additive verifier accepts only the source-derived geometry change:

- Bounding-box fields must retain their exact shape and finite, non-boolean
  numeric types, positive unchanged dimensions, correct translation with the
  observed player position, and feet/center anchoring.
- Shelter `roof_y` must retain its required type and equal
  `floor(player.y) + 2`; all other shelter fields remain exact.
- The geometry tolerance of 1e-12 handles numeric representation only. It does
  not widen the 0.23 landing radius, vertical tolerance, grounded/low-motion
  requirements or ordinary vertical-velocity range.
- Normalization is applied to a deep copy only after those checks. All other
  frozen checks still run, including initial validation, exact original receipt
  and compressed-digest identity, RPC correlation, one submission/mutation,
  native witness, owner controls/release, inventory/gear/health/food/menu/hazard
  conservation and the later stable/final samples.

Independent review accepted this narrow correction. The retained adversarial
suite recorded 20 passing checks covering malformed geometry, non-derived roof
changes, protected state, ownership, stable samples and terminal-promotion
rejection. Review of those records is not a new gameplay run. Additive
revalidation reproduced the accepted original-evidence result without changing
the original failed case status or collecting a new runtime observation.

This is not a relaxed production admission guard, a larger arrival tolerance,
general permission to ignore changing protected fields, or a rewritten failure.

## Independently verified saved endpoint

One stopped-world reader exited 0 and retained 31 files. Independent re-decoding
used the prepared baseline and retained copy only, without invoking that reader
again or rereading the installed save. The complete saved projection agreed.

All four typed player representations contained the expected saved descent
endpoint, with health, food, inventory, armor and offhand conserved. These are
four representations of one player, not four separate successful descents.
All 180 compared corridor terrain states were unchanged.

Other player, entity and world metadata differed. The descriptive comparison
found 16 changed existing entity records, with none added or removed, and 311
changed region records. Those differences have no established causal
attribution; selected-field agreement is not whole-world equality.

Saved endpoint evidence does not establish native action success by itself,
verify every intermediate trajectory state, or exclude intermediate damage and
later item/state restoration. The original live evidence and additive review
remain necessary. The saved reader preserves the original functional failure
instead of promoting it to success.

## Ordinary closure

The final handoff records ordinary closure in 59.967 seconds from the original
origin. All nine original process identities and the bridge listener were
confirmed absent. Launcher, Resident, Watchdog and MCP owner exit codes were 0.
Java's numeric exit was unobserved and remains null; process absence and another
process's exit are not substitutes for that observation.

Closure, live action verification and persistence are distinct evidence layers.
Successful ordinary closure does not erase the original case-comparator failure.
No further live tests or action replays were started for this acceptance.

## Remaining navigation limits

The accepted geometry is one cardinal descent from an isolated full-cube
pedestal onto an ordinary dry full-cube floor. The source's complete 180-cell
footprint and original ownership, freshness, entity, input and unknown-outcome
fences remain required. This case does not establish terraces, obstacles,
partial blocks, fluids, step-up, jumping, multi-step routes or arbitrary-world
navigation.

The source admission centering tolerance is 0.10 blocks, while arrival tolerance
remains 0.23. An accepted landing need not satisfy the next segment's admission;
no composable-route or automatic chaining guarantee is made. Existing flat
movement, collection and legacy navigation contracts are unchanged.

T17's qualified collection and T32's automatic HOLD/manual final-window closure
retain their earlier interpretations. Other unknown and failed records remain
preserved. See [Capability status](CAPABILITY-STATUS.md). This document authorizes
no retry, paused-task resumption, new live case or multiplayer access.

## Exact runtime and evidence provenance

T34 used a distinct descent runtime, separate from the T29–T32 artifacts and
from the public-source publication inventory:

- Runtime artifact SHA-256: `9a85846eb2ad73b2e18ea054b2d58d0034320bd3ac219d5146ccce2a41836bda`
- Runtime-source manifest SHA-256: `3a8003993f31015e668e4bbcb98d0403b64e120c5bb2f9abfb623d0a65c02b47`
- Public-safe acceptance summary SHA-256: `d3727c8c967c0c86696845737de1fc9112e007a9151ed9b0b81f5f8a94746cff`
- Final handoff SHA-256: `d89a851f6aa36dd82eba812138a9889f8002cad4fff7caad7be70d3c0c57a600`
- Original failed case report SHA-256: `13e056ea1f6ad856b85f5d2b093e4b72487f54190aacc8605e6a1e91e3594133`
- Additive result SHA-256: `9094adc6c65f6dcb25b1c4cddced27277f81d8ff8f57b0d1b7056d5b61cf5417`
- Independent additive review SHA-256: `339fa4a674999506ab6f98fecb0c4cdb1c54b449ba4ac82c87d76bdbb7f369de`
- Independent retained re-decoding review SHA-256: `940a528721377573704aee792e4ee0a6e2856abb88a6c420188204369d233826`

Only bounded summaries and hashes are public here. Raw receipts, private paths,
world coordinates, player/account identities, runtime/action/job identifiers,
saved worlds and binaries are excluded. A source publication or successful
offline check does not deploy a new artifact or transfer this runtime's live
acceptance to a rebuild.
