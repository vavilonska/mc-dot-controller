# Bounded public defensive combat

Declared base: frozen TEST1 source manifest SHA256
073c5447c88863194ab5bc6edd1ab483dd815ac04e215d78eeb91ee006f45bf0.
This delta is separate from the narrow TEST1.1 compact/HTTP repair.

## Public operations

- `defend_local(target_uuid, window_ms=1000)` uses one exact offhand shield for a
  bounded shield-only window. It does not attack or advance toward the target.
- `evade_local(target_uuid, window_ms=2500, max_distance=4,
  minimum_separation_gain=0.5)` requests immediate local dry retreat. It uses the
  existing loaded geometry, retreat corridor and owned movement controller.
- Windows accept 300–2500 ms. The native original timeout reserves 250 ms and
  never exceeds 3000 ms. Evade distance accepts 1–4 blocks, and required separation
  gain accepts 0.1–2 blocks below the requested distance. Movement admission
  reserves a conservative 0.65-block next-step margin. These are bounded caller
  parameters, not unchangeable policy constants.

Both require separately negotiated `combat-defensive-local-v1`, the existing
single Runtime/gateway/Resident/native owner, exact target ID/UUID/type, current
bound private single-player context, loaded dry grounded geometry, a finite
positive health value and an unchanged selected/offhand item binding. They may
admit below the offensive reserve; `effective_min_health=0` means strictly positive
health is required, not permission to act while dead. A selected weapon is not
required. Existing `engage` still uses `combat-local-observed-v1` and its original
14–20 reserve. Missing defensive support never falls back to engage/raw actions.

## Effect and completion boundaries

The policy is closed and cannot be submitted on the raw or offensive scoped path.
Defensive ticks branch before the ordinary attack loop. Attack entry and entity
attack packets are blocked while this mode owns control; only a same-call exact
player offhand shield use is admitted. Unscoped/vanilla repeated uses are cancelled
before effects. One interrupted or unconfirmed shield use is not retried.

The native callback fence finishes clock/tick reads before a pure exact owner
predicate. Shield use, packet, aiming, retreat and cleanup boundaries retain
captured player/world/menu/session identity. A stale callback cannot manipulate a
replacement owner. The shared `WorldGeneration.matches` helper is identical to the
external-stop delta and should be merged once.

Shield success requires at least three distinct blocking samples and the exact
shield still actively blocking at the end of the requested window. Evade success
requires a checked local route arrival plus observed separation gain from the
same target. Both report zero attacks, `physical_safe=false` and
`risk_remaining=true`. Observed travel does not cancel external velocity or prove
a physically safe stopping point. Failed, lost or uncertain work never retries,
retargets or resumes an earlier job. Exact cancel and input release remain the
existing owner lifecycle.

## Supported scope and remaining campaign gaps

The explicit six types are zombie, husk, zombie villager, skeleton, stray and
bogged. There is no new dimension whitelist: the same-bound dimension, loaded
dry geometry and exact target gates apply. This is not certification of Nether
or End encounters. There is no arbitrary mob acquisition, projectile forecast,
auto-aim daemon, general ranged defense or campaign planner.

Existing `engage` already performs bounded native per-tick targeting, cooldown,
shield, approach and retreat for those six types; this delta reuses that loop.
Existing `defend_once` remains an explicit post-terminal option for its supported
ordinary task types after a known released stop.

Legacy dragon phase 6/7 head strikes, blaze ranged/fire-resistance or shield-cycle
logic and Enderman shelter-gated strikes exist behind legacy skills, but they are
not available through the current initial public owner adapter. Wither and wither
skeleton support is not implemented. The catalog now exposes explicit target/mode
coverage and those unavailable legacy paths, rather than implying campaign-wide
combat readiness. Public ranged/phase APIs are a later separately reviewed slice.

## Validation meaning

Pure policies and boundary probes test closed fields, bounds, one-call use and
late owner replacement. Exact Java request/evidence/ActionRegistry output passes
through production ActionResponses and BridgeJson, then actual loopback Bridge
HTTP and Resident/Runtime consumers. Terminal facts in these fixtures are modeled,
not live gameplay evidence. Separate public owner-chain and Node front-door tests
exercise exact IDs, negotiated profiles, cancellation and lost-response UNKNOWN.
Actual bytecode transformation checks the cancellable attack/use seams and a
missing-seam negative. No live defensive combat acceptance is claimed.
