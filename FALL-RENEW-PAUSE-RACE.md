# Standalone fall renewal / GUI pause boundary

Declared base: immutable TEST2.1. This delta changes three production Python files,
no native source, ownership model, ordinary gameplay admission, or saved world.

A fully received, authenticated native renewal refusal is classified only when
its exact existing production response is HTTP 409 and the closed JSON object
`{"ok":false,"error":"fall_rescue_not_armed"}`. The first native renewal guard
emits that rejection before mutation. Error text alone, transport uncertainty,
other status/reason, duplicate keys or extra fields cannot establish this proof.

The existing Resident owner may then make one read-only status request. It must
match the same arm, owner, action session, world generation, player, dimension and
unchanged arm revision; the immutable prior status and current status must both
have zero episodes. The returned status must be disarmed, input-unowned,
nonquarantined, unblocked, have no remaining lease or episode, and report exactly
`user_screen_or_pause`. The same Resident owner/status objects and unchanged
values, bridge identity/session, running state and absence of active/pending,
combat/aim or handoff are fenced after callbacks. A replacement receives no proof
and is not paused by a stale failure.

A closed request-bound `fall_rescue_renewal_stop` receipt records that renewal was
refused, not applied. Runtime validates the same evidence independently; ordinary
renewal validation is unchanged. The guard ends its monitoring loop, performs the
existing one exact disarm, and uses the existing strict cleanup-only neutral
proof. A verified paused result is interrupted / none_proven / cleanup confirmed;
the game stays paused and new gameplay still requires explicit handoff. No arm or
renew retry, second writer, automatic resume, or generic unknown settlement is
introduced. An attempted episode or any ambiguous outcome stays UNKNOWN.

The historical TEST2.1 pause job TEST2_1_ORIGINAL_PAUSE_JOB lacks a saved
same-owner stopped proof and remains UNKNOWN. This fix is accepted only for a new
run; its records and receipts are not rewritten.

Validation uses actual production ActionResponses + BridgeJson rejection bytes
through real loopback Bridge HTTP, deterministic callback/state fault tests, and
the production Resident/gateway/Runtime/Toolbox chain with a modeled native game.
The codec fixture does not launch Minecraft. Live pause timing remains a separate
sole-operator acceptance case after the reviewed Python delta is packaged.
