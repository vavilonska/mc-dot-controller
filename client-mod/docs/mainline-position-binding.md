# Mainline position binding slice (offline integration)

Base: local mainline `da57daa48f038c16e895db6fcf51d3680f28c59b`.
The native adapter is byte-identical to frozen v18 commit
`07c9a76bdb18d7d59476ca38114ab7211e509dbb`. The already-integrated pure
PositionDiscontinuityGuard thresholds/readiness are unchanged. This slice does
not enable combat/encounter/pause or add HTTP endpoints. It is not deployed.

## Native admission and cleanup

State publishes `world.navigation_guard`. Automatic land requests carry the
observed `expected_navigation_epoch`, exact finite `expected_origin` and observed
world/player/action-session identity. Native admission checks identities and the
pair before input takeover. Initial legacy unbound native requests remain
supported until the pure guard requires binding. Explicit partial/malformed pairs
reject with 400 even before native readiness; automatic new-schema producers
always provide a complete pair. Recovery, inventory clicks and boats remain
outside the land guard.

A running guarded action whose epoch changes cancels with
`position_discontinuity_rebind_required`. For this new cancellation path only,
mining/placement join confirmed terminal cleanup. Attack key-up and block-break
stop each run once even if the other throws; sprint/input release still runs.
Cleanup failure retains the requested cancelled status/reason as evidence and
publishes raw failed/input_release_unconfirmed. The resident/watchdog/cursor latch stops further dispatch. This new cancellation
has no legacy missing-release variant: only its complete original native cancelled
receipt with confirmed release authorizes bounded continuation. Ordinary legacy recovery,
mining, placement and inventory terminal ordering/fields remain unchanged.
Existing older non-discontinuity cleanup exception risks are outside this slice.

## Observation-bound producers

Both main cursor sites (ground-anchor and adaptive/explicit route prefixes),
resident walk_to/pillar, watchdog ranged retreat, and play.go/travel bind the
state that actually produced their plan. Raw action bodies are not repaired or
rebased by resident/watchdog/play.run. The watchdog defense epoch remains distinct
and only `_navigation_defense_epoch` is removed by its gateway.

Capability presence, including malformed/null/unsupported data, is sticky in the
WorldCache lifecycle, watchdog/client owner context and cursor schema-2 checkpoint.
Terrain invalidation or a new recipe/leg cannot make a missing field legacy again.
Three identical pure `navigation_binding.py` modules preserve standalone cursor
and gameplay imports without runtime discovery or service initialization. Tests
verify all three bytes and common contract vectors.

WorldCache validates every initial/final read. A successful terrain snapshot now
publishes its final validated scan state C; pre-scan A and C world/player/session
must agree. An error never falls back to A or old cached terrain. Prospecting uses
C too. The separate status/action/screen reads are still not atomic; producers
also check C.client_action before movement. No additional state GET is added.

An unready native observation creates no movement or synthetic settled samples.
Cursor waits without consuming its anchor/slice/replan counters; pillar uses its
existing bounded observation wait. One-shot walk_to/go/travel stops before the
action, requiring the caller to obtain a fresh plan. No recipe is replayed. A single travel/pillar operation retains its first observed
world/player/session through every leg/placement; a new explicit go may use a new
current context. Public play.run(observe) records capability just like obs().

## Rejection versus attempted movement

Only a real first-step action POST that throws a definite non-uncertain 4xx
rejection emits `action_admission` provenance. Cursor fresh-plan recovery is
restricted to strict 409/no-admission evidence and these exact reasons:
navigation_rebind_required, navigation_epoch_changed, navigation_not_settled,
navigation_origin_changed. The new plan uses a new ID and its own observation;
the old request is never changed or replayed. Rejection consumes a replan but does
not blacklist a physical edge that was never attempted. Known rejected anchors
refund the unattempted centering attempt, while the replan limit still applies.

400, changed identity, malformed response, 5xx, timeout, uncertainty and release
failure stop. Explicit top-level post_uncertain/uncertain/unknown_outcome non-false
flags override otherwise plausible no-effect evidence. A reason string alone is not proof of no effect. Already-admitted
discontinuity cancellation is a separate bounded replan, never free combat
preemption; reaching an old local-leg endpoint cannot reset that charge.

## Evidence and limits

- Original 63 upstream main regression files remain byte-identical.
- Java 429/429 with actual offline single-worker `test build`, no build cache.
- Python 938 discovered: 937 passed, one inherited skip; all seven original suites.
- Real pure Java snapshot -> three Python adapters -> pure Java admission: 24/24.
- Independent review supplied six additional boundary groups; they fail on the
  frozen r2 source and pass unchanged on r3.
- Node framing and the original seven-tool assertions through the reviewed
  synthetic Linux fixture runner pass. Windows/PowerShell is still unverified.
- Red tests on the prior frozen root reproduce missing binding, unready dispatch
  and rejection misclassification. Synthetic real Resident/Queue/Watchdog/Cursor
  tests show confirmed no-effect fresh plans and no second POST after uncertain
  or unconfirmed-release outcomes.

These offline checks do not establish Minecraft physics, live performance,
Windows/PowerShell behavior, or complete main/v18 integration. Independent review
and separately scoped live acceptance remain necessary.
