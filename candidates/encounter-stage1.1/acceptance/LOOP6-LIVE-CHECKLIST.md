# .6 staged ordinary-world acceptance (not executed)

Use the existing authorized test operator and an ordinary generated local world. Do not install/restart under authority from this file. Verify runtime version/JAR hash and original immutable action ID/world/player/session. Do not run old Python combat/watchdog around this native action to bypass its gates. Pause other game writers. Record all entities' UUID/type/position/health, difficulty, actual weather/time, armor/weapon/shield, hunger/effects, beginning health, and unmodified terrain. Equipment groups must remain separate.

## First: single-target route and failure correctness
1. On full dry flat ground repeat zombie and skeleton baselines for iron and diamond (3 small trials per group as an initial diagnostic, not statistics).
2. Use a naturally occurring trunk with a verified dry side route. Show the original corridor's true collision, `replanning`, a bounded waypoint route, each fresh tick's body/envelope/cell check, and real reengagement or honest later failure.
3. Reproduce a true lake-edge hole and a terrain configuration with no admitted route. Preserve support rejection. A failed route is not combat completion or escape.
4. Exercise diagonal continuous sweep, small safe corner, real pit, water/lava, unknown/unloaded edge, partial support/height, low canopy, and a changing obstacle. No jumping over an unknown hole.
5. Let a friendly animal/player or collidable vehicle cross the intended segment. Movement must revalidate, never follow the cached plan blindly.
6. Knockback while grounded before a turn and before urgent withdrawal: no forward input until motion admitted for a detour; urgent unready motion reports risk_remaining. Observe residual velocity and physical displacement, not only requested input.
7. Repeated obstruction/recovery: attempts <=3, settling <=10 episode/40 cumulative, original <=30s deadline, original12-block boundary, and cumulative no-closure charge unchanged. Recovery has20-tick episode/two-settled-sample rule.

## Second: stop and collateral safety
8. A friendly player, villager or pet enters sword sweep range. Select a verified axe or fail protected overlap; no incidental damage. Repeat a diagonal bounding-box corner.
9. Introduce a creeper while attacking a zombie, initially from beyond the conservative warning radius. On entry, stop attack that tick, never sweep it, and attempt only the checked flat withdrawal. No close-range fuse gambling.
10. Introduce spider, Enderman, or another unsupported Enemy/NeutralMob. Enderman presence must prevent target-facing aim, including after a health or creeper interruption was already latched. Unsupported types must not become targets by changing the request type.
11. Trigger health<=14 and separately >=4 loss within1s; show the latched reason and never resume offense even after healing. Do not claim who caused damage without evidence.
12. Unknown/truncated/invalid/stale threat observation and health observation gaps: fail closed. Include a final attack-delay/freshness case for axes as well as swords.
13. Give withdrawal a clear full3-block dry route, then an obstructed route and a route blocked by another mob. Even physical completion is risk_remaining until a separately supported safety condition exists. Stop-input evidence alone is not escape success.

## Third: required multi-mob progression, still open
14. Two same-direction zombies, then three, then one flanking zombie. This .6 candidate is expected to interrupt; record correctness and actual remaining risk. Later multi-target strategy must separately demonstrate stable locks, prioritization, and whole-encounter budgets.
15. Zombie+skeleton, then two zombies+skeleton and a flanking skeleton. Account for mob infighting; mob-caused target health loss is not player hit confirmation. Do not score .6 refusal as multi-mob combat completed.
16. Zombie+spider+skeleton+creeper from a known open escape area. First acceptance is no unwanted attack/sweep, prompt threat interruption, terrain-valid bounded withdrawal if possible, honest risk_remaining if not. Multi-kill acceptance remains deferred until spider/multi-target strategy exists; creeper melee remains prohibited.

## Interruptions and terminal accounting
17. Cancel by exact action ID, direct API takeover, GUI opening, player death, world/player replacement, disconnection, deadline expiry, target same-ID/different-UUID replacement and target disappearance. Confirm cleanup/input release, no action replay, no route/budget reset. Actual physical keyboard takeover is a separate unverified path.
18. Record per-trial attack_completed, correct_refusal, actual safe-disengagement evidence (if independently established), risk_remaining/failed, or rescue_contaminated. Any emergency clear/heal/teleport invalidates a success trial; rescue after failure can protect the operator but cannot change the outcome.

Stop the group for any unauthorized collateral hit, stale attack, movement into unsafe/unknown terrain, identity drift, budget reset, missing cleanup, or claimed safety without evidence. Fix and rerun affected cases plus earlier regressions before expanding scope. Friend-server acceptance comes later under its own authorization; local-world evidence is not server compatibility proof.
