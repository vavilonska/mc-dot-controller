package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Random;

/** Runs production pure classes and exact Java HTTP wire parser, without starting Minecraft. */
public final class NativeFallRescueChecks {
    static int checks;
    static void check(boolean b,String label){checks++;if(!b)throw new AssertionError(label);}
    static void reject(Runnable r,String label){checks++;try{r.run();throw new AssertionError(label);}catch(IllegalStateException|ClientActionRequest.Rejected expected){}}
    static JsonObject arm(){return JsonParser.parseString("{\"fall_rescue_schema_version\":1,\"arm_id\":\"arm-a\",\"owner_id\":\"owner-a\",\"expected_action_session\":\"session-a\",\"expected_world_generation\":\"world-a\",\"expected_player_uuid\":\"player-a\",\"permitted_action_ids\":[\"combat-a\"]}").getAsJsonObject();}
    public static void main(String[] args)throws Exception{
        var policy=FallRescuePolicy.arm(arm());check(policy.ttlMs()==60000,"stable default TTL");check(policy.episodes()==1,"bounded default");
        for(int n:new int[]{-1,0,999,600001,Integer.MAX_VALUE}){var j=arm();j.addProperty("ttl_ms",n);reject(()->FallRescuePolicy.arm(j),"invalid TTL "+n);}
        for(int n:new int[]{1000,60000,600000}){var j=arm();j.addProperty("ttl_ms",n);check(FallRescuePolicy.arm(j).ttlMs()==n,"TTL boundary "+n);}
        for(String k:new String[]{"arm_id","owner_id","expected_action_session","expected_world_generation","expected_player_uuid"}){var j=arm();j.addProperty(k,"");reject(()->FallRescuePolicy.arm(j),"empty binding "+k);}
        var wrong=arm();wrong.addProperty("autonomous",true);reject(()->FallRescuePolicy.arm(wrong),"unknown field");
        var duplicate=arm();duplicate.getAsJsonArray("permitted_action_ids").add("combat-a");reject(()->FallRescuePolicy.arm(duplicate),"duplicate action id");
        var noIds=arm();noIds.remove("permitted_action_ids");reject(()->FallRescuePolicy.arm(noIds),"authority list required even if empty");
        var invalid=arm();invalid.addProperty("max_episodes",17);reject(()->FallRescuePolicy.arm(invalid),"episode upper bound");
        check(FallRescuePolicy.dangerous(0,4,20),"prearm knockup future descent");check(!FallRescuePolicy.dangerous(0,3,20),"normal low fall");
        check(FallRescuePolicy.dangerous(Float.NaN,0,20),"unknown forecast conservative");
        var arbiter=new SingleInputArbiter();var first=arbiter.claim("e1");check(arbiter.owns(first),"acquisition owns before old cleanup");
        reject(()->arbiter.claim("reentrant"),"reentrant old cleanup admission blocked");
        arbiter.stop();check(!arbiter.owns(first)&&!arbiter.blocked(),"stop revokes old callback");
        var second=arbiter.claim("e2");arbiter.release(first);check(arbiter.owns(second),"stale cleanup cannot release new owner");
        arbiter.quarantine("unknown");check(arbiter.blocked()&&!arbiter.owns(second),"unknown blocks automation");arbiter.stop();check(arbiter.quarantined(),"stop cannot clear unknown");reject(()->arbiter.claim("retry"),"unknown cannot retry");
        var random=new Random(817733);for(int run=0;run<1000;run++){
            var a=new SingleInputArbiter();SingleInputArbiter.Lease lease=null;
            for(int step=0;step<100;step++){
                switch(random.nextInt(5)){
                    case 0 -> {if(!a.blocked())lease=a.claim("r"+run+"s"+step);else{var captured=a;reject(()->captured.claim("bad"),"random blocked claim");}}
                    case 1 -> a.stop();case 2 -> a.release(lease);case 3 -> {if(random.nextInt(12)==0)a.quarantine("fault");}
                    default -> {if(a.quarantined())check(!a.owns(lease),"quarantine invalidates all tokens");}
                }
                if(a.owns(lease))check(a.blocked(),"exclusive owner invariant");
            }
        }
        for(int failStage=0;failStage<5;failStage++){
            var e=new FallRescueEpisode("fault"+failStage,0);if(failStage==0){e.end("cancelled_before_call");check(!e.attempted(),"before-call cancel");}
            else{e.attempt();if(failStage>=2)e.packet();if(failStage>=3)e.predictedWater(true);if(failStage==4)e.serverObservation(true,false,true);e.end("injected_failure");check(!e.confirmed(),"failure/prediction cannot claim rescue");}
            reject(e::attempt,"fault cannot replay");
        }
        var e=new FallRescueEpisode("one",8);e.attempt();reject(e::attempt,"single use");e.packet();reject(e::packet,"single packet");
        e.predictedWater(true);check(!e.confirmed(),"prediction is not success");e.serverObservation(true,true,false);check(!e.confirmed(),"placement is not landing");
        e.serverObservation(true,true,true);check(e.confirmed()&&e.terminal(),"authoritative water bucket landing proof");
        e.end("late_error");check(e.confirmed()&&e.outcome().equals("server_placement_and_landing_observed"),"terminal stable");
        check(!new FallRescueEpisode("timeout",0).timedOut(199)&&new FallRescueEpisode("timeout",0).timedOut(200),"episode tick deadline");
        var ordered=new FallRescueEpisode("ordered",0);ordered.attempt();ordered.serverObservation(false,false,true);
        ordered.serverObservation(true,true,false);check(!ordered.confirmed(),"landing before placement is not proof");
        ordered.serverObservation(false,false,true);check(ordered.confirmed(),"later alive landing confirms placement");
        var operation=new FallRescueFence();long oldOperation=operation.stamp();operation.changed();
        reject(()->operation.commit(oldOperation),"stop during arm invalidates outer commit");
        long beforeReplace=operation.stamp();operation.commit(beforeReplace);
        reject(()->operation.commit(beforeReplace),"nested arm cannot be overwritten");
        var finalOwner=new SingleInputArbiter();var finalLease=finalOwner.claim("final");
        check(!FallRescueFence.afterHook(()->{finalOwner.stop();return true;},()->finalOwner.owns(finalLease)),"stop in final neutral callback wins");
        var cleanupOwner=new SingleInputArbiter();cleanupOwner.claim("cleanup");
        check(!cleanupOwner.stopAndCleanup("unknown_effect",()->{check(cleanupOwner.quarantined(),"unknown latched before cleanup hook");throw new IllegalStateException("hook");}),"thrown cleanup reported");
        check(cleanupOwner.quarantined()&&cleanupOwner.blocked(),"thrown cleanup never frees unknown owner");
        var cleanupOnly=new SingleInputArbiter();cleanupOnly.claim("clean");
        check(!cleanupOnly.stopAndCleanup(null,()->{throw new IllegalStateException("keyup");})&&cleanupOnly.quarantined(),"cleanup failure itself quarantines");
        var cleanupReentry=new SingleInputArbiter();cleanupReentry.claim("old");
        check(cleanupReentry.stopAndCleanup(null,()->{cleanupReentry.stop();reject(()->cleanupReentry.claim("new"),"nested stop cannot release cleanup fence");}),"clean cleanup succeeds");
        check(!cleanupReentry.blocked(),"confirmed cleanup releases control");
        JsonArray wire=new JsonArray();var adapter=new FallRescueControl.Adapter(){
            public JsonObject arm(FallRescuePolicy.Arm r){var j=new JsonObject();j.addProperty("status","armed");j.addProperty("arm_id",r.id());j.addProperty("owner_id",r.owner());return j;}
            public JsonObject renew(FallRescuePolicy.Renew r){var j=new JsonObject();j.addProperty("status","armed");j.addProperty("expected_arm_revision",r.revision());return j;}
            public JsonObject disarm(FallRescuePolicy.Stop r){var j=new JsonObject();j.addProperty("status","disarmed");return j;}
            public JsonObject status(){var j=new JsonObject();j.addProperty("status","disarmed");return j;}
        };
        var out=BridgeServer.ActionResponses.result(()->FallRescueControl.apply("arm",arm(),adapter),false);
        check(out.status()==200&&out.body().get("status").getAsString().equals("armed"),"real Java HTTP wrapper arm wire");wire.add(out.body());
        out=BridgeServer.ActionResponses.result(()->FallRescueControl.apply("arm",wrong,adapter),false);check(out.status()==409,"real Java rejection wire");wire.add(out.body());
        var renew=JsonParser.parseString("{\"fall_rescue_schema_version\":1,\"arm_id\":\"arm-a\",\"owner_id\":\"owner-a\",\"expected_arm_revision\":1,\"ttl_ms\":60000}").getAsJsonObject();
        out=BridgeServer.ActionResponses.result(()->FallRescueControl.apply("renew",renew,adapter),false);check(out.status()==200,"renew wire");wire.add(out.body());
        var stop=JsonParser.parseString("{\"fall_rescue_schema_version\":1,\"arm_id\":\"arm-a\",\"owner_id\":\"owner-a\"}").getAsJsonObject();
        out=BridgeServer.ActionResponses.result(()->FallRescueControl.apply("disarm",stop,adapter),false);check(out.status()==200,"disarm wire");wire.add(out.body());
        if(args.length>0)Files.writeString(Path.of(args[0]),wire.toString());
        System.out.println("PASS NativeFallRescueChecks checks="+checks+" game_started=false real_world_acceptance=NOT_RUN");
    }
}
