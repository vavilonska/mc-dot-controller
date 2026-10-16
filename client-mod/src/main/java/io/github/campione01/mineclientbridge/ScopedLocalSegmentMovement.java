package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.Set;
import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import net.minecraft.world.level.block.LeavesBlock;
import net.minecraft.world.level.block.SnowyDirtBlock;
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

/** One dry full-cube flat/up/down cardinal segment under ClientActions' sole input owner.
 * Never writes position, velocity, packets, keys, or another owner's input.
 */
final class ScopedLocalSegmentMovement {
    static final String PROFILE="movement-local-segment-observed-v1";
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
    final ScopedLocalSegmentPolicy.Bounds descent;
    private ScopedLocalSegmentPolicy.Phase phase=ScopedLocalSegmentPolicy.Phase.GROUND;
    private double lastY;
    private int airborneSince=-1, jumpPulses=0, jumpPulseTick=-1, neutralTick=-1;
    private int settledTick=-1, settledSamples=0;
    private double pulseX,pulseY,pulseZ,pulseVx,pulseVz;
    final long sourceNano, sourceTick, deadline;
    final JsonObject footprint;
    private final Terrain admissionTerrain;
    private record RawCell(BlockPos pos,Object state,Block block,Map<?,?> properties,JsonObject row) { }
    private record Terrain(JsonObject json,List<RawCell> raw) { }
    private final ClientActionRequest request;
    private final float initialHealth;
    private final int initialFood;
    private final AttributeMap attributeMap;
    private final AttributeInstance gravityAttribute, movementAttribute, jumpAttribute;
    private final Pose admissionPose;
    private final Entities admissionEntities;
    private final boolean spatial, spatialStop, bees, requireStopOnly;
    private final String profile, selectedUuid;
    private long lastEntityTick,lastEntityNano;
    private int maximumCheckedPopulation;
    private long ownerRevision;
    private ActionRegistry.Entry actionEntry;
    private int sampleActionTick=0;
    private double sampleX,sampleY,sampleZ,tickDistance,tickDownDistance,sampledDistance;
    private boolean activated, attempted, preEffectThreatRace;
    private JsonObject validatedThreatStop;
    private int checks;

    ScopedLocalSegmentMovement(Minecraft mc, ClientActionRequest request, long sourceNano, long sourceTick) {
        this(mc,request,sourceNano,sourceTick,false);
    }
    ScopedLocalSegmentMovement(Minecraft mc, ClientActionRequest request, long sourceNano, long sourceTick,boolean spatial) {
        this(mc,request,sourceNano,sourceTick,spatial,false);
    }
    ScopedLocalSegmentMovement(Minecraft mc,ClientActionRequest request,long sourceNano,long sourceTick,boolean spatial,boolean spatialStop){
        this(mc,request,sourceNano,sourceTick,spatial,spatialStop,false);
    }
    ScopedLocalSegmentMovement(Minecraft mc,ClientActionRequest request,long sourceNano,long sourceTick,boolean spatial,boolean spatialStop,boolean bees){
        require(!bees||spatialStop,"local_segment_profile_conflict");
        this.bees=bees;
        require(!spatial||!spatialStop,"local_segment_profile_conflict");
        this.request=request;this.sourceNano=sourceNano;this.sourceTick=sourceTick;this.spatial=spatial;this.spatialStop=spatialStop;
        profile=spatial?ScopedRouteThreatPolicy.PROFILE:spatialStop?(bees?ScopedRouteStopPolicy.PROFILE_V2:ScopedRouteStopPolicy.PROFILE):PROFILE;
        validateIntent(request.original(),spatial);
        requireStopOnly=spatial&&request.original().has("route_stop_only");
        selectedUuid=spatial?request.original().getAsJsonObject("route_threat_guard").get("target_uuid").getAsString():null;
        require(MovementBudget.snapshot().get("status").getAsString().equals("unarmed"),"local_segment_movement_budget_must_be_unarmed");
        player=mc.player;level=mc.level;
        require(player.getClass()==LocalPlayer.class,"local_segment_exact_player_class_required");
        attributeMap=player.getAttributes();gravityAttribute=player.getAttribute(Attributes.GRAVITY);movementAttribute=player.getAttribute(Attributes.MOVEMENT_SPEED);jumpAttribute=player.getAttribute(Attributes.JUMP_STRENGTH);
        require(attributeMap!=null && attributeMap.getClass()==AttributeMap.class
                && gravityAttribute!=null && gravityAttribute.getClass()==AttributeInstance.class
                && movementAttribute!=null && movementAttribute.getClass()==AttributeInstance.class
                && jumpAttribute!=null && jumpAttribute.getClass()==AttributeInstance.class,"local_segment_exact_attribute_readers_required");server=mc.getSingleplayerServer();session=ClientActions.session();
        serverIdentity=IntegratedServerIdentity.current(server,CapabilityGuard.privateSingleplayer(mc));
        worldGeneration=WorldGeneration.current(level);playerUuid=player.getUUID().toString();navigationEpoch=NavigationPositionGuard.epoch();
        require(!spatial||!selectedUuid.equals(playerUuid),"route_spatial_self_target_forbidden");
        require(request.action().equals("follow_path") && request.timeoutMs()<=ScopedLocalSegmentPolicy.MAX_TIMEOUT_MS
                && ClientActionRequest.bool(request.original(),"capability_route",false)
                && !request.jump() && !request.sneak() && request.hotbarSlot()==-1
                && !ClientActionRequest.bool(request.original(),"sprint",false)
                && request.waypoints().stream().noneMatch(ClientActionRequest.Point::jump),"local_segment_request_outside_profile");
        // No other special route may borrow this profile's authority.
        require(!request.original().has("encounter_route_guard") && !request.original().has("coordination_step"),
                "local_segment_other_route_forbidden");
        try {descent=ScopedLocalSegmentPolicy.route(player.getX(),player.getY(),player.getZ(),request.waypoints().stream()
                .map(p->new ScopedLocalSegmentPolicy.Point(p.x(),p.y(),p.z())).toList()); bounds=descent.prism();}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        JsonObject origin=request.original().getAsJsonObject("expected_origin");
        require(origin!=null && Math.abs(origin.get("x").getAsDouble()-player.getX())<=.03
                && Math.abs(origin.get("y").getAsDouble()-player.getY())<=.03
                && Math.abs(origin.get("z").getAsDouble()-player.getZ())<=.03,"local_segment_origin_changed");
        initialHealth=player.getHealth();initialFood=player.getFoodData().getFoodLevel();deadline=sourceNano+request.timeoutMs()*1_000_000L;
        sampleX=player.getX();sampleY=player.getY();sampleZ=player.getZ();lastY=player.getY();
        // Admission has no Entry yet; its action age is explicitly zero.
        admissionEntities=captureEntities(mc,0,true);
        require(!requireStopOnly||admissionEntities.attacker(),"route_spatial_stop_only_attacker_required");
        // An already observed attacker must fit the terminal proof before registration.
        // This is a detached size preview only; no proof is published and no effect runs.
        if(admissionEntities.attacker())admissionEntities.stop(true);
        lastEntityTick=admissionEntities.tick();lastEntityNano=admissionEntities.nano();
        maximumCheckedPopulation=admissionEntities.population();
        Pose pose=environment(mc,true);
        admissionPose=pose;
        admissionTerrain=terrain(mc);footprint=admissionTerrain.json();
        require(pose.equals(environment(mc,true)),"local_segment_facts_changed_after_hooks");
        assertRawFootprint(admissionTerrain);
        admissionEntities.assertUnchanged();
        fence(mc,pose,false,0);
        admissionEntities.finalFence();
        stopOnlyAdmissionFence(mc,pose);
    }

    /** Exactly one reader policy is attached to this profile. Legacy profiles never enter the spatial branch. */
    private record Entities(ScopedMovementEntities legacy,ScopedRouteThreatEntities spatial,ScopedRouteStopEntities stop) {
        JsonObject json(){return stop!=null?stop.frame.json():spatial==null?legacy.frame.json():spatial.frame.json();}
        long tick(){return stop!=null?stop.frame.tick():spatial==null?legacy.frame.tick():spatial.frame.tick();}
        long nano(){return stop!=null?stop.frame.nano():spatial==null?legacy.frame.nano():spatial.frame.nano();}
        int population(){return stop!=null?stop.frame.population():spatial==null?legacy.frame.population():spatial.frame.population();}
        void assertUnchanged(){if(stop!=null)stop.assertUnchanged();else if(spatial==null)legacy.assertUnchanged();else spatial.assertUnchanged();}
        void finalFence(){if(stop!=null)stop.finalFence();else if(spatial!=null)spatial.finalFence();}
        boolean attacker(){return spatial!=null&&spatial.frame.attacker()!=null;}
        JsonObject stop(boolean preempted){
            try{return spatial.frame.stop(preempted);}
            catch(IllegalArgumentException invalid){
                // Preserve this bounded refusal only. Other unchecked failures still
                // use the generic check-failure path and cannot gain stop authority.
                if("route_spatial_stop_evidence_too_large".equals(invalid.getMessage()))
                    throw new ClientActionRequest.Rejected(409,invalid.getMessage());
                throw invalid;
            }
        }
        boolean sameAttacker(Entities other){
            if(!attacker()||!other.attacker())return false;
            var a=spatial.frame.attacker();var b=other.spatial.frame.attacker();
            if(a.id()!=b.id()||!a.uuid().equals(b.uuid())||!a.type().equals(b.type())||!a.className().equals(b.className()))return false;
            Object before=null,now=null;
            for(var entry:spatial.entries)if(entry.row()==a)before=entry.identity();
            for(var entry:other.spatial.entries)if(entry.row()==b)now=entry.identity();
            return before!=null&&before==now;
        }
    }
    private Entities captureEntities(Minecraft mc,int ticks,boolean allowProjectedAttacker){
        return spatial?new Entities(null,ScopedRouteThreatEntities.capture(mc,descent,ticks,selectedUuid,allowProjectedAttacker),null)
            :spatialStop?new Entities(null,null,ScopedRouteStopEntities.capture(mc,descent,ticks,bees))
            :new Entities(ScopedMovementEntities.capture(level,player,bounds,ticks),null,null);
    }
    boolean admissionThreat(){return spatial&&admissionEntities.attacker();}
    boolean spatialThreatProfile(){return spatial;}
    boolean spatialStopProfile(){return spatialStop;}
    private boolean knownOutcome(ActionRegistry.Entry entry){
        return spatial&&entry==actionEntry&&!entry.result.has("unknown_outcome")&&!entry.result.has("motion_gate_rejected")
            &&!entry.result.has("requires_handoff")&&!entry.result.has("effect_outcome");
    }
    boolean hasValidatedThreatStop(ActionRegistry.Entry entry){
        return knownOutcome(entry)&&validatedThreatStop!=null&&validatedThreatStop.equals(entry.result.get("route_threat_stop"));
    }
    boolean hasPreEffectThreatRace(ActionRegistry.Entry entry){
        return knownOutcome(entry)&&preEffectThreatRace&&!attempted&&validatedThreatStop==null&&!entry.result.has("route_threat_stop");
    }

    void activate(ActionRegistry.Entry entry) {
        require(!activated && actionEntry==null && entry!=null && entry.running() && entry.ticks==0
                && entry.request.id().equals(request.id()) && entry.request.action().equals(request.action())
                && entry.request.timeoutMs()==request.timeoutMs() && ClientActions.ownsScopedLocalSegment(this,entry),
                "local_segment_activation_changed");
        actionEntry=entry;ownerRevision=ClientActions.ownershipRevision();activated=true;
    }
    /** Raw native Entry state only; no supplier, world-clock age, or per-effect increment. */
    private int actionTicks() {
        require(activated && actionEntry!=null && ClientActions.ownsScopedLocalSegment(this,actionEntry)
                && ClientActions.ownershipRevision()==ownerRevision,"local_segment_action_owner_changed");
        int ticks=actionEntry.ticks;
        require(ticks>=0 && ticks<ScopedEntityPolicy.MAX_TICKS,"local_segment_entity_tick_budget");
        require(ticks>=sampleActionTick && ticks-sampleActionTick<=1,"local_segment_tick_gap");
        return ticks;
    }
    void admissionEvidenceFence(){if(bees)admissionEntities.finalFence();}
    JsonObject facts(){
        try {JsonObject out=footprint.deepCopy();out.add("entity_guard",admissionEntities.json());return out;}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
    }
    void admissionRecheck(Minecraft mc) {
        Pose pose=environment(mc,true);
        require(footprint.equals(terrain(mc).json()),"local_segment_footprint_changed");
        require(pose.equals(environment(mc,true)),"local_segment_facts_changed_after_hooks");
        assertRawFootprint(admissionTerrain);
        admissionEntities.assertUnchanged();
        fence(mc,pose,false,0);
        admissionEntities.finalFence();
        stopOnlyAdmissionFence(mc,pose);
    }
    /** Runs after final generic inventory/menu facts; never performs shape/friction/attribute/slot hooks. */
    void admissionRawFence(Minecraft mc) {
        assertRawFootprint(admissionTerrain);
        admissionEntities.assertUnchanged();
        fence(mc,admissionPose,false,0);
        admissionEntities.finalFence();
        stopOnlyAdmissionFence(mc,admissionPose);
    }
    /** The explicit fast path must still have the same fresh actual attacker before registration.
     * Keep the original witness immutable. A separate current batch is validated, never substituted into it.
     */
    private void stopOnlyAdmissionFence(Minecraft mc,Pose pose){
        if(!requireStopOnly)return;
        Entities current=captureEntities(mc,0,true);
        require(admissionEntities.sameAttacker(current),"route_spatial_stop_only_attacker_changed");
        current.stop(true);
        current.assertUnchanged();
        admissionEntities.assertUnchanged();
        assertRawFootprint(admissionTerrain);
        fence(mc,pose,false,0);
        current.finalFence();admissionEntities.finalFence();
    }
    /** Reads may call mod hooks. The final fence deliberately does no block/entity/attribute hooks. */
    void beforeEffect(Minecraft mc) { try{check(mc,false);}catch(RuntimeException failure){recordFailure(failure);throw failure;} }
    private void check(Minecraft mc,boolean motionBoundary) {
        long began=System.nanoTime();
        int actionTicks=actionTicks();
        Entities entities=captureEntities(mc,actionTicks,admissionThreat()&&!attempted&&actionTicks==0);
        Pose pose=environment(mc,false,motionBoundary);
        Terrain current=terrain(mc);
        requireEquivalent(current);
        require(pose.equals(environment(mc,false,motionBoundary)),"local_segment_facts_changed_after_hooks");
        assertRawFootprint(spatialStop?current:admissionTerrain);
        entities.assertUnchanged();
        require(System.nanoTime()-began>=0 && System.nanoTime()-began<=ScopedNativePreflight.MAX_NANOS,
                "local_segment_check_budget_exceeded");
        fence(mc,pose,true,actionTicks);
        entities.finalFence();
        boolean immediate=admissionThreat()&&!attempted&&actionTicks==0;
        if(immediate)require(pose.equals(admissionPose),"route_spatial_stop_pose_changed");
        else if(!jumpTransition(pose,motionBoundary))account(pose,actionTicks);
        // Counts completed read-only validation, not effects. Immediate stop reports 1 check and 0 attempted effects.
        checks++;
        lastEntityTick=entities.tick();lastEntityNano=entities.nano();
        maximumCheckedPopulation=Math.max(maximumCheckedPopulation,entities.population());
        if(entities.attacker()) {
            require(!motionBoundary,"route_spatial_motion_boundary_threat_unknown");
            if(!admissionThreat()&&!attempted){preEffectThreatRace=true;throw new ClientActionRequest.Rejected(409,"route_spatial_pre_effect_attacker_changed");}
            boolean preempted=admissionThreat()&&!attempted&&actionTicks==0&&sampledDistance==0&&jumpPulses==0;
            require(!preempted||admissionEntities.sameAttacker(entities),"route_spatial_admission_attacker_identity_changed");
            // Build the bounded proof before adding it: a failed/oversized proof is never a known threat terminal.
            JsonObject stop=entities.stop(preempted);
            validatedThreatStop=stop.deepCopy();
            actionEntry.result.add("route_threat_stop",stop);
            throw new ClientActionRequest.Rejected(409,"capability_threat_observed");
        }
        require(!admissionThreat()||attempted,"route_spatial_admission_attacker_changed");
    }
    void recordFailure(RuntimeException failure){
        if(spatialStop&&actionEntry!=null&&actionEntry.running()&&ClientActions.ownsScopedLocalSegment(this,actionEntry)
                &&failure instanceof ClientActionRequest.Rejected rejected&&rejected.routeEntityRejection!=null)
            actionEntry.result.add("route_entity_rejection",rejected.routeEntityRejection.deepCopy());
        if(spatialStop&&actionEntry!=null&&actionEntry.running()&&ClientActions.ownsScopedLocalSegment(this,actionEntry)
                &&ClientActions.ownershipRevision()==ownerRevision
                &&failure instanceof ClientActionRequest.Rejected rejected&&rejected.routeTerrainRejection!=null)
            actionEntry.result.add("route_terrain_rejection",rejected.routeTerrainRejection.deepCopy());
    }
    void markAttempted(){attempted=true;}
    void motionUnknown(String reason){
        if(actionEntry!=null){
            actionEntry.result.addProperty("motion_gate_rejected",true);
            actionEntry.result.addProperty("unknown_outcome",true);
            actionEntry.result.addProperty("motion_gate_reason",reason);
        }
    }
    private record Pose(double x,double y,double z,double vx,double vy,double vz,float health,float yaw,float pitch,long tick,boolean grounded,float fall) { }
    private Pose environment(Minecraft mc,boolean initial) {return environment(mc,initial,false);}
    private Pose environment(Minecraft mc,boolean initial,boolean motionBoundary) {
        require(mc.player==player && mc.level==level && mc.gameMode!=null && CapabilityGuard.privateSingleplayer(mc)
                && mc.gameMode.getPlayerMode()==GameType.SURVIVAL
                && level.dimension().location().toString().equals("minecraft:overworld"),"local_segment_private_overworld_survival_required");
        require(player.containerMenu==player.inventoryMenu && player.containerMenu.getClass()==InventoryMenu.class
                && mc.screen==null && player.containerMenu.getCarried().isEmpty() && !player.isUsingItem(),
                "local_segment_closed_inventory_required");
        require(player.isAlive() && !player.isSpectator() && !player.isPassenger() && !player.isSprinting()
                && !player.getAbilities().flying && !player.getAbilities().mayfly && !player.noPhysics
                && !player.isFallFlying() && !player.isSwimming() && !player.isCrouching() && !player.isNoGravity()
                && !player.isAutoJumpEnabled() && !mc.options.autoJump().get() && player.autoJumpTime==0
                && !player.isInWater() && !player.isInLava() && !player.isInPowderSnow && !player.isOnFire()
                && !player.onClimbable() && player.getActiveEffects().isEmpty() && player.hurtTime==0
                && (!initial || player.onGround() && player.fallDistance==0) && !player.horizontalCollision,"local_segment_player_envelope_changed");
        double speed=player.getAttributeValue(Attributes.MOVEMENT_SPEED);
        double gravity=player.getAttributeValue(Attributes.GRAVITY);
        double jumpStrength=player.getAttributeValue(Attributes.JUMP_STRENGTH);
        require(Double.isFinite(jumpStrength)&&Math.abs(jumpStrength-(double).42F)<=1e-9,"local_segment_ordinary_jump_required");
        require(Double.isFinite(gravity) && Math.abs(gravity-.08)<=1e-9,"local_segment_ordinary_gravity_required");
        var v=player.getDeltaMovement();var box=player.getBoundingBox();
        require(ScopedFlatPolicy.finite(speed,player.getSpeed(),v.x,v.y,v.z,player.getHealth()) && speed>=0
                && speed<=.10000001 && player.getSpeed()>=0 && player.getSpeed()<=.10000001F
                && v.horizontalDistance()<=(initial?.003:ScopedLocalSegmentPolicy.MAX_SPEED) && Math.abs(v.y)<=ScopedLocalSegmentPolicy.MAX_VERTICAL_SPEED
                && (!initial || v.y>=-.09 && v.y<=0)
                && box.getXsize()>=.599999 && box.getXsize()<=.600001 && box.getZsize()>=.599999 && box.getZsize()<=.600001
                && box.getYsize()>=1.799999 && box.getYsize()<=1.800001
                && initialFood>=6 && initialFood<=20 && player.getFoodData().getFoodLevel()==initialFood
                && Math.abs(box.minX-(player.getX()-.3))<=1e-6 && Math.abs(box.minZ-(player.getZ()-.3))<=1e-6
                && Math.abs(box.minY-player.getY())<=1e-6
                && player.getHealth()>=initialHealth && descent.contains(player.getX(),player.getY(),player.getZ()),
                "local_segment_motion_or_health_changed");
        Pose current=new Pose(player.getX(),player.getY(),player.getZ(),v.x,v.y,v.z,player.getHealth(),player.getYRot(),player.getXRot(),level.getGameTime(),player.onGround(),player.fallDistance);
        try {if(!jumpTransition(current,motionBoundary))ScopedLocalSegmentPolicy.phase(descent,phase,lastY,player.getY(),v.y,player.fallDistance,player.onGround(),jumpPulses==1);}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        return new Pose(player.getX(),player.getY(),player.getZ(),v.x,v.y,v.z,player.getHealth(),player.getYRot(),player.getXRot(),level.getGameTime(),player.onGround(),player.fallDistance);
    }
    private Terrain terrain(Minecraft mc) {
        JsonObject out=new JsonObject();
        out.addProperty("profile",profile);out.addProperty("source","native-client-loaded-level");
        out.addProperty("min_x",bounds.minX());out.addProperty("max_x",bounds.maxX());
        out.addProperty("min_y",bounds.minY());out.addProperty("max_y",bounds.maxY());
        out.addProperty("min_z",bounds.minZ());out.addProperty("max_z",bounds.maxZ());
        out.addProperty("start_x",descent.startX());out.addProperty("start_y",descent.startY());out.addProperty("start_z",descent.startZ());
        out.addProperty("end_x",descent.endX());out.addProperty("end_y",descent.endY());out.addProperty("end_z",descent.endZ());out.addProperty("steps",1);
        out.addProperty("halo",ScopedLocalSegmentPolicy.HALO);out.addProperty("expected_cells",bounds.cells());
        out.addProperty("all_loaded",true);out.addProperty("movement_budget_status","unarmed");out.addProperty("source_food_level",initialFood);
        out.addProperty("closed_inventory",true);out.addProperty("survival",true);out.addProperty("using_item",false);
        out.addProperty("maximum_horizontal_speed",ScopedLocalSegmentPolicy.MAX_SPEED);
        out.addProperty("maximum_tick_sampled_displacement",ScopedLocalSegmentPolicy.MAX_TICK_DISPLACEMENT);
        out.addProperty("maximum_vertical_speed",ScopedLocalSegmentPolicy.MAX_VERTICAL_SPEED);
        out.addProperty("maximum_fall_distance",ScopedLocalSegmentPolicy.MAX_FALL_DISTANCE);
        out.addProperty("maximum_rise",ScopedLocalSegmentPolicy.MAX_RISE);out.addProperty("step_dy",descent.dy());
        out.addProperty("source_center_tolerance",ScopedLocalSegmentPolicy.SOURCE_CENTER_TOLERANCE);
        out.addProperty("arrival_radius",ScopedLocalSegmentPolicy.ARRIVAL_RADIUS);
        out.addProperty("maximum_airborne_ticks",ScopedLocalSegmentPolicy.MAX_AIRBORNE_TICKS);
        out.addProperty("deadline_nano",Long.toString(deadline));
        JsonArray cells=new JsonArray();List<RawCell> raw=new ArrayList<>();
        for(int x=bounds.minX();x<=bounds.maxX();x++)for(int y=bounds.minY();y<=bounds.maxY();y++)for(int z=bounds.minZ();z<=bounds.maxZ();z++) {
            BlockPos pos=new BlockPos(x,y,z);var role=descent.role(x,y,z);
            RouteTerrainDiagnostics diagnostic=diagnostic(cells.size(),"capture");
            try {
                boolean loaded=level.hasChunkAt(pos);if(diagnostic!=null)diagnostic.loaded(loaded);
                require(loaded,"local_segment_unknown_corridor_cell");
                var state=level.getBlockState(pos);Block block=state.getBlock();String id=BuiltInRegistries.BLOCK.getKey(block).toString();
                String stateText=state.toString();if(diagnostic!=null)diagnostic.state(id,stateText);
                boolean dry=level.getFluidState(pos).isEmpty();if(diagnostic!=null)diagnostic.flag("fluid_empty",dry);
                require(dry,"local_segment_fluid_present");
                boolean floor=role==ScopedLocalSegmentPolicy.Role.SUPPORT
                    || role==ScopedLocalSegmentPolicy.Role.CONTEXT && !state.isAir();float friction=0;
                if(floor) {
                    require(allowedSolid(id,block.getClass(),role),"local_segment_floor_unsupported");
                    boolean full=state.isCollisionShapeFullBlock(level,pos);if(diagnostic!=null){diagnostic.flag("full_cube",full);if(full)diagnostic.flag("collision_empty",false);}
                    require(full,"local_segment_floor_unsupported");
                    friction=state.getFriction(level,pos,player);if(diagnostic!=null)diagnostic.friction(friction);
                    require(Float.isFinite(friction) && friction>=.5999999F && friction<=.6000001F,
                            "local_segment_special_friction");
                } else {
                    require((id.equals("minecraft:air") || id.equals("minecraft:cave_air")) && state.isAir(),"local_segment_clearance_or_hazard_changed");
                    boolean empty=state.getCollisionShape(level,pos).isEmpty();if(diagnostic!=null){diagnostic.flag("collision_empty",empty);if(empty)diagnostic.flag("full_cube",false);}
                    require(empty,"local_segment_clearance_or_hazard_changed");
                    if(diagnostic!=null)diagnostic.friction(0);
                }
                JsonObject cell=new JsonObject();cell.addProperty("x",x);cell.addProperty("y",y);cell.addProperty("z",z);
                cell.addProperty("id",id);cell.addProperty("state",stateText);cell.addProperty("fluid","minecraft:empty");
                cell.addProperty("role",role.name().toLowerCase(java.util.Locale.ROOT));cell.addProperty("full_cube",floor);cell.addProperty("friction",friction);cells.add(cell);
                // Property keys are native singleton identities; copying prevents a later reader from changing the captured values.
                raw.add(new RawCell(pos,state,block,spatialStop?Map.copyOf(state.getValues()):Map.of(),cell));
            } catch(ClientActionRequest.Rejected failure){throw diagnostic==null?failure:diagnostic.attach(failure);}
        }
        out.add("cells",cells);return new Terrain(out,List.copyOf(raw));
    }
    private RouteTerrainDiagnostics diagnostic(int index,String phase){
        return spatialStop&&activated?new RouteTerrainDiagnostics(footprint.getAsJsonArray("cells").get(index).getAsJsonObject(),phase,profile):null;
    }
    private void requireEquivalent(Terrain current){
        if(!spatialStop){require(footprint.equals(current.json()),"local_segment_footprint_changed");return;}
        require(current.raw().size()==admissionTerrain.raw().size(),"local_segment_footprint_changed");
        for(int i=0;i<current.raw().size();i++){
            RawCell before=admissionTerrain.raw().get(i),now=current.raw().get(i);
            if(equivalent(before,now))continue;
            RouteTerrainDiagnostics diagnostic=diagnostic(i,"equivalence");diagnostic.validated(now.row());
            throw diagnostic.attach(new ClientActionRequest.Rejected(409,"local_segment_footprint_changed"));
        }
    }
    /** Only a registered default-stop continuation may use the audited leaves or context-soil equivalence.
     * Every current cell already passed all physics checks. Unknown properties, IDs and classes stay exact.
     */
    private static boolean equivalent(RawCell before,RawCell now){
        if(before.block()!=now.block())return soilEquivalent(before,now);
        if(before.row().equals(now.row()))return before.properties().equals(now.properties());
        String id=before.row().get("id").getAsString();
        if(before.block().getClass()!=LeavesBlock.class || !(id.equals("minecraft:oak_leaves")||id.equals("minecraft:birch_leaves"))
                || !before.row().get("role").getAsString().equals("context"))return false;
        JsonObject a=before.row().deepCopy(),b=now.row().deepCopy();a.remove("state");b.remove("state");
        if(!a.equals(b)||!before.properties().keySet().equals(now.properties().keySet()))return false;
        boolean auditedChange=false;
        for(var property:before.properties().keySet())if(!java.util.Objects.equals(before.properties().get(property),now.properties().get(property))){
            if(property!=LeavesBlock.DISTANCE&&property!=LeavesBlock.PERSISTENT)return false;
            auditedChange=true;
        }
        // A textual change with no actual audited native property change is never ignored.
        return auditedChange;
    }
    /** The only approved ID-changing family: exact, non-snowy grass and ordinary dirt in context.
     * Natural grass death/spread changes no currently validated movement surface; support and clearance remain exact.
     */
    private static boolean soilEquivalent(RawCell before,RawCell now){
        if(!before.row().get("role").getAsString().equals("context")||!now.row().get("role").getAsString().equals("context")
                ||!((grass(before)&&dirt(now))||(dirt(before)&&grass(now))))return false;
        JsonObject a=before.row().deepCopy(),b=now.row().deepCopy();a.remove("id");a.remove("state");b.remove("id");b.remove("state");
        return a.equals(b);
    }
    private static boolean grass(RawCell cell){
        return cell.block().getClass()==GrassBlock.class&&cell.row().get("id").getAsString().equals("minecraft:grass_block")
            &&cell.properties().size()==1&&cell.properties().keySet().iterator().next()==SnowyDirtBlock.SNOWY
            &&Boolean.FALSE.equals(cell.properties().get(SnowyDirtBlock.SNOWY));
    }
    private static boolean dirt(RawCell cell){return cell.block().getClass()==Block.class
        &&cell.row().get("id").getAsString().equals("minecraft:dirt")&&cell.properties().isEmpty();}
    static boolean allowedSolid(String id,Class<?> type,ScopedLocalSegmentPolicy.Role role){
        if(role==ScopedLocalSegmentPolicy.Role.CLEAR)return false;
        if(FLOORS.contains(id)&&(type==Block.class||type==GrassBlock.class))return true;
        return role==ScopedLocalSegmentPolicy.Role.CONTEXT
            && (id.equals("minecraft:barrel")&&type==net.minecraft.world.level.block.BarrelBlock.class
                || id.equals("minecraft:furnace")&&type==net.minecraft.world.level.block.FurnaceBlock.class
                || (id.equals("minecraft:oak_leaves")||id.equals("minecraft:birch_leaves"))
                    &&type==net.minecraft.world.level.block.LeavesBlock.class);
    }
    /** No shape, friction, attribute, permission or ray hooks after this point. */
    private void assertRawFootprint(Terrain captured) {
        for(int i=0;i<captured.raw().size();i++) {
            RawCell raw=captured.raw().get(i);var row=raw.row();BlockPos pos=raw.pos();
            RouteTerrainDiagnostics diagnostic=diagnostic(i,"raw_fence");
            try {
                boolean loaded=level.hasChunkAt(pos);if(diagnostic!=null)diagnostic.loaded(loaded);
                require(loaded,"local_segment_corridor_unloaded_after_hooks");
                var state=level.getBlockState(pos);String id=BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();String stateText=state.toString();
                if(diagnostic!=null)diagnostic.state(id,stateText);
                boolean dry=state.getFluidState().isEmpty();if(diagnostic!=null)diagnostic.flag("fluid_empty",dry);
                require((!spatialStop||state==raw.state()) && id.equals(row.get("id").getAsString())
                        && stateText.equals(row.get("state").getAsString()) && dry,
                        "local_segment_corridor_changed_after_hooks");
            } catch(ClientActionRequest.Rejected failure){throw diagnostic==null?failure:diagnostic.attach(failure);}
        }
    }
    /** Final hook-free field/identity/time fence, immediately preceding a direct view/input write. */
    private void fence(Minecraft mc,Pose p,boolean owned,int actionTicks) {
        // Exact vanilla AttributeMap/AttributeInstance readers bind base values and absence of modifiers.
        // No getAttributeValue/calculateValue callback is used at this final boundary.
        require(player.getAttributes()==attributeMap && player.getAttribute(Attributes.GRAVITY)==gravityAttribute
                && player.getAttribute(Attributes.MOVEMENT_SPEED)==movementAttribute
                && player.getAttribute(Attributes.JUMP_STRENGTH)==jumpAttribute
                && Math.abs(jumpAttribute.getBaseValue()-(double).42F)<=1e-9 && jumpAttribute.getModifiers().isEmpty()
                && Math.abs(gravityAttribute.getBaseValue()-.08)<=1e-9 && gravityAttribute.getModifiers().isEmpty()
                && movementAttribute.getBaseValue()>=0 && movementAttribute.getBaseValue()<=.10000001
                && movementAttribute.getModifiers().isEmpty(),"local_segment_attribute_binding_changed_after_hooks");
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
                && (owned ? activated && actionEntry!=null && ClientActions.ownsScopedLocalSegment(this,actionEntry)
                    && ClientActions.ownershipRevision()==ownerRevision
                    // Re-read the trusted Entry after every potentially reentrant fact hook.
                    && actionEntry.ticks==actionTicks
                    : !activated && actionEntry==null && actionTicks==0 && !ClientActions.ownsInput()),
                "local_segment_final_boundary_changed");
    }
    private void account(Pose p,int actionTicks) {
        require(actionTicks>=sampleActionTick && actionTicks-sampleActionTick<=1,"local_segment_tick_gap");
        ScopedLocalSegmentPolicy.Phase next;
        try {next=ScopedLocalSegmentPolicy.phase(descent,phase,lastY,p.y,p.vy,p.fall,p.grounded,jumpPulses==1);}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        int nextAirborneSince=!p.grounded && airborneSince<0?actionTicks:airborneSince;
        require(p.grounded || actionTicks-nextAirborneSince<=ScopedLocalSegmentPolicy.MAX_AIRBORNE_TICKS,
                "local_segment_airborne_tick_budget");
        double distance=Math.hypot(p.x-sampleX,p.z-sampleZ);
        double nextTickDistance=(actionTicks==sampleActionTick?tickDistance:0)+distance;
        double nextSampledDistance=sampledDistance+distance;
        double nextDownDistance=(actionTicks==sampleActionTick?tickDownDistance:0)+Math.abs(sampleY-p.y);
        require(nextDownDistance<=ScopedLocalSegmentPolicy.MAX_VERTICAL_SPEED+1e-6,"local_segment_tick_drop_exceeded");
        require(nextTickDistance<=ScopedLocalSegmentPolicy.MAX_TICK_DISPLACEMENT
                && nextSampledDistance<=bounds.steps()+1,"local_segment_sampled_displacement_exceeded");
        airborneSince=nextAirborneSince;phase=next;lastY=p.y;tickDownDistance=nextDownDistance;
        tickDistance=nextTickDistance;sampledDistance=nextSampledDistance;
        sampleActionTick=actionTicks;sampleX=p.x;sampleY=p.y;sampleZ=p.z;
    }
    static void validateIntent(JsonObject body) {validateIntent(body,false);}
    static void validateIntent(JsonObject body,boolean spatial) {
        if(body.has("route_stop_only"))require(spatial&&body.get("route_stop_only").isJsonPrimitive()
            &&body.getAsJsonPrimitive("route_stop_only").isBoolean()&&body.get("route_stop_only").getAsBoolean(),
            "route_spatial_stop_only_flag_invalid");
        if(spatial){
            require(body.has("route_threat_guard")&&body.get("route_threat_guard").isJsonObject(),"route_spatial_guard_required");
            JsonObject g=body.getAsJsonObject("route_threat_guard");
            require(!g.has("target_uuid")||!g.get("target_uuid").equals(body.get("expected_player_uuid")),"route_spatial_self_target_forbidden");
            require(g.keySet().equals(Set.of("schema_version","target_uuid"))&&g.get("schema_version").isJsonPrimitive()
                &&g.getAsJsonPrimitive("schema_version").isNumber()&&g.get("schema_version").getAsString().equals("1")
                &&g.get("target_uuid").isJsonPrimitive()&&g.getAsJsonPrimitive("target_uuid").isString(),"route_spatial_guard_invalid");
            try{require(java.util.UUID.fromString(g.get("target_uuid").getAsString()).toString().equals(g.get("target_uuid").getAsString()),"route_spatial_target_uuid_invalid");}
            catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,"route_spatial_target_uuid_invalid");}
        }

        var health=body.get("min_health");
        require(health!=null && health.isJsonPrimitive() && health.getAsJsonPrimitive().isNumber()
                && Double.isFinite(health.getAsDouble()) && health.getAsDouble()>=8 && health.getAsDouble()<=20,
                "local_segment_health_guard_required");
        require(Set.of("action_id","action","timeout_ms","waypoints","capability_route","min_health","jump","sprint","sneak",
            "capability_guard","expected_origin","expected_navigation_epoch","expected_world_generation","expected_dimension",
            "expected_player_uuid","expected_action_session","expected_hotbar_slot","expected_held_item").containsAll(
                body.keySet().stream().filter(k->!spatial||!Set.of("route_threat_guard","route_stop_only").contains(k)).collect(java.util.stream.Collectors.toSet())),
            "local_segment_unknown_intent_field");
        require(body.has("waypoints") && body.get("waypoints").isJsonArray() && body.getAsJsonArray("waypoints").size()==1,
            "local_segment_exactly_one_step");
        var point=body.getAsJsonArray("waypoints").get(0);
        require(point.isJsonObject() && Set.of("x","y","z","jump").containsAll(point.getAsJsonObject().keySet()),"local_segment_unknown_waypoint_field");
    }
    boolean settled() {
        var v=player.getDeltaMovement();
        return phase==ScopedLocalSegmentPolicy.Phase.LANDED && player.onGround() && player.fallDistance==0
            && Math.abs(player.getY()-descent.endY())<=1e-6
            && Math.hypot(player.getX()-descent.endX()-.5,player.getZ()-descent.endZ()-.5)<=ScopedLocalSegmentPolicy.ARRIVAL_RADIUS
            && ScopedLocalSegmentPolicy.finite(v.x,v.y,v.z) && Math.hypot(v.x,v.z)<=.003 && v.y>=-.09 && v.y<=0;
    }
    record Step(float yaw,float forward,boolean jump,boolean done) { }
    /** Pure decision after beforeEffect's last hook-free fence. No replay/unstuck fallback. */
    Step step() {
        double x=player.getX(),z=player.getZ();float yaw=player.getYRot();var velocity=player.getDeltaMovement();
        if(settled()) {
            if(sampleActionTick!=settledTick){settledTick=sampleActionTick;settledSamples++;}
            return new Step(yaw,0,false,settledSamples>=2);
        }
        settledSamples=0;settledTick=-1;
        if(descent.dy()>0&&jumpPulses==0) {
            double sourceDistance=Math.hypot(x-descent.startX()-.5,z-descent.startZ()-.5);
            if(sourceDistance>.02) {
                var centered=ScopedLocalSegmentPolicy.toward(x,z,yaw,descent.startX()+.5,descent.startZ()+.5,.012,.2F);
                return new Step(centered.yaw(),sourceDistance<=.012?0:centered.forward(),false,false);
            }
            // Vanilla aiStep naturally clamps tiny components. Wait for that ordinary
            // zero, rather than treating its post-input clamp as an external mutation.
            if(velocity.horizontalDistance()!=0)return new Step(yaw,0,false,false);
            float target=(float)Math.toDegrees(Math.atan2(-(descent.endX()-descent.startX()),descent.endZ()-descent.startZ()));
            double error=Math.IEEEremainder(target-yaw,360);
            float turned=(float)(yaw+Math.max(-45,Math.min(45,error)));
            boolean aligned=Math.abs(Math.IEEEremainder(target-turned,360))<=1;
            return new Step(turned,0,aligned&&neutralTick>=0&&sampleActionTick>neutralTick,false);
        }
        if(descent.dy()>0&&phase==ScopedLocalSegmentPolicy.Phase.GROUND) {
            require(sampleActionTick<=jumpPulseTick,"local_segment_jump_not_observed");
            return new Step(yaw,0,false,false);
        }
        if(descent.dy()>0&&!player.onGround()&&player.getY()<descent.endY()-1e-6)
            return new Step(yaw,0,false,false);
        var steering=ScopedLocalSegmentPolicy.toward(x,z,yaw,descent.endX()+.5,descent.endZ()+.5,.04,.5F);
        float forward=steering.forward();
        // A vertical ordinary jump has a short clearance window. Normal air input,
        // never sprint or a velocity write, crosses until the actual upper landing.
        if(descent.dy()>0&&!player.onGround()) {
            double target=Math.toDegrees(Math.atan2(-(descent.endX()+.5-x),descent.endZ()+.5-z));
            forward=steering.distance()<=.04||Math.abs(Math.IEEEremainder(target-steering.yaw(),360))>1?0:1;
        }
        return new Step(steering.yaw(),forward,false,false);
    }
    /** Called at the exact owned Input field-write boundary, with no intervening hooks. */
    void recordInput(boolean jump,float forward) {
        int tick=actionTicks();
        require(Float.isFinite(forward)&&forward>=0&&forward<=1,"local_segment_invalid_input");
        if(jump){
            require(descent.dy()==1&&jumpPulses==0&&phase==ScopedLocalSegmentPolicy.Phase.GROUND
                &&player.onGround()&&neutralTick>=0&&tick>neutralTick
                &&Math.hypot(player.getX()-descent.startX()-.5,player.getZ()-descent.startZ()-.5)<=.02
                &&player.getDeltaMovement().horizontalDistance()==0&&forward==0,"local_segment_jump_boundary_changed");
            jumpPulses=1;jumpPulseTick=tick;
            pulseX=player.getX();pulseY=player.getY();pulseZ=player.getZ();
            pulseVx=player.getDeltaMovement().x;pulseVz=player.getDeltaMovement().z;
        } else if(forward==0&&jumpPulses==0)neutralTick=tick;
    }
    private boolean jumpTransition(Pose p,boolean boundary){
        return boundary&&descent.dy()==1&&jumpPulses==1&&phase==ScopedLocalSegmentPolicy.Phase.GROUND
            &&sampleActionTick==jumpPulseTick&&p.grounded&&p.y==pulseY&&p.vy==(double).42F;
    }
    /** Exact post-jump-hook, pre-Entity.move fence. Requested vanilla motion is never rewritten. */
    void beforeVanillaMove(Minecraft mc,net.minecraft.world.phys.Vec3 requested){
        try{check(mc,true);}catch(RuntimeException failure){recordFailure(failure);throw failure;}
        var v=player.getDeltaMovement();
        require(requested!=null&&ScopedLocalSegmentPolicy.finite(requested.x,requested.y,requested.z)
            &&requested.x==v.x&&requested.y==v.y&&requested.z==v.z,"local_segment_requested_motion_changed");
        // Known requested horizontal motion must stay inside the swept body corridor.
        // Downward Y is not projected through support: vanilla collision clips the landing.
        require(descent.horizontalContains(player.getX()+requested.x,player.getZ()+requested.z)
            &&player.getY()+requested.y<=descent.startY()+(descent.dy()>0?ScopedLocalSegmentPolicy.MAX_RISE:0)+1e-6,
            "local_segment_requested_sweep_outside");
        if(descent.dy()==1&&jumpPulses==1&&phase==ScopedLocalSegmentPolicy.Phase.GROUND)
            require(sampleActionTick==jumpPulseTick&&player.onGround()&&player.getX()==pulseX&&player.getY()==pulseY
                &&player.getZ()==pulseZ&&v.x==pulseVx&&v.z==pulseVz&&v.y==(double).42F,
                "local_segment_post_jump_hook_changed");
    }
    static boolean keysDown(Minecraft mc){return mc.options.keyUp.isDown() || mc.options.keyDown.isDown()
            || mc.options.keyLeft.isDown() || mc.options.keyRight.isDown() || mc.options.keyJump.isDown()
            || mc.options.keySprint.isDown() || mc.options.keyShift.isDown() || mc.options.keyAttack.isDown()
            || mc.options.keyUse.isDown();}
    static boolean neutral(Input input){return input==null || input.forwardImpulse==0 && input.leftImpulse==0
            && !input.up && !input.down && !input.left && !input.right && !input.jumping && !input.shiftKeyDown;}
    JsonObject terminal(boolean neutral) {
        JsonObject out=new JsonObject();out.addProperty("profile",profile);out.addProperty("effect_attempted",attempted);
        out.addProperty("local_checks",checks);out.addProperty("sampled_horizontal_distance",sampledDistance);
        out.addProperty("jump_pulses",jumpPulses);
        out.addProperty("phase",phase.name().toLowerCase(java.util.Locale.ROOT));out.addProperty("landed",phase==ScopedLocalSegmentPolicy.Phase.LANDED);
        out.addProperty("distance_accounting","callback-sampled-not-all-move-instrumentation");
        out.addProperty("input_neutral",neutral);out.addProperty("velocity_stopped_proven",false);
        out.addProperty("deadline_nano",Long.toString(deadline));
        out.addProperty("entity_guard_policy",spatial?ScopedRouteThreatPolicy.POLICY:spatialStop?(bees?ScopedRouteStopPolicy.POLICY_V2:ScopedRouteStopPolicy.POLICY):ScopedEntityPolicy.POLICY);out.addProperty("entity_guard_checks",checks);
        out.addProperty("last_entity_check_tick",lastEntityTick);out.addProperty("last_entity_check_nano",Long.toString(lastEntityNano));
        out.addProperty("timing_contract",TIMING_CONTRACT);out.addProperty("last_entity_check_action_tick",sampleActionTick);
        out.addProperty("maximum_checked_population",maximumCheckedPopulation);return out;
    }
    static String rejection(RuntimeException failure) {
        return failure instanceof ClientActionRequest.Rejected && failure.getMessage()!=null
                ? failure.getMessage() : "local_segment_check_failed";
    }
    private static void require(boolean condition,String reason){if(!condition)throw new ClientActionRequest.Rejected(409,reason);}
}
