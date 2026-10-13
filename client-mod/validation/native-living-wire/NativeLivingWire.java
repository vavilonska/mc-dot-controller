package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.nio.file.Path;
import java.util.Map;

/** Synthetic inputs through the exact production snapshot and HTTP encoder; never starts Minecraft. */
public final class NativeLivingWire {
    private static final Object CONTEXT = new Object();
    private static final String DIMENSION = "minecraft:overworld";
    private static final String WORLD = "synthetic-native-wire-world";
    private static final String SESSION = "synthetic-native-wire-session";
    private static final String PLAYER = "00000000-0000-4000-8000-000000000001";
    private static final String BEE = "00000000-0000-4000-8000-000000000009";
    private static final String TARGET = "00000000-0000-4000-8000-000000000008";
    private static final long TICK = 100, SOURCE_NANO = 1_000_000_000L, SAMPLE_NANO = 1_050_000_000L;

    private static JsonObject point(double x, double y, double z) {
        JsonObject value = new JsonObject(); value.addProperty("x", x); value.addProperty("y", y); value.addProperty("z", z); return value;
    }
    private static JsonObject box(double x, double width, double height) {
        JsonObject value = new JsonObject(); value.add("min", point(x-width/2,64,-width/2));
        value.add("max", point(x+width/2,64+height,width/2)); return value;
    }
    private static JsonObject entity(String uuid, int id, String type, String cls, double x, double width, double height) {
        JsonObject value = point(x,64,0); value.addProperty("uuid", uuid); value.addProperty("entity_id", id);
        value.addProperty("type", type); value.addProperty("class", cls); value.addProperty("alive", true);
        value.addProperty("on_ground", false); value.add("velocity", point(0,0,0)); value.addProperty("distance", x);
        value.add("bounding_box", box(x,width,height)); return value;
    }
    private static JsonObject nativeFacts(String uuid, int id, String type, boolean available,
                                          boolean target, boolean persistent, boolean stale) {
        var observedTarget = target ? new NativeLivingSnapshot.Target(TARGET, 8, "minecraft:player") : null;
        var bee = type.equals("minecraft:bee") ? new NativeLivingSnapshot.BeeState(false,0,persistent ? TARGET : null) : null;
        var row = new NativeLivingSnapshot.Row(uuid,id,type,TICK,SOURCE_NANO,true,false,observedTarget,bee);
        var batch = available ? new NativeLivingSnapshot.Batch(CONTEXT,new Object(),DIMENSION,Map.of(uuid,row),true,3,"observed") : null;
        return NativeLivingSnapshot.json(batch,CONTEXT,DIMENSION,WORLD,PLAYER,uuid,id,type,TICK,
                stale ? SOURCE_NANO+250_000_001L : SAMPLE_NANO);
    }
    private static JsonObject living(String uuid, int id, String type, String cls, double x, double width, double height,
                                     boolean available, boolean target, boolean persistent, boolean stale) {
        JsonObject value = entity(uuid,id,type,cls,x,width,height);
        value.addProperty("health",10.0); value.addProperty("max_health",10.0);
        value.addProperty("hurt_time",0); value.addProperty("using_item",false);
        value.add("native_living",nativeFacts(uuid,id,type,available,target,persistent,stale)); return value;
    }
    private static JsonObject state(boolean available, boolean target, boolean persistent, boolean stale) {
        JsonObject root = new JsonObject(); root.addProperty("private_singleplayer",true);
        root.addProperty("focused",true); root.addProperty("paused",false); root.addProperty("screen_open",false);
        JsonObject world = new JsonObject(); world.addProperty("dimension",DIMENSION);
        world.addProperty("world_generation",WORLD); world.addProperty("game_time",TICK); root.add("world",world);
        JsonObject player = point(0,64,0); player.addProperty("uuid",PLAYER); player.addProperty("dimension",DIMENSION);
        player.add("bounding_box",box(0,.6,1.8)); root.add("player",player);
        JsonObject action = new JsonObject(); action.addProperty("action_session",SESSION);
        action.add("action_id",JsonNull.INSTANCE); action.addProperty("status","idle"); root.add("client_action",action);
        JsonObject guard = new JsonObject(); guard.addProperty("schema_version",1);
        guard.addProperty("source_tick",TICK); guard.addProperty("source_nano",Long.toString(SAMPLE_NANO)); root.add("capability_guard",guard);
        JsonArray entities = new JsonArray(); entities.add(living(BEE,9,"minecraft:bee","net.minecraft.world.entity.animal.Bee",
                24,.7,.6,available,target,persistent,stale));
        JsonObject nearby = new JsonObject(); nearby.addProperty("radius",48.0); nearby.addProperty("total",1);
        nearby.addProperty("returned",1); nearby.addProperty("truncated",false); nearby.add("entities",entities); root.add("nearby",nearby);
        return root;
    }
    private static JsonObject facts(JsonObject state) {
        return state.getAsJsonObject("nearby").getAsJsonArray("entities").get(0).getAsJsonObject().getAsJsonObject("native_living");
    }
    private static void add(JsonArray cases, String name, JsonObject state) throws Exception {
        JsonObject before = state.deepCopy(); String encoded = BridgeJson.toJson(state);
        if (!state.equals(before) || !encoded.equals(BridgeJson.toJson(state))) throw new AssertionError("Encoder mutated input or was unstable: " + name);
        JsonObject row = new JsonObject(); row.addProperty("name",name); row.addProperty("response_json",encoded); cases.add(row);
    }
    private static void requireProductionJar(Path expected, Class<?> type) throws Exception {
        Path actual = Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();
        if (!actual.equals(expected)) throw new AssertionError(type.getName()+" loaded from "+actual+", expected "+expected);
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Expected exact production JAR path");
        Path jar = Path.of(args[0]).toRealPath();
        for (Class<?> type : new Class<?>[]{BridgeJson.class, NativeLivingSnapshot.class,
                NativeLivingSnapshot.Row.class, NativeLivingSnapshot.Batch.class}) requireProductionJar(jar,type);
        JsonArray cases = new JsonArray();
        add(cases,"known_null",state(true,false,false,false));
        add(cases,"current_target",state(true,true,false,false));
        add(cases,"persistent_target",state(true,false,true,false));
        add(cases,"both_targets",state(true,true,true,false));
        add(cases,"unknown_absent",state(false,false,false,false));
        add(cases,"stale_absent",state(true,false,false,true));
        JsonObject missing = state(true,false,false,false); facts(missing).remove("current_target");
        add(cases,"missing_current_target",missing);
        missing = state(true,false,false,false); facts(missing).getAsJsonObject("bee").remove("persistent_anger_target_uuid");
        add(cases,"missing_persistent_target",missing);
        JsonObject unrelated = state(true,false,false,false), nearby = unrelated.getAsJsonObject("nearby");
        for (JsonObject object : new JsonObject[]{unrelated,nearby,nearby.getAsJsonArray("entities").get(0).getAsJsonObject(),
                facts(unrelated),facts(unrelated).getAsJsonObject("bee")}) object.add("legacy_null",JsonNull.INSTANCE);
        add(cases,"unrelated_nulls",unrelated);
        JsonObject multiple = state(true,false,false,false); nearby = multiple.getAsJsonObject("nearby");
        JsonArray entities = nearby.getAsJsonArray("entities");
        entities.add(living("00000000-0000-4000-8000-000000000010",10,"minecraft:sheep","net.minecraft.world.entity.animal.Sheep",
                26,.9,1.3,true,false,false,false));
        JsonObject boat = entity("00000000-0000-4000-8000-000000000011",11,"minecraft:boat","net.minecraft.world.entity.vehicle.Boat",28,1.375,.5625);
        boat.addProperty("ordinary_boat",true); boat.addProperty("passenger_count",0); boat.addProperty("yaw_rate",0.0);
        entities.add(boat); nearby.addProperty("total",3); nearby.addProperty("returned",3);
        add(cases,"multiple_rows",multiple);
        System.out.println(cases);
    }
}
