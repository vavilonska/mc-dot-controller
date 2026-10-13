# Read-only diagnostic integration, batch 1

This increment ports observation-only timing and explicit nullable wire encoding
from the isolated encounter candidate into the newer main production source.
It does not enable encounter, boat, terminal-pause or new recovery actions.

## What is measured

- GET `/control/state` and GET `/control/terrain` report per-request Java phase
  offsets through JSON encoding. Origin is HTTP handler entry, not socket arrival.
- Optional FPS, focus and pause values are observed on the same client callback.
- Resident transport records bytes actually read and validated timing headers.
  Missing, partial or malformed timing remains unknown/invalid. Headers never
  authorize freshness, retries or successful actions.
- Terrain reads add bounded per-attempt diagnostics. Python monotonic durations
  and Java reported durations are separate clocks; no network/queue/CPU time is
  invented by subtraction. Existing scan deadlines and retry budgets remain.
- A failed terrain observation carries only that request's diagnostic record.
  Existing statuses, reasons, action dispatch and uncertainty handling remain.

## Wire compatibility

Existing explicit-null guard ownership, client-action and biome contracts remain.
The narrow codec additionally preserves documented nullable encounter outcome,
callback-interruption and terminal-pause fields, if those fields are supplied.
It does not invent missing fields, advertise actions or add endpoints. A null
at an unrelated path retains its prior omission behavior.

## Preserved production behavior

Environment recovery and its zero-lifetime request, stable placement, stable
mining/crafting evidence, watchdog recovery, cursor ground anchors/adaptive
slices, transport write allowlists and terrain page-tick reversal semantics are
unchanged. Future execution integration must retain these contracts and both
families of regression tests. This source increment is not live acceptance or
completion of the overall main/candidate integration.
