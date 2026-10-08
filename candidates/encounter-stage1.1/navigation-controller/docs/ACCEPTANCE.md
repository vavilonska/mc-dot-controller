# Live navigation acceptance remains outstanding

This component contains source, protocol parsers, a bounded planner and fake tests.
The optional HTTP transport is source-tested with mocks only. There is no token
discovery, saved credential configuration or fallback to legacy input routes. `Navigator` defaults to disabled and
also rejects adapters without the explicit simulation-only marker. This marker is
an interface contract for the included fake, not a sandbox against malicious Python.

The companion source now supplies separate default-disabled guarded forward-sample
and yaw primitives. The new `sample_adapter.py` and wire fake implement their
external contract. An optional numeric-loopback transport now connects this
contract only when caller-supplied credentials and both explicit acceptance gates
are provided; it was not used against any game during implementation. The original combat look/attack
endpoint is not reused for navigation. Legacy queued key input could execute
after a timeout, world switch or newer observation and remains forbidden.

The forward primitive is one ordinary half-forward sample, not a held-key lease
or 100 ms of travel. The original `executor.py` duration fake is not wired to it.
See [the one-sample contract](ONE_SAMPLE_ADAPTER.md) for implemented source checks
and settling behavior; neither fake establishes Minecraft physics acceptance.

## Required before owner-run live acceptance

1. Obtain explicit user approval for a separate live navigation acceptance session
   in a disposable, unpublished local Survival world, preserving the working mod,
   profile and worlds. Multiplayer remains outside scope
2. Independently build, review and live-accept the companion guarded primitives with
   execution-time world/player identity, expected position/pose, expiry, single-flight
   and replay checks; prove local unpublished Survival scope at execution time
3. Verify the one-sample admission lease is at most 100 ms and does not become
   repeated or held input. Confirm bridge-owned fields clear at tick end and on
   lifecycle cancellation. Release cannot depend only on a controller round trip;
   cleared input does not brake momentum already consumed by the game
4. Establish normal walking controls and speed without sprint, jump, use, attack,
   block breaking/placing or arbitrary key mappings. Test pose and movement effects
5. Verify the implemented post-turn/sample readback, near-rest settling, fresh
   local swept-path validation, progress/drift and neutral-input checks against the
   actual game. Stop on uncertainty; never retry an ambiguous action
6. Test first on a wide, flat, dry vanilla area with no nearby entities. Then test
   obstacle detours, corners, unloaded boundaries, disconnect/world changes, UI
   opening, damage, stalls, response loss, expired commands and independent release
7. Separately test diagonal motion geometry, exact stopping distances and safe
   one-block descent/landing. The original fake has instantaneous braking and the
   one-sample fake has illustrative decay; neither includes real fall physics or
   can establish these live properties

## Current limitations

- Flat fake-route execution only; one-block descents can be planned but are not run
- Full-block ascent, jumping, swimming, sprinting, block edits and Nether disabled
- A centered player is required; broad initial repositioning is not assumed safe
- All nearby entities, active effects, held input and unsettled motion block execution
- Sequential terrain pages can change immediately after sampling
- Collision data and basic hazard tags do not sandbox arbitrary mod behavior
- A successful plan or fake demo is not a live movement acceptance result

## Offline verification

```sh
python -m unittest discover -v
python -m compileall -q navigation_controller tests
python -m navigation_controller
python -m navigation_controller.sample_demo
```

The independent source review identified and regressions now cover observation
bracket drift, elapsed deadlines between look and pulse, and A* cost/depth pruning
under a finite route-length cap. All were fixed before the source handoff.

See [the owner-run probe guide](OWNER_PROBE.md) for read-only default commands,
exactly-one-action opt-ins, hidden token entry and nonsecret report handling.
No guarded movement/yaw runtime acceptance was performed by this source task.
