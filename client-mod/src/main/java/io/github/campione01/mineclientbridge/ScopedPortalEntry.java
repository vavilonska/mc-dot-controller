package io.github.campione01.mineclientbridge;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.GrassBlock;
import net.minecraft.world.level.block.NetherrackBlock;
import net.minecraft.world.level.block.NetherPortalBlock;
import net.minecraft.world.level.block.EndPortalBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.entity.TheEndPortalBlockEntity;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.phys.Vec3;
/** Prepared flat entry only. Lifecycle cancellation releases input; it never proves arrival. */
final class ScopedPortalEntry {
    static final String PROFILE="portal-entry-observed-v1";
    static final int MAX_TICKS=160,MAX_TIMEOUT=8000;
    private static final Set<String> FLOORS=Set.of("minecraft:stone","minecraft:cobblestone","minecraft:dirt","minecraft:grass_block","minecraft:obsidian","minecraft:netherrack","minecraft:end_stone","minecraft:stone_bricks");
    private static final Set<String> TRANSITIONS=Set.of("world_changed","world_or_player_changed","world_transition","capability_world_changed","capability_dimension_changed","player_changed");
    private final TypedPortalReaders readers;
    final ClientActionRequest request;final LocalPlayer player;final ClientLevel level;final Object server;
    final String session,serverIdentity,worldGeneration,playerUuid,destination,dimension;
    final long sourceNano,sourceTick,deadline,navigationEpoch,admissionOwnerRevision;final ScopedFlatPolicy.Bounds bounds;
    private final Object gameMode;private final BlockPos portal;private final JsonObject metadata,footprint;
    private final List<BlockPos> positions=new ArrayList<>();private final List<BlockState> states=new ArrayList<>();
    private final List<TypedPortalStack> inventory=new ArrayList<>();private final int selected,menuRevision;
    private final net.minecraft.world.inventory.AbstractContainerMenu menu;private final float health;
    private final PlacementCallbackFence callbackFence;private final Pose admissionPose;private Pose lastPose;
    private ActionRegistry.Entry entry;private long ownerRevision;private JsonObject originalWitness;
    private long contactTick=-1,lastCheckNano;
    private int lastTick,checks;private double sampleX,sampleZ,sampledDistance,tickDistance;
    private boolean attempted,unknown,transitionEligible,lastAtPortal,sourceContact;
    static void validateIntent(JsonObject b){ScopedPortalEntryIntent.validate(b);}
    ScopedPortalEntry(Minecraft mc,ClientActionRequest request,long nano,long tick){
        admissionOwnerRevision=ClientActions.ownershipRevision();
        validateIntent(request.original());require(ScopedPortalEntryDispatch.ready(),"portal_entry_contact_hook_not_installed");readers=new TypedPortalReaders(mc);this.request=request;sourceNano=nano;sourceTick=tick;deadline=nano+request.timeoutMs()*1000000L;
        player=mc.player;level=mc.level;server=mc.getSingleplayerServer();gameMode=mc.gameMode;session=ClientActions.session();serverIdentity=IntegratedServerIdentity.current(server,CapabilityGuard.privateSingleplayer(mc));
        worldGeneration=WorldGeneration.current(level);playerUuid=player.getUUID().toString();dimension=level.dimension().location().toString();navigationEpoch=NavigationPositionGuard.epoch();
        metadata=request.original().getAsJsonObject("typed_portal_entry").deepCopy();destination=metadata.get("destination").getAsString();portal=pos(metadata.getAsJsonObject("portal_cell"));
        double x=player.getX(),y=player.getY(),z=player.getZ();int sx=(int)Math.floor(x),sy=(int)Math.rint(y),sz=(int)Math.floor(z);
        JsonObject origin=request.original().getAsJsonObject("expected_origin");require(origin!=null&&origin.keySet().equals(Set.of("x","y","z"))
            &&origin.get("x").getAsDouble()==x&&origin.get("y").getAsDouble()==y&&origin.get("z").getAsDouble()==z
            &&request.original().get("expected_navigation_epoch").getAsLong()==navigationEpoch,"portal_entry_expected_origin_changed");
        require(ScopedFlatPolicy.finite(x,y,z)&&Math.abs(x-sx-.5)<=.10&&Math.abs(z-sz-.5)<=.10&&Math.abs(y-sy)<1e-7
            &&portal.getY()==sy&&Math.sqrt(Math.pow(portal.getX()+.5-x,2)+Math.pow(portal.getZ()+.5-z,2))<=2&&Math.hypot(portal.getX()+.5-x,portal.getZ()+.5-z)>.23,"portal_entry_centered_flat_two_block_corridor");
        require(CapabilityPlacement.exact(TypedPortalReaders.block(level,portal),metadata.get("portal_id").getAsString(),metadata.getAsJsonObject("portal_properties")),"portal_entry_target_changed");
        int minX=(int)Math.floor(Math.min(x,portal.getX()+.5)-.31),maxX=(int)Math.floor(Math.max(x,portal.getX()+.5)+.31);
        int minZ=(int)Math.floor(Math.min(z,portal.getZ()+.5)-.31),maxZ=(int)Math.floor(Math.max(z,portal.getZ()+.5)+.31);
        bounds=new ScopedFlatPolicy.Bounds(minX,sy-1,minZ,maxX,sy+1,maxZ,sx,sy,sz,portal.getX(),portal.getZ(),2);
        require(bounds.cells()<=48,"portal_entry_footprint_budget");selected=player.getInventory().selected;menu=player.containerMenu;menuRevision=menu.getStateId();health=player.getHealth();
        require(menu==player.inventoryMenu&&menu.getClass()==InventoryMenu.class&&player.getInventory().getClass()==net.minecraft.world.entity.player.Inventory.class,"portal_entry_exact_inventory_required");
        for(int i=0;i<41;i++)inventory.add(new TypedPortalStack(player.getInventory().getItem(i)));
        sampleX=x;sampleZ=z;JsonArray cells=new JsonArray();
        for(int cx=bounds.minX();cx<=bounds.maxX();cx++)for(int cy=bounds.minY();cy<=bounds.maxY();cy++)for(int cz=bounds.minZ();cz<=bounds.maxZ();cz++){
            BlockPos p=new BlockPos(cx,cy,cz);BlockState state=readCell(p);positions.add(p);states.add(state);cells.add(cell(p,state));}
        footprint=new JsonObject();footprint.addProperty("profile",PROFILE);footprint.addProperty("source","native-client-loaded-level");footprint.add("typed_portal_entry",metadata.deepCopy());
        for(String a:Set.of("x","y","z")){footprint.addProperty("min_"+a,a.equals("x")?bounds.minX():a.equals("y")?bounds.minY():bounds.minZ());footprint.addProperty("max_"+a,a.equals("x")?bounds.maxX():a.equals("y")?bounds.maxY():bounds.maxZ());}
        footprint.addProperty("expected_cells",bounds.cells());footprint.add("cells",cells);footprint.addProperty("all_loaded",true);footprint.addProperty("complete",true);
        footprint.addProperty("maximum_action_ticks",MAX_TICKS);footprint.addProperty("maximum_timeout_ms",MAX_TIMEOUT);footprint.addProperty("deadline_nano",Long.toString(deadline));footprint.add("entity_guard",entities(0).frame.json());
        callbackFence=new PlacementCallbackFence(()->entry==null?ClientActions.ownershipRevision()==admissionOwnerRevision&&!ClientActions.ownsInput():ClientActions.ownsScopedPortalEntry(this,entry),System::nanoTime,level::getGameTime);
        admissionPose=pose(mc,true);admissionRecheck(mc);
    }
    JsonObject facts(){return footprint.deepCopy();}
    void activate(ActionRegistry.Entry e){require(entry==null&&e!=null&&e.ticks==0&&ClientActions.ownsScopedPortalEntry(this,e),"portal_entry_activation_changed");entry=e;ownerRevision=ClientActions.ownershipRevision();originalWitness=e.result.getAsJsonObject("scoped_native_preflight").deepCopy();ScopedPortalEntryDispatch.bind(this);}
    void admissionRecheck(Minecraft mc){check(mc,true);}
    void admissionRawFence(Minecraft mc){require(entry==null,"portal_entry_admission_owner_changed");callbackFence.check(()->raw(mc,admissionPose,0,System.nanoTime(),true));}
    void beforeEffect(Minecraft mc){require(!unknown,"portal_entry_unknown_outcome_no_further_effect");check(mc,false);}
    private int actionTick(){if(entry==null)return 0;require(ClientActions.ownsScopedPortalEntry(this,entry)&&ownerRevision==ClientActions.ownershipRevision()&&entry.ticks>=lastTick&&entry.ticks-lastTick<=1&&entry.ticks<MAX_TICKS,"portal_entry_owner_or_tick_changed");return entry.ticks;}
    private ScopedMovementEntities entities(int t){var e=ScopedMovementEntities.capture(level,player,bounds,t);e.assertUnchanged();return e;}
    private BlockState readCell(BlockPos p){require(level.hasChunkAt(p),"portal_entry_corridor_unloaded");BlockState s=TypedPortalReaders.block(level,p);String id=BuiltInRegistries.BLOCK.getKey(s.getBlock()).toString();
        require(s.getFluidState().isEmpty(),"portal_entry_fluid");
        if(p.getY()==bounds.minY())require(FLOORS.contains(id)&&(s.getBlock().getClass()==Block.class||s.getBlock()==Blocks.NETHERRACK&&s.getBlock().getClass()==NetherrackBlock.class
            ||s.getBlock()==Blocks.GRASS_BLOCK&&s.getBlock().getClass()==GrassBlock.class)
            &&s.isCollisionShapeFullBlock(level,p)&&Math.abs(s.getFriction(level,p,player)-.6F)<.000001,"portal_entry_supported_floor_required");
        else require((s.getBlock()==Blocks.AIR||s.getBlock()==Blocks.CAVE_AIR||s.getBlock()==Blocks.VOID_AIR||portalState(s))&&s.getCollisionShape(level,p).isEmpty(),"portal_entry_clearance_changed");
        require(blockEntity(p,s),"portal_entry_block_entity_changed");return s;}
    private boolean portalState(BlockState s){return CapabilityPlacement.exact(s,metadata.get("portal_id").getAsString(),metadata.getAsJsonObject("portal_properties"))
        &&(s.getBlock()==Blocks.NETHER_PORTAL&&s.getBlock().getClass()==NetherPortalBlock.class||s.getBlock()==Blocks.END_PORTAL&&s.getBlock().getClass()==EndPortalBlock.class);}
    private boolean blockEntity(BlockPos p,BlockState s){var e=TypedPortalReaders.blockEntity(level,p);return s.getBlock()!=Blocks.END_PORTAL?e==null:e!=null&&e.getClass()==TheEndPortalBlockEntity.class&&e.getType()==BlockEntityType.END_PORTAL&&!e.isRemoved()&&e.getLevel()==level&&e.getBlockPos().equals(p)&&e.getBlockState()==s;}
    private record Pose(double x,double y,double z,double vx,double vy,double vz,float health,float yaw,float pitch,long tick){}
    private Pose pose(Minecraft mc,boolean admission){
        var v=player.getDeltaMovement();var b=player.getBoundingBox();double speed=player.getAttributeValue(Attributes.MOVEMENT_SPEED);
        require(ScopedFlatPolicy.finite(player.getX(),player.getY(),player.getZ(),v.x,v.y,v.z,speed)&&speed>=0&&speed<=.10000001
            &&player.getSpeed()>=0&&player.getSpeed()<=.10000001F&&v.horizontalDistance()<=(admission?.003:.30)&&v.y>=-.09&&v.y<=0
            &&b.getXsize()<=.600001&&b.getZsize()<=.600001&&b.getYsize()<=1.800001&&bounds.containsPose(player.getX(),player.getY(),player.getZ())
            &&b.minX>=bounds.minX()&&b.maxX<=bounds.maxX()+1&&b.minZ>=bounds.minZ()&&b.maxZ<=bounds.maxZ()+1,"portal_entry_motion_or_corridor_changed");
        return new Pose(player.getX(),player.getY(),player.getZ(),v.x,v.y,v.z,player.getHealth(),player.getYRot(),player.getXRot(),level.getGameTime());}
    private void check(Minecraft mc,boolean admission){try{callbackFence.check(()->{readers.current(mc);long began=System.nanoTime();int t=actionTick();Pose p=pose(mc,admission);
        for(int i=0;i<positions.size();i++)require(readCell(positions.get(i))==states.get(i),"portal_entry_footprint_changed");var entityFrame=entities(t);
        require(p.equals(pose(mc,admission)),"portal_entry_pose_changed_after_hooks");raw(mc,p,t,began,admission);entityFrame.assertUnchanged();raw(mc,p,t,began,admission);
        double distance=Math.hypot(p.x-sampleX,p.z-sampleZ);double next=(t==lastTick?tickDistance:0)+distance;
        require(next<=.35&&sampledDistance+distance<=3,"portal_entry_displacement_budget");tickDistance=next;sampledDistance+=distance;sampleX=p.x;sampleZ=p.z;lastTick=t;checks++;lastCheckNano=began;lastPose=p;lastAtPortal=Math.hypot(p.x-portal.getX()-.5,p.z-portal.getZ()-.5)<=.23&&Math.abs(p.y-portal.getY())<1e-6;
        });}catch(RuntimeException failed){if(attempted)unknown=true;throw failed;}}
    private void raw(Minecraft mc,Pose p,int t,long began,boolean admission){
        readers.current(mc);player.getInBlockState();player.isSpectator();readers.current(mc);readers.warmEffectiveValues();var boundary=new TypedPortalBoundary(player,level,positions);var policyBoundary=new TypedPortalPolicyBoundary(mc,player,readers);var entityBoundary=entities(t);
        ExternalControllerGuard.requireIdle(mc);NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();
        for(int i=0;i<positions.size();i++){BlockPos pos=positions.get(i);require(level.hasChunkAt(pos)&&TypedPortalReaders.block(level,pos)==states.get(i)&&blockEntity(pos,states.get(i)),"portal_entry_raw_footprint_changed");}
        require(player.getInventory().getClass()==net.minecraft.world.entity.player.Inventory.class&&player.getInventory().getContainerSize()==41&&player.getInventory().selected==selected
            &&player.containerMenu==menu&&menu==player.inventoryMenu&&menu.getStateId()==menuRevision&&menu.getCarried().isEmpty(),"portal_entry_inventory_context_changed");
        for(int i=0;i<41;i++)require(inventory.get(i).same(player.getInventory().getItem(i)),"portal_entry_inventory_changed");
        long now=System.nanoTime();var v=player.getDeltaMovement();
        require(mc.isSameThread()&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server&&CapabilityGuard.privateSingleplayer(mc)
            &&serverIdentity.equals(IntegratedServerIdentity.current(server,true))&&session.equals(ClientActions.session())&&worldGeneration.equals(WorldGeneration.current(level))
            &&navigationEpoch==NavigationPositionGuard.epoch()&&dimension.equals(level.dimension().location().toString())&&playerUuid.equals(player.getUUID().toString())
            &&now>=sourceNano&&now<deadline&&now>=began&&now-began<=ScopedNativePreflight.MAX_NANOS&&level.getGameTime()==p.tick
            &&mc.gameMode.getPlayerMode()==GameType.SURVIVAL&&mc.isWindowActive()&&!mc.isPaused()&&mc.screen==null&&player.isAlive()&&!player.isSpectator()&&!player.isPassenger()
            &&!player.getAbilities().flying&&!player.noPhysics&&!player.isSprinting()&&!player.isShiftKeyDown()&&!player.isUsingItem()&&!player.isFallFlying()
            &&player.onGround()&&!player.onClimbable()&&player.getActiveEffects().isEmpty()&&!player.isInWater()&&!player.isInLava()&&!player.isInPowderSnow&&!player.isOnFire()
            &&player.hurtTime==0&&player.fallDistance==0&&!player.horizontalCollision&&player.getHealth()>=health
            &&player.getX()==p.x&&player.getY()==p.y&&player.getZ()==p.z&&v.x==p.vx&&v.y==p.vy&&v.z==p.vz&&player.getHealth()==p.health&&player.getYRot()==p.yaw&&player.getXRot()==p.pitch
            &&!BridgeServer.hasHeldInputs()
            &&(entry==null?admission&&ClientActions.ownershipRevision()==admissionOwnerRevision&&!ClientActions.ownsInput()&&level.getGameTime()==sourceTick&&now-sourceNano<=ScopedNativePreflight.MAX_NANOS:
                ClientActions.ownsScopedPortalEntry(this,entry)&&ownerRevision==ClientActions.ownershipRevision()&&entry.ticks==t&&originalWitness.equals(entry.result.get("scoped_native_preflight"))),"portal_entry_final_owner_context_or_deadline_changed");
        readers.current(mc);entityBoundary.assertUnchanged();readers.current(mc);boundary.unchanged();policyBoundary.unchanged();
        require(mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server&&session.equals(ClientActions.session())
            &&worldGeneration.equals(WorldGeneration.current(level))&&navigationEpoch==NavigationPositionGuard.epoch()&&System.nanoTime()<deadline
            &&System.nanoTime()>=began&&System.nanoTime()-began<=ScopedNativePreflight.MAX_NANOS
            &&(entry==null?admission&&ClientActions.ownershipRevision()==admissionOwnerRevision&&!ClientActions.ownsInput():ClientActions.ownsScopedPortalEntry(this,entry)&&ownerRevision==ClientActions.ownershipRevision()
                &&entry.ticks==t&&originalWitness.equals(entry.result.get("scoped_native_preflight"))),"portal_entry_external_reader_changed_owner");
    }
    void markAttempted(){attempted=true;}boolean attempted(){return attempted;}void markUnknown(){unknown=true;transitionEligible=false;}
    boolean atPortal(){return lastAtPortal;}
    PathSteering.Step step(){require(lastPose!=null,"portal_entry_checked_pose_required");return PathSteering.toward(lastPose.x,lastPose.y,lastPose.z,lastPose.yaw,true,false,request.waypoints().get(0),true);}
    boolean expectedTransition(Minecraft mc,String reason){
        if(entry==null||mc.player==null||mc.level==null||mc.player.getClass()!=LocalPlayer.class||mc.level.getClass()!=ClientLevel.class){transitionEligible=false;return false;}
        var original=new PortalTransitionPolicy.Bound(request.id(),session,playerUuid,serverIdentity,worldGeneration,dimension,destination,ownerRevision,sourceNano,deadline);
        String liveServer=IntegratedServerIdentity.current(mc.getSingleplayerServer(),CapabilityGuard.privateSingleplayer(mc));
        var live=new PortalTransitionPolicy.Live(entry.request.id(),ClientActions.session(),mc.player.getUUID().toString(),liveServer,
            WorldGeneration.current(mc.level),mc.level.dimension().location().toString(),ClientActions.ownershipRevision(),System.nanoTime());
        boolean contactStillBound=sourceContact&&readers.originalHealthAtLeast(health);
        if(mc.level==level){
            if(mc.player!=player)contactStillBound=false;
            else {readers.current(mc);contactStillBound &= PortalContactPolicy.sourceLifecycle(true,player.isAlive()&&!player.isDeadOrDying(),player.getHealth()>=health,bodyOverlaps(player.getBoundingBox()),contactTick,level.getGameTime());}
        }
        boolean owned=mc.isSameThread()&&mc.getSingleplayerServer()==server&&(ClientActions.ownsScopedPortalEntry(this,entry)||ClientActions.terminalPortalEntryCleanup(this,entry));
        transitionEligible=PortalTransitionPolicy.permits(original,live,reason,owned,attempted,unknown,contactStillBound)
            &&ownerRevision==ClientActions.ownershipRevision()&&(ClientActions.ownsScopedPortalEntry(this,entry)||ClientActions.terminalPortalEntryCleanup(this,entry))
            &&session.equals(ClientActions.session())&&mc.getSingleplayerServer()==server&&System.nanoTime()<deadline
            &&originalWitness.equals(entry.result.get("scoped_native_preflight"));return transitionEligible;
    }
    boolean activeBinding(){return entry!=null&&ClientActions.ownsScopedPortalEntry(this,entry)&&ownerRevision==ClientActions.ownershipRevision();}
    void contact(net.minecraft.world.entity.Entity actual,net.minecraft.world.level.block.Portal actualPortal,BlockPos actualCell){
        Minecraft mc=Minecraft.getInstance();
        if(!mc.isSameThread()||actual!=player||!activeBinding()||!attempted||unknown||actualCell==null)return;
        if(actualCell.getClass()!=BlockPos.class&&actualCell.getClass()!=BlockPos.MutableBlockPos.class)return;
        BlockPos captured=actualCell.immutable();
        if(!captured.equals(portal)||actualPortal!=states.get(positions.indexOf(portal)).getBlock())return;
        try{
            beforeEffect(mc);callbackFence.check(()->{
            var b=new PortalTransitionPolicy.Bound(request.id(),session,playerUuid,serverIdentity,worldGeneration,dimension,destination,ownerRevision,sourceNano,deadline);
            var v=new PortalTransitionPolicy.Live(entry.request.id(),ClientActions.session(),player.getUUID().toString(),IntegratedServerIdentity.current(mc.getSingleplayerServer(),CapabilityGuard.privateSingleplayer(mc)),WorldGeneration.current(mc.level),mc.level.dimension().location().toString(),ClientActions.ownershipRevision(),System.nanoTime());
            var body=player.getBoundingBox();boolean overlap=bodyOverlaps(body);readers.current(mc);readers.warmEffectiveValues();
            var boundary=new TypedPortalBoundary(player,level,positions);var policyBoundary=new TypedPortalPolicyBoundary(mc,player,readers);var entityBoundary=entities(actionTick());
            boolean exactCell=actualCell.equals(captured)&&captured.equals(portal)&&TypedPortalReaders.block(level,portal)==states.get(positions.indexOf(portal));
            ExternalControllerGuard.requireIdle(mc);NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();
            readers.current(mc);entityBoundary.assertUnchanged();readers.current(mc);boundary.unchanged();policyBoundary.unchanged();
            require(PortalContactPolicy.permits(b,v,activeBinding(),actual==player&&mc.player==player,mc.level==level,mc.getSingleplayerServer()==server,
                actualPortal==states.get(positions.indexOf(portal)).getBlock(),exactCell&&actualCell.equals(captured),overlap,attempted,unknown)
                &&activeBinding()&&session.equals(ClientActions.session())&&worldGeneration.equals(WorldGeneration.current(level))&&System.nanoTime()<deadline
                &&System.nanoTime()>=lastCheckNano&&System.nanoTime()-lastCheckNano<=ScopedNativePreflight.MAX_NANOS
                &&player.getBoundingBox().equals(body)&&player.getX()==lastPose.x&&player.getY()==lastPose.y&&player.getZ()==lastPose.z
                &&originalWitness.equals(entry.result.get("scoped_native_preflight")),
                "portal_entry_contact_binding_changed");
            policyBoundary.unchanged();
            require(activeBinding()&&System.nanoTime()<deadline,"portal_entry_contact_final_policy_changed");
            sourceContact=true;contactTick=lastPose.tick;
            });
        }catch(RuntimeException failed){markUnknown();}
    }
    private boolean bodyOverlaps(net.minecraft.world.phys.AABB b){
        return b!=null&&b.getClass()==net.minecraft.world.phys.AABB.class&&PortalContactPolicy.overlaps(metadata.get("portal_id").getAsString().equals("minecraft:end_portal"),portal.getX(),portal.getY(),portal.getZ(),b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ);
    }
    boolean releaseBinding(Minecraft mc){return entry!=null&&ClientActions.terminalPortalEntryCleanup(this,entry)&&mc.isSameThread()&&mc.getSingleplayerServer()==server
        &&serverIdentity.equals(IntegratedServerIdentity.current(server,CapabilityGuard.privateSingleplayer(mc)))&&session.equals(ClientActions.session())&&mc.player!=null&&playerUuid.equals(mc.player.getUUID().toString());}
    JsonObject terminal(boolean neutral){ScopedPortalEntryDispatch.unbind(this);JsonObject o=new JsonObject();o.addProperty("profile",PROFILE);o.addProperty("effect_attempted",attempted);o.addProperty("unknown_outcome",unknown);o.addProperty("transition_eligible",transitionEligible);o.addProperty("source_portal_contact",sourceContact);
        o.addProperty("source_dimension",dimension);o.addProperty("destination",destination);o.add("portal_cell",ScopedMining.position(portal));o.addProperty("entry_contract",ScopedPortalEntryIntent.CONTRACT);
        o.addProperty("original_native_action_id",request.id());o.addProperty("original_action_session",session);o.addProperty("original_player_uuid",playerUuid);o.addProperty("integrated_server_instance",serverIdentity);o.addProperty("source_world_generation",worldGeneration);
        o.addProperty("deadline_nano",Long.toString(deadline));o.addProperty("input_neutral",neutral);o.addProperty("local_checks",checks);o.addProperty("sampled_distance",sampledDistance);
        o.addProperty("destination_arrival_proven",false);o.addProperty("automatic_replay_allowed",false);o.addProperty("server_confirmed",false);return o;}
    private static BlockPos pos(JsonObject p){return new BlockPos(p.get("x").getAsInt(),p.get("y").getAsInt(),p.get("z").getAsInt());}
    private static JsonObject cell(BlockPos p,BlockState s){JsonObject o=ScopedMining.position(p);o.addProperty("id",BuiltInRegistries.BLOCK.getKey(s.getBlock()).toString());o.addProperty("state",s.toString());o.addProperty("block_class",s.getBlock().getClass().getName());o.addProperty("loaded",true);o.addProperty("fluid","minecraft:empty");JsonObject props=new JsonObject();for(var e:s.getValues().entrySet())props.addProperty(e.getKey().getName(),e.getValue().toString());o.add("properties",props);return o;}
    private static void require(boolean ok,String reason){ScopedPortalEntryIntent.need(ok,reason);}
}
