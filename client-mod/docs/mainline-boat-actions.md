# Mainline bounded boat contracts

This integrates the frozen-v18 boat action family into the newer main source.
It is an offline source/build milestone, not deployment or live acceptance.

- `boat_drive` starts already aboard an ordinary boat. It accepts an immutable
  finite observed-water route: at most 64 x/z-only points, 0.25–16 blocks between
  listed points, at most 16 blocks from the current boat to the first point,
  total at most 256 blocks, with a 1–120 second deadline. No append,
  renewal, mount or dismount is implicit.
- `boat_mount` and `boat_dismount` are separate requests. Their exact field set
  binds world, player, action session, boat UUID/entity ID/type and observed game
  time. They require private singleplayer, a 1–5 second deadline, and at most ten
  sneak ticks for dismount. Mount attempts one ordinary interaction without a
  fallback or replay; it requires the observed reachable exact boat, empty hand
  and the appropriate current membership state.
- Admission finishes before input takeover. Current native passenger/hull
  geometry, loaded collision/fluid checks, identity and membership guards remain
  those in the frozen-v18 implementation. No position, velocity or forced riding
  membership write is introduced.
- Cancellation uses the existing action ID. An optional expected action session
  is checked before cancellation; callers omitting it retain the old endpoint
  contract. Unknown write outcomes still require observing the same ID, not a
  new request or replay.
- Owned boat and player input layers are both cleared before a new boat terminal
  is published. Release failure reports `input_release_unconfirmed`, never a
  successful action. Released input is not evidence that boat momentum stopped.
  Dismount observation is not a safe-landing guarantee.

The original main action set, continuous environment recovery (including its
zero-lifetime request), player environment/bounding-box observations and stable
mining/placement remain. No encounter/combat action, new pause route, mandatory
position rebind, watchdog or cursor change is included in this slice. Three
existing v18 AccessTransformer entries expose boat status/angular/bubble fields
for read-only telemetry; they do not change account or OS permissions.
