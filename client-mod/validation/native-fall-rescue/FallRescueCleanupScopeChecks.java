package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Production pure release scope/arbiter/registry + exact HTTP codec; no game is started. */
public final class FallRescueCleanupScopeChecks {
 static int checks;
 static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
 static void rejects(Runnable run,String message){checks++;try{run.run();throw new AssertionError(message);}catch(IllegalStateException expected){}}
 public static void main(String[] args)throws Exception {
  var scope=new FallRescueCleanupScope();var arbiter=new SingleInputArbiter();var lease=arbiter.claim("rescue-original");
  Object owner=new Object(),guard=new Object(),entry=new Object();
  check(arbiter.blocked(),"old !ownsInput predicate deterministically fails while authorized successor is held");
  var token=scope.open(owner,guard,entry,()->arbiter.owns(lease));
  check(scope.permits(guard,entry)&&scope.bound(owner,entry),"exact original release accepted under same successor");
  check(!scope.permits(new Object(),entry)&&!scope.permits(guard,new Object()),"foreign guard or entry rejected");
  check(!scope.bound(new Object(),entry),"foreign original owner rejected");
  rejects(()->scope.open(owner,guard,entry,()->true),"nested release scope rejected");
  rejects(()->arbiter.claim("other"),"scope never frees input arbiter");
  scope.close(token);check(!scope.active()&&!scope.permits(guard,entry),"closed scope cannot authorize release");
  var later=scope.open(owner,guard,entry,()->true);scope.close(token);
  check(scope.permits(guard,entry),"closing stale token cannot retire replacement scope");scope.close(later);
  for(String fault:new String[]{"stop","different_successor","arm","operation","world","session","player","mode","screen","deadline","tick_budget","dispatch_attempted","preemption_verified","external_owner","action_revision","registry_replaced","runtime_replaced"}) {
   boolean[] live={true};var current=scope.open(owner,guard,entry,()->live[0]);
   check(scope.permits(guard,entry),fault+" starts bound");live[0]=false;
   check(!scope.permits(guard,entry)&&!scope.bound(owner,entry),fault+" late callback refuses");live[0]=true;
   check(!scope.permits(guard,entry),fault+" cannot revive invalid scope");scope.close(current);
  }
  var throwing=scope.open(owner,guard,entry,()->{throw new IllegalStateException("callback");});
  check(!scope.permits(guard,entry),"thrown callback fails closed");scope.close(throwing);
  for(int channel=0;channel<3;channel++) {
   boolean[] raw={false};int[] isolated={0};Object[] guarded={null};
   var current=scope.open(owner,guard,entry,()->FallRescueCleanupScope.channelsAbsent(raw[0],isolated[0],guarded[0]));
   check(scope.permits(guard,entry),"foreign channel initially absent");
   if(channel==0)raw[0]=true;else if(channel==1)isolated[0]=1;else guarded[0]=new Object();
   Object foreign=guarded[0];
   check(!scope.permits(guard,entry),"new unrelated channel refuses next old release");
   check(channel==0?raw[0]:channel==1?isolated[0]==1:guarded[0]==foreign,"foreign channel is neither released nor cancelled");
   raw[0]=false;isolated[0]=0;guarded[0]=null;
   check(!scope.permits(guard,entry),"foreign channel disappearance cannot revive invalid cleanup");scope.close(current);
  }
  var rows=new JsonArray();
  for(boolean valid:new boolean[]{true,false}) {
   var registry=new ActionRegistry();var body=new JsonObject();body.addProperty("action_id","471ba4ebf1d95447acd7bf48fc51cbc1");body.addProperty("action","combat_entity");
   var request=new ClientActionRequest("471ba4ebf1d95447acd7bf48fc51cbc1","combat_entity",30000,List.of(),null,null,null,-1,false,false,-1,-1,0,null,body);
   var original=registry.begin(request);original.result.addProperty("preempted_by_native_fall_rescue",true);
   original.result.addProperty("unknown_outcome",true);original.result.addProperty("requires_handoff",true);original.result.addProperty("no_auto_resume",true);
   boolean[] live={true};var current=scope.open(owner,guard,original,()->live[0]);
   check(scope.permits(guard,original),"entry starts authorized");live[0]=valid;
   boolean released=scope.bound(owner,original);registry.finishAfterCleanup("cancelled","native_fall_rescue_preempted",released);scope.close(current);
   var response=BridgeServer.ActionResponses.result(()->registry.status("471ba4ebf1d95447acd7bf48fc51cbc1"),false);
   var encoded=BridgeJson.toJson(response.body());var actual=JsonParser.parseString(encoded).getAsJsonObject();
   check(actual.get("status").getAsString().equals(valid?"cancelled":"failed"),"actual terminal classification");
   check(actual.getAsJsonObject("result").get("input_release_confirmed").getAsBoolean()==valid,"actual release flag");
   check(actual.getAsJsonObject("result").get("unknown_outcome").getAsBoolean(),"original effects remain UNKNOWN");
   var row=new JsonObject();row.addProperty("scope_live",valid);row.addProperty("http_status",response.status());row.addProperty("body",encoded);rows.add(row);
  }
  Files.writeString(Path.of(args[0]),rows.toString());System.out.println("fall cleanup scope/registry checks="+checks);
 }
}
