# Route-only spatial defense candidate

Status: implementation and offline validation in progress. No live acceptance claim.
Base: frozen `mdc-usable-main-integration-20261015`; that source and T35 are unchanged.

## Public behavior

The existing explicit request-only `navigate_route_local` + `defend_once` policy supplies one canonical hostile UUID, bounded defense timeout and health reserve, and original reflex/cleanup action reserves. If native advertises `movement-local-segment-spatial-threat-v1`, the adapter negotiates that profile and binds the configured UUID into `route_threat_guard` on each segment. No new user target selector, wildcard, permission, owner or lease is added. Default stop uses the old route profile. Older native retains its existing damage-only defense behavior.

The new profile retains complete loaded entity enumeration, exact typed reader validation, finite geometry, identity/same-callback checks, no truncation, and observed projected geometry. The body sweep is distinct from terrain-validation context. Only audited additional classes are supported; unknown rows remain refusal. Complete geometry does not certify future AI motion, physics or future safety. Exact-class certification here applies to the client geometry reader. Existing integrated-server observation supplies actual owning-thread Mob target/alive/aggressive facts keyed to UUID/id/type; it does not certify the server runtime class. Native fresh integrated-server attack facts must be at most 250 milliseconds and five ticks old; missing facts do not establish calm.

An active threat produces a distinct `capability_threat_observed` terminal only from an actual owned admitted route action before its next ordinary effect. The original immutable action identity, full scoped witness, typed threat evidence and confirmed input release must validate. Wrong configured UUID, other threat, collision-only stop, unknown receipt, motion-gate rejection, lost acknowledgement or admission rejection cannot authorize defense.

The same Runtime/JobControl/lease/generation/deadline/ledger then obtains a fresh observation, requires the configured living hostile to target this player, and requires grounded healthy state and distance at most three blocks for the new typed threat transition. Legacy damage-only defense retains its existing six-block admission envelope (without approach, this may only shield/wait outside actual attack reach). One bounded `combat_entity` command uses `approach=false` and shield enabled. Native exact ray/line-of-sight/collateral/species/health/owner guards remain authoritative. Being within three blocks is necessary, not proof an attack will land. Out-of-range, airborne, stale facts or changed target stop without an attack. No knockback settlement relaxation is included.

A preexisting selected attacker may receive true stop-only admission: full terrain/player/owner validation, real registered action and immutable witness, immediately cancelled and input-released before any ordinary view/input/motion effect. Its current AABB must remain outside the entire swept corridor; only future projected overlap is excepted, and only while zero ordinary effects are proven. Other threats still refuse. This branch reports `preempted_before_motion` after defense. That proof refers to the newly registered stop-only segment; a later-segment preemption may retain earlier completed route segments and their original receipts. Admission rejection is never converted to this proof.

Before a new-profile route plans terrain, a fresh state-only observation checks the selected target. Confirmed calm or absent targets proceed to historical terrain Survey and a separate fresh state for each segment. Unknown, stale or inconsistent target facts refuse. A confirmed active selected zombie within three blocks skips the full Survey and proposes exactly one adjacent flat corridor away from the dominant horizontal target direction (x on ties). The immutable intent carries `route_stop_only=true`, accepted only by the new profile. Native must still validate all current local terrain, entities, body geometry and owner state, and must find the selected attacker at admission; otherwise it refuses before any ordinary effect. No alternative corridor, ordinary movement fallback or Survey retry is allowed. The flag never authorizes movement, even if the attacker disappears. This avoids full-route terrain acquisition in the preexisting-threat path; it makes no universal millisecond latency promise.

Historical Survey is planning evidence only, with age, page provenance and hash metadata. It is never the mutation preflight or last Observation. Current entity/hazard state and per-segment native geometry remain fresh authorities; the global observation freshness limit is unchanged.

The original route ends interrupted after defense, even when defense succeeds. It never resumes and never reports route completion. Original cancellation/deadline and unknown latches dominate; unknown actions are not retried. Mining/placement/collect/step-down and the old spatial policy retain their original semantics. Mining unknown settlement is not promoted to known by a reason string.

## Required offline evidence

- Pure native policy/geometry, full pinned production compile, actual controller/reader/store harness with explicit synthetic client/server readers, and original serializer bytes cross-validated by the strict consumer. These do not establish genuine loader/world/physics acceptance.
- Closed cross-language profile/frame/terminal schema and immutable command binding.
- Actual public MCP entry with synthetic Bridge proving one original segment then one bounded defense, same owner/lease/budget, terminal interruption and no resume.
- Default stop, no reserve, wrong target, stale facts, range, airborne, unknown motion, missing release, cancellation and deadline negatives.
- Legacy route/defense/mining/placement regression and independent review.

## Later live acceptance

Operator owns a separate test world/copy and the next artifact. Use natural server target acquisition for one marked vanilla hostile outside the swept body corridor and within actual combat reach, not fake damage or fabricated target/receipt. Require real shield/attack evidence plus terminal cleanup and no route resumption. No live operation is part of this candidate task.
