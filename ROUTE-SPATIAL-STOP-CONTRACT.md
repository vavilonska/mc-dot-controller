# Versioned default-stop route spatial policy

Implementation candidate only. T37's rejected entity was not identified by its original receipt; its species and distance remain unproven.

Default `navigate_route_local` with reaction `stop` negotiates `movement-local-segment-spatial-stop-v1` when explicitly advertised. Older native implementations retain the prior profile. Explicit `defend_once` continues to use its separate reviewed threat profile. Mining, placement, collect and other movement profiles are not migrated.

The new policy retains complete loaded enumeration, identity/class/type consistency, bounded counts and encoded size, finite position/AABB/velocity/interpolation, projected AABB recomputation, current context, and same-callback fences. It never truncates or silently discards far entities.

Original audited entities (sheep, cow, chicken, pig, frog, boat, chest minecart and item) must have projected boxes strictly separated from the complete allowed player-body sweep. Rabbit is excluded because its hostile variant is not certified by these facts.

Additional exact vanilla passive classes are eligible only after native reader/mechanics audit. Their projected boxes must be strictly outside the entire terrain-validation context prism, a stronger exclusion than body-sweep separation. Unknown classes, unsupported variants, projectiles, explosives and unaudited harmful mechanics remain refusal at any distance. Geometry alone is not a certificate of unknown behavior or future AI motion. This version does not claim to make every remote hostile safe.

The separate closed frame includes each retained row and its explicit `outside_swept` or `outside_context` verdict. No selected-target guard, stop-only command, active-threat proof or defense handoff is accepted under this default-stop profile. Every non-success stops the route; unknown outcomes remain latched and are never retried.

Bounded native rejection diagnostics identify the actual rejecting phase and safely obtained type, or explicitly mark the type unavailable. They are descriptive evidence only: no admitted action, known-effect promotion, defense authorization or retry follows from them. They must survive the real response serializer and public receipt chain.

Offline acceptance requires exact-class audit, native pure/controller tests, production compilation, original-byte serializer/consumer tests, actual public MCP chain tests using a synthetic native endpoint, legacy/defense regressions and independent review. Genuine single-player loader, physics and ordinary-world usability require a later separate test copy.
