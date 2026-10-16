# Route terrain equivalence

This change applies only to registered continuation of `movement-local-segment-spatial-stop-v1`. It does not expand the allowed blocks or entity classes, change action ownership, retry a segment, resume interrupted work, or authorize defense.

## Admission and continuation

Admission and its final pre-registration checks retain the exact immutable terrain witness. Each continuation independently validates the complete current terrain prism: loaded cells, exact allowed block identity/class, cell role, collision/support geometry, empty fluids, and ordinary friction. Only exact vanilla oak/birch leaves may change their `distance` and `persistent` properties relative to admission. All remaining properties, including `waterlogged`, remain exact. Exact vanilla grass-block↔dirt replacement is additionally equivalent for CONTEXT cells only after the same current full-cube, fluid and friction checks. SUPPORT and CLEAR cells keep exact block identity. Mud, dirt paths, farmland, snow layers and hazards are outside this equivalence. All other block replacement, including leaf decay to air, remains a refusal.

After that validation, the final raw fence must bind the exact current callback capture. A property change during validation hooks is a refusal, even if that property could be equivalent across callbacks. Original serialized admission facts never change.

## Failure evidence

A bounded, non-authorizing `route_terrain_rejection` records the failing phase and first relevant cell, the original admission row, available current facts, and recomputed changed fields. Missing current facts stay explicitly unavailable. It does not convert an uncertain effect into a known outcome, erase motion/release failure, or permit another route segment.

## T38 evidence limitation

T38 completed three route segments. The fourth segment jumped and landed before `local_segment_footprint_changed`, with confirmed neutral release. Its original admission contains oak-leaf context cells, but the replacement footprint at the failing callback was not retained. The actual changed cell and property remain unproved. A separately retained later saved copy has four context grass-to-dirt changes and no leaf changes in the 180-cell prism. This supports a practical reason for context grass/dirt equivalence, but cannot establish the exact failing callback's state.

## Acceptance boundary

Offline tests must exercise the real native controller, collision/support validation, exact callback fences, reentrancy and original serialized failure evidence. Public entry tests must retain failure evidence and stop before the next segment. Offline success does not establish ordinary-world or live timing acceptance.
