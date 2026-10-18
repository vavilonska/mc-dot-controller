package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;

/** Canonical production model -> ActionResponses -> BridgeJson. No Minecraft startup. */
public final class ExternalNavigationWireFixtures {
    static final long START=1234L;
    static JsonObject proof(long tick,boolean busy){
        return ExternalControllerProof.snapshot(new ExternalControllerProof.Context(new Object(),new Object(),new Object(),
            "session","world","player",tick),c -> new ExternalControllerProof.Facts("present",true,true,1,
            busy,busy,false,false,busy,busy?1:0,12,busy?1:0,"version_pinned_actual_api_sample"));
    }
    static void row(JsonArray rows,String name,JsonObject payload,int expected) throws Exception {
        var response=BridgeServer.ActionResponses.result(() -> payload.deepCopy(),false);
        if(response.status()!=expected)throw new AssertionError(name+" HTTP status");
        JsonObject row=new JsonObject();row.addProperty("name",name);row.addProperty("http_status",response.status());
        row.addProperty("wire",BridgeJson.toJson(response.body()));row.addProperty("embedded_wire",BridgeJson.toJson(payload));
        JsonObject state=new JsonObject();state.add("external_navigation_status",payload.deepCopy());
        state.addProperty("unrelated_null",(String)null);JsonObject other=new JsonObject();other.addProperty("cancel_accepted",(String)null);other.addProperty("external_navigation_schema_version",1);state.add("unrelated",other);
        row.addProperty("state_wire",BridgeJson.toJson(state));
        JsonObject unrelated=new JsonObject();unrelated.addProperty("external_navigation_schema_version",true);
        unrelated.addProperty("cancel_accepted",(String)null);row.addProperty("boolean_schema_wire",BridgeJson.toJson(unrelated));
        unrelated.addProperty("external_navigation_schema_version",1.0);row.addProperty("floating_schema_wire",BridgeJson.toJson(unrelated));
        rows.add(row);
    }
    static ExternalNavigationLease.Request request(){return new ExternalNavigationLease.Request("a".repeat(32),"b".repeat(32),1,
        "job_original","session","world","player","minecraft:overworld",9,START,1000);}
    public static void main(String[] args) throws Exception {
        JsonArray rows=new JsonArray();
        var busy=new ExternalNavigationLease();var e=busy.claim(request(),START,9);busy.attempt(e);e.cancelAccepted=true;
        row(rows,"busy_attempted",ExternalNavigationResponses.status(e,proof(9,true),START+10_000_000L),200);
        busy.sample(e,true,true,10,START+20_000_000L);
        row(rows,"one_idle_sample",ExternalNavigationResponses.status(e,proof(10,false),START+20_000_000L),200);
        busy.sample(e,true,true,11,START+30_000_000L);
        row(rows,"settled_attempted",ExternalNavigationResponses.status(e,proof(11,false),START+30_000_000L),200);
        var idle=new ExternalNavigationLease();var i=idle.claim(request(),START,9);
        row(rows,"already_idle_pending",ExternalNavigationResponses.status(i,proof(9,false),START+10_000_000L),200);
        idle.sample(i,true,true,10,START+20_000_000L);idle.sample(i,true,true,11,START+30_000_000L);
        row(rows,"already_idle_settled",ExternalNavigationResponses.status(i,proof(11,false),START+30_000_000L),200);
        var failed=new ExternalNavigationLease();var f=failed.claim(request(),START,9);failed.attempt(f);failed.unknown(f,"external_navigation_stop_outcome_unknown");
        row(rows,"attempted_unknown_null",ExternalNavigationResponses.status(f,proof(9,true),START+40_000_000L),200);
        row(rows,"unowned_idle",ExternalNavigationResponses.status(null,null,START),200);
        var rejected=BridgeServer.ActionResponses.result(() -> {throw new ClientActionRequest.Rejected(409,"external_navigation_original_owner_unresolved");},false);
        if(rejected.status()!=409)throw new AssertionError("rejected HTTP status");
        JsonObject error=new JsonObject();error.addProperty("name","rejected");error.addProperty("http_status",rejected.status());
        error.addProperty("wire",BridgeJson.toJson(rejected.body()));rows.add(error);
        Files.writeString(Path.of(args[0]),new GsonBuilder().setPrettyPrinting().create().toJson(rows)+"\n");
        System.out.println("canonical response rows="+rows.size());
    }
}
