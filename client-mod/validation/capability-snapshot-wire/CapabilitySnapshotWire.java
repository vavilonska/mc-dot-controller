package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.nio.file.Path;
import java.util.Map;

/** Synthetic inputs through the exact production snapshot and HTTP encoder; never starts Minecraft. */
public final class CapabilitySnapshotWire {
    private static final Object CONTEXT = new Object();
    private static final String DIMENSION = "minecraft:overworld";
    private static final String WORLD = "11111111-2222-4333-8444-555555555555";
    private static final String SESSION = "22222222-3333-4444-8555-666666666666";
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
    private static JsonObject protocol() {
        JsonObject value=new JsonObject();value.addProperty("ok",true);value.addProperty("protocol","mineclient-bridge");
        value.addProperty("schema_version",2);return value;
    }
    private static JsonObject bundle(JsonObject state) {
        for(var field:protocol().entrySet())state.add(field.getKey(),field.getValue());
        JsonObject player=state.getAsJsonObject("player");player.addProperty("yaw",0);player.addProperty("pitch",0);
        JsonObject action=state.getAsJsonObject("client_action");action.addProperty("ok",true);
        action.addProperty("action_schema_version",1);action.addProperty("input_owner","direct");
        JsonObject budget=state.has("movement_budget")?state.getAsJsonObject("movement_budget"):new JsonObject();
        if(!budget.has("schema_version")){budget.addProperty("schema_version",1);budget.addProperty("status","unarmed");}
        action.add("movement_budget",budget);state.add("movement_budget",budget.deepCopy());
        JsonObject menu=new JsonObject();menu.addProperty("menu_class","InventoryMenu");menu.addProperty("container_id",0);
        menu.addProperty("state_id",0);menu.add("slots",new JsonArray());
        menu.add("carried",com.google.gson.JsonParser.parseString("{\"id\":\"\",\"count\":0,\"empty\":true}"));state.add("menu",menu);
        JsonObject status=protocol(),screen=protocol();status.addProperty("in_world",true);
        status.addProperty("run_id","synthetic-capability-wire");status.addProperty("process_id",1234);status.add("held_mappings",new JsonArray());
        status.add("world",state.get("world").deepCopy());status.add("player",player.deepCopy());
        status.getAsJsonObject("world").addProperty("present",true);status.getAsJsonObject("player").addProperty("present",true);
        status.add("client_action",action.deepCopy());JsonObject statusScreen=new JsonObject();statusScreen.addProperty("present",false);
        status.add("screen",statusScreen);screen.addProperty("open",false);screen.add("menu",menu.deepCopy());
        screen.addProperty("children_total",0);screen.addProperty("children_returned",0);screen.addProperty("children_truncated",false);
        screen.add("children",new JsonArray());
        var context=new CapabilitySnapshot.Context(CONTEXT,player,action,null,menu,WORLD,PLAYER,DIMENSION,SESSION,TICK);
        return CapabilitySnapshot.assemble(context,context,status,action,state,screen,action.deepCopy());
    }
    private static void add(JsonArray cases, String name, JsonObject state) throws Exception {
        JsonObject envelope=bundle(state),before=envelope.deepCopy();String encoded=BridgeJson.toJson(envelope);
        if (!envelope.equals(before) || !encoded.equals(BridgeJson.toJson(envelope))) throw new AssertionError("Encoder mutated input or was unstable: " + name);
        JsonObject parsed=com.google.gson.JsonParser.parseString(encoded).getAsJsonObject();
        JsonObject action=parsed.getAsJsonObject("action").deepCopy();action.remove("protocol");action.remove("schema_version");
        if(!action.equals(parsed.getAsJsonObject("status").get("client_action"))
                || !action.equals(parsed.getAsJsonObject("state").get("client_action"))
                || !action.get("movement_budget").equals(parsed.getAsJsonObject("state").get("movement_budget")))
            throw new AssertionError("Sibling null/value mismatch through actual production JAR encoder: "+name);
        JsonObject row = new JsonObject(); row.addProperty("name",name); row.addProperty("response_json",encoded); cases.add(row);
    }
    private static void requireProductionJar(Path expected, Class<?> type) throws Exception {
        Path actual = Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();
        if (!actual.equals(expected)) throw new AssertionError(type.getName()+" loaded from "+actual+", expected "+expected);
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Expected exact production JAR path");
        Path jar = Path.of(args[0]).toRealPath();
        for (Class<?> type : new Class<?>[]{BridgeJson.class, CapabilitySnapshot.class, MovementBudgetLedger.class, ActionRegistry.class, ClientActionRequest.Rejected.class, NativeLivingSnapshot.class,
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
        for(String phase:new String[]{"armed","stopping","sealed"}) {
            var ledger=new MovementBudgetLedger("wire-bundle",SESSION,WORLD,PLAYER,CONTEXT,CONTEXT,0,64,0,SOURCE_NANO);
            if(phase.equals("stopping"))for(int i=1;i<=60;i++) {
                ledger.beginTick();ledger.beginMove(true,.5,0,0);ledger.position(i*.5,64,0);ledger.endMove();
            }
            if(phase.equals("sealed")) {
                for(int i=0;i<3;i++)ledger.sample(CONTEXT,CONTEXT,SESSION,0,64,0,true,true);
                ledger.seal(SAMPLE_NANO);
            }
            var registry=new ActionRegistry();
            var request=new ClientActionRequest("terminal","select_hotbar",3000,java.util.List.of(),null,null,"north",0,false,false,0,0,0,"pickup",new JsonObject());
            var entry=registry.begin(request);entry.result.add("unknown_metric",JsonNull.INSTANCE);
            JsonObject nested=new JsonObject();nested.add("unknown",JsonNull.INSTANCE);entry.result.add("nested",nested);
            registry.finishAfterCleanup("succeeded","selected",true);JsonObject terminal=registry.status(null);terminal.addProperty("action_session",SESSION);
            JsonObject metered=state(true,false,false,false);metered.add("client_action",terminal);metered.add("movement_budget",ledger.snapshot());
            add(cases,"meter_"+phase,metered);
        }
        System.out.println(cases);
    }
}
