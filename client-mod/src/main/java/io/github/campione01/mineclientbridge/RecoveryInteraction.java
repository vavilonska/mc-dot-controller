package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import io.github.campione01.mineclientbridge.mixin.RecoveryMiningAccessor;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.*;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.*;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.projectile.ProjectileUtil;
import net.minecraft.world.item.*;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.*;

/** Task-specific interactions, not a general attack or inventory automation surface. */
final class RecoveryInteraction {
    static final String ROOT="/control/recovery-interaction/v1/";
    static final String V3_ROOT="/control/recovery-interaction/v3/";
    static final boolean V3_ENABLED=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoveryInteractionV3","false"));
    static final String V2_ROOT="/control/recovery-interaction/v2/";
    static final boolean V2_ENABLED=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoveryInteractionV2","false"));
    static final boolean ENABLED=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoveryInteractionV1","false"));
    static final Set<BlockPos> TARGETS=Set.of(new BlockPos(-636,60,33),new BlockPos(-636,61,34));
    static final class Capture {
        final RecoveryShortInputLedger.Entry entry;final LocalPlayer player;final ClientLevel level;
        final MultiPlayerGameMode gameMode;final ClientPacketListener connection;
        final Object server;final BlockPos target;final Direction face;final BlockState blockState;
        final net.minecraft.client.player.Input survivalInput;final net.minecraft.world.entity.Entity survivalTarget;
        final ItemStack tool;final int selected;final BlockPos anchor;final BlockState anchorState;final BlockHitResult placementHit;
        Capture(RecoveryShortInputLedger.Entry e,Minecraft mc){
            entry=e;player=mc.player;level=mc.level;gameMode=mc.gameMode;server=mc.getSingleplayerServer();
            connection=mc.getConnection();var o=e.request.operation();
            var place=o.placement();
            target=place!=null?new BlockPos(place.x(),place.y(),place.z()):e.request.kind().equals("break_block")?new BlockPos(o.x(),o.y(),o.z()):null;
            anchor=place==null?null:new BlockPos(place.anchorX(),place.anchorY(),place.anchorZ());anchorState=anchor==null?null:level.getBlockState(anchor);
            placementHit=place==null?null:new BlockHitResult(new Vec3(place.hitX(),place.hitY(),place.hitZ()),Direction.valueOf(place.face()),anchor,false);
            face=target==null?null:Direction.valueOf(place==null?o.face():place.face());blockState=target==null?null:level.getBlockState(target);
            selected=e.request.kind().equals("select_hotbar")?o.slot():player.getInventory().selected;
            tool=player.getInventory().getItem(selected).copy();
            survivalInput=RecoverySurvivalV6.profile(e.request.profile())?player.input:null;var hit=RecoverySurvivalV6.profile(e.request.profile())&&e.request.kind().equals("attack_blaze")?RecoverySurvivalV6.eligibleHit(mc):null;survivalTarget=hit==null?null:hit.getEntity();
        }
        boolean sameCurrentContext(){Minecraft mc=Minecraft.getInstance();return mc.player==player&&mc.level==level&&mc.gameMode==gameMode
            &&mc.getConnection()==connection&&mc.getSingleplayerServer()==server;}
        boolean ownsMining(){return gameMode instanceof RecoveryMiningAccessor a&&a.recovery$connection()==connection
            &&(!gameMode.isDestroying()||(a.recovery$target().equals(target)&&ItemStack.matches(a.recovery$item(),tool)));}
    }
    static boolean hooksReady(MultiPlayerGameMode gameMode){return RecoveryInteractionDispatch.ready()&&gameMode instanceof RecoveryMiningAccessor;}
    static String problem(Capture c,boolean first){
        var r=c.entry.request;var o=r.operation();Minecraft mc=Minecraft.getInstance();
        if(!c.sameCurrentContext())return "interaction_context_changed";
        if(RecoverySurvivalV6.profile(r.profile())){String p=RecoverySurvivalV6.problem(c,first);if(p!=null)return p;if(RecoverySurvivalV6.callKind(r.kind()))return null;}
        if(RecoveryMaintenanceV5.profile(r.profile())){String p=RecoveryMaintenanceV5.problem(c,first);if(p!=null)return p;if(r.kind().equals("place_block"))return null;}
        if(r.kind().equals("look"))return Math.abs(Math.IEEEremainder(o.yaw()-c.player.getYRot(),360))<=90&&Math.abs(o.pitch()-c.player.getXRot())<=90?null:"look_delta_exceeds_90";
        if(r.kind().equals("select_hotbar"))return ItemStack.matches(c.tool,c.player.getInventory().getItem(o.slot()))
            &&fingerprint(c.player.getInventory().getItem(o.slot()),mc).equals(o.fingerprint())?null:"selected_stack_changed";
        if(!r.kind().equals("break_block"))return null;
        if(!hooksReady(c.gameMode))return "mining_hooks_unavailable";
        if(c.gameMode.getPlayerMode()!=GameType.SURVIVAL)return "mining_survival_mode_required";
        if(!allowedTarget(r.profile(),c.target,Math.floor(c.player.getY())))return "unsupported_task_break_target";
        if(!c.level.hasChunkAt(c.target))return "target_unloaded";
        if(c.level.getBlockState(c.target)!=c.blockState||!allowedBlock(r,c.blockState)||!c.blockState.getFluidState().isEmpty()||c.blockState.hasBlockEntity())return "target_changed";
        if(c.player.getInventory().selected!=c.selected||!ItemStack.matches(c.tool,c.player.getMainHandItem())
            ||!fingerprint(c.player.getMainHandItem(),mc).equals(o.fingerprint())||!(c.player.getMainHandItem().getItem() instanceof PickaxeItem))return "mining_tool_changed";
        if(first&&c.gameMode.isDestroying())return "existing_mining_owner";
        if(!first&&(!c.gameMode.isDestroying()||!c.ownsMining()))return "mining_progress_owner_changed";
        HitResult hit=ray(mc);if(!(hit instanceof BlockHitResult b)||hit.getType()!=HitResult.Type.BLOCK||!b.getBlockPos().equals(c.target)||b.getDirection()!=c.face)return "target_ray_changed";
        return finalBinding(c,first)?null:"interaction_binding_changed_after_ray";
    }
    /** Final local binding after ray/entity callbacks; no new scan, serialization or event hook. */
    static boolean finalBinding(Capture c,boolean first){
        if(!c.sameCurrentContext())return false;
        if(RecoverySurvivalV6.profile(c.entry.request.profile()))return RecoverySurvivalV6.finalBinding(c);
        if(RecoveryMaintenanceV5.profile(c.entry.request.profile())){
            if((c.entry.request.kind().equals("place_block")||c.entry.request.kind().equals("break_block")&&c.blockState.is(Blocks.TNT))&&!RecoveryMaintenanceV5.primed(Minecraft.getInstance()).clear())return false;
            if(c.entry.request.kind().equals("place_block"))return RecoveryMaintenanceV5.placementBinding(c);
            if(c.entry.request.kind().equals("break_block")&&(RecoveryMaintenanceV5.protectedCell(c.player.getBoundingBox(),c.target)||!RecoveryMaintenanceV5.safeTnt(c)))return false;
        }
        if(c.entry.request.kind().equals("look"))return true;
        if(c.entry.request.kind().equals("select_hotbar"))return ItemStack.matches(c.tool,c.player.getInventory().getItem(c.selected));
        return allowedTarget(c.entry.request.profile(),c.target,Math.floor(c.player.getY()))&&c.level.hasChunkAt(c.target)&&c.level.getBlockState(c.target)==c.blockState
            &&c.player.getInventory().selected==c.selected&&ItemStack.matches(c.tool,c.player.getMainHandItem())
            &&c.gameMode.getPlayerMode()==GameType.SURVIVAL&&(first?!c.gameMode.isDestroying():c.gameMode.isDestroying()&&c.ownsMining());
    }
    static boolean allowedTarget(String profile,BlockPos target,double feetFloor){
        return RecoveryMaintenanceV5.profile(profile)||target.getY()>=feetFloor+1&&(RecoveryShortInputLedger.planProfile(profile)
            ||(RecoveryShortInputLedger.INTERACTION_PROFILE.equals(profile)&&TARGETS.contains(target)&&feetFloor==59));
    }
    private static boolean allowedBlock(RecoveryShortInputLedger.Request r,BlockState state){
        if(RecoveryMaintenanceV5.profile(r.profile()))return RecoveryMaintenanceV5.breakBlock(state,r.operation().blockId());
        // Literal ordinary Block instances only. No tag widening, block entities or falling-block subclass.
        if(state.getBlock().getClass()!=net.minecraft.world.level.block.Block.class)return false;
        String expected=r.operation().blockId();
        return "minecraft:cobblestone".equals(expected)&&state.is(Blocks.COBBLESTONE)
            ||RecoveryShortInputLedger.planProfile(r.profile())&&"minecraft:nether_wart_block".equals(expected)&&state.is(Blocks.NETHER_WART_BLOCK);
    }
    static void rawOneShot(Capture c){
        var o=c.entry.request.operation();
        if(c.entry.request.kind().equals("look")){c.player.setYRot((float)o.yaw());c.player.setXRot((float)o.pitch());}
        else if(c.entry.request.kind().equals("select_hotbar"))c.player.getInventory().selected=o.slot();
        else throw new IllegalStateException("not_one_shot");
    }
    static void mine(Capture c){
        var scope=RecoveryInteractionDispatch.enter(c,false);
        try{if(c.entry.applied==0)c.gameMode.startDestroyBlock(c.target,c.face);else c.gameMode.continueDestroyBlock(c.target,c.face);
            RecoveryInteractionDispatch.exit(scope);
        }catch(RuntimeException|Error failure){RecoveryInteractionDispatch.abandon();throw failure;}
    }
    /** Returns false rather than touching a replacement game mode/target. Detached owner is not guessed safe. */
    static boolean release(Capture c){
        if(!c.entry.request.kind().equals("break_block"))return true;
        if(c.gameMode instanceof RecoveryMiningAccessor a&&!c.gameMode.isDestroying()&&a.recovery$progress()==0)return true;
        if(!c.sameCurrentContext()||!c.ownsMining())return false;
        if(c.gameMode.isDestroying()){
            var scope=RecoveryInteractionDispatch.enter(c,true);
            try{c.gameMode.stopDestroyBlock();RecoveryInteractionDispatch.exit(scope);}
            catch(RuntimeException|Error failure){RecoveryInteractionDispatch.abandon();throw failure;}
        }
        return !c.gameMode.isDestroying()&&((RecoveryMiningAccessor)c.gameMode).recovery$progress()==0;
    }
    static boolean finished(Capture c){return c.level.getBlockState(c.target)!=c.blockState||!c.gameMode.isDestroying();}
    static String gameplay(Capture c){return c.level.getBlockState(c.target)==c.blockState?"target_unchanged":"target_changed";}
    /** Fresh read-only view ray plus nearest pickable entity obstruction; never mutates Minecraft.hitResult. */
    static HitResult ray(Minecraft mc){
        var p=mc.player;double reach=p.blockInteractionRange();Vec3 eye=p.getEyePosition(1),delta=p.getViewVector(1).scale(reach),end=eye.add(delta);
        HitResult block=p.pick(reach,1,false);double limit=block.getType()==HitResult.Type.MISS?reach*reach:eye.distanceToSqr(block.getLocation());
        EntityHitResult entity=ProjectileUtil.getEntityHitResult(p,eye,end,p.getBoundingBox().expandTowards(delta).inflate(1),e->!e.isSpectator()&&e.isPickable(),limit);
        return entity!=null&&eye.distanceToSqr(entity.getLocation())<=limit?entity:block;
    }
    static void observation(JsonObject out,Minecraft mc){observation(out,mc,false);}
    static void observation(JsonObject out,Minecraft mc,boolean v2){
        if(mc.player==null||mc.level==null){out.add("player_bbox",JsonNull.INSTANCE);out.add("selected_slot",JsonNull.INSTANCE);out.add("hotbar",new JsonArray());out.add("ray",JsonNull.INSTANCE);return;}
        var p=mc.player;AABB b=p.getBoundingBox();JsonObject bbox=new JsonObject();
        bbox.addProperty("min_x",b.minX);bbox.addProperty("min_y",b.minY);bbox.addProperty("min_z",b.minZ);bbox.addProperty("max_x",b.maxX);bbox.addProperty("max_y",b.maxY);bbox.addProperty("max_z",b.maxZ);out.add("player_bbox",bbox);
        out.addProperty("selected_slot",p.getInventory().selected);JsonArray hotbar=new JsonArray();
        for(int slot=0;slot<9;slot++){ItemStack stack=p.getInventory().getItem(slot);hotbar.add(describeHotbarStack(slot,BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(),stack.getCount(),stack.getDamageValue(),v2?stack.getMaxDamage():0,fingerprint(stack,mc),v2));}out.add("hotbar",hotbar);
        HitResult hit=ray(mc);JsonObject j=new JsonObject();j.addProperty("kind",hit.getType().name().toLowerCase(Locale.ROOT));
        if(hit.getType()==HitResult.Type.BLOCK&&hit instanceof BlockHitResult h){j.addProperty("x",h.getBlockPos().getX());j.addProperty("y",h.getBlockPos().getY());j.addProperty("z",h.getBlockPos().getZ());j.addProperty("face",h.getDirection().name());
            JsonObject point=new JsonObject();point.addProperty("x",hit.getLocation().x);point.addProperty("y",hit.getLocation().y);point.addProperty("z",hit.getLocation().z);j.add("point",point);j.addProperty("block_id",BuiltInRegistries.BLOCK.getKey(mc.level.getBlockState(h.getBlockPos()).getBlock()).toString());}
        else for(String key:new String[]{"x","y","z","face","point","block_id"})j.add(key,JsonNull.INSTANCE);out.add("ray",j);
    }
    /** Production hotbar DTO; v1 intentionally has no max_damage key. */
    static JsonObject describeHotbarStack(int slot,String itemId,int count,int damage,int maxDamage,String fingerprint,boolean v2){
        JsonObject j=new JsonObject();j.addProperty("slot",slot);j.addProperty("item_id",itemId);j.addProperty("count",count);j.addProperty("damage",damage);
        if(v2)j.addProperty("max_damage",maxDamage);j.addProperty("stack_fingerprint",fingerprint);return j;
    }
    static String fingerprint(ItemStack stack,Minecraft mc){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest((stack.isEmpty()?"empty":stack.save(mc.level.registryAccess()).toString()).getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException("stack_fingerprint_failed",e);}}
    private RecoveryInteraction(){}
}
