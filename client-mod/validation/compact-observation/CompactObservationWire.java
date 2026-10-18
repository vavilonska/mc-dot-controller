package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;

/** Actual compact projection and BridgeJson HTTP codec over synthetic facts, no world startup. */
public final class CompactObservationWire {
    static int checks;
    static void check(boolean b){checks++;if(!b)throw new AssertionError("check "+checks);}
    static void reject(Runnable action){try{action.run();throw new AssertionError("accepted invalid");}catch(ClientActionRequest.Rejected expected){checks++;}}
    static JsonObject json(String value){return JsonParser.parseString(value).getAsJsonObject();}
    public static void main(String[] args)throws Exception{
        Object nativeObject=new Object();
        var context=new ObservationClientClock.Context(nativeObject,nativeObject,nativeObject,nativeObject,nativeObject,
            "compact-wire",1234,"server-wire","11111111-2222-4333-8444-555555555555","minecraft:overworld",
            "00000000-0000-4000-8000-000000000001","22222222-3333-4444-8555-666666666666");
        var stamp=new ObservationClientClock.Stamp("33333333-4444-4555-8666-777777777777",5,1000000,context);
        JsonObject world=json("{\"game_time\":100}");world.addProperty("world_generation",context.worldGeneration());world.addProperty("dimension",context.dimension());world.addProperty("integrated_server_instance",context.serverInstance());
        JsonObject player=json("{\"x\":0.5,\"y\":64,\"z\":0.5,\"inventory_total\":0,\"inventory_truncated\":false,\"inventory\":[],\"alive\":true,\"health\":20}");
        player.addProperty("uuid",context.playerUuid());player.addProperty("dimension",context.dimension());
        JsonObject action=json("{\"action_schema_version\":1,\"action_id\":null,\"status\":\"idle\"}");action.addProperty("action_session",context.actionSession());
        JsonObject state=json("{\"focused\":true,\"private_singleplayer\":true,\"paused\":false,\"screen_open\":false,\"held_inputs\":{\"neutral\":true},\"menu\":{\"menu_class\":\"InventoryMenu\",\"container_id\":0,\"state_id\":0,\"carried\":{\"id\":\"minecraft:air\",\"count\":0}}}");
        state.add("world",world);state.add("player",player);
        JsonObject bundle=new JsonObject();bundle.add("state",state);bundle.add("action",action);bundle.add("status",new JsonObject());bundle.add("screen",new JsonObject());
        ObservationClockWire.snapshot(bundle,stamp,stamp);
        JsonObject terrain=json("{\"radius\":1,\"vertical\":2,\"game_time\":100,\"response_game_time\":100,\"offset\":0,\"next_offset\":45,\"total_cells\":45,\"returned\":45,\"complete\":true,\"next_cursor\":null,\"unknown_cells\":0,\"origin\":{\"x\":0,\"y\":64,\"z\":0},\"generation\":\"44444444-5555-4666-8777-888888888888\"}");
        terrain.addProperty("world_generation",context.worldGeneration());terrain.addProperty("dimension",context.dimension());
        JsonArray cells=new JsonArray();for(int x=-1;x<=1;x++)for(int z=-1;z<=1;z++)for(int y=62;y<=66;y++){
            JsonObject row=json("{\"status\":\"loaded\",\"known\":true,\"id\":\"minecraft:air\"}");row.addProperty("x",x);row.addProperty("y",y);row.addProperty("z",z);cells.add(row);
        }terrain.add("cells",cells);ObservationClockWire.page(terrain,stamp,stamp);
        var request=CompactObservation.parse("request_id=compact-one&radius=1");JsonObject saved=bundle.deepCopy(),savedTerrain=terrain.deepCopy();
        JsonObject output=CompactObservation.project(request,bundle,terrain,stamp,stamp,41_496_861);
        var timing=new CompactObservation.Diagnostic(request,0);timing.returned=45;timing.terrainElapsed=252_893;timing.enter("terrain_ids",100_000);timing.enter("state",352_893);timing.external(1_000_000,11_000_000);timing.enter("final_context",41_000_000);timing.enter("projection",41_496_000);
        CompactObservation.complete(output,timing,41_496_861);
        check(output.get("native_elapsed_nanos").getAsString().equals("41496861"));
        check(output.getAsJsonObject("native_timing").getAsJsonObject("stage_elapsed_nanos").get("state").getAsLong()==40_647_107);
        check(output.getAsJsonObject("terrain").getAsJsonArray("cells").size()==45);
        check(saved.equals(bundle)&&savedTerrain.equals(terrain));check(!output.get("execution_authority").getAsBoolean());
        Path out=Path.of(args[0]);Files.createDirectories(out);Files.writeString(out.resolve("compact.json"),BridgeJson.toJson(output));
        for(String query:new String[]{"radius=1","request_id=compact&radius=3","request_id=a&request_id=b","request_id=a&wat=1","request_id=a&radius=true"})reject(()->CompactObservation.parse(query));
        reject(()->CompactObservation.project(request,bundle,terrain,stamp,new ObservationClientClock.Stamp(stamp.generation(),6,stamp.originNano(),context),1000));
        reject(()->CompactObservation.project(request,bundle,terrain,stamp,new ObservationClientClock.Stamp("55555555-6666-4777-8888-999999999999",5,stamp.originNano(),context),1000));
        JsonObject ahead=terrain.deepCopy();ahead.addProperty("game_time",101);final JsonObject timeAhead=ahead;reject(()->CompactObservation.project(request,bundle,timeAhead,stamp,stamp,1000));
        ahead=terrain.deepCopy();ahead.getAsJsonObject("source_clock").addProperty("count",6);final JsonObject clockAhead=ahead;reject(()->CompactObservation.project(request,bundle,clockAhead,stamp,stamp,1000));
        JsonObject incomplete=terrain.deepCopy();incomplete.addProperty("complete",false);reject(()->CompactObservation.project(request,bundle,incomplete,stamp,stamp,1000));
        JsonObject wrong=bundle.deepCopy();wrong.getAsJsonObject("state").getAsJsonObject("observation_clock").addProperty("count",4);reject(()->CompactObservation.project(request,wrong,terrain,stamp,stamp,1000));
        reject(()->CompactObservation.budget(100,99));reject(()->CompactObservation.budget(0,100000001));CompactObservation.budget(0,100000000);checks++;
        reject(()->CompactObservation.project(request,bundle,terrain,stamp,stamp,100_000_001));
        var slow=new CompactObservation.Diagnostic(request,0);slow.enter("state",252_893);slow.external(1_000_000,80_000_000);slow.enter("final_context",100_000_000);
        try{CompactObservation.budget(0,100_000_001);throw new AssertionError();}catch(ClientActionRequest.Rejected failure){
            JsonObject failed=failure.response();failed.add("compact_observation_diagnostic",slow.json(100_000_001));
            Files.writeString(out.resolve("over-budget.json"),BridgeJson.toJson(failed));check(slow.json(100_000_001).get("stage").getAsString().equals("final_context"));}
        JsonObject exact=CompactObservation.project(request,bundle,terrain,stamp,stamp,100_000_000);check(!exact.get("execution_authority").getAsBoolean());
        JsonObject huge=bundle.deepCopy();huge.getAsJsonObject("state").getAsJsonObject("player").addProperty("vehicle","x".repeat(65536));reject(()->CompactObservation.project(request,huge,terrain,stamp,stamp,1000));
        System.out.println("PASS "+checks+" compact production projection/codec assertions; no game execution");
    }
}
