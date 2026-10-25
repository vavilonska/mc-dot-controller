# Read-only damage diagnostic watcher

Standalone Python stdlib module. Does **not** import effect controllers, read/create owner or ledger files, read/create tokens, POST, reset native windows, alter input or close the game. Existing operator wrapper supplies a bounded **GET-only** transport and runs the separately authorized UI-close mechanism. Tests use offline fakes and explicitly controlled ephemeral loopback servers only.

## Operator API

```python
from damage_watch.watcher import Reply, watch
result = watch(
    transport, NEW_CAPTURE_DIRECTORY,
    expected_pose={"x": EXPECTED_X, "y": EXPECTED_Y, "z": EXPECTED_Z},
    expected_owner=ORIGINAL_OWNER_UUID,
    expected_player=ORIGINAL_PLAYER_UUID,
    expected_next_generation=95,
    expected_entry_count=94,
)
```

The numbers shown bind this 94-known checkpoint, not a reset or an inferred new owner. Supply actual pinned expected pose/identities. `transport.get(path, timeout_s=...)` must return `Reply(status, body: bytes, complete: bool, error=None)` and enforce:

- exact `/control/recovery-diagnostics/v1/events` GET only;
- existing operator-managed authentication, no secrets in arguments/logs/receipts;
- an absolute ≤0.75 s timeout, bounded ≤131,072 B response (one extra byte may detect overflow), no redirects or automatic retries;
- `Reply(None, b'', False, 'connection_unavailable')` **only** for a confirmed prelaunch connection refusal. Generic exception is not silently reclassified as expected startup.

The standalone `damage_watch.transport.HttpTransport(endpoint, existing_token)` adapter enforces these constraints and implements only `.get`, with no token-file reading or credential creation. Slow-header and dribbling-body absolute deadlines, single-request/no-redirect, bounds, echo quarantine and refused-connection classification have controlled loopback tests. A minimal CLI is supplied: `python -m damage_watch --endpoint HTTP_LOOPBACK --outdir NEW_DIRECTORY --expected-x X --expected-y Y --expected-z Z --expected-owner UUID --expected-player UUID --expected-next-generation 95 --expected-entry-count 94 --token-env EXISTING_TOKEN_ENV_NAME`. Omit `--token-env` only to use a hidden prompt. Never pass a token value in argv. There is no POST command or runtime credential/config writer. The operator must arm the external stop-trigger observer **before** starting the game and must arrange normal UI-close on watcher/process/storage failure as well as trigger. This module never invokes CUA or a game shutdown endpoint. A failing or noncompliant wrapper cannot be made safe by this synchronous API.

## Bound and stop semantics

Startup ≤60 s, once native first server/client/damage record starts the window ≤12 s, poll ≥0.2 s, absolute maximum 400 GET attempts. Native recording has its own one-shot15 s window. The watcher uses native elapsed time and a conservative request-start clock anchor, so a late watcher or slow HTTP response cannot restart/extend its12 s budget.

Before first world only explicit connection-unavailable may retry. Every other incomplete/invalid receipt stops; after first world every transport loss stops. First observed server damage (even before client readiness), HP<20, any-axis pose displacement>0.05, nonzero input samples or cumulative count, unexpected native action, owner/player/boot/generation/entry-count change, UNKNOWN, capture errors or evidence regression stops. A bounded timeout without reproduction also requests close, not a safety verdict.

Each response persists `NNNN.raw` plus metadata (HTTP status, exact raw SHA256, UTC and monotonic timings, transport completeness). Raw is saved **before** triggering. Oversized input saves at most131,073 B and is explicitly a prefix/incomplete, never a full receipt. Exceptions are sanitized, not copied into output. `stop-trigger.json` is atomically replaced and fsynced with `close_required: true`, followed by `report.json`. All terminal paths request external close. At most400 responses ×131,073 B plus bounded metadata are retained (about50 MiB raw maximum); nothing is silently pruned. Disk failures propagate; the wrapper must close rather than continue unaudited. Output directory must be new; no existing run is overwritten.

## What the data does not prove

Closed schema `recovery_damage_diagnostics_v1`, schema1. Server damage events and client samples have separate tick/nanosecond timestamps; attached native state is the latest earlier client DTO, **not same-frame atomic causation**. Native damage retention is first32 events plus dropped count. Client sampling counts every observed PlayerTick.Post and cumulative nonzero input, while `client_samples` is a bounded change/20-tick-heartbeat ring (last32), with independent first/latest DTOs; `client_dropped` counts ring eviction, not all ticks absent from the ring. No claim of a continuous position/input trace is made. Native window closure, transport completeness, capture gaps and reproduction are reported separately. No reproduction in this short window is not proof of no future harm or no previous input.

Run tests from candidate `source/`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=damage-watch python -m unittest discover -s damage-watch/tests -v
```
