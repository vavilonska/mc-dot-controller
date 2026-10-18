# Display-only callback cost correction

Base: frozen TEST1.1 manifest SHA256
5092d4b73e0f404e6318e715f5b34941cc3740dc4a1fb467d87cef79e76e4cd9.

The original TEST1.1 read TEST1_1_ORIGINAL_COMPACT_READ
failed terminally with compact_observation_budget_exhausted at final_context.
It completed all 45 terrain cells in 252893 ns; the callback had taken 41496861 ns
against 20000000 ns. That receipt is preserved and is not retried. It did not
measure individual state/context phases, so cold JIT or external-controller
inspection are possible costs, not established causes.

This correction allows 100000000 ns (100ms) for the display-only callback. The
measured 41.497 ms read fits with roughly 2.4× headroom. 100 ms is a cooperative wall-time
cost allowance, not permission for a two-tick-old observation or a real-time
scheduling guarantee. The clock, same original callback/tick, world/player/menu
context, future-timestamp rejection, exact 45/125-coordinate coverage and 64 KiB
response size checks remain unchanged. The ID-only terrain scheduler retains its
8 ms budget and hard cell cap. No action preflight or freshness budget changes.

Bounded timings now divide the callback into context, terrain_ids, state,
final_context and projection. State includes the capability snapshot bundle
(status/action/state/screen), not only player data. A nested measured
external_controller elapsed time and sample count help distinguish its cost.
Timings are available on successful native_timing and on budget rejection
compact_observation_diagnostic; they are request-bound diagnostic data, never
execution authority. Projection timings are captured before the final response
size-encoding check, which is followed by the same total budget check. Other
pre-existing non-budget exception paths may omit diagnostics.

Offline boundaries explicitly accept 41.496861 ms and exactly 100 ms, reject over 100 ms
and a reversed clock, and retain stage evidence on overbudget failure. Existing
context/epoch/future-coordinate/duplicate/size negatives stay enabled. The real
production projection and BridgeJson codec are used; this endpoint constructs its
own exact protocol envelope rather than ActionResponses. No new live success is
claimed until a separately authorized new original read completes.
