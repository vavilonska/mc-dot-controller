package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.Input;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.entity.ai.attributes.AttributeInstance;
import net.minecraft.world.entity.ai.attributes.AttributeMap;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.GrassBlock;

/** Isolated-pedestal one-block descent under ClientActions' sole input owner.
 * Never writes position, velocity, packets, keys, or another owner's input.
 */
final class ScopedStepDownMovement {
    static final String PROFILE="movement-step-down-observed-v1";
    static final String TIMING_CONTRACT="native-action-pre-ticks-v1";
    static final Set<String> FLOORS=Set.of("minecraft:stone","minecraft:cobblestone","minecraft:dirt",
            "minecraft:grass_block","minecraft:oak_planks","minecraft:andesite","minecraft:granite",
            "minecraft:diorite","minecraft:cobbled_deepslate","minecraft:smooth_stone",
            "minecraft:stone_bricks","minecraft:bricks");
    final LocalPlayer player;
    final ClientLevel level;
    final Object server;
    final String session, serverIdentity, worldGeneration, playerUuid;
    final long navigationEpoch;
    final ScopedFlatPolicy.Bounds bounds;
    final ScopedStepDownPolicy.Bounds descent;
    private ScopedStepDownPolicy.Phase phase=ScopedStepDownPolicy.Phase.UPPER;
    private double lastY;
    private int airborneSince=-1;
    final long sourceNano, sourceTick, deadline;
    final JsonObject footprint;
    private final ClientActionRequest request;
    private final float initialHealth;
    private final int initialFood;
    private final AttributeMap attributeMap;
    private final AttributeInstance gravityAttribute, movementAttribute;
    private final Pose admissionPose;
    private final ScopedMovementEntities admissionEntities;
    private long lastEntityTick,lastEntityNano;
    private int maximumCheckedPopulation;
    private long ownerRevision;
    private ActionRegistry.Entry actionEntry;
    private int sampleActionTick=0;
    private double sampleX,sampleY,sampleZ,tickDistance,tickDownDistance,sampledDistance;
    private boolean activated, attempted;
    private int checks;

    ScopedStepDownMovement(Minecraft mc, ClientActionRequest request, long sourceNano, long sourceTick) {
        this.request=request;this.sourceNano=sourceNano;this.sourceTick=sourceTick;
        validateIntent(request.original());
        require(MovementBudget.snapshot().get("status").getAsString().equals("unarmed"),"step_down_movement_budget_must_be_unarmed");
        player=mc.player;level=mc.level;
        require(player.getClass()==LocalPlayer.class,"step_down_exact_player_class_required");
        attributeMap=player.getAttributes();gravityAttribute=player.getAttribute(Attributes.GRAVITY);movementAttribute=player.getAttribute(Attributes.MOVEMENT_SPEED);
        require(attributeMap!=null && attributeMap.getClass()==AttributeMap.class
                && gravityAttribute!=null && gravityAttribute.getClass()==AttributeInstance.class
                && movementAttribute!=null && movementAttribute.getClass()==AttributeInstance.class,"step_down_exact_attribute_readers_required");server=mc.getSingleplayerServer();session=ClientActions.session();
        serverIdentity=IntegratedServerIdentity.current(server,CapabilityGuard.privateSingleplayer(mc));
        worldGeneration=WorldGeneration.current(level);playerUuid=player.getUUID().toString();navigationEpoch=NavigationPositionGuard.epoch();
        require(request.action().equals("follow_path") && request.timeoutMs()<=ScopedStepDownPolicy.MAX_TIMEOUT_MS
                && ClientActionRequest.bool(request.original(),"capability_route",false)
                && !request.jump() && !request.sneak() && request.hotbarSlot()==-1
                && !ClientActionRequest.bool(request.original(),"sprint",false)
                && request.waypoints().stream().noneMatch(ClientActionRequest.Point::jump),"step_down_request_outside_profile");
        // No other special route may borrow this profile's authority.
        require(!request.original().has("encounter_route_guard") && !request.original().has("coordination_step"),
                "step_down_other_route_forbidden");
        try {descent=ScopedStepDownPolicy.route(player.getX(),player.getY(),player.getZ(),request.waypoints().stream()
                .map(p->new ScopedStepDownPolicy.Point(p.x(),p.y(),p.z())).toList()); bounds=descent.prism();}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        JsonObject origin=request.original().getAsJsonObject("expected_origin");
        require(origin!=null && Math.abs(origin.get("x").getAsDouble()-player.getX())<=.03
                && Math.abs(origin.get("y").getAsDouble()-player.getY())<=.03
                && Math.abs(origin.get("z").getAsDouble()-player.getZ())<=.03,"step_down_origin_changed");
        initialHealth=player.getHealth();initialFood=player.getFoodData().getFoodLevel();deadline=sourceNano+request.timeoutMs()*1_000_000L;
        sampleX=player.getX();sampleY=player.getY();sampleZ=player.getZ();lastY=player.getY();
        // Admission has no Entry yet; its action age is explicitly zero.
        admissionEntities=ScopedMovementEntities.capture(level,player,bounds,0);
        lastEntityTick=admissionEntities.frame.tick();lastEntityNano=admissionEntities.frame.nano();
        maximumCheckedPopulation=admissionEntities.frame.population();
        Pose pose=environment(mc,true);
        admissionPose=pose;
        footprint=terrain(mc);
        require(pose.equals(environment(mc,true)),"step_down_facts_changed_after_hooks");
        assertRawFootprint();
        admissionEntities.assertUnchanged();
        fence(mc,pose,false,0);
    }

    void activate(ActionRegistry.Entry entry) {
        require(!activated && actionEntry==null && entry!=null && entry.running() && entry.ticks==0
                && entry.request.id().equals(request.id()) && entry.request.action().equals(request.action())
                && entry.request.timeoutMs()==request.timeoutMs() && ClientActions.ownsScopedStepDown(this,entry),
                "step_down_activation_changed");
        actionEntry=entry;ownerRevision=ClientActions.ownershipRevision();activated=true;
    }
    /** Raw native Entry state only; no supplier, world-clock age, or per-effect increment. */
    private int actionTicks() {
        require(activated && actionEntry!=null && ClientActions.ownsScopedStepDown(this,actionEntry)
                && ClientActions.ownershipRevision()==ownerRevision,"step_down_action_owner_changed");
        int ticks=actionEntry.ticks;
        require(ticks>=0 && ticks<ScopedEntityPolicy.MAX_TICKS,"step_down_entity_tick_budget");
        require(ticks>=sampleActionTick && ticks-sampleActionTick<=1,"step_down_tick_gap");
        return ticks;
    }
    JsonObject facts(){
        try {JsonObject out=footprint.deepCopy();out.add("entity_guard",admissionEntities.frame.json());return out;}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
    }
    void admissionRecheck(Minecraft mc) {
        Pose pose=environment(mc,true);
        require(footprint.equals(terrain(mc)),"step_down_footprint_changed");
        require(pose.equals(environment(mc,true)),"step_down_facts_changed_after_hooks");
        assertRawFootprint();
        admissionEntities.assertUnchanged();
        fence(mc,pose,false,0);
    }
    /** Runs after final generic inventory/menu facts; never performs shape/friction/attribute/slot hooks. */
    void admissionRawFence(Minecraft mc) {
        assertRawFootprint();
        admissionEntities.assertUnchanged();
        fence(mc,admissionPose,false,0);
    }
    /** Reads may call mod hooks. The final fence deliberately does no block/entity/attribute hooks. */
    void beforeEffect(Minecraft mc) {
        long began=System.nanoTime();
        int actionTicks=actionTicks();
        ScopedMovementEntities entities=ScopedMovementEntities.capture(level,player,bounds,actionTicks);
        Pose pose=environment(mc,false);
        require(footprint.equals(terrain(mc)),"step_down_footprint_changed");
        require(pose.equals(environment(mc,false)),"step_down_facts_changed_after_hooks");
        assertRawFootprint();
        entities.assertUnchanged();
        require(System.nanoTime()-began>=0 && System.nanoTime()-began<=ScopedNativePreflight.MAX_NANOS,
                "step_down_check_budget_exceeded");
        fence(mc,pose,true,actionTicks);
        account(pose,actionTicks);
        lastEntityTick=entities.frame.tick();lastEntityNano=entities.frame.nano();
        maximumCheckedPopulation=Math.max(maximumCheckedPopulation,entities.frame.population());
        checks++;
    }
    void markAttempted(){attempted=true;}
    private record Pose(double x,double y,double z,double vx,double vy,double vz,float health,float yaw,float pitch,long tick,boolean grounded,float fall) { }
    private Pose environment(Minecraft mc,boolean initial) {
        require(mc.player==player && mc.level==level && mc.gameMode!=null && CapabilityGuard.privateSingleplayer(mc)
                && mc.gameMode.getPlayerMode()==GameType.SURVIVAL
                && level.dimension().location().toString().equals("minecraft:overworld"),"step_down_private_overworld_survival_required");
        require(player.containerMenu==player.inventoryMenu && player.containerMenu.getClass()==InventoryMenu.class
                && mc.screen==null && player.containerMenu.getCarried().isEmpty() && !player.isUsingItem(),
                "step_down_closed_inventory_required");
        require(player.isAlive() && !player.isSpectator() && !player.isPassenger() && !player.isSprinting()
                && !player.getAbilities().flying && !player.getAbilities().mayfly && !player.noPhysics
                && !player.isFallFlying() && !player.isSwimming() && !player.isCrouching() && !player.isNoGravity()
                && !player.isAutoJumpEnabled() && !mc.options.autoJump().get() && player.autoJumpTime==0
                && !player.isInWater() && !player.isInLava() && !player.isInPowderSnow && !player.isOnFire()
                && !player.onClimbable() && player.getActiveEffects().isEmpty() && player.hurtTime==0
                && (!initial || player.onGround() && player.fallDistance==0) && !player.horizontalCollision,"step_down_player_envelope_changed");
        double speed=player.getAttributeValue(Attributes.MOVEMENT_SPEED);
        double gravity=player.getAttributeValue(Attributes.GRAVITY);
        require(Double.isFinite(gravity) && Math.abs(gravity-.08)<=1e-9,"step_down_ordinary_gravity_required");
        var v=player.getDeltaMovement();var box=player.getBoundingBox();
        require(ScopedFlatPolicy.finite(speed,player.getSpeed(),v.x,v.y,v.z,player.getHealth()) && speed>=0
                && speed<=.10000001 && player.getSpeed()>=0 && player.getSpeed()<=.10000001F
                && v.horizontalDistance()<=(initial?.003:ScopedStepDownPolicy.MAX_SPEED) && v.y<=0 && v.y>=-ScopedStepDownPolicy.MAX_DOWNWARD_SPEED
                && (!initial || v.y>=-.09)
                && box.getXsize()>=.599999 && box.getXsize()<=.600001 && box.getZsize()>=.599999 && box.getZsize()<=.600001
                && box.getYsize()>=1.799999 && box.getYsize()<=1.800001
                && initialFood>=6 && initialFood<=20 && player.getFoodData().getFoodLevel()==initialFood
                && Math.abs(box.minX-(player.getX()-.3))<=1e-6 && Math.abs(box.minZ-(player.getZ()-.3))<=1e-6
                && Math.abs(box.minY-player.getY())<=1e-6
                && player.getHealth()>=initialHealth && descent.contains(player.getX(),player.getY(),player.getZ()),
                "step_down_motion_or_health_changed");
        try {ScopedStepDownPolicy.phase(descent,phase,lastY,player.getY(),v.y,player.fallDistance,player.onGround());}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        return new Pose(player.getX(),player.getY(),player.getZ(),v.x,v.y,v.z,player.getHealth(),player.getYRot(),player.getXRot(),level.getGameTime(),player.onGround(),player.fallDistance);
    }
    private JsonObject terrain(Minecraft mc) {
        JsonObject out=new JsonObject();
        out.addProperty("profile",PROFILE);out.addProperty("source","native-client-loaded-level");
        out.addProperty("min_x",bounds.minX());out.addProperty("max_x",bounds.maxX());
        out.addProperty("min_y",bounds.minY());out.addProperty("max_y",bounds.maxY());
        out.addProperty("min_z",bounds.minZ());out.addProperty("max_z",bounds.maxZ());
        out.addProperty("start_x",descent.startX());out.addProperty("start_y",descent.startY());out.addProperty("start_z",descent.startZ());
        out.addProperty("end_x",descent.endX());out.addProperty("end_y",descent.endY());out.addProperty("end_z",descent.endZ());out.addProperty("steps",1);
        out.addProperty("halo",ScopedStepDownPolicy.HALO);out.addProperty("expected_cells",bounds.cells());
        out.addProperty("all_loaded",true);out.addProperty("movement_budget_status","unarmed");out.addProperty("source_food_level",initialFood);
        out.addProperty("closed_inventory",true);out.addProperty("survival",true);out.addProperty("using_item",false);
        out.addProperty("maximum_horizontal_speed",ScopedStepDownPolicy.MAX_SPEED);
        out.addProperty("maximum_tick_sampled_displacement",ScopedStepDownPolicy.MAX_TICK_DISPLACEMENT);
        out.addProperty("maximum_downward_speed",ScopedStepDownPolicy.MAX_DOWNWARD_SPEED);
        out.addProperty("maximum_fall_distance",ScopedStepDownPolicy.MAX_FALL_DISTANCE);
        out.addProperty("maximum_airborne_ticks",ScopedStepDownPolicy.MAX_AIRBORNE_TICKS);
        out.addProperty("deadline_nano",Long.toString(deadline));
        JsonArray cells=new JsonArray();
        for(int x=bounds.minX();x<=bounds.maxX();x++)for(int y=bounds.minY();y<=bounds.maxY();y++)for(int z=bounds.minZ();z<=bounds.maxZ();z++) {
            BlockPos pos=new BlockPos(x,y,z);
            require(level.hasChunkAt(pos),"step_down_unknown_corridor_cell");
            var state=level.getBlockState(pos);String id=BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
            require(level.getFluidState(pos).isEmpty(),"step_down_fluid_present");
            boolean floor=descent.solid(x,y,z);float friction=0;
            if(floor) {
                var type=state.getBlock().getClass();
                require(FLOORS.contains(id) && (type==Block.class || type==GrassBlock.class)
                        && state.isCollisionShapeFullBlock(level,pos),"step_down_floor_unsupported");
                friction=state.getFriction(level,pos,player);
                require(Float.isFinite(friction) && friction>=.5999999F && friction<=.6000001F,
                        "step_down_special_friction");
            } else require((id.equals("minecraft:air") || id.equals("minecraft:cave_air"))
                    && state.isAir() && state.getCollisionShape(level,pos).isEmpty(),"step_down_clearance_or_hazard_changed");
            JsonObject cell=new JsonObject();cell.addProperty("x",x);cell.addProperty("y",y);cell.addProperty("z",z);
            cell.addProperty("id",id);cell.addProperty("state",state.toString());cell.addProperty("fluid","minecraft:empty");
            cell.addProperty("full_cube",floor);cell.addProperty("friction",friction);cells.add(cell);
        }
        out.add("cells",cells);return out;
    }
    /** No shape, friction, attribute, permission or ray hooks after this point. */
    private void assertRawFootprint() {
        for(var element:footprint.getAsJsonArray("cells")) {
            var row=element.getAsJsonObject();
            BlockPos pos=new BlockPos(row.get("x").getAsInt(),row.get("y").getAsInt(),row.get("z").getAsInt());
            require(level.hasChunkAt(pos),"step_down_corridor_unloaded_after_hooks");
            var state=level.getBlockState(pos);
            require(BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString().equals(row.get("id").getAsString())
                    && state.toString().equals(row.get("state").getAsString()) && state.getFluidState().isEmpty(),
                    "step_down_corridor_changed_after_hooks");
        }
    }
    /** Final hook-free field/identity/time fence, immediately preceding a direct view/input write. */
    private void fence(Minecraft mc,Pose p,boolean owned,int actionTicks) {
        // Exact vanilla AttributeMap/AttributeInstance readers bind base values and absence of modifiers.
        // No getAttributeValue/calculateValue callback is used at this final boundary.
        require(player.getAttributes()==attributeMap && player.getAttribute(Attributes.GRAVITY)==gravityAttribute
                && player.getAttribute(Attributes.MOVEMENT_SPEED)==movementAttribute
                && Math.abs(gravityAttribute.getBaseValue()-.08)<=1e-9 && gravityAttribute.getModifiers().isEmpty()
                && movementAttribute.getBaseValue()>=0 && movementAttribute.getBaseValue()<=.10000001
                && movementAttribute.getModifiers().isEmpty(),"step_down_attribute_binding_changed_after_hooks");
        long now=System.nanoTime();var v=player.getDeltaMovement();
        require(mc.isSameThread() && mc.player==player && mc.level==level && mc.gameMode!=null
                && mc.getSingleplayerServer()==server && CapabilityGuard.privateSingleplayer(mc)
                && serverIdentity.equals(IntegratedServerIdentity.current(server,true))
                && worldGeneration.equals(WorldGeneration.current(level)) && player.getUUID().toString().equals(playerUuid)
                && NavigationPositionGuard.epoch()==navigationEpoch
                && ClientActions.session().equals(session)
                && now>=sourceNano && now<deadline && actionTicks>=0 && actionTicks<ScopedEntityPolicy.MAX_TICKS
                && level.getGameTime()==p.tick
                && mc.isWindowActive() && !mc.isPaused() && mc.screen==null
                && player.containerMenu==player.inventoryMenu && player.containerMenu.getCarried().isEmpty()
                && mc.gameMode.getPlayerMode()==GameType.SURVIVAL && player.isAlive() && !player.isSpectator()
                && !player.isPassenger() && !player.isSprinting() && !player.getAbilities().flying && !player.noPhysics
                && !player.isInWater() && !player.isInLava() && !player.isInPowderSnow && !player.isOnFire()
                && player.getActiveEffects().isEmpty() && player.fallDistance==p.fall && !player.isUsingItem()
                && !player.isAutoJumpEnabled() && !mc.options.autoJump().get() && player.autoJumpTime==0
                && !player.isFallFlying() && !player.isSwimming() && !player.isCrouching() && !player.isNoGravity() && !player.getAbilities().mayfly
                && MovementBudget.snapshot().get("status").getAsString().equals("unarmed")
                && player.getFoodData().getFoodLevel()==initialFood
                && Math.abs(player.getBoundingBox().minX-(player.getX()-.3))<=1e-6
                && Math.abs(player.getBoundingBox().minZ-(player.getZ()-.3))<=1e-6
                && Math.abs(player.getBoundingBox().minY-player.getY())<=1e-6
                && player.getSpeed()>=0 && player.getSpeed()<=.10000001F && player.getBoundingBox().getXsize()>=.599999 && player.getBoundingBox().getXsize()<=.600001
                && player.getBoundingBox().getZsize()>=.599999 && player.getBoundingBox().getZsize()<=.600001
                && player.getBoundingBox().getYsize()>=1.799999 && player.getBoundingBox().getYsize()<=1.800001
                && player.getX()==p.x && player.getY()==p.y && player.getZ()==p.z
                && v.x==p.vx && v.y==p.vy && v.z==p.vz && player.getHealth()==p.health && player.getYRot()==p.yaw && player.getXRot()==p.pitch
                && player.hurtTime==0 && player.onGround()==p.grounded && !player.horizontalCollision
                && !keysDown(mc) && !BridgeServer.hasHeldInputs()
                && (owned ? activated && actionEntry!=null && ClientActions.ownsScopedStepDown(this,actionEntry)
                    && ClientActions.ownershipRevision()==ownerRevision
                    // Re-read the trusted Entry after every potentially reentrant fact hook.
                    && actionEntry.ticks==actionTicks
                    : !activated && actionEntry==null && actionTicks==0 && !ClientActions.ownsInput()),
                "step_down_final_boundary_changed");
    }
    private void account(Pose p,int actionTicks) {
        require(actionTicks>=sampleActionTick && actionTicks-sampleActionTick<=1,"step_down_tick_gap");
        ScopedStepDownPolicy.Phase next;
        try {next=ScopedStepDownPolicy.phase(descent,phase,lastY,p.y,p.vy,p.fall,p.grounded);}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        int nextAirborneSince=next==ScopedStepDownPolicy.Phase.DESCENDING && airborneSince<0?actionTicks:airborneSince;
        require(next!=ScopedStepDownPolicy.Phase.DESCENDING || actionTicks-nextAirborneSince<=ScopedStepDownPolicy.MAX_AIRBORNE_TICKS,
                "step_down_airborne_tick_budget");
        double distance=Math.hypot(p.x-sampleX,p.z-sampleZ);
        double nextTickDistance=(actionTicks==sampleActionTick?tickDistance:0)+distance;
        double nextSampledDistance=sampledDistance+distance;
        double nextDownDistance=(actionTicks==sampleActionTick?tickDownDistance:0)+Math.max(0,sampleY-p.y);
        require(nextDownDistance<=ScopedStepDownPolicy.MAX_DOWNWARD_SPEED+1e-6,"step_down_tick_drop_exceeded");
        require(nextTickDistance<=ScopedStepDownPolicy.MAX_TICK_DISPLACEMENT
                && nextSampledDistance<=bounds.steps()+1,"step_down_sampled_displacement_exceeded");
        airborneSince=nextAirborneSince;phase=next;lastY=p.y;tickDownDistance=nextDownDistance;
        tickDistance=nextTickDistance;sampledDistance=nextSampledDistance;
        sampleActionTick=actionTicks;sampleX=p.x;sampleY=p.y;sampleZ=p.z;
    }
    static void validateIntent(JsonObject body) {
        var health=body.get("min_health");
        require(health!=null && health.isJsonPrimitive() && health.getAsJsonPrimitive().isNumber()
                && Double.isFinite(health.getAsDouble()) && health.getAsDouble()>=8 && health.getAsDouble()<=20,
                "step_down_health_guard_required");
        require(Set.of("action_id","action","timeout_ms","waypoints","capability_route","min_health","jump","sprint","sneak",
            "capability_guard","expected_origin","expected_navigation_epoch","expected_world_generation","expected_dimension",
            "expected_player_uuid","expected_action_session","expected_hotbar_slot","expected_held_item").containsAll(body.keySet()),
            "step_down_unknown_intent_field");
        require(body.has("waypoints") && body.get("waypoints").isJsonArray() && body.getAsJsonArray("waypoints").size()==1,
            "step_down_exactly_one_step");
        var point=body.getAsJsonArray("waypoints").get(0);
        require(point.isJsonObject() && Set.of("x","y","z","jump").containsAll(point.getAsJsonObject().keySet()),"step_down_unknown_waypoint_field");
    }
    boolean settled() {
        var v=player.getDeltaMovement();
        return phase==ScopedStepDownPolicy.Phase.LANDED && player.onGround() && player.fallDistance==0
            && Math.abs(player.getY()-descent.endY())<=1e-6
            && Math.hypot(player.getX()-descent.endX()-.5,player.getZ()-descent.endZ()-.5)<=.23
            && ScopedStepDownPolicy.finite(v.x,v.y,v.z) && Math.hypot(v.x,v.z)<=.003 && v.y>=-.09 && v.y<=0;
    }
    static boolean keysDown(Minecraft mc){return mc.options.keyUp.isDown() || mc.options.keyDown.isDown()
            || mc.options.keyLeft.isDown() || mc.options.keyRight.isDown() || mc.options.keyJump.isDown()
            || mc.options.keySprint.isDown() || mc.options.keyShift.isDown() || mc.options.keyAttack.isDown()
            || mc.options.keyUse.isDown();}
    static boolean neutral(Input input){return input==null || input.forwardImpulse==0 && input.leftImpulse==0
            && !input.up && !input.down && !input.left && !input.right && !input.jumping && !input.shiftKeyDown;}
    JsonObject terminal(boolean neutral) {
        JsonObject out=new JsonObject();out.addProperty("profile",PROFILE);out.addProperty("effect_attempted",attempted);
        out.addProperty("local_checks",checks);out.addProperty("sampled_horizontal_distance",sampledDistance);
        out.addProperty("phase",phase.name().toLowerCase(java.util.Locale.ROOT));out.addProperty("landed",phase==ScopedStepDownPolicy.Phase.LANDED);
        out.addProperty("distance_accounting","callback-sampled-not-all-move-instrumentation");
        out.addProperty("input_neutral",neutral);out.addProperty("velocity_stopped_proven",false);
        out.addProperty("deadline_nano",Long.toString(deadline));
        out.addProperty("entity_guard_policy",ScopedEntityPolicy.POLICY);out.addProperty("entity_guard_checks",checks);
        out.addProperty("last_entity_check_tick",lastEntityTick);out.addProperty("last_entity_check_nano",Long.toString(lastEntityNano));
        out.addProperty("timing_contract",TIMING_CONTRACT);out.addProperty("last_entity_check_action_tick",sampleActionTick);
        out.addProperty("maximum_checked_population",maximumCheckedPopulation);return out;
    }
    static String rejection(RuntimeException failure) {
        return failure instanceof ClientActionRequest.Rejected && failure.getMessage()!=null
                ? failure.getMessage() : "step_down_check_failed";
    }
    private static void require(boolean condition,String reason){if(!condition)throw new ClientActionRequest.Rejected(409,reason);}
}
