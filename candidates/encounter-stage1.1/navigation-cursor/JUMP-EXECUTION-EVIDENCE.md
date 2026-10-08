# Jump-edge execution boundary

Movement source classes assessed for this cursor version:

- `PathSteering.java`
- `ClientActions.java`
- `ClientActionRequest.java`

The assessed action accepts waypoint x/y/z and a boolean jump. On each client tick
it turns toward the waypoint, scales forward movement by distance and yaw error,
and jumps when grounded if jump is requested, the target is higher, or a collision
occurs. Arrival is horizontal distance <=0.23 and vertical difference <=0.55.
There is no waypoint-specific takeoff location, run-up speed, sprint mode,
trajectory envelope, airborne progress, or explicit landing acknowledgment.

Consequently, the existing executor supports ordinary adjacent up-steps but does
not establish repeatable maximum-distance gap jumps. Merely inserting a distant
jump=true waypoint could jump at the wrong position, brake before launch, or
repeat jumping after landing. This package deliberately does not advertise
unsupported gap edges or hard-code a four-block jump limit.

A future gap-jump increment should first provide an executable edge contract:
separate ordinary/sprint modes, observed grounded takeoff and velocity/run-up,
headroom and swept player-volume checks, complete landing collision evidence,
and an observed landing/end result. Its feasible horizontal/vertical envelope
must come from the actual loaded movement physics and effects, then be validated
in controlled gameplay. This is a separate movement capability to implement and
validate; the offline cursor tests do not establish live gap-jump acceptance.
