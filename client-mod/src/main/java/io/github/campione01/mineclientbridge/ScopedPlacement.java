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
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.GrassBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

/** One stationary, ordinary vanilla placement. Never writes blocks or sends packets itself. */
final class ScopedPlacement {
    static final String PROFILE="placement-local-observed-v1";
    static final int MAX_TICKS=40,MAX_TIMEOUT=2000;
    final ClientActionRequest request;
    final LocalPlayer player; final ClientLevel level;
    final BlockPos target,support,standingSupport;
    final Direction face;
    final long sourceNano,sourceTick,deadline,navigationEpoch;
    private final Object server,gameMode;
    private final String session,worldGeneration,serverIdentity,commandDigest;
    private final double x,y,z; private final Vec3 eye;
    private final AABB body; private final float health,saturation;
    private final int food,selected,initialCount,menuState;
    private final List<ItemStack> inventory=new ArrayList<>();
    private final List<BlockPos> positions=new ArrayList<>();
    private final List<BlockState> states=new ArrayList<>();
    private final RawMenu rawMenu;
    private final ScopedFlatPolicy.Bounds bounds;
    private final JsonObject footprint;
    private long ownerRevision;
    private ActionRegistry.Entry entry;
    private JsonObject originalWitness;
    private final PlacementCallbackFence callbackFence;
    private int checks,effectCount,packetCount,lastTick,useCount,selectionPackets;
    private net.minecraft.network.protocol.Packet<?> expectedPacket;
    private boolean attempted,unknown;
    private BlockHitResult dispatchHit;
    private Vec3 dispatchLocation;
    private int expectedSequence;
    private PlacementPacketBinding expectedBinding;
    private float dispatchYaw,dispatchPitch;

    static void validateIntent(JsonObject body){ScopedPlacementIntent.validate(body);}
    ScopedPlacement(Minecraft mc,ClientActionRequest request,long nano,long tick) {
        validateIntent(request.original());this.request=request;sourceNano=nano;sourceTick=tick;deadline=nano+request.timeoutMs()*1_000_000L;
        require(ScopedPlacementDispatch.ready(),"placement_callback_seams_unavailable");
        player=mc.player;level=mc.level;server=mc.getSingleplayerServer();gameMode=mc.gameMode;
        session=ClientActions.session();worldGeneration=WorldGeneration.current(level);
        serverIdentity=IntegratedServerIdentity.current(server,CapabilityGuard.privateSingleplayer(mc));
        navigationEpoch=NavigationPositionGuard.epoch();commandDigest=ScopedNativePreflight.digest(request.original());
        x=player.getX();y=player.getY();z=player.getZ();eye=player.getEyePosition();body=player.getBoundingBox();
        health=player.getHealth();food=player.getFoodData().getFoodLevel();saturation=player.getFoodData().getSaturationLevel();
        selected=player.getInventory().selected;initialCount=player.getMainHandItem().getCount();menuState=player.containerMenu.getStateId();
        support=new BlockPos(request.support().x(),request.support().y(),request.support().z());
        face=Direction.valueOf(request.face().toUpperCase(java.util.Locale.ROOT));target=support.relative(face);standingSupport=BlockPos.containing(x,y-.01,z);
        require(Double.isFinite(x)&&Double.isFinite(y)&&Double.isFinite(z)&&eye.distanceTo(Vec3.atCenterOf(support))<=6
            && !body.intersects(new AABB(target)),"placement_position_or_target_invalid");
        require(initialCount>=1 && initialCount<=64 && player.getMainHandItem().getItem().getClass()==BlockItem.class
            && ItemStack.isSameItemSameComponents(player.getMainHandItem(),Items.COBBLESTONE.getDefaultInstance()),"placement_plain_cobblestone_required");
        for(int i=0;i<41;i++)inventory.add(player.getInventory().getItem(i).copy());
        rawMenu=new RawMenu(player,selected);
        require(body.minX>=standingSupport.getX() && body.maxX<=standingSupport.getX()+1 && body.minZ>=standingSupport.getZ()
            && body.maxZ<=standingSupport.getZ()+1 && Math.abs(body.minY-standingSupport.getY()-1)<1e-7 && body.getYsize()<=1.800001,
            "placement_single_standing_support_required");
        int minX=Math.min(standingSupport.getX(),Math.min(target.getX(),support.getX()))-1,maxX=Math.max(standingSupport.getX(),Math.max(target.getX(),support.getX()))+1;
        int minY=Math.min(standingSupport.getY(),Math.min(target.getY(),support.getY()))-1,maxY=Math.max(standingSupport.getY()+3,Math.max(target.getY(),support.getY())+1);
        int minZ=Math.min(standingSupport.getZ(),Math.min(target.getZ(),support.getZ()))-1,maxZ=Math.max(standingSupport.getZ(),Math.max(target.getZ(),support.getZ()))+1;
        long count=(long)(maxX-minX+1)*(maxY-minY+1)*(maxZ-minZ+1);require(count>0&&count<=512,"placement_footprint_over_bound");
        bounds=new ScopedFlatPolicy.Bounds(minX,minY,minZ,maxX,maxY,maxZ,standingSupport.getX(),standingSupport.getY()+1,standingSupport.getZ(),target.getX(),target.getZ(),0);
        JsonArray cells=new JsonArray();
        for(int cx=minX;cx<=maxX;cx++)for(int cy=minY;cy<=maxY;cy++)for(int cz=minZ;cz<=maxZ;cz++) {
            BlockPos pos=new BlockPos(cx,cy,cz);positions.add(pos);BlockState state=readCell(pos);states.add(state);cells.add(cell(pos,state));
        }
        require(level.getBlockState(target)==Blocks.AIR.defaultBlockState(),"placement_exact_target_air_required");
        require(CapabilityPlacement.exact(level.getBlockState(support),ClientActionRequest.string(request.original(),"expected_support_id"),new JsonObject())
            && ScopedMining.TARGETS.contains(level.getBlockState(support).getBlock()) && level.getBlockState(support).getBlock().getClass()==Block.class,
            "placement_exact_plain_support_required");
        footprint=new JsonObject();footprint.addProperty("profile",PROFILE);footprint.addProperty("source","native-client-loaded-level");
        footprint.add("support",ScopedMining.position(support));footprint.add("target",ScopedMining.position(target));footprint.add("standing_support",ScopedMining.position(standingSupport));
        footprint.addProperty("face",request.face());footprint.addProperty("support_id",ClientActionRequest.string(request.original(),"expected_support_id"));
        footprint.add("support_properties",new JsonObject());footprint.addProperty("block_id","minecraft:cobblestone");footprint.add("block_properties",new JsonObject());
        footprint.addProperty("selected_slot",selected);footprint.addProperty("initial_count",initialCount);
        footprint.addProperty("min_x",minX);footprint.addProperty("max_x",maxX);footprint.addProperty("min_y",minY);footprint.addProperty("max_y",maxY);
        footprint.addProperty("min_z",minZ);footprint.addProperty("max_z",maxZ);footprint.addProperty("expected_cells",count);footprint.add("cells",cells);
        footprint.addProperty("all_loaded",true);footprint.addProperty("complete",true);footprint.addProperty("callbacks_installed",true);
        footprint.addProperty("maximum_action_ticks",MAX_TICKS);footprint.addProperty("maximum_timeout_ms",MAX_TIMEOUT);footprint.addProperty("deadline_nano",Long.toString(deadline));
        footprint.add("entity_guard",entities(0).frame.json());
        callbackFence=new PlacementCallbackFence(()->entry==null?!ClientActions.ownsInput():ClientActions.ownsScopedPlacement(this,entry),System::nanoTime,level::getGameTime);
        admission(mc);
    }
    JsonObject facts(){return footprint.deepCopy();}
    void admission(Minecraft mc){check(mc,false,false);}
    void activate(ActionRegistry.Entry entry){
        require(this.entry==null && entry!=null && entry.ticks==0 && ClientActions.ownsScopedPlacement(this,entry),"placement_activation_changed");
        this.entry=entry;ownerRevision=ClientActions.ownershipRevision();originalWitness=entry.result.getAsJsonObject("scoped_native_preflight").deepCopy();
        require(commandDigest.equals(originalWitness.get("command_sha256").getAsString()),"placement_command_digest_changed");
    }
    private int actionTick(){
        if(entry==null)return 0;
        require(ClientActions.ownsScopedPlacement(this,entry)&&ClientActions.ownershipRevision()==ownerRevision,"placement_owner_changed");
        int t=entry.ticks;require(t>=lastTick&&t-lastTick<=1&&t<MAX_TICKS,"placement_tick_gap_or_budget");return t;
    }
    private ScopedMovementEntities entities(int t){var e=ScopedMovementEntities.capture(level,player,bounds,t);e.assertUnchanged();return e;}
    private BlockState readCell(BlockPos p){
        require(level.hasChunkAt(p),"placement_dependency_unloaded");BlockState s=level.getBlockState(p);Block b=s.getBlock();
        boolean air=b==Blocks.AIR||b==Blocks.CAVE_AIR||b==Blocks.VOID_AIR;
        boolean solid=ScopedMining.TARGETS.contains(b)&&b.getClass()==Block.class || b==Blocks.GRASS_BLOCK&&b.getClass()==GrassBlock.class || b==Blocks.BEDROCK;
        require((air||solid)&&s.getFluidState().isEmpty()&&level.getBlockEntity(p)==null,"placement_hazard_or_unknown_geometry");
        require(air?s.getCollisionShape(level,p).isEmpty()&&s.getShape(level,p).isEmpty():s.isCollisionShapeFullBlock(level,p)&&s.getShape(level,p).bounds().equals(new AABB(0,0,0,1,1,1)),"placement_nonstatic_shape");
        if(p.equals(standingSupport))require(!air,"placement_standing_support_missing");
        if(p.getX()==standingSupport.getX()&&p.getZ()==standingSupport.getZ()&&p.getY()>standingSupport.getY()&&p.getY()<=standingSupport.getY()+2)require(air,"placement_body_not_clear");
        return s;
    }
    void check(Minecraft mc,boolean permitEffect,boolean ray){callbackFence.check(()->checkCurrent(mc,permitEffect,ray));}
    private void checkCurrent(Minecraft mc,boolean permitEffect,boolean ray){
        long began=System.nanoTime(),tick=level.getGameTime();int t=actionTick();float yaw=player.getYRot(),pitch=player.getXRot();
        raw(mc,permitEffect,t,began,tick,yaw,pitch);
        for(int i=0;i<positions.size();i++){BlockPos p=positions.get(i);BlockState s=readCell(p);
            require(s==states.get(i)||permitEffect&&effectCount==1&&p.equals(target)&&s==Blocks.COBBLESTONE.defaultBlockState(),"placement_footprint_changed");}
        entities(t);
        BlockHitResult hit=null;double reach=0;
        if(ray){mc.gameRenderer.pick(1.0F);reach=player.blockInteractionRange();
            require(Double.isFinite(reach)&&reach>0&&reach<=6&&mc.hitResult!=null&&mc.hitResult.getClass()==BlockHitResult.class,"placement_ray_required");
            hit=(BlockHitResult)mc.hitResult;require(validHit(hit)&&eye.distanceTo(hit.getLocation())<=reach,"placement_support_not_visible_or_reachable");}
        raw(mc,permitEffect,t,began,tick,yaw,pitch);
        if(hit!=null)require(mc.hitResult==hit&&validHit(hit),"placement_ray_changed_after_hooks");
        lastTick=t;checks++;
    }
    private boolean validHit(BlockHitResult hit){return hit!=null&&hit.getType()==HitResult.Type.BLOCK&&hit.getBlockPos().equals(support)&&hit.getDirection()==face&&!hit.isInside()
        && Double.isFinite(hit.getLocation().x)&&Double.isFinite(hit.getLocation().y)&&Double.isFinite(hit.getLocation().z)
        && hit.getLocation().distanceTo(CapabilityPlacement.hit(request))<=.01;}
    private void raw(Minecraft mc,boolean permitEffect,int t,long began,long tick,float yaw,float pitch){
        require(player.getInventory().getClass()==net.minecraft.world.entity.player.Inventory.class&&player.getInventory().getContainerSize()==41
            &&player.getInventory().selected==selected&&player.containerMenu==player.inventoryMenu&&player.containerMenu.getClass()==InventoryMenu.class
            &&player.containerMenu.getStateId()==menuState&&player.containerMenu.getCarried().isEmpty(),"placement_menu_or_selection_changed");
        for(int i=0;i<41;i++)require(sameStack(inventory.get(i),player.getInventory().getItem(i),permitEffect&&effectCount==1&&i==selected),"placement_inventory_changed");
        rawMenu.check(player);
        for(int i=0;i<positions.size();i++){BlockPos p=positions.get(i);require(level.hasChunkAt(p),"placement_unloaded_after_hooks");var s=level.getBlockState(p);
            require((s==states.get(i)||permitEffect&&effectCount==1&&p.equals(target)&&s==Blocks.COBBLESTONE.defaultBlockState())&&s.getFluidState().isEmpty()&&level.getBlockEntity(p)==null,"placement_state_changed_after_hooks");}
        entities(t); // Exact vanilla raw readers; no slot or shape callbacks after this fence.
        Vec3 v=player.getDeltaMovement();long now=System.nanoTime();
        require(mc.isSameThread()&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server
            &&CapabilityGuard.privateSingleplayer(mc)&&serverIdentity.equals(IntegratedServerIdentity.current(server,true))
            &&session.equals(ClientActions.session())&&worldGeneration.equals(WorldGeneration.current(level))&&navigationEpoch==NavigationPositionGuard.epoch()
            &&commandDigest.equals(ScopedNativePreflight.digest(request.original()))
            &&now>=began&&now-began<=ScopedNativePreflight.MAX_NANOS&&now>=sourceNano&&now<deadline&&level.getGameTime()==tick
            &&mc.gameMode.getPlayerMode()==GameType.SURVIVAL&&!mc.gameMode.isDestroying()&&level.dimension().location().toString().equals("minecraft:overworld")
            &&mc.isWindowActive()&&!mc.isPaused()&&mc.screen==null&&player.isAlive()&&!player.isSpectator()&&!player.isPassenger()&&!player.isFallFlying()
            &&!player.getAbilities().flying&&!player.noPhysics&&player.onGround()&&!player.isSprinting()&&!player.isShiftKeyDown()&&!player.isUsingItem()
            &&!player.onClimbable()&&player.getActiveEffects().isEmpty()&&!player.isInWater()&&!player.isEyeInFluid(net.minecraft.tags.FluidTags.WATER)
            &&!player.isInLava()&&!player.isInPowderSnow&&!player.isOnFire()&&player.hurtTime==0&&player.fallDistance==0
            &&player.getHealth()==health&&player.getFoodData().getFoodLevel()==food&&player.getFoodData().getSaturationLevel()==saturation
            &&player.getX()==x&&player.getY()==y&&player.getZ()==z&&player.getBoundingBox().equals(body)&&player.getEyePosition().equals(eye)
            &&Float.isFinite(yaw)&&Float.isFinite(pitch)&&player.getYRot()==yaw&&player.getXRot()==pitch
            &&Double.isFinite(v.x)&&Double.isFinite(v.y)&&Double.isFinite(v.z)&&v.horizontalDistance()<=.0001&&v.y>=-.09&&v.y<=0
            &&ScopedMining.neutral(player.input)&&!ScopedMining.otherKeys(mc)&&!mc.options.keyAttack.isDown()&&!BridgeServer.hasHeldInputs()
            &&(entry==null?!ClientActions.ownsInput()&&tick==sourceTick&&now-sourceNano<=ScopedNativePreflight.MAX_NANOS
                :ClientActions.ownsScopedPlacement(this,entry)&&entry.ticks==t&&ownerRevision==ClientActions.ownershipRevision()
                    &&originalWitness.equals(entry.result.get("scoped_native_preflight"))),"placement_final_owner_context_or_budget_changed");
        if(attempted)require(player.getYRot()==dispatchYaw&&player.getXRot()==dispatchPitch,"placement_dispatch_pose_changed");
    }
    static boolean sameStack(ItemStack before,ItemStack actual,boolean permitOne){
        if(ItemStack.matches(before,actual))return true;
        if(!permitOne||before.isEmpty())return false;
        if(before.getCount()==1)return actual.isEmpty();
        return actual.getCount()==before.getCount()-1&&ItemStack.isSameItemSameComponents(before,actual);
    }
    void beforeUse(Minecraft mc,BlockHitResult hit){
        require(!attempted&&effectCount==0&&packetCount==0,"placement_replay_forbidden");check(mc,false,true);
        require(validHit(hit)&&mc.hitResult instanceof BlockHitResult actual&&validHit(actual),"placement_use_hit_changed");
        dispatchHit=hit;dispatchLocation=new Vec3(hit.getLocation().x,hit.getLocation().y,hit.getLocation().z);dispatchYaw=player.getYRot();dispatchPitch=player.getXRot();attempted=true;
    }
    void enterUse(LocalPlayer p,InteractionHand hand,BlockHitResult hit){
        require(attempted&&useCount==0&&p==player&&hand==InteractionHand.MAIN_HAND&&hit==dispatchHit,"placement_recursive_or_changed_use");
        check(Minecraft.getInstance(),false,true);useCount++;
    }
    void beforeEffect(BlockItem item,BlockPlaceContext c,BlockState state){
        require(attempted&&useCount==1&&effectCount==0&&packetCount==0&&item==Items.COBBLESTONE&&item.getClass()==BlockItem.class
            &&c.getClass()==BlockPlaceContext.class&&c.getLevel()==level&&c.getPlayer()==player&&c.getHand()==InteractionHand.MAIN_HAND&&c.getClickedPos().equals(target)
            &&c.getClickedFace()==face&&c.getItemInHand()==player.getMainHandItem()&&state==Blocks.COBBLESTONE.defaultBlockState(),"placement_effect_binding_changed");
        check(Minecraft.getInstance(),false,true);
        require(effectCount==0&&packetCount==0&&useCount==1&&c.getClickedPos().equals(target)&&c.getItemInHand()==player.getMainHandItem()
            &&state==Blocks.COBBLESTONE.defaultBlockState()&&ClientActions.ownsScopedPlacement(this,entry),"placement_effect_context_changed_after_hooks");
        effectCount++; // Irreversible-attempt latch set immediately before the ordinary Level.setBlock call.
    }
    void packet(net.minecraft.network.protocol.Packet<?> packet,LocalPlayer p,InteractionHand hand,BlockHitResult hit,int sequence){
        require(attempted&&effectCount==1&&packetCount==0&&p==player&&hand==InteractionHand.MAIN_HAND&&hit==dispatchHit
            &&expectedPacket==null&&packet instanceof net.minecraft.network.protocol.game.ServerboundUseItemOnPacket,"placement_packet_binding_changed");
        var wire=(net.minecraft.network.protocol.game.ServerboundUseItemOnPacket)packet;
        require(wire.getHand()==hand&&wire.getHitResult()==hit&&wire.getSequence()==sequence,"placement_returned_packet_changed");
        check(Minecraft.getInstance(),true,false);require(settled()&&wire.getHand()==hand&&wire.getHitResult()==hit&&wire.getSequence()==sequence&&validHit(hit)
            &&hit.getLocation().equals(dispatchLocation)&&packetCount==0&&expectedPacket==null,"placement_packet_effect_or_consumption_unconfirmed");expectedSequence=sequence;expectedPacket=packet;expectedBinding=packetIdentity(wire);
    }
    void send(net.minecraft.network.protocol.Packet<?> packet){
        if(packet instanceof net.minecraft.network.protocol.game.ServerboundSetCarriedItemPacket slot){
            require(useCount==1&&effectCount==0&&packetCount==0&&selectionPackets==0&&slot.getSlot()==selected,"placement_selection_packet_changed");
            check(Minecraft.getInstance(),false,true);require(selectionPackets==0&&effectCount==0&&packetCount==0&&slot.getSlot()==selected,"placement_selection_reentered");selectionPackets++;return;
        }
        require(expectedPacket!=null&&packet==expectedPacket&&packetCount==0&&effectCount==1,"placement_unexpected_or_duplicate_packet");
        var use=(net.minecraft.network.protocol.game.ServerboundUseItemOnPacket)packet;
        require(packetBinding(use),"placement_send_packet_changed");
        check(Minecraft.getInstance(),true,false);require(settled()&&packetCount==0&&packet==expectedPacket&&packetBinding(use),"placement_send_effect_unconfirmed");packetCount++;
    }
    private boolean packetBinding(net.minecraft.network.protocol.game.ServerboundUseItemOnPacket p){
        return p.getHand()==InteractionHand.MAIN_HAND&&p.getSequence()==expectedSequence&&p.getHitResult()==dispatchHit
            &&validHit(dispatchHit)&&dispatchHit.getLocation().equals(dispatchLocation)&&expectedBinding.equals(packetIdentity(p));
    }
    private static PlacementPacketBinding packetIdentity(net.minecraft.network.protocol.game.ServerboundUseItemOnPacket p){
        BlockHitResult h=p.getHitResult();BlockPos b=h.getBlockPos();Vec3 v=h.getLocation();
        return new PlacementPacketBinding(p.getSequence(),p.getHand().name(),b.getX(),b.getY(),b.getZ(),h.getDirection().name(),v.x,v.y,v.z,h.isInside(),h.getType().name());
    }
    void afterUse(){check(Minecraft.getInstance(),true,false);require(effectCount==1&&packetCount==1&&settled(),"placement_dispatch_unconfirmed");}
    boolean settled(){return level.hasChunkAt(target)&&level.getBlockState(target)==Blocks.COBBLESTONE.defaultBlockState()
        &&player.getMainHandItem().getCount()==initialCount-1;}
    boolean cleanupState(boolean success){
        try {
            Minecraft mc=Minecraft.getInstance();
            require(mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server
                &&CapabilityGuard.privateSingleplayer(mc)&&session.equals(ClientActions.session())
                &&worldGeneration.equals(WorldGeneration.current(level))&&navigationEpoch==NavigationPositionGuard.epoch()
                &&player.getX()==x&&player.getY()==y&&player.getZ()==z&&player.getInventory().selected==selected,"placement_cleanup_context_changed");
            for(int i=0;i<41;i++)require(sameStack(inventory.get(i),player.getInventory().getItem(i),effectCount==1&&i==selected),"placement_cleanup_inventory_changed");
            rawMenu.check(player);require(!success||settled(),"placement_cleanup_effect_changed");return true;
        }catch(RuntimeException failed){return false;}
    }
    void markUnknown(){unknown=true;}
    boolean attempted(){return attempted;}
    JsonObject terminal(boolean neutral,boolean success){
        JsonObject o=new JsonObject();o.addProperty("profile",PROFILE);o.add("target",ScopedMining.position(target));o.add("support",ScopedMining.position(support));o.addProperty("face",request.face());
        o.addProperty("effect_attempted",attempted);o.addProperty("effect_count",effectCount);o.addProperty("packet_count",packetCount);
        o.addProperty("unknown_outcome",unknown);o.addProperty("block_placed",success&&!unknown&&effectCount==1&&packetCount==1&&settled());
        o.addProperty("server_confirmed",false);o.addProperty("input_neutral",neutral);o.addProperty("local_checks",checks);
        o.addProperty("selected_slot",selected);o.addProperty("initial_count",initialCount);o.addProperty("final_count",player.getMainHandItem().getCount());
        o.addProperty("protected_inventory_unchanged",success&&!unknown);o.addProperty("deadline_nano",Long.toString(deadline));
        o.addProperty("automatic_replay_allowed",false);o.addProperty("future_dynamics_certified",false);return o;
    }
    private static JsonObject cell(BlockPos p,BlockState s){
        JsonObject o=ScopedMining.position(p);o.addProperty("id",BuiltInRegistries.BLOCK.getKey(s.getBlock()).toString());o.addProperty("state",s.toString());
        o.addProperty("loaded",true);o.addProperty("fluid","minecraft:empty");o.addProperty("air",s.isAir());o.addProperty("static_full_cube",!s.isAir());o.addProperty("block_class",s.getBlock().getClass().getName());
        JsonObject props=new JsonObject();for(var e:s.getValues().entrySet())props.addProperty(e.getKey().getName(),e.getValue().toString());o.add("properties",props);return o;
    }
    static void require(boolean condition,String reason){if(!condition)throw new ClientActionRequest.Rejected(409,reason);}
    private final class RawMenu {
        final net.minecraft.world.entity.player.Inventory inventory;
        final net.minecraft.world.inventory.AbstractContainerMenu menu;
        final List<net.minecraft.world.inventory.Slot> slots;
        final net.minecraft.world.Container[] containers;
        final int[] indices;
        final ItemStack[] items;
        final int selected,revision;
        RawMenu(LocalPlayer player,int selected) {
            this.selected=selected;inventory=player.getInventory();menu=player.containerMenu;
            require(inventory.getClass()==net.minecraft.world.entity.player.Inventory.class && menu.getClass()==InventoryMenu.class,
                "placement_exact_vanilla_inventory_required");
            slots=List.copyOf(menu.slots);containers=new net.minecraft.world.Container[slots.size()];
            indices=new int[slots.size()];items=new ItemStack[slots.size()];revision=menu.getStateId();
            for(int i=0;i<slots.size();i++) {
                var slot=slots.get(i);var type=slot.getClass();var container=slot.container;
                require(type==net.minecraft.world.inventory.Slot.class || type==net.minecraft.world.inventory.ResultSlot.class
                    || type.getClassLoader()==net.minecraft.world.inventory.Slot.class.getClassLoader()
                        && (type.getName().equals("net.minecraft.world.inventory.ArmorSlot")
                            || type.getName().equals("net.minecraft.world.inventory.InventoryMenu$1")),
                    "placement_unknown_inventory_slot");
                require(container.getClass()==net.minecraft.world.entity.player.Inventory.class
                    || container.getClass()==net.minecraft.world.inventory.TransientCraftingContainer.class
                    || container.getClass()==net.minecraft.world.inventory.ResultContainer.class,"placement_unknown_inventory_container");
                require(slot.index==i,"placement_slot_index_changed");
                containers[i]=container;indices[i]=slot.getContainerSlot();items[i]=container.getItem(indices[i]).copy();
            }
        }
        void check(LocalPlayer player) {
            require(player.getInventory()==inventory && player.containerMenu==menu && menu.getStateId()==revision
                && menu.containerId==0 && menu.slots.size()==slots.size() && menu.getCarried().isEmpty(),"placement_raw_menu_changed");
            for(int i=0;i<slots.size();i++) {
                var slot=menu.slots.get(i);
                require(slot==slots.get(i) && slot.index==i && slot.container==containers[i]
                    && sameStack(items[i],containers[i].getItem(indices[i]),effectCount==1 && i==36+selected),"placement_raw_slot_or_stack_changed");
            }
        }
    }
}
