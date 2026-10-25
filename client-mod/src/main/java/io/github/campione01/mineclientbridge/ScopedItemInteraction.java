package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ServerboundUseItemOnPacket;
import net.minecraft.network.protocol.game.ServerboundSetCarriedItemPacket;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.FlintAndSteelItem;
import net.minecraft.world.item.EnderEyeItem;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.GrassBlock;
import net.minecraft.world.level.block.NetherrackBlock;
import net.minecraft.world.level.block.EndPortalFrameBlock;
import net.minecraft.world.level.block.NetherPortalBlock;
import net.minecraft.world.level.block.EndPortalBlock;
import net.minecraft.world.level.block.FireBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

/** One stationary ordinary vanilla item use. All mutations remain in vanilla code. */
final class ScopedItemInteraction {
    static final String PROFILE="item-on-block-observed-v1";
    static final int MAX_TICKS=60,MAX_TIMEOUT=3000;
    private final TypedPortalReaders readers;
    final ClientActionRequest request;
    final LocalPlayer player;final ClientLevel level;
    final BlockPos target,standingSupport;
    final long sourceNano,sourceTick,deadline,navigationEpoch,admissionOwnerRevision;
    final String kind;
    private final Object server,gameMode;
    private final String session,worldGeneration,serverIdentity,commandDigest,dimension;
    private final double x,y,z;private final Vec3 eye;private final AABB body;
    private final float health,saturation;private final int food,selected,initialCount,initialDamage;
    private final Item item;private final ItemStack initial;
    private final List<ItemStack> inventory=new ArrayList<>();
    private final java.util.IdentityHashMap<ItemStack,TypedPortalStack> rawStacks=new java.util.IdentityHashMap<>();
    private final List<BlockPos> positions=new ArrayList<>();private final List<BlockState> states=new ArrayList<>();
    private final java.util.Map<BlockPos,JsonObject> effects=new java.util.HashMap<>();
    private final ScopedFlatPolicy.Bounds bounds;private final JsonObject footprint;
    private final PlacementCallbackFence callbackFence;private final ItemInteractionSettlementPolicy settlement;
    private final ItemInteractionArgumentFence argumentFence=new ItemInteractionArgumentFence();
    private final net.minecraft.world.inventory.AbstractContainerMenu menu;
    private final List<net.minecraft.world.inventory.Slot> slots;
    private final List<ItemStack> menuItems=new ArrayList<>();
    private ActionRegistry.Entry entry;private long ownerRevision;private JsonObject originalWitness;
    private long checkedNano,checkedWorldTick;private boolean checkedPermit;private float checkedYaw,checkedPitch;
    private int checks,lastTick,useCount,itemCalls,itemReturns,localEffectCount,packetCount,selectionPackets;
    private boolean attempted,unknown,returned,checkedConsumption,checkedDurability,checkedBlocks;private int checkedCount,checkedDamage,checkedMenuRevision;private String firstGuardReason="";
    private BlockHitResult dispatchHit;private Vec3 dispatchLocation;private float dispatchYaw,dispatchPitch;
    private ServerboundUseItemOnPacket expectedPacket;private PlacementPacketBinding binding;

    static void validateIntent(JsonObject b){ScopedItemInteractionIntent.validate(b);}
    ScopedItemInteraction(Minecraft mc,ClientActionRequest request,long nano,long tick){
        admissionOwnerRevision=ClientActions.ownershipRevision();
        validateIntent(request.original());require(ScopedItemInteractionDispatch.ready(),"item_interaction_callback_seams_unavailable");TypedPortalReaders.itemContextReaderReady();
        readers=new TypedPortalReaders(mc);this.request=request;sourceNano=nano;sourceTick=tick;deadline=nano+request.timeoutMs()*1000000L;
        player=mc.player;level=mc.level;server=mc.getSingleplayerServer();gameMode=mc.gameMode;session=ClientActions.session();
        worldGeneration=WorldGeneration.current(level);serverIdentity=IntegratedServerIdentity.current(server,CapabilityGuard.privateSingleplayer(mc));
        dimension=level.dimension().location().toString();navigationEpoch=NavigationPositionGuard.epoch();commandDigest=ScopedNativePreflight.digest(request.original());
        kind=ClientActionRequest.string(request.original().getAsJsonObject("typed_item_interaction"),"kind");
        require(kind.equals("insert_end_eye")?dimension.equals("minecraft:overworld"):
            java.util.Set.of("minecraft:overworld","minecraft:the_nether").contains(dimension),"item_interaction_dimension_invalid");
        x=player.getX();y=player.getY();z=player.getZ();eye=player.getEyePosition();body=player.getBoundingBox();
        JsonObject origin=request.original().getAsJsonObject("expected_origin");
        require(origin!=null&&origin.keySet().equals(java.util.Set.of("x","y","z"))&&origin.get("x").getAsDouble()==x&&origin.get("y").getAsDouble()==y&&origin.get("z").getAsDouble()==z
            &&request.original().get("expected_navigation_epoch").getAsLong()==navigationEpoch,"item_interaction_expected_origin_changed");
        health=player.getHealth();food=player.getFoodData().getFoodLevel();saturation=player.getFoodData().getSaturationLevel();
        selected=player.getInventory().selected;initial=player.getMainHandItem().copy();initialCount=initial.getCount();initialDamage=damage(initial);checkedCount=initialCount;checkedDamage=initialDamage;
        item=kind.equals("insert_end_eye")?Items.ENDER_EYE:Items.FLINT_AND_STEEL;
        require(selected>=0&&selected<=8&&initial.getItem()==item&&(kind.equals("insert_end_eye")?item.getClass()==EnderEyeItem.class&&initialCount>=1&&initialCount<=64:
            item.getClass()==FlintAndSteelItem.class&&initialCount==1&&initialDamage>=0&&initialDamage<=62),"item_interaction_exact_selected_item");
        ItemStack plain=item.getDefaultInstance();if(!kind.equals("insert_end_eye"))plain.set(DataComponents.DAMAGE,initialDamage);
        require(new TypedPortalStack(initial).same(plain,false,!kind.equals("insert_end_eye"))&&damage(initial)==damage(plain)
            &&(kind.equals("insert_end_eye")||initial.get(DataComponents.DAMAGE)!=null),"item_interaction_plain_components_required");
        rawStacks.put(initial,new TypedPortalStack(initial));
        target=pos(request.original().getAsJsonObject("target"));standingSupport=BlockPos.containing(x,y-.01,z);
        require(eye.distanceTo(Vec3.atCenterOf(target))<=6&&body.minX>=standingSupport.getX()&&body.maxX<=standingSupport.getX()+1
            &&body.minZ>=standingSupport.getZ()&&body.maxZ<=standingSupport.getZ()+1&&Math.abs(body.minY-standingSupport.getY()-1)<1e-7
            &&body.getYsize()<=1.800001,"item_interaction_stationary_support_required");
        for(int i=0;i<41;i++){var copy=player.getInventory().getItem(i).copy();inventory.add(copy);rawStacks.put(copy,new TypedPortalStack(copy));}
        menu=player.containerMenu;settlement=new ItemInteractionSettlementPolicy(menu.getStateId());slots=List.copyOf(menu.slots);
        require(menu==player.inventoryMenu&&menu.getClass()==InventoryMenu.class&&player.getInventory().getClass()==net.minecraft.world.entity.player.Inventory.class,
            "item_interaction_exact_inventory_required");
        for(int i=0;i<slots.size();i++){var s=slots.get(i);require(s.index==i&&vanillaSlot(s),"item_interaction_unknown_slot");var copy=s.container.getItem(s.getContainerSlot()).copy();menuItems.add(copy);rawStacks.put(copy,new TypedPortalStack(copy));}
        int minX=standingSupport.getX(),maxX=minX,minY=standingSupport.getY(),maxY=minY+3,minZ=standingSupport.getZ(),maxZ=minZ;
        for(var e:request.original().getAsJsonArray("item_footprint")){JsonObject row=e.getAsJsonObject();BlockPos p=pos(row.getAsJsonObject("position"));
            require(effects.put(p,row.deepCopy())==null,"item_interaction_duplicate_dependency");
            minX=Math.min(minX,p.getX());maxX=Math.max(maxX,p.getX());minY=Math.min(minY,p.getY());maxY=Math.max(maxY,p.getY());minZ=Math.min(minZ,p.getZ());maxZ=Math.max(maxZ,p.getZ());
            require(CapabilityPlacement.exact(TypedPortalReaders.block(level,p),row.get("expected_id").getAsString(),row.getAsJsonObject("expected_properties")),"item_interaction_footprint_expectation_changed");
            if(!row.get("expected_id").equals(row.get("block_id"))||!row.get("expected_properties").equals(row.get("properties")))require(!body.intersects(new AABB(p)),"item_interaction_body_intersects_effect");
        }
        bounds=new ScopedFlatPolicy.Bounds(minX-1,minY-1,minZ-1,maxX+1,maxY+1,maxZ+1,standingSupport.getX(),standingSupport.getY()+1,standingSupport.getZ(),target.getX(),target.getZ(),0);
        require(bounds.cells()>0&&bounds.cells()<=512,"item_interaction_footprint_budget");JsonArray cells=new JsonArray();
        for(int cx=bounds.minX();cx<=bounds.maxX();cx++)for(int cy=bounds.minY();cy<=bounds.maxY();cy++)for(int cz=bounds.minZ();cz<=bounds.maxZ();cz++){
            BlockPos p=new BlockPos(cx,cy,cz);BlockState s=readCell(p,false);positions.add(p);states.add(s);cells.add(cell(p,s));}
        footprint=new JsonObject();footprint.addProperty("profile",PROFILE);footprint.addProperty("source","native-client-loaded-level");footprint.addProperty("kind",kind);
        footprint.add("target",ScopedMining.position(target));footprint.add("standing_support",ScopedMining.position(standingSupport));
        footprint.add("typed_item_interaction",request.original().get("typed_item_interaction").deepCopy());footprint.add("item_hit",request.original().get("item_hit").deepCopy());
        footprint.add("item_footprint",request.original().get("item_footprint").deepCopy());footprint.addProperty("selected_slot",selected);footprint.addProperty("initial_count",initialCount);footprint.addProperty("initial_damage",initialDamage);
        for(String a:java.util.Set.of("x","y","z")){footprint.addProperty("min_"+a,a.equals("x")?bounds.minX():a.equals("y")?bounds.minY():bounds.minZ());footprint.addProperty("max_"+a,a.equals("x")?bounds.maxX():a.equals("y")?bounds.maxY():bounds.maxZ());}
        footprint.addProperty("expected_cells",bounds.cells());footprint.add("cells",cells);footprint.addProperty("all_loaded",true);footprint.addProperty("complete",true);footprint.addProperty("callbacks_installed",true);
        footprint.addProperty("maximum_action_ticks",MAX_TICKS);footprint.addProperty("maximum_timeout_ms",MAX_TIMEOUT);footprint.addProperty("deadline_nano",Long.toString(deadline));footprint.add("entity_guard",entities(0).frame.json());
        callbackFence=new PlacementCallbackFence(()->entry==null?ClientActions.ownershipRevision()==admissionOwnerRevision&&!ClientActions.ownsInput():(ClientActions.ownsScopedItemInteraction(this,entry)||ClientActions.terminalItemInteractionCleanup(this,entry)),System::nanoTime,level::getGameTime);admission(mc);
    }
    JsonObject facts(){return footprint.deepCopy();}
    void admission(Minecraft mc){check(mc,false,false);}
    void admissionRawFence(Minecraft mc){require(entry==null,"item_interaction_admission_owner_changed");callbackFence.check(()->raw(mc,false,0,System.nanoTime(),sourceTick,player.getYRot(),player.getXRot()));}
    void activate(ActionRegistry.Entry e){require(entry==null&&e!=null&&e.ticks==0&&ClientActions.ownsScopedItemInteraction(this,e),"item_interaction_activation_changed");entry=e;ownerRevision=ClientActions.ownershipRevision();originalWitness=e.result.getAsJsonObject("scoped_native_preflight").deepCopy();require(commandDigest.equals(originalWitness.get("command_sha256").getAsString()),"item_interaction_digest_changed");}
    private int tick(){if(entry==null)return 0;require((ClientActions.ownsScopedItemInteraction(this,entry)||ClientActions.terminalItemInteractionCleanup(this,entry))&&ownerRevision==ClientActions.ownershipRevision()&&entry.ticks>=lastTick&&entry.ticks-lastTick<=1&&entry.ticks<MAX_TICKS,"item_interaction_owner_or_tick_changed");return entry.ticks;}
    private ScopedMovementEntities entities(int t){var e=ScopedMovementEntities.capture(level,player,bounds,t);e.assertUnchanged();return e;}
    private BlockState readCell(BlockPos p,boolean permit){
        require(level.hasChunkAt(p),"item_interaction_dependency_unloaded");BlockState s=TypedPortalReaders.block(level,p);Block b=s.getBlock();
        boolean air=b==Blocks.AIR||b==Blocks.CAVE_AIR||b==Blocks.VOID_AIR;
        boolean solid=(ScopedMining.LEGACY_TARGETS.contains(b)||b==Blocks.OBSIDIAN||b==Blocks.BEDROCK||b==Blocks.END_STONE)&&b.getClass()==Block.class
            ||b==Blocks.NETHERRACK&&b.getClass()==NetherrackBlock.class||b==Blocks.GRASS_BLOCK&&b.getClass()==GrassBlock.class;
        boolean frame=b==Blocks.END_PORTAL_FRAME&&b.getClass()==EndPortalFrameBlock.class&&effects.containsKey(p);
        boolean effect=permit&&allowedState(p,s,true);
        require((air||solid||frame||effect)&&s.getFluidState().isEmpty()&&blockEntityPermitted(p,s),"item_interaction_unknown_geometry");
        if(air)require(s.getCollisionShape(level,p).isEmpty(),"item_interaction_air_collision_changed");
        if(solid)require(s.isCollisionShapeFullBlock(level,p),"item_interaction_full_cube_required");
        if(p.equals(standingSupport))require(solid,"item_interaction_standing_support_changed");
        if(p.getX()==standingSupport.getX()&&p.getZ()==standingSupport.getZ()&&p.getY()>standingSupport.getY()&&p.getY()<=standingSupport.getY()+2)require(air,"item_interaction_standing_body_changed");return s;
    }
    private boolean blockEntityPermitted(BlockPos p,BlockState s){var e=TypedPortalReaders.blockEntity(level,p);if(s.getBlock()!=Blocks.END_PORTAL)return e==null;
        return effects.containsKey(p)&&allowedState(p,s,false)&&e!=null&&e.getClass()==net.minecraft.world.level.block.entity.TheEndPortalBlockEntity.class
            &&e.getType()==net.minecraft.world.level.block.entity.BlockEntityType.END_PORTAL&&!e.isRemoved()&&e.getLevel()==level&&e.getBlockPos().equals(p)&&e.getBlockState()==s;}
    private boolean allowedState(BlockPos p,BlockState s,boolean transientFire){
        JsonObject row=effects.get(p);if(row==null)return false;
        if(CapabilityPlacement.exact(s,row.get("block_id").getAsString(),row.getAsJsonObject("properties"))){Block b=s.getBlock();return b==Blocks.NETHER_PORTAL&&b.getClass()==NetherPortalBlock.class||b==Blocks.END_PORTAL&&b.getClass()==EndPortalBlock.class||b==Blocks.END_PORTAL_FRAME&&b.getClass()==EndPortalFrameBlock.class||b==Blocks.AIR;}
        return transientFire&&kind.equals("ignite_nether_portal")&&localEffectCount==1&&p.equals(target.above())&&s==Blocks.FIRE.defaultBlockState()&&s.getBlock().getClass()==FireBlock.class;
    }
    void check(Minecraft mc,boolean permit,boolean ray){try{callbackFence.check(()->{
        readers.current(mc);int t=tick();long began=System.nanoTime(),worldTick=level.getGameTime();int revision=menu.getStateId();float yaw=player.getYRot(),pitch=player.getXRot();
        for(int i=0;i<positions.size();i++){BlockState s=readCell(positions.get(i),permit);require(s==states.get(i)||permit&&allowedState(positions.get(i),s,true),"item_interaction_footprint_changed");}
        var entityFrame=entities(t);BlockHitResult hit=null;if(ray){mc.gameRenderer.pick(1);double reach=player.blockInteractionRange();require(Double.isFinite(reach)&&reach>0&&reach<=6&&mc.hitResult!=null&&mc.hitResult.getClass()==BlockHitResult.class,"item_interaction_ray_required");hit=(BlockHitResult)mc.hitResult;require(validHit(hit)&&eye.distanceTo(hit.getLocation())<=reach,"item_interaction_target_not_visible");}
        raw(mc,permit,t,began,worldTick,yaw,pitch);entityFrame.assertUnchanged();require(menu.getStateId()==revision,"item_interaction_revision_changed_in_check");if(hit!=null)require(mc.hitResult==hit&&validHit(hit),"item_interaction_ray_changed_after_hooks");lastTick=t;checks++;
        boolean consumption=consumptionOutcome(),durability=durabilityOutcome(),blocks=blocksOutcome();int count=player.getMainHandItem().getCount(),damage=damage(player.getMainHandItem());readers.current(mc);
        require((entry==null?ClientActions.ownershipRevision()==admissionOwnerRevision&&!ClientActions.ownsInput():(ClientActions.ownsScopedItemInteraction(this,entry)||ClientActions.terminalItemInteractionCleanup(this,entry))&&ownerRevision==ClientActions.ownershipRevision())
            &&mc.player==player&&mc.level==level&&level.getGameTime()==worldTick&&System.nanoTime()<deadline,"item_interaction_outcome_reader_owner_changed");
        checkedConsumption=consumption;checkedDurability=durability;checkedBlocks=blocks;checkedCount=count;checkedDamage=damage;checkedMenuRevision=revision;checkedNano=began;checkedWorldTick=worldTick;checkedPermit=permit;checkedYaw=yaw;checkedPitch=pitch;
        });settlement.commit(checkedMenuRevision,returned&&checkedConsumption&&checkedDurability);}catch(RuntimeException failed){recordFailure(failed);throw failed;}}
    private boolean stack(ItemStack before,ItemStack now,boolean permit){
        TypedPortalStack raw=rawStacks.get(before);require(raw!=null,"item_interaction_raw_stack_missing");
        if(raw.same(now))return true;if(!permit)return false;
        if(kind.equals("insert_end_eye"))return before.getCount()==1?now.isEmpty()&&now.getCount()==0:now.getCount()==before.getCount()-1&&raw.same(now,true,false);
        return now.getItem()==item&&now.getCount()==1&&damage(now)==initialDamage+1&&raw.same(now,false,true);
    }
    private void raw(Minecraft mc,boolean permit,int t,long began,long worldTick,float yaw,float pitch){
        readers.current(mc);player.getInBlockState();player.isSpectator();readers.current(mc);readers.warmEffectiveValues();var boundary=new TypedPortalBoundary(player,level,positions);var policyBoundary=new TypedPortalPolicyBoundary(mc,player,readers);var entityBoundary=entities(t);
        ExternalControllerGuard.requireIdle(mc);NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();
        require(player.getInventory().getClass()==net.minecraft.world.entity.player.Inventory.class&&player.getInventory().getContainerSize()==41&&player.getInventory().selected==selected
            &&player.containerMenu==menu&&menu==player.inventoryMenu&&menu.getClass()==InventoryMenu.class&&menu.getCarried().isEmpty()
            &&settlement.permits(menu.getStateId(),returned,useCount,packetCount,inventoryOutcome()),"item_interaction_menu_or_selection_changed");
        for(int i=0;i<41;i++)require(stack(inventory.get(i),player.getInventory().getItem(i),permit&&i==selected),"item_interaction_inventory_changed");
        require(menu.slots.size()==slots.size(),"item_interaction_slots_changed");for(int i=0;i<slots.size();i++){var s=menu.slots.get(i);require(s==slots.get(i)&&s.index==i&&vanillaSlot(s)&&stack(menuItems.get(i),s.container.getItem(s.getContainerSlot()),permit&&i==36+selected),"item_interaction_raw_slot_changed");}
        for(int i=0;i<positions.size();i++){BlockPos p=positions.get(i);require(level.hasChunkAt(p)&&(TypedPortalReaders.block(level,p)==states.get(i)||permit&&allowedState(p,TypedPortalReaders.block(level,p),true))&&TypedPortalReaders.block(level,p).getFluidState().isEmpty()&&blockEntityPermitted(p,TypedPortalReaders.block(level,p)),"item_interaction_raw_footprint_changed");}
        Vec3 v=player.getDeltaMovement();long now=System.nanoTime();
        require(mc.isSameThread()&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server&&CapabilityGuard.privateSingleplayer(mc)
            &&serverIdentity.equals(IntegratedServerIdentity.current(server,true))&&session.equals(ClientActions.session())&&worldGeneration.equals(WorldGeneration.current(level))
            &&navigationEpoch==NavigationPositionGuard.epoch()&&commandDigest.equals(ScopedNativePreflight.digest(request.original()))&&dimension.equals(level.dimension().location().toString())
            &&now>=began&&now-began<=ScopedNativePreflight.MAX_NANOS&&now>=sourceNano&&now<deadline&&level.getGameTime()==worldTick
            &&mc.gameMode.getPlayerMode()==GameType.SURVIVAL&&!mc.gameMode.isDestroying()&&mc.isWindowActive()&&!mc.isPaused()&&mc.screen==null
            &&player.isAlive()&&!player.isSpectator()&&!player.isPassenger()&&!player.isFallFlying()&&!player.getAbilities().flying&&!player.noPhysics
            &&player.onGround()&&!player.isSprinting()&&!player.isShiftKeyDown()&&!player.isUsingItem()&&!player.onClimbable()&&player.getActiveEffects().isEmpty()
            &&!player.isInWater()&&!player.isEyeInFluid(net.minecraft.tags.FluidTags.WATER)&&!player.isInLava()&&!player.isInPowderSnow&&!player.isOnFire()&&player.hurtTime==0&&player.fallDistance==0
            &&player.getHealth()==health&&player.getFoodData().getFoodLevel()==food&&player.getFoodData().getSaturationLevel()==saturation
            &&player.getX()==x&&player.getY()==y&&player.getZ()==z&&player.getBoundingBox().equals(body)&&player.getEyePosition().equals(eye)
            &&Float.isFinite(yaw)&&Float.isFinite(pitch)&&player.getYRot()==yaw&&player.getXRot()==pitch&&Double.isFinite(v.x)&&Double.isFinite(v.y)&&Double.isFinite(v.z)&&v.horizontalDistance()<=.0001&&v.y>=-.09&&v.y<=0
            &&ScopedMining.neutral(player.input)&&!BridgeServer.hasHeldInputs()
            &&(entry==null?ClientActions.ownershipRevision()==admissionOwnerRevision&&!ClientActions.ownsInput()&&worldTick==sourceTick&&now-sourceNano<=ScopedNativePreflight.MAX_NANOS:(ClientActions.ownsScopedItemInteraction(this,entry)||ClientActions.terminalItemInteractionCleanup(this,entry))
                &&entry.ticks==t&&ownerRevision==ClientActions.ownershipRevision()&&originalWitness.equals(entry.result.get("scoped_native_preflight"))),"item_interaction_final_owner_context_or_deadline_changed");
        if(attempted)require(player.getYRot()==dispatchYaw&&player.getXRot()==dispatchPitch,"item_interaction_dispatch_pose_changed");
        readers.current(mc);entityBoundary.assertUnchanged();readers.current(mc);boundary.unchanged();policyBoundary.unchanged();
        require(mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server&&session.equals(ClientActions.session())
            &&worldGeneration.equals(WorldGeneration.current(level))&&navigationEpoch==NavigationPositionGuard.epoch()&&System.nanoTime()<deadline
            &&System.nanoTime()>=began&&System.nanoTime()-began<=ScopedNativePreflight.MAX_NANOS&&level.getGameTime()==worldTick
            &&(entry==null?ClientActions.ownershipRevision()==admissionOwnerRevision&&!ClientActions.ownsInput():(ClientActions.ownsScopedItemInteraction(this,entry)||ClientActions.terminalItemInteractionCleanup(this,entry))
                &&ownerRevision==ClientActions.ownershipRevision()&&entry.ticks==t&&originalWitness.equals(entry.result.get("scoped_native_preflight"))),"item_interaction_external_reader_changed_owner");
    }
    private boolean validHit(BlockHitResult h){return h!=null&&h.getClass()==BlockHitResult.class&&TypedPortalReaders.hitPositionKnown(h.getBlockPos())&&h.getLocation().getClass()==Vec3.class&&h.getType()==HitResult.Type.BLOCK&&h.getBlockPos().equals(target)&&h.getDirection()==Direction.UP&&!h.isInside()&&h.getLocation().distanceTo(hit())<=.01;}
    private Vec3 hit(){var h=request.original().getAsJsonObject("item_hit");return new Vec3(h.get("x").getAsDouble(),h.get("y").getAsDouble(),h.get("z").getAsDouble());}
    void beforeUse(Minecraft mc,BlockHitResult h){
        require(!attempted&&useCount==0&&packetCount==0,"item_interaction_replay_forbidden");check(mc,false,true);
        require(validHit(h),"item_interaction_hit_changed");dispatchHit=h;dispatchLocation=h.getLocation();dispatchYaw=player.getYRot();dispatchPitch=player.getXRot();
        finalArguments(()->{require(!attempted&&useCount==0&&packetCount==0&&h==dispatchHit,"item_interaction_use_arguments_changed");return argumentFrame(new Object[]{h});});attempted=true;
    }
    void enterUse(LocalPlayer p,InteractionHand h,BlockHitResult hit){
        require(attempted&&useCount==0&&p==player&&h==InteractionHand.MAIN_HAND&&hit==dispatchHit,"item_interaction_recursive_use");check(Minecraft.getInstance(),false,true);
        finalArguments(()->{require(attempted&&useCount==0&&p==player&&h==InteractionHand.MAIN_HAND&&hit==dispatchHit,"item_interaction_use_arguments_changed");return argumentFrame(new Object[]{p,h,hit});});useCount++;
    }
    private void context(Item i,UseOnContext c){
        BlockHitResult hit=TypedPortalReaders.contextHit(c);
        require(hit==dispatchHit&&validHit(hit)&&i==item&&c.getLevel()==level&&c.getPlayer()==player&&c.getHand()==InteractionHand.MAIN_HAND
            &&c.getClickedPos()==hit.getBlockPos()&&c.getClickedPos().equals(target)&&c.getClickedFace()==Direction.UP
            &&c.getClickLocation()==hit.getLocation()&&c.getClickLocation().equals(dispatchLocation)&&c.getItemInHand()==player.getMainHandItem(),"item_interaction_item_context_changed");
    }
    private TypedBoundaryPolicy contextArguments(Item i,UseOnContext c,Object[] extra,long...numbers){
        context(i,c);var references=new java.util.ArrayList<Object>();
        java.util.Collections.addAll(references,i,c,TypedPortalReaders.contextHit(c),c.getLevel(),c.getPlayer(),c.getHand(),c.getItemInHand());
        java.util.Collections.addAll(references,extra);return argumentFrame(references.toArray(),numbers);
    }
    void beforeItemUse(Item i,UseOnContext c){
        context(i,c);require(attempted&&useCount==1&&itemCalls==0&&packetCount==0,"item_interaction_recursive_item_use");check(Minecraft.getInstance(),false,true);
        finalArguments(()->{require(attempted&&useCount==1&&itemCalls==0&&packetCount==0,"item_interaction_item_reentered");return contextArguments(i,c,new Object[0]);});itemCalls++;
    }
    void beforeFlintEffect(Item i,UseOnContext c,net.minecraft.world.level.Level actualLevel,BlockPos p,BlockState state,int flags){
        context(i,c);flintArguments(actualLevel,p,state,flags);check(Minecraft.getInstance(),false,true);
        finalArguments(()->{flintArguments(actualLevel,p,state,flags);return contextArguments(i,c,new Object[]{actualLevel,p,state},flags,p.getX(),p.getY(),p.getZ());});localEffectCount++;
    }
    private void flintArguments(net.minecraft.world.level.Level actualLevel,BlockPos p,BlockState state,int flags){
        require(actualLevel==level&&p!=null&&p.getClass()==BlockPos.class&&flags==11&&kind.equals("ignite_nether_portal")&&itemCalls==1&&localEffectCount==0
            &&packetCount==0&&p.equals(target.above())&&state==Blocks.FIRE.defaultBlockState(),"item_interaction_flint_effect_changed");
    }
    void itemResult(Item i,UseOnContext c,InteractionResult result){
        context(i,c);resultArguments(result);check(Minecraft.getInstance(),true,false);
        finalArguments(()->{resultArguments(result);return contextArguments(i,c,new Object[]{result});});itemReturns++;
    }
    private void resultArguments(InteractionResult result){
        require(itemCalls==1&&itemReturns==0&&result==InteractionResult.SUCCESS&&localEffectCount==(kind.equals("insert_end_eye")?0:1),"item_interaction_typed_result_changed");
    }
    void packet(Packet<?> p){
        if(p instanceof ServerboundSetCarriedItemPacket){selectionArguments((ServerboundSetCarriedItemPacket)p);return;}
        require(p!=null&&p.getClass()==ServerboundUseItemOnPacket.class&&expectedPacket==null&&packetCount==0&&itemReturns==1,"item_interaction_unexpected_packet");
        var wire=(ServerboundUseItemOnPacket)p;packetArguments(wire,null,false);var capturedBinding=packetIdentity(wire);check(Minecraft.getInstance(),true,false);
        finalArguments(()->packetArguments(wire,capturedBinding,false));expectedPacket=wire;binding=capturedBinding;
    }
    void send(Packet<?> p){
        if(p instanceof ServerboundSetCarriedItemPacket selection){
            selectionArguments(selection);check(Minecraft.getInstance(),false,true);finalArguments(()->selectionArguments(selection));selectionPackets++;return;
        }
        require(p==expectedPacket,"item_interaction_send_packet_changed");packetArguments(expectedPacket,binding,true);check(Minecraft.getInstance(),true,false);
        finalArguments(()->{require(p==expectedPacket,"item_interaction_send_packet_changed");return packetArguments(expectedPacket,binding,true);});packetCount++;
    }
    private TypedBoundaryPolicy selectionArguments(ServerboundSetCarriedItemPacket packet){
        require(packet!=null&&packet.getClass()==ServerboundSetCarriedItemPacket.class&&useCount==1&&itemCalls==0&&selectionPackets==0
            &&packet.getSlot()==selected,"item_interaction_selection_packet_changed");return argumentFrame(new Object[]{packet},packet.getSlot());
    }
    private TypedBoundaryPolicy packetArguments(ServerboundUseItemOnPacket packet,PlacementPacketBinding expected,boolean sending){
        require(packet!=null&&packet.getClass()==ServerboundUseItemOnPacket.class&&packetCount==0&&itemReturns==1
            &&(sending?packet==expectedPacket&&expected!=null:expectedPacket==null),"item_interaction_packet_arguments_changed");
        require(packet.getHand()==InteractionHand.MAIN_HAND&&packet.getHitResult()==dispatchHit&&validHit(packet.getHitResult()),"item_interaction_packet_binding_changed");
        if(expected!=null)require(expected.equals(packetIdentity(packet)),"item_interaction_packet_fields_changed");
        return argumentFrame(new Object[]{packet,packet.getHand(),packet.getHitResult()},packet.getSequence());
    }
    private TypedBoundaryPolicy argumentFrame(Object[] extra,long...extraNumbers){
        require(validHit(dispatchHit)&&dispatchHit.getLocation()==dispatchLocation,"item_interaction_dispatch_hit_changed");
        var pos=dispatchHit.getBlockPos();var location=dispatchHit.getLocation();var identities=new java.util.ArrayList<Object>();
        java.util.Collections.addAll(identities,dispatchHit,pos,location,dispatchHit.getDirection(),dispatchHit.getType(),expectedPacket,binding);
        java.util.Collections.addAll(identities,extra);var numbers=new java.util.ArrayList<Long>();
        for(long number:new long[]{pos.getX(),pos.getY(),pos.getZ(),Double.doubleToLongBits(location.x),Double.doubleToLongBits(location.y),Double.doubleToLongBits(location.z),
            dispatchHit.isInside()?1:0,Float.floatToIntBits(dispatchYaw),Float.floatToIntBits(dispatchPitch),attempted?1:0,unknown?1:0,returned?1:0,
            useCount,itemCalls,itemReturns,localEffectCount,packetCount,selectionPackets})numbers.add(number);
        for(long number:extraNumbers)numbers.add(number);
        return new TypedBoundaryPolicy(identities.toArray(),numbers.stream().mapToLong(Long::longValue).toArray());
    }
    private void finalArguments(java.util.function.Supplier<TypedBoundaryPolicy> arguments){
        try{require(!unknown,"item_interaction_unknown_outcome_no_further_effect");argumentFence.check(this::finalBinding,arguments);}
        catch(RuntimeException failed){recordFailure(failed);markUnknown();throw failed;}
    }
    private void finalBinding(){Minecraft mc=Minecraft.getInstance();callbackFence.check(()->{
        raw(mc,checkedPermit,lastTick,checkedNano,checkedWorldTick,checkedYaw,checkedPitch);
        require(entry!=null&&ClientActions.ownsScopedItemInteraction(this,entry)&&ownerRevision==ClientActions.ownershipRevision()
            &&mc.isSameThread()&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server
            &&session.equals(ClientActions.session())&&worldGeneration.equals(WorldGeneration.current(level))&&System.nanoTime()<deadline
            &&System.nanoTime()>=checkedNano&&System.nanoTime()-checkedNano<=ScopedNativePreflight.MAX_NANOS&&level.getGameTime()==checkedWorldTick
            &&originalWitness.equals(entry.result.get("scoped_native_preflight")),"item_interaction_final_effect_binding_changed");
        });}
    void afterUse(){require(!returned&&useCount==1&&itemReturns==1&&packetCount==1,"item_interaction_dispatch_unconfirmed");check(Minecraft.getInstance(),true,false);returned=true;}
    private boolean consumptionOutcome(){ItemStack current=player.getMainHandItem();return kind.equals("insert_end_eye")?(initialCount==1?current.isEmpty()&&current.getCount()==0:current.getCount()==initialCount-1&&rawStacks.get(initial).same(current,true,false)):current.getItem()==item&&current.getCount()==initialCount;}
    private boolean durabilityOutcome(){ItemStack current=player.getMainHandItem();return kind.equals("insert_end_eye")?damage(current)==initialDamage:damage(current)==initialDamage+1&&stack(initial,current,true);}
    private boolean inventoryOutcome(){return consumptionOutcome()&&durabilityOutcome();}
    private boolean blocksOutcome(){for(var e:effects.entrySet())if(!level.hasChunkAt(e.getKey())||!CapabilityPlacement.exact(TypedPortalReaders.block(level,e.getKey()),e.getValue().get("block_id").getAsString(),e.getValue().getAsJsonObject("properties")))return false;return true;}
    boolean settled(){return returned&&packetCount==1&&checkedConsumption&&checkedDurability&&checkedBlocks;}
    boolean cleanupState(boolean success){try{check(Minecraft.getInstance(),attempted,false);return !success||settled();}catch(RuntimeException failed){recordFailure(failed);return false;}}
    boolean releaseBinding(Minecraft mc){return mc.isSameThread()&&mc.player==player&&mc.level==level&&mc.gameMode==gameMode&&mc.getSingleplayerServer()==server&&session.equals(ClientActions.session())&&worldGeneration.equals(WorldGeneration.current(level))&&ownerRevision==ClientActions.ownershipRevision()&&ClientActions.terminalItemInteractionCleanup(this,entry);}
    void recordFailure(RuntimeException failed){if(firstGuardReason.isEmpty())firstGuardReason=failed.getMessage()==null?"item_interaction_check_failed":failed.getMessage();}
    void markUnknown(){unknown=true;}boolean attempted(){return attempted;}
    JsonObject terminal(boolean neutral,boolean success){JsonObject o=new JsonObject();o.addProperty("profile",PROFILE);o.addProperty("kind",kind);o.add("target",ScopedMining.position(target));
        o.addProperty("effect_attempted",attempted);o.addProperty("use_count",useCount);o.addProperty("local_effect_count",localEffectCount);o.addProperty("packet_count",packetCount);o.addProperty("unknown_outcome",unknown);
        o.addProperty("consumption_verified",success&&!unknown&&checkedConsumption);o.addProperty("durability_verified",success&&!unknown&&checkedDurability);o.addProperty("block_outcome_verified",success&&!unknown&&checkedBlocks);
        o.addProperty("input_neutral",neutral);o.addProperty("protected_inventory_unchanged",success&&!unknown);o.addProperty("selected_slot",selected);o.addProperty("initial_count",initialCount);o.addProperty("final_count",checkedCount);
        o.addProperty("initial_damage",initialDamage);o.addProperty("final_damage",checkedDamage);o.addProperty("local_checks",checks);o.addProperty("guard_reason",firstGuardReason);
        o.addProperty("deadline_nano",Long.toString(deadline));o.addProperty("automatic_replay_allowed",false);o.addProperty("server_confirmed",false);return o;}
    private static int damage(ItemStack s){Integer d=s.get(DataComponents.DAMAGE);return d==null?0:d;}
    private static BlockPos pos(JsonObject p){return new BlockPos(p.get("x").getAsInt(),p.get("y").getAsInt(),p.get("z").getAsInt());}
    private static PlacementPacketBinding packetIdentity(ServerboundUseItemOnPacket p){TypedPortalReaderPolicy.exact(p,ServerboundUseItemOnPacket.class);var h=TypedPortalReaderPolicy.exact(p.getHitResult(),BlockHitResult.class);var b=TypedPortalReaders.hitPosition(h.getBlockPos());var v=TypedPortalReaderPolicy.exact(h.getLocation(),Vec3.class);return new PlacementPacketBinding(p.getSequence(),p.getHand().name(),b.getX(),b.getY(),b.getZ(),h.getDirection().name(),v.x,v.y,v.z,h.isInside(),h.getType().name());}
    private static boolean vanillaSlot(net.minecraft.world.inventory.Slot s){var t=s.getClass();var c=s.container.getClass();return (t==net.minecraft.world.inventory.Slot.class||t==net.minecraft.world.inventory.ResultSlot.class||t.getClassLoader()==net.minecraft.world.inventory.Slot.class.getClassLoader()&&(t.getName().equals("net.minecraft.world.inventory.ArmorSlot")||t.getName().equals("net.minecraft.world.inventory.InventoryMenu$1")))&&(c==net.minecraft.world.entity.player.Inventory.class||c==net.minecraft.world.inventory.TransientCraftingContainer.class||c==net.minecraft.world.inventory.ResultContainer.class);}
    private static JsonObject cell(BlockPos p,BlockState s){JsonObject o=ScopedMining.position(p);o.addProperty("id",BuiltInRegistries.BLOCK.getKey(s.getBlock()).toString());o.addProperty("state",s.toString());o.addProperty("block_class",s.getBlock().getClass().getName());o.addProperty("loaded",true);o.addProperty("fluid","minecraft:empty");JsonObject props=new JsonObject();for(var e:s.getValues().entrySet())props.addProperty(e.getKey().getName(),e.getValue().toString());o.add("properties",props);return o;}
    static void require(boolean ok,String reason){ScopedItemInteractionIntent.need(ok,reason);}
}
