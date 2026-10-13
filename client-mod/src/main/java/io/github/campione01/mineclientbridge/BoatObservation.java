package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.vehicle.Boat;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

/** Observed vehicle facts; being a passenger is not permission to drive. */
final class BoatObservation {
    static com.google.gson.JsonElement snapshot(Minecraft mc) {
        Entity vehicle=mc.player==null?null:mc.player.getVehicle();
        if(vehicle==null) {JsonObject absent=new JsonObject();absent.addProperty("schema_version",1);absent.addProperty("riding",false);absent.addProperty("controlling_seat",false);return absent;}
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);
        j.addProperty("uuid",vehicle.getUUID().toString());j.addProperty("entity_id",vehicle.getId());
        j.addProperty("type",BuiltInRegistries.ENTITY_TYPE.getKey(vehicle.getType()).toString());
        j.addProperty("x",vehicle.getX());j.addProperty("y",vehicle.getY());j.addProperty("z",vehicle.getZ());
        j.addProperty("yaw",vehicle.getYRot());j.add("velocity",vector(vehicle.getDeltaMovement()));
        j.add("aabb",box(vehicle.getBoundingBox()));j.addProperty("alive",vehicle.isAlive());
        j.addProperty("riding",true);j.addProperty("controlling_seat",vehicle.getControllingPassenger()==mc.player);
        j.addProperty("controlling_passenger_uuid",vehicle.getControllingPassenger()==null?null:vehicle.getControllingPassenger().getUUID().toString());
        JsonArray passengers=new JsonArray();for(var p:vehicle.getPassengers())passengers.add(p.getUUID().toString());
        j.add("passengers",passengers);
        JsonArray geometry=new JsonArray();
        for(var p:vehicle.getPassengers()) {
            JsonObject rider=new JsonObject();rider.addProperty("uuid",p.getUUID().toString());
            try {
                rider.addProperty("type",BuiltInRegistries.ENTITY_TYPE.getKey(p.getType()).toString());
                rider.addProperty("pose",p.getPose().name().toLowerCase(java.util.Locale.ROOT));
                rider.addProperty("alive",p.isAlive()&&!p.isRemoved());
                rider.addProperty("direct_passenger",p.getVehicle()==vehicle);
                rider.addProperty("nested_passenger_count",p.getPassengers().size());
                rider.add("aabb",box(p.getBoundingBox()));
                var attachment=p.getVehicleAttachmentPoint(vehicle);
                var dimensions=p.getDimensions(p.getPose());
                var mount=vehicle.getPassengerRidingPosition(p).subtract(attachment);
                rider.add("vehicle_attachment",vector(attachment));
                rider.addProperty("native_width",dimensions.width());rider.addProperty("native_height",dimensions.height());
                rider.add("native_mount_position",vector(mount));
                rider.add("native_expected_aabb",box(dimensions.makeBoundingBox(mount)));
                rider.addProperty("geometry_complete",true);
            } catch(RuntimeException unknown) {rider.addProperty("geometry_complete",false);}
            geometry.add(rider);
        }
        j.addProperty("passenger_geometry_schema_version",1);j.add("passenger_geometry",geometry);
        if(vehicle instanceof Boat boat) {
            j.addProperty("ordinary_boat",boat.getClass()==Boat.class);
            j.addProperty("variant",boat.getVariant().getName());
            j.addProperty("water_status",boat.status==null?"unknown":boat.status.name().toLowerCase(java.util.Locale.ROOT));
            j.addProperty("yaw_rate",boat.deltaRotation);j.addProperty("above_bubble_column",boat.isAboveBubbleColumn);
            j.addProperty("horizontal_speed",boat.getDeltaMovement().horizontalDistance());
        }
        return j;
    }
    static JsonObject vector(Vec3 v) {JsonObject j=new JsonObject();j.addProperty("x",v.x);j.addProperty("y",v.y);j.addProperty("z",v.z);return j;}
    static JsonObject box(AABB b) {JsonObject j=new JsonObject();j.addProperty("min_x",b.minX);j.addProperty("min_y",b.minY);j.addProperty("min_z",b.minZ);j.addProperty("max_x",b.maxX);j.addProperty("max_y",b.maxY);j.addProperty("max_z",b.maxZ);return j;}
    private BoatObservation() { }
}
