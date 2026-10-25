# Scoped stationary target action validation

This candidate exposes only `strike` and `remove_crystal` behind
`target-action-stationary-v1` in request-only mode. The shared integrator owns
catalog/profile registration, resident/runtime admission, native ownership and
mixin insertion. This directory is not a standalone deployable runtime.

## Bounded contract

- One explicitly identified target, stationary full-block support, exact owner,
  session/world/player/level/equipment and original deadline.
- Melee requires an already selected vanilla axe, zero client attack knockback,
  no sweep and an exact final ray. Swords fail before dispatch in this profile.
  Existing `engage` is outside this change.
- Ranged requires the already selected vanilla bow, plain arrows, a full draw
  and one release. This binds 20–40 player use ticks, not a post-onArrowLoose
  power value or server projectile trajectory/damage. The trajectory clearance
  check is the retained full-draw planning model, not a server flight proof.
  No retarget, pathfinding, equipment setup or automatic retry.
- Preserve Enderman shelter; blaze fire-resistance or full shield-window policy;
  creeper fuse and cave-spider poison guards; crystal clearance/collateral;
  dragon phase 6/7 and exact head identity/ray.
- Client-local and final connection-send proof counts are distinct. Packet HEAD
  is only a matching token, not a second packet charge. Exact packet classes,
  target/hand/pose and offense kind are revalidated after callback-backed checks.
  The bow-draw ammo argument is separately identity/component-bound across them,
  including when a projectile hook returns a detached copy.
- Interrupted bow draws stop local use without sending a release-to-fire packet.
  Their server outcome is UNKNOWN and quarantined. Cleanup never reacquires a
  preempted owner or uses ordinary-admission authority. Final stop cleanup also
  binds the original use-stack object and hand across the onStopUsing callback.
- The final pure snapshot covers every consumed player policy input, inventory
  and carried stack identity, target mapping, projectile owner/velocity, and the
  fresh calm/targetless observation predicate. Its loaded block footprint covers
  the station, Enderman roof and each exact melee/bow segment with a one-cell
  margin. Unknown/dynamic block shape readers and over-budget footprints refuse
  admission rather than guessing. It does not scan an arbitrary 32-cubed volume.
- Living target disappearance is not death. Health loss is observed, not causal
  attribution. Crystal success means stable absence in the loaded local area,
  not absence of all world crystals.

The stationary melee primitive omits the optional item-callback swing animation.
Its single attack packet and exact local attack remain the offense contract.
The owned use key is the original exact vanilla KeyMapping object, including
cleanup; replacing options or the key cannot redirect a later input write.

## Tests and what they establish

`run_dispatch_hook_checks.py` compiles the real production ScopedTargetDispatch,
TargetActionEffectBudget, TargetActionReaderPolicy and CombatCallbackFence with
small Minecraft/guard test doubles, then executes their actual hook methods.
It covers bounded lifetime, owner replacement/cancel, late deadline/tick changes,
post-event mutation seams, duplicate packets/local effects, exact dragon head
versus body identity, forced sweep/knockback rejection and cleanup ownership.
It also rejects initial/final callback replacement of captured bow/ammo/use
arguments and a non-vanilla nested packet Action without invoking that Action.
It does not load mixins or execute the real Minecraft geometry/policy guard.
The late-policy-input dispatch cases use a geometry-change test double; the
separate actual native checks exercise the production pure comparator and
per-segment footprint math. Raw-world capture completeness is independently
source-reviewed, not represented as a constructed Minecraft-world test.

`ScopedTargetAdmissionChecks.java` runs actual ScopedTargetAction.validateIntent
and retained native target policies using the official named Minecraft classes.
Compile it against a full integrated native-source compile plus the official
AT classpath. It does not launch Minecraft or construct a game world.

`test_target_action_chain.py` exercises public ToolboxService → OwnerRuntimeBackend
→ Runtime → IntentClient → watchdog → Resident methods. Only the final native
HTTP endpoint is synthetic. It covers one melee/bow/crystal dispatch, phase 6/7
dragon health-loss evidence, sheltered Enderman and pre-submit refusals, missing
living targets, UNKNOWN quarantine, lost submit and exact cancellation.

Run with `PYTHONDONTWRITEBYTECODE=1` and `python -B`; subprocesses inherit the
same setting. Native test compilation uses `-J-Xmx256m`, execution `-Xmx256m`.
Full native-source compilation uses `-J-Xmx512m -proc:none --release 21`.
Set JAVA_HOME to an approved JDK21 and use the verified official AT-transformed
compile classpath. Do not substitute the partial patched client jar alone.

## Mandatory shared final seams

Readiness requires all of these installed, in addition to exact native ownership:

1. Attack/use/release caller gates and packet HEAD/final Connection.send gates.
2. LivingEntity.startUsingItem, after onItemUseStart, before useItem PUTFIELD;
   validate captured stack/hand/72000 duration and charge use once.
3. Bow release after onUseItemStop and onArrowLoose; charge only at draw HEAD.
4. Player.attack primary Entity.hurt seam; reject sweep and secondary knockback.
5. Entity.isInvulnerableTo RETURN after its NeoForge callback, exact DamageSource.
6. Player.attack post-sound setLastHurtMob/cooldown and GameMode final cooldown.
7. LivingEntity.stopUsingItem, after onStopUsing, before useItem PUTFIELD.
8. GameMode use-item result replacement before Player.setItemInHand; scoped bow
   and shield actions refuse this callback-produced replacement branch entirely.

The exact packet action field is compared by identity to the vanilla attack
singleton through a narrow trusted field reader; Action.dispatch is never used
for validation. Readiness is false if the exact reader is unavailable.

The module returns false readiness if these markers are absent. Compilation,
offline proofs and bytecode shape checks are not a claim that a mixin was loaded
or that an ordinary-world fight, shield cycle, crystal shot or dragon hit passed.
A separate approved test runtime/world is still required for those claims.
