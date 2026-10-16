# Exact far-passive reader and mechanics review

This review concerns Minecraft 1.21.1's pinned mapped class bytes. It is not a claim that a complete world, live loader, future AI, physics, or another mod's mutations are safe. No classes are initialized by the audit. The approved expansion is a closed list of 15 concrete classes; subclasses, registry/class mismatches and all other live types still refuse before geometry exemption.

## Pinned evidence

`audit_readers.py` disassembles the supplied local JAR with `javap -p -c`, records full class hashes and reader-method bodies, follows each superclass chain, and rejects concrete overrides of the called reader surface. The accepted compiler JAR SHA-256 is `1c47e83623a9a2634db3f3b2b93ebf69f0bfe5d975cc038248135d289d772b6f`.

That compiler JAR derives from pinned accepted mapped game JAR `2e25a85c5e1f78bc4823220e9e4ca0469941a43d00ca169abdfee25787a82814`: only Entity.getSharedFlag's access flags change from protected to public. Existing derivation evidence reports every method body and all other uncompressed members unchanged. The production access transformer already requests that getter; this candidate adds no access transformer or permission.

The 15 concrete types resolve every one of the 22 called readers to Entity, LivingEntity, or Mob, with no concrete override:
- Entity: id, UUID, registry type, removal state, x/y/z, final AABB, observed velocity, vehicle, final passenger list, remaining fire ticks, shared fire flag.
- LivingEntity: health, alive/dead, active-effect collection, interpolation targets. Alive and dead queries delegate to audited health/removal readers. Interpolation targets read existing lerp fields or the zero-argument Entity position getters.
- Mob: current client target reference and leash-data reference.

The position/AABB/velocity/target data remain finite, complete and tied to object identity plus UUID/id/type/class. Target is checked only for null, with no getters called on its referent. These client target fields do not establish server calm. The profile does not claim that they do. Health/shared flags use the existing SynchedEntityData read; active effects return existing map values. No collision-shape, damage, AI, travel, target acquisition, or entity capability callback is invoked by the new reader.

The executable audit distinguishes zero-argument position getters from their overloaded offset getters. Its recorded bodies and class hashes, rather than method names alone, are the evidence.

## Per-family mechanics and limits

- Bat: exact `ambient.Bat`. Its server-AI flight/roost code changes ordinary motion; it has no player attack target goal. It remains far-only because flight can change direction. No guarantee is made about its next movement.
- Cod, Salmon, TropicalFish: exact three `animal` classes and AbstractSchoolingFish/AbstractFish chain. AbstractFish registers panic, player avoidance and swim goals; schooling adds follow behavior. Their normal variants do not add the Pufferfish sting mechanics. Pufferfish is explicitly absent. Swimming, flopping and school movement can change velocity, so the full projected envelope must remain outside the context prism at each check.
- Squid and GlowSquid: exact `animal.Squid` and `world.entity.GlowSquid` (not `animal.GlowSquid`). Squid registers movement/flee goals; ink/glow behavior is not projectile attack authority. Current body and motion remain far-only. The inherited reader surface is unchanged.
- Turtle: exact `animal.Turtle`. Breeding, egg laying, water seeking, homing, travel, look and stroll goals are retained as ordinary dynamic behavior, with no player attack target goal. No egg or water-world mutation is authorized by this profile.
- Cat: exact `animal.Cat`. Its actual goal list includes leap and OcelotAttackGoal, with prey target selectors for Rabbit/BabyTurtle. This is not evidence of harmless AI in general. Player movement is allowed only with the complete current observed envelope outside the context prism and no observed target, hurt/fire/effect/leash/riding state. Tame follow-owner movement may relocate later; the profile certifies no future dynamics and never exempts a nearby or newly overlapping cat.
- Ocelot: exact `animal.Ocelot`. Actual prey target selectors are Chicken/BabyTurtle; leap/attack goals exist. It receives the same far-only complete-geometry treatment, never a blanket hostile or unknown-far exemption.
- Parrot: exact `animal.Parrot`. Follow-owner/follow-mob/flying/shoulder goals change future movement. Shoulder/riding state is refused when observed. Cookie poisoning is self-directed item interaction, not an action this profile performs; active effects still refuse.
- Horse, Donkey, Mule: exact three `animal.horse` classes, excluding all other AbstractHorse subclasses (including skeleton/zombie horses and llamas). The inherited goal list includes panic, taming/run-around, breeding, parent-follow, strolling, looking, standing and eating/float goals. Fall handling can damage passengers, which are forbidden by the complete state flags. No riding, taming, inventory or jump input to these entities is authorized.
- Villager: exact `npc.Villager`, excluding ZombieVillager. Its brain uses work/play/core/meet/rest/idle/panic/raid/hide packages. Golem spawning, conversion and other later changes are not a future safety guarantee: a new unallowlisted live entity or changed class at the next check refuses. Trading/inventory callbacks are not invoked by entity reads.
- WanderingTrader: exact `npc.WanderingTrader`. Goals include trading, avoidance, panic, wandering and ordinary self-use of potion/milk. Any observed active effect refuses. TraderLlama is intentionally absent because spit/retaliation mechanics are not reviewed here; loaded llamas will still make the route refuse.

## Geometry and fail-closed boundary

The original eight reviewed non-rabbit classes use `outside_swept`, strictly separated from the complete route body sweep including jump headroom. The 15 additions use `outside_context`, strictly separated from the entire terrain-validation prism. Projection contains the current box, interpolation delta, remaining-action velocity delta, and their combination. Touching is conflict. The entity is never omitted from the frame. Maximum remaining horizon stays 160 minus trusted action ticks; full loaded enumeration (including removed rows), duplicate detection, same-callback object/field comparison, no truncation and response budgets remain.

The list does not add Rabbit, Pufferfish, Dolphin, Goat, Wolf, Fox, Bee, llama, hostile, projectile, explosive, effect cloud, lightning, falling block, unknown, or modded subclasses. These still refuse even when far away. A removed unknown row is accepted only under the existing exact base identity-reader rule and remains an explicit removed identity row.

## Diagnostics

`route_entity_rejection` carries only versioned profile/policy, a finite phase vocabulary, bounded actual registry type or `type_unavailable`, exception category, and allowlisted stable rejection code. Unknown overridden `getType` is never called for diagnostics. Per-row geometry validation runs before leaving that row; aggregate failures clear the type to avoid blaming a different row. Replacement comparisons report type unavailable. No UUID, class, exception text, stack, credentials or fabricated target authority is serialized.

Diagnostics do not change settlement: admission stays no action admitted, ordinary continuation stops under its existing owner, and motion-gate failure remains unknown. No failure triggers retry, combat or route resumption.
