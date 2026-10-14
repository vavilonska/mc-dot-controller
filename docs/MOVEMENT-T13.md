# T13: bounded observed movement

This change combines two dependent fixes. It does not expand movement authority,
response limits, supported environments or future-dynamics guarantees.

## Single-authority wire evidence

The native coherent response validates all complete sibling bodies first, then
projects two exact same-envelope witness references to the authoritative action
witness. Standalone action bodies stay complete. Both admission size preview and
actual serialization use the same projection. Request/response and reserve caps
are unchanged; known pre-admission size refusals can carry bounded diagnostics.

Resident rejects duplicate JSON keys, malformed/partial projections, extra keys,
wrong owner/job/action/digests/clocks, dangling or chained references and sibling
disagreement. It decodes into separate semantic data while retaining the original
UTF-8 length and SHA-256 exactly once. Terrain acquisition retains the exact A
span and complete C bytes. Runtime rechecks provenance and semantic equality;
public output contains one decoded state and compact provenance, not duplicated
full bodies. Complete-inline legacy bodies remain supported.

## Native action ticks

Activation binds the exact running registry Entry. Lifetime and displacement
buckets use that Entry's native Pre counter, including rejection of negative,
regressing, skipped or expired counts. A final post-hook fence rechecks counter
and owner identity. World timestamps remain evidence of captured world state;
original monotonic deadlines and within-callback world consistency remain.

Terminal evidence adds timing_contract=native-action-pre-ticks-v1 and
last_entity_check_action_tick. Successful case acceptance requires an integer
action age in 1..159 matching the successful native action's tick. A cancelled
action may retain an earlier successful sample; this is not movement success.
Input-neutral evidence does not by itself prove velocity has stopped.

## Test layers and dependencies

The existing Java 21 / Minecraft 1.21.1 / NeoForge dependencies remain unchanged.
Focused native compilation requires the established compiler-only game classpath
and sibling bridge classes. Synthetic engine readers exercise actual movement
policy, registry and codec logic; owner-query excerpts are explicitly synthetic
drivers, not execution of the real Minecraft/NeoForge lifecycle.

Fresh producer fixtures are serialized by actual native codecs. Python tests use
real strict parsers, Resident, Runtime, queue/archive/public service code and
Python-to-Node response framing with synthetic native facts and in-memory HTTP
responses. They do not launch a game or server. Tests cover schema failures,
provenance tampering, exact cap/+1 boundaries, legacy compatibility, action-clock
ownership, world-time discontinuities, hook mutations, expiry and displacement.

The T13 case uses health 20 and min_health=nextafter(20, negative infinity) because
the reserve comparison is exclusive. This does not change production health
defaults. Synthetic test examples and cancellation cases are labeled as such;
private live receipts and saved-world data are not test fixtures in this repo.

## Integration verification

Fresh integration checks completed on this source checkout:

- Resident: 410 Python tests; navigation cursor: 83; gameplay: 64; toolbox: 57
- Full capability suite: 651 Python tests passed in 231.603 seconds
- Node portable: 122; NDJSON framing: 9; synthetic platform gate passed
- Native: 37 source checks; fresh compilation of 12 production families into
  37 Java 21 classes, including all seven changed native families
- Actual policy with synthetic engine readers: 15 scenarios, 168 assertions
- Native-generated action witness to actual Python consumer: 52 checks
- Portable Python codec/navigation invariant: 8 tests; full-reply Python: 6
  tests / 22 reported cases; Node reply boundary: 38 cases

The final Python/Node run was repeated in a fresh output directory after
strengthening its network guard; both attempts passed. Native compilation and
its ten test processes all exited zero. The actual synthetic-engine terminal
remained cancelled/fixture_end/ticks1; success envelopes were labeled copies.

The broad capability suite passed on its distinct second attempt with a
450-second allowance. The first attempt hit an undersized 180-second runner
limit (the prior baseline took 261.660 seconds), with no test failure observed.
Its known terminated/reaped process and original output were retained.

Run the [native focused suite](../client-mod/validation/movement-t13/README.md)
then the [Python/Node suite](../resident-controller/tests/movement_t13/README.md).
The compiler-only pinned prerequisites are external inputs, not bundled public
artifacts. This was not a complete Gradle/NeoForge build or Windows/PowerShell
validation. No current GitHub CI pass is implied by these local results.

## Live scope

T13 completed one cardinal flat-block public movement, with 34 continuation checks
and native action tick 13. Later observation showed the expected destination,
stopped horizontal motion, conserved health/items and confirmed normal shutdown
in 51.382848 seconds. Independent stopped-world readback verified both saved-player
mirrors at that same destination, goal error 0.0743125 blocks, with health, inventory
and equipment conserved. The original world and prior retained copy were unchanged.
No generic pathfinding, future entity prediction, multiplayer confirmation or
completion of all toolbox cases is claimed.
