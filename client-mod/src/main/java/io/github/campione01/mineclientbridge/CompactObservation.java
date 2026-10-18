package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Set;

/** Bounded display-only projection of one original native callback. Never dispatch authority. */
final class CompactObservation {
    static final int MAX_BYTES=65536, MAX_RADIUS=2, VERTICAL=2;
    static final long MAX_NANOS=100_000_000L;
    record Request(String id,int radius) { }
    /** Bounded read timing only. Same-turn checks, not duration, bind the snapshot. */
    static final class Diagnostic {
        static final java.util.List<String> STAGES=java.util.List.of("context","terrain_ids","state","final_context","projection");
        final Request request;final long started;String stage="context";int returned;long terrainElapsed;
        final java.util.Map<String,Long> stages=new java.util.LinkedHashMap<>();
        long stageStarted,externalElapsed;int externalSamples;
        Diagnostic(Request request,long started){this.request=request;this.started=started;stageStarted=started;for(String s:STAGES)stages.put(s,0L);}
        void enter(String next,long now){require(STAGES.contains(next),"timing_stage");stages.put(stage,stages.get(stage)+Math.max(0,now-stageStarted));stage=next;stageStarted=now;}
        void external(long before,long after){externalSamples++;externalElapsed+=Math.max(0,after-before);}
        void terrain(CompactTerrainScan.Result scan){returned=scan.cells().size();terrainElapsed=scan.elapsedNanos();}
        JsonObject json(long now){JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("request_id",request.id());
            j.addProperty("read_only",true);j.addProperty("execution_authority",false);j.addProperty("stage",stage);
            j.addProperty("radius",request.radius());j.addProperty("terrain_returned",returned);j.addProperty("terrain_total",(2*request.radius()+1)*(2*request.radius()+1)*5);
            j.addProperty("terrain_elapsed_nanos",Long.toString(Math.max(0,terrainElapsed)));j.addProperty("terrain_budget_nanos",Long.toString(CompactTerrainScan.MAX_NANOS));
            j.addProperty("callback_elapsed_nanos",Long.toString(Math.max(0,now-started)));j.addProperty("callback_budget_nanos",Long.toString(MAX_NANOS));
            JsonObject durations=new JsonObject();for(String s:STAGES)durations.addProperty(s,Long.toString(stages.get(s)+(s.equals(stage)?Math.max(0,now-stageStarted):0)));
            j.add("stage_elapsed_nanos",durations);j.addProperty("external_controller_elapsed_nanos",Long.toString(externalElapsed));
            j.addProperty("external_controller_samples",externalSamples);return j;}
    }
    static void complete(JsonObject body,Diagnostic diagnostic,long now) {
        budget(diagnostic.started,now);body.addProperty("native_elapsed_nanos",Long.toString(now-diagnostic.started));
        body.add("native_timing",diagnostic.json(now));
        try {require(BridgeJson.toJson(body).getBytes(StandardCharsets.UTF_8).length<=MAX_BYTES,"response_too_large");}
        catch(java.io.IOException failure){throw new ClientActionRequest.Rejected(409,"compact_observation_encoding_failed");}
    }
    static Request parse(String raw) {
        require(raw!=null && raw.length()<=256,"query");
        var values=new HashMap<String,String>();
        for(String part:raw.split("&",-1)){
            String[] pair=part.split("=",2);require(pair.length==2,"query");
            String key=URLDecoder.decode(pair[0],StandardCharsets.UTF_8),value=URLDecoder.decode(pair[1],StandardCharsets.UTF_8);
            require(Set.of("request_id","radius").contains(key)&&values.putIfAbsent(key,value)==null,"query");
        }
        String id=values.get("request_id"),radius=values.getOrDefault("radius","1");
        require(id!=null&&id.matches("[A-Za-z0-9_-]{1,64}")&&radius.matches("[12]"),"query");
        return new Request(id,Integer.parseInt(radius));
    }
    static void budget(long started,long now){require(now>=started&&now-started<=MAX_NANOS,"budget_exhausted");}
    static JsonObject fields(JsonObject source,String... names){
        JsonObject value=new JsonObject();
        for(String name:names)if(source.has(name))value.add(name,source.get(name).deepCopy());
        return value;
    }
    static JsonObject project(Request request,JsonObject bundle,JsonObject terrain,
                              ObservationClientClock.Stamp before,ObservationClientClock.Stamp after,long elapsed){
        budget(0,elapsed);
        require(before!=null&&before.sameTurn(after),"epoch_changed");
        require(bundle.get("observation_clock").equals(before.json()),"snapshot_clock");
        for(String key:new String[]{"status","action","state","screen"})
            require(bundle.getAsJsonObject(key).get("observation_clock").equals(before.json()),"sibling_clock");
        JsonObject state=bundle.getAsJsonObject("state"),player=state.getAsJsonObject("player"),world=state.getAsJsonObject("world"),action=bundle.getAsJsonObject("action");
        require(terrain.get("complete").getAsBoolean()&&terrain.get("next_cursor").isJsonNull()
            &&terrain.get("offset").getAsInt()==0&&terrain.get("next_offset").getAsInt()==terrain.get("total_cells").getAsInt(),"terrain_incomplete");
        require(terrain.get("source_clock").equals(before.json())&&terrain.get("response_clock").equals(before.json()),"terrain_clock");
        require(terrain.get("game_time").getAsLong()<=world.get("game_time").getAsLong()
            &&terrain.get("response_game_time").getAsLong()<=world.get("game_time").getAsLong(),"terrain_ahead_of_state");
        require(terrain.get("world_generation").equals(world.get("world_generation"))
            &&terrain.get("dimension").equals(world.get("dimension")),"terrain_context");
        JsonObject out=new JsonObject();out.addProperty("ok",true);out.addProperty("protocol","mineclient-bridge");out.addProperty("schema_version",2);
        out.addProperty("compact_observation_schema_version",1);out.addProperty("request_id",request.id());
        out.addProperty("read_only",true);out.addProperty("execution_authority",false);out.addProperty("server_confirmed",false);
        out.add("observation_clock",before.json());out.add("context",before.context().wire());
        JsonObject bounds=new JsonObject();bounds.addProperty("radius",request.radius());bounds.addProperty("vertical",VERTICAL);out.add("bounds",bounds);
        out.addProperty("native_elapsed_nanos",Long.toString(elapsed));out.addProperty("native_budget_nanos",Long.toString(MAX_NANOS));
        out.add("world",fields(world,"world_generation","dimension","integrated_server_instance","game_time","day_time","biome_id"));
        out.add("player",fields(player,"uuid","dimension","x","y","z","yaw","pitch","velocity","on_ground","alive","health","food","air","max_air","in_water","eye_in_water","in_lava","on_fire","selected_slot","mainhand","offhand","vehicle"));
        JsonArray inventory=new JsonArray();
        for(var row:player.getAsJsonArray("inventory"))inventory.add(fields(row.getAsJsonObject(),"slot","id","count","empty","damage","max_damage"));
        JsonObject items=new JsonObject();items.add("items",inventory);items.add("total",player.get("inventory_total").deepCopy());items.add("truncated",player.get("inventory_truncated").deepCopy());out.add("inventory",items);
        out.add("menu",fields(state.getAsJsonObject("menu"),"menu_class","container_id","state_id","carried","slots_total","slots_truncated","recovery_context"));
        out.add("control",fields(state,"focused","private_singleplayer","paused","screen_open","held_inputs"));
        JsonObject summary=fields(action,"action_schema_version","action_session","action_id","action","status","reason","ticks");
        if(action.has("result")&&action.get("result").isJsonObject())summary.add("outcome",fields(action.getAsJsonObject("result"),"unknown_outcome","requires_handoff","input_release_confirmed","effects_none_proven","interaction_result","placement_effect_verification"));
        summary.addProperty("details_omitted",true);out.add("action",summary);
        JsonObject terrainSummary=fields(terrain,"world_generation","dimension","generation","origin","radius","vertical","offset","next_offset","total_cells","returned","complete","unknown_cells","game_time","response_game_time","source_clock","response_clock","read_elapsed_micros","budget_exhausted");
        JsonArray cells=new JsonArray();for(var cell:terrain.getAsJsonArray("cells"))cells.add(fields(cell.getAsJsonObject(),"x","y","z","status","known","id"));terrainSummary.add("cells",cells);out.add("terrain",terrainSummary);
        JsonObject coverage=new JsonObject();coverage.addProperty("terrain_coordinate_complete",true);coverage.addProperty("terrain_physics_omitted",true);coverage.addProperty("entities_captured",false);coverage.addProperty("menu_slots_captured",false);coverage.addProperty("action_details_captured",false);coverage.addProperty("inventory_recovery_complete",false);out.add("coverage",coverage);
        // Integration-provided controller/rescue status is retained, never inferred from input neutrality.
        for(String key:new String[]{"external_controller","native_fall_rescue_status"}){
            if(state.has(key))out.add(key,state.get(key).deepCopy());
            else {JsonObject unavailable=new JsonObject();unavailable.addProperty("status","unavailable");out.add(key,unavailable);}
        }
        try {require(BridgeJson.toJson(out).getBytes(StandardCharsets.UTF_8).length<=MAX_BYTES,"response_too_large");}
        catch(java.io.IOException failure){throw new ClientActionRequest.Rejected(409,"compact_observation_encoding_failed");}
        return out;
    }
    static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,"compact_observation_"+reason);}
    private CompactObservation() { }
}
