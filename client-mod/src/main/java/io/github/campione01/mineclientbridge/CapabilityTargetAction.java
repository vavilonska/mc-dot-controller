package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import java.util.HashSet;
import java.util.UUID;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.BlockPos;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.NeutralMob;
import net.minecraft.world.entity.boss.EnderDragonPart;
import net.minecraft.world.entity.boss.enderdragon.EnderDragon;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.projectile.Projectile;
import net.minecraft.world.item.AxeItem;
import net.minecraft.world.item.SwordItem;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

/** One real melee strike or one fully drawn bow release. No auto-repeat, pursuit or kill inference.
 * ClientActions owns the action lifetime and per-callback capability guard. */
final class CapabilityTargetAction {
    record Step(String status, String reason, JsonObject evidence) { }
    private static final Set<String> LIVING_TYPES=Set.of("minecraft:zombie","minecraft:husk",
            "minecraft:zombie_villager","minecraft:skeleton","minecraft:stray","minecraft:bogged",
            "minecraft:shulker","minecraft:spider","minecraft:cave_spider","minecraft:creeper","minecraft:enderman","minecraft:blaze");
    private final JsonObject body, evidence=new JsonObject();
    private final ClientLevel level;
    private final LocalPlayer player;
    private final Vec3 origin;
    private final int targetId, dragonPhase, drawTicks;
    private final String targetUuid,targetType,world,session;
    private final boolean shooting,shieldWindow;
    private final net.minecraft.world.item.ItemStack shield;
    private boolean shieldStarted,shieldReleased,preCoverComplete,preCoverSawCharge;
    private int preCoverTicks;
    private long shieldStartTick;
    private int coverTicks;
    private final CapabilityUseTransition itemUseTransition=new CapabilityUseTransition();
    private final Set<UUID> projectilesBeforeShot=new HashSet<>();
    private Vec3 shotDirection=Vec3.ZERO;
    private final float initialHealth;
    private final LivingEntity targetWitness;
    private final float targetInitialHealth;
    private float targetMinHealth;
    private boolean targetDeadObserved;
    private long targetObservationTick;
    private final double minHealth;
    private final long deadline;
    private float expectedYaw,expectedPitch;
    private boolean drawStarted,dispatched,released,useOwned;

    static void validate(JsonObject body) {
        String action=ClientActionRequest.string(body,"action");
        ClientActionRequest.require(action.equals("attack_entity") || action.equals("shoot_entity"),"invalid_target_action");
        String type=ClientActionRequest.string(body,"target_type");
        boolean shoot=action.equals("shoot_entity"),dragon=type.equals("minecraft:ender_dragon");
        boolean shieldMode=type.equals("minecraft:blaze")&&body.has("blaze_safety_mode")&&ClientActionRequest.string(body,"blaze_safety_mode").equals("shield_window");
        ClientActionRequest.require(LIVING_TYPES.contains(type) || (!shoot && (dragon || type.equals("minecraft:shulker_bullet")))
                || (shoot && type.equals("minecraft:end_crystal")),"capability_target_unsupported");
        if(type.equals("minecraft:enderman")) {
            ClientActionRequest.require(!shoot && ClientActionRequest.bool(body,"enderman_shelter_required",false),"enderman_requires_sheltered_melee");
        }
        if(type.equals("minecraft:blaze")) {
            String mode=body.has("blaze_safety_mode")?ClientActionRequest.string(body,"blaze_safety_mode"):"fire_resistance";
            ClientActionRequest.require(shoot && Set.of("fire_resistance","shield_window").contains(mode),"blaze_requires_ranged_safety_mode");
            if(mode.equals("fire_resistance"))ClientActionRequest.require(ClientActionRequest.bool(body,"fire_resistance_required",false),"blaze_requires_fire_resistant_ranged");
            else {
                ClientActionRequest.require(body.has("expected_offhand_item")&&body.get("expected_offhand_item").isJsonObject(),"blaze_exact_offhand_required");
                CapabilityPlacement.number(body,"min_health",18,20);
                int lifetime=ClientActionRequest.integer(body,"timeout_ms",0);
                ClientActionRequest.require(lifetime>=18000&&lifetime<=20000,"blaze_shield_timeout_18000_to20000");
            }
        }
        if(type.equals("minecraft:creeper"))ClientActionRequest.require(shoot && ClientActionRequest.bool(body,"creeper_safety_required",false),"creeper_requires_safe_ranged");
        if(type.equals("minecraft:cave_spider"))ClientActionRequest.require(shoot && ClientActionRequest.bool(body,"poison_guard_required",false),"cave_spider_requires_poison_guarded_ranged");
        if(Set.of("minecraft:enderman","minecraft:blaze","minecraft:creeper","minecraft:cave_spider").contains(type))
            CapabilityPlacement.number(body,"min_health",12,20);
        for(String key:ListFields.UUIDS) {
            String id=ClientActionRequest.string(body,key);
            try { ClientActionRequest.require(UUID.fromString(id).toString().equals(id),"invalid_"+key); }
            catch(IllegalArgumentException e) { throw new ClientActionRequest.Rejected(400,"invalid_"+key); }
        }
        ClientActionRequest.require(ClientActionRequest.integer(body,"target_entity_id",-1)>=0,"invalid_target_entity_id");
        int timeout=ClientActionRequest.integer(body,"timeout_ms",5000);
        ClientActionRequest.require(timeout>=50 && timeout<=(shieldMode?20000:10000),"target_timeout_out_of_mode_bounds");
        int draw=ClientActionRequest.integer(body,"draw_ticks",20);
        ClientActionRequest.require(draw>=20 && draw<=40,"target_draw_20_to_40");
        ClientActionRequest.require(shoot || !body.has("draw_ticks"),"draw_ticks_requires_shoot");
        if(dragon) ClientActionRequest.require(CapabilityTargetPolicy.stationaryDragonPhase(
                ClientActionRequest.integer(body,"expected_dragon_phase",-1)),"dragon_requires_safe_perched_phase");
        else ClientActionRequest.require(!body.has("expected_dragon_phase"),"dragon_phase_requires_dragon");
        if(body.has("min_health")) {
            var v=body.get("min_health");
            ClientActionRequest.require(v.isJsonPrimitive() && v.getAsJsonPrimitive().isNumber()
                    && Double.isFinite(v.getAsDouble()) && v.getAsDouble()>=8 && v.getAsDouble()<=20,"min_health_8_to_20");
        }
        ClientActionRequest.require(!body.has("hotbar_slot"),"target_requires_already_selected_equipment");
    }
    private static final class ListFields {
        static final String[] UUIDS={"target_uuid","expected_world_generation","expected_player_uuid","expected_action_session"};
    }
    static CapabilityTargetAction start(Minecraft mc,JsonObject body) {
        validate(body);return new CapabilityTargetAction(mc,body);
    }
    static boolean shulkerShellOpen(net.minecraft.world.entity.monster.Shulker shulker) {
        return CapabilityCombatSafety.shellOpen(shulker.getRawPeekAmount(),shulker.getClientPeekAmount(1.0F));
    }
    static String shulkerAdmission(Minecraft mc,ClientActionRequest request) {
        if(!Set.of("attack_entity","shoot_entity").contains(request.action())
                ||!ClientActionRequest.string(request.original(),"target_type").equals("minecraft:shulker"))return null;
        JsonObject body=request.original();
        Entity target=mc.level.getEntity(ClientActionRequest.integer(body,"target_entity_id",-1));
        if(!(target instanceof net.minecraft.world.entity.monster.Shulker shulker)||!target.isAlive()
                ||!target.getUUID().toString().equals(ClientActionRequest.string(body,"target_uuid")))
            return "target_missing_not_a_kill";
        return shulkerShellOpen(shulker)?null:"shulker_shell_not_open";
    }
    private CapabilityTargetAction(Minecraft mc,JsonObject b) {
        body=b.deepCopy();level=mc.level;player=mc.player;origin=player.position();
        targetId=ClientActionRequest.integer(b,"target_entity_id",-1);
        targetUuid=ClientActionRequest.string(b,"target_uuid");targetType=ClientActionRequest.string(b,"target_type");
        world=ClientActionRequest.string(b,"expected_world_generation");session=ClientActionRequest.string(b,"expected_action_session");
        dragonPhase=ClientActionRequest.integer(b,"expected_dragon_phase",-1);drawTicks=ClientActionRequest.integer(b,"draw_ticks",20);
        shooting=ClientActionRequest.string(b,"action").equals("shoot_entity");
        shieldWindow=targetType.equals("minecraft:blaze")&&b.has("blaze_safety_mode")&&ClientActionRequest.string(b,"blaze_safety_mode").equals("shield_window");
        shield=player.getOffhandItem().copy();
        if(shieldWindow && (!shield.is(Items.SHIELD)||!CapabilityItemBinding.matches(b.getAsJsonObject("expected_offhand_item"),shield)))throw new ClientActionRequest.Rejected(409,"blaze_exact_shield_required");
        if(shieldWindow && !BlazeShieldPolicy.reserve(shield.getMaxDamage(),shield.getDamageValue()))throw new ClientActionRequest.Rejected(409,"blaze_shield_durability_reserve_64");
        minHealth=CapabilityCombatSafety.minimum(b,8);
        deadline=System.nanoTime()+ClientActionRequest.integer(b,"timeout_ms",5000)*1_000_000L;
        initialHealth=player.getHealth();expectedYaw=player.getYRot();expectedPitch=player.getXRot();
        Entity observedTarget=target();targetWitness=observedTarget instanceof LivingEntity living?living:null;
        targetInitialHealth=targetWitness==null?Float.NaN:targetWitness.getHealth();targetMinHealth=targetInitialHealth;
        targetObservationTick=level.getGameTime();
        evidence.addProperty("target_uuid",targetUuid);evidence.addProperty("target_entity_id",targetId);
        evidence.addProperty("target_type",targetType);evidence.addProperty("server_confirmed",false);
        evidence.addProperty("damage_attributed_to_action",false);evidence.addProperty("dispatches",0);
    }
    private Entity target() {
        Entity e=level.getEntity(targetId);
        return e!=null && e.getUUID().toString().equals(targetUuid)
                && BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).toString().equals(targetType)?e:null;
    }
    private String guard(Minecraft mc) {
        if(!ClientActions.ownsCapabilityTarget(this))return "target_owner_changed";
        if(System.nanoTime()>=deadline)return "target_deadline_exceeded";
        if(mc.player!=player || mc.level!=level || mc.gameMode==null || !world.equals(WorldGeneration.current(level))
                || !session.equals(ClientActions.session())
                || !player.getUUID().toString().equals(ClientActionRequest.string(body,"expected_player_uuid")))return "target_context_changed";
        if(!mc.hasSingleplayerServer() || mc.getSingleplayerServer()==null || mc.getSingleplayerServer().isPublished()
                || !mc.isWindowActive() || mc.screen!=null || mc.isPaused())return "target_private_focused_world_required";
        if(!player.isAlive() || player.isSpectator() || !Float.isFinite(player.getHealth())
                || !CapabilityCombatSafety.healthy(player.getHealth(),minHealth) || initialHealth-player.getHealth()>4)return "target_health_guard";
        if(!player.onGround() || player.isInWater() || player.isInLava() || player.isOnFire()
                || player.isInPowderSnow || player.getTicksFrozen()>0
                || player.position().distanceTo(origin)>.5)return "target_stable_dry_station_required";
        if(CombatRules.manualViewChanged(player.getYRot(),player.getXRot(),expectedYaw,expectedPitch))return "manual_view_changed";
        if(shooting ? !player.getMainHandItem().is(Items.BOW)
                : !(player.getMainHandItem().getItem() instanceof SwordItem || player.getMainHandItem().getItem() instanceof AxeItem))
            return "target_selected_weapon_changed";
        if(shieldWindow&&!sameShield())return "blaze_offhand_shield_changed";
        Entity t=target();
        if(t==null || !t.isAlive())return shieldWindow&&dispatched?dangers(mc,null):"target_missing_not_a_kill";
        if(t instanceof EnderDragon d && d.getPhaseManager().getCurrentPhase().getPhase().getId()!=dragonPhase)
            return "dragon_phase_changed";
        if(!dispatched && t instanceof net.minecraft.world.entity.monster.Shulker shulker
                &&!shulkerShellOpen(shulker))return "shulker_shell_not_open";
        double range=player.position().distanceTo(t.position());
        if(t instanceof net.minecraft.world.entity.monster.EnderMan && !CapabilityShelter.safe(mc))return "enderman_shelter_not_observed";
        if(t instanceof net.minecraft.world.entity.monster.Creeper creeper && !CapabilitySpeciesPolicy.creeper(range,creeper.isPowered(),creeper.isIgnited(),creeper.swell,creeper.getSwellDir(),creeper.maxSwell,creeper.explosionRadius))return "creeper_fuse_or_blast_guard";
        if(t instanceof net.minecraft.world.entity.monster.Blaze blaze) {
            if(shieldWindow) {
                if(!BlazeShieldPolicy.range(range))return "blaze_shield_range_16_to32";
                if(preCoverComplete && !dispatched && (blaze.isCharged()||fireballsNear()))return "blaze_draw_window_closed";
                if(!preCoverComplete && !shieldStarted && fireballsNear())return "blaze_initial_projectile_window_unsafe";
            } else {
                var resistance=player.getEffect(net.minecraft.world.effect.MobEffects.FIRE_RESISTANCE);
                boolean covered=resistance!=null && (resistance.isInfiniteDuration()||resistance.getDuration()>=(drawStarted?20:drawTicks+40));
                if(!CapabilitySpeciesPolicy.blaze(range,covered))return "blaze_fire_resistance_or_range_guard";
            }
        }
        if(t instanceof net.minecraft.world.entity.monster.CaveSpider && !CapabilitySpeciesPolicy.caveSpider(range,player.hasEffect(net.minecraft.world.effect.MobEffects.POISON)))return "cave_spider_poison_or_range_guard";
        return dangers(mc,t);
    }
    private String dangers(Minecraft mc,Entity t) {
        int count=0;
        boolean crystal=targetType.equals("minecraft:end_crystal");
        var livingFrame=NativeLivingObservation.capture(mc);
        double distance=t==null?Double.POSITIVE_INFINITY:player.position().distanceTo(t.position());
        if(crystal && !CapabilityTargetPolicy.crystalClear(distance))return "crystal_blast_clearance_required";
        for(Entity e:level.entitiesForRendering()) {
            if(++count>1024)return "target_entity_scan_budget";
            if(e==player || e==t || !e.isAlive())continue;
            String type=BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).toString();
            if(shieldWindow && CapabilityEncounterPolicy.dangerous(type,e instanceof Enemy||e instanceof NeutralMob) && e.distanceToSqr(player)<=32*32)return "blaze_shield_requires_isolated_hostile";
            boolean calmPumpkinEnderman=e instanceof net.minecraft.world.entity.monster.EnderMan enderman
                    && player.getItemBySlot(net.minecraft.world.entity.EquipmentSlot.HEAD).is(Items.CARVED_PUMPKIN)
                    && !enderman.isCreepy() && !enderman.hasBeenStaredAt()
                    && NativeLivingObservation.knownCalmTargetless(mc,e,livingFrame);
            if(type.equals("minecraft:enderman") && !calmPumpkinEnderman && e.distanceToSqr(player)<=48*48)return "enderman_gaze_unplanned";
            if(e instanceof net.minecraft.world.entity.monster.Creeper creeper && e.distanceToSqr(player)<(creeper.isPowered()?18*18:14*14)
                    && (creeper.isIgnited()||creeper.swell>0||creeper.getSwellDir()>0))return "nearby_creeper_fuse_risk";
            if(e instanceof Projectile && e.distanceToSqr(player)<25) {
                boolean covered=shieldWindow&&shieldStarted&&e instanceof net.minecraft.world.entity.projectile.SmallFireball
                    &&BlazeShieldPolicy.frontal(expectedYaw,e.getX()-player.getX(),e.getZ()-player.getZ());
                if(!covered && !outgoingOwnArrow(e,type))return "nearby_projectile";
            }
            if(type.equals("minecraft:area_effect_cloud") && e.distanceToSqr(player)<100)return "nearby_effect_cloud";
            if(!calmPumpkinEnderman && CapabilityEncounterPolicy.dangerous(type,e instanceof Enemy || e instanceof NeutralMob)
                    && e.distanceToSqr(player)<64)return "non_target_threat_near";
            if(crystal && e instanceof LivingEntity && e.distanceToSqr(t)<144)return "crystal_blast_collateral";
            if(!shooting && e instanceof LivingEntity
                    && e.getBoundingBox().inflate(1.5,1,1.5).intersects(t.getBoundingBox()))return "target_sweep_collateral";
        }
        return null;
    }
    Step tick(Minecraft mc) {
        if(shieldWindow && !preCoverComplete)return preCover(mc);
        if(shieldWindow && dispatched)return cover(mc);
        if(dispatched)return done("succeeded","single_dispatch_complete_observe_outcome");
        String problem=guard(mc);if(problem!=null)return done("failed",problem);
        Entity t=target(),hitTarget=t;
        if(t instanceof EnderDragon d) {
            hitTarget=null;
            for(EnderDragonPart part:d.getSubEntities())if(part.name.equals("head"))hitTarget=part;
            if(hitTarget==null)return done("failed","dragon_head_unavailable");
            evidence.addProperty("dragon_phase_id",dragonPhase);evidence.addProperty("dragon_part","head");
        }
        Vec3 eye=player.getEyePosition(),point=hitTarget.getBoundingBox().getCenter(),delta=point.subtract(eye);
        double flat=Math.hypot(delta.x,delta.z),elevation=Math.atan2(delta.y,flat);
        if(shooting) {
            if(eye.distanceTo(point)<4 || eye.distanceTo(point)>CapabilityTargetPolicy.MAX_SHOT_DISTANCE)
                return done("failed","shot_range_4_to_32");
            elevation=CapabilityTargetPolicy.bowElevation(flat,delta.y);
            if(!Double.isFinite(elevation))return done("failed","shot_trajectory_unavailable");
            problem=shotCorridor(eye,point,elevation,t);
            if(problem!=null)return done("failed",problem);
        }
        // Guard against callbacks during geometry reads before replacing our owned view.
        problem=guard(mc);if(problem!=null)return done("failed",problem);
        expectedYaw=(float)Math.toDegrees(Math.atan2(-delta.x,delta.z));expectedPitch=(float)-Math.toDegrees(elevation);
        player.setYRot(expectedYaw);player.setXRot(expectedPitch);player.setYHeadRot(expectedYaw);
        problem=guard(mc);if(problem!=null)return done("failed",problem);
        mc.gameRenderer.pick(1.0F);
        problem=guard(mc);if(problem!=null)return done("failed",problem);
        if(shooting) {
            if(!drawStarted) {
                if(player.isUsingItem() || mc.options.keyUse.isDown())return done("failed","item_use_already_active");
                if(player.getProjectile(player.getMainHandItem()).isEmpty())return done("failed","bow_ammunition_required");
                drawStarted=true;useOwned=true; // Mark ownership before any potentially reentrant callback.
                mc.options.keyUse.setDown(true);
                problem=guard(mc);if(problem!=null)return done("failed",problem);
                itemUseTransition.run(()->mc.gameMode.useItem(player,InteractionHand.MAIN_HAND));
                problem=guard(mc);if(problem!=null)return done("failed",problem);
                if(!player.isUsingItem())return done("failed","bow_draw_not_started");
                return done(null,"drawing_bow");
            }
            if(!player.isUsingItem() || !mc.options.keyUse.isDown())return done("failed","bow_draw_interrupted");
            if(player.getTicksUsingItem()<drawTicks)return done(null,"drawing_bow");
            problem=guard(mc);if(problem!=null)return done("failed",problem);
            // Bind exclusions to arrows absent immediately before this one release.
            if(shieldWindow) {
                for(Entity existing:level.entitiesForRendering())if(existing instanceof Projectile)projectilesBeforeShot.add(existing.getUUID());
                shotDirection=player.getLookAngle();
            }
            problem=guard(mc);if(problem!=null)return done("failed",problem);
            dispatched=true;evidence.addProperty("dispatches",1);
            ClientActions.markCapabilityDispatched(this);
            evidence.addProperty("draw_ticks",player.getTicksUsingItem());
            itemUseTransition.run(()->mc.gameMode.releaseUsingItem(player));
            // A resumed old callback must not clear the replacement owner's input.
            if(!ClientActions.ownsCapabilityTarget(this))return done("failed","target_owner_changed");
            released=!player.isUsingItem();
            mc.options.keyUse.setDown(false);useOwned=false;
            problem=guardAfterDispatch(mc);if(problem!=null)return done("failed",problem);
            if(!released)return done("failed","bow_release_unconfirmed");
            return shieldWindow?cover(mc):done("succeeded","bow_released_observe_outcome");
        }
        if(!(mc.hitResult instanceof EntityHitResult hit) || hit.getEntity()!=hitTarget
                || !CapabilityTargetPolicy.meleeReach(eye.distanceTo(hit.getLocation()),player.entityInteractionRange()))
            return done("failed","exact_target_not_in_melee_reach");
        if(!CombatRules.cooldownReady(player.getAttackStrengthScale(.5F)))return done(null,"waiting_attack_cooldown");
        problem=guard(mc);if(problem!=null)return done("failed",problem);
        dispatched=true;evidence.addProperty("dispatches",1);
        mc.gameMode.attack(player,hitTarget);
        problem=guardAfterDispatch(mc);if(problem!=null)return done("failed",problem);
        player.swing(InteractionHand.MAIN_HAND);
        problem=guardAfterDispatch(mc);if(problem!=null)return done("failed",problem);
        return done("succeeded","melee_dispatched_observe_outcome");
    }
    private boolean outgoingOwnArrow(Entity entity,String type) {
        if(!shieldWindow || !dispatched || !released || !(entity instanceof net.minecraft.world.entity.projectile.AbstractArrow arrow)
                || !(type.equals("minecraft:arrow")||type.equals("minecraft:spectral_arrow"))
                || arrow.getOwner()!=player || projectilesBeforeShot.contains(entity.getUUID()))return false;
        Vec3 motion=entity.getDeltaMovement();
        return BlazeShieldPolicy.outgoingArrow(entity.getX()-player.getX(),entity.getZ()-player.getZ(),
                motion.x,motion.z,shotDirection.x,shotDirection.z);
    }
    private boolean sameShield() {
        var current=player.getOffhandItem().copy();
        if(!current.is(Items.SHIELD)||current.getCount()!=shield.getCount()||current.getDamageValue()<shield.getDamageValue())return false;
        current.setDamageValue(shield.getDamageValue());return CapabilityItemBinding.same(current,shield);
    }
    private boolean fireballsNear() {
        int scanned=0;
        for(Entity e:level.entitiesForRendering()) {
            if(++scanned>1024)return true;
            if(e instanceof net.minecraft.world.entity.projectile.SmallFireball && e.isAlive()&&e.distanceToSqr(player)<=32*32)return true;
        }
        return false;
    }
    private Step preCover(Minecraft mc) {
        String problem=guard(mc);if(problem!=null)return done("failed",problem);
        if(!shieldStarted) {
            if(player.isUsingItem())return done("failed","blaze_shield_existing_use");
            shieldStarted=true;shieldStartTick=level.getGameTime();useOwned=true;
            mc.options.keyUse.setDown(true);
            itemUseTransition.run(()->mc.gameMode.useItem(player,InteractionHand.OFF_HAND));
            if(!ClientActions.ownsCapabilityTarget(this))return done("failed","target_owner_changed");
        }
        if(!player.isUsingItem()||player.getUsedItemHand()!=InteractionHand.OFF_HAND||!player.getUseItem().is(Items.SHIELD))return done("failed","blaze_shield_interrupted");
        preCoverTicks=(int)(level.getGameTime()-shieldStartTick);
        if(preCoverTicks<0)return done("failed","blaze_shield_tick_regressed");
        if(preCoverTicks>=5&&!player.isBlocking())return done("failed","blaze_shield_not_blocking");
        Entity t=target();
        if(!(t instanceof net.minecraft.world.entity.monster.Blaze blaze)||!blaze.isAlive())return done("failed","blaze_precover_target_changed");
        Vec3 direction=t.position().subtract(player.position());
        expectedYaw=(float)Math.toDegrees(Math.atan2(-direction.x,direction.z));expectedPitch=0;
        player.setYRot(expectedYaw);player.setXRot(expectedPitch);
        boolean charged=blaze.isCharged();if(charged)preCoverSawCharge=true;
        boolean fireballs=fireballsNear();
        evidence.addProperty("shield_blocking_observed",player.isBlocking());evidence.addProperty("risk_remaining",charged||fireballs);
        if(BlazeShieldPolicy.initialReady(preCoverSawCharge,preCoverTicks,charged,fireballs)) {
            itemUseTransition.run(()->mc.gameMode.releaseUsingItem(player));
            if(!ClientActions.ownsCapabilityTarget(this))return done("failed","target_owner_changed");
            shieldReleased=!player.isUsingItem();mc.options.keyUse.setDown(false);useOwned=false;
            if(!shieldReleased)return done("failed","blaze_shield_release_unconfirmed");
            preCoverComplete=true;shieldStarted=false;shieldReleased=false;
            return done(null,"blaze_cooldown_observed_prepare_single_draw");
        }
        if(preCoverTicks>=BlazeShieldPolicy.MAX_PRE_COVER_TICKS)return done("failed","blaze_precover_cycle_not_observed");
        return done(null,"blaze_shield_observe_first_volley");
    }
    private Step cover(Minecraft mc) {
        String problem=guardAfterDispatch(mc);if(problem!=null)return done("failed",problem);
        if(!shieldStarted) {
            if(player.isUsingItem())return done("failed","blaze_shield_existing_use");
            shieldStarted=true;shieldStartTick=level.getGameTime();useOwned=true;
            mc.options.keyUse.setDown(true);
            itemUseTransition.run(()->mc.gameMode.useItem(player,InteractionHand.OFF_HAND));
            if(!ClientActions.ownsCapabilityTarget(this))return done("failed","target_owner_changed");
            if(!player.isUsingItem()||player.getUsedItemHand()!=InteractionHand.OFF_HAND)return done("failed","blaze_shield_use_unconfirmed");
        }
        if(!player.isUsingItem()||player.getUsedItemHand()!=InteractionHand.OFF_HAND||!player.getUseItem().is(Items.SHIELD))return done("failed","blaze_shield_interrupted");
        coverTicks=(int)(level.getGameTime()-shieldStartTick);
        if(coverTicks<0)return done("failed","blaze_shield_tick_regressed");
        if(coverTicks>=5&&!player.isBlocking())return done("failed","blaze_shield_not_blocking");
        Entity t=target();
        if(t!=null&&t.isAlive()) {
            Vec3 direction=t.position().subtract(player.position());
            expectedYaw=(float)Math.toDegrees(Math.atan2(-direction.x,direction.z));expectedPitch=0;
            player.setYRot(expectedYaw);player.setXRot(expectedPitch);
        }
        boolean charged=t instanceof net.minecraft.world.entity.monster.Blaze blaze&&blaze.isAlive()&&blaze.isCharged();
        boolean fireballs=fireballsNear();
        evidence.addProperty("shield_blocking_observed",player.isBlocking());evidence.addProperty("cover_ticks",coverTicks);
        evidence.addProperty("risk_remaining",charged||fireballs);
        if(BlazeShieldPolicy.ready(coverTicks,charged,fireballs)) {
            itemUseTransition.run(()->mc.gameMode.releaseUsingItem(player));
            if(!ClientActions.ownsCapabilityTarget(this))return done("failed","target_owner_changed");
            shieldReleased=!player.isUsingItem();mc.options.keyUse.setDown(false);useOwned=false;
            problem=guardAfterDispatch(mc);if(problem!=null)return done("failed",problem);
            return done(shieldReleased?"succeeded":"failed",shieldReleased?"blaze_shield_window_released":"blaze_shield_release_unconfirmed");
        }
        if(coverTicks>=BlazeShieldPolicy.MAX_COVER_TICKS)return done("failed","blaze_shield_cover_budget");
        return done(null,"blaze_shield_cover");
    }
    private String guardAfterDispatch(Minecraft mc) {
        // Target may legitimately die during the call; retain every ownership/context/player guard.
        String p=guard(mc);return "target_missing_not_a_kill".equals(p)?null:p;
    }
    private String shotCorridor(Vec3 eye,Vec3 point,double elevation,Entity target) {
        Vec3 delta=point.subtract(eye);double h=Math.hypot(delta.x,delta.z),time=h/(3*Math.cos(elevation));
        Vec3 previous=eye;
        for(int i=1;i<=24;i++) {
            if(System.nanoTime()>=deadline)return "shot_trajectory_budget";
            double tick=time*i/24,run=3*Math.cos(elevation)*tick;
            Vec3 next=new Vec3(eye.x+delta.x/h*run,eye.y+3*Math.sin(elevation)*tick-.025*tick*tick,eye.z+delta.z/h*run);
            // Reject unloaded chunks across the whole arc segment, including diagonal corners.
            for(int x=(int)Math.floor(Math.min(previous.x,next.x)-.6);x<=(int)Math.floor(Math.max(previous.x,next.x)+.6);x++)
                for(int z=(int)Math.floor(Math.min(previous.z,next.z)-.6);z<=(int)Math.floor(Math.max(previous.z,next.z)+.6);z++)
                    if(!level.hasChunkAt(new BlockPos(x,(int)Math.floor(next.y),z)))return "shot_corridor_unloaded";
            if(level.clip(new ClipContext(previous,next,ClipContext.Block.COLLIDER,ClipContext.Fluid.NONE,player)).getType()!=HitResult.Type.MISS)
                return "shot_blocked_cage_or_terrain";
            int examined=0;
            for(Entity e:level.entitiesForRendering()) {
                if(++examined>1024)return "shot_entity_scan_budget";
                if(e==player || e==target || !e.isAlive())continue;
                if(e.getBoundingBox().inflate(.6).clip(previous,next).isPresent())return "shot_collateral_corridor";
            }
            previous=next;
        }
        return null;
    }
    private void observeTargetWitness() {
        if(targetWitness==null||!ClientActions.ownsCapabilityTarget(this)||Minecraft.getInstance().level!=level||Minecraft.getInstance().player!=player)return;
        // Retain only actual health from this exact original LivingEntity. Removal alone is never death.
        float health=targetWitness.getHealth();
        if(!Float.isFinite(health)||health<0||!Float.isFinite(targetInitialHealth)||targetInitialHealth<=0)return;
        targetMinHealth=Math.min(targetMinHealth,health);targetObservationTick=level.getGameTime();
        if(health<=0&&!targetWitness.isAlive())targetDeadObserved=true;
    }
    private Step done(String status,String reason) {
        observeTargetWitness();
        evidence.addProperty("phase",reason);evidence.addProperty("pre_cover_ticks",preCoverTicks);
        evidence.addProperty("pre_cover_saw_charge",preCoverSawCharge);evidence.addProperty("pre_cover_complete",preCoverComplete);
        if(targetWitness!=null&&Float.isFinite(targetInitialHealth)) {
            evidence.addProperty("target_initial_health",targetInitialHealth);evidence.addProperty("target_min_observed_health",targetMinHealth);
            evidence.addProperty("target_dead_observed",targetDeadObserved);evidence.addProperty("observation_tick",targetObservationTick);
        }
        evidence.addProperty("bow_draw_started",drawStarted);evidence.addProperty("bow_released",released);
        evidence.addProperty("shield_window",shieldWindow);evidence.addProperty("shield_raised",shieldStarted);evidence.addProperty("shield_released",shieldReleased);
        return new Step(status,reason,evidence.deepCopy());
    }
    void release(Minecraft mc) {
        boolean uncertain=drawStarted && !released;
        try {
            // Never release a half-drawn bow: that would fire during a safety stop.
            if(uncertain && mc.player==player)player.stopUsingItem();
            if(!itemUseTransition.cleanupMayConfirm())throw new IllegalStateException("item_use_transition_unconfirmed");
            if(shieldStarted&&!shieldReleased) {
                if(mc.player!=player||mc.gameMode==null)throw new IllegalStateException("shield_release_context_unconfirmed");
                if(player.isUsingItem()) {
                    if(player.getUsedItemHand()!=InteractionHand.OFF_HAND||!player.getUseItem().is(Items.SHIELD))throw new IllegalStateException("shield_release_hand_unconfirmed");
                    itemUseTransition.run(()->mc.gameMode.releaseUsingItem(player));
                }
                shieldReleased=!player.isUsingItem();
                if(!shieldReleased)throw new IllegalStateException("shield_release_unconfirmed");
            }
        } finally {
            if(useOwned){mc.options.keyUse.setDown(false);useOwned=false;}
        }
        if(uncertain)throw new IllegalStateException("bow_abort_server_release_unconfirmed");
    }
}
