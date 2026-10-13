package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.NeutralMob;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.monster.EnderMan;
import net.minecraft.world.entity.monster.Creeper;
import net.minecraft.world.entity.projectile.Projectile;
import net.minecraft.world.effect.MobEffects;
import net.minecraft.world.item.Items;

/** Opt-in encounter movement only. Re-observes loaded entities before admission and every input callback. */
final class CapabilityEncounterRoute {
    static boolean nativeDangerous(Entity entity) {return entity instanceof Enemy||entity instanceof NeutralMob;}
    static void validate(ClientActionRequest request) {CapabilityEncounterPolicy.validate(request);}
    static String check(Minecraft mc,ClientActionRequest request) {
        if(!request.original().has(CapabilityEncounterPolicy.FIELD))return null;
        var target=CapabilityEncounterPolicy.validate(request);
        if(!CapabilityCombatSafety.healthy(mc.player.getHealth(),Math.max(12,CapabilityCombatSafety.minimum(request.original(),12))))
            return "capability_health_guard";
        long started=System.nanoTime(),tick=mc.level.getGameTime();int examined=0;
        var rows=new ArrayList<CapabilityEncounterPolicy.Observed>();
        var livingFrame=NativeLivingObservation.capture(mc);
        boolean pumpkin=mc.player.getItemBySlot(net.minecraft.world.entity.EquipmentSlot.HEAD).is(Items.CARVED_PUMPKIN);
        try {
            for(Entity entity:mc.level.entitiesForRendering()) {
                if(++examined>CapabilityEncounterPolicy.MAX_EXAMINED||System.nanoTime()-started>CapabilityEncounterPolicy.MAX_SCAN_NANOS)
                    return "encounter_route_observation_incomplete";
                if(entity==mc.player)continue;
                String type=BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString();
                boolean calm=entity instanceof EnderMan enderman&&pumpkin&&!enderman.isCreepy()
                        &&!enderman.hasBeenStaredAt()&&NativeLivingObservation.knownCalmTargetless(mc,entity,livingFrame);
                boolean powered=entity instanceof Creeper creeper&&creeper.isPowered();
                boolean fuse=entity instanceof Creeper creeper&&(creeper.isIgnited()||creeper.swell>0||creeper.getSwellDir()>0);
                double minimum=0;String problem=null;boolean shieldWindow=false;
                if(target!=null&&target.id()==entity.getId()&&target.uuid().equals(entity.getUUID().toString())) {
                    if(type.equals("minecraft:enderman")&&!calm)problem="encounter_route_enderman_not_calm_with_pumpkin";
                    if(entity instanceof Creeper creeper) {
                        minimum=powered?16:12;
                        if(!CapabilitySpeciesPolicy.creeper(minimum,powered,creeper.isIgnited(),creeper.swell,
                                creeper.getSwellDir(),creeper.maxSwell,creeper.explosionRadius))problem="encounter_route_creeper_fuse_guard";
                    }
                    if(type.equals("minecraft:blaze")) {
                        var resistance=mc.player.getEffect(MobEffects.FIRE_RESISTANCE);
                        boolean covered=resistance!=null&&(resistance.isInfiniteDuration()||resistance.getDuration()>=60);
                        minimum=covered?12:16;shieldWindow=!covered;
                        if(!covered&&(!mc.player.getOffhandItem().is(Items.SHIELD)
                                ||!BlazeShieldPolicy.reserve(mc.player.getOffhandItem().getMaxDamage(),mc.player.getOffhandItem().getDamageValue())
                                ||mc.player.getHealth()<=18))problem="encounter_route_blaze_reserve_required";
                    }
                    if(type.equals("minecraft:cave_spider")) {
                        minimum=8;
                        if(mc.player.hasEffect(MobEffects.POISON))problem="encounter_route_poison_stop";
                    }
                }
                rows.add(new CapabilityEncounterPolicy.Observed(entity.getId(),entity.getUUID().toString(),type,
                        new CapabilityEncounterPolicy.Point(entity.getX(),entity.getY(),entity.getZ()),entity.isAlive(),
                        nativeDangerous(entity),entity instanceof Projectile,
                        entity instanceof net.minecraft.world.entity.AreaEffectCloud,calm,fuse,powered,shieldWindow,minimum,problem));
            }
            String problem=CapabilityEncounterPolicy.check(request,new CapabilityEncounterPolicy.Point(mc.player.getX(),mc.player.getY(),mc.player.getZ()),
                    rows,tick,started,mc.level.getGameTime(),System.nanoTime(),true);
            return problem!=null?problem:System.nanoTime()-started>CapabilityEncounterPolicy.MAX_SCAN_NANOS
                    ?"encounter_route_observation_stale":null;
        } catch(RuntimeException unknown) {return "encounter_route_observation_failed";}
    }
    private CapabilityEncounterRoute() {}
}
