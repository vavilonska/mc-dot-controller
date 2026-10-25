package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.util.*;
public final class ReactiveDefenseChecks {
 static int checks;static void yes(boolean ok){checks++;if(!ok)throw new AssertionError("check "+checks);}static void denied(Runnable f){try{f.run();throw new AssertionError("expected rejection");}catch(ClientActionRequest.Rejected expected){checks++;}}
 static JsonObject arm(){JsonObject b=new JsonObject();for(String k:List.of("arm_id","expected_world_generation","expected_player_uuid","expected_action_session"))b.addProperty(k,UUID.randomUUID().toString());b.addProperty("expected_dimension","minecraft:overworld");b.addProperty("weapon_slot",0);b.addProperty("use_shield",true);b.addProperty("interrupt_actions",true);JsonArray types=new JsonArray();for(String t:ReactiveDefensePolicy.TYPES)types.add(t);b.add("target_types",types);b.addProperty("episode_timeout_ms",60000);b.addProperty("quiet_ticks",30);b.addProperty("low_health",6);return b;}
 public static void main(String[] args)throws Exception {
  JsonObject b=arm();var config=NativeReactiveGuard.config(b);yes(config.types().size()==12);yes(config.interrupt());yes(config.weaponSlot()==0);
  for(String type:ReactiveDefensePolicy.TYPES){JsonObject q=b.deepCopy();JsonArray a=new JsonArray();a.add(type);q.add("target_types",a);yes(NativeReactiveGuard.config(q).types().contains(type));}
  for(String type:List.of("minecraft:ender_man","minecraft:enderman","minecraft:creeper","minecraft:player","minecraft:wither","skeleton")){JsonObject q=b.deepCopy();JsonArray a=new JsonArray();a.add(type);q.add("target_types",a);denied(()->NativeReactiveGuard.config(q));}
  JsonObject q=b.deepCopy();q.addProperty("unapproved",true);denied(()->NativeReactiveGuard.config(q));
  for(int n:new int[]{-1,9}){JsonObject c=b.deepCopy();c.addProperty("weapon_slot",n);denied(()->NativeReactiveGuard.config(c));}
  for(int n:new int[]{0,999,120001}){JsonObject c=b.deepCopy();c.addProperty("episode_timeout_ms",n);denied(()->NativeReactiveGuard.config(c));}
  for(int n:new int[]{0,9,101}){JsonObject c=b.deepCopy();c.addProperty("quiet_ticks",n);denied(()->NativeReactiveGuard.config(c));}
  for(double n:new double[]{0,20,Double.NaN}){JsonObject c=b.deepCopy();c.addProperty("low_health",n);denied(()->NativeReactiveGuard.config(c));}
  JsonObject child=new JsonObject();child.addProperty("action_id",UUID.randomUUID().toString());child.addProperty("action","reactive_defense");child.addProperty("timeout_ms",60000);child.addProperty("defense_arm_id",b.get("arm_id").getAsString());var request=ClientActionRequest.parse(child);yes(request.action().equals("reactive_defense"));denied(()->NativeReactiveGuard.requireStart(request));
  JsonObject proof=new NativeAdmission(child,false,ClientActions.session()).proof("test");proof.addProperty("ordinary_start_entered",true);yes(NativeReactiveGuard.preInput(proof,request));
  for(String key:List.of("input_transfer_entered","registration_entered","reentry_observed")){JsonObject p=proof.deepCopy();p.addProperty(key,true);yes(!NativeReactiveGuard.preInput(p,request));}
  JsonObject sessionWrong=proof.deepCopy();sessionWrong.addProperty("action_session","other");yes(!NativeReactiveGuard.preInput(sessionWrong,request));
  JsonObject wrong=proof.deepCopy();wrong.addProperty("request_payload_sha256","wrong");yes(!NativeReactiveGuard.preInput(wrong,request));
  for(JsonElement bad:List.of(JsonNull.INSTANCE,new JsonPrimitive("false"),new JsonPrimitive(0))){JsonObject p=proof.deepCopy();p.add("registration_entered",bad);yes(!NativeReactiveGuard.preInput(p,request));}
  yes(!NativeReactiveGuard.preInput(null,request));
  JsonObject unknown=new JsonObject();unknown.addProperty("unknown_outcome",true);unknown.addProperty("requires_handoff",true);yes(ClientActions.reactiveReleaseEvidence(unknown));yes(unknown.get("unknown_outcome").getAsBoolean());
  unknown.addProperty("input_release_confirmed",false);yes(!ClientActions.reactiveReleaseEvidence(unknown));unknown.addProperty("input_release_confirmed",true);yes(ClientActions.reactiveReleaseEvidence(unknown));unknown.add("input_release_diagnostics",new JsonObject());yes(!ClientActions.reactiveReleaseEvidence(unknown));
  var fence=new ReactiveDefensePolicy.DirectFence();yes(!fence.blocks());
  int[] effects={0};try{fence.call(()->{effects[0]++;yes(fence.blocks());throw new RuntimeException("after_dispatch");},()->true);throw new AssertionError();}catch(RuntimeException expected){yes(fence.blocks());}yes(effects[0]==1);
  fence.call(()->{yes(fence.blocks());return 1;},()->false);yes(fence.blocks());
  fence.call(()->2,()->true);yes(fence.blocks()); // A later call cannot erase thrown dispatch uncertainty.
  var reentry=new ReactiveDefensePolicy.DirectFence();
  reentry.call(()->{try{reentry.call(()->0,()->true);}catch(IllegalStateException swallowed){}return 3;},()->true);yes(reentry.blocks());
  reentry.call(()->4,()->true);yes(reentry.blocks()); // Swallowed reentry remains uncertain.
  yes(!ReactiveDefensePolicy.needsLocalPlan(true,false)); // Repeated timer ticks/cell crossings retain the uncompleted next center.
  yes(ReactiveDefensePolicy.needsLocalPlan(false,false));
  yes(ReactiveDefensePolicy.needsLocalPlan(true,true));
  yes(ReactiveDefensePolicy.needsLocalPlan(false,true));
  var stalled=new ReactiveDefensePolicy.Stalled(0,64,0,0,70,7,20,true,true);
  yes(stalled.unchanged(0,64,0,0,70,7,20,true,true,false));
  yes(!stalled.unchanged(0,64,0,0,70,7,20,true,true,true));
  yes(!stalled.unchanged(0,64,0,0,70,7,19,true,true,false));
  yes(!stalled.unchanged(2,64,0,0,70,7,20,true,true,false));
  yes(!stalled.unchanged(0,64,0,0,69,7,20,true,true,false));
  yes(!stalled.unchanged(0,64,0,0,70,7,20,true,false,false));
  System.out.println("ReactiveDefenseChecks: "+checks+" passed (actual parser/config/receipt predicates; no live game)");
 }
}
