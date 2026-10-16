# Explicit bounded terminal defense

Combined source integrates bounded local routes and explicit terminal defense. Ordinary-world acceptance of this combined revision remains pending.

## What already worked

- `CapabilityGuard.check` stops noncombat native actions on health loss / hurtTime or environmental hazards.
- `Runtime._native_receipt` verifies original action UUID, action session, terminal status, scoped witness, and input release before returning a known native failure.
- Public `engage` runs existing bounded native combat. Native per-tick threat, collateral, cooldown, shield, health reserve, route/retreat and context checks remain authoritative.
- Existing public reactions default to stop. The older generic supervisor requires `continuation_safe`, unsuitable for terminal-only defense followed by a stopped task.

## Added useful minimum

Explicit public job policy:

```json
{"version":1,"execution_mode":"request_only","reactions":"defend_once",
 "defense":{"target_uuid":"44444444-4444-4444-8444-444444444444","timeout_ms":2000,"min_health":14}}
```

This is a concrete UUID selected by the caller. No nearest-target acquisition, implicit retaliation against arbitrary mobs, or retargeting.

- Supported ordinary capabilities: `navigate_local`, `navigate_step_down`, `mine_local`, `collect_local`; `navigate_route_local` is included in this combined integration and remains request_only.
- `request_only` or `guarded` may opt in; `noncombat` cannot. Route keeps its narrower request_only requirement.
- Default stop stays unchanged. `avoid` and old `defend` remain unadvertised/unimplemented. A `defense` object without `defend_once` is rejected, preventing hidden opt-in.
- Reserve at least one original reflex action, one cleanup action, and one ordinary action. No new owner or reset deadline/budget. At transition at least 15 observations must remain, covering fresh attacker evidence, bounded postcondition samples, and original cleanup.
- Trigger only exact `capability_damage_observed`, known failed/cancelled native `follow_path` or `break_block`, confirmed native input release, same original Runtime job/lease. Environment hazard, successful ordinary action, unknown outcome, cancellation, unsupported task, or expired deadline never starts defense.
- The original native action's inputs are released; the original job lease is retained. Fresh observation must still show that exact terminal native action, unchanged world/player/action context and owner identity.
- Explicit target must be a living supported zombie/skeleton-family hostile within six blocks. Fresh integrated-server native_living evidence must show this exact mob currently targeting this player. All identity, completeness, source tick and nanos/age relationships are checked. This does not claim it caused the preceding damage.
- One existing scoped `combat_entity` action, approach=false, shield=true, timeout 50–5000 ms, health reserve 14–20. It may execute several native attacks within that one bounded action, or native safety retreat. No ranged mode is added.
- On completion, ordinary task remains interrupted (`ordinary_task_interrupted_after_defense`), never succeeded merely because defense ran, and never resumed. Events record original interruption plus separate defense result. Unknown remains unknown; no new action or retry. Same request identity is deduplicated by existing public service.


## Acceptance boundary

Portable production-entry tests use a synthetic Bridge. They establish bounded ownership and refusal semantics, not live combat effectiveness. Legacy automatic defense cannot race an active capability lease. No automatic acquisition, retargeting, ordinary-job resumption or unknown-action retry is added.
