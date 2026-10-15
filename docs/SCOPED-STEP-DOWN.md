# Scoped one-pedestal descent

The candidate adds `navigate_step_down` under native profile
`movement-step-down-observed-v1`. The goal is exactly one cardinal block away and
one block lower. Its complete 180-cell native footprint supports one isolated
full-cube pedestal above an ordinary full-cube floor; all remaining cells must be
dry literal air. Terraces, jump-up, obstacles, partial blocks, fluids and unknown
geometry are outside this slice.

The public mode must be `request_only`. MovementBudget must remain unarmed.
Recommended public bounds are deadline 60 seconds, maximum actions 2 including
one cleanup reserve, maximum observations 64, no reflex actions. The single
native movement is limited to 8 seconds / 160 action ticks and a bounded
20-action-tick airborne interval. These are operational limits, not a benchmark
or an added harness observation-age gate.

The explicit descent capability alone selects this profile. Existing flat
movement and collection retain their original native profiles; legacy
`navigate` and `navigate_loaded` are not thereby enabled. No retry or resume is
permitted after an unknown action outcome. There is no general route, chaining,
future entity dynamics or global physical-distance accounting guarantee. Source
centering is .10; settled destination tolerance remains .23, which need not
satisfy another segment's admission.

The production Node MCP stdio → configured Python toolbox → Owner/Runtime →
Intent/Watchdog → Resident test is a real entry-chain test with a synthetic native
Bridge endpoint. Its transcripts and original Runtime/toolbox journals can be
retained separately. Native-generated wire consumer tests and Java tests are
separate offline evidence. None substitutes for an ordinary-world functional
trial on an independent copy using the same final built bytes. Installation and
live acceptance must be reported separately; this document does not assert them.

See [public request and detailed bounds](../capability-runtime/docs/NAVIGATE-STEP-DOWN.md).
