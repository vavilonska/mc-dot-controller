# Exact Bee route-v2 reader and mechanics review

## Evidence and scope

This is a static review of pinned Minecraft 1.21.1 mapped class bytes, together with executable production reader/controller tests against explicit synthetic engine inputs. It does not certify live AI, actual physics, future motion, a world, or arbitrary bytecode modifications by other mods.

The executable `audit_readers.py` requires compiler JAR SHA-256 `1c47e83623a9a2634db3f3b2b93ebf69f0bfe5d975cc038248135d289d772b6f`. This existing compiler JAR derives from accepted mapped game JAR `2e25a85c5e1f78bc4823220e9e4ca0469941a43d00ca169abdfee25787a82814`, with only the already-approved Entity.getSharedFlag access flags made public. This change adds no access transformer. It records hashes and disassembly of 26 hierarchy, coordinate-reader and mechanics classes and resolves 30 called entity readers. No game class is loaded or initialized by this audit.

## Exact readers

A live client Bee must be exactly `net.minecraft.world.entity.animal.Bee` with `EntityType.BEE`. The same exact class and registry check gates the server-only `BeeRouteState`; subclasses cannot produce that state. The existing shared `BeeState` separately requires the same exact class/type. Null/missing either state never establishes calm.

Bee does not override the 22 existing generic identity, position, AABB, velocity, interpolation, health, target, removal, passenger, leash, fire and effect readers. They resolve to the existing Entity/LivingEntity/Mob field-reader chain. The current target is checked for null without invoking its referent's getters on the route callback. `hurtTime` and `noPhysics` retain the existing raw-field checks.

The new Bee-specific accessors are:
- `NeutralMob.isAngry`: exactly remaining anger time greater than zero.
- `Bee.getRemainingPersistentAngerTime`: a SynchedEntityData integer read.
- `Bee.getPersistentAngerTarget`: direct UUID field read.
- `Bee.hasStung` and `hasNectar`: the private `getFlag` helper reads synced DATA_FLAGS_ID bits 4 and 8.
- `Bee.getHivePos` and `getSavedFlowerPos`: direct stored BlockPos references. The source accepts only null, exact BlockPos, or exact BlockPos.MutableBlockPos, then copies x/y/z into an immutable primitive BeePosition record through inherited Vec3i field readers. Arbitrary subclasses of either class remain unavailable and their coordinate getters are never invoked. It never reads a hive, flower block, path, goal, brain, capability, collision shape, or nearby world entity while extracting these new facts.
- Generic server alive/aggressive/current-target facts remain the existing owning-server-thread NativeLivingObservation contract. `Mob.isAggressive` reads its synced mob flag. Additional facts are immutable values before publication.

Client synced anger and stung state are checked too: old calm server facts cannot override locally observed anger or a sting. Server-only persistent anger and target authority is never inferred from client target null.

## Attacks, anger and sting lifecycle

The pinned BeeAttackGoal starts and continues only when the underlying melee goal permits it, the Bee is angry and it has not stung. BeeBecomeAngryTargetGoal and BeeHurtByOtherGoal can select or propagate targets; the general NeutralMob logic maintains persistent anger, supports universal-anger behavior, clears or changes targets and decrements anger time. Therefore `current_target == null` alone and `aggressive == false` alone are insufficient.

Successful `Bee.doHurtTarget` applies sting damage, increments the victim's stinger count, applies poison on normal/hard difficulty, sets `hasStung`, and calls `stopBeingAngry`. A just-stung Bee can consequently look calm under the old anger/target triad while its post-sting death lifecycle remains active. Route-v2 explicitly refuses every stung Bee. It also requires alive, not aggressive, null current target, angry false, zero remaining anger ticks, and null persistent anger target. No target UUID is treated as permission to fight.

The source does not call attack, damage, goal-selection, target-selection or anger-update methods. It reads results of the owning server tick.

## Nectar, hive and flower transitions

Pollination can update nectar and saved flower state; goals can move a Bee toward a flower or hive. `wantsToEnterHive` depends on the stay-out timer, pollination, absence of sting/target, nectar or tiredness or weather/time, and nearby fire. BeeEnterHiveGoal can add an occupant to a hive; hive occupancy removes the world entity. Hive release can produce a newly visible entity and may assign a target when disturbed. Those mechanics are not route authority.

Nectar and hive/flower coordinates are retained as complete sampled lifecycle facts. They need no geometric separation rule because a stored destination is not a current collision body or a verified future path. Fresh snapshots may change these facts across callbacks without refusal when all calm and geometry conditions still hold. A different published batch during a callback is permitted only when its complete, fresh, monotonic source contains exactly equivalent immutable facts for every guarded Bee; any within-callback state change still invalidates that callback, even when both states are calm. Entered/removed or reintroduced bees are handled by the same complete loaded enumeration, object/UUID/id/type checks, and next-callback source matching. There is no teleport, hive inspection, future path guarantee or assumption that return-to-hive is harmless.

## Source, freshness and coverage boundary

The shared source coverage is unchanged: private integrated server only, one player, at most 4,096 inspected entities and 256 Mob rows within 128 blocks of that player. An observed client Bee outside that source radius, missing row, partial batch, wrong UUID/id/type, wrong dimension/context, expired/future source or wrong tick does not qualify, even when arbitrarily far. No distance exemption bypasses missing authority, and the T39 refusal did not establish its offending Bee's distance or UUID.

The server observer owns all live server getter reads. The client route works only with immutable Batch/Row values. Each callback captures a fresh optional batch; post-hook comparisons reuse exactly that batch and reject changed client identities/fields. The final no-hook boundary checks the current publication atomically under the Store monitor: context, server-level identity and dimension remain identical; coverage remains complete and bounded; every guarded Bee retains identical UUID/id/type and all immutable Row fields except nonregressing source tick/nano. Both captured and current sources must remain within 250 ms and five ticks, and the client tick cannot advance during the callback. This uses immutable values only, with no game getters or supplied callbacks under the monitor. The original captured witness and clocks are retained; current publication is never silently substituted. Publication after that check is a subsequent event, not a guarantee about future server state. A fresh batch is obtained on the next callback, never pinned for the whole action. Witness construction performs an additional no-hook evidence fence after taking its `admitted_nano`, making source-age checks cover admission-end time too.

## Geometry and negotiation

Only the new negotiated `movement-local-segment-spatial-stop-v2` / `route-spatial-stop-v2` pair permits Bee rows, in a schema-2 frame. The response-size diagnostic uses schema 8. Old route-stop-v1, threat, ordinary movement, mining and placement acceptance are unchanged; shared native_living JSON also remains unchanged outside the v2 witness.

Every Bee row includes full finite current position/AABB/velocity/interpolation target and the exact remaining-action projected AABB. The projection must be strictly separated from the whole context prism, not merely the path body. Current overlap, boundary touch, velocity crossing, interpolation crossing and their combined envelope all refuse. Full enumeration, duplicate identities/objects, state flags, finite-size budgets, same-callback comparisons, terrain equivalence, input ownership and unknown late-motion settlement are retained. Nothing here ignores bees globally, admits unknown far entities, authorizes defense, retries a rejected move or resumes paused work.

## Common types still unsupported

The closed native lists still reject live Rabbit, Wolf, Fox, Goat, Pufferfish, Dolphin, Llama/TraderLlama, PolarBear, Panda, IronGolem, Enderman and ZombifiedPiglin, as well as other unlisted threats, projectiles, explosives and modded subclasses, even if far away. This is an allowlist-scope audit, not approval of those species' mechanics. Rabbit variants, retaliation, ram/sting/spit/contact damage, owner-defense, anger and teleport behavior need separate exact readers and policy review before any expansion. No unrelated species is implemented in this candidate.

## Ordinary vanilla pollination and the October 16 correction

The pinned BeePollinateGoal.findNearestBlock bytecode allocates an exact BlockPos.MutableBlockPos at offset 9, assigns it local slot 5, and returns that same reference via Optional.of at offsets 128–133. canBeeUse takes Optional.get and puts the object directly into Bee.savedFlowerPos at offset 62. Neither method calls immutable(). Therefore the previous exact BlockPos-only check systematically omitted route extension evidence after this ordinary vanilla path. This proves a source compatibility defect; the existing T40 receipt lacks the native reason/read status and does not prove that T40 took this branch.

The narrowly expanded reader accepts the exact pinned MutableBlockPos class only. Both accepted coordinate classes inherit getX/getY/getZ from Vec3i; static audit asserts no override and pure field-read bytecode. The owning-server-thread reader copies three primitive ints immediately. No mutable object is published. BeePositionPinnedProbe exercises the actual pinned coordinate classes against production trust/copy helpers, verifies immutable coordinates after mutation, and verifies zero unknown-subclass getter calls. The route engine separately drives the production exact-row reader and route admission under explicit synthetic engine values. Its mutable-success witness retains hive (1,2,3) and flower (4,5,6) despite later mutation of the input positions. These tests do not execute a world or AI loop.

## Bounded refusal diagnostics

When route-v2 has captured a complete Bee row and a policy, comparison, or final freshness fence refuses, an optional schema-1 native_bee_diagnostic object upgrades only the route_entity_rejection envelope to schema 2. Legacy schema-1 envelopes remain byte-for-byte unchanged when detail is unavailable. Detail contains a closed entity identity/geometry object; the original native known/reason/coverage/inspection/sample facts; exact immutable source clocks when a captured row exists; route wire presence versus stored-state presence and closed read status; captured source/context flags; and same-callback client world/player/route context. Unknown sample clocks stay null, missing source rows do not imply an out-of-radius distance, and client distance is not server exclusion proof. Diagnostic construction failure omits detail without replacing the refusal.

The detail is capped at 8,192 UTF-8 bytes using a null-preserving encoding. Closed strings, canonical signed clocks and UUIDs, finite fixed-length geometry and nontruncated fields prevent arbitrary exception text or unbounded data from escaping. BridgeJson preserves nulls only for the new schema-2 Bee diagnostic contract; all old witness/nearby/native_living formats remain unchanged. The original rejection code, HTTP 409, admission guards, effect certainty, no-retry and unknown handling are unchanged. The full native runner re-encodes every original engine-produced refusal with production Rejected.response and BridgeJson and requires exact byte equality. BridgeServer.sendJson uses this same BridgeJson.toJson encoder.
