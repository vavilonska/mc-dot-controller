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
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.GrassBlock;

/** A finite native-client corridor controller under ClientActions' sole input owner.
 * Never writes position, velocity, packets, keys, or another owner's input.
 */
final class ScopedFlatMovement {
    static final String PROFILE="movement-flat-observed-v2";
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
    final long sourceNano, sourceTick, deadline;
    final JsonObject footprint;
    private final ClientActionRequest request;
    private final float initialHealth;
    private final Pose admissionPose;
    private final ScopedMovementEntities admissionEntities;
    private long lastEntityTick,lastEntityNano;
    private int maximumCheckedPopulation;
    private long ownerRevision, sampleTick;
    private double sampleX,sampleZ,tickDistance,sampledDistance;
    private boolean activated, attempted;
    private int checks;

    ScopedFlatMovement(Minecraft mc, ClientActionRequest request, long sourceNano, long sourceTick) {
        this.request=request;this.sourceNano=sourceNano;this.sourceTick=sourceTick;
        player=mc.player;level=mc.level;server=mc.getSingleplayerServer();session=ClientActions.session();
        serverIdentity=IntegratedServerIdentity.current(server,CapabilityGuard.privateSingleplayer(mc));
        worldGeneration=WorldGeneration.current(level);playerUuid=player.getUUID().toString();navigationEpoch=NavigationPositionGuard.epoch();
        require(request.action().equals("follow_path") && request.timeoutMs()<=ScopedFlatPolicy.MAX_TIMEOUT_MS
                && ClientActionRequest.bool(request.original(),"capability_route",false)
                && !request.jump() && !request.sneak() && request.hotbarSlot()==-1
                && !ClientActionRequest.bool(request.original(),"sprint",false)
                && request.waypoints().stream().noneMatch(ClientActionRequest.Point::jump),"scoped_movement_request_outside_profile");
        // No other special route may borrow this profile's authority.
        require(!request.original().has("encounter_route_guard") && !request.original().has("coordination_step"),
                "scoped_movement_other_route_forbidden");
        try {bounds=ScopedFlatPolicy.route(player.getX(),player.getY(),player.getZ(),request.waypoints().stream()
                .map(p->new ScopedFlatPolicy.Point(p.x(),p.y(),p.z())).toList());}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        JsonObject origin=request.original().getAsJsonObject("expected_origin");
        require(origin!=null && Math.abs(origin.get("x").getAsDouble()-player.getX())<=.03
                && Math.abs(origin.get("y").getAsDouble()-player.getY())<=.03
                && Math.abs(origin.get("z").getAsDouble()-player.getZ())<=.03,"scoped_movement_origin_changed");
        initialHealth=player.getHealth();deadline=sourceNano+request.timeoutMs()*1_000_000L;
        sampleX=player.getX();sampleZ=player.getZ();sampleTick=sourceTick;
        admissionEntities=ScopedMovementEntities.capture(level,player,bounds,sourceTick);
        lastEntityTick=admissionEntities.frame.tick();lastEntityNano=admissionEntities.frame.nano();
        maximumCheckedPopulation=admissionEntities.frame.population();
        Pose pose=environment(mc,true);
        admissionPose=pose;
        footprint=terrain(mc);
        require(pose.equals(environment(mc,true)),"scoped_movement_facts_changed_after_hooks");
        assertRawFootprint();
        admissionEntities.assertUnchanged();
        fence(mc,pose,false);
    }

    void activate() {ownerRevision=ClientActions.ownershipRevision();activated=true;}
    JsonObject facts(){
        try {JsonObject out=footprint.deepCopy();out.add("entity_guard",admissionEntities.frame.json());return out;}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
    }
    void admissionRecheck(Minecraft mc) {
        Pose pose=environment(mc,true);
        require(footprint.equals(terrain(mc)),"scoped_movement_footprint_changed");
        require(pose.equals(environment(mc,true)),"scoped_movement_facts_changed_after_hooks");
        assertRawFootprint();
        admissionEntities.assertUnchanged();
        fence(mc,pose,false);
    }
    /** Runs after final generic inventory/menu facts; never performs shape/friction/attribute/slot hooks. */
    void admissionRawFence(Minecraft mc) {
        assertRawFootprint();
        admissionEntities.assertUnchanged();
        fence(mc,admissionPose,false);
    }
    /** Reads may call mod hooks. The final fence deliberately does no block/entity/attribute hooks. */
    void beforeEffect(Minecraft mc) {
        long began=System.nanoTime();
        ScopedMovementEntities entities=ScopedMovementEntities.capture(level,player,bounds,sourceTick);
        Pose pose=environment(mc,false);
        require(footprint.equals(terrain(mc)),"scoped_movement_footprint_changed");
        require(pose.equals(environment(mc,false)),"scoped_movement_facts_changed_after_hooks");
        assertRawFootprint();
        entities.assertUnchanged();
        require(System.nanoTime()-began>=0 && System.nanoTime()-began<=ScopedNativePreflight.MAX_NANOS,
                "scoped_movement_check_budget_exceeded");
        fence(mc,pose,true);
        account(pose);
        lastEntityTick=entities.frame.tick();lastEntityNano=entities.frame.nano();
        maximumCheckedPopulation=Math.max(maximumCheckedPopulation,entities.frame.population());
        checks++;
    }
    void markAttempted(){attempted=true;}
    private record Pose(double x,double y,double z,double vx,double vy,double vz,float health,float yaw,float pitch,long tick) { }
    private Pose environment(Minecraft mc,boolean initial) {
        require(mc.player==player && mc.level==level && mc.gameMode!=null && CapabilityGuard.privateSingleplayer(mc)
                && mc.gameMode.getPlayerMode()==GameType.SURVIVAL
                && level.dimension().location().toString().equals("minecraft:overworld"),"scoped_movement_private_overworld_survival_required");
        require(player.containerMenu==player.inventoryMenu && player.containerMenu.getClass()==InventoryMenu.class
                && mc.screen==null && player.containerMenu.getCarried().isEmpty() && !player.isUsingItem(),
                "scoped_movement_closed_inventory_required");
        require(player.isAlive() && !player.isSpectator() && !player.isPassenger() && !player.isSprinting()
                && !player.getAbilities().flying && !player.noPhysics && player.onGround()
                && !player.isInWater() && !player.isInLava() && !player.isInPowderSnow && !player.isOnFire()
                && !player.onClimbable() && player.getActiveEffects().isEmpty() && player.hurtTime==0
                && player.fallDistance==0 && !player.horizontalCollision,"scoped_movement_player_envelope_changed");
        double speed=player.getAttributeValue(Attributes.MOVEMENT_SPEED);
        var v=player.getDeltaMovement();var box=player.getBoundingBox();
        require(ScopedFlatPolicy.finite(speed,player.getSpeed(),v.x,v.y,v.z,player.getHealth()) && speed>=0
                && speed<=.10000001 && player.getSpeed()>=0 && player.getSpeed()<=.10000001F
                && v.horizontalDistance()<=(initial?.003:ScopedFlatPolicy.MAX_SPEED) && v.y<=0 && v.y>=-.09
                && box.getXsize()<=.600001 && box.getZsize()<=.600001 && box.getYsize()<=1.800001
                && player.getHealth()>=initialHealth && bounds.containsPose(player.getX(),player.getY(),player.getZ()),
                "scoped_movement_motion_or_health_changed");
        return new Pose(player.getX(),player.getY(),player.getZ(),v.x,v.y,v.z,player.getHealth(),player.getYRot(),player.getXRot(),level.getGameTime());
    }
    private JsonObject terrain(Minecraft mc) {
        JsonObject out=new JsonObject();
        out.addProperty("profile",PROFILE);out.addProperty("source","native-client-loaded-level");
        out.addProperty("min_x",bounds.minX());out.addProperty("max_x",bounds.maxX());
        out.addProperty("min_y",bounds.minY());out.addProperty("max_y",bounds.maxY());
        out.addProperty("min_z",bounds.minZ());out.addProperty("max_z",bounds.maxZ());
        out.addProperty("feet_y",bounds.feetY());out.addProperty("steps",bounds.steps());
        out.addProperty("halo",ScopedFlatPolicy.HALO);out.addProperty("expected_cells",bounds.cells());
        out.addProperty("all_loaded",true);
        out.addProperty("closed_inventory",true);out.addProperty("survival",true);out.addProperty("using_item",false);
        out.addProperty("maximum_horizontal_speed",ScopedFlatPolicy.MAX_SPEED);
        out.addProperty("maximum_tick_sampled_displacement",ScopedFlatPolicy.MAX_TICK_DISPLACEMENT);
        out.addProperty("deadline_nano",Long.toString(deadline));
        JsonArray cells=new JsonArray();
        for(int x=bounds.minX();x<=bounds.maxX();x++)for(int y=bounds.minY();y<=bounds.maxY();y++)for(int z=bounds.minZ();z<=bounds.maxZ();z++) {
            BlockPos pos=new BlockPos(x,y,z);
            require(level.hasChunkAt(pos),"scoped_movement_unknown_corridor_cell");
            var state=level.getBlockState(pos);String id=BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
            require(level.getFluidState(pos).isEmpty(),"scoped_movement_fluid_present");
            boolean floor=y==bounds.minY();float friction=0;
            if(floor) {
                var type=state.getBlock().getClass();
                require(FLOORS.contains(id) && (type==Block.class || type==GrassBlock.class)
                        && state.isCollisionShapeFullBlock(level,pos),"scoped_movement_floor_unsupported");
                friction=state.getFriction(level,pos,player);
                require(Float.isFinite(friction) && friction>=.5999999F && friction<=.6000001F,
                        "scoped_movement_special_friction");
            } else require((id.equals("minecraft:air") || id.equals("minecraft:cave_air"))
                    && state.isAir() && state.getCollisionShape(level,pos).isEmpty(),"scoped_movement_clearance_or_hazard_changed");
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
            require(level.hasChunkAt(pos),"scoped_movement_corridor_unloaded_after_hooks");
            var state=level.getBlockState(pos);
            require(BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString().equals(row.get("id").getAsString())
                    && state.toString().equals(row.get("state").getAsString()) && state.getFluidState().isEmpty(),
                    "scoped_movement_corridor_changed_after_hooks");
        }
    }
    /** Final hook-free field/identity/time fence, immediately preceding a direct view/input write. */
    private void fence(Minecraft mc,Pose p,boolean owned) {
        long now=System.nanoTime();var v=player.getDeltaMovement();
        require(mc.isSameThread() && mc.player==player && mc.level==level && mc.gameMode!=null
                && mc.getSingleplayerServer()==server && CapabilityGuard.privateSingleplayer(mc)
                && serverIdentity.equals(IntegratedServerIdentity.current(server,true))
                && worldGeneration.equals(WorldGeneration.current(level)) && player.getUUID().toString().equals(playerUuid)
                && NavigationPositionGuard.epoch()==navigationEpoch
                && ClientActions.session().equals(session)
                && now>=sourceNano && now<deadline && p.tick>=sourceTick && p.tick-sourceTick>=0 && p.tick-sourceTick<ScopedEntityPolicy.MAX_TICKS
                && level.getGameTime()==p.tick
                && mc.isWindowActive() && !mc.isPaused() && mc.screen==null
                && player.containerMenu==player.inventoryMenu && player.containerMenu.getCarried().isEmpty()
                && mc.gameMode.getPlayerMode()==GameType.SURVIVAL && player.isAlive() && !player.isSpectator()
                && !player.isPassenger() && !player.isSprinting() && !player.getAbilities().flying && !player.noPhysics
                && !player.isInWater() && !player.isInLava() && !player.isInPowderSnow && !player.isOnFire()
                && player.getActiveEffects().isEmpty() && player.fallDistance==0 && !player.isUsingItem()
                && player.getSpeed()>=0 && player.getSpeed()<=.10000001F && player.getBoundingBox().getXsize()<=.600001
                && player.getBoundingBox().getZsize()<=.600001 && player.getBoundingBox().getYsize()<=1.800001
                && player.getX()==p.x && player.getY()==p.y && player.getZ()==p.z
                && v.x==p.vx && v.y==p.vy && v.z==p.vz && player.getHealth()==p.health && player.getYRot()==p.yaw && player.getXRot()==p.pitch
                && player.hurtTime==0 && player.onGround() && !player.horizontalCollision
                && !keysDown(mc) && !BridgeServer.hasHeldInputs()
                && (owned ? activated && ClientActions.ownsScopedMovement(this)
                    && ClientActions.ownershipRevision()==ownerRevision : !ClientActions.ownsInput()),
                "scoped_movement_final_boundary_changed");
    }
    private void account(Pose p) {
        require(p.tick>=sampleTick && p.tick-sampleTick>=0 && p.tick-sampleTick<=1,"scoped_movement_tick_gap");
        if(p.tick!=sampleTick){tickDistance=0;sampleTick=p.tick;}
        double distance=Math.hypot(p.x-sampleX,p.z-sampleZ);
        tickDistance+=distance;sampledDistance+=distance;sampleX=p.x;sampleZ=p.z;
        require(tickDistance<=ScopedFlatPolicy.MAX_TICK_DISPLACEMENT
                && sampledDistance<=bounds.steps()+1,"scoped_movement_sampled_displacement_exceeded");
    }
    static boolean keysDown(Minecraft mc){return mc.options.keyUp.isDown() || mc.options.keyDown.isDown()
            || mc.options.keyLeft.isDown() || mc.options.keyRight.isDown() || mc.options.keyJump.isDown()
            || mc.options.keySprint.isDown() || mc.options.keyShift.isDown() || mc.options.keyAttack.isDown()
            || mc.options.keyUse.isDown();}
    static boolean neutral(Input input){return input==null || input.forwardImpulse==0 && input.leftImpulse==0
            && !input.up && !input.down && !input.left && !input.right && !input.jumping && !input.shiftKeyDown;}
    JsonObject terminal(boolean neutral) {
        JsonObject out=new JsonObject();out.addProperty("profile",PROFILE);out.addProperty("effect_attempted",attempted);
        out.addProperty("local_checks",checks);out.addProperty("sampled_distance",sampledDistance);
        out.addProperty("distance_accounting","callback-sampled-not-all-move-instrumentation");
        out.addProperty("input_neutral",neutral);out.addProperty("velocity_stopped_proven",false);
        out.addProperty("deadline_nano",Long.toString(deadline));
        out.addProperty("entity_guard_policy",ScopedEntityPolicy.POLICY);out.addProperty("entity_guard_checks",checks);
        out.addProperty("last_entity_check_tick",lastEntityTick);out.addProperty("last_entity_check_nano",Long.toString(lastEntityNano));
        out.addProperty("maximum_checked_population",maximumCheckedPopulation);return out;
    }
    static String rejection(RuntimeException failure) {
        return failure instanceof ClientActionRequest.Rejected && failure.getMessage()!=null
                ? failure.getMessage() : "scoped_movement_check_failed";
    }
    private static void require(boolean condition,String reason){if(!condition)throw new ClientActionRequest.Rejected(409,reason);}
}
