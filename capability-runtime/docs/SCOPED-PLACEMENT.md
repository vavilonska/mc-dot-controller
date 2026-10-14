# One explicit local placement

`place_local` is a primitive in the building group. The caller (including an outer AI planner) chooses an exact support coordinate, support face and expected static support state. It is not a blueprint executor. Existing `build` and `build_with_materials` remain unavailable for runtime execution.

Required arguments: `support`, `face`, `expected_support_id`, `expected_support_properties` (empty object), `expected_block_id` (`minecraft:cobblestone`), and `expected_block_properties` (empty object). The supported support IDs are the same twelve plain static full cubes admitted by `mining-local-observed-v2`. Target is exactly support plus the selected face normal, initially `minecraft:air`. The hit point is the support face center. The caller cannot supply arbitrary native intent fields.

Admission requires private singleplayer, active `request_only` execution policy and native `placement-local-observed-v1` negotiation mapped exactly to `place_block`. There is no fallback to legacy placement. The original Runtime, IntentClient, Watchdog and Resident owner chain, durable action reservation, observation budget, cleanup reserve, exact action identity and cancellation are preserved.

The selected main-hand stack must already be plain cobblestone. No movement, slot selection, procurement, bridge/pillar behavior, retries or automatic continuation occur. The native action is limited to 40 action ticks and 2 seconds, one ordinary vanilla placement effect and one ordinary use-item-on packet. A bounded complete static footprint and the existing conservative entity exclusion policy are checked. That entity policy projects 160 ticks, conservatively longer than this action's lifetime; it does not certify future dynamics.

Success requires native target-state observation, exactly one selected-stack decrement, all other native inventory/menu contents unchanged, neutral input, and two later increasing-tick Python inventory observations. These are client-observed facts, not server confirmation. Cancellation before the use attempt can be a known no-effect stop. Any unknown submission, after-effect failure, malformed or missing witness, or unconfirmed release retains uncertainty and never authorizes replay. HTTP 4xx alone does not prove placement was effect-free.

Offline tests include closed witness mutations and producer checks. The real JavaScript toolbox wrapper is tested through a Python subprocess and the original owner chain with a synthetic native endpoint. Such fixtures establish wiring and rejection behavior only; they do not establish game geometry, native callbacks or live placement acceptance. No deployment or game launch is part of this change.

## Reproducing offline checks

Run `python -B capability-runtime/tests/fixtures/generate_crystal_worlds.py` if the generated crystal geometry fixture is absent from a source-only export. It deterministically restores the existing unrelated planner fixture; its SHA-256 is `3a989c6e5ccb88dd0c126abc6734a95e17dcfa69a01d06d727a1e8f1f80a0ce9`.

Run the ordinary capability and Resident unit-test discovery with the repository's component directories on `PYTHONPATH`, plus `client-mod/mcp/toolbox-test.mjs` under Node's test runner. `client-mod/mcp/sync-toolbox-schema.py --check` checks the real JS/Python front-door schemas. Placement consumer fixtures live in `capability-runtime/tests/placement`; their files state explicitly that facts are synthetic. The pre-existing collect/combat Java-wire consumer suite additionally needs `MDC_NATIVE_WIRE_DIR`, and reports a skip rather than fabricating native inputs when those files are unavailable.
