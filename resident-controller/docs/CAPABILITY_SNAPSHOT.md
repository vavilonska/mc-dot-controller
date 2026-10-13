# Opt-in coherent capability observation

An `observe` command with `capability_observation: true` now requires native
`GET /control/capability-snapshot?radius=N`, with the caller's exact entity
radius. `coordination_step: true` adds the existing `coordination_step=1` query.
There is no fallback to older independent endpoints when the coherent endpoint
is unavailable, malformed, downgraded, or inconsistent.

The native response has protocol `mineclient-bridge`, schema 2,
`capability_snapshot_schema_version: 1`, and `status`, `action`, `state`, and
`screen` sibling objects. Each retains its original native endpoint contract.
The native schema attests that these objects were captured in one Minecraft
callback; Resident additionally checks all sibling schemas, world generation,
dimension, game tick, player identity/position, action identity and record,
menu, and screen presence/details. It checks the requested entity radius and
entity list/count/truncation consistency. The complete native state, including
explicit nullable entity facts and the original native sample ages, is retained.
A true truncation flag remains true; a complete array is not invented.

State-only capability observations use one native callback. Terrain observations
use the current request's coherent A, the existing bounded terrain page sequence,
and coherent final C. C replaces **all four** result siblings together, including
the native capability guard and original C acquisition diagnostics. A's one-use
token is bound to its cache, unchanged state and sibling envelope, entity radius,
and original acquisition start. No state or bundle from an earlier request is
re-stamped as A. The terrain's original acquisition origin, region/profile/tick
fences, scan retry limits, clock limits, and historical-only survey behavior are
unchanged. Failed A or C cannot publish partial terrain or a prior cached grid.

`capability_capture` reports original Python monotonic acquisition start/end,
and `state_read_diagnostics` carries that read's actual transport metadata.
These are diagnostics, not a substitute for native source freshness.
`capability_guard.source_tick` and its exact native `source_nano` string are never
rewritten. Resident does not compare the native nano clock with Python's clock.

Ordinary observations still use their legacy endpoints. The Resident loop remains
50 ms. The HTTP response limit stays 256 KiB, with no automatic action retries.

## Rejection diagnostics

An actual definite POST rejection retains its existing `action_admission`
semantics. The optional native `capability_source_freshness` object is copied
unchanged into that evidence only when its diagnostic schema is valid. It reports
the native guard phase, original/current ticks and nano strings, elapsed nano
string, unchanged 5-tick and 800,000,000-ns limits, and four violation booleans.
Malformed optional diagnostic metadata is marked
`capability_source_freshness_status: "invalid"`; absent metadata stays absent.
No values are inferred. HTTP 5xx and transport ambiguity stay uncertain regardless
of any diagnostic fields. A rejected capability action is not automatically retried.

## Offline verification scope

`test_capability_coherent_snapshot.py` runs the actual Resident, WorldCache,
QueueClient and HTTP adapter against native-shaped fixtures with deterministic
50-ms callback delays. It covers timely admission, tick-age expiry, nano-age
expiry, unchanged source values, exact final C replacement, invalid/null/schema
and identity mismatches, no fallback/replay, nullable raw entity facts, optional
freshness evidence, and the unchanged response byte bound. Related capability
terrain tests retain full-page, region, identity, acquisition-time, retry, and
historical survey checks. These offline checks do not establish live performance
or successful gameplay acceptance.

The regression fixtures also include 13 exact Java-encoded capability bundles
from the candidate JAR, with producer hash and byte hashes pinned alongside them.
The actual Bridge → Resident path preserves native entity nullable fields, armed,
stopping and sealed movement budgets, and terminal nested-null results unchanged.
One-sibling omission or mutation is rejected rather than normalized. Three actual
native HTTP rejection fixtures retain each guard phase and exact nano strings
larger than JavaScript's safe integer range.
