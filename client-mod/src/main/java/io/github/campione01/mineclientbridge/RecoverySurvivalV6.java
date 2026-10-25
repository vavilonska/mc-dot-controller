package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Options;
import net.minecraft.core.component.DataComponents;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.monster.Blaze;
import net.minecraft.world.entity.projectile.ProjectileUtil;
import net.minecraft.world.food.Foods;
import net.minecraft.world.item.*;
import net.minecraft.world.level.GameType;
import net.minecraft.world.phys.*;

/** Explicit V6 top-level survival calls, not a generic combat/use dispatch framework. */
public final class RecoverySurvivalV6 {
    static final boolean ENABLED=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoverySurvivalV6","false"));
    static final float MIN_ATTACK_STRENGTH=1.0F;
    private static volatile boolean useHookReady;
    private static volatile Use ownedUse;
    static boolean profile(String p){return RecoveryShortInputLedger.survivalProfile(p);}
    public static void installed(){useHookReady=true;}
    static boolean ready(){return useHookReady;}
    /** Not ledger.live: a stopped/expired/naturally finished owner still blocks until exact release. */
    public static boolean suppressDefaultUse(){Use u=ownedUse;return ENABLED&&u!=null&&u.bound.blocksRestart();}
    static boolean callKind(String k){return k.equals("attack_blaze")||k.equals("consume_bread");}
    static boolean bread(ItemStack s){return !s.isEmpty()&&s.getItem()==Items.BREAD&&s.getItem().getClass()==Item.class&&Foods.BREAD.equals(s.get(DataComponents.FOOD));}
    static boolean axe(ItemStack s){return !s.isEmpty()&&s.getItem()==Items.IRON_AXE&&s.getItem().getClass()==AxeItem.class;}
    static boolean selectAllowed(int slot,boolean ordinaryBread,boolean ordinaryAxe,boolean using,boolean mining){return !using&&!mining&&(slot==1&&ordinaryBread||slot==8&&ordinaryAxe);}
    static String problem(RecoveryInteraction.Capture c,boolean first){
        var r=c.entry.request;var o=r.operation();var p=c.player;
        if(!c.sameCurrentContext())return "survival_context_changed";
        if(!ready())return "survival_use_hook_unavailable";
        if(c.gameMode.getPlayerMode()!=GameType.SURVIVAL)return "survival_mode_required";
        if(r.kind().equals("move")||r.kind().equals("look"))return null;
        if(r.kind().equals("select_hotbar"))return selectAllowed(o.slot(),bread(c.tool),axe(c.tool),p.isUsingItem(),c.gameMode.isDestroying())?null:"survival_selected_item_unsupported";
        if(!first&&r.kind().equals("consume_bread"))return ownedUse!=null&&ownedUse.c==c&&ownedUse.binding()?null:"survival_use_owner_changed";
        if(p.isUsingItem()||c.gameMode.isDestroying())return "existing_item_use_or_mining";
        if(p.getInventory().selected!=c.selected||!ItemStack.matches(c.tool,p.getMainHandItem())||!RecoveryInteraction.fingerprint(p.getMainHandItem(),Minecraft.getInstance()).equals(o.fingerprint()))return "survival_stack_changed";
        if(r.kind().equals("consume_bread")){
            if(c.selected!=1||!bread(c.tool)||!Foods.BREAD.equals(p.getMainHandItem().getFoodProperties(p))||p.getMainHandItem().getUseDuration(p)!=32)return "ordinary_bread_required";
            return p.getFoodData().getFoodLevel()<20?null:"food_already_full";
        }
        if(r.kind().equals("attack_blaze")){
            if(c.selected!=8||!axe(c.tool))return "iron_axe_required";
            if(p.getAttackStrengthScale(0)<MIN_ATTACK_STRENGTH)return "attack_cooldown_not_ready";
            EntityHitResult hit=eligibleHit(Minecraft.getInstance());
            if(hit==null||hit.getEntity()!=c.survivalTarget||hit.getEntity().getId()!=o.survival().entityId()||!hit.getEntity().getUUID().toString().equals(o.survival().uuid())||!hit.getEntity().isAlive())return "blaze_target_ray_changed";
            return null;
        }
        return "invalid_survival_kind";
    }
    static boolean finalBinding(RecoveryInteraction.Capture c){
        if(!c.sameCurrentContext()||c.player.input!=c.survivalInput||!c.player.isAlive()||c.gameMode.getPlayerMode()!=GameType.SURVIVAL)return false;
        if(c.entry.request.kind().equals("look"))return true;
        if(c.entry.request.kind().equals("select_hotbar"))return ItemStack.matches(c.tool,c.player.getInventory().getItem(c.selected))&&selectAllowed(c.selected,bread(c.tool),axe(c.tool),c.player.isUsingItem(),c.gameMode.isDestroying());
        return c.player.getInventory().selected==c.selected&&ItemStack.matches(c.tool,c.player.getMainHandItem())&&!c.player.isUsingItem()&&!c.gameMode.isDestroying();
    }
    static boolean withinHit(double squaredDistance,double blockSquared,double entityReach){return Double.isFinite(squaredDistance)&&squaredDistance>=0&&Double.isFinite(blockSquared)&&squaredDistance<blockSquared&&Double.isFinite(entityReach)&&entityReach>=0&&entityReach<=64&&squaredDistance<entityReach*entityReach;}
    /** Current vanilla combined reach, block occlusion and nearest pickable entity, without changing hitResult. */
    static EntityHitResult eligibleHit(Minecraft mc){
        var p=mc.player;double er=p.entityInteractionRange(),br=p.blockInteractionRange(),reach=Math.max(er,br);
        if(!Double.isFinite(er)||er<0||er>64||!Double.isFinite(reach)||reach<0||reach>64)return null;
        Vec3 eye=p.getEyePosition(1);HitResult block=p.pick(reach,1,false);double blockDistance=eye.distanceToSqr(block.getLocation());double limit=block.getType()==HitResult.Type.MISS?reach*reach:blockDistance;
        double segment=block.getType()==HitResult.Type.MISS?reach:Math.sqrt(blockDistance);Vec3 delta=p.getViewVector(1).scale(segment),end=eye.add(delta);
        EntityHitResult hit=ProjectileUtil.getEntityHitResult(p,eye,end,p.getBoundingBox().expandTowards(delta).inflate(1),e->!e.isSpectator()&&e.isPickable(),limit);
        if(hit==null||!withinHit(eye.distanceToSqr(hit.getLocation()),blockDistance,er))return null;
        var target=hit.getEntity();return target.getClass()==Blaze.class&&target.getType()==EntityType.BLAZE?hit:null;
    }
    static void attack(RecoveryInteraction.Capture c){
        EntityHitResult hit=eligibleHit(Minecraft.getInstance());var spec=c.entry.request.operation().survival();
        if(hit==null||hit.getEntity()!=c.survivalTarget||hit.getEntity().getId()!=spec.entityId()||!hit.getEntity().getUUID().toString().equals(spec.uuid())||!hit.getEntity().isAlive()||c.player.getAttackStrengthScale(0)<MIN_ATTACK_STRENGTH||!finalBinding(c))throw new IllegalStateException("survival_attack_final_binding");
        c.gameMode.attack(c.player,hit.getEntity());
        if(!c.sameCurrentContext())throw new IllegalStateException("survival_attack_context_lost");
        c.entry.gameplay="attack_returned_observe_outcome";
    }
    /** Small finite lifecycle state, shared by production and synthetic boundary tests. */
    static final class UseBound {
        final long startTick;final int maxTicks;boolean started,released;
        UseBound(long tick,int maxTicks){if(maxTicks<1||maxTicks>40)throw new IllegalArgumentException("invalid_use_bound");startTick=tick;this.maxTicks=maxTicks;}
        void start(){if(started||released)throw new IllegalStateException("bread_restart_forbidden");started=true;}
        boolean expired(long tick){long elapsed=tick-startTick;return elapsed<0||elapsed>=maxTicks;}
        boolean blocksRestart(){return started&&!released;}
        void release(){released=true;}
    }
    private static final class Use {
        final RecoveryInteraction.Capture c;final net.minecraft.client.player.Input input;final Options options;final KeyMapping key;final ItemStack stack;final UseBound bound;
        boolean releaseEntered;
        Use(RecoveryInteraction.Capture c,long tick){this.c=c;input=c.survivalInput;options=Minecraft.getInstance().options;key=options.keyUse;stack=c.player.getMainHandItem();bound=new UseBound(tick,c.entry.request.operation().survival().maxUseTicks());}
        boolean binding(){
            Minecraft mc=Minecraft.getInstance();if(!c.sameCurrentContext()||c.player.input!=input||mc.options!=options||options.keyUse!=key||c.player.getInventory().selected!=c.selected)return false;
            if(c.player.isUsingItem())return c.player.getUsedItemHand()==InteractionHand.MAIN_HAND&&c.player.getUseItem()==stack&&c.player.getMainHandItem()==stack&&ItemStack.matches(c.tool,stack);
            ItemStack now=c.player.getMainHandItem();return ItemStack.isSameItemSameComponents(c.tool,now)&&now.getCount()<=c.tool.getCount()&&now.getCount()>=c.tool.getCount()-1||now.isEmpty()&&c.tool.getCount()==1;
        }
    }
    static boolean hasUse(RecoveryInteraction.Capture c){Use u=ownedUse;return u!=null&&u.c==c;}
    static void startUse(RecoveryInteraction.Capture c,long tick){
        if(ownedUse!=null||!ready()||!finalBinding(c))throw new IllegalStateException("survival_use_claim_changed");
        Use u=new Use(c,tick);u.bound.start();ownedUse=u; // latch BEFORE the first callback, retained on throw
        InteractionResult result=c.gameMode.useItem(c.player,InteractionHand.MAIN_HAND);
        if(result==null||!u.binding())throw new IllegalStateException("survival_use_return_binding");
        c.entry.gameplay="use_"+result.name().toLowerCase(Locale.ROOT);
        if(c.player.isUsingItem())u.key.setDown(true);
    }
    static boolean useFinished(RecoveryInteraction.Capture c,long tick){Use u=ownedUse;if(u==null||u.c!=c||!u.binding())throw new IllegalStateException("survival_use_owner_changed");return !c.player.isUsingItem()||u.bound.expired(tick);}
    static boolean ownedInput(Minecraft mc){
        Use u=ownedUse;if(u==null||!u.binding()||mc.player!=u.c.player)return false;
        for(KeyMapping key:mc.options.keyMappings)if(key!=u.key&&key.isDown())return false;
        return true;
    }
    /** Never release a replacement player, stack, hand, key map or owner. Once entered, release is not retried. */
    static boolean release(RecoveryInteraction.Capture c){
        Use u=ownedUse;if(u==null)return true;if(u.c!=c||!u.binding()||u.releaseEntered)return false;
        u.releaseEntered=true;u.key.setDown(false);
        if(c.player.isUsingItem())c.gameMode.releaseUsingItem(c.player);
        return u.binding()&&!u.key.isDown()&&!c.player.isUsingItem();
    }
    static void released(RecoveryInteraction.Capture c){Use u=ownedUse;if(u!=null&&u.c==c){u.bound.release();ownedUse=null;}}
    static JsonObject unavailable(){JsonObject j=new JsonObject();j.addProperty("complete",false);for(String key:List.of("food_level","saturation","is_using_item","used_hand","use_remaining_ticks","hurt_time","entity_reach","attack_strength","entity_hit"))j.add(key,JsonNull.INSTANCE);return j;}
    static JsonObject observation(Minecraft mc){
        try{
            var p=mc.player;var level=mc.level;if(p==null||level==null)return unavailable();
            int food=p.getFoodData().getFoodLevel(),hurt=p.hurtTime,remaining=p.getUseItemRemainingTicks();float saturation=p.getFoodData().getSaturationLevel(),strength=p.getAttackStrengthScale(0);double reach=p.entityInteractionRange();boolean using=p.isUsingItem();
            if(food<0||food>20||!Float.isFinite(saturation)||saturation<0||saturation>20||hurt<0||!Float.isFinite(strength)||strength<0||strength>1||!Double.isFinite(reach)||reach<0||reach>64)return unavailable();
            JsonObject j=new JsonObject();j.addProperty("complete",true);j.addProperty("food_level",food);j.addProperty("saturation",saturation);j.addProperty("is_using_item",using);j.addProperty("used_hand",using?p.getUsedItemHand().name():null);j.addProperty("use_remaining_ticks",remaining);j.addProperty("hurt_time",hurt);j.addProperty("entity_reach",reach);j.addProperty("attack_strength",strength);
            EntityHitResult hit=eligibleHit(mc);j.add("entity_hit",hit==null?JsonNull.INSTANCE:describeHit((Blaze)hit.getEntity(),hit.getLocation()));
            return mc.player==p&&mc.level==level?j:unavailable();
        }catch(RuntimeException failure){return unavailable();}
    }
    private static JsonObject describeHit(Blaze target,Vec3 point){
        JsonObject j=new JsonObject();j.addProperty("entity_id",target.getId());j.addProperty("uuid",target.getUUID().toString());j.addProperty("type","minecraft:blaze");j.addProperty("provider_class",target.getClass().getName());j.addProperty("alive",target.isAlive());float hp=target.getHealth();if(!Float.isFinite(hp)||hp<0)throw new IllegalStateException("invalid_target_health");j.addProperty("health",hp);
        AABB b=target.getBoundingBox();if(!(b.minX<b.maxX&&b.minY<b.maxY&&b.minZ<b.maxZ)||!Double.isFinite(point.x)||!Double.isFinite(point.y)||!Double.isFinite(point.z))throw new IllegalStateException("invalid_target_geometry");JsonObject box=new JsonObject();double[] coordinates={b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ};String[] names={"min_x","min_y","min_z","max_x","max_y","max_z"};for(int i=0;i<6;i++){if(!Double.isFinite(coordinates[i]))throw new IllegalStateException("invalid_target_box");box.addProperty(names[i],coordinates[i]);}j.add("bbox",box);JsonObject q=new JsonObject();q.addProperty("x",point.x);q.addProperty("y",point.y);q.addProperty("z",point.z);j.add("point",q);return j;
    }
    private RecoverySurvivalV6(){}
}
