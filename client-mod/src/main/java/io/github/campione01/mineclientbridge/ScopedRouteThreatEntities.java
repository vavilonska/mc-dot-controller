package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
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
import net.minecraft.world.entity.animal.Rabbit;
import net.minecraft.world.entity.animal.Sheep;
import net.minecraft.world.entity.animal.frog.Frog;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.vehicle.Boat;
import net.minecraft.world.entity.vehicle.MinecartChest;
import net.minecraft.world.entity.monster.Zombie;
import net.minecraft.client.Minecraft;
import com.google.gson.JsonObject;

/** Exact vanilla class readers, followed by identity/field comparison. No entity/world mutation. */
final class ScopedRouteThreatEntities {
    static boolean ready(){return ScopedMovementEntities.ready();}
    record Entry(Entity identity,ScopedRouteThreatPolicy.Row row) { }
    final ClientLevel level;
    final LocalPlayer player;
    final ScopedFlatPolicy.Bounds bounds;
    final int actionTicks;
    final boolean allowProjectedAttacker;
    final ScopedLocalSegmentPolicy.Bounds route;
    final String selectedUuid;
    final NativeLivingObservation.Frame serverFrame;
    final ScopedRouteThreatPolicy.Frame frame;
    final List<Entry> entries;
    private ScopedRouteThreatEntities(ClientLevel level,LocalPlayer player,ScopedLocalSegmentPolicy.Bounds route,int actionTicks,
            ScopedRouteThreatPolicy.Frame frame,List<Entry> entries,String selectedUuid,NativeLivingObservation.Frame serverFrame,boolean allowProjectedAttacker){
        this.level=level;this.player=player;this.bounds=route.prism();this.route=route;this.actionTicks=actionTicks;
        this.frame=frame;this.entries=List.copyOf(entries);this.selectedUuid=selectedUuid;this.serverFrame=serverFrame;this.allowProjectedAttacker=allowProjectedAttacker;
    }
    static ScopedRouteThreatEntities capture(Minecraft mc,ScopedLocalSegmentPolicy.Bounds route,int actionTicks,String selectedUuid,boolean allowProjectedAttacker){
        return capture(mc,route,actionTicks,selectedUuid,NativeLivingObservation.capture(mc),allowProjectedAttacker,"capture");
    }
    private static ScopedRouteThreatEntities capture(Minecraft mc,ScopedLocalSegmentPolicy.Bounds route,int actionTicks,String selectedUuid,NativeLivingObservation.Frame serverFrame,boolean allowProjectedAttacker,String diagnosticPhase){
        ClientLevel level=mc.level;LocalPlayer player=mc.player;ScopedFlatPolicy.Bounds bounds=route.prism();
        try {
            require(ready(),"scoped_movement_entity_fire_reader_unavailable");
            long began=System.nanoTime(),tick=level.getGameTime();
            require(actionTicks>=0 && actionTicks<ScopedEntityPolicy.MAX_TICKS,"scoped_movement_entity_tick_budget");
            int horizon=ScopedEntityPolicy.MAX_TICKS-actionTicks;
            var prism=new ScopedEntityPolicy.Box(bounds.minX(),bounds.minY(),bounds.minZ(),bounds.maxX()+1,bounds.maxY()+1,bounds.maxZ()+1);
            var entries=new ArrayList<Entry>();var seen=new IdentityHashMap<Entity,Boolean>();
            var ids=new HashSet<Integer>();var uuids=new HashSet<String>();int examined=0,self=0;
            for(Entity entity:level.entitiesForRendering()){
                require(++examined<=ScopedEntityPolicy.LIMIT,"scoped_movement_entity_coverage_limit");
                require(entity!=null && seen.put(entity,Boolean.TRUE)==null,"scoped_movement_entity_duplicate_object");
                if(entity==player){self++;continue;}
                boolean removed=entity.isRemoved();
                if(removed)requireBaseIdentityReaders(entity);else require(supported(entity),"scoped_movement_entity_unsupported");
                int id=entity.getId();String uuid=entity.getUUID().toString();
                require(id!=player.getId() && !uuid.equals(player.getUUID().toString()) && ids.add(id) && uuids.add(uuid),
                        "scoped_movement_entity_duplicate_identity");
                String type=BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString(),className=entity.getClass().getName();
                ScopedRouteThreatPolicy.Row row;
                if(removed)row=new ScopedRouteThreatPolicy.Row(id,uuid,type,className,true,null,null,null,null,null,null,null);
                else {
                    var position=new ScopedEntityPolicy.V(entity.getX(),entity.getY(),entity.getZ());
                    var b=entity.getBoundingBox();var box=new ScopedEntityPolicy.Box(b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ);
                    var v=entity.getDeltaMovement();var velocity=new ScopedEntityPolicy.V(v.x,v.y,v.z);
                    var target=new ScopedEntityPolicy.V(entity.lerpTargetX(),entity.lerpTargetY(),entity.lerpTargetZ());
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
                    if(entity.getClass()==Zombie.class){JsonObject holder=new JsonObject();NativeLivingObservation.append(mc,entity,holder,serverFrame);nativeLiving=holder.getAsJsonObject("native_living");}
                    row=new ScopedRouteThreatPolicy.Row(id,uuid,type,className,false,position,box,velocity,target,flags,
                            ScopedEntityPolicy.project(box,position,velocity,target,horizon),nativeLiving);
                }
                entries.add(new Entry(entity,row));
            }
            require(self==1 && examined==entries.size()+1,"scoped_movement_entity_self_coverage");
            entries.sort((a,b)->ScopedRouteThreatPolicy.ORDER.compare(a.row,b.row));
            var frame=new ScopedRouteThreatPolicy.Frame(tick,began,horizon,self,prism,ScopedRouteThreatPolicy.swept(route),
                new ScopedEntityPolicy.V(player.getX(),player.getY(),player.getZ()),player.getUUID().toString(),WorldGeneration.current(level),
                level.dimension().location().toString(),selectedUuid,entries.stream().map(Entry::row).toList(),allowProjectedAttacker);
            frame.json(); // Finite-size budget also applies to continuation frames, never truncates.
            long elapsed=System.nanoTime()-began;
            require(elapsed>=0 && elapsed<=ScopedNativePreflight.MAX_NANOS && level.getGameTime()==tick,
                    "scoped_movement_entity_capture_stale");
            return new ScopedRouteThreatEntities(level,player,route,actionTicks,frame,entries,selectedUuid,serverFrame,allowProjectedAttacker);
        } catch(RouteThreatDiagnostics.FailedRow rejected){
            throw RouteThreatDiagnostics.rejection(rejected,serverFrame.batch(),serverFrame.context(),selectedUuid,diagnosticPhase);
        } catch(ClientActionRequest.Rejected known){throw known;}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        catch(RuntimeException unavailable){throw new ClientActionRequest.Rejected(409,"scoped_movement_entity_coverage_unknown");}
    }
    /** Readers are the audited exact-class data accessors, not classification/shape/capability callbacks. */
    void assertUnchanged(){
        ScopedRouteThreatEntities current=capture(Minecraft.getInstance(),route,actionTicks,selectedUuid,serverFrame,allowProjectedAttacker,"recheck");
        require(current.frame.tick()==frame.tick() && current.entries.size()==entries.size(),"scoped_movement_entities_changed_after_hooks");
        for(int i=0;i<entries.size();i++){
            Entry old=entries.get(i),now=current.entries.get(i);
            require(old.identity==now.identity && comparable(old.row).equals(comparable(now.row)),"scoped_movement_entities_changed_after_hooks");
        }
    }
    /** Immutable server data still has to be fresh at the final no-hook effect boundary. */
    void finalFence(){
        require(NativeLivingObservation.current(serverFrame),"route_spatial_native_context_changed");
        long now=System.nanoTime();
        for(Entry e:entries)if(e.row.nativeLiving()!=null){
            long source=Long.parseLong(e.row.nativeLiving().get("source_nano").getAsString());
            if(!(now>=source&&now-source<=250_000_000L)){
                var failed=new RouteThreatDiagnostics.FailedRow(new IllegalArgumentException("route_spatial_native_target_stale"),
                    e.row,frame.tick(),frame.nano(),frame.playerUuid(),frame.world(),frame.dimension(),now);
                throw RouteThreatDiagnostics.rejection(failed,serverFrame.batch(),serverFrame.context(),selectedUuid,"final_fence");
            }
        }
    }
    private static JsonObject comparable(ScopedRouteThreatPolicy.Row row){
        JsonObject j=row.json(false);if(j.has("native_living")){var n=j.getAsJsonObject("native_living");n.remove("sample_nano");n.remove("sample_age_ms");}return j;
    }
    private static boolean supported(Entity e){
        Class<?> c=e.getClass();
        if(c!=Sheep.class && c!=Cow.class && c!=Chicken.class && c!=Pig.class && c!=Frog.class
                && c!=Boat.class && c!=MinecartChest.class && c!=ItemEntity.class && c!=Zombie.class)return false;
        EntityType<?> t=e.getType();
        return c==Sheep.class && t==EntityType.SHEEP || c==Cow.class && t==EntityType.COW
            || c==Chicken.class && t==EntityType.CHICKEN || c==Pig.class && t==EntityType.PIG
            || c==Frog.class && t==EntityType.FROG
            || c==Boat.class && t==EntityType.BOAT || c==MinecartChest.class && t==EntityType.CHEST_MINECART
            || c==ItemEntity.class && t==EntityType.ITEM || c==Zombie.class && t==EntityType.ZOMBIE;
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
