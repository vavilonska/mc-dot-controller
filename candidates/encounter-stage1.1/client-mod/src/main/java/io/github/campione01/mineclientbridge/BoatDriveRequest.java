package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/** Versioned, immutable finite route. There is deliberately no renewal or append operation. */
record BoatDriveRequest(String world, String player, String session, String vehicle, int vehicleId,
                        int surfaceY, List<BoatSteering.Point> points, int timeoutMs) {
    static final int MAX_POINTS = 64;
    static final double MAX_LENGTH = 256, MAX_SEGMENT = 16;
    private static final Set<String> FIELDS = Set.of("action_id", "action", "boat_schema_version", "timeout_ms",
            "expected_world_generation", "expected_player_uuid", "expected_action_session", "vehicle_uuid",
            "vehicle_entity_id", "vehicle_type", "water_surface_y", "waypoints");
    static BoatDriveRequest parse(JsonObject body) {
        for (String key : body.keySet()) ClientActionRequest.require(FIELDS.contains(key), "boat_unknown_field_" + key);
        ClientActionRequest.require(ClientActionRequest.integer(body,"boat_schema_version",-1)==1,"boat_schema_version_required");
        ClientActionRequest.require(ClientActionRequest.string(body,"vehicle_type").equals("minecraft:boat"),"boat_type_unsupported");
        int timeout=ClientActionRequest.integer(body,"timeout_ms",-1);
        ClientActionRequest.require(timeout>=1000 && timeout<=120000,"boat_timeout_1000_to_120000");
        int vehicleId=ClientActionRequest.integer(body,"vehicle_entity_id",-1);
        ClientActionRequest.require(vehicleId>=0,"invalid_vehicle_entity_id");
        int surface=ClientActionRequest.integer(body,"water_surface_y",Integer.MIN_VALUE);
        ClientActionRequest.require(surface>=-2048 && surface<=2048,"invalid_water_surface_y");
        ClientActionRequest.require(body.has("waypoints") && body.get("waypoints").isJsonArray(),"invalid_boat_waypoints");
        var values=body.getAsJsonArray("waypoints");
        ClientActionRequest.require(!values.isEmpty() && values.size()<=MAX_POINTS,"boat_waypoint_limit");
        List<BoatSteering.Point> points=new ArrayList<>(); double length=0;
        for (var value:values) {
            ClientActionRequest.require(value.isJsonObject(),"invalid_boat_waypoint");
            var point=value.getAsJsonObject();
            ClientActionRequest.require(point.keySet().equals(Set.of("x","z")),"boat_waypoint_requires_only_x_z");
            var p=new BoatSteering.Point(number(point,"x"),number(point,"z"));
            if (!points.isEmpty()) {
                double d=p.distance(points.getLast());
                ClientActionRequest.require(d>=.25 && d<=MAX_SEGMENT,"boat_segment_025_to_16");
                length+=d;
            }
            points.add(p);
        }
        ClientActionRequest.require(length<=MAX_LENGTH,"boat_route_too_long");
        return new BoatDriveRequest(uuid(body,"expected_world_generation"),uuid(body,"expected_player_uuid"),
                uuid(body,"expected_action_session"),uuid(body,"vehicle_uuid"),vehicleId,surface,List.copyOf(points),timeout);
    }
    private static double number(JsonObject body,String key) {
        var v=body.get(key);
        ClientActionRequest.require(v!=null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isNumber(),"invalid_"+key);
        double n=v.getAsDouble();
        ClientActionRequest.require(Double.isFinite(n) && Math.abs(n)<=29999900,"invalid_"+key);
        return n;
    }
    private static String uuid(JsonObject body,String key) {
        String value=ClientActionRequest.string(body,key);
        try { ClientActionRequest.require(UUID.fromString(value).toString().equals(value),"invalid_"+key); }
        catch (IllegalArgumentException e) { throw new ClientActionRequest.Rejected(400,"invalid_"+key); }
        return value;
    }
}
