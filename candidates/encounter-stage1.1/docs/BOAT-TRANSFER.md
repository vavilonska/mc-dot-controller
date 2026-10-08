# Bounded boat mounting and dismounting (offline candidate)

This extension supplies two small native actions. It is not installed or game-tested.
There is no new planner, queue owner, live bridge adapter, credential, access
permission, automatic placement, approach route, combat, or world modification.
The pre-existing `boat_drive` action is unchanged and still requires a mounted
driver. This candidate does not make an end-to-end boat trip automatic.

## Existing interfaces and the actual gap

- `/control/state` already exposes `player.vehicle.riding`, boat UUID/entity ID,
  controlling seat, ordered passengers, and actual/native passenger geometry.
- `/control/look` has an optional entity-identity/view/tick guard; it protects the
  look call, not a later generic use click.
- `/control/key` supports ordinary `key.use` click and `key.sneak` down/up. Direct
  requests report input dispatch, not passenger membership, and have no native
  finite boat-transfer lease. A press and release in one callback need not survive
  to a player tick. Toggle-sneak also makes generic key-up an unreliable cleanup
  substitute. The new actions do not modify that preference or hold its keymap.
- The missing part was therefore native target-bound, single-use mounting and
  finite tick-spanning dismount input with an observed terminal result. It was
  not merely missing acceptance of an already implemented transfer action.

## Strict request and immutable budgets

Both actions use the existing `POST /control/action` and action status/cancel
routes. The exact fields below are required; unknown and missing fields fail.
`timeout_ms` has no default: callers must choose 1000–5000 ms. The example uses
2000 ms. No user-selectable retry, sneak count, hotbar slot, route or renewal is
accepted. Bindings must come from a fresh observation, never from this example.

```json
{
  "action_id": "unique-transfer-id",
  "action": "boat_mount",
  "boat_transfer_schema_version": 1,
  "timeout_ms": 2000,
  "expected_world_generation": "00000000-0000-0000-0000-000000000001",
  "expected_player_uuid": "00000000-0000-0000-0000-000000000002",
  "expected_action_session": "00000000-0000-0000-0000-000000000003",
  "expected_game_time": 100,
  "vehicle_uuid": "00000000-0000-0000-0000-000000000004",
  "vehicle_entity_id": 7,
  "vehicle_type": "minecraft:boat"
}
```

Use `boat_dismount` with fresh bindings for the second action. With resident,
submit the same fields with `op: action` and omit `action_id`; the resident owns
that ID. Its existing action passthrough preserves every binding and budget.
No new resident task type is required. The sole established queue owner remains
responsible for submitting it; a second producer is not authorized.

Admission requires an observation no more than five game ticks old, an ordinary
Boat class, a loaded in-bounds local hull, and a private integrated singleplayer
server (LAN publication and external servers reject). Identity, topology,
liveness, pause/GUI, and stationary bounds are rechecked before a use or sneak
input. Horizontal speed and absolute vertical speed must be at most .025 blocks
per client tick; absolute angular speed at most .25 degrees per tick. Burning,
underwater/bubble, nested mounts, and additional boat passengers reject. These
are conservative transfer bounds, not fresh calibration or a landing proof.

### Mount

The player must be unmounted, with an empty main hand and sneak released; the
boat must be empty. The caller can first use the existing guarded look interface.
On the client thread, a fresh renderer pick must hit the exact boat instance,
with ordinary visibility and entity reach. The code checks again after the input
hook and then calls `gameMode.interact(player, boat, MAIN_HAND)` exactly once.
The ordinary Minecraft interaction and mod hook paths remain in use.

There is no `interactAt` fallback, second hand, item-use fallback, forced
`startRiding`, position write, packet construction, or retry. The attempt is
recorded before dispatch. PASS, a lost response, an exception, or delayed mounting
cannot authorize another use. Success requires the player to be the sole actual
passenger and controlling driver on two distinct later game times.

### Dismount

The player must initially be the target boat's sole actual controlling passenger.
The native movement-input callback supplies only ordinary `shiftKeyDown`, with
all movement/jump inputs neutral. It spans at most ten distinct game-time samples
and never renews. Detachment permanently ends that input attempt, even if a late
correction reattaches the player. After the budget, the action only observes until
the fixed deadline. It never calls `stopRiding` or changes a sneak option/keymap.

Success requires two distinct later game times with no player vehicle and an
empty target boat passenger list. Input is cleared on every terminal path through
the existing action cleanup, including deadline, GUI, death, world/player change,
cancel, or direct takeover. `result.boat_transfer.input_released` and top-level
`result.input_release_confirmed` describe cleanup separately from membership.
A frozen JVM/client thread cannot provide a hard real-time release guarantee.

## Evidence and limits

The nested `boat_transfer` result records target identity, attempt count/tick,
sneak tick count, latest vehicle observation, stable observation count and input
cleanup. The usual outer result is still `server_confirmed:false`.
`landing_safety_confirmed:false` is intentional: observing detachment does not
establish a safe shore, ground support, unchanged health, or that the boat stopped.
This primitive neither chooses nor validates a dismount destination. Only a
separately reviewed safe scene should be used for the first acceptance.

A named action's status can be read after uncertain dispatch. Do not resend the
transfer or issue a new ID because a response is missing. The existing registry
preserves the named result and rejects payload changes. Resident's existing
uncertainty path may request cancellation of that ID and pauses; it does not
replay the transfer. A late membership change is fresh observation to reconcile,
not permission to reissue the action.

## Minimum future live acceptance, not authorization

This development run did not start/control a game, create a boat, move a player,
change a world, or contact live bridge/queues. A later approved singleplayer test
can be limited to one pre-existing stationary empty ordinary boat on a reviewed,
loaded, flat clear safe pad, no hazards/mobs, and one authorized owner:

1. Confirm the actual installed artifact, world/player/session, private server,
   empty main hand, neutral input, full current observations and safe dismount
   surroundings. Look at the boat using existing guarded look, then observe again.
2. Submit one `boat_mount` with a 2000 ms deadline and those fresh identities.
   Read only the named status until terminal. Require one interaction attempt,
   two increasing confirmation ticks, matching sole driver and input release.
3. Obtain fresh stationary vehicle evidence. Submit one `boat_dismount`, with
   the same 2000 ms budget. Require at most ten sneak ticks, both sides of the
   passenger relationship cleared on two increasing ticks, and input release.
4. Independently inspect player support/health, boat drift, view and neutral
   inputs. Failure or uncertainty ends this trial; reconcile without another
   transfer. This test does not include driving, spawning, boat placement,
   returning to water, long navigation or combat.

Negative admission checks can be added only within the later approved test scope:
stale/wrong identity, nonempty boat, out-of-reach or occluded pick, moving boat,
and cancellation. These do not count as live passes until actually observed.

## Offline verification

New focused Java checks cover strict fields, tick/timeout/identity boundaries,
registry reuse, single dispatch, delayed/transient membership, passenger mismatch,
distinct-tick confirmation, input count/clock regression, no renewed sneak, and
source wiring. Python fake-bridge checks verify exact resident passthrough and no
second transfer POST on unknown response. Source-wiring tests and synthetic
observations do not execute Minecraft and do not establish live safety.
