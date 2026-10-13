# Covered Enderman melee goal correction

## Scope

This successor changes two Python production files only. It does not change the
native mod, a world, a live case, a process, runtime installation, or credentials.
The immutable candidate-12 source and consumed fourth combat case are retained.

The native entity `line_of_sight` observation uses vanilla eye-to-eye visibility.
A normal adult Enderman's eyes can sit above the player's two-high shelter roof,
while native melee aims its current bounding-box center below that roof. The old
`_Hunt.strike` rejects the latter solely because eye visibility is false.

## Narrow admission

Only `_Hunt.strike` for `minecraft:enderman` melee gains a covered-eye exception.
All other species retain their existing eye-LOS gates and command route. Missing,
numeric or otherwise unknown eye-LOS is not false and never enables the exception.
For an explicitly false eye-LOS, the goal requires:

- The original complete entity snapshot and exact row selected from it.
- All prior health, environment, ambient-danger, native shelter, observed full
  3x3 roof, standability and centered-station checks.
- The same raw terrain object acquired with that observation, full declared cell
  coverage without duplicates, original capture age at most 800ms and terrain
  age at most five ticks. No refreshed timestamp, scan expansion or retry.
- Finite observed player eye and canonical adult Enderman bounding-box geometry
  at its observed position; the native-aim segment must enter that actual box
  within `min(3, observed entity_interaction_range)`.
- Every touched voxel from the actual eye to the observed box center must be
  uniquely observed, loaded, known, dry, hazard-free air with empty collision.
  Exact boundary splits check both sides of voxel edges/corners. Partial or
  nonempty collision shapes are conservatively refused, even if another ray
  could have passed around them. No collision shape is invented.

The Enderman branch calls public `threats.strike` with the same owned `before`
observation. Its new optional argument avoids a second state-only read separating
roof/ray proof from action. Default callers still acquire their own observation;
no other public strike behavior changes. A direct public call without `before`
still performs its prior state-only acquisition; this patch does not add the
new goal-layer torso proof to standalone direct calls. Runtime still enforces current owner,
latest observation identity, original age, raw fingerprint, context and action
reservation. `_Bounded` charges one attempt and latches every unsuccessful or
unknown outcome. Confirmed damage is not a kill or attributed/server damage.

## Native authority and limits

Unchanged `CapabilityTargetAction` rechecks current private/focused context,
health, dry station, weapon, shelter, ambient threats, current target identity,
current box-center aim, exact renderer pick and native melee reach immediately
around the one attack. The Python corridor is only a preflight; it never asserts
that an attack has happened. Raw eye-LOS stays false.

The unchanged native implementation recomputes geometry if the target moves; it
does not provide a new exact target-position lock. A separate stationary case
must enforce any stricter no-motion/teleport conditions. The offline negative
models an obstruction appearing after preflight and a teleport out of native
reach, both refused with zero modeled damage and no replay. It does not establish
that every within-reach target motion is rejected, or that a shelter contains all
teleports. No live hit, ordinary-world acceptance or full-hunt success is claimed.

A pre-existing general boundary was identified: Runtime hashes the original raw
payload and compares the observation's state, but does not separately compare a
replaced `Observation.terrain` field. This patch binds terrain to raw locally for
the new exception; it does not claim to repair that general Runtime boundary.

## Evidence

`tests/test_sheltered_enderman_los.py` contains full729-cell geometry with both
stone roofs, eight bottom stone slabs and dirt supports, grass floor, original
player station, actual vanilla float dimensions, pumpkin and diamond sword. The
original production goal red is retained outside this source under
`validation/sheltered-enderman-los-offline-20261010/` beside all later terminals.

The main test uses actual production `_Hunt -> threats.strike -> _Bounded ->
Runtime -> IntentClient -> Watchdog -> QueueClient -> Resident` encoding and
receipt correlation. The endpoint is a deterministic in-process substitute for
Minecraft/native callbacks: its own segment/shape model supplies health changes,
not an actual renderer, attack, AI simulation or server. Captured native POST JSON
proves the Python native-wire boundary only. There is no newly compiled native
callback/physics evidence. Two later independent semantic samples are still
required by the production Runtime.
