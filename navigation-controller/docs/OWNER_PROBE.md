# Owner-run loopback probe and single-action acceptance

**Current status: custom-bridge acceptance is paused.** These commands are retained
for reference only. The earlier real read-only attempt failed with a generic error;
its cause is unknown. No guarded turn/forward action ran, and the client was saved
and closed. The new serialization correction is uninstalled and is not a confirmed
fix for that failure. Do not resume a token prompt, request, installation or game
input from this preserved guide without a separately approved new plan.

## Current evidence and scope

These tools are implemented and tested with mocked sockets and offline transports.
No real HTTP request, token read, game input or installation was performed while
building them. The earlier captured terrain fixture establishes only its read
schema. Guarded movement and yaw still need separate isolated runtime acceptance.

The CLI defaults to read-only. A separate invocation can perform exactly **one**
guarded yaw change or **one** half-forward input sample. It never follows a route,
joins a server, chooses a world, launches a client, installs a mod, changes an option
or enables a persistent setting. Flags express the owner's approval for that local
invocation; they do not prove runtime safety. The bridge rechecks its own guards.

## Prerequisites

Before even a one-action test:

1. Separately approve and finish installing the reviewed movement+turn build in an
   isolated profile, preserving the working profile/JAR and worlds. A terrain-only
   build is insufficient. The installed build must expose the documented movement
   and turn schema 1 fields, including shared observation and ownership metadata
2. Open a disposable, unpublished local Survival world yourself. Do not use a
   multiplayer server or publish the integrated world. Close other controllers;
   a new state read invalidates another controller's pending observation challenge
3. For movement acceptance, use a wide flat dry vanilla test area, no nearby
   entities, full health/air, food at least 8, no effects or held inputs, ordinary
   standing pose, and auto-jump disabled. Close screens and wait for near-rest
4. Independently enable only the intended reviewed bridge test flags for that
   isolated session. This CLI does not set JVM flags or change game settings
5. Know the explicit bridge port and obtain its token yourself. Never paste the
   token into a command line, report, chat or public issue

Stop if any prerequisite is unverified. Do not weaken the terrain, scope,
freshness, settling, entity or speed guards to make a test pass.

## Read-only first

From `navigation-controller/`, replace `PORT` with the bridge's explicit port:

```sh
python -m navigation_controller.live_probe \
  --url http://127.0.0.1:PORT \
  --start-delay 5 \
  --report probe-readonly.json
```

IPv6 loopback syntax is `http://[::1]:PORT`. Only these exact numeric loopback
addresses and an explicit port are accepted. There is no hostname resolution,
proxy support, redirect following or endpoint discovery.

Enter the token only at the hidden interactive prompt. Noninteractive stdin and
any inability to suppress terminal echo are rejected. The token is never saved,
read from a file/environment variable, included in a report or shown in errors.
The report path must be new; an existing/unwritable path is rejected before a token
prompt or any request. Without `--report`, the same nonsecret JSON is printed.

`--start-delay` is optional and defaults to zero. An explicitly chosen finite
value from 0 to 15 seconds waits **after hidden token entry and before any HTTP
request**. Return focus to Minecraft yourself during this interval, close its
screens and release all controls; actions require its mouse to be grabbed.
The tool does not press keys, click, focus windows or change mouse/input settings.
Its brief focus notice goes to stderr, leaving stdout as JSON. Fresh observations
and all existing scan/action deadlines begin after the wait, without being relaxed.
Interrupting the wait sends no request; conditions may change during the wait and
are checked afresh afterward. The delay grants no action permission.

The read-only probe checks capabilities, state/status identity, bounded ordered
terrain pages and cleanup metadata. Its report includes a session fingerprint,
aggregate terrain counts, health/ground/near-rest facts and yaw. It omits raw
player/run/world/observation UUIDs, absolute position, names, inventory, paths,
authentication material and raw server bodies. No POST is sent.

At the title screen it reports that a local world is required and makes no terrain
or state request. It does not open or select one. A successful read-only result
is not action acceptance; disabled guards, incomplete cleanup or failed readiness
still prohibit an action.

## Exactly one approved yaw test

After checking the read-only report and all prerequisites, replace `FINGERPRINT`
with that report's full session fingerprint. This example requests a single
15-degree yaw change, then verifies readback:

```sh
python -m navigation_controller.live_probe \
  --url http://127.0.0.1:PORT \
  --start-delay 5 \
  --action turn --turn-degrees 15 \
  --expected-session FINGERPRINT \
  --accept-local-test \
  --accept-installed-guard-build \
  --accept-unpublished-survival \
  --report probe-one-turn.json
```

The three flags are mandatory and apply only to this invocation. The command uses
an absolute canonical float32 target on the wire; it never calls legacy look.
A turn is limited to a nonzero delta of at most 29.99 degrees. Pitch is unchanged.
A changed bridge movement session or player/world/process identity rejects the
fingerprint before a POST. Post-action state/terrain/status must verify the result.

## Exactly one approved forward sample

Run the read-only probe again into a new report and check readiness and cleanup.
Then, only after separately deciding the forward test is appropriate:

```sh
python -m navigation_controller.live_probe \
  --url http://127.0.0.1:PORT \
  --start-delay 5 \
  --action forward-sample \
  --expected-session FINGERPRINT \
  --accept-local-test \
  --accept-installed-guard-build \
  --accept-unpublished-survival \
  --report probe-one-forward.json
```

This asks for exactly one ordinary half-forward sample. `duration_ms: 100` is the
maximum handler-entry-to-sample lease, **not 100 ms of held movement**. No distance
is promised. The tool waits for two distinct near-rest ticks and then fresh local
terrain/state/status; no next movement action is issued. It does not turn first.
A blocked or unknown forward corridor simply stops the test.

Each test permits one action and at most one sample. The default total checking
budget is two seconds (`--max-seconds` can explicitly select 0.5–5 seconds). Each
HTTP operation defaults to a 0.5-second deadline; calls use direct numeric sockets
and a deadline timer. These limits are not hard real-time physics guarantees.

## Failures, stopping and reports

- A reserved report file is not evidence of success. Inspect its JSON `result`.
  Earlier CLI versions could leave an empty file on a read failure. The current
  CLI writes sanitized failures and interruptions into the reserved report too
- Read-only failure reports identify a fixed stage such as `configure_transport`,
  `capabilities`, `terrain_page`, `player_state` or `validate_observations`, plus
  an allowlisted local error code. Non-200 responses may include only their
  validated numeric `http_status`; bodies, headers, authentication values,
  missing-key names and arbitrary exception messages are never included
- `invalid_caller_token` at configuration means the entered value failed local
  syntax checks before a connection. An HTTP 401/403 reports an access rejection;
  it does not establish why access was rejected. Do not change credentials or
  repeatedly retry. Read-only `input_sent: false` does not imply authentication
  or observation success. An uncertain action failure never receives that claim
- Any ambiguous POST, unsafe readback, stale identity, unknown terrain, damage,
  unsettled movement or contradictory cleanup stops and latches the adapter
- No action is retried, including with a new request ID. There is no legacy
  key/look/release fallback and no automatic next test or rearming
- `close()`/`stop()` close local admission and sockets. They cannot retract a sent
  request, brake motion or confirm remote cleanup. Bridge-owned tick/lifecycle
  cleanup must handle the one input sample
- After interruption or `cleanup_verified: false`, do not repeat the action.
  Inspect the client yourself; a new read-only probe can report ownership and
  neutral-input metadata, but does not itself establish physical safety
- `guard_cleanup_quiescent` reports complete ownership metadata, no current owner,
  not sampled and released. It is not a claim of zero velocity or future safety
- If a report write fails after an action, stdout preserves its action count and
  cleanup result and adds `report_saved: false`. A report-file failure never means
  the action was not sent or may safely be repeated
- If stdout is closed or interrupted, an already saved report is left intact instead of having
  a second error object appended. A nonzero exit code still requires inspecting
  the recorded action count and cleanup result before any next step
- Ctrl+C during report writing returns 130 and prints the existing outcome with
  `report_saved: false` when stdout is available. It never appends a second object
  to a potentially partial file, retries an action or replaces a known action
  count with a new interruption result

Reports distinguish `input_sent: false` read-only evidence, one-action attempts,
release/readback results and `live_navigation_accepted: false`. Even a successful
single local test is not general route-following, multiplayer or mod compatibility
acceptance. Preserve the report and review it before choosing any next test.

## Library use

`LoopbackConfig` takes an explicit base URL and token supplied in memory. Mutation
requires both `enabled=True` and `acceptance_verified=True`. The higher-level
adapter additionally requires its own acceptance flag, expected run/process/player/
world identity and pinned movement session. Constructors do not connect.
The HTTP transport itself permanently admits at most one POST per instance,
including failed or ambiguous dispatch; GET readback remains available.
The live adapter requires `max_actions=1`, `max_samples=1` and a checking budget
no greater than five seconds. `SampleNavigator` still rejects every live
transport, regardless of acceptance flags; route-following is not activated by
this acceptance tool. No automatic discovery or credential configuration is
provided. Avoid wrapping
untrusted transports or bypassing the owner-run scope with custom code.
