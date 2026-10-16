# Bounded defense stop-proof repair (offline candidate)

This change is a source-only repair for the spatial-threat route profile. It is
not live defense acceptance. The original T43 public job remains unknown, and
its original Watchdog/Resident receipts must not be replaced by a later cancel
or by a new offline classification. No old request is replayed.

## Reproduced defect and evidence limit

The retained T43 admission has 22 entity rows. Actual Gson serialization of the
retained JSON is 17,761 bytes. Reconstructing the production Frame yields
semantically equal JSON of 17,760 bytes; the old production Frame.stop(true)
throws route_spatial_stop_evidence_too_large at its 16 KiB guard limit.

This proves the old admission/stop size mismatch on the retained scene. It does
not prove the precise historical exception: the later failing current frame and
original exception details were not retained. Generic local_segment_check_failed
alone cannot exclude a different RuntimeException.

## Native behavior and response bounds

The stop entity guard and the complete stop proof are each capped at 32 KiB.
Checking the complete proof also bounds its identity envelope. General admission
entity evidence retains its 192 KiB ceiling; it is not a promise that all such
frames can become a stop proof.

An admitted attacker is checked for stop-proof capacity before registration.
Runtime current evidence is checked again before a proof is attached. An
oversize stop proof keeps the specific route_spatial_stop_evidence_too_large
reason. It does not manufacture a threat stop, suppress safety checks, or extend
any tick, clock, geometry, identity, owner, or freshness boundary.

Each terminal action reserves 40 KiB: a complete proof up to 32 KiB plus the
existing 8 KiB terminal metadata reserve. The canonical capability response
contains three action-result copies, so it reserves 120 KiB. Against the
unchanged 256 KiB wire limit, admission requires standalone bytes <= 216 KiB and
capability bytes <= 136 KiB. Full response measurements and boundary tests must
pass independently. Schema-6 size diagnostics carry reserves 40,960 and 122,880.
The Java producer and Python consumer must be deployed as a matched candidate.

This is a deliberately bounded repair. A scene exceeding the proof or overall
response capacity is refused. Supporting arbitrarily larger valid scenes would
require a separate wire-deduplication design and is outside this change.

## Consumer behavior

A spatial admission with stop_only=true no longer unconditionally demands a
successful typed threat proof after native proof construction has failed.

A missing proof is accepted only as a known cancellation for the exact reasons
local_segment_check_failed, route_spatial_stop_evidence_too_large, or
route_spatial_evidence_too_large, after the
existing action/owner/context/command-digest and full admission validation.
It must have ticks=0, ground phase, no effect attempt, no jump, no sampled
movement, zero or one completed check with coherent clocks, neutral input,
confirmed input release, and no uncertainty or handoff flags. Both this path and
the typed-stop path reject any effect_outcome marker, including null or a
contradictory claim of a known outcome. A present malformed
proof, claimed threat reason, wrong identity, mismatched digest, partial motion,
or missing release remains invalid/uncertain. Later polls must retain the
immutable original admission witness.

This cancellation grants no defense authority. The unchanged defensive handoff
still requires its separately validated typed threat stop (or the existing
qualified damage path), a fresh attacker observation, original ownership, and
fresh native combat admission. No ordinary task resumes automatically.

Python checks its compact UTF-8 reconstruction of the guard and the entire
proof independently. At extreme serialization boundaries it may conservatively
reject a representation whose Java encoding is slightly shorter; exact raw
native transport limits remain separately enforced.

## Verification scope

New tests cover a legal proof exceeding the old 16 KiB ceiling, complete-proof
size limits, strict no-effect cancellation, and invalid identity/digest/effect/
release/uncertainty mutations. Production Node MCP -> Python owner -> Watchdog ->
Resident tests use a synthetic native endpoint and verify no replay and no
combat for proof failures. Genuine Java-generated wire and loader fixtures are
separate evidence; neither is ordinary Minecraft gameplay.

Before any deployment, review the final source/hash manifest and independent
review. A fresh bounded singleplayer test on an independent world copy is still
required to establish this rebuilt candidate's real stop-to-defense behavior,
normal save/exit, and input release. It must use a new job ID; T43 stays closed
for replay.
