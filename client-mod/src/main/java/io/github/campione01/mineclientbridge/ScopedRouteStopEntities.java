package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import net.minecraft.client.Minecraft;
import net.minecraft.world.entity.animal.Bee;
import com.google.gson.JsonObject;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.List;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.Leashable;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.animal.Chicken;
import net.minecraft.world.entity.animal.Cow;
import net.minecraft.world.entity.animal.Pig;
import net.minecraft.world.entity.animal.Sheep;
import net.minecraft.world.entity.animal.frog.Frog;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.vehicle.Boat;
import net.minecraft.world.entity.vehicle.MinecartChest;
import net.minecraft.world.entity.ambient.Bat;
import net.minecraft.world.entity.animal.Cod;
import net.minecraft.world.entity.animal.Salmon;
import net.minecraft.world.entity.animal.TropicalFish;
import net.minecraft.world.entity.animal.Squid;
import net.minecraft.world.entity.GlowSquid;
import net.minecraft.world.entity.animal.Turtle;
import net.minecraft.world.entity.animal.Cat;
import net.minecraft.world.entity.animal.Ocelot;
import net.minecraft.world.entity.animal.Parrot;
import net.minecraft.world.entity.animal.horse.Horse;
import net.minecraft.world.entity.animal.horse.Donkey;
import net.minecraft.world.entity.animal.horse.Mule;
import net.minecraft.world.entity.npc.Villager;
import net.minecraft.world.entity.npc.WanderingTrader;

/** Exact vanilla class readers, followed by identity/field comparison. No entity/world mutation. */
final class ScopedRouteStopEntities {
    /** Check actual loader accessibility without invoking the getter or changing access. */
    static boolean ready(){
        try {
            var getter=Entity.class.getDeclaredMethod("getSharedFlag",int.class);
            int modifiers=getter.getModifiers();
            return getter.getDeclaringClass()==Entity.class && getter.getReturnType()==boolean.class
                    && java.lang.reflect.Modifier.isPublic(modifiers) && !java.lang.reflect.Modifier.isStatic(modifiers);
        } catch(ReflectiveOperationException | SecurityException unavailable){return false;}
    }
    record Entry(Entity identity,ScopedRouteStopPolicy.Row row) { }
    final boolean bees;
    final NativeLivingObservation.Frame serverFrame;
    final RouteBeeDiagnostics.Context beeContext;
    final ClientLevel level;
    final LocalPlayer player;
    final ScopedFlatPolicy.Bounds bounds;
    final int actionTicks;
    final ScopedLocalSegmentPolicy.Bounds route;
    final ScopedRouteStopPolicy.Frame frame;
    final List<Entry> entries;
    private ScopedRouteStopEntities(ClientLevel level,LocalPlayer player,ScopedFlatPolicy.Bounds bounds,int actionTicks,
            ScopedRouteStopPolicy.Frame frame,List<Entry> entries,ScopedLocalSegmentPolicy.Bounds route,boolean bees,NativeLivingObservation.Frame serverFrame,RouteBeeDiagnostics.Context beeContext){
        this.bees=bees;this.serverFrame=serverFrame;this.beeContext=beeContext;
        this.level=level;this.player=player;this.bounds=bounds;this.actionTicks=actionTicks;this.frame=frame;this.entries=List.copyOf(entries);this.route=route;
    }
    static ScopedRouteStopEntities capture(ClientLevel level,LocalPlayer player,ScopedLocalSegmentPolicy.Bounds route,int actionTicks){
        return capture(null,level,player,route,actionTicks,false,null);
    }
    static ScopedRouteStopEntities capture(Minecraft mc,ScopedLocalSegmentPolicy.Bounds route,int actionTicks,boolean bees){
        return capture(mc,mc.level,mc.player,route,actionTicks,bees,bees?NativeLivingObservation.capture(mc):null);
    }
    private static ScopedRouteStopEntities capture(Minecraft mc,ClientLevel level,LocalPlayer player,ScopedLocalSegmentPolicy.Bounds route,int actionTicks,boolean bees,NativeLivingObservation.Frame serverFrame){
        ScopedFlatPolicy.Bounds bounds=route.prism();
        RouteEntityDiagnostics diagnostics=new RouteEntityDiagnostics(bees);
        try {
            require(ready(),"scoped_movement_entity_fire_reader_unavailable");
            long began=System.nanoTime(),tick=level.getGameTime();
            require(actionTicks>=0 && actionTicks<ScopedEntityPolicy.MAX_TICKS,"scoped_movement_entity_tick_budget");
            int horizon=ScopedEntityPolicy.MAX_TICKS-actionTicks;
            var prism=new ScopedEntityPolicy.Box(bounds.minX(),bounds.minY(),bounds.minZ(),bounds.maxX()+1,bounds.maxY()+1,bounds.maxZ()+1);
            if(bees)diagnostics.context(new RouteBeeDiagnostics.Context(level.dimension().location().toString(),WorldGeneration.current(level),
                    player.getUUID().toString(),tick,began,player.getX(),player.getY(),player.getZ(),prism,ScopedRouteStopPolicy.swept(route)));
            var entries=new ArrayList<Entry>();var seen=new IdentityHashMap<Entity,Boolean>();
            var ids=new HashSet<Integer>();var uuids=new HashSet<String>();int examined=0,self=0;
            for(Entity entity:level.entitiesForRendering()){
                diagnostics.phase(RouteEntityDiagnostics.Phase.ENUMERATION);diagnostics.typeUnavailable();
                require(++examined<=ScopedEntityPolicy.LIMIT,"scoped_movement_entity_coverage_limit");
                require(entity!=null && seen.put(entity,Boolean.TRUE)==null,"scoped_movement_entity_duplicate_object");
                if(entity==player){self++;continue;}
                diagnostics.phase(RouteEntityDiagnostics.Phase.IDENTITY);diagnostics.entityType(entity);
                boolean removed=entity.isRemoved();
                diagnostics.phase(RouteEntityDiagnostics.Phase.TYPE);
                if(removed)requireBaseIdentityReaders(entity);else if(!supported(entity,bees))throw NativeEntityDiagnostics.unsupported(entity,bees?ScopedRouteStopPolicy.PROFILE_V2:ScopedRouteStopPolicy.PROFILE);
                int id=entity.getId();String uuid=entity.getUUID().toString();
                require(id!=player.getId() && !uuid.equals(player.getUUID().toString()) && ids.add(id) && uuids.add(uuid),
                        "scoped_movement_entity_duplicate_identity");
                String type=BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString(),className=entity.getClass().getName();
                ScopedRouteStopPolicy.Row row;
                if(removed)row=new ScopedRouteStopPolicy.Row(id,uuid,type,className,true,null,null,null,null,null,null);
                else {
                    diagnostics.phase(RouteEntityDiagnostics.Phase.GEOMETRY);
                    var position=new ScopedEntityPolicy.V(entity.getX(),entity.getY(),entity.getZ());
                    var b=entity.getBoundingBox();var box=new ScopedEntityPolicy.Box(b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ);
                    var v=entity.getDeltaMovement();var velocity=new ScopedEntityPolicy.V(v.x,v.y,v.z);
                    var target=new ScopedEntityPolicy.V(entity.lerpTargetX(),entity.lerpTargetY(),entity.lerpTargetZ());
                    diagnostics.phase(RouteEntityDiagnostics.Phase.STATE);
                    boolean living=entity instanceof LivingEntity;
                    LivingEntity life=living?(LivingEntity)entity:null;
                    require(life==null || Float.isFinite(life.getHealth()),"scoped_movement_entity_health_nonfinite");
                    // A nonnull target is immediately unsupported; do not invoke another entity's getters.
                    require(!(entity instanceof Mob mob) || mob.getTarget()==null,"scoped_movement_entity_target_present");
                    var flags=new ScopedEntityPolicy.Flags(living,entity.isAlive(),life!=null && life.isDeadOrDying(),
                            entity.getVehicle()!=null,!entity.getPassengers().isEmpty(),
                            entity instanceof Leashable leash && leash.getLeashData()!=null,
                            entity.noPhysics,entity.getRemainingFireTicks()>0 || entity.getSharedFlag(0),
                            life==null?0:life.getActiveEffects().size(),life==null?0:life.hurtTime,null);
                    JsonObject nativeLiving=null;
                    if(entity.getClass()==Bee.class){
                        Bee bee=(Bee)entity;
                        require(!bee.isAngry()&&bee.getRemainingPersistentAngerTime()==0&&!bee.hasStung(),"route_bee_not_calm");
                        JsonObject holder=new JsonObject();NativeLivingObservation.appendRouteBee(mc,entity,holder,serverFrame);
                        nativeLiving=holder.getAsJsonObject("native_living");
                    }
                    diagnostics.phase(RouteEntityDiagnostics.Phase.POLICY);
                    row=new ScopedRouteStopPolicy.Row(id,uuid,type,className,false,position,box,velocity,target,flags,
                            ScopedEntityPolicy.project(box,position,velocity,target,horizon),nativeLiving);
                }
                diagnostics.phase(RouteEntityDiagnostics.Phase.POLICY);
                if(!row.removed()&&row.nativeLiving()!=null)diagnostics.bee(row,serverFrame);
                if(!row.removed()&&row.nativeLiving()!=null)ScopedRouteBeePolicy.validate(row,tick,began,player.getUUID().toString(),WorldGeneration.current(level),level.dimension().location().toString());
                ScopedRouteStopPolicy.validateGeometry(row,prism,ScopedRouteStopPolicy.swept(route),horizon);
                entries.add(new Entry(entity,row));
            }
            diagnostics.typeUnavailable();diagnostics.phase(RouteEntityDiagnostics.Phase.COVERAGE);
            require(self==1 && examined==entries.size()+1,"scoped_movement_entity_self_coverage");
            entries.sort((a,b)->ScopedRouteStopPolicy.ORDER.compare(a.row,b.row));
            diagnostics.phase(RouteEntityDiagnostics.Phase.POLICY);
            var frame=new ScopedRouteStopPolicy.Frame(tick,began,horizon,self,prism,ScopedRouteStopPolicy.swept(route),entries.stream().map(Entry::row).toList(),bees,player.getUUID().toString(),WorldGeneration.current(level),level.dimension().location().toString());
            frame.json(); // Finite-size budget also applies to continuation frames, never truncates.
            diagnostics.phase(RouteEntityDiagnostics.Phase.FRESHNESS);
            long elapsed=System.nanoTime()-began;
            require(elapsed>=0 && elapsed<=ScopedNativePreflight.MAX_NANOS && level.getGameTime()==tick,
                    "scoped_movement_entity_capture_stale");
            return new ScopedRouteStopEntities(level,player,bounds,actionTicks,frame,entries,route,bees,serverFrame,diagnostics.context());
        } catch(RuntimeException failure){throw diagnostics.rejection(failure);}
    }
    /** Readers are the audited exact-class data accessors, not classification/shape/capability callbacks. */
    void assertUnchanged(){
        ScopedRouteStopEntities current=capture(bees?Minecraft.getInstance():null,level,player,route,actionTicks,bees,serverFrame);
        RouteEntityDiagnostics diagnostics=new RouteEntityDiagnostics(bees);diagnostics.context(current.beeContext);diagnostics.phase(RouteEntityDiagnostics.Phase.COMPARE);
        try {
        require(current.frame.tick()==frame.tick() && current.entries.size()==entries.size(),"scoped_movement_entities_changed_after_hooks");
        for(int i=0;i<entries.size();i++){
            Entry old=entries.get(i),now=current.entries.get(i);
            diagnostics.typeUnavailable();if(old.identity==now.identity&&old.row.type().equals(now.row.type()))diagnostics.trustedType(now.row.type());
            if(now.row.nativeLiving()!=null)diagnostics.bee(now.row,current.serverFrame);
            require(old.identity==now.identity && comparable(old.row).equals(comparable(now.row)),"scoped_movement_entities_changed_after_hooks");
        }
        }catch(RuntimeException failure){throw diagnostics.rejection(failure);}
    }
    /** No world/shape/AI hooks after this fence. Retain one witness per callback, never across action ticks.
     * A newer publication must preserve every relevant immutable Bee fact, not merely its context. */
    void finalFence(){
        boolean hasBee=entries.stream().anyMatch(e->e.row.nativeLiving()!=null);if(!hasBee)return;
        RouteEntityDiagnostics diagnostic=new RouteEntityDiagnostics(bees);diagnostic.context(beeContext);diagnostic.phase(RouteEntityDiagnostics.Phase.FRESHNESS);
        diagnostic.trustedType(ScopedRouteStopPolicy.BEE);
        try {
            for(Entry e:entries)if(e.row.nativeLiving()!=null){diagnostic.bee(e.row,serverFrame);break;}
            long tick=level.getGameTime();
            var uuids=entries.stream().filter(e->e.row.nativeLiving()!=null).map(e->e.row.uuid()).toList();
            var status=NativeLivingObservation.equivalentBeeBatch(serverFrame,uuids,tick);
            require(status!=NativeLivingSnapshot.BeeFence.CONTEXT_CHANGED,"route_bee_native_context_changed");
            require(status!=NativeLivingSnapshot.BeeFence.STALE,"route_bee_native_stale");
            long now=System.nanoTime();
            for(Entry e:entries)if(e.row.nativeLiving()!=null){
                diagnostic.bee(e.row,serverFrame);
                JsonObject n=e.row.nativeLiving();long source=ScopedRouteBeePolicy.nano(n,"source_nano"),sourceTick=n.get("source_tick").getAsLong();
                require(tick==frame.tick()&&sourceTick>=0&&Math.abs(tick-sourceTick)<=NativeLivingSnapshot.MAX_TICK_SKEW
                    &&now>=source&&now-source<=NativeLivingSnapshot.MAX_AGE_NANOS,"route_bee_native_stale");
            }
        }catch(RuntimeException failure){throw diagnostic.rejection(failure);}
    }
    private static JsonObject comparable(ScopedRouteStopPolicy.Row row){
        JsonObject j=row.json();if(j.has("native_living")){JsonObject n=j.getAsJsonObject("native_living");n.remove("sample_nano");n.remove("sample_age_ms");}return j;
    }
    private static boolean supported(Entity e,boolean bees){
        Class<?> c=e.getClass();
        if(bees&&c==Bee.class)return e.getType()==EntityType.BEE;
        if(c!=Sheep.class && c!=Cow.class && c!=Chicken.class && c!=Pig.class && c!=Frog.class && c!=Boat.class && c!=MinecartChest.class && c!=ItemEntity.class && c!=Bat.class && c!=Cod.class && c!=Salmon.class && c!=TropicalFish.class && c!=Squid.class && c!=GlowSquid.class && c!=Turtle.class && c!=Cat.class && c!=Ocelot.class && c!=Parrot.class && c!=Horse.class && c!=Donkey.class && c!=Mule.class && c!=Villager.class && c!=WanderingTrader.class)return false;
        EntityType<?> t=e.getType();
        return c==Sheep.class && t==EntityType.SHEEP
            || c==Cow.class && t==EntityType.COW
            || c==Chicken.class && t==EntityType.CHICKEN
            || c==Pig.class && t==EntityType.PIG
            || c==Frog.class && t==EntityType.FROG
            || c==Boat.class && t==EntityType.BOAT
            || c==MinecartChest.class && t==EntityType.CHEST_MINECART
            || c==ItemEntity.class && t==EntityType.ITEM
            || c==Bat.class && t==EntityType.BAT
            || c==Cod.class && t==EntityType.COD
            || c==Salmon.class && t==EntityType.SALMON
            || c==TropicalFish.class && t==EntityType.TROPICAL_FISH
            || c==Squid.class && t==EntityType.SQUID
            || c==GlowSquid.class && t==EntityType.GLOW_SQUID
            || c==Turtle.class && t==EntityType.TURTLE
            || c==Cat.class && t==EntityType.CAT
            || c==Ocelot.class && t==EntityType.OCELOT
            || c==Parrot.class && t==EntityType.PARROT
            || c==Horse.class && t==EntityType.HORSE
            || c==Donkey.class && t==EntityType.DONKEY
            || c==Mule.class && t==EntityType.MULE
            || c==Villager.class && t==EntityType.VILLAGER
            || c==WanderingTrader.class && t==EntityType.WANDERING_TRADER;
    }
    /** Removed unknown types are safe only if all identity reads still resolve to plain Entity field getters. */
    private static void requireBaseIdentityReaders(Entity e){
        try {
            for(String name:List.of("getId","getUUID","getType"))
                require(e.getClass().getMethod(name).getDeclaringClass()==Entity.class,"scoped_movement_removed_entity_reader_unknown");
        } catch(ReflectiveOperationException unavailable){throw new ClientActionRequest.Rejected(409,"scoped_movement_removed_entity_reader_unknown");}
    }
    private static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
}
