package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.item.AxeItem;
import net.minecraft.world.item.SwordItem;

/** Same-callback entity admission; no owner, queue, target acquisition or resume. */
final class ScopedCombat {
    static final String PROFILE="combat-local-observed-v1";
    static final Set<String> TYPES=Set.of("minecraft:zombie","minecraft:husk","minecraft:zombie_villager",
        "minecraft:skeleton","minecraft:stray","minecraft:bogged");
    final LocalPlayer player;
    final ClientLevel level;
    final Object gameMode,server;
    final String actionSession,world;
    final LivingEntity target;
    final BoundedCombatRequest request;
    final JsonObject captured;
    final long deadline,startNano;
    final double x,y,z;
    final int selectedSlot;
    final net.minecraft.world.item.ItemStack held,offhand;
    ActionRegistry.Entry entry;
    private int effects;
    void unknown(){if(entry!=null)entry.result.addProperty("unknown_outcome",true);}
    void cleanupFence(Minecraft mc,boolean terminal){
        require((terminal?!ClientActions.ownsInput():ClientActions.ownsScopedCombat(this,entry)) && mc.player==player && mc.level==level && mc.gameMode==gameMode
            && mc.getSingleplayerServer()==server,"scoped_combat_cleanup_owner_or_context_changed");
        require(!player.isUsingItem() || player.getUsedItemHand()==net.minecraft.world.InteractionHand.OFF_HAND
            && player.getUseItem().is(net.minecraft.world.item.Items.SHIELD),"scoped_combat_cleanup_use_changed");
    }
    void chargeEffect(){require(effects<64,"scoped_combat_effect_budget_64");effects++;}
    ScopedCombat(Minecraft mc,ClientActionRequest command,long nano) {
        validateIntent(command.original());
        request=BoundedCombatRequest.parse(command.original());
        require(command.action().equals("combat_entity") && TYPES.contains(request.targetType()) && request.encounter()==null,
            "scoped_combat_explicit_supported_target_required");
        require(request.minHealth()>=14 && request.minHealth()<=20,"scoped_combat_reserve_14_to_20");
        player=mc.player;level=mc.level;gameMode=mc.gameMode;server=mc.getSingleplayerServer();
        actionSession=ClientActions.session();world=WorldGeneration.current(level);
        var entity=level.getEntity(request.targetId());
        require(entity instanceof LivingEntity,"scoped_combat_target_missing");
        target=(LivingEntity)entity;
        startNano=nano;deadline=nano+command.timeoutMs()*1_000_000L;
        x=player.getX();y=player.getY();z=player.getZ();
        selectedSlot=player.getInventory().selected;held=player.getMainHandItem().copy();offhand=player.getOffhandItem().copy();
        JsonObject old=command.original().getAsJsonObject("capability_guard");
        require(old.get("source_tick").getAsLong()<=level.getGameTime() && old.get("source_nano").getAsLong()<=nano,
            "scoped_combat_future_planning_guard");
        identity(mc,true);
        require(player.getHealth()>request.minHealth() && !player.isUsingItem() && player.containerMenu==player.inventoryMenu
            && player.containerMenu.getCarried().isEmpty(),"scoped_combat_admission_player_unavailable");
        captured=factsNow();
    }
    static void validateIntent(JsonObject body){
        Set<String> required=Set.of("action","action_id","target_entity_id","target_uuid","target_type","approach","shield",
            "min_health","timeout_ms","capability_guard","expected_world_generation","expected_dimension","expected_player_uuid",
            "expected_action_session","expected_hotbar_slot","expected_held_item");
        java.util.HashSet<String> withNavigation=new java.util.HashSet<>(required);
        withNavigation.add("expected_navigation_epoch");withNavigation.add("expected_origin");
        require(body.keySet().equals(required)||body.keySet().equals(withNavigation),"scoped_combat_closed_intent_required");
        for(String key:Set.of("target_entity_id","timeout_ms","expected_hotbar_slot"))strictInteger(body,key);
        if(body.has("expected_navigation_epoch"))strictInteger(body,"expected_navigation_epoch");
        JsonObject old=body.getAsJsonObject("capability_guard");
        strictInteger(old,"schema_version");strictInteger(old,"source_tick");
        require(old.get("source_nano")!=null && old.get("source_nano").isJsonPrimitive()
            && old.get("source_nano").getAsJsonPrimitive().isString()
            && old.get("source_nano").getAsString().matches("-?(0|[1-9][0-9]{0,18})"),"scoped_combat_invalid_source_nano");
        require(old.keySet().equals(Set.of("schema_version","source_tick","source_nano"))
            && ClientActionRequest.integer(old,"schema_version",0)==1,"scoped_combat_planning_guard_invalid");
    }
    private static void strictInteger(JsonObject body,String key){
        var value=body.get(key);require(value!=null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber()
            && value.getAsString().matches("0|[1-9][0-9]*"),"scoped_combat_integer_required_"+key);
    }
    JsonObject facts(){return captured.deepCopy();}
    private JsonObject factsNow(){
        JsonObject f=new JsonObject();f.addProperty("profile",PROFILE);
        f.addProperty("target_entity_id",request.targetId());f.addProperty("target_uuid",request.targetUuid());
        f.addProperty("target_type",request.targetType());f.addProperty("target_health",target.getHealth());
        f.addProperty("x",target.getX());f.addProperty("y",target.getY());f.addProperty("z",target.getZ());
        f.addProperty("alive",target.isAlive());f.addProperty("approach",request.approach());f.addProperty("shield",request.shield());
        f.addProperty("min_health",request.minHealth());f.addProperty("timeout_ms",(deadline - startNano)/1_000_000L);
        return f;
    }
    void admission(Minecraft mc){identity(mc,true);require(captured.equals(factsNow()),"scoped_combat_target_changed_during_capture");}
    void activate(ActionRegistry.Entry entry){this.entry=entry;}
    void callbackFence(Minecraft mc,long started,long tick){
        long elapsed=System.nanoTime()-started;
        require(elapsed>=0 && elapsed<=50_000_000L && level.getGameTime()==tick,"scoped_combat_callback_budget");
        require(mc.player==player && mc.level==level && mc.gameMode==gameMode && mc.getSingleplayerServer()==server
            && actionSession.equals(ClientActions.session()) && world.equals(WorldGeneration.current(level))
            && ClientActions.ownsScopedCombat(this,entry),"scoped_combat_callback_context_changed");
    }
    void check(Minecraft mc,boolean alive){
        require(ClientActions.ownsScopedCombat(this,entry),"scoped_combat_owner_changed");
        identity(mc,alive);
        require(ClientActions.ownsScopedCombat(this,entry),"scoped_combat_owner_changed_after_hooks");
    }
    private void identity(Minecraft mc,boolean alive){
        require(mc.isSameThread() && mc.player==player && mc.level==level && mc.gameMode==gameMode && mc.getSingleplayerServer()==server
            && actionSession.equals(ClientActions.session()) && world.equals(WorldGeneration.current(level))
            && CapabilityGuard.privateSingleplayer(mc) && mc.screen==null && !mc.isPaused() && mc.isWindowActive()
            && player.isAlive() && !player.isSpectator() && System.nanoTime()<deadline,
            "scoped_combat_context_or_deadline_changed");
        require(level.getEntity(request.targetId())==target && target.getUUID().toString().equals(request.targetUuid())
            && BuiltInRegistries.ENTITY_TYPE.getKey(target.getType()).toString().equals(request.targetType())
            && (!alive || target.isAlive() && Float.isFinite(target.getHealth()) && target.getHealth()>0),
            "scoped_combat_target_identity_or_liveness_changed");
        require(!player.isAlliedTo(target),"scoped_combat_allied_target_forbidden");
        require(Double.isFinite(target.getX()) && Math.abs(target.getX())<=30000000
            && Double.isFinite(target.getY()) && Math.abs(target.getY())<=2048
            && Double.isFinite(target.getZ()) && Math.abs(target.getZ())<=30000000,
            "scoped_combat_invalid_target_position");
        require(player.getInventory().selected==selectedSlot && unchanged(player.getMainHandItem(),held)
            && unchanged(player.getOffhandItem(),offhand),"scoped_combat_held_binding_changed");
        require(Double.isFinite(player.getX()) && Double.isFinite(player.getY()) && Double.isFinite(player.getZ())
            && player.position().distanceTo(new net.minecraft.world.phys.Vec3(x,y,z))<=12,
            "scoped_combat_area_limit");
        require(player.getMainHandItem().getItem() instanceof SwordItem || player.getMainHandItem().getItem() instanceof AxeItem,
            "scoped_combat_selected_weapon_required");
    }
    private static boolean unchanged(net.minecraft.world.item.ItemStack live,net.minecraft.world.item.ItemStack original){
        var current=live.copy();
        if(current.getDamageValue()<original.getDamageValue())return false;
        if(current.isDamageableItem())current.setDamageValue(original.getDamageValue());
        return CapabilityItemBinding.same(current,original);
    }
    static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
}
