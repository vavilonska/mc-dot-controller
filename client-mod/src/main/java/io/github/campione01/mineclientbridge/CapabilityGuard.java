package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.state.BlockState;

/** Additive opt-in envelope. Ordinary legacy actions retain their existing policy. */
final class CapabilityGuard {
    private final ClientActionRequest request;
    private final LocalPlayer player;
    private final ClientLevel level;
    private final ItemStack held;
    private final net.minecraft.world.inventory.AbstractContainerMenu capturedMenu;
    private final int selected;
    private final long sourceNano,sourceTick;
    private boolean activeSelection;
    private float bestHealth;
    private CapabilityGuard(Minecraft mc,ClientActionRequest request,long nano,long tick) {
        this.request=request;player=mc.player;level=mc.level;sourceNano=nano;sourceTick=tick;capturedMenu=player.containerMenu;bestHealth=player.getHealth();
        selected=request.hotbarSlot()>=0?request.hotbarSlot():player.getInventory().selected;
        held=player.getInventory().getItem(selected).copy();
    }
    static boolean envelopeField(JsonObject body,String key) {
        return requested(body) && Set.of("capability_guard","expected_dimension","expected_hotbar_slot","expected_held_item").contains(key);
    }
    static boolean requested(JsonObject body) {return body.has("capability_guard");}
    static void validate(ClientActionRequest r) {
        JsonObject b=r.original();
        InventoryRecoveryGuard.validate(r);
        if(!requested(b)) {
            ClientActionRequest.require(java.util.Collections.disjoint(b.keySet(),Set.of("capability_route","encounter_route_guard","capability_bridge","capability_descent","placement_hit","placement_yaw","placement_footprint","require_pumpkin")),"capability_guard_required");
            ClientActionRequest.require(!Set.of("interact_block","use_item","select_hotbar","close_menu","attack_entity","shoot_entity","gateway_pearl","movement_budget_start","movement_budget_finish").contains(r.action()),"capability_guard_required");
            return;
        }
        ClientActionRequest.require(b.get("capability_guard").isJsonObject(),"invalid_capability_guard");
        JsonObject g=b.getAsJsonObject("capability_guard");
        ClientActionRequest.require(g.keySet().equals(Set.of("schema_version","source_tick","source_nano"))
                && ClientActionRequest.integer(g,"schema_version",-1)==1,"invalid_capability_guard");
        parseNano(g);parseTick(g);
        for(String key:Set.of("expected_world_generation","expected_player_uuid","expected_action_session","expected_dimension"))
            ClientActionRequest.require(!ClientActionRequest.string(b,key).isBlank(),"capability_identity_required");
        ClientActionRequest.require(r.timeoutMs()>0 && r.timeoutMs()<=60000,"capability_finite_deadline_required");
        if(Set.of("click_slot","close_menu").contains(r.action()))ClientActionRequest.string(b,"expected_menu_class");
        if(r.action().equals("click_slot")) {
            ClientActionRequest.require(r.slot()>=0,"capability_outside_click_not_supported");
            ClientActionRequest.require(ClientActionRequest.integer(b,"expected_menu_state_id",-1)>=0,"capability_menu_revision_required");
            object(b,"expected_slot_item");object(b,"expected_carried");
            if(r.clickType().equals("swap")) object(b,"expected_swap_item");
        } else if(r.action().equals("close_menu")) {
            ClientActionRequest.require(ClientActionRequest.integer(b,"container_id",-1)>=0 && ClientActionRequest.integer(b,"expected_menu_state_id",-1)>=0,"capability_menu_revision_required");
            object(b,"expected_carried");
        } else {
            int slot=ClientActionRequest.integer(b,"expected_hotbar_slot",-1);
            ClientActionRequest.require(slot>=0 && slot<=8,"capability_hotbar_binding_required");
            object(b,"expected_held_item");
        }
        if(Set.of("break_block","interact_block").contains(r.action())) ClientActionRequest.string(b,"expected_block_id");
        if(b.has("capability_route")) {
            ClientActionRequest.require(r.action().equals("follow_path") && ClientActionRequest.bool(b,"capability_route",false),"capability_route_requires_path");
            ClientActionRequest.require(b.has("expected_origin")&&b.has("expected_navigation_epoch"),"capability_route_binding_required");
        }
        CapabilityEncounterRoute.validate(r);
        if(b.has("require_pumpkin"))ClientActionRequest.bool(b,"require_pumpkin",false);
        if(b.has("capability_descent"))ClientActionRequest.require(r.action().equals("break_block")&&ClientActionRequest.bool(b,"capability_descent",false),"invalid_capability_descent");
        if(b.has("min_health") && Set.of("follow_path","place_block","break_block","combat_entity").contains(r.action()))CapabilityPlacement.number(b,"min_health",8,20);
        if(b.has("require_correct_tool"))ClientActionRequest.bool(b,"require_correct_tool",false);
        if(r.action().equals("place_block")) {
            for(String key:Set.of("expected_support_id","expected_target_id","expected_block_id")) ClientActionRequest.string(b,key);
            object(b,"expected_support_properties");object(b,"expected_target_properties");
            CapabilityPlacement.validate(r);
        }
    }
    static CapabilityGuard start(Minecraft mc,ClientActionRequest r) {
        if(!requested(r.original()))return null;
        validate(r);
        var spec=r.original().getAsJsonObject("capability_guard");
        CapabilityGuard guard=new CapabilityGuard(mc,r,parseNano(spec),parseTick(spec));
        guard.requireFresh(mc,"guard_start");
        String denied=guard.check(mc,false);
        if(denied!=null)throw new ClientActionRequest.Rejected(409,denied);
        if(!BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean())
            throw new ClientActionRequest.Rejected(409,"capability_input_not_neutral");
        return guard;
    }
    void activate(){activeSelection=true;}
    void requireFresh(Minecraft mc,String phase) {
        requireFresh(sourceNano,sourceTick,System.nanoTime(),mc.level.getGameTime(),phase);
    }
    static void requireFresh(long sourceNano,long sourceTick,long currentNano,long tick,String phase) {
        long elapsed=currentNano-sourceNano;
        boolean nanoNegative=elapsed<0,nanoExceeded=elapsed>800_000_000L;
        boolean tickReversed=tick<sourceTick,tickExceeded=tick-sourceTick>5;
        if(nanoNegative || nanoExceeded || tickReversed || tickExceeded) {
            JsonObject evidence=new JsonObject();evidence.addProperty("schema_version",1);
            evidence.addProperty("phase",phase);
            evidence.addProperty("source_tick",sourceTick);evidence.addProperty("current_tick",tick);
            evidence.addProperty("tick_delta",tick-sourceTick);
            evidence.addProperty("source_nano",Long.toString(sourceNano));
            evidence.addProperty("current_nano",Long.toString(currentNano));
            evidence.addProperty("elapsed_nanos",Long.toString(elapsed));
            evidence.addProperty("max_elapsed_nanos","800000000");evidence.addProperty("max_tick_delta",5);
            evidence.addProperty("nano_age_negative",nanoNegative);evidence.addProperty("nano_age_exceeded",nanoExceeded);
            evidence.addProperty("tick_reversed",tickReversed);evidence.addProperty("tick_delta_exceeded",tickExceeded);
            throw new ClientActionRequest.Rejected(409,"capability_source_expired",evidence);
        }
    }
    String check(Minecraft mc,boolean dispatched) {
        JsonObject b=request.original();
        if(mc.player!=player || mc.level!=level || mc.gameMode==null)return "capability_context_changed";
        if(!privateSingleplayer(mc))return "capability_private_singleplayer_required";
        if(!mc.isWindowActive() || mc.isPaused())return "capability_focus_or_pause_changed";
        if(!player.isAlive() || player.isSpectator() || !Float.isFinite(player.getHealth()))return "capability_player_unavailable";
        if(ClientActionRequest.bool(b,"require_pumpkin",false) && !player.getItemBySlot(net.minecraft.world.entity.EquipmentSlot.HEAD).is(net.minecraft.world.item.Items.CARVED_PUMPKIN))return "capability_pumpkin_removed";
        if(player.hasEffect(net.minecraft.world.effect.MobEffects.LEVITATION))return "capability_levitation_stop";
        if(ClientActionRequest.bool(b,"require_pumpkin",false)) {
            int examined=0;
            for(var entity:level.entitiesForRendering()) {
                if(++examined>1024)return "capability_end_entity_budget";
                if(!entity.isAlive() || entity==player)continue;
                if(entity instanceof net.minecraft.world.entity.monster.EnderMan enderman
                        && entity.distanceToSqr(player)<=256 && (enderman.isCreepy()||enderman.hasBeenStaredAt()||enderman.getTarget()==player))return "capability_aggressive_enderman";
                boolean ownBullet=request.action().equals("attack_entity") && b.has("target_uuid") && entity.getUUID().toString().equals(ClientActionRequest.string(b,"target_uuid"));
                if(entity instanceof net.minecraft.world.entity.projectile.ShulkerBullet && !ownBullet && entity.distanceToSqr(player)<16)return "capability_nearby_shulker_bullet";
                if(entity instanceof net.minecraft.world.entity.AreaEffectCloud && entity.distanceToSqr(player)<36)return "capability_nearby_effect_cloud";
            }
        }
        if(b.has("min_health") && !(request.action().equals("combat_entity") && b.has("defensive_policy"))
                && !CapabilityCombatSafety.healthy(player.getHealth(),b.get("min_health").getAsDouble()))return "capability_health_guard";
        String encounterProblem=CapabilityEncounterRoute.check(mc,request);
        if(encounterProblem!=null)return encounterProblem;
        String shellProblem=dispatched?null:CapabilityTargetAction.shulkerAdmission(mc,request);
        if(shellProblem!=null)return shellProblem;
        if(!Set.of("recover_environment","combat_entity","attack_entity","shoot_entity").contains(request.action())) {
            if(player.getHealth()<bestHealth || player.hurtTime>0)return "capability_damage_observed";
            bestHealth=Math.max(bestHealth,player.getHealth());
            if(player.isInWater() || player.isEyeInFluid(net.minecraft.tags.FluidTags.WATER)
                    || player.isInLava() || player.isInPowderSnow || player.isOnFire())return "capability_environment_hazard";
        }
        if(!ClientActionRequest.string(b,"expected_dimension").equals(level.dimension().location().toString())
                || !ClientActionRequest.string(b,"expected_world_generation").equals(WorldGeneration.current(level))
                || !ClientActionRequest.string(b,"expected_player_uuid").equals(player.getUUID().toString())
                || !ClientActionRequest.string(b,"expected_action_session").equals(ClientActions.session()))return "capability_identity_changed";
        boolean menuAction=Set.of("click_slot","close_menu").contains(request.action());
        if(mc.screen!=null && !menuAction && !(dispatched && request.action().equals("interact_block")))return "capability_screen_opened";
        if(!menuAction) {
            int expectedSelection=activeSelection?selected:ClientActionRequest.integer(b,"expected_hotbar_slot",-1);
            if(player.getInventory().selected!=expectedSelection)return "capability_hotbar_changed";
        }
        if(ClientActionRequest.bool(b,"capability_descent",false)) {
            BlockPos lower=pos(request.target()).below();
            if(!level.hasChunkAt(lower)||!level.getBlockState(lower).isCollisionShapeFullBlock(level,lower)||!level.getFluidState(lower).isEmpty()
                    || Math.hypot(player.getX()-lower.getX()-.5,player.getZ()-lower.getZ()-.5)>.25)return "capability_descent_support_changed";
        }
        if(dispatched) {
            if(request.action().equals("break_block")) {
                BlockPos target=pos(request.target());
                if(!level.hasChunkAt(target))return "capability_target_unloaded";
                var state=level.getBlockState(target);
                if(state.isAir())return null; // No further attack; mine() terminates absent.
                if(!blockMatches(state,ClientActionRequest.string(b,"expected_block_id"),b.has("expected_block_properties")?object(b,"expected_block_properties"):null))return "capability_target_changed";
                ItemStack current=player.getMainHandItem().copy();
                // Only ordinary durability loss may evolve during one mining hold.
                if(current.getDamageValue()<held.getDamageValue())return "capability_tool_changed";
                if(current.isDamageableItem())current.setDamageValue(held.getDamageValue());
                if(!CapabilityItemBinding.same(current,held))return "capability_tool_changed";
                if(ClientActionRequest.bool(b,"require_correct_tool",false) && !player.hasCorrectToolForDrops(state))return "capability_correct_tool_required";
            } else if(request.action().equals("use_item") && player.isUsingItem()) {
                ItemStack current=player.getMainHandItem();
                if(!ItemStack.isSameItemSameComponents(current,held) || current.getCount()>held.getCount()
                        || current.getCount()<held.getCount()-1)return "capability_consumable_changed";
            }
            return null;
        }
        if(menuAction) {
            String recoveryProblem = InventoryRecoveryGuard.check(mc, request);
            if(recoveryProblem != null)return recoveryProblem;
            var menu=player.containerMenu;
            int expectedContainer=request.action().equals("click_slot")?request.containerId():ClientActionRequest.integer(b,"container_id",-1);
            if(menu!=capturedMenu || !menu.getClass().getName().equals(ClientActionRequest.string(b,"expected_menu_class"))
                    || menu.containerId!=expectedContainer || menu.getStateId()!=ClientActionRequest.integer(b,"expected_menu_state_id",-1))return "capability_menu_changed";
            if(!CapabilityItemBinding.matches(object(b,"expected_carried"),menu.getCarried()))return "capability_cursor_changed";
            if(request.action().equals("close_menu"))return menu.getCarried().isEmpty()?null:"capability_cursor_not_empty";
            if(request.slot()<0 || request.slot()>=menu.slots.size() || !CapabilityItemBinding.matches(object(b,"expected_slot_item"),menu.slots.get(request.slot()).getItem()))return "capability_slot_changed";
            if(request.clickType().equals("swap") && !CapabilityItemBinding.matches(object(b,"expected_swap_item"),player.getInventory().getItem(request.button())))return "capability_swap_slot_changed";
        } else {
            if(activeSelection && request.action().equals("combat_entity")) {
                ItemStack current=player.getMainHandItem().copy();
                if(current.getDamageValue()<held.getDamageValue())return "capability_tool_changed";
                if(current.isDamageableItem())current.setDamageValue(held.getDamageValue());
                if(!CapabilityItemBinding.same(current,held))return "capability_tool_changed";
            } else if(!CapabilityItemBinding.matches(object(b,"expected_held_item"),player.getInventory().getItem(selected))
                    || !CapabilityItemBinding.same(held,player.getInventory().getItem(selected)))return "capability_held_item_changed";
        }
        if(Set.of("break_block","interact_block").contains(request.action())) {
            BlockPos p=pos(request.target());
            if(!level.hasChunkAt(p) || !blockMatches(level.getBlockState(p),ClientActionRequest.string(b,"expected_block_id"),b.has("expected_block_properties")?object(b,"expected_block_properties"):null))return "capability_target_changed";
            if(request.action().equals("break_block") && ClientActionRequest.bool(b,"require_correct_tool",false)
                    && !player.hasCorrectToolForDrops(level.getBlockState(p)))return "capability_correct_tool_required";
        }
        if(request.action().equals("place_block")) {
            String footprint=CapabilityPlacement.before(mc,request);if(footprint!=null)return footprint;
            BlockPos support=pos(request.support());
            var face=net.minecraft.core.Direction.valueOf(request.face().toUpperCase(java.util.Locale.ROOT));
            BlockPos target=support.relative(face);
            if(!level.hasChunkAt(support) || !level.hasChunkAt(target)
                    || !blockMatches(level.getBlockState(support),ClientActionRequest.string(b,"expected_support_id"),object(b,"expected_support_properties"))
                    || !blockMatches(level.getBlockState(target),ClientActionRequest.string(b,"expected_target_id"),object(b,"expected_target_properties")))return "capability_placement_context_changed";
            if(!(held.getItem() instanceof net.minecraft.world.item.BlockItem item))return "capability_placement_item_mismatch";
            String expected=ClientActionRequest.string(b,"expected_block_id"), itemBlock=BuiltInRegistries.BLOCK.getKey(item.getBlock()).toString();
            boolean wallVariant=item instanceof net.minecraft.world.item.StandingAndWallBlockItem && (
                itemBlock.equals("minecraft:torch")&&expected.equals("minecraft:wall_torch")
                || itemBlock.equals("minecraft:soul_torch")&&expected.equals("minecraft:soul_wall_torch"));
            if(!itemBlock.equals(expected)&&!wallVariant)return "capability_placement_item_mismatch";
        }
        return null;
    }
    static boolean privateSingleplayer(Minecraft mc) {return mc.hasSingleplayerServer() && mc.getSingleplayerServer()!=null && !mc.getSingleplayerServer().isPublished();}
    static boolean blockMatches(BlockState state,String id,JsonObject properties) {
        if(!BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString().equals(id))return false;
        if(properties==null)return true;
        for(var entry:properties.entrySet()) {
            var property=state.getBlock().getStateDefinition().getProperty(entry.getKey());
            if(property==null || !propertyValue(state,property).equals(entry.getValue().getAsString()))return false;
        }
        return true;
    }
    private static <T extends Comparable<T>> String propertyValue(BlockState s,net.minecraft.world.level.block.state.properties.Property<T> p) {return p.getName(s.getValue(p));}
    static JsonObject observation(long tick,long nano) {var j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("source_tick",tick);j.addProperty("source_nano",Long.toString(nano));return j;}
    private static JsonObject object(JsonObject b,String k) {ClientActionRequest.require(b.has(k)&&b.get(k).isJsonObject(),"invalid_"+k);return b.getAsJsonObject(k);}
    private static long parseNano(JsonObject s) {String value=ClientActionRequest.string(s,"source_nano");ClientActionRequest.require(value.matches("-?(0|[1-9][0-9]{0,18})"),"invalid_capability_source_nano");try{return Long.parseLong(value);}catch(NumberFormatException e){throw new ClientActionRequest.Rejected(400,"invalid_capability_source_nano");}}
    private static long parseTick(JsonObject s) {var e=s.get("source_tick");ClientActionRequest.require(e!=null&&e.isJsonPrimitive()&&e.getAsJsonPrimitive().isNumber(),"invalid_capability_source_tick");double v=e.getAsDouble();ClientActionRequest.require(Double.isFinite(v)&&v>=0&&v==Math.rint(v)&&v<=9007199254740991L,"invalid_capability_source_tick");return (long)v;}
    private static BlockPos pos(ClientActionRequest.Cell p){return new BlockPos(p.x(),p.y(),p.z());}
}
