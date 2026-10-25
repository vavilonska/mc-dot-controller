package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.core.*;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.item.*;
import net.minecraft.world.entity.item.PrimedTnt;
import net.minecraft.world.level.entity.EntityTypeTest;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.*;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.*;

/** Explicit finite maintenance catalogue. Task coordinates remain bound public PLAN data. */
final class RecoveryMaintenanceV5 {
    static final boolean ENABLED=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoveryMaintenanceV5","false"));
    static boolean profile(String p){return RecoveryShortInputLedger.maintenanceProfile(p);}
    static boolean anchor(BlockState s,String id){
        if(s.getBlock().getClass()!=Block.class||s.hasBlockEntity()||!s.getFluidState().isEmpty())return false;
        return switch(id){case "minecraft:stone"->s.is(Blocks.STONE);case "minecraft:sandstone"->s.is(Blocks.SANDSTONE);
            case "minecraft:cut_sandstone"->s.is(Blocks.CUT_SANDSTONE);case "minecraft:chiseled_sandstone"->s.is(Blocks.CHISELED_SANDSTONE);case "minecraft:andesite"->s.is(Blocks.ANDESITE);default->false;};
    }
    static boolean breakBlock(BlockState s,String id){
        if(s.hasBlockEntity()||!s.getFluidState().isEmpty())return false;
        if("minecraft:tnt".equals(id))return s.is(Blocks.TNT)&&s.getBlock().getClass()==TntBlock.class&&!s.getValue(TntBlock.UNSTABLE);
        return ("minecraft:cut_sandstone".equals(id)||"minecraft:chiseled_sandstone".equals(id))&&anchor(s,id);
    }
    /** Never remove a body cell or any cell below its current horizontal support footprint. */
    static boolean finiteBody(AABB b){return Double.isFinite(b.minX)&&Double.isFinite(b.minY)&&Double.isFinite(b.minZ)&&Double.isFinite(b.maxX)&&Double.isFinite(b.maxY)&&Double.isFinite(b.maxZ)&&b.minX<b.maxX&&b.minY<b.maxY&&b.minZ<b.maxZ;}
    static boolean protectedCell(AABB body,BlockPos p){return !finiteBody(body)||body.maxX>p.getX()&&body.minX<p.getX()+1D&&body.maxZ>p.getZ()&&body.minZ<p.getZ()+1D&&p.getY()<body.maxY;}
    record TntFacts(boolean unstable,boolean signal,boolean fire){}
    static TntFacts tntFacts(net.minecraft.client.multiplayer.ClientLevel level,BlockPos pos,BlockState state){
        if(!state.is(Blocks.TNT)||state.getBlock().getClass()!=TntBlock.class)return null;
        boolean fire=false;
        for(Direction d:Direction.values()){
            BlockPos n=pos.relative(d);if(!level.hasChunkAt(n))return null;
            BlockState s=level.getBlockState(n);
            fire|=s.is(Blocks.FIRE)||s.is(Blocks.SOUL_FIRE)||s.getFluidState().is(FluidTags.LAVA);
        }
        return new TntFacts(state.getValue(TntBlock.UNSTABLE),level.hasNeighborSignal(pos),fire);
    }
    static boolean safeTnt(RecoveryInteraction.Capture c){
        if(!c.blockState.is(Blocks.TNT))return true;
        TntFacts f=tntFacts(c.level,c.target,c.blockState);return f!=null&&!f.unstable()&&!f.signal()&&!f.fire()&&c.level.getBlockState(c.target)==c.blockState;
    }
    static String problem(RecoveryInteraction.Capture c,boolean first){
        var r=c.entry.request;String kind=r.kind();
        if(kind.equals("select_hotbar")){
            int slot=r.operation().slot();ItemStack s=c.player.getInventory().getItem(slot);
            return (slot==2&&s.getItem()==Items.STONE_PICKAXE&&s.getItem().getClass()==PickaxeItem.class||slot==3&&s.getItem()==Items.ANDESITE&&s.getItem().getClass()==BlockItem.class)?null:"maintenance_selection_catalogue";
        }
        if(!kind.equals("break_block")&&!kind.equals("place_block"))return null;
        if(c.gameMode.getPlayerMode()!=GameType.SURVIVAL)return "maintenance_survival_required";
        if((kind.equals("place_block")||c.blockState.is(Blocks.TNT))&&!primed(Minecraft.getInstance()).clear())return "maintenance_local_primed_tnt_or_incomplete";
        if(kind.equals("break_block")){
            if(protectedCell(c.player.getBoundingBox(),c.target))return "maintenance_body_or_support_column";
            if(c.selected!=2||c.tool.getItem()!=Items.STONE_PICKAXE||c.tool.getItem().getClass()!=PickaxeItem.class)return "maintenance_stone_pickaxe_required";
            if(!safeTnt(c))return "maintenance_tnt_current_trigger";
            return null;
        }
        if(!RecoveryMaintenancePlacementDispatch.ready())return "maintenance_placement_hooks_unavailable";
        if(c.selected!=3||c.tool.isEmpty()||c.tool.getItem()!=Items.ANDESITE||c.tool.getItem().getClass()!=BlockItem.class)return "maintenance_andesite_required";
        if(c.gameMode.isDestroying())return "existing_mining_owner";
        if(!placementBinding(c))return "maintenance_placement_binding_changed";
        if(!RecoveryInteraction.fingerprint(c.player.getMainHandItem(),Minecraft.getInstance()).equals(r.operation().fingerprint()))return "placement_stack_changed";
        HitResult hit=RecoveryInteraction.ray(Minecraft.getInstance());
        if(!(hit instanceof BlockHitResult h)||hit.getType()!=HitResult.Type.BLOCK||!sameHit(h,c.placementHit))return "placement_ray_changed";
        return placementBinding(c)?null:"maintenance_placement_binding_changed_after_ray";
    }
    static boolean placementBinding(RecoveryInteraction.Capture c){
        var p=c.entry.request.operation().placement();
        return c.sameCurrentContext()&&c.gameMode.getPlayerMode()==GameType.SURVIVAL&&!c.gameMode.isDestroying()
            &&c.player.getInventory().selected==c.selected&&ItemStack.matches(c.tool,c.player.getMainHandItem())
            &&c.level.hasChunkAt(c.target)&&c.level.hasChunkAt(c.anchor)&&c.level.getBlockState(c.target)==c.blockState
            &&c.blockState.is(Blocks.AIR)&&c.blockState.getBlock().getClass()==AirBlock.class
            &&c.level.getBlockState(c.anchor)==c.anchorState&&anchor(c.anchorState,p.anchorBlock())
            &&finiteBody(c.player.getBoundingBox())&&!c.player.getBoundingBox().intersects(new AABB(c.target))
            &&c.level.getWorldBorder().isWithinBounds(c.target)&&c.level.getWorldBorder().isWithinBounds(c.anchor)
            &&c.sameCurrentContext()&&c.player.getInventory().selected==c.selected&&ItemStack.matches(c.tool,c.player.getMainHandItem());
    }
    static boolean sameHit(BlockHitResult a,BlockHitResult b){return a.getType()==HitResult.Type.BLOCK&&b.getType()==HitResult.Type.BLOCK
        &&a.getBlockPos().equals(b.getBlockPos())&&a.getDirection()==b.getDirection()&&!a.isInside()&&!b.isInside()
        &&Math.abs(a.getLocation().x-b.getLocation().x)<=1E-4&&Math.abs(a.getLocation().y-b.getLocation().y)<=1E-4&&Math.abs(a.getLocation().z-b.getLocation().z)<=1E-4;}
    record PrimedFacts(int count,boolean complete,boolean overflow){
        JsonObject json(){JsonObject j=new JsonObject();j.addProperty("count",count);j.addProperty("complete",complete);j.addProperty("overflow",overflow);return j;}
        boolean clear(){return complete&&count==0;}
    }
    static PrimedFacts classifyPrimed(List<Class<?>> classes){
        int count=0;boolean complete=classes.size()<=32,overflow=classes.size()>32;
        for(int i=0;i<Math.min(classes.size(),33);i++){if(classes.get(i)!=PrimedTnt.class)complete=false;else if(count<32)count++;}
        return new PrimedFacts(count,complete,overflow);
    }
    static PrimedFacts primed(Minecraft mc){
        if(mc.player==null||mc.level==null)return new PrimedFacts(0,false,false);
        try{
            double x=mc.player.getX(),y=mc.player.getY(),z=mc.player.getZ();
            List<PrimedTnt> rows=new ArrayList<>();
            mc.level.getEntities(EntityTypeTest.forClass(PrimedTnt.class),new AABB(x-8,y-8,z-8,x+8,y+8,z+8),e->true,rows,33);
            List<Class<?>> classes=new ArrayList<>();for(PrimedTnt e:rows)classes.add(e.getClass());
            return classifyPrimed(classes);
        }catch(RuntimeException failure){return new PrimedFacts(0,false,false);}
    }
    static JsonElement eyeJson(Vec3 eye){
        if(eye==null||!Double.isFinite(eye.x)||!Double.isFinite(eye.y)||!Double.isFinite(eye.z)||Math.abs(eye.x)>30_000_000||Math.abs(eye.y)>30_000_000||Math.abs(eye.z)>30_000_000)return JsonNull.INSTANCE;
        JsonObject j=new JsonObject();j.addProperty("x",eye.x);j.addProperty("y",eye.y);j.addProperty("z",eye.z);return j;
    }
    static void eyePosition(JsonObject out,Minecraft mc){
        JsonElement eye=JsonNull.INSTANCE;try{eye=eyeJson(mc.player.getEyePosition(1));}catch(RuntimeException failure){/* missing pure-read facts, no ticket */}
        out.add("eye_position",eye);if(eye.isJsonNull()){out.addProperty("ready",false);out.addProperty("reason","maintenance_eye_unavailable");}
    }
    static void rayWitness(JsonObject out,Minecraft mc){
        JsonElement raw=out.get("ray");
        if(raw==null||raw.isJsonNull()||!raw.getAsJsonObject().get("kind").getAsString().equals("block")){out.add("ray_target_witness",JsonNull.INSTANCE);return;}
        JsonObject ray=raw.getAsJsonObject(),j=new JsonObject();BlockPos pos=new BlockPos(ray.get("x").getAsInt(),ray.get("y").getAsInt(),ray.get("z").getAsInt());
        j.addProperty("x",pos.getX());j.addProperty("y",pos.getY());j.addProperty("z",pos.getZ());boolean loaded=mc.level.hasChunkAt(pos),complete=loaded;
        j.addProperty("loaded",loaded);for(String k:new String[]{"id","fluid","unstable","neighbor_signal","adjacent_fire_or_lava"})j.add(k,JsonNull.INSTANCE);
        if(loaded){
            try{BlockState s=mc.level.getBlockState(pos);String id=BuiltInRegistries.BLOCK.getKey(s.getBlock()).toString();j.addProperty("id",id);j.addProperty("fluid",BuiltInRegistries.FLUID.getKey(s.getFluidState().getType()).toString());
                complete=id.equals(ray.get("block_id").getAsString());
                if(s.is(Blocks.TNT)){TntFacts f=tntFacts(mc.level,pos,s);if(f==null)complete=false;else{j.addProperty("unstable",f.unstable());j.addProperty("neighbor_signal",f.signal());j.addProperty("adjacent_fire_or_lava",f.fire());}}
                complete&=mc.level.getBlockState(pos)==s;
            }catch(RuntimeException failure){complete=false;}
        }
        j.addProperty("complete",complete);out.add("ray_target_witness",j);
        if(!complete){out.addProperty("ready",false);out.addProperty("reason","maintenance_ray_facts_incomplete");}
    }
    static void latestTarget(JsonObject out,Minecraft mc,RecoveryShortInputLedger ledger){
        var e=ledger.latestMaintenanceTarget();out.add("latest_target_witness",JsonNull.INSTANCE);
        if(e==null)return;var r=e.request;
        if(!r.session().equals(ledger.session)||!r.ownerId().equals(ledger.owner())||!r.world().equals(out.get("world_generation").getAsString())||!r.player().equals(out.get("player_uuid").getAsString()))return;
        var o=r.operation();var place=o.placement();BlockPos pos=place==null?new BlockPos(o.x(),o.y(),o.z()):new BlockPos(place.x(),place.y(),place.z());
        JsonObject j=new JsonObject();j.addProperty("action_id",r.id());j.addProperty("x",pos.getX());j.addProperty("y",pos.getY());j.addProperty("z",pos.getZ());
        boolean loaded=mc.level.hasChunkAt(pos),complete=loaded;j.addProperty("loaded",loaded);j.add("id",JsonNull.INSTANCE);j.add("fluid",JsonNull.INSTANCE);
        if(loaded){try{BlockState state=mc.level.getBlockState(pos);j.addProperty("id",BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());j.addProperty("fluid",BuiltInRegistries.FLUID.getKey(state.getFluidState().getType()).toString());complete=mc.level.getBlockState(pos)==state;}catch(RuntimeException failure){complete=false;}}
        j.addProperty("complete",complete);out.add("latest_target_witness",j);
    }
    private RecoveryMaintenanceV5(){}
}
