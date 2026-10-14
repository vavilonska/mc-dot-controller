package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import java.util.UUID;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.item.ItemStack;

/** Read-only, exact observation binding for one ordinary local pickup. Never removes an entity. */
final class ScopedCollectTarget {
    static final String PROFILE="collect-local-observed-v1";
    static final Set<String> ITEMS=Set.of("minecraft:stone","minecraft:cobblestone","minecraft:dirt",
            "minecraft:oak_planks","minecraft:coal","minecraft:stick","minecraft:iron_nugget");
    private static final Set<String> KEYS=Set.of("entity_id","uuid","item_id","count","item_fingerprint",
            "component_fingerprint","x","y","z");
    final String uuid;
    private final int id,count;
    private final double x,y,z,goalY;
    private final String itemId;
    private final ItemEntity target;
    private final ItemStack stack;
    private final LocalPlayer player;
    private final ClientLevel level;
    private final JsonObject expected;

    ScopedCollectTarget(Minecraft mc,ClientActionRequest request) {
        require(mc.player!=null && mc.level!=null,"scoped_collect_world_missing");
        player=mc.player;level=mc.level;
        require(request.original().has("pickup_target") && request.original().get("pickup_target").isJsonObject(),
                "scoped_collect_target_invalid");
        expected=request.original().getAsJsonObject("pickup_target").deepCopy();
        require(expected.keySet().equals(KEYS),"scoped_collect_target_invalid");
        for(String k:KEYS)require(expected.get(k).isJsonPrimitive(),"scoped_collect_target_invalid");
        for(String k:Set.of("uuid","item_id","item_fingerprint","component_fingerprint"))
            require(expected.getAsJsonPrimitive(k).isString(),"scoped_collect_target_invalid");
        for(String k:Set.of("entity_id","count","x","y","z"))
            require(expected.getAsJsonPrimitive(k).isNumber(),"scoped_collect_target_invalid");
        uuid=expected.get("uuid").getAsString();itemId=expected.get("item_id").getAsString();
        try {require(UUID.fromString(uuid).toString().equals(uuid),"scoped_collect_target_invalid");}
        catch(IllegalArgumentException bad){throw new ClientActionRequest.Rejected(409,"scoped_collect_target_invalid");}
        id=expected.get("entity_id").getAsInt();count=expected.get("count").getAsInt();
        require(expected.get("entity_id").getAsDouble()==id && expected.get("count").getAsDouble()==count
                && count>0 && count<=64 && ITEMS.contains(itemId),"scoped_collect_stack_unsupported");
        x=expected.get("x").getAsDouble();y=expected.get("y").getAsDouble();z=expected.get("z").getAsDouble();
        require(ScopedFlatPolicy.finite(x,y,z) && request.waypoints().size()==1,"scoped_collect_goal_invalid");
        var goal=request.waypoints().getFirst();goalY=goal.y();
        int dx=(int)Math.floor(goal.x())-(int)Math.floor(player.getX());
        int dz=(int)Math.floor(goal.z())-(int)Math.floor(player.getZ());
        require(Math.abs(dx)+Math.abs(dz)==1 && goal.y()==player.getY()
                && Math.floor(x)==Math.floor(goal.x()) && Math.floor(z)==Math.floor(goal.z())
                && y>=goal.y() && y<=goal.y()+.25,"scoped_collect_goal_invalid");
        Entity entity=level.getEntity(id);
        require(entity!=null && entity.getClass()==ItemEntity.class && entity.getType()==EntityType.ITEM
                && entity.getUUID().toString().equals(uuid),"scoped_collect_target_identity_changed");
        target=(ItemEntity)entity;stack=target.getItem().copy();
        assertCurrent(level);
    }
    void assertCurrent(ClientLevel current) {
        require(current==level && Minecraft.getInstance().player==player,"scoped_collect_world_changed");
        // Inspect replacement identity before absence: absence alone is not evidence of pickup.
        Entity atId=level.getEntity(id);int examined=0;boolean found=false;
        for(Entity e:level.entitiesForRendering()) {
            require(++examined<=ScopedEntityPolicy.LIMIT,"scoped_collect_entity_coverage_limit");
            require(e!=null,"scoped_collect_entity_coverage_unknown");
            try {
                for(String method:java.util.List.of("getId","getUUID"))
                    require(e.getClass().getMethod(method).getDeclaringClass()==Entity.class,"scoped_collect_entity_reader_unknown");
            } catch(ReflectiveOperationException unknown){throw new ClientActionRequest.Rejected(409,"scoped_collect_entity_reader_unknown");}
            if(e==target)found=!e.isRemoved();
            if(e.getId()==id || e.getUUID().toString().equals(uuid))
                require(e==target && e.getId()==id && e.getUUID().toString().equals(uuid),
                        "scoped_collect_target_identity_changed");
        }
        require(atId==null || atId==target,"scoped_collect_target_identity_changed");
        require(target.getId()==id && target.getUUID().toString().equals(uuid)
                && target.getClass()==ItemEntity.class && target.getType()==EntityType.ITEM,
                "scoped_collect_target_identity_changed");
        require(found && atId==target && !target.isRemoved(),"scoped_collect_target_absent");
        var velocity=target.getDeltaMovement();
        require(target.isAlive() && target.onGround() && !target.hasPickUpDelay() && target.getTarget()==null
                && !target.isPassenger() && target.getPassengers().isEmpty() && !target.noPhysics
                && !target.isNoGravity() && !target.isInWater() && !target.isInLava() && !target.isOnFire()
                && ScopedEntityPolicy.restingPickupAnchor(new ScopedEntityPolicy.V(x,y,z),
                    new ScopedEntityPolicy.V(target.getX(),target.getY(),target.getZ()))
                && target.getY()>=goalY && target.getY()<=goalY+.25
                && ScopedEntityPolicy.restingPickupMotion(new ScopedEntityPolicy.V(velocity.x,velocity.y,velocity.z))
                && target.lerpTargetX()==target.getX() && target.lerpTargetY()==target.getY() && target.lerpTargetZ()==target.getZ(),
                "scoped_collect_target_motion_or_state_changed");
        ItemStack now=target.getItem();
        require(!now.isEmpty() && now.getCount()==count && now.isComponentsPatchEmpty()
                && (now.getItem().getClass()==net.minecraft.world.item.Item.class
                    || now.getItem().getClass()==net.minecraft.world.item.BlockItem.class)
                && now.getMaxStackSize()==64 && BuiltInRegistries.ITEM.getKey(now.getItem()).toString().equals(itemId)
                && CapabilityItemBinding.same(stack,now) && CapabilityItemBinding.matches(expected,now)
                && CapabilityItemBinding.matchesComponents(expected,now),"scoped_collect_target_stack_changed");
        Inventory inventory=player.getInventory();
        require(inventory.getClass()==Inventory.class && inventory.items.size()==36,"scoped_collect_inventory_unsupported");
        int capacity=0;
        for(ItemStack slot:inventory.items) {
            if(slot.isEmpty())capacity+=64;
            else if(slot.isComponentsPatchEmpty() && ItemStack.isSameItemSameComponents(slot,now))
                capacity+=Math.max(0,64-slot.getCount());
        }
        require(capacity>=count,"scoped_collect_inventory_capacity_insufficient");
    }
    JsonObject facts(){JsonObject out=expected.deepCopy();out.addProperty("simple_components",true);
        out.addProperty("on_ground",true);out.addProperty("resting_envelope",ScopedEntityPolicy.PICKUP_RESTING_ENVELOPE);return out;}
    private static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
}
