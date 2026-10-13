package io.github.campione01.mineclientbridge;

import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.phys.Vec3;
import java.util.Set;

/** Fresh loaded collision for opt-in adjacent ground routes; never extrapolates unknown terrain. */
final class CapabilityPath {
    private static final Set<String> FLOORS=Set.of("stone","dirt","grass_block","cobblestone","deepslate","cobbled_deepslate","andesite","diorite","granite","sandstone","smooth_stone","bricks","stone_bricks","oak_planks","spruce_planks","birch_planks","jungle_planks","acacia_planks","dark_oak_planks","mangrove_planks","cherry_planks","obsidian","end_stone","netherrack","blackstone","basalt","polished_blackstone","end_stone_bricks","glass","glowstone","sea_lantern","quartz_block","purpur_block","purpur_pillar");
    static String check(Minecraft mc,ClientActionRequest request,int index) {
        if(!request.original().has("capability_route"))return null;
        if(!ClientActionRequest.bool(request.original(),"capability_route",false))return "capability_route_required";
        var points=request.waypoints();
        if(index>=points.size())return null;
        var goal=points.get(index);
        var previous=index==0?request.original().getAsJsonObject("expected_origin"):null;
        Vec3 a=index==0?new Vec3(previous.get("x").getAsDouble(),previous.get("y").getAsDouble(),previous.get("z").getAsDouble()):new Vec3(points.get(index-1).x(),points.get(index-1).y(),points.get(index-1).z());
        BlockPos start=BlockPos.containing(a),target=BlockPos.containing(goal.x(),goal.y(),goal.z());
        int dx=target.getX()-start.getX(),dy=target.getY()-start.getY(),dz=target.getZ()-start.getZ();
        if(Math.abs(dx)>1||Math.abs(dz)>1||Math.abs(dy)>1||dx!=0&&dz!=0&&dy!=0)return "capability_route_nonadjacent";
        if(!standable(mc,start)||!standable(mc,target))return "capability_route_support_changed";
        if(dy>0 && (!air(mc,start.above(2))||!air(mc,target.above(2))))return "capability_step_up_headroom";
        if(dy<0 && !air(mc,target.above(2)))return "capability_step_down_headroom";
        if(dx!=0&&dz!=0&&(partial(mc,start.below())||partial(mc,target.below())||partial(mc,start.offset(dx,-1,0))||partial(mc,start.offset(0,-1,dz))))return "capability_partial_tread_diagonal";
        if(dx!=0&&dz!=0&&(!standable(mc,start.offset(dx,0,0))||!standable(mc,start.offset(0,0,dz))))return "capability_route_corner_blocked";
        var player=mc.player.position();
        double cx=Math.max(Math.min(a.x,goal.x()),Math.min(Math.max(a.x,goal.x()),player.x));
        double cz=Math.max(Math.min(a.z,goal.z()),Math.min(Math.max(a.z,goal.z()),player.z));
        if(Math.hypot(player.x-cx,player.z-cz)>.65 || player.y<Math.min(a.y,goal.y())-.25 || player.y>Math.max(a.y,goal.y())+1.5)return "capability_route_deviation";
        return null;
    }
    static boolean standable(Minecraft mc,BlockPos p){return support(mc,p.below())&&air(mc,p)&&air(mc,p.above());}
    private static boolean air(Minecraft mc,BlockPos p){return mc.level.hasChunkAt(p)&&mc.level.getBlockState(p).isAir()&&mc.level.getFluidState(p).isEmpty();}
    static boolean support(Minecraft mc,BlockPos p) {
        if(!mc.level.hasChunkAt(p)||!mc.level.getFluidState(p).isEmpty())return false;
        var state=mc.level.getBlockState(p);var key=BuiltInRegistries.BLOCK.getKey(state.getBlock());
        if(!key.getNamespace().equals("minecraft"))return false;
        if(state.getBlock() instanceof net.minecraft.world.level.block.StairBlock)return state.getCollisionShape(mc.level,p).bounds().maxY==1;
        if(state.getBlock() instanceof net.minecraft.world.level.block.SlabBlock)
            return state.getValue(net.minecraft.world.level.block.SlabBlock.TYPE)!=net.minecraft.world.level.block.state.properties.SlabType.BOTTOM;
        String id=key.getPath();
        boolean material=FLOORS.contains(id)||id.endsWith("_planks")||id.endsWith("_log")||id.endsWith("_wood")
            ||id.endsWith("_stem")||id.endsWith("_hyphae")||Set.of("bamboo_block","stripped_bamboo_block","crafting_table","furnace","blast_furnace","smoker").contains(id);
        return material&&state.isCollisionShapeFullBlock(mc.level,p);
    }
    private static boolean partial(Minecraft mc,BlockPos p) {
        var state=mc.level.getBlockState(p);
        return state.getBlock() instanceof net.minecraft.world.level.block.StairBlock
            && state.getValue(net.minecraft.world.level.block.StairBlock.HALF)==net.minecraft.world.level.block.state.properties.Half.BOTTOM;
    }
    private CapabilityPath(){}
}
