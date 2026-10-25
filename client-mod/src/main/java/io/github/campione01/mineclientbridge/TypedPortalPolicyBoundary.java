package io.github.campione01.mineclientbridge;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import net.minecraft.client.Minecraft;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.client.multiplayer.PlayerInfo;
import net.minecraft.client.player.AbstractClientPlayer;
import net.minecraft.client.player.Input;
import net.minecraft.client.player.KeyboardInput;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.Holder;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.ai.attributes.AttributeInstance;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Abilities;
import net.minecraft.world.level.GameType;
import net.neoforged.neoforge.common.NeoForgeMod;
import net.neoforged.neoforge.fluids.FluidType;
import net.neoforged.neoforge.registries.DeferredHolder;
import it.unimi.dsi.fastutil.objects.Object2DoubleArrayMap;
import it.unimi.dsi.fastutil.objects.Object2DoubleMap;
import it.unimi.dsi.fastutil.objects.AbstractObject2DoubleFunction;

/** Consumed-policy frame around callback-backed readers. Raw fields only: no
 * KeyMapping.isDown, ladder/shape hook, registry binding, entity getter or equals.
 * Existing geometry/inventory/owner frames remain independently required. */
final class TypedPortalPolicyBoundary {
    private static final Field[] CLIENT={
        field(Minecraft.class,"windowActive",boolean.class,false),
        field(Minecraft.class,"pause",boolean.class,false),
        field(Minecraft.class,"isLocalServer",boolean.class,false)};
    private static final Field SERVER=field(Minecraft.class,"singleplayerServer",IntegratedServer.class,false);
    private static final Field PUBLISHED=field(IntegratedServer.class,"publishedPort",int.class,false);
    private static final Field[] MODE={
        field(MultiPlayerGameMode.class,"localPlayerMode",GameType.class,false),
        field(MultiPlayerGameMode.class,"isDestroying",boolean.class,false)};
    private static final Field[] ENTITY={
        field(Entity.class,"level",net.minecraft.world.level.Level.class,false),
        field(Entity.class,"uuid",java.util.UUID.class,false),
        field(Entity.class,"onGround",boolean.class,false),
        field(Entity.class,"wasTouchingWater",boolean.class,false),
        field(Entity.class,"firstTick",boolean.class,false),
        field(Entity.class,"vehicle",Entity.class,false),
        field(Entity.class,"removalReason",Entity.RemovalReason.class,false),
        field(Entity.class,"remainingFireTicks",int.class,false),
        field(Entity.class,"noPhysics",boolean.class,false),
        field(Entity.class,"fallDistance",float.class,false),
        field(Entity.class,"eyeHeight",float.class,false),
        field(Entity.class,"horizontalCollision",boolean.class,false),
        field(Entity.class,"isInPowderSnow",boolean.class,false),
        field(Entity.class,"forgeFluidTypeOnEyes",FluidType.class,false),
        field(Entity.class,"blockPosition",net.minecraft.core.BlockPos.class,false),
        field(Entity.class,"inBlockState",net.minecraft.world.level.block.state.BlockState.class,false)};
    private static final Field[] LIVING={
        field(LivingEntity.class,"hurtTime",int.class,false),
        field(LivingEntity.class,"speed",float.class,false),
        field(LivingEntity.class,"lastClimbablePos",java.util.Optional.class,false),
        field(LivingEntity.class,"useItem",net.minecraft.world.item.ItemStack.class,false),
        field(LivingEntity.class,"useItemRemaining",int.class,false)};
    private static final Field[] LOCAL={
        field(LocalPlayer.class,"startedUsingItem",boolean.class,false),
        field(LocalPlayer.class,"usingItemHand",net.minecraft.world.InteractionHand.class,false)};
    private static final Field[] ATTRIBUTE={
        field(AttributeInstance.class,"cachedValue",double.class,false),
        field(AttributeInstance.class,"dirty",boolean.class,false)};
    private static final Field ABILITIES=field(net.minecraft.world.entity.player.Player.class,"abilities",Abilities.class,true);
    private static final Field PLAYER_INFO=field(AbstractClientPlayer.class,"playerInfo",PlayerInfo.class,false);
    private static final Field INFO_MODE=field(PlayerInfo.class,"gameMode",GameType.class,false);
    private static final Field TYPE=field(Entity.class,"type",EntityType.class,true);
    private static final Field IMMUNE=field(EntityType.class,"fireImmune",boolean.class,true);
    private static final Field DATA=field(Entity.class,"entityData",SynchedEntityData.class,true);
    private static final Field DATA_ROWS=field(SynchedEntityData.class,"itemsById",SynchedEntityData.DataItem[].class,true);
    private static final Field ROW_VALUE=field(SynchedEntityData.DataItem.class,"value",Object.class,false);
    private static final Field ROW_ACCESSOR=field(SynchedEntityData.DataItem.class,"accessor",net.minecraft.network.syncher.EntityDataAccessor.class,true);
    private static final Field EFFECTS=field(LivingEntity.class,"activeEffects",java.util.Map.class,true);
    private static final Field FLUIDS=field(Entity.class,"forgeFluidTypeHeight",Object2DoubleMap.class,false);
    private static final Field FLUID_KEYS=field(Object2DoubleArrayMap.class,"key",Object[].class,false);
    private static final Field FLUID_VALUES=field(Object2DoubleArrayMap.class,"value",double[].class,false);
    private static final Field FLUID_SIZE=field(Object2DoubleArrayMap.class,"size",int.class,false);
    private static final Field FLUID_DEFAULT=field(AbstractObject2DoubleFunction.class,"defRetValue",double.class,false);
    private static final Field DEFERRED=field(DeferredHolder.class,"holder",Holder.class,false);
    private static final Field HOLDER_VALUE=field(Holder.Reference.class,"value",Object.class,false);
    private static final Class<?> EMPTY_TYPE=fluidClass("net.neoforged.neoforge.common.NeoForgeMod$1");
    private static final Class<?> WATER_TYPE=fluidClass("net.neoforged.neoforge.common.NeoForgeMod$2");
    private static final Class<?> LAVA_TYPE=fluidClass("net.neoforged.neoforge.common.NeoForgeMod$3");
    private final Minecraft minecraft;private final LocalPlayer player;private final TypedPortalReaders readers;private final TypedBoundaryPolicy before;

    TypedPortalPolicyBoundary(Minecraft mc,LocalPlayer p,TypedPortalReaders r){minecraft=mc;player=p;readers=r;before=snapshot(mc,p,r);}
    void unchanged(){require(before.same(snapshot(minecraft,player,readers)),"typed_policy_changed_after_callback");}
    static TypedBoundaryPolicy snapshot(Minecraft mc,LocalPlayer p,TypedPortalReaders readers){
        exact(mc,Minecraft.class);exact(p,LocalPlayer.class);exact(mc.gameMode,MultiPlayerGameMode.class);
        var ids=new ArrayList<Object>();var bits=new ArrayList<Long>();
        ids.add(mc);ids.add(p);ids.add(mc.player);ids.add(mc.level);ids.add(mc.gameMode);ids.add(mc.screen);
        appendFields(mc,CLIENT,ids,bits);appendFields(mc.gameMode,MODE,ids,bits);
        Object server=read(SERVER,mc);exact(server,IntegratedServer.class);ids.add(server);appendFields(server,new Field[]{PUBLISHED},ids,bits);
        TargetActionKeySnapshot.appendNeutral(mc.options,ids,bits);
        appendInput(p.input,ids,bits);appendAbilities((Abilities)read(ABILITIES,p),ids,bits);
        appendFields(p,ENTITY,ids,bits);appendFields(p,LIVING,ids,bits);appendFields(p,LOCAL,ids,bits);
        Object info=read(PLAYER_INFO,p);ids.add(info);
        if(info!=null){exact(info,PlayerInfo.class);appendFields(info,new Field[]{INFO_MODE},ids,bits);}
        Object type=read(TYPE,p);exact(type,EntityType.class);ids.add(type);appendFields(type,new Field[]{IMMUNE},ids,bits);
        appendData(read(DATA,p),ids,bits);appendEffects(read(EFFECTS,p),ids,bits);appendFluidMap(read(FLUIDS,p),ids,bits);
        appendFluidHolder(NeoForgeMod.EMPTY_TYPE,EMPTY_TYPE,ids);appendFluidHolder(NeoForgeMod.WATER_TYPE,WATER_TYPE,ids);appendFluidHolder(NeoForgeMod.LAVA_TYPE,LAVA_TYPE,ids);
        readers.appendEffectiveValues(ids,bits);bits.add(BridgeServer.hasHeldInputs()?1L:0L);
        return new TypedBoundaryPolicy(ids.toArray(),bits.stream().mapToLong(Long::longValue).toArray());
    }
    static void appendAttribute(AttributeInstance attribute,List<Object> ids,List<Long> bits){
        exact(attribute,AttributeInstance.class);ids.add(attribute);appendFields(attribute,ATTRIBUTE,ids,bits);
    }
    static void appendInput(Input input,List<Object> ids,List<Long> bits){
        exact(input,KeyboardInput.class);ids.add(input);
        bits.add((long)Float.floatToRawIntBits(input.forwardImpulse));bits.add((long)Float.floatToRawIntBits(input.leftImpulse));
        for(boolean value:new boolean[]{input.up,input.down,input.left,input.right,input.jumping,input.shiftKeyDown})bits.add(value?1L:0L);
    }
    static void appendAbilities(Abilities abilities,List<Object> ids,List<Long> bits){
        exact(abilities,Abilities.class);ids.add(abilities);
        for(boolean value:new boolean[]{abilities.flying,abilities.mayfly,abilities.instabuild,abilities.invulnerable})bits.add(value?1L:0L);
    }
    static void appendData(Object data,List<Object> ids,List<Long> bits){
        exact(data,SynchedEntityData.class);ids.add(data);
        Object raw=read(DATA_ROWS,data);exact(raw,SynchedEntityData.DataItem[].class);
        var rows=(SynchedEntityData.DataItem<?>[])raw;require(rows.length>0&&rows.length<=256,"typed_policy_data_coverage");ids.add(rows);bits.add((long)rows.length);
        for(var row:rows){ids.add(row);if(row!=null){exact(row,SynchedEntityData.DataItem.class);ids.add(read(ROW_ACCESSOR,row));ids.add(read(ROW_VALUE,row));}}
    }
    static void appendEffects(Object effects,List<Object> ids,List<Long> bits){
        exact(effects,HashMap.class);ids.add(effects);int size=((HashMap<?,?>)effects).size();
        require(size==0,"typed_policy_effects_present");bits.add((long)size);
    }
    static void appendFluidMap(Object map,List<Object> ids,List<Long> bits){
        exact(map,Object2DoubleArrayMap.class);ids.add(map);
        Object rawKeys=read(FLUID_KEYS,map),rawValues=read(FLUID_VALUES,map);exact(rawKeys,Object[].class);exact(rawValues,double[].class);
        Object[] keys=(Object[])rawKeys;double[] values=(double[])rawValues;int size=(Integer)read(FLUID_SIZE,map);
        require(size>=0&&size<=256&&size<=keys.length&&size<=values.length,"typed_policy_fluid_coverage");
        ids.add(keys);ids.add(values);bits.add((long)size);bits.add(Double.doubleToRawLongBits((Double)read(FLUID_DEFAULT,map)));
        for(int i=0;i<size;i++){ids.add(keys[i]);bits.add(Double.doubleToRawLongBits(values[i]));}
    }
    private static void appendFluidHolder(Object deferred,Class<?> expected,List<Object> ids){
        exact(deferred,DeferredHolder.class);ids.add(deferred);Object holder=read(DEFERRED,deferred);
        exact(holder,Holder.Reference.class);ids.add(holder);Object value=read(HOLDER_VALUE,holder);
        require(expected!=null,"typed_policy_fluid_reader_unavailable");exact(value,expected);ids.add(value);
    }
    private static Class<?> fluidClass(String name){
        try{
            Class<?> type=Class.forName(name,false,NeoForgeMod.class.getClassLoader());
            if(type.getClassLoader()!=NeoForgeMod.class.getClassLoader()||type.getSuperclass()!=FluidType.class
                ||type.getMethod("equals",Object.class).getDeclaringClass()!=Object.class)return null;
            return type;
        }catch(ReflectiveOperationException|RuntimeException unavailable){return null;}
    }
    private static void appendFields(Object value,Field[] fields,List<Object> ids,List<Long> bits){
        for(Field field:fields){Object read=read(field,value);Class<?> type=field.getType();
            if(type==boolean.class)bits.add((Boolean)read?1L:0L);
            else if(type==int.class)bits.add((long)(Integer)read);
            else if(type==float.class)bits.add((long)Float.floatToRawIntBits((Float)read));
            else if(type==double.class)bits.add(Double.doubleToRawLongBits((Double)read));
            else ids.add(read);
        }
    }
    private static Field field(Class<?> owner,String name,Class<?> type,boolean isFinal){
        try{Field field=owner.getDeclaredField(name);int flags=field.getModifiers();
            if(field.getType()!=type||Modifier.isStatic(flags)||Modifier.isFinal(flags)!=isFinal||!field.trySetAccessible())return null;
            return field;
        }catch(ReflectiveOperationException|RuntimeException unavailable){return null;}
    }
    private static Object read(Field field,Object owner){
        require(field!=null,"typed_policy_field_unavailable");
        try{return field.get(owner);}catch(IllegalAccessException|IllegalArgumentException unavailable){throw new IllegalStateException("typed_policy_field_unavailable",unavailable);}
    }
    private static void exact(Object value,Class<?> type){TypedPortalReaderPolicy.exact(value,type);}
    private static void require(boolean ok,String reason){if(!ok)throw new IllegalStateException(reason);}
}
