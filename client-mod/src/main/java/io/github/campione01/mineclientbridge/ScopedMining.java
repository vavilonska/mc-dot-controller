package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.Input;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.inventory.InventoryMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.GrassBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

/** Attached validator for the existing ClientActions mining owner, never another writer. */
final class ScopedMining {
    static final String PROFILE="mining-local-observed-v2";
    static final Set<Block> LEGACY_TARGETS=Set.of(Blocks.STONE,Blocks.COBBLESTONE,Blocks.DIRT,Blocks.ANDESITE,
        Blocks.GRANITE,Blocks.DIORITE,Blocks.SMOOTH_STONE,Blocks.STONE_BRICKS,Blocks.BRICKS,
        Blocks.OAK_PLANKS,Blocks.SPRUCE_PLANKS,Blocks.BIRCH_PLANKS);
    static final Set<Block> TARGETS=java.util.stream.Stream.concat(LEGACY_TARGETS.stream(),java.util.stream.Stream.of(
        Blocks.OAK_LOG,Blocks.SPRUCE_LOG,Blocks.BIRCH_LOG,Blocks.JUNGLE_LOG,Blocks.ACACIA_LOG,Blocks.DARK_OAK_LOG,Blocks.MANGROVE_LOG,
        Blocks.IRON_ORE,Blocks.DEEPSLATE_IRON_ORE)).collect(java.util.stream.Collectors.toUnmodifiableSet());
    private static final Set<Block> CELLS=java.util.stream.Stream.concat(TARGETS.stream(),java.util.stream.Stream.of(
        Blocks.AIR,Blocks.CAVE_AIR,Blocks.VOID_AIR,Blocks.GRASS_BLOCK,Blocks.BEDROCK,Blocks.DEEPSLATE,
        Blocks.COAL_ORE,Blocks.DEEPSLATE_COAL_ORE,
        Blocks.OAK_LEAVES,Blocks.SPRUCE_LEAVES,Blocks.BIRCH_LEAVES,Blocks.JUNGLE_LEAVES,Blocks.ACACIA_LEAVES,Blocks.DARK_OAK_LEAVES,Blocks.MANGROVE_LEAVES,
        Blocks.SHORT_GRASS,Blocks.FERN,Blocks.TALL_GRASS,Blocks.LARGE_FERN,Blocks.VINE,
        Blocks.DANDELION,Blocks.POPPY,Blocks.BLUE_ORCHID,Blocks.ALLIUM,Blocks.AZURE_BLUET,Blocks.RED_TULIP,Blocks.ORANGE_TULIP,
        Blocks.WHITE_TULIP,Blocks.PINK_TULIP,Blocks.OXEYE_DAISY,Blocks.CORNFLOWER,Blocks.LILY_OF_THE_VALLEY))
        .collect(java.util.stream.Collectors.toUnmodifiableSet());
    final LocalPlayer player; final ClientLevel level; final BlockPos target, support;
    final long sourceNano, sourceTick, deadline, navigationEpoch;
    final JsonObject footprint;
    final ClientActionRequest request;
    private final String commandDigest;
    private final BlockState expectedTargetState;
    private JsonObject originalWitness;
    private final Object server, gameMode;
    private final String session,worldGeneration,serverIdentity;
    private final double x,y,z,eyeX,eyeY,eyeZ;
    private final float health,initialYaw,initialPitch;
    private final net.minecraft.world.phys.AABB body;
    private final int selected,menuState;
    private final List<ItemStack> inventory=new ArrayList<>();
    private final RawMenu rawMenu;
    private final List<Boolean> mayPickup=new ArrayList<>(),mayPlace=new ArrayList<>();
    private final int food;
    private final float saturation;
    private final List<BlockPos> positions=new ArrayList<>();
    private final List<BlockState> states=new ArrayList<>();
    private long ownerRevision;
    private boolean activated, attempted, unknown, removed;
    private int checks;
    private int observedPassiveItems;
    private ScopedFlatPolicy.Bounds entityBounds;
    private ScopedMiningEntities admissionEntities;
    private ActionRegistry.Entry actionEntry;
    private int sampleActionTick;
    private JsonObject result;
    private BlockHitResult lastHit;
    private float lastRayYaw,lastRayPitch;
    private double lastReach;

    ScopedMining(Minecraft mc,ClientActionRequest request,long nano,long tick) {
        this.request=request;commandDigest=ScopedNativePreflight.digest(request.original());sourceNano=nano;sourceTick=tick;deadline=nano+request.timeoutMs()*1_000_000L;
        require(ScopedMiningDispatch.ready(),"mining_callback_seams_unavailable");
        require(!mc.gameMode.isDestroying(),"mining_existing_destroy_progress_forbidden");
        require(request.action().equals("break_block") && request.timeoutMs()>0 && request.timeoutMs()<=8000
            && request.hotbarSlot()==-1 && !request.jump() && !request.sneak()
            && request.original().has("expected_block_properties")
            && ScopedMiningCellPolicy.target(ClientActionRequest.string(request.original(),"expected_block_id"),
                request.original().getAsJsonObject("expected_block_properties"))
            && !request.original().has("capability_descent") && !request.original().has("coordination_step"),
            "mining_request_outside_profile");
        player=mc.player;level=mc.level;server=mc.getSingleplayerServer();gameMode=mc.gameMode;
        session=ClientActions.session();worldGeneration=WorldGeneration.current(level);
        serverIdentity=IntegratedServerIdentity.current(server,CapabilityGuard.privateSingleplayer(mc));
        navigationEpoch=NavigationPositionGuard.epoch();
        x=player.getX();y=player.getY();z=player.getZ();var eye=player.getEyePosition();eyeX=eye.x;eyeY=eye.y;eyeZ=eye.z;
        health=player.getHealth();initialYaw=player.getYRot();initialPitch=player.getXRot();body=player.getBoundingBox();food=player.getFoodData().getFoodLevel();saturation=player.getFoodData().getSaturationLevel();selected=player.getInventory().selected;menuState=player.containerMenu.getStateId();
        target=new BlockPos(request.target().x(),request.target().y(),request.target().z());
        support=BlockPos.containing(x,y-.01,z);
        require(!(target.getX()==support.getX() && target.getZ()==support.getZ()),"mining_player_column_forbidden");
        require(level.hasChunkAt(target),"mining_target_unloaded");
        var state=level.getBlockState(target);expectedTargetState=state;
        require(TARGETS.contains(state.getBlock()) && exactCellState(state)
            && BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString().equals(ClientActionRequest.string(request.original(),"expected_block_id"))
            && properties(state).equals(request.original().getAsJsonObject("expected_block_properties")),"mining_exact_target_changed");
        for(int i=0;i<41;i++)inventory.add(player.getInventory().getItem(i).copy());
        rawMenu=new RawMenu(player,selected);
        require(player.containerMenu.slots.size()==46,"mining_inventory_menu_coverage");
        for(var slot:player.containerMenu.slots) {
            mayPickup.add(slot.mayPickup(player));
            mayPlace.add(slot.mayPlace(player.containerMenu.getCarried()));
        }
        restrictions(mc);
        require(body.minX>=support.getX() && body.maxX<=support.getX()+1 && body.minZ>=support.getZ()
            && body.maxZ<=support.getZ()+1 && Math.abs(body.minY-support.getY()-1)<1e-7
            && body.getYsize()<=1.800001,"mining_single_support_required");
        int minX=Math.min(support.getX(),target.getX())-1,maxX=Math.max(support.getX(),target.getX())+1;
        int minY=Math.min(support.getY(),target.getY()-1),maxY=Math.max(support.getY()+3,target.getY()+1);
        int minZ=Math.min(support.getZ(),target.getZ())-1,maxZ=Math.max(support.getZ(),target.getZ())+1;
        entityBounds=new ScopedFlatPolicy.Bounds(minX,minY,minZ,maxX,maxY,maxZ,support.getX(),support.getY()+1,support.getZ(),target.getX(),target.getZ(),0);
        admissionEntities=ScopedMiningEntities.capture(level,player,entityBounds,0);
        long count=(long)(maxX-minX+1)*(maxY-minY+1)*(maxZ-minZ+1);
        require(count>0 && count<=512,"mining_footprint_over_bound");
        JsonArray cells=new JsonArray();
        for(int cx=minX;cx<=maxX;cx++)for(int cy=minY;cy<=maxY;cy++)for(int cz=minZ;cz<=maxZ;cz++) {
            BlockPos p=new BlockPos(cx,cy,cz);positions.add(p);states.add(readCell(p));cells.add(cell(p,states.get(states.size()-1)));
        }
        footprint=new JsonObject();footprint.addProperty("profile",PROFILE);footprint.addProperty("source","native-client-loaded-level");
        footprint.add("target",position(target));footprint.add("support",position(support));
        footprint.addProperty("min_x",minX);footprint.addProperty("max_x",maxX);footprint.addProperty("min_y",minY);
        footprint.addProperty("max_y",maxY);footprint.addProperty("min_z",minZ);footprint.addProperty("max_z",maxZ);
        footprint.addProperty("expected_cells",count);footprint.add("cells",cells);
        footprint.addProperty("all_loaded",true);footprint.addProperty("stationary",true);footprint.addProperty("survival",true);
        footprint.addProperty("entity_scope","all-client-loaded-mining-prism-with-passive-items");
        footprint.addProperty("entity_policy","mining-observed-items-v1");
        footprint.addProperty("other_entities",0);footprint.addProperty("passive_items",0);
        footprint.addProperty("entity_limit",1024);footprint.addProperty("closed_inventory",true);
        footprint.addProperty("target_static_class",state.getBlock().getClass().getName());
        footprint.addProperty("require_correct_tool",ClientActionRequest.bool(request.original(),"require_correct_tool",false));
        footprint.addProperty("deadline_nano",Long.toString(deadline));footprint.addProperty("maximum_reach",6);
        footprint.add("eye",vector(eye));footprint.add("velocity",vector(player.getDeltaMovement()));
        footprint.addProperty("callbacks_installed",true);
        admissionBeforeFacts(mc);
        rawFence(mc,false,false,null,0,sourceTick,initialYaw,initialPitch,0,sourceNano);
        footprint.addProperty("other_entities",admissionEntities.frame.rows().stream().filter(r->!r.removed()).count());
        footprint.add("entity_guard",admissionEntities.frame.json());
        footprint.addProperty("maximum_action_ticks",160);
        footprint.addProperty("maximum_timeout_ms",8000);
        footprint.addProperty("passive_items",observedPassiveItems);
    }
    void activate(ActionRegistry.Entry entry){
        require(!activated && actionEntry==null && entry!=null && entry.running() && entry.ticks==0
            && entry.request.id().equals(request.id()) && entry.request.action().equals(request.action())
            && entry.request.timeoutMs()==request.timeoutMs() && ClientActions.ownsScopedMining(this,entry),
            "mining_activation_changed");
        actionEntry=entry;this.result=entry.result;originalWitness=result.getAsJsonObject("scoped_native_preflight").deepCopy();
        require(commandDigest.equals(originalWitness.get("command_sha256").getAsString()),"mining_actual_command_digest_changed");
        ownerRevision=ClientActions.ownershipRevision();activated=true;
    }
    void markAttempted(){attempted=true;}
    boolean removalAdmissible(){return attempted && lastHit!=null;}
    void markUnknown(){unknown=true;if(result!=null){result.addProperty("unknown_outcome",true);
        if(result.has("mining")){result.getAsJsonObject("mining").addProperty("unknown_outcome",true);
            result.getAsJsonObject("mining").addProperty("block_removed",false);}}}
    JsonObject facts(){return footprint.deepCopy();}
    boolean targetAir(){return level.hasChunkAt(target) && level.getBlockState(target).isAir();}
    void admissionBeforeFacts(Minecraft mc) {checkFacts(mc,false,0);}
    void admissionAfterFacts(Minecraft mc) {rawFence(mc,false,false,null,0,sourceTick,initialYaw,initialPitch,0,sourceNano);}

    /** All callbacks (tool/shape/ray) run before the final raw-state and owner fence. */
    void check(Minecraft mc,boolean permitAir,boolean pick) {
        long began=System.nanoTime(),checkTick=level.getGameTime();
        int actionTick=actionTicks();
        float yaw=player.getYRot(),pitch=player.getXRot();
        checkFacts(mc,permitAir,actionTick);
        BlockHitResult hit=null;double reach=0;
        if(!targetAir() && pick) {
            reach=player.blockInteractionRange();
            require(Double.isFinite(reach) && reach>0 && reach<=6,"mining_reach_unsupported");
            mc.gameRenderer.pick(1.0F);
            require(mc.hitResult!=null && mc.hitResult.getClass()==BlockHitResult.class,"mining_exact_ray_required");
            reach=player.blockInteractionRange(); // Last hook-bearing reach read, after renderer picking.
            require(Double.isFinite(reach) && reach>0 && reach<=6,"mining_reach_changed_after_ray");
            hit=(BlockHitResult)mc.hitResult;
            require(hit.getType()==HitResult.Type.BLOCK && hit.getBlockPos().equals(target) && !hit.isInside()
                && player.getEyePosition().distanceTo(hit.getLocation())<=reach,"mining_target_not_visible_or_reachable");
        }
        require(System.nanoTime()-began>=0 && System.nanoTime()-began<=ScopedNativePreflight.MAX_NANOS,"mining_check_budget_exceeded");
        rawFence(mc,true,permitAir,hit,reach,checkTick,yaw,pitch,actionTick,began);
        sampleActionTick=actionTick;
        if(hit!=null){lastHit=hit;lastRayYaw=yaw;lastRayPitch=pitch;lastReach=reach;}
        checks++;
    }
    private void checkFacts(Minecraft mc,boolean permitAir,int actionTick) {
        restrictions(mc);
        for(int i=0;i<positions.size();i++) {
            BlockPos p=positions.get(i);BlockState now=readCell(p);
            require(now==states.get(i) || permitAir && p.equals(target) && now.isAir(),"mining_footprint_changed");
        }
        var block=level.getBlockState(target);
        require(!block.isAir() || permitAir,"mining_target_replaced_or_absent");
        if(!block.isAir()) {
            require(!ClientActionRequest.bool(request.original(),"require_correct_tool",false) || player.hasCorrectToolForDrops(block),
                    "mining_correct_tool_required");
            float progress=block.getDestroyProgress(player,level,target);
            require(Float.isFinite(progress) && progress>0,"mining_unbreakable_or_tool_invalid");
        }
        for(int i=0;i<player.containerMenu.slots.size();i++) {
            var slot=player.containerMenu.slots.get(i);
            require(slot.mayPickup(player)==mayPickup.get(i) && slot.mayPlace(player.containerMenu.getCarried())==mayPlace.get(i),
                "mining_menu_permissions_changed");
        }
        entities(actionTick);
    }
    private BlockState readCell(BlockPos p) {
        require(level.hasChunkAt(p),"mining_dependency_unloaded");var state=level.getBlockState(p);var b=state.getBlock();
        String id=BuiltInRegistries.BLOCK.getKey(b).toString();
        boolean air=ScopedMiningCellPolicy.AIR.contains(id), plant=ScopedMiningCellPolicy.PLANTS.contains(id);
        require(exactCellState(state),"mining_position_dependent_or_hazard_geometry_unsupported");
        require(state.getFluidState().isEmpty() && level.getBlockEntity(p)==null,"mining_fluid_or_block_entity_unsupported");
        require(air ? state.getCollisionShape(level,p).isEmpty() && state.getShape(level,p).isEmpty()
                : plant ? state.getCollisionShape(level,p).isEmpty()
                : state.isCollisionShapeFullBlock(level,p) && state.getShape(level,p).bounds().equals(new net.minecraft.world.phys.AABB(0,0,0,1,1,1)),
                "mining_nonstatic_shape");
        if(p.equals(support))require(!air && !plant && !ScopedMiningCellPolicy.LEAVES.contains(id),"mining_support_missing");
        if(p.getX()==support.getX() && p.getZ()==support.getZ() && p.getY()>support.getY() && p.getY()<=support.getY()+2)
            require(ScopedMiningCellPolicy.bodyClear(id),"mining_body_not_clear");
        return state;
    }
    private void restrictions(Minecraft mc) {
        require(mc.player==player && mc.level==level && mc.gameMode==gameMode && CapabilityGuard.privateSingleplayer(mc)
            && mc.gameMode.getPlayerMode()==GameType.SURVIVAL && level.dimension().location().toString().equals("minecraft:overworld"),
            "mining_private_overworld_survival_required");
        require(player.containerMenu==player.inventoryMenu && player.containerMenu.getClass()==InventoryMenu.class
            && player.containerMenu.getCarried().isEmpty() && mc.screen==null && !player.isUsingItem(),"mining_closed_inventory_required");
        var v=player.getDeltaMovement();
        require(player.isAlive() && !player.isSpectator() && !player.isPassenger() && !player.isFallFlying()
            && !player.getAbilities().flying && !player.noPhysics && player.onGround() && !player.isSprinting()
            && !player.isShiftKeyDown() && !player.onClimbable() && player.getActiveEffects().isEmpty()
            && !player.isInWater() && !player.isEyeInFluid(net.minecraft.tags.FluidTags.WATER) && !player.isInLava()
            && !player.isInPowderSnow && !player.isOnFire() && player.hurtTime==0 && player.fallDistance==0
            && player.getHealth()==health && Double.isFinite(v.x) && Double.isFinite(v.y) && Double.isFinite(v.z)
            && v.horizontalDistance()<=.0001 && v.y>=-.09 && v.y<=0 && player.getX()==x && player.getY()==y && player.getZ()==z,
            "mining_player_or_motion_changed");
        require(player.getInventory().getContainerSize()==41 && player.getInventory().selected==selected,"mining_tool_selection_changed");
        rawInventory();
    }
    private void rawInventory() {
        require(player.getInventory().getClass()==net.minecraft.world.entity.player.Inventory.class
            && player.containerMenu==player.inventoryMenu && player.containerMenu.getStateId()==menuState
            && player.containerMenu.getCarried().isEmpty() && player.getInventory().selected==selected,"mining_menu_or_selection_changed");
        for(int i=0;i<41;i++)require(sameStack(inventory.get(i),player.getInventory().getItem(i),i==selected),
            "mining_inventory_or_tool_changed");
    }
    /** Read DataComponents.DAMAGE directly: ItemStack.getDamageValue invokes Item.getDamage hooks. */
    private static boolean sameStack(ItemStack old,ItemStack actual,boolean permitDamage) {
        ItemStack current=actual.copy();
        Integer oldDamage=old.get(net.minecraft.core.component.DataComponents.DAMAGE);
        Integer damage=current.get(net.minecraft.core.component.DataComponents.DAMAGE);
        if(permitDamage && oldDamage!=null) {
            if(damage==null || damage<oldDamage)return false;
            current.set(net.minecraft.core.component.DataComponents.DAMAGE,oldDamage);
        }
        return ItemStack.matches(old,current);
    }
    /** Exact vanilla slot/container identities, with no virtual Slot getter in the final fence. */
    private static final class RawMenu {
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
                "mining_exact_vanilla_inventory_required");
            slots=List.copyOf(menu.slots);containers=new net.minecraft.world.Container[slots.size()];
            indices=new int[slots.size()];items=new ItemStack[slots.size()];revision=menu.getStateId();
            for(int i=0;i<slots.size();i++) {
                var slot=slots.get(i);var type=slot.getClass();var container=slot.container;
                require(type==net.minecraft.world.inventory.Slot.class || type==net.minecraft.world.inventory.ResultSlot.class
                    || type.getClassLoader()==net.minecraft.world.inventory.Slot.class.getClassLoader()
                        && (type.getName().equals("net.minecraft.world.inventory.ArmorSlot")
                            || type.getName().equals("net.minecraft.world.inventory.InventoryMenu$1")),
                    "mining_unknown_inventory_slot");
                require(container.getClass()==net.minecraft.world.entity.player.Inventory.class
                    || container.getClass()==net.minecraft.world.inventory.TransientCraftingContainer.class
                    || container.getClass()==net.minecraft.world.inventory.ResultContainer.class,"mining_unknown_inventory_container");
                require(slot.index==i,"mining_slot_index_changed");
                containers[i]=container;indices[i]=slot.getContainerSlot();items[i]=container.getItem(indices[i]).copy();
            }
        }
        void check(LocalPlayer player) {
            require(player.getInventory()==inventory && player.containerMenu==menu && menu.getStateId()==revision
                && menu.containerId==0 && menu.slots.size()==slots.size() && menu.getCarried().isEmpty(),"mining_raw_menu_changed");
            for(int i=0;i<slots.size();i++) {
                var slot=menu.slots.get(i);
                require(slot==slots.get(i) && slot.index==i && slot.container==containers[i]
                    && sameStack(items[i],containers[i].getItem(indices[i]),i==36+selected),"mining_raw_slot_or_stack_changed");
            }
        }
    }
    private int actionTicks() {
        require(activated && actionEntry!=null && ClientActions.ownsScopedMining(this,actionEntry)
            && ClientActions.ownershipRevision()==ownerRevision,"mining_action_owner_changed");
        int tick=actionEntry.ticks;
        require(tick>=0 && tick<160 && tick>=sampleActionTick && tick-sampleActionTick<=1,"mining_action_tick_gap_or_budget");
        return tick;
    }
    private void entities(int tick) {
        require(!activated && tick==0 || activated && actionTicks()==tick,"mining_entity_action_tick_changed");
        ScopedMiningEntities current=ScopedMiningEntities.capture(level,player,entityBounds,tick);
        current.assertUnchanged();
        if(!activated)admissionEntities.assertUnchanged();
        observedPassiveItems=(int)current.frame.rows().stream().filter(r->!r.removed() && r.type().equals("minecraft:item")).count();

    }
    private void rawFence(Minecraft mc,boolean owned,boolean permitAir,BlockHitResult hit,double reach,long checkTick,float yaw,float pitch,int actionTick,long checkBegan) {
        rawInventory();rawMenu.check(player);
        require(commandDigest.equals(ScopedNativePreflight.digest(request.original()))
            && (!owned || originalWitness!=null && originalWitness.equals(result.get("scoped_native_preflight"))),
            "mining_original_command_scope_witness_changed");
        for(int i=0;i<positions.size();i++) {
            BlockPos p=positions.get(i);require(level.hasChunkAt(p),"mining_loaded_context_changed_after_hooks");
            BlockState now=level.getBlockState(p);
            require((now==states.get(i) || permitAir && p.equals(target) && now.isAir()) && now.getFluidState().isEmpty()
                && level.getBlockEntity(p)==null,"mining_footprint_changed_after_hooks");
        }
        entities(actionTick);var v=player.getDeltaMovement();var eye=player.getEyePosition();long now=System.nanoTime();
        require((!owned || actionEntry!=null && ClientActions.ownsScopedMining(this,actionEntry)
                && actionEntry.ticks==actionTick && actionTicks()==actionTick)
            && now>=checkBegan && now-checkBegan<=ScopedNativePreflight.MAX_NANOS
            && mc.isSameThread() && mc.player==player && mc.level==level && mc.gameMode==gameMode
            && mc.getSingleplayerServer()==server && serverIdentity.equals(IntegratedServerIdentity.current(server,true))
            && worldGeneration.equals(WorldGeneration.current(level)) && ClientActions.session().equals(session)
            && NavigationPositionGuard.epoch()==navigationEpoch && now>=sourceNano && now<deadline && level.getGameTime()==checkTick
            && mc.isWindowActive() && !mc.isPaused() && mc.screen==null && player.isAlive() && !player.isSpectator()
            && mc.gameMode.getPlayerMode()==GameType.SURVIVAL && player.getYRot()==yaw && player.getXRot()==pitch
            && player.getBoundingBox().equals(body) && player.getX()==x && player.getY()==y && player.getZ()==z
            && eye.x==eyeX && eye.y==eyeY && eye.z==eyeZ && player.getHealth()==health && player.hurtTime==0
            && player.getFoodData().getFoodLevel()==food && player.getFoodData().getSaturationLevel()==saturation
            && player.onGround() && !player.isPassenger() && !player.isFallFlying() && !player.getAbilities().flying
            && !player.noPhysics && !player.isSprinting() && !player.isShiftKeyDown() && !player.isUsingItem()
            && player.getActiveEffects().isEmpty() && !player.isInWater() && !player.isInLava() && !player.isInPowderSnow
            && !player.isOnFire() && player.fallDistance==0 && Double.isFinite(v.x) && Double.isFinite(v.y) && Double.isFinite(v.z)
            && v.horizontalDistance()<=.0001 && v.y>=-.09 && v.y<=0 && !otherKeys(mc) && !BridgeServer.hasHeldInputs()
            && (owned ? activated && ClientActions.ownsScopedMining(this) && ClientActions.ownershipRevision()==ownerRevision
                : !ClientActions.ownsInput() && level.getGameTime()==sourceTick && now-sourceNano<=ScopedNativePreflight.MAX_NANOS),
            "mining_final_owner_player_or_deadline_changed");
        if(hit!=null)require(mc.hitResult==hit && hit.getType()==HitResult.Type.BLOCK && hit.getBlockPos().equals(target)
            && !hit.isInside() && eye.distanceTo(hit.getLocation())<=reach,"mining_final_hit_changed");
    }
    void packet(Minecraft mc,net.minecraft.network.protocol.Packet<?> packet,int sequence,
                net.minecraft.core.Direction direction,net.minecraft.network.protocol.game.ServerboundPlayerActionPacket.Action action) {
        require(packet instanceof net.minecraft.network.protocol.game.ServerboundPlayerActionPacket,"mining_wrong_packet_type");
        var p=(net.minecraft.network.protocol.game.ServerboundPlayerActionPacket)packet;
        require(p.getPos().equals(target) && p.getDirection()==direction && p.getAction()==action && p.getSequence()==sequence,
            "mining_returned_packet_identity_changed");
        require(lastHit!=null && lastHit.getBlockPos().equals(target) && lastHit.getDirection()==direction,
            "mining_packet_ray_binding_missing");
        boolean air=targetAir();
        check(mc,air,!air);
        require(lastHit!=null && lastHit.getBlockPos().equals(target) && lastHit.getDirection()==direction,
            "mining_final_packet_ray_changed");
        if(air){require(attempted && player.getYRot()==lastRayYaw && player.getXRot()==lastRayPitch,
            "mining_predicted_air_ray_changed");removed=true;}
    }
    void beforeRemoval(BlockState receiver,net.minecraft.world.level.Level suppliedLevel,BlockPos pos,
            net.minecraft.world.entity.player.Player suppliedPlayer,boolean harvest,net.minecraft.world.level.material.FluidState fluid) {
        require(receiver==expectedTargetState && suppliedLevel==level && suppliedPlayer==player && pos.equals(target)
            && !harvest && fluid.isEmpty(),"mining_removal_receiver_or_arguments_changed");
        check(Minecraft.getInstance(),false,true);
        require(level.getBlockState(target)==receiver && level.getFluidState(target)==fluid,
            "mining_removal_state_changed_after_hooks");
    }
    void progressAbortPacket(Minecraft mc,net.minecraft.network.protocol.Packet<?> packet) {
        require(packet instanceof net.minecraft.network.protocol.game.ServerboundPlayerActionPacket,"mining_progress_abort_type");
        var p=(net.minecraft.network.protocol.game.ServerboundPlayerActionPacket)packet;
        require(p.getPos().equals(target) && p.getAction()==net.minecraft.network.protocol.game.ServerboundPlayerActionPacket.Action.ABORT_DESTROY_BLOCK
            && p.getDirection()==net.minecraft.core.Direction.DOWN && p.getSequence()==0,"mining_progress_abort_binding");
        check(mc,false,true);
    }
    void abortPacket(Minecraft mc,net.minecraft.network.protocol.Packet<?> packet) {
        require(packet instanceof net.minecraft.network.protocol.game.ServerboundPlayerActionPacket,"mining_abort_packet_type");
        var p=(net.minecraft.network.protocol.game.ServerboundPlayerActionPacket)packet;
        require(p.getPos().equals(target) && p.getAction()==net.minecraft.network.protocol.game.ServerboundPlayerActionPacket.Action.ABORT_DESTROY_BLOCK
            && p.getDirection()==net.minecraft.core.Direction.DOWN && p.getSequence()==0
            && mc.gameMode==gameMode && mc.level==level && mc.player==player
            && ClientActions.ownershipRevision()==ownerRevision && !ClientActions.ownsInput(),"mining_abort_binding_changed");
    }
    static boolean otherKeys(Minecraft mc){return mc.options.keyUp.isDown() || mc.options.keyDown.isDown()
        || mc.options.keyLeft.isDown() || mc.options.keyRight.isDown() || mc.options.keyJump.isDown()
        || mc.options.keyShift.isDown() || mc.options.keySprint.isDown() || mc.options.keyUse.isDown();}
    static boolean neutral(Input i){return i==null || i.forwardImpulse==0 && i.leftImpulse==0
        && !i.up && !i.down && !i.left && !i.right && !i.jumping && !i.shiftKeyDown;}
    JsonObject terminal(boolean neutral,boolean blockRemoved) {
        JsonObject out=new JsonObject();out.addProperty("profile",PROFILE);out.add("target",position(target));
        out.addProperty("effect_attempted",attempted);out.addProperty("unknown_outcome",unknown);
        out.addProperty("block_removed",blockRemoved && !unknown);out.addProperty("server_confirmed",false);
        out.addProperty("input_neutral",neutral);out.addProperty("local_checks",checks);
        out.addProperty("deadline_nano",Long.toString(deadline));out.addProperty("drops_or_pickup_proven",false);
        out.addProperty("entity_policy","mining-observed-items-v1");
        out.addProperty("observed_passive_items",observedPassiveItems);
        out.addProperty("last_entity_check_action_tick",sampleActionTick);
        out.addProperty("maximum_action_ticks",160);
        out.addProperty("future_dynamics_certified",false);
        if(lastHit!=null){JsonObject ray=new JsonObject();ray.add("target",position(lastHit.getBlockPos()));
            ray.addProperty("face",lastHit.getDirection().getName());ray.add("hit",vector(lastHit.getLocation()));
            ray.add("eye",vector(new Vec3(eyeX,eyeY,eyeZ)));ray.addProperty("reach",lastReach);
            ray.addProperty("yaw",lastRayYaw);ray.addProperty("pitch",lastRayPitch);out.add("final_ray",ray);}
        return out;
    }
    private static JsonObject cell(BlockPos p,BlockState s) {
        JsonObject out=position(p);out.addProperty("id",BuiltInRegistries.BLOCK.getKey(s.getBlock()).toString());
        out.addProperty("state",s.toString());out.addProperty("loaded",true);out.addProperty("fluid","minecraft:empty");
        out.addProperty("air",s.isAir());out.addProperty("static_full_cube",!s.isAir() && !ScopedMiningCellPolicy.PLANTS.contains(BuiltInRegistries.BLOCK.getKey(s.getBlock()).toString()));out.addProperty("block_class",s.getBlock().getClass().getName());
        out.add("properties",properties(s));return out;
    }
    static JsonObject properties(BlockState state) {
        JsonObject out=new JsonObject();for(var entry:state.getValues().entrySet())
            out.addProperty(entry.getKey().getName(),entry.getValue().toString());
        return out;
    }
    static boolean exactCellState(BlockState state) {
        Block block=state.getBlock();String id=BuiltInRegistries.BLOCK.getKey(block).toString();
        return CELLS.contains(block) && block.getClass().getClassLoader()==Block.class.getClassLoader()
            && ScopedMiningCellPolicy.accepts(id,block.getClass().getName(),properties(state));
    }
    static JsonObject position(BlockPos p){JsonObject o=new JsonObject();o.addProperty("x",p.getX());o.addProperty("y",p.getY());o.addProperty("z",p.getZ());return o;}
    static JsonObject vector(Vec3 v){JsonObject o=new JsonObject();o.addProperty("x",v.x);o.addProperty("y",v.y);o.addProperty("z",v.z);return o;}
    static final class Refused extends RuntimeException {Refused(String reason){super(reason);}}
    static void require(boolean condition,String reason){if(!condition)throw new Refused(reason);}
}
