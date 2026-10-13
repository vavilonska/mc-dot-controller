package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.Vec3;

/** Optional exact oriented placement contract. It never writes block state. */
final class CapabilityPlacement {
    static void validate(ClientActionRequest r) {
        JsonObject b=r.original();
        if(b.has("capability_bridge")) {
            ClientActionRequest.require(ClientActionRequest.bool(b,"capability_bridge",false) && r.sneak() && !r.jump() && Set.of("north","south","east","west").contains(r.face()),"invalid_capability_bridge");
        }
        if(b.has("placement_yaw")) number(b,"placement_yaw",-180,180);
        if(b.has("placement_hit")) {
            ClientActionRequest.require(b.get("placement_hit").isJsonObject(),"invalid_placement_hit");
            var h=b.getAsJsonObject("placement_hit");
            ClientActionRequest.require(h.keySet().equals(Set.of("x","y","z")),"invalid_placement_hit");
            double x=number(h,"x",-30000000,30000000), y=number(h,"y",-2048,2048), z=number(h,"z",-30000000,30000000);
            var s=r.support();var d=Direction.valueOf(r.face().toUpperCase(java.util.Locale.ROOT));
            double[] v={x-s.x(),y-s.y(),z-s.z()};
            int axis=d.getAxis()==Direction.Axis.X?0:d.getAxis()==Direction.Axis.Y?1:2;
            for(int i=0;i<3;i++)ClientActionRequest.require(i==axis?Math.abs(v[i]-(d.getAxisDirection()==Direction.AxisDirection.POSITIVE?1:0))<1e-6:v[i]>=.001 && v[i]<=.999,"placement_hit_not_on_face");
            exactObject(b,"expected_block_properties");
        }
        if(b.has("placement_footprint")) {
            ClientActionRequest.require(b.get("placement_footprint").isJsonArray() && b.getAsJsonArray("placement_footprint").size()>=1 && b.getAsJsonArray("placement_footprint").size()<=2,"invalid_placement_footprint");
            BlockPos support=new BlockPos(r.support().x(),r.support().y(),r.support().z());
            BlockPos target=support.relative(Direction.valueOf(r.face().toUpperCase(java.util.Locale.ROOT)));
            var seen=new java.util.HashSet<BlockPos>();
            for(var row:b.getAsJsonArray("placement_footprint")) {
                ClientActionRequest.require(row.isJsonObject(),"invalid_placement_footprint_cell");var cell=row.getAsJsonObject();
                ClientActionRequest.require(cell.keySet().equals(Set.of("position","expected_id","expected_properties","block_id","properties")),"invalid_placement_footprint_fields");
                BlockPos p=position(cell.getAsJsonObject("position"));
                ClientActionRequest.require((p.equals(target) || p.equals(target.above())) && seen.add(p),"invalid_placement_footprint_position");
                ClientActionRequest.string(cell,"expected_id");ClientActionRequest.string(cell,"block_id");exactObject(cell,"expected_properties");exactObject(cell,"properties");
            }
            ClientActionRequest.require(seen.contains(target),"placement_footprint_primary_required");
        }
    }
    static Vec3 hit(ClientActionRequest r) {
        if(r.original().has("placement_hit")){var h=r.original().getAsJsonObject("placement_hit");return new Vec3(h.get("x").getAsDouble(),h.get("y").getAsDouble(),h.get("z").getAsDouble());}
        var s=r.support();var d=Direction.valueOf(r.face().toUpperCase(java.util.Locale.ROOT));
        return new Vec3(s.x()+.5+d.getStepX()*.5,s.y()+.5+d.getStepY()*.5,s.z()+.5+d.getStepZ()*.5);
    }
    static String before(Minecraft mc,ClientActionRequest r) {
        var b=r.original();
        if(ClientActionRequest.bool(b,"capability_bridge",false)) {
            var source=new BlockPos(r.support().x(),r.support().y(),r.support().z());
            if(!mc.player.onGround() || Math.abs(mc.player.getY()-source.getY()-1)>.2 || Math.hypot(mc.player.getX()-source.getX()-.5,mc.player.getZ()-source.getZ()-.5)>.85
                    || !mc.level.getBlockState(source).isCollisionShapeFullBlock(mc.level,source))return "bridge_source_support_or_pose_changed";
        }
        if(!b.has("placement_footprint"))return null;
        for(var entry:b.getAsJsonArray("placement_footprint")) {
            var c=entry.getAsJsonObject();var p=position(c.getAsJsonObject("position"));
            if(!mc.level.hasChunkAt(p)||!exact(mc.level.getBlockState(p),ClientActionRequest.string(c,"expected_id"),c.getAsJsonObject("expected_properties")))return "placement_footprint_changed";
        }
        return null;
    }
    static boolean after(Minecraft mc,ClientActionRequest r) {
        var b=r.original();
        if(b.has("placement_hit")) {
            var target=new BlockPos(r.support().x(),r.support().y(),r.support().z()).relative(Direction.valueOf(r.face().toUpperCase(java.util.Locale.ROOT)));
            if(!exact(mc.level.getBlockState(target),ClientActionRequest.string(b,"expected_block_id"),b.getAsJsonObject("expected_block_properties")))return false;
        }
        if(!b.has("placement_footprint"))return true;
        for(var entry:b.getAsJsonArray("placement_footprint")) {
            var c=entry.getAsJsonObject();var p=position(c.getAsJsonObject("position"));
            if(!mc.level.hasChunkAt(p)||!exact(mc.level.getBlockState(p),ClientActionRequest.string(c,"block_id"),c.getAsJsonObject("properties")))return false;
        }
        return true;
    }
    static String predicted(Minecraft mc,ClientActionRequest r,BlockPlaceContext context,BlockItem item) {
        var b=r.original();if(!b.has("placement_hit") && !b.has("placement_footprint"))return null;
        if(b.has("placement_yaw") && Math.abs(Math.IEEEremainder(mc.player.getYRot()-b.get("placement_yaw").getAsDouble(),360))>.5)return "placement_yaw_not_observed";
        BlockPlaceContext adjusted=item.updatePlacementContext(context);
        if(adjusted==null || !adjusted.getClickedPos().equals(context.getClickedPos()))return "placement_context_changed_target";
        if(mc.player.getMainHandItem().has(net.minecraft.core.component.DataComponents.BLOCK_STATE))return "placement_component_override_unsupported";
        BlockState state=item.getPlacementState(adjusted);
        if(state==null || !exact(state,ClientActionRequest.string(b,"expected_block_id"),b.getAsJsonObject("expected_block_properties")))return "placement_state_not_obtainable_from_hit";
        return null;
    }
    static boolean exact(BlockState state,String id,JsonObject properties) {
        return properties!=null && state.getProperties().size()==properties.size() && CapabilityGuard.blockMatches(state,id,properties);
    }
    static BlockPos position(JsonObject p) {
        ClientActionRequest.require(p!=null && p.keySet().equals(Set.of("x","y","z")),"invalid_placement_position");
        return new BlockPos(ClientActionRequest.integer(p,"x",0),ClientActionRequest.integer(p,"y",0),ClientActionRequest.integer(p,"z",0));
    }
    static double number(JsonObject b,String k,double min,double max) {
        var v=b.get(k);ClientActionRequest.require(v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isNumber(),"invalid_"+k);
        double n=v.getAsDouble();ClientActionRequest.require(Double.isFinite(n)&&n>=min&&n<=max,"invalid_"+k);return n;
    }
    private static void exactObject(JsonObject b,String key) {
        ClientActionRequest.require(b.has(key)&&b.get(key).isJsonObject(),"invalid_"+key);
        for(var e:b.getAsJsonObject(key).entrySet())ClientActionRequest.require(e.getValue().isJsonPrimitive()&&e.getValue().getAsJsonPrimitive().isString(),"invalid_"+key);
    }
    private CapabilityPlacement(){}
}
