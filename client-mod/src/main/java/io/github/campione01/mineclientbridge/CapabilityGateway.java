package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.world.item.Items;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

/** Single close-range ordinary pearl. Discrete loaded swept uncertainty envelope only. */
final class CapabilityGateway {
    static void validate(JsonObject b) {
        ClientActionRequest.require(ClientActionRequest.string(b,"expected_block_id").equals("minecraft:end_gateway"),"gateway_block_required");
        ClientActionRequest.require(b.has("target")&&b.get("target").isJsonObject(),"invalid_gateway_target");
        CapabilityPlacement.position(b.getAsJsonObject("target"));
        ClientActionRequest.require(ClientActionRequest.integer(b,"hotbar_slot",-1)>=0,"gateway_pearl_hotbar_required");
        CapabilityPlacement.number(b,"min_health",12,20);
        ClientActionRequest.require(b.has("expected_block_properties")&&b.get("expected_block_properties").isJsonObject(),"gateway_properties_required");
    }
    static Vec3 target(JsonObject b){return Vec3.atCenterOf(CapabilityPlacement.position(b.getAsJsonObject("target")));}
    static Vec3 spawn(Minecraft mc){return mc.player.getEyePosition().add(0,-.10000000149011612,0);}
    static GatewayTrajectory.Plan trajectory(Minecraft mc,JsonObject b) {
        Vec3 delta=target(b).subtract(spawn(mc)),v=mc.player.getKnownMovement();
        return GatewayTrajectory.plan(delta.x,delta.y,delta.z,v.x,v.z);
    }
    static String check(Minecraft mc,JsonObject b) {
        if(!mc.level.dimension().location().toString().equals("minecraft:the_end"))return "gateway_requires_end";
        if(mc.player.getHealth()<=b.get("min_health").getAsDouble() || !mc.player.onGround()
                || mc.player.hasEffect(net.minecraft.world.effect.MobEffects.LEVITATION))return "gateway_health_or_landing_guard";
        if(!mc.player.getMainHandItem().is(Items.ENDER_PEARL)||mc.player.getCooldowns().isOnCooldown(Items.ENDER_PEARL))return "gateway_pearl_unavailable";
        BlockPos p=CapabilityPlacement.position(b.getAsJsonObject("target"));
        if(!mc.level.hasChunkAt(p)||!CapabilityGuard.blockMatches(mc.level.getBlockState(p),"minecraft:end_gateway",b.getAsJsonObject("expected_block_properties")))return "gateway_target_changed";
        if(!(mc.level.getBlockEntity(p) instanceof net.minecraft.world.level.block.entity.TheEndGatewayBlockEntity gateway) || gateway.isCoolingDown())return "gateway_cooling_or_unknown";
        var plan=trajectory(mc,b);if(plan==null)return "gateway_aperture_not_proven";
        Vec3 start=spawn(mc);
        for(int i=1;i<plan.points().size();i++) {
            var a=plan.points().get(i-1);var c=plan.points().get(i);
            double margin=Math.max(a.uncertainty(),c.uncertainty())+GatewayTrajectory.RADIUS;
            AABB sweep=new AABB(start.add(a.x(),a.y(),a.z()),start.add(c.x(),c.y(),c.z())).inflate(margin);
            for(BlockPos pos:BlockPos.betweenClosed(BlockPos.containing(sweep.minX,sweep.minY,sweep.minZ),BlockPos.containing(sweep.maxX,sweep.maxY,sweep.maxZ))) {
                if(!mc.level.hasChunkAt(pos))return "gateway_pearl_corridor_unloaded";
                if(!mc.level.getFluidState(pos).isEmpty())return "gateway_pearl_corridor_fluid";
                for(AABB box:mc.level.getBlockState(pos).getCollisionShape(mc.level,pos).toAabbs())
                    if(box.move(pos).intersects(sweep))return "gateway_pearl_corridor_blocked";
            }
            int count=0;for(var e:mc.level.entitiesForRendering()) {
                if(++count>1024)return "gateway_entity_scan_budget";
                if(e==mc.player||!e.isAlive())continue;
                var v=e.getDeltaMovement();
                if(!Double.isFinite(v.length()))return "gateway_entity_motion_unknown";
                // Future motion is not trusted stationary. Include observed velocity and a bounded acceleration margin.
                if(e.getBoundingBox().inflate(.6+i*(v.length()+.3)).intersects(sweep))return "gateway_pearl_entity_collision";
            }
        }
        return null;
    }
    private CapabilityGateway(){}
}
