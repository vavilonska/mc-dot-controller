# Boat passenger admission correction (1.21.1)

Status: isolated `1.1.7-boat-passenger.1` offline candidate based on `1.1.7-integrated.1`. No deployment or post-fix game trials. Does not include concurrent retreat/coordination changes.

## Confirmed cause and evidence limits

The first recorded 8-block route at `water_surface_y=63` was rejected before an action ID or boat input. Observed boat Y was `62.522468156083576`; player Y was `62.109968156083575`. The original passenger test incorrectly reused the boat buoyancy floor (`surface - 0.8 = 62.2`) as a passenger-feet floor.

The cached Minecraft 1.21.1 client and official mappings were hash-verified against Mojang's version manifest. Inspection of the unpatched, officially named bytecode establishes:

- `EntityType.BOAT`: width `1.375f`, height `0.5625f`.
- `Boat.getPassengerAttachmentPoint`: for wood boats, Y is boat height / 3; a single rider has zero horizontal seat offset. Bamboo uses its native higher attachment.
- `Entity.positionRider`: rider position is vehicle passenger-riding position minus rider vehicle attachment.
- `Player.DEFAULT_VEHICLE_ATTACHMENT`: `(0, 0.6, 0)`; standing/crouching dimensions retain it.
- `EntityDimensions.makeBoundingBox`: min Y is the entity feet, with width centered on X/Z.

Therefore ordinary seated-player feet are `boatY + 0.1875 - 0.6 = boatY - 0.4125`, exactly the recorded Y. Seated rendering does not imply a shorter collision AABB. With vanilla standing dimensions `0.6f` by `1.8f`, the derived AABB is `(8.199999988079071, 62.109968156083575, 56.19999998807907)` to `(8.800000011920929, 63.90996810839986, 56.80000001192093)`.

IMPORTANT: the old recording contains the boat AABB and player position/eye position, but not player pose, scale, or AABB. That player box is an explicitly labeled native-standing derivation, not measured historical evidence. The fix reads the actual current AABB and native pose dimensions; it does not hardcode this derived player box.

Primary artifact provenance:
- https://piston-data.mojang.com/v1/objects/30c73b1c5da787909b2f73340419fdf13b9def88/client.jar
- https://piston-data.mojang.com/v1/objects/2244b6f072256667bcd9a73df124d6c58de77992/client.txt

## Revised admission and per-tick safety

1. Existing world/player/session/vehicle/driver/passenger-order identity and ordinary-boat, buoyancy, speed, bubble, collision and liveness guards run unchanged.
2. Validate finite, positive-volume hull/rider geometry; 1–2 unique direct, live, nonspectator riders; no nested riders. Every observed rider box must match the native current-pose box at `boat.getPassengerRidingPosition(rider) - rider.getVehicleAttachmentPoint(boat)` within `1e-5` coordinate arithmetic epsilon. Unsupported or incomplete geometry fails closed.
3. Retain the `1.4` rider width/depth cap; explicitly cap height at `2.9`. Nonvertical custom VEHICLE attachments fail closed, because independent passenger yaw could otherwise extend their future envelope.
4. Fit the complete body within the prism actually checked by `BoatCorridor`: two source-water layers `[surface-2,surface)` and three collision-free air layers `[surface,surface+3)`, with a `0.1` vertical margin. This replaces the wrong boat-relative feet floor, without altering the requested surface or reducing fluid/headroom checks.
5. For every rider, the horizontal seat distance plus the body half-diagonal bounds the rider through any boat yaw. The maximum of hull and rider extents is used in both block sweeps and protected-entity overlap. The original admission/tick margins remain; maximum rider radius `2` keeps all sweeps within the existing bound (`+1` tick margin, total ≤3).
6. All cells are freshly read with the actual boat collision context, chunk/build/world-border checks, full source water, strict air and bubble/magma/soul-sand/lava exclusions. Unknown cells, collisions and dangerous fluids still reject. No position/velocity mutation, fake water surface, mount/dismount, or look-only steering is introduced.

Observations add `passenger_geometry_schema_version:1` and per-rider observed AABB, pose, native width/height, vehicle attachment, native mount, expected AABB, identity/liveness/topology and completeness. Action evidence adds clearance dimensions.

## Verification limits and required future acceptance

Offline geometry/boundary tests and full regression validate deterministic logic and wiring, not Minecraft live safety. The guard runs in `ClientTickEvent.Pre`; exact native mount/pose equality is intentionally fail-closed. An authorized live run must measure whether client tick order, interpolation, mount settling, or server corrections produce false rejections. Do not loosen it without such evidence.

Before the next separately authorized game trial, record the new actual/native AABBs and keep water surface 63. Start with the same stationary driver-only ordinary oak boat and short safe route; then check progress, stable identity, complete snapshots, turn envelope, head/side collisions, unsafe fluid/load rejection, and ownership cleanup. Strict-geometry false rejections remain a live-calibration risk. Successful offline admission of the recorded-derived fixture is not completion of that route. Zero post-fix live tests were performed.
