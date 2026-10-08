# Terrain refresh latency observations (schema 1)

This is an offline diagnostic candidate, based on integrated.2. It does not fix
latency and has not been installed, restarted, or exercised against Minecraft.
The terrain-latency patch itself leaves Java/mod source unchanged. The combined
integrated.3 candidate also includes reviewed Combat/TerrainReader changes; see
[the union scope](../../docs/INTEGRATED-DIAGNOSTICS.md). The 2 ms cooperative
sampling budget, terrain protocol, planner,
256 KiB non-frame response bound, 128-cell page limit, complete coverage,
identity/world/tick checks, 32-page cap, two-attempt cap and shared 3-second
Python monotonic deadline remain unchanged. A fixed `game_time` is allowed.

## Where the evidence appears

`WorldCache.terrain_read` retains the existing outcome/attempts/pages/last_rejection/
elapsed_ms fields. `diagnostics` is additive. `Resident.publish()` already includes
this object in session status. Successful observations already include it in
`result.terrain_read`. A failed explicit observation whose terrain scan actually
started now includes its own `terrain_read` alongside the failed request's reason;
it is attached to that exception and request, not inferred from the latest cache.
A bad bounds request or failure before a new scan cannot inherit an older scan.
Later reads may replace session status, so retain the exact per-request result.

There are no new requests, endpoints, retries, writes, timers, worker threads or
background sampling. The request wrapper invokes the original `bridge.request`
exactly once. Transport metadata is reset at the beginning of every request. No
bearer, response body, cells, player UUID, action-session value, or cursor is copied
into the diagnostic object.

## Top-level diagnostics

- `schema_version`: 1.
- `clock`: `python_monotonic`; `time_origin`: `scan_start`.
- `total_budget_ms`: the original shared deadline minus the original start (3000).
- `actual_attempts`: number of initial-state request invocations actually begun,
  including an initial-state request that raises. A loop iteration refused by its
  first deadline guard is not counted. Existing `terrain_read.attempts` retains
  its prior loop-entry meaning; `attempts_entered` makes that distinction explicit.
- `attempts`: ordered attempt records, at most two.
- `total_elapsed_ms` and `remaining_total_ms`: measured at the latest completed or
  rejected attempt boundary. Remaining time can be negative; no budget is reset.
- `network_elapsed_ms`, `http_queue_elapsed_ms`, `python_cpu_elapsed_ms`: null,
  with `attribution_status: "unknown"`. No such measurements exist in this patch.
- `clock_observation_errors`: extra diagnostic clock reads that raised or returned
  a non-finite/non-numeric value. This only invalidates that measurement and does
  not change, suppress, or replace the original safety clock checks.

All offsets/durations are milliseconds, rounded to three decimal places, relative
to this scan's actual monotonic start. They are not Unix timestamps, game ticks,
Java `nanoTime` timestamps, or precise cross-process correlation clocks. A rounded
0 ms means below this output precision; it does not mean zero work occurred.

## Attempts and stages

Each attempt records `attempt`, `initial_state_requested`, `started_offset_ms`,
`budget_at_entry_ms`, `assembler_budget_ms`, `elapsed_ms`, `ended_offset_ms`,
`remaining_total_ms`, `outcome`, `last_rejection`, `original_rejection`,
`rejection_phase`, and an ordered `stages` list. The assembler budget is exactly
the original `remaining` argument; it is not a separately granted budget.

Each stage records `phase`, optional per-attempt `page`, `start_offset_ms`,
`end_offset_ms`, `elapsed_ms`, `remaining_total_at_start_ms`,
`remaining_total_at_end_ms`, `attempt_elapsed_at_end_ms`, `timing_status`,
`outcome`, and `original_rejection`. Phases are:

- `initial_state` and `final_state`: the actual state request wrapper.
- `terrain_page`: one actual page request wrapper, in request order.
- `assembler_init`: original assembler construction.
- `assembler_add_and_collect`: original page validation/add and the resident's
  loaded-cell collection. This is not a pure parser-only measurement.
- `assembler_finish`: original final grid construction/freshness validation.
- `page_interval`: the original 50 ms sleep, measured including scheduling delay.
- `retry_interval`: the original 50 ms retry sleep, after the prior rejection.

`retry_interval` is stored with the rejected attempt for chronology, but happens
after that attempt's recorded end; it is excluded from that attempt's elapsed
work and included in the subsequent overall scan time. Stage sums are not a
complete accounting of the scan: safety checks, state context validation, loop
bookkeeping, diagnostic construction, and output work can fall between stages.
Nested request roundtrip and Java sampling values must not be added to stage
elapsed durations.

`rejection_phase` also names non-timed checkpoints: `attempt_deadline`,
`initial_state_validation`, `initial_state_deadline`, `page_deadline`,
`final_state_deadline`, `final_state_validation`, and `completion_deadline`.
This distinguishes the same public stale-clock error arising at different checks.

## Request evidence

Request stages additionally contain:

- `method: "GET"`, `route`: `/control/state` or `/control/terrain`, without query.
- `request_start_offset_ms`, `request_return_offset_ms`, `roundtrip_ms`,
  `roundtrip_status`. The two clock samples directly bracket the single call,
  including exception returns. Wrapper stage duration is separate.
- `roundtrip_scope: "bridge.request_including_decode_and_close"`. It covers the
  synchronous Python call, including HTTP handling, waits, response reads, JSON
  decoding, and close. It is not a wire RTT, pure network time, or Java CPU time.
- `http_status`: actually observed status in the built-in transport, or null.
- `response_bytes_read`: `len(raw)` from that exchange's one bounded HTTP read,
  or null when no successful read result exists/custom transport lacks evidence.
- `response_bytes_status`: `observed_read_length`, `limit_exceeded_prefix`, or
  `unknown`. An oversized read records the observed `bound + 1` prefix, not the
  complete body size. Headers/TLS/framing overhead are excluded. A read exception
  leaves bytes unknown, even if some bytes may have been received internally.

Custom/Fake clients report unknown bytes; JSON is never re-encoded to guess the
original response size. There is no network-versus-queue-versus-CPU subtraction.
The known synchronous built-in `Bridge` provides bytes; subclasses do not silently
inherit a claim that their override captured a matching exchange.

A returned page contains `page_reported` scalar header fields: offset, next_offset,
returned, total_cells, complete, budget_exhausted, game_time, response_game_time,
generation, world_generation, dimension. These are reported claims before
assembler validation, not proof of complete/safe terrain. Missing or non-scalar
fields become null. No body or cell records are retained here.

`java_read_elapsed_micros` is the reported nonnegative integer, with
`java_read_elapsed_status: "reported_unvalidated"`; otherwise null/`unknown`.
A successful assembler stage is separate evidence that its normal schema checks
passed. The field covers Java sampling work only; it excludes request queueing,
HTTP and serialization. Its absence still causes the same original schema
rejection. The diagnostic's label does not make missing protocol data optional.

State requests retain `state_reported` containing paused/screen_open and world
world_generation/dimension/game_time when available. They are snapshots at their
respective response; equal first/last ticks do not prove the client was paused
continuously throughout the scan.

## Failures and unknowns

`original_rejection` captures the original exception type and message (at most
512 characters with an explicit truncation flag). Assembler wrappers also retain
`detail` and `refreshable`; bridge errors retain compact code, status and uncertain.
The existing public exception/reason and retry classification are unchanged.
A formatter/property that itself raises becomes `unknown_format_error` or
`unknown_attribute_error`; diagnostics do not mask that original exception.

Null times plus `unknown_clock_error` mean the measurement was unavailable.
A decreasing diagnostic clock produces `clock_reversed` with no manufactured
nonnegative duration. Reported raw timing observations do not bypass the existing
assembler's clock-reversal or freshness checks. The runtime's monotonic clock is
expected to be reliable; fault fixtures establish observer behavior, not a new
recovery policy for a failing platform clock.

## Budget and interpretation limits

The original `started + 3.0` deadline is captured before diagnostic allocation.
No diagnostic cost is subtracted and no request timeout is shortened or extended.
Added observations can therefore make an already marginal scan fail sooner.
All existing admission guards remain. As before, a single blocking HTTP request
may return after 3 seconds before the next safety guard can reject it. Neither
this Python deadline nor Java's cooperative sampling budget is preemptive.
There is still small work after the final deadline sample (return bookkeeping
and diagnostic stamping), so this is not a hard real-time promise about the
entire function or later serialization. This patch makes no latency improvement
claim. Exact baseline/candidate equality is tested under identical event-driven
synthetic clocks, not guaranteed at every physical timing boundary under extra
instrumentation overhead.

Records are bounded by the unchanged attempt/page loop (fewer than 210 stages per
scan). There is no unbounded history. The 256 KiB HTTP response gate is unchanged;
its limit is not a claim about the separate status/result document size.

## One future authorized read-only preflight

This document does not authorize, install, restart, or execute a preflight. After
separate loading/real-read authorization and version verification, retain the
exact one-shot request ID/result and this diagnostic. Use the same radius 4,
vertical 3, full scan. At the 128-cell per-page ceiling, 567 cells require at least five pages
(128 x 4 + 55 when every earlier page is full). Java's cooperative budget can
yield more pages. A one-page probe is not a
substitute for full, fresh, identity-matching coverage and cannot authorize
movement. Do not replay an uncertain operation or keep retrying the experiment.
First locate the dominating recorded phases. Explain queue/network/CPU attribution
as unknown unless another independently authorized measurement supplies it.
