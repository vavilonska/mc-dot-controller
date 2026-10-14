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

/** Exact vanilla class readers, followed by identity/field comparison. No entity/world mutation. */
final class ScopedMovementEntities {
    /** Check actual loader accessibility without invoking the getter or changing access. */
    static boolean ready(){
        try {
            var getter=Entity.class.getDeclaredMethod("getSharedFlag",int.class);
            int modifiers=getter.getModifiers();
            return getter.getDeclaringClass()==Entity.class && getter.getReturnType()==boolean.class
                    && java.lang.reflect.Modifier.isPublic(modifiers) && !java.lang.reflect.Modifier.isStatic(modifiers);
        } catch(ReflectiveOperationException | SecurityException unavailable){return false;}
    }
    record Entry(Entity identity,ScopedEntityPolicy.Row row) { }
    final ClientLevel level;
    final LocalPlayer player;
    final ScopedFlatPolicy.Bounds bounds;
    final int actionTicks;
    final ScopedEntityPolicy.Frame frame;
    final List<Entry> entries;
    private ScopedMovementEntities(ClientLevel level,LocalPlayer player,ScopedFlatPolicy.Bounds bounds,int actionTicks,
            ScopedEntityPolicy.Frame frame,List<Entry> entries){
        this.level=level;this.player=player;this.bounds=bounds;this.actionTicks=actionTicks;this.frame=frame;this.entries=List.copyOf(entries);
    }
    static ScopedMovementEntities capture(ClientLevel level,LocalPlayer player,ScopedFlatPolicy.Bounds bounds,int actionTicks){
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
                ScopedEntityPolicy.Row row;
                if(removed)row=new ScopedEntityPolicy.Row(id,uuid,type,className,true,null,null,null,null,null,null);
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
                    row=new ScopedEntityPolicy.Row(id,uuid,type,className,false,position,box,velocity,target,flags,
                            ScopedEntityPolicy.project(box,position,velocity,target,horizon));
                }
                entries.add(new Entry(entity,row));
            }
            require(self==1 && examined==entries.size()+1,"scoped_movement_entity_self_coverage");
            entries.sort((a,b)->ScopedEntityPolicy.ORDER.compare(a.row,b.row));
            var frame=ScopedEntityPolicy.frame(tick,began,horizon,self,prism,entries.stream().map(Entry::row).toList());
            frame.json(); // Finite-size budget also applies to continuation frames, never truncates.
            long elapsed=System.nanoTime()-began;
            require(elapsed>=0 && elapsed<=ScopedNativePreflight.MAX_NANOS && level.getGameTime()==tick,
                    "scoped_movement_entity_capture_stale");
            return new ScopedMovementEntities(level,player,bounds,actionTicks,frame,entries);
        } catch(ClientActionRequest.Rejected known){throw known;}
        catch(IllegalArgumentException invalid){throw new ClientActionRequest.Rejected(409,invalid.getMessage());}
        catch(RuntimeException unavailable){throw new ClientActionRequest.Rejected(409,"scoped_movement_entity_coverage_unknown");}
    }
    /** Readers are the audited exact-class data accessors, not classification/shape/capability callbacks. */
    void assertUnchanged(){
        ScopedMovementEntities current=capture(level,player,bounds,actionTicks);
        require(current.frame.tick()==frame.tick() && current.entries.size()==entries.size(),"scoped_movement_entities_changed_after_hooks");
        for(int i=0;i<entries.size();i++){
            Entry old=entries.get(i),now=current.entries.get(i);
            require(old.identity==now.identity && old.row.equals(now.row),"scoped_movement_entities_changed_after_hooks");
        }
    }
    private static boolean supported(Entity e){
        Class<?> c=e.getClass();
        if(c!=Sheep.class && c!=Cow.class && c!=Chicken.class && c!=Pig.class && c!=Rabbit.class && c!=Frog.class
                && c!=Boat.class && c!=MinecartChest.class && c!=ItemEntity.class)return false;
        EntityType<?> t=e.getType();
        return c==Sheep.class && t==EntityType.SHEEP || c==Cow.class && t==EntityType.COW
            || c==Chicken.class && t==EntityType.CHICKEN || c==Pig.class && t==EntityType.PIG
            || c==Rabbit.class && t==EntityType.RABBIT || c==Frog.class && t==EntityType.FROG
            || c==Boat.class && t==EntityType.BOAT || c==MinecartChest.class && t==EntityType.CHEST_MINECART
            || c==ItemEntity.class && t==EntityType.ITEM;
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
