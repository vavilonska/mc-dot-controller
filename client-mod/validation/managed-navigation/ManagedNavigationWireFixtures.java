package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
/** Canonical route payload -> actual response wrapper -> exact HTTP codec. */
public final class ManagedNavigationWireFixtures {
    static final long START=1234;
    static JsonObject requestBody(){
        JsonObject b=new JsonObject();b.addProperty("managed_navigation_schema_version",1);b.addProperty("operation_id","a".repeat(32));
        b.addProperty("owner_id","b".repeat(32));b.addProperty("owner_generation",1);b.addProperty("job_id","job_original");
        b.addProperty("expected_action_session","session");b.addProperty("expected_world_generation","world");b.addProperty("expected_player_uuid","player");
        b.addProperty("expected_dimension","minecraft:overworld");b.addProperty("source_tick",9);b.addProperty("source_nano",Long.toString(START));
        b.addProperty("timeout_ms",1000);b.addProperty("goal_x",100);b.addProperty("goal_y",64);b.addProperty("goal_z",100);b.addProperty("max_distance",200);b.addProperty("min_health",12);return b;
    }
    static ManagedNavigationLease.Request request(){return ManagedNavigationControl.parse(requestBody());}
    static JsonObject proof(long tick,boolean busy){return ExternalControllerProof.snapshot(new ExternalControllerProof.Context(
        new Object(),new Object(),new Object(),"session","world","player",tick),c->new ExternalControllerProof.Facts(
        "present",true,true,1,busy,busy,false,false,busy,busy?1:0,12,busy?1:0,"version_pinned_actual_api_sample"));}
    static void row(JsonArray rows,String name,ManagedNavigationLease.Entry e,boolean busy,long now)throws Exception{
        JsonObject payload=ManagedNavigationResponses.status(e,e==null?null:proof(e.lastTick,busy),now);
        var response=BridgeServer.ActionResponses.result(()->payload.deepCopy(),false);
        if(response.status()!=200)throw new AssertionError(name+" status");
        JsonObject row=new JsonObject();row.addProperty("request_wire",BridgeJson.toJson(requestBody()));row.addProperty("name",name);row.addProperty("http_status",response.status());
        row.addProperty("wire",BridgeJson.toJson(response.body()));row.addProperty("embedded_wire",BridgeJson.toJson(payload));
        JsonObject state=new JsonObject();state.add("managed_navigation_status",payload.deepCopy());
        JsonObject unrelated=payload.deepCopy();state.add("unrelated",unrelated);
        row.addProperty("state_wire",BridgeJson.toJson(state));rows.add(row);
    }
    public static void main(String[] args)throws Exception{
        for(String key:new String[]{"managed_navigation_schema_version","source_tick","goal_x","extra"}){
            JsonObject bad=requestBody();bad.addProperty(key,true);
            try{ManagedNavigationControl.parse(bad);throw new AssertionError("native parser accepted "+key);}catch(ClientActionRequest.Rejected expected){if(expected.httpStatus!=400)throw new AssertionError("native parser status");}
        }
        JsonArray rows=new JsonArray();var success=new ManagedNavigationLease();var e=success.claim(request(),START,9);success.startAttempt(e);
        row(rows,"routing",e,true,START+10_000_000L);success.sample(e,true,true,true,10,START+20_000_000L);
        row(rows,"one_idle_sample",e,false,START+20_000_000L);success.sample(e,true,true,true,11,START+30_000_000L);
        e.settingsRestored=true;success.settle(e);row(rows,"settled_goal",e,false,START+30_000_000L);
        var cancel=new ManagedNavigationLease();var c=cancel.claim(request(),START,9);cancel.startAttempt(c);cancel.requestStop(c,"managed_navigation_cancel_requested",START+10_000_000L);cancel.stopAttempt(c);c.cancelAccepted=true;
        row(rows,"stopping",c,true,START+10_000_000L);cancel.sample(c,true,true,false,10,START+20_000_000L);cancel.sample(c,true,true,false,11,START+30_000_000L);c.settingsRestored=true;cancel.settle(c);
        row(rows,"settled_cancel",c,false,START+30_000_000L);
        var unknown=new ManagedNavigationLease();var u=unknown.claim(request(),START,9);unknown.startAttempt(u);unknown.unknown(u,"managed_navigation_start_outcome_unknown");
        row(rows,"unknown",u,true,START+40_000_000L);row(rows,"unowned_idle",null,false,START);
        var rejected=BridgeServer.ActionResponses.result(()->{throw new ClientActionRequest.Rejected(409,"managed_navigation_external_idle_required");},false);
        if(rejected.status()!=409)throw new AssertionError("error HTTP status");JsonObject error=new JsonObject();error.addProperty("name","rejected");error.addProperty("http_status",rejected.status());error.addProperty("wire",BridgeJson.toJson(rejected.body()));rows.add(error);
        Files.writeString(Path.of(args[0]),new GsonBuilder().setPrettyPrinting().create().toJson(rows)+"\n");System.out.println("managed canonical rows="+rows.size());
    }
}
