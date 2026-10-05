# Live navigation acceptance is not implemented

This component contains source, protocol parsers, a bounded planner and fake tests.
There is no live HTTP movement adapter, hidden enable flag, token reader or
fallback to legacy key/look/release routes. `Navigator` defaults to disabled and
also rejects adapters without the explicit simulation-only marker. This marker is
an interface contract for the included fake, not a sandbox against malicious Python.

The existing companion guarded endpoint supports look/attack in a combat context.
It does not support navigation movement, a player-only look action, or held-key
leases. Reusing legacy queued key input would permit a stale request to execute
after a timeout, world switch or newer observation. It is not a safe substitution.

## Companion source progress

The companion mod now contains a separately default-disabled
[guarded forward sample](../../client-mod/docs/guarded-movement.md). Its build/tests
pass, but it has not been installed or live-accepted. It supplies one half-forward
input sample with release-before-acknowledgement, not the fake adapter's duration-
based pulse. Navigation-only turning and this component's live transport remain
missing. The existing fake cannot establish physical settling or stopping distance.

## Required before a real adapter

1. Obtain explicit user approval for a separate live navigation acceptance session
   in a disposable, unpublished local Survival world, preserving the working mod,
   profile and worlds. Multiplayer remains outside scope
2. Complete, review and live-accept the narrow bridge-side movement contract with
   execution-time world/player identity, expected position/pose, expiry, single-flight
   and replay checks; prove local unpublished Survival scope at execution time
3. Make each pulse independently time-bounded at no more than 100 ms. Release held
   movement on expiry, rejection, disconnect, world switch, UI transition, shutdown
   and controller failure. Emergency release cannot depend only on a successful
   controller network round trip
4. Establish normal walking controls and speed without sprint, jump, use, attack,
   block breaking/placing or arbitrary key mappings. Test pose and movement effects
5. Add post-look and post-pulse observations, fresh local swept-path validation,
   stagnation/drift detection and neutral-input verification. Stop on uncertainty;
   never retry an ambiguous action from its old context
6. Test first on a wide, flat, dry vanilla area with no nearby entities. Then test
   obstacle detours, corners, unloaded boundaries, disconnect/world changes, UI
   opening, damage, stalls, response loss, expired commands and independent release
7. Separately test diagonal motion geometry, exact stopping distances and safe
   one-block descent/landing. The current fake has instantaneous braking and no
   fall physics, so it cannot establish any of these live properties

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
```

The independent source review identified and regressions now cover observation
bracket drift, elapsed deadlines between look and pulse, and A* cost/depth pruning
under a finite route-length cap. All were fixed before the source handoff.
