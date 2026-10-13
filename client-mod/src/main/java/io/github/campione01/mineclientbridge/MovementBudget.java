package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.Input;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

/** Optional acceptance envelope. Observes vanilla motion; never edits physics, position or velocity. */
public final class MovementBudget {
    private static MovementBudgetLedger ledger;
    private static boolean positionHookSeen, moveHookSeen;
    private static final Set<String> SAFE_FLOOR=Set.of("minecraft:stone","minecraft:cobblestone","minecraft:dirt",
        "minecraft:grass_block","minecraft:oak_planks","minecraft:andesite","minecraft:granite","minecraft:diorite",
        "minecraft:deepslate","minecraft:cobbled_deepslate","minecraft:smooth_stone","minecraft:stone_bricks","minecraft:bricks");
    private static final Set<String> SAFE_ACTIONS=Set.of("follow_path","break_block","place_block","click_slot",
        "interact_block","select_hotbar","close_menu","movement_budget_finish");
    static boolean budgetAction(String action){return action.equals("movement_budget_start")||action.equals("movement_budget_finish");}
    static void validate(ClientActionRequest r) {
        JsonObject b=r.original();
        if(budgetAction(r.action()))ClientActionRequest.require(CapabilityGuard.requested(b),"capability_guard_required");
        if(r.action().equals("movement_budget_start")) {
            ClientActionRequest.require(b.has("movement_budget")&&b.get("movement_budget").isJsonObject(),"invalid_movement_budget");
            JsonObject g=b.getAsJsonObject("movement_budget");
            ClientActionRequest.require(g.keySet().equals(Set.of("schema_version","bundle_id","max_distance","mode"))
                    &&ClientActionRequest.integer(g,"schema_version",-1)==1
                    &&ClientActionRequest.integer(g,"max_distance",-1)==32
                    &&ClientActionRequest.string(g,"mode").equals(MovementBudgetLedger.MODE),"invalid_movement_budget");
            validId(ClientActionRequest.string(g,"bundle_id"));
            ClientActionRequest.require(!b.has("movement_budget_bundle_id"),"movement_budget_start_binding_conflict");
        } else {
            ClientActionRequest.require(!b.has("movement_budget"),"movement_budget_start_required");
            if(b.has("movement_budget_bundle_id"))validId(ClientActionRequest.string(b,"movement_budget_bundle_id"));
            if(r.action().equals("movement_budget_finish"))ClientActionRequest.require(b.has("movement_budget_bundle_id"),"movement_budget_binding_required");
        }
    }
    private static void validId(String id){ClientActionRequest.require(!id.isBlank()&&id.length()<=128,"invalid_movement_budget_bundle_id");}
    static void admission(Minecraft mc,ClientActionRequest r) {
        validate(r);
        if(r.action().equals("movement_budget_start")) {
            if(ledger!=null)throw new ClientActionRequest.Rejected(409,"movement_budget_already_started");
            if(!positionHookSeen||!moveHookSeen)throw new ClientActionRequest.Rejected(409,"movement_budget_hooks_unverified");
            String problem=environment(mc,true);if(problem!=null)throw new ClientActionRequest.Rejected(409,problem);
            if(!BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean())throw new ClientActionRequest.Rejected(409,"movement_budget_input_not_neutral");
            return;
        }
        if(ledger==null) {
            if(r.original().has("movement_budget_bundle_id"))throw new ClientActionRequest.Rejected(409,"movement_budget_not_started");
            return;
        }
        observe(mc,false);
        if(!r.original().has("movement_budget_bundle_id")||!ledger.bundleId.equals(ClientActionRequest.string(r.original(),"movement_budget_bundle_id")))
            throw new ClientActionRequest.Rejected(409,"movement_budget_binding_changed");
        if(ledger.invalid()||!ledger.observing())throw new ClientActionRequest.Rejected(409,ledger.reason());
        if(ledger.stopping()&&!r.action().equals("movement_budget_finish"))throw new ClientActionRequest.Rejected(409,ledger.reason());
        if(!CapabilityGuard.requested(r.original())||!SAFE_ACTIONS.contains(r.action())||r.jump()
                ||r.waypoints().stream().anyMatch(ClientActionRequest.Point::jump)
                ||ClientActionRequest.bool(r.original(),"sprint",false)||ClientActionRequest.bool(r.original(),"capability_bridge",false)
                ||ClientActionRequest.bool(r.original(),"capability_descent",false))throw new ClientActionRequest.Rejected(409,"movement_budget_action_outside_envelope");
        if(r.action().equals("break_block")&&r.target().y()<Math.floor(mc.player.getY()))
            throw new ClientActionRequest.Rejected(409,"movement_budget_support_mining_forbidden");
        if(r.action().equals("follow_path")&&r.waypoints().stream().anyMatch(p->p.y()!=mc.player.getY()))
            throw new ClientActionRequest.Rejected(409,"movement_budget_flat_route_required");
        if(r.action().equals("movement_budget_finish")&&!ledger.canSeal())throw new ClientActionRequest.Rejected(409,"movement_budget_not_settled");
    }
    static void start(Minecraft mc,ClientActionRequest r) {
        if(ledger!=null)throw new ClientActionRequest.Rejected(409,"movement_budget_already_started");
        JsonObject b=r.original();String id=ClientActionRequest.string(b.getAsJsonObject("movement_budget"),"bundle_id");
        ledger=new MovementBudgetLedger(id,ClientActions.session(),WorldGeneration.current(mc.level),mc.player.getUUID().toString(),
            mc.level,mc.player,mc.player.getX(),mc.player.getY(),mc.player.getZ(),System.nanoTime());
    }
    static void finish(){ledger.seal(System.nanoTime());}
    static boolean armed(){return ledger!=null&&ledger.observing();}
    static void interrupt(String reason){if(ledger!=null)ledger.invalidate(reason);}
    /** Preserve isolation exactly; accepted human callbacks invalidate even between tick samples. */
    public static boolean acceptsInputCallback(){
        boolean accepted=ClientInputIsolation.acceptsInputCallback();
        if(accepted&&armed()&&!ClientInputIsolation.isSyntheticDispatch())interrupt("movement_budget_manual_input");
        return accepted;
    }
    public static void effectivePlayerTurn(Entity player,double dx,double dy){
        if((dx!=0||dy!=0)&&armed()&&player==ledger.player&&!ClientInputIsolation.isSyntheticDispatch())interrupt("movement_budget_manual_input");
    }
    static void preTick(Minecraft mc){if(armed())ledger.beginTick();observe(mc,false);}
    static void observe(Minecraft mc,boolean postTick) {
        if(!armed())return;
        try {
            if(mc.player==null||mc.level==null){ledger.invalidate("movement_budget_context_changed");return;}
            Vec3 v=mc.player.getDeltaMovement();
            ledger.sample(mc.level,mc.player,ClientActions.session(),mc.player.getX(),mc.player.getY(),mc.player.getZ(),
                v.horizontalDistance()<=.003&&mc.player.onGround(),postTick);
            String problem=environment(mc,false);if(problem!=null)ledger.invalidate(problem);
        } catch(RuntimeException unavailable){ledger.invalidate("movement_budget_observation_failed");}
    }
    static String invalidReason(){return ledger!=null&&ledger.invalid()?ledger.reason():null;}
    static String problem(Minecraft mc){observe(mc,false);return ledger!=null&&ledger.observing()&&!ledger.usable()?ledger.reason():null;}
    static void checkInput(Minecraft mc,Input input,boolean owned) {
        if(!armed())return;
        observe(mc,false);
        if(input.jumping||Math.abs(input.forwardImpulse)>1||Math.abs(input.leftImpulse)>1
                ||!owned&&(input.forwardImpulse!=0||input.leftImpulse!=0||input.up||input.down||input.left||input.right))
            ledger.invalidate("movement_budget_unowned_or_unsafe_input");
    }
    static JsonObject snapshot(Minecraft mc){observe(mc,false);return snapshot();}
    static JsonObject snapshot(){if(ledger!=null)return ledger.snapshot();JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("status","unarmed");j.addProperty("position_hook_seen",positionHookSeen);j.addProperty("move_hook_seen",moveHookSeen);return j;}

    // Entity hooks include all same-tick reversals, before callback-driven reentry.
    public static void beginMove(Entity entity,MoverType type,Vec3 requested) {
        if(!(entity instanceof net.minecraft.client.player.LocalPlayer))return;
        moveHookSeen=true;
        if(!armed()||entity!=ledger.player)return;
        if(Thread.currentThread()!=ledger.ownerThread){ledger.invalidate("movement_budget_wrong_thread");return;}
        ledger.beginMove(type==MoverType.SELF,requested.x,requested.y,requested.z);
    }
    public static void positionChanged(Entity entity) {
        if(!(entity instanceof net.minecraft.client.player.LocalPlayer))return;
        positionHookSeen=true;
        if(!armed()||entity!=ledger.player)return;
        if(Thread.currentThread()!=ledger.ownerThread){ledger.invalidate("movement_budget_wrong_thread");return;}
        ledger.position(entity.getX(),entity.getY(),entity.getZ());
    }
    public static void endMove(Entity entity){if(armed()&&entity==ledger.player)ledger.endMove();}
    private static String environment(Minecraft mc,boolean initial) {
        var p=mc.player;var level=mc.level;
        if(p==null||level==null||mc.gameMode==null||!CapabilityGuard.privateSingleplayer(mc))return "movement_budget_private_context_required";
        if(!mc.isWindowActive()||mc.isPaused())return "movement_budget_focus_or_pause_changed";
        if(!p.isAlive()||p.isSpectator()||p.isPassenger()||p.isSprinting()||p.getAbilities().flying||p.noPhysics
                ||p.isInWater()||p.isInLava()||p.isInPowderSnow||p.isOnFire()||p.onClimbable()||!p.onGround()
                ||!p.getActiveEffects().isEmpty()||p.hurtTime>0||p.fallDistance!=0)return "movement_budget_player_envelope_changed";
        Vec3 v=p.getDeltaMovement();
        if(!Double.isFinite(v.x)||!Double.isFinite(v.y)||!Double.isFinite(v.z)||v.horizontalDistance()>(initial?.003:MovementBudgetLedger.MAX_SPEED)
                ||v.y>0||v.y<-.09||Math.abs(p.getY()-Math.rint(p.getY()))>1e-7)return "movement_budget_velocity_or_height_changed";
        double speed=p.getAttributeValue(Attributes.MOVEMENT_SPEED);
        if(!Double.isFinite(speed)||speed<0||speed>.10000001||p.getSpeed()>.10000001F)return "movement_budget_speed_attribute_changed";
        if(mc.options.keyUp.isDown()||mc.options.keyDown.isDown()||mc.options.keyLeft.isDown()||mc.options.keyRight.isDown()
                ||mc.options.keyJump.isDown()||mc.options.keySprint.isDown()||mc.options.keyShift.isDown()||BridgeServer.hasHeldInputs())return "movement_budget_external_input";
        // Conservative clearance for the next <=.55 move. Known full cubes prevent step-up, edge fall and special friction.
        AABB box=p.getBoundingBox().inflate(.56,0,.56);int ground=(int)Math.rint(p.getY())-1;
        for(BlockPos cell:BlockPos.betweenClosed(BlockPos.containing(box.minX,ground,box.minZ),BlockPos.containing(box.maxX,ground,box.maxZ))) {
            if(!level.hasChunkAt(cell))return "movement_budget_unloaded_floor";
            var state=level.getBlockState(cell);String id=BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
            if(!SAFE_FLOOR.contains(id)||!state.isCollisionShapeFullBlock(level,cell)||!level.getFluidState(cell).isEmpty()
                    ||!ordinaryFriction(state.getFriction(level,cell,p)))return "movement_budget_floor_changed";
            for(int dy=1;dy<=2;dy++) {
                BlockPos head=cell.above(dy);
                if(!level.hasChunkAt(head)||!level.getBlockState(head).getCollisionShape(level,head).isEmpty()||!level.getFluidState(head).isEmpty())
                    return "movement_budget_clearance_changed";
            }
        }
        int examined=0;for(Entity entity:level.entitiesForRendering()) {
            if(++examined>1024)return "movement_budget_entity_observation_limit";
            if(entity!=p&&!entity.isRemoved()&&entity.distanceToSqr(p)<16) {
                if(!allowedNearbyEntity(entity))return "movement_budget_nearby_entity";
            }
        }
        return null;
    }
    static boolean furnaceOutputRequest(ClientActionRequest r){
        JsonObject b=r.original();
        if(!r.action().equals("click_slot")||r.slot()!=2||!r.clickType().equals("quick_move")||!CapabilityGuard.requested(b)
                ||!ClientActionRequest.string(b,"expected_menu_class").equals("net.minecraft.world.inventory.FurnaceMenu"))return false;
        JsonObject item=b.getAsJsonObject("expected_slot_item");
        return item.has("id")&&item.has("count")&&ClientActionRequest.string(item,"id").equals("minecraft:iron_ingot")
                &&ClientActionRequest.integer(item,"count",-1)==1;
    }
    static void beforeClick(Minecraft mc,ClientActionRequest r){
        if(!armed()||!ledger.usable()||!furnaceOutputRequest(r))return;
        var menu=mc.player.containerMenu;
        if(menu.getClass()!=net.minecraft.world.inventory.FurnaceMenu.class||menu.containerId!=r.containerId()||menu.slots.size()<=2)return;
        var output=menu.slots.get(2).getItem();
        if(output.is(net.minecraft.world.item.Items.IRON_INGOT)&&output.getCount()==1
                &&CapabilityItemBinding.matches(r.original().getAsJsonObject("expected_slot_item"),output))ledger.allowFurnaceXp();
    }
    static boolean allowedNearbyEntity(Entity entity){
        if(entity.getClass()==net.minecraft.world.entity.ExperienceOrb.class)
            return ledger!=null&&ledger.furnaceXpAllowed()&&entity.getType()==net.minecraft.world.entity.EntityType.EXPERIENCE_ORB;
        return entity.getClass()==net.minecraft.world.entity.item.ItemEntity.class
            &&entity.getType()==net.minecraft.world.entity.EntityType.ITEM
            &&((net.minecraft.world.entity.item.ItemEntity)entity).getItem().is(net.minecraft.world.item.Items.OAK_LOG);
    }
    static boolean ordinaryFriction(float friction){return Float.isFinite(friction)&&friction>=.5999999F&&friction<=.6000001F;}
    private MovementBudget(){}
}
