# Exact old-combat release during native fall takeover

Base: immutable TEST2.1. This delta changes six native production files, without
changing the public seal, adjudication eligibility, action replay, or old receipts.

The live TEST2.1 attached run performed 12 combat attacks, then one bucket rescue
with correlated server water, bucket transition and alive landing observations.
Its original combat receipt nevertheless sealed input_release_confirmed=false:
terminal ScopedCombat cleanup required no input owner, while the authorized fall
successor already held the arbiter. This was a release-fence self-conflict.
Successful landing does not repair that old receipt; its UNKNOWN remains held.

The fix installs a synchronous release-only scope around finish() for exactly the
old RuntimeAction, ScopedCombat and ActionRegistry.Entry. Its pure predicate binds
that exact registry entry, native action revision, current arm/episode/operation,
player/level/game mode, action session, unchanged world generation, absence of an
external controller lease, original lease deadline and episode tick budget. The
successor must not have dispatched or completed preemption. The predicate uses
only fields, immutable identity values, pure getters and the monotonic clock; it
cannot execute an external/mod callback. Invalid scopes latch invalid permanently.

The arbiter remains held throughout cleanup. A permanently marked preempted guard
can never fall back to ordinary cleanup after the scope closes. Other guards,
entries, successors, expired or revoked scopes are refused. Every old input/key
release and sprint transition is fenced before the
next effect; non-defensive shield release uses the same per-step fences as the
existing defensive release path. Callback-backed context reads precede final pure
owner/world/session checks. Vanilla leaf server getter behavior remains the same
cooperative assumption as existing cleanup; a changed server identity is reread
before the final pure fence.

Raw keyboard/mouse and isolated-key holds, plus independent guarded-movement
ownership, must remain absent at admission and every scoped cleanup boundary.
A newly appearing channel refuses cleanup and is left untouched. Preemption no
longer invokes global input release or guarded-movement cancellation; it releases
only the original action. The redundant post-finish item-release callback is
removed; only an exact-bound input-field reset remains. Rescue then requires the
existing positive native neutral
proof before rescue selection or use.

The existing scoped cleanup packet filter still permits only RELEASE_USE_ITEM.
Use/use-on and attack are additionally refused at their injected HEAD dispatch
methods while cleanup is active, before local effects. This scope grants no attack,
new item use, hotbar selection, movement, aim, effect retry or owner authority.
Late callbacks cannot finish a replacement registry entry. Bounded failure-stage
and reason diagnostics identify rejected cleanup without claiming it succeeded.
The original effects remain UNKNOWN after known cancellation/release and still
require the existing separate explicit original-owner adjudication.

Offline validation includes the compiled production scope/arbiter/ActionRegistry,
actual ActionResponses + BridgeJson bytes through real Bridge HTTP and unchanged
strict attached-seal validation. The actual production HEAD/packet/lifetime adapter
probe uses a test-only constructor-free guard to avoid creating Minecraft; its
Unsafe compiler warning is retained, and no game classes are initialized. Real
registered Mixins are applied to all actual target class bytes, with missing-seam
negatives. Source-site parity checks bind callback/final-fence placement. These are
not a real mod-callback execution or gameplay timing test. A fresh sole-operator
attached combat/rescue/adjudication run remains the final live acceptance gate.
