> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Recovery survival v6 — narrow implementation contract

Explicit independent candidate. Current formal338 is cold and unchanged; original v5 JAR8584c0d7…1b550e remains the recoverable predecessor. Source/offline review and independent TEST qualification precede any formal operation. No original-world rollback, copied TEST progress, credential, multiplayer access or hidden legacy mutation bypass.

## Profile, representation and history

Startup-only `recovery_survival_v6`, new explicit flag, same authenticated recovery interaction v3 route and same single-owner journal. New PLAN version4/kind `survival`: closed four-field context, optional bounded unchanged navigation stages and bounded survival stages, unique stage IDs and at least one stage. No maintenance worksites, block targets, placement or fake workstations.

New effects are only `move`, `look`, `select_hotbar`, `attack_blaze`, `consume_bread`. New navigation retains existing actual-shape/source/target and finite first-sample-jump rules. Each survival stage permits exactly one intent of its declared kind; counts are cumulative by context/stage/kind across PLAN hashes, including knownzero. This does not impose an unrequested permanent per-UUID blacklist: any later deliberate action requires a new explicitly bounded plan stage and fresh decision, never an automatic retry or multi-attack loop.

All338 stored requests/digests/terminal/evidence/PLAN proofs remain exact. Old v5 maintenance and navigation raw PLAN kinds dispatch to their original validators; older profiles likewise retain their readers. Old status/exact-stop and same-ID/same-payload reports remain available based on stored record profile, not the active PLAN. New effects on old profiles are unavailable in the v6 exclusive mode. Global UNKNOWN survives profile changes/restarts; no empty journal, new owner or evidence deletion.

Same bounded storage/count/response ceilings (public24MiB/512, single response64KiB) and pre-dispatch cleanup/status reserves. Count ceiling is not a guarantee every maximal record fits. New binary/request data is conditional on v6 only; old byte encoding must roundtrip exactly.

## Three distinct bounded operations

### Selection

`select_hotbar` is one vanilla-compatible selected-slot update after durable effect claim, only 0-based slot1 exact bread or slot8 exact iron axe, current full stack fingerprint/owner/context bound. No inventory movement/search, auto-selection or other slots. Selection is a separate action and does not attack/use.

### One current Blaze attack

`attack_blaze` binds current target entity ID, UUID, fixed type `minecraft:blaze`, exact native Blaze class, current combined entity ray/hit, alive target, actual entity reach and unobstructed hit, full `getAttackStrengthScale(0) >= 1.0` cooldown, selected slot8/exact iron axe/full stack and captured player/level/gameMode/connection/owner. Request plus original observation preserves this identity; the target need not remain physically stationary between observation and the current final check.

One durable claim then one top-level original `gameMode.attack(capturedPlayer,exactTarget)` outside the ledger monitor, finally tracked. No key attack hold, aim mutation, chase, fallback block attack, repeated strike, generic entity catalogue, bow, shield policy or dragon multipart. Do not import old ScopedCombat's ranged-only Blaze policy or construct a full hurt/knockback/packet side-effect framework. Normal original downstream game behavior is not isolated or certified safe.

Preclaim predicate refusal is known0/no effect. Entered call that returns normally is one attempted call even if target health did not change or the target remains alive; post damage/death is separate gameplay observation. Throw after entering/possible packet send follows original UNKNOWN, not false zero-dispatch. Stop prevents later claims but does not falsely claim it interrupted a synchronous entered callback.

### One bread use lifecycle

`consume_bread` binds selected slot1, exact ordinary bread/default food behavior (32-tick normal duration, no extra food/conversion effects), MAIN_HAND, full starting stack, max_items1, max_start_calls1 and max_use_ticks≤40. Food already full or unsuitable preclaim state is known0; the implementation never waits for hunger before starting.

The only action TTL extension is v6 consume: absolute ≤4000ms from native submit (default4000). All other new kinds and every old kind retain original ≤2000ms domain; navigation request budgets are unchanged. Ticket freshness remains2000ms/40ticks and is not the action TTL. Neither use start, tick, response, observation nor cleanup renews a deadline. A separate≤40client-tick lifetime bound ends the hold, whichever limit comes first; lag/expiry can yield known interrupted with no consumed item.

Exactly one direct original `gameMode.useItem(MAIN_HAND)` invocation after durable claim. An entered FAIL may still send a vanilla use packet and is therefore one returned attempt, not known0. Applied_calls0/1 counts this single invocation, not held ticks or food success. Held use remains ACTIVE/releasedfalse after that invocation; it cannot settle merely because applied_calls reached1.

Only this captured owner may hold the use key. A narrow required `Minecraft.startUseItem` gate blocks default repeat/otherhand/entity/block use from before the first call through key clearing and exact lifecycle release, including natural-finish same-tick windows and stop/TTL invalidation. The repeat blocker must not disappear merely because ledger.live becomes false or isUsingItem first becomes false. Hardware/key/other-owner isolation stays in effect.

Every exit invalidates this owner's queued/held use, clears its key state and performs at most one necessary original releaseUsingItem on its exact still-owned player/hand/use lifecycle. Natural completion with no active use needs no gratuitous release packet, but key neutrality must be established. A replacement owner/player/use cannot be cleared by old cleanup. Synchronous call/release exceptions or uncertain ownership retain original UNKNOWN semantics and never reopen the one-start permission.

Normal observations are deliberately separated: one returned start; whether using was observed; later usingfalse; same bread components and count decreased exactly1; food/saturation before/after; release proof. Count/food deltas are observations, not guaranteed causal attribution. Notusing without observed count decrease is `finished/unobserved`, expiry/stop is `interrupted`; both can be known once release is proven. Never turn 1attempt into “ate successfully”, and never auto-start again to obtain success.

## Public completion and ordinary gameplay risk

Only v6 consume uses .25s bounded readonly status polling, retaining24 evidence slots and original stop/status reserves. Its reporting window is TTL+.5s and does not extend native TTL. All old profiles and non-consume kinds delegate to the original finish implementation. No evidence capacity increase or new timer framework. Original-ID stop/status only; unknown state cannot be cleared by a later successful read or PLAN change.

Alive/context/authority and local current predicates are control facts. HP20, no hurt, no fire or no nearby enemy are not permanent production invariants. Ordinary damage, interruption, misses and death are gameplay results, not automatically protocol UNKNOWN. Upper-layer decisions may avoid current threats or stop eating; exact release decides protocol completion. No all-loaded-entity or future-zero-risk proof.

## Required observations and tests

Only v6 adds bounded current food/use facts and one actual ray-target witness (ID/UUID/type/class/alive/bbox/hit/reach/cooldown), not arbitrary target scans. Unsupported target returns no usable attack witness; navigation need not fail because the crosshair sees another class. Old observation schemas remain unchanged; actual largest v6 wire must remain within64KiB or refuse without publishing a ticket.

Minimum regression: actual338 exact roundtrip/mixed proofs; new closed schema/digest including target/tool/use limits; new-ID wrong owner/target/ray/reach/stack and expired absoluteTTL even with valid ticket → no claim; sameID original report; global UNKNOWN; exactly-one attack/use; packet-possible returned FAIL is1attempt;32tick nominal completion and no same-tick restart;40tick/4s/cancel/disconnect and release exceptions; old owner cannot clear replacement; zero-latency4s poll does not exhaust24slots; no-terminal observation ends original-ID cleanup without clearing UNKNOWN. Branch tests must disclose synthetic physics and any disabled repeated saves. Independent TEST uses explicitly marked materials/entities if needed; formal stays survival/no item spawning or rollback.

Portal entry is not this implementation's execution permission. Normal future crossing uses existing bounded move, known release, readonly real dimension+new world_generation binding, and a new explicit PLAN. No teleport packet/command; session/player UUID need not change on normal dimension transition. Prepare that separate finite handoff before opening the formal world.
