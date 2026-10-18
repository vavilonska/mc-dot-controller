package io.github.campione01.mineclientbridge;

import java.util.List;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.status.ChunkStatus;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

/** Read-only bounded ballistic forecast against native collision shapes; never moves the player.
 * The forecast is an estimate and is replaced every tick. Dispatch additionally needs the actual
 * current eye ray and reach. Unsupported side/ceiling hits, unloaded cells, and fluids fail closed. */
final class FallRescueGeometry {
    private static final Set<String> SUPPORTS=Set.of("stone","granite","diorite","andesite","deepslate",
            "cobbled_deepslate","cobblestone","dirt","grass_block","end_stone","obsidian","bedrock",
            "oak_planks","birch_planks","spruce_planks","sandstone","smooth_sandstone");
    record Landing(BlockPos support,BlockPos water,Vec3 aim,int ticks,double descent,AABB feet) { }
    static Landing forecast(Minecraft mc) {
        var p=mc.player;AABB box=p.getBoundingBox();Vec3 velocity=p.getDeltaMovement();
        double peak=box.minY, initialY=box.minY;
        if(!finite(velocity)||velocity.horizontalDistance()>0.8||Math.abs(velocity.y)>4.0)return null;
        for(int tick=1;tick<=FallRescuePolicy.MAX_FORECAST_TICKS;tick++){
            AABB swept=box.expandTowards(velocity).inflate(1.001);
            if(Math.abs(box.minY-initialY)>96||!loaded(mc,swept))return null;
            if(!mc.level.getEntities(p,swept.deflate(.99),e->e.isAlive()&&e.canBeCollidedWith()).isEmpty())return null;
            Vec3 resolved=Entity.collideBoundingBox(p,velocity,box,mc.level,List.of());
            if(!finite(resolved)||Math.abs(resolved.x-velocity.x)>1e-7||Math.abs(resolved.z-velocity.z)>1e-7)return null;
            box=box.move(resolved);peak=Math.max(peak,box.minY);
            if(Math.abs(resolved.y-velocity.y)>1e-7){
                if(velocity.y>=0)return null;
                BlockPos support=BlockPos.containing((box.minX+box.maxX)/2,box.minY-.001,(box.minZ+box.maxZ)/2);
                if(box.minX<support.getX()+.02||box.maxX>support.getX()+.98
                        ||box.minZ<support.getZ()+.02||box.maxZ>support.getZ()+.98)return null;
                if(Math.abs(box.minY-(support.getY()+1))>1e-5||!targetClear(mc,support))return null;
                return new Landing(support,support.above(),new Vec3(support.getX()+.5,support.getY()+1,support.getZ()+.5),
                        tick,Math.max(0,peak-box.minY),box);
            }
            // Vanilla ordinary airborne player drag/gravity; unsupported physics are rejected by context().
            velocity=new Vec3(velocity.x*.91,(velocity.y-p.getGravity())*.98,velocity.z*.91);
        }
        return null; // No supported loaded landing is known. Never guess a void or unloaded surface.
    }
    static boolean targetClear(Minecraft mc,BlockPos support){
        if(!loaded(mc,new AABB(support).expandTowards(0,2,0)))return false;
        var state=mc.level.getBlockState(support);
        var key=BuiltInRegistries.BLOCK.getKey(state.getBlock());
        return key.getNamespace().equals("minecraft")&&SUPPORTS.contains(key.getPath())
                &&state.getFluidState().isEmpty()&&state.isCollisionShapeFullBlock(mc.level,support)
                &&!state.getShape(mc.level,support).isEmpty()&&state.getShape(mc.level,support).bounds().equals(new AABB(0,0,0,1,1,1))
                &&air(mc.level.getBlockState(support.above()))&&air(mc.level.getBlockState(support.above(2)));
    }
    static boolean air(BlockState state){return state.isAir()&&state.getFluidState().isEmpty();}
    static boolean loaded(Minecraft mc,AABB bounds){
        if(bounds.minY<mc.level.getMinBuildHeight()||bounds.maxY>=mc.level.getMaxBuildHeight())return false;
        if(bounds.getXsize()>8||bounds.getZsize()>8||bounds.getYsize()>12)return false;
        for(int x=(int)Math.floor(bounds.minX)>>4;x<=((int)Math.floor(bounds.maxX)>>4);x++)
            for(int z=(int)Math.floor(bounds.minZ)>>4;z<=((int)Math.floor(bounds.maxZ)>>4);z++)
                if(mc.level.getChunkSource().getChunk(x,z,ChunkStatus.FULL,false)==null)return false;
        return true;
    }
    static BlockHitResult currentRay(Minecraft mc,BlockPos support){
        Vec3 eye=mc.player.getEyePosition();double reach=mc.player.blockInteractionRange();
        if(!Double.isFinite(reach)||reach<=0||reach>6)return null;
        Vec3 end=eye.add(mc.player.getViewVector(1).scale(reach));
        if(!loaded(mc,new AABB(eye,end).inflate(.01)))return null;
        BlockHitResult hit=mc.level.clip(new ClipContext(eye,end,ClipContext.Block.OUTLINE,ClipContext.Fluid.NONE,mc.player));
        if(hit.getType()!=HitResult.Type.BLOCK||hit.getDirection()!=Direction.UP||!hit.getBlockPos().equals(support)
                ||hit.isInside()||hit.getLocation().distanceTo(eye)>reach+1e-7)return null;
        return hit;
    }
    static boolean reachable(Minecraft mc,Landing landing){return mc.player.getEyePosition().distanceTo(landing.aim())<=mc.player.blockInteractionRange()-.02;}
    static void aim(net.minecraft.client.player.LocalPlayer player,Vec3 target,java.util.function.BooleanSupplier owner){
        Vec3 delta=target.subtract(player.getEyePosition());
        float yaw=(float)(Math.toDegrees(Math.atan2(delta.z,delta.x))-90);
        float pitch=(float)-Math.toDegrees(Math.atan2(delta.y,Math.hypot(delta.x,delta.z)));
        // Eye/rotation hooks can revoke the original episode. Never fetch a replacement player.
        FallRescuePolicy.require(owner.getAsBoolean(),"fall_rescue_aim_owner_changed");player.setYRot(yaw);
        FallRescuePolicy.require(owner.getAsBoolean(),"fall_rescue_aim_owner_changed");player.setXRot(pitch);
        FallRescuePolicy.require(owner.getAsBoolean(),"fall_rescue_aim_owner_changed");player.setYHeadRot(yaw);
        FallRescuePolicy.require(owner.getAsBoolean(),"fall_rescue_aim_owner_changed");player.setYBodyRot(yaw);
    }
    static boolean finite(Vec3 v){return Double.isFinite(v.x)&&Double.isFinite(v.y)&&Double.isFinite(v.z);}
    private FallRescueGeometry() { }
}
