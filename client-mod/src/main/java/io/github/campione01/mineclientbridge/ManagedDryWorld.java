package io.github.campione01.mineclientbridge;

import java.lang.reflect.Field;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientChunkCache;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Holder;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.world.entity.Pose;
import net.minecraft.world.entity.ai.attributes.*;
import net.minecraft.world.entity.player.Abilities;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.chunk.*;
import net.minecraft.world.level.material.Fluids;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.Shapes;

/** Raw cached-cell and concrete player readers; never invokes a block's shape/fluid callback. */
final class ManagedDryWorld {
    private static final Class<?> CACHE=load("net.minecraft.world.level.block.state.BlockBehaviour$BlockStateBase$Cache");
    private static final Field STATE_CACHE=field(BlockBehaviour.BlockStateBase.class,"cache",CACHE);
    private static final Field CACHE_FULL=field(CACHE,"isCollisionShapeFullBlock",boolean.class);
    private static final Field CACHE_SHAPE=field(CACHE,"collisionShape",net.minecraft.world.phys.shapes.VoxelShape.class);
    private static final Field FRICTION=field(BlockBehaviour.class,"friction",float.class);
    private static final Field SPEED=field(BlockBehaviour.class,"speedFactor",float.class);
    private static final Field JUMP=field(BlockBehaviour.class,"jumpFactor",float.class);
    private static final IdentityHashMap<Block,Boolean> VANILLA=vanilla();
    private static IdentityHashMap<Block,Boolean> vanilla(){
        var result=new IdentityHashMap<Block,Boolean>();
        try{for(Field f:Blocks.class.getFields())if(f.getType()==Block.class&&java.lang.reflect.Modifier.isStatic(f.getModifiers()))result.put((Block)f.get(null),Boolean.TRUE);}
        catch(ReflectiveOperationException failure){throw new ExceptionInInitializerError(failure);}return result;
    }
    record Body(java.util.UUID uuid,Object playerLevel,Vec3 position,Vec3 velocity,AABB box,float yaw,float health,int air,float fall,boolean ground,Pose pose,
                Object input,float left,float forward,float xxa,float yya,float zza,boolean jumping,boolean shift,long tick,Object abilities,Object data,Object attributes,
                Object movement,Object gravity,Object jump,Object step,Object effects) {
        boolean same(Body b){return uuid==b.uuid&&playerLevel==b.playerLevel&&position==b.position&&velocity==b.velocity&&box==b.box&&yaw==b.yaw&&health==b.health&&air==b.air&&fall==b.fall
            &&ground==b.ground&&pose==b.pose&&input==b.input&&left==b.left&&forward==b.forward&&xxa==b.xxa&&yya==b.yya&&zza==b.zza&&jumping==b.jumping&&shift==b.shift&&tick==b.tick
            &&abilities==b.abilities&&data==b.data&&attributes==b.attributes&&movement==b.movement&&gravity==b.gravity&&jump==b.jump&&step==b.step&&effects==b.effects;}
    }
    static final class Frame {
        final LocalPlayer player;final ClientLevel level;final Object mode;final Object pathOwner;
        final Object server;final Body body;final ManagedDryRoute.Snapshot route;final Vec3 pending;final long captured=System.nanoTime();
        final Map<BlockPos,BlockState> cells=new LinkedHashMap<>();final ManagedDryStepPolicy.Decision decision;
        Frame(Minecraft mc,Object path,Vec3 pending,boolean requireStep,double pendingJump)throws Exception{
            player=exact(mc.player,LocalPlayer.class);level=exact(mc.level,ClientLevel.class);mode=exact(mc.gameMode,MultiPlayerGameMode.class);pathOwner=path;
            server=exact(mc.getSingleplayerServer(),net.minecraft.client.server.IntegratedServer.class);context(mc);this.pending=pending==null?null:exact(pending,Vec3.class);body=body(player,level);route=ManagedDryRoute.read(path);
            var box=new ManagedDryStepPolicy.Box(body.box.minX,body.box.minY,body.box.minZ,body.box.maxX,body.box.maxY,body.box.maxZ);
            var motion=motion(body,pending,pendingJump);var noImpulse=motion(body,null,pendingJump);
            if(requireStep&&route.step()==null)throw new IllegalStateException("managed_navigation_no_current_step_for_input");
            if(route.step()==null)require(body.ground,"managed_navigation_station_not_grounded");
            decision=route.step()==null?ManagedDryStepPolicy.assessStation(box,motion,noImpulse,this::cell):ManagedDryStepPolicy.assess(route.step(),box,motion,noImpulse,this::cell);
            require(decision.allowed(),decision.reason());
        }
        private ManagedDryStepPolicy.CellState cell(ManagedDryStepPolicy.Cell c){
            BlockPos pos=new BlockPos(c.x(),c.y(),c.z());BlockState state=block(level,pos);cells.put(pos,state);return state(state);
        }
        void unchanged(Minecraft mc)throws Exception{
            require(mc.player==player&&mc.level==level&&mc.gameMode==mode&&mc.getSingleplayerServer()==server,"managed_navigation_dry_context_changed");context(mc);
            require(body.same(body(player,level))&&route.same(ManagedDryRoute.read(pathOwner)),"managed_navigation_dry_snapshot_changed");
            for(var cell:cells.entrySet())require(block(level,cell.getKey())==cell.getValue(),"managed_navigation_dry_cell_changed");
            // Every preceding reader is admitted concrete vanilla data. No callback follows this clock fence.
            require(System.nanoTime()-captured<=50_000_000L,"managed_navigation_dry_snapshot_stale");
        }
    }
    static Frame capture(Minecraft mc,Object path,Vec3 pending,boolean requireStep)throws Exception{return new Frame(mc,path,pending,requireStep,0);}
    static Frame capture(Minecraft mc,Object path,Vec3 pending,boolean requireStep,double pendingJump)throws Exception{return new Frame(mc,path,pending,requireStep,pendingJump);}
    private static ManagedDryStepPolicy.Motion motion(Body body,Vec3 pending,double pendingJump){
        double vx=body.velocity.x,vz=body.velocity.z;
        if(pending!=null){
            require(Double.isFinite(pending.x)&&Double.isFinite(pending.y)&&Double.isFinite(pending.z)&&pending.y==0,"managed_navigation_travel_intent_unproven");
            double length=Math.hypot(pending.x,pending.z);require(length<=1.5,"managed_navigation_travel_intent_unbounded");
            double scale=.101/Math.max(1,length);float angle=body.yaw*((float)Math.PI/180F);double sin=net.minecraft.util.Mth.sin(angle),cos=net.minecraft.util.Mth.cos(angle);
            vx+=(pending.x*cos-pending.z*sin)*scale;vz+=(pending.z*cos+pending.x*sin)*scale;
        }
        require(Double.isFinite(pendingJump)&&pendingJump>=0&&pendingJump<=.420001,"managed_navigation_jump_argument_unproven");
        double vertical=pendingJump>0?Math.max(body.velocity.y,pendingJump):body.velocity.y;if(body.jumping&&body.ground)vertical=Math.max(vertical,.420001);
        return new ManagedDryStepPolicy.Motion(vx,vertical,vz);
    }
    private static void context(Minecraft mc){
        exact(mc,Minecraft.class);exact(mc.getSingleplayerServer(),net.minecraft.client.server.IntegratedServer.class);require(mc.screen==null&&!mc.isPaused()&&mc.isWindowActive()&&CapabilityGuard.privateSingleplayer(mc)
            &&mc.gameMode.getPlayerMode()==net.minecraft.world.level.GameType.SURVIVAL&&mc.player.containerMenu==mc.player.inventoryMenu,"managed_navigation_dry_context_unsafe");
    }
    private static Body body(LocalPlayer p,ClientLevel level){
        exact(p,LocalPlayer.class);exact(level,ClientLevel.class);exact(level.getChunkSource(),ClientChunkCache.class);
        exact(level.getLevelData(),ClientLevel.ClientLevelData.class);exact(p.getEntityData(),SynchedEntityData.class);
        var abilities=exact(p.getAbilities(),Abilities.class);var attrs=exact(p.getAttributes(),AttributeMap.class);
        AttributeInstance movement=attribute(p,Attributes.MOVEMENT_SPEED,.1),gravity=attribute(p,Attributes.GRAVITY,.08),jump=attribute(p,Attributes.JUMP_STRENGTH,.42),step=attribute(p,Attributes.STEP_HEIGHT,.6);
        var effects=exact(p.getActiveEffectsMap(),java.util.HashMap.class);
        require(!effects.containsKey(net.minecraft.world.effect.MobEffects.LEVITATION)&&!effects.containsKey(net.minecraft.world.effect.MobEffects.SLOW_FALLING)
            &&!effects.containsKey(net.minecraft.world.effect.MobEffects.JUMP),"managed_navigation_nonstandard_vertical_physics");
        var position=exact(p.position(),Vec3.class);var velocity=exact(p.getDeltaMovement(),Vec3.class);var box=exact(p.getBoundingBox(),AABB.class);
        var input=p.input;require(input!=null,"managed_navigation_player_input_missing");
        require(p.isAlive()&&!p.isPassenger()&&!p.isFallFlying()&&!p.isNoGravity()&&!abilities.flying&&!p.noPhysics&&!p.isSprinting()
            &&!p.isInWater()&&!p.isInLava()&&!p.isOnFire()&&!p.isInPowderSnow&&p.getAirSupply()>=80
            &&!p.shouldDiscardFriction()&&Float.isFinite(p.getSpeed())&&p.getSpeed()>=0&&p.getSpeed()<=.100001f&&(p.getPose()==Pose.STANDING||p.getPose()==Pose.CROUCHING)
            &&Float.isFinite(p.getYRot())&&Float.isFinite(p.getHealth())&&Float.isFinite(p.fallDistance)&&p.fallDistance<=1.5
            &&Double.isFinite(velocity.x)&&Double.isFinite(velocity.y)&&Double.isFinite(velocity.z)&&velocity.y>=-1.5&&velocity.y<=.75&&Math.hypot(velocity.x,velocity.z)<=.35,
            "managed_navigation_dry_physics_unproven");
        require(p.level()==level,"managed_navigation_player_level_changed");exact(p.getUUID(),java.util.UUID.class);
        return new Body(p.getUUID(),p.level(),position,velocity,box,p.getYRot(),p.getHealth(),p.getAirSupply(),p.fallDistance,p.onGround(),p.getPose(),input,
            input.leftImpulse,input.forwardImpulse,p.xxa,p.yya,p.zza,input.jumping,input.shiftKeyDown,level.getGameTime(),abilities,p.getEntityData(),attrs,movement,gravity,jump,step,effects);
    }
    private static AttributeInstance attribute(LocalPlayer player,Holder<Attribute> holder,double expected){
        // NeoForge's exact vanilla movement-speed holder uses PercentageAttribute; its
        // override is tooltip-only. Other protected holders retain exact RangedAttribute.
        exact(holder,Holder.Reference.class);exact(holder.value(),holder==Attributes.MOVEMENT_SPEED
            ?net.neoforged.neoforge.common.PercentageAttribute.class:RangedAttribute.class);
        var a=exact(player.getAttribute(holder),AttributeInstance.class);
        require(a.getAttribute()==holder&&Double.isFinite(a.getBaseValue())&&Math.abs(a.getBaseValue()-expected)<=1e-7&&a.getModifiers().isEmpty(),"managed_navigation_standard_attributes_required");return a;
    }
    private static BlockState block(ClientLevel level,BlockPos pos){
        exact(level,ClientLevel.class);exact(level.getChunkSource(),ClientChunkCache.class);
        require(!level.isOutsideBuildHeight(pos)&&level.hasChunkAt(pos),"managed_navigation_dry_cell_unloaded");
        var chunk=exact(level.getChunkAt(pos),LevelChunk.class);var section=exact(chunk.getSection(chunk.getSectionIndex(pos.getY())),LevelChunkSection.class);
        exact(section.getStates(),PalettedContainer.class);return exact(chunk.getBlockState(pos),BlockState.class);
    }
    private static ManagedDryStepPolicy.CellState state(BlockState state){
        Block b=state.getBlock();require(VANILLA.containsKey(b),"managed_navigation_nonvanilla_cell");
        boolean dry=state.getFluidState().getType()==Fluids.EMPTY;
        Object cache=read(STATE_CACHE,state);require(cache!=null&&cache.getClass()==CACHE,"managed_navigation_dynamic_collision_unproven");
        boolean ordinary=(float)read(FRICTION,b)==.6f&&(float)read(SPEED,b)==1f&&(float)read(JUMP,b)==1f;
        boolean hazard=b==Blocks.MAGMA_BLOCK||b==Blocks.CACTUS||b==Blocks.SWEET_BERRY_BUSH||b==Blocks.WITHER_ROSE
            ||b==Blocks.FIRE||b==Blocks.SOUL_FIRE||b==Blocks.COBWEB||b==Blocks.NETHER_PORTAL||b==Blocks.END_PORTAL||b==Blocks.END_GATEWAY
            ||b==Blocks.POWDER_SNOW||b==Blocks.BUBBLE_COLUMN||b==Blocks.LADDER||b==Blocks.VINE||b==Blocks.SCAFFOLDING
            ||b==Blocks.WEEPING_VINES||b==Blocks.WEEPING_VINES_PLANT||b==Blocks.TWISTING_VINES||b==Blocks.TWISTING_VINES_PLANT;
        return new ManagedDryStepPolicy.CellState(true,dry,(boolean)read(CACHE_FULL,cache)&&ordinary&&!hazard,
            read(CACHE_SHAPE,cache)==Shapes.empty()&&!hazard&&ordinary);
    }
    private static Class<?> load(String n){try{return Class.forName(n,false,ManagedDryWorld.class.getClassLoader());}catch(Exception e){throw new ExceptionInInitializerError(e);}}
    private static Field field(Class<?> owner,String n,Class<?> type){try{Field f=owner.getDeclaredField(n);require(f.getType()==type&&!java.lang.reflect.Modifier.isStatic(f.getModifiers())&&f.trySetAccessible(),"managed_navigation_raw_cell_field_changed");return f;}catch(Exception e){throw new ExceptionInInitializerError(e);}}
    private static Object read(Field f,Object owner){try{return f.get(owner);}catch(IllegalAccessException e){throw new IllegalStateException("managed_navigation_raw_cell_unavailable",e);}}
    private static <T>T exact(T v,Class<?> type){require(v!=null&&v.getClass()==type,"managed_navigation_dry_reader_changed");return v;}
    private static void require(boolean ok,String why){if(!ok)throw new IllegalStateException(why);}
    private ManagedDryWorld(){}
}
