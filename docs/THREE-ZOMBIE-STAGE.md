# P2 first bounded increment: exactly three zombies

Mainline integration of the reviewed v18 three-zombie candidate contract. This is one additional
bounded retreat case, not completion of P2 or mixed-enemy combat. No game was run
while implementing it. The old `two_zombie_retreat_v1` remains exactly two ordinary
zombies; legacy single-target combat and the NoAI case entry remain unchanged.

## Explicit contract and gate

`three_zombie_retreat_v1` accepts exactly three distinct ID/UUID/type objects in
`encounter_scope`, all `minecraft:zombie`, including the exact legacy target.
Unknown fields, skeletons/husks/spiders, duplicate IDs/UUIDs, a missing target,
and two/four-element scopes refuse. The native, resident and MCP parsers agree.
`approach:false` and `shield:false` remain explicit; attack, chase, shield, extra
hotbar/sprint/sneak/jump control and incidental sweep are not enabled.

The independent JVM boolean property
`mineclientBridge.encounterRetreatThreeZombieEnabled` defaults false. A disabled
start returns `encounter_three_zombie_disabled` before ownership/input takeover.
The old stage-1 property cannot enable this new mode, and the new property cannot
enable the old mode. This source does not set either property, install a JAR,
restart a process, create permissions or configure credentials.

One original native action owns the entire retreat. The existing immutable
world/player/action-session/navigation bindings, 4-block accumulated 3D distance,
60 observed ticks, 3-second monotonic budget, 12-block original combat area,
1.5-block segment, 0.65-block reserved probe, 150ms snapshot/health continuity,
8ms cooperative route check and input cleanup are unchanged. Route revocation,
third-target loss and replanning never refund any of these. Callback delays can
still exceed an observed limit before the client thread runs; no hard-real-time
release guarantee is made and the earlier cold-plan/callback findings remain open.

## Bounded projectile refusal, not arrow defense

Only the new mode extends the existing threat scan to count live instances of
Minecraft's `Projectile` class. It uses the same renderer-loaded entity pass,
16-block player-centered 3D radius, 1,024 examined-entity and 4ms cooperative scan
limits, and at most 128 projectile identities. The final-entity scan overrun is
also checked. Existing living/dynamic-obstacle caps still apply. Types and exact
ID/UUID identities are emitted as diagnostics; no owner, trajectory, impact time,
damage, shield timing or line-of-fire inference is made.

A complete fresh scan reporting zero projectiles is required for every new-mode
decision. Any projectile, including a potentially harmless or grounded one,
terminates with `encounter_projectile_observed_risk_remaining` before planning or
movement. Missing projectile evidence terminates with
`encounter_projectile_observation_unknown_risk_remaining`; stale, truncated or
failed entire scans retain their original `threat_snapshot_*_risk_remaining`
refusal. The old five-argument snapshot constructor means projectile evidence is
unknown (-1), never implicitly zero. The old mode ignores this new dimension and
its native adapter does not perform the new projectile branch.

Zero means only that this complete bounded client scan saw no projectile. It
cannot certify unloaded, outside-radius, hidden-from-client, future or server
state. The new mode still refuses a fourth dangerous identity, every unsupported
living threat, a creeper or an Enderman. Thus skeleton/mixed-enemy support is not
implied by projectile detection.

## Outcomes and pause

Limited success requires all three exact zombies alive and observed beyond
8 horizontal blocks clearance for three consecutive fresh samples, settled
motion and no health interruption. Its outcome is exactly
`three_scoped_living_zombies_beyond_8_for_3_samples`. Missing/dead third identities
cannot become kills or completion. The original target is never replaced with a
new attack target.

Every outcome retains `risk_remaining:true`, `requires_handoff:true`,
`safety_assured:false`, zero attack dispatches and no server/kill/survival claim.
A successful receipt additionally requires known-zero projectile evidence and
three exact ordered living-scope entries. Two-target evidence cannot validate as
three-target success, or vice versa.

Native terminal pause and resident pause receipt validation accept the new
explicit mode while retaining the same world/player/session/action binding,
private-singleplayer and no-foreign-owner checks. An already attempted unknown
native pause is not retried. Input release and actual world pause remain separate
observations. Cleanup failure still downgrades success.

## Runner and ledger

The queue-scoped append-only ledger accepts three active adult zombies only when
`register_active_case(..., encounter_mode='three_zombie_retreat_v1')` is explicitly
used. Its default remains the old exact-two mode; NoAI registration remains two.
New three-target registrations store the mode. Existing registrations without a
mode are interpreted as the old mode and are never rewritten. Reservation and
re-verification bind the mode and the entire ordered identity list.

`active_case.run_registered_three_zombie_case` is a narrow callable wrapper over
the existing one-shot pause-first runner. It requires the new mode, exact prior
registration and native terminal-pause opt-in. It creates no fixtures or transport,
enables no feature and performs no cleanup. It permits one authorized resume and
one original action; unknown actions are not resubmitted.

Separate operator closeout requires exactly three sequential exact-UUID cleanup
commands and three positive death/effect observations. An absent entity, submitted
acknowledgement, two deaths, reordered proof or unknown third dispatch is not
sufficient. The recorder only reads and appends verified evidence; it does not
perform cleanup, rewrite historical reports or clear the safety stop. The old
mode still requires exactly two cleanup proofs. A later case requires the same
full verified closeout plus a new authorization in the same fixed ledger.

## Verification and remaining gaps

For this mainline integration, use the accompanying report for the exact test
commands, results and whether receipts were freshly emitted or frozen. The
original candidate verification description below is historical evidence; it
does not imply that mainline compilation, installation or gameplay has occurred.

The accompanying report records actual offline test commands and results.
Native snapshots are synthetic; the Minecraft adapter was compiled, not run.
Eight actual native serializer/state-machine receipts are consumed by the real
resident, harness and JS validators. Active runner and closeout tests use temporary
ledgers and fake queues, with all original two-target regressions retained.

Next mixed-enemy stage needs separate evidence and design: exact zombie/skeleton
scope; adult/type/equipment observation limits; non-projectile skeleton ranged
risk even before an arrow exists; bounded projectile geometry/freshness and threat
classification; authorized shield/facing policy and timing; no incidental melee
or pursuit expansion; actual arrow/occlusion/collision evidence. None is supplied
by this three-zombie increment. See the separately documented single-case plan.
