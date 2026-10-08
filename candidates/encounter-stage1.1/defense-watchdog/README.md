# Watchdog v5.1: terminal-event deduplication and live-hit recovery

Watchdog-only replacement for the current v5 setup. Keep the already loaded
resident melee-closing schema 2 and Java client unchanged. No credential changes.
This source was tested offline; live combat acceptance remains pending.

## Correction

The actual Resident.cancel implementation preserves an already-stopped combat's
request ID and reason. v5 treated the same stopped `combat_flat_approach_blocked`
record as a new failure on every observation, repeatedly cancelling navigation
and extending target exclusion. The corrected fake queue now matches the real
cancel behavior. A real Resident class regression confirms that behavior, and
an old-v5 versus new-wrapper regression demonstrates the repeated-cancel fix.

v5.1 handles each terminal (world, action session, request, UUID, reason) once.
An owned target with a CURRENT entity crosshair hit, matching UUID/id/type and
observed eye-to-hit distance <= 3, can recover stationary melee. It is rechecked
AFTER cancel and a fresh observation. If the hit disappears, recovery is dropped;
encounter history/exclusion are preserved, and it does not switch to approach.
Current attackable entity hits take priority over old approach/no-attack budgets.
The normal resident still owns aim, weapon choice, protected-entity checks,
attack cadence, input release and actual attacks. Target stickiness is retained.

The reported historical minimum body distance 0.68 does not establish that a
valid hit existed when the original approach failure occurred. Alive geometry
from that encounter was not retained. This fix does not claim to reconstruct it.

## Sole-operator replacement

1. Stop ordinary intent producers. Request STOP through the old watchdog.
2. Confirm old state is stopped, cancellation/release confirmed, and its process
   has exited. Do not start a second queue writer if release is unconfirmed.
3. The existing game operator may normally respawn/establish a safe point while
   the watchdog is stopped. Leave resident/client and their authentication alone.
4. Explicitly remove only the existing control directory's STOP marker, then run:

       python /path/to/minecraft-watchdog-hit-recovery-v5.1/watchdog.py run \
         --queue EXISTING_QUEUE --control EXISTING_CONTROL

5. Confirm exactly one watchdog process, `armed:true`, fresh observations, and
   `watchdog_revision:"v5.1-live-hit-recovery"` in state.json. The implementation
   string remains `native-defense-watchdog-v5` and schema remains 5 for existing
   intent/navigation compatibility. Continue through the same intent gateway.

Runtime imports the sibling `minecraft-resident-controller` or portable
`resident-controller` package. No new package dependencies are needed.

## Minimal live acceptance

Use normal gameplay with a naturally observed hostile, not a new test world.
Verify the same target UUID has a real entity crosshair hit and eye/hit geometry,
then an increasing native `attack_dispatches` counter, then separately observed
target health changes or a dead target. Client input dispatch alone is not a
server-confirmed hit. Do not infer success merely from a progress notification.

A bounded local `combat-trace-<watchdog-session>.json` in the existing control
folder records up to 96 compact observations: player pose/health, target geometry/
health, crosshair, combat counters and aim status. It freezes on the first dead
sample so later dead observations cannot overwrite the useful lead-in. At most
four generated trace files are retained. It excludes chat, names, inventory,
authentication and queue contents. These runtime files are private and must not
be added to a public source package.

## Offline regression

    python -m unittest discover -s /path/to/minecraft-watchdog-hit-recovery-v5.1 -p 'test_*.py' -q

111 tests pass, including nine focused terminal-recovery/trace tests and the
existing 102 tests. The real Resident class is used for the cancel-semantics
regression, with an in-memory bridge and temporary files, never the live queue.
The old-v5 comparison test skips only if its historical source is unavailable.

An experimental direct attack probe is deliberately excluded from this release.
The tested native combat path remains the sole attack implementation.
