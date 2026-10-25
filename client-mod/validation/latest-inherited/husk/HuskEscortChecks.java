package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.util.*;
public final class HuskEscortChecks {
 static int checks;
 static void check(boolean b,String s){checks++;if(!b)throw new AssertionError(s);}
 static void reject(JsonElement types){checks++;var q=BlazeEscortChecks.request();q.getAsJsonObject("blaze_guard").add("target_types",types);try{ClientActionRequest.parse(q);throw new AssertionError("accepted "+types);}catch(ClientActionRequest.Rejected expected){}}
 public static void main(String[] args){
  var q=BlazeEscortChecks.request();
  check(NativeBlazeEscort.validate(ClientActionRequest.parse(q)).targetTypes().equals(Set.of("minecraft:blaze")),"default remains exact Blaze");
  q.getAsJsonObject("blaze_guard").add("target_types",JsonParser.parseString("[\"minecraft:husk\"]"));
  check(NativeBlazeEscort.validate(ClientActionRequest.parse(q)).targetTypes().equals(Set.of("minecraft:husk")),"true Husk opt-in");
  for(boolean shield:new boolean[]{false,true}){
   q.getAsJsonObject("blaze_guard").addProperty("shield",shield);
   var c=NativeBlazeEscort.validate(ClientActionRequest.parse(q));
   check(c.shield()==shield&&c.stopHealth()==6&&c.maximumDamage()==20,"no-shield and shield retain original damage budget");
  }
  q.getAsJsonObject("blaze_guard").add("target_types",JsonParser.parseString("[\"minecraft:blaze\",\"minecraft:zombie\",\"minecraft:drowned\",\"minecraft:husk\"]"));
  check(NativeBlazeEscort.validate(ClientActionRequest.parse(q)).targetTypes().equals(NativeBlazeEscort.SUPPORTED_TARGET_TYPES),"four exact supported types");
  for(String bad:List.of("[]","[\"husk\"]","[\"minecraft:Husk\"]","[\"minecraft:husk\",\"minecraft:husk\"]","[\"minecraft:skeleton\"]","[\"minecraft:zombie_villager\"]","[\"minecraft:blaze\",\"minecraft:zombie\",\"minecraft:drowned\",\"minecraft:husk\",\"minecraft:skeleton\"]"))reject(JsonParser.parseString(bad));
  check(BoundedCombatRequest.REQUEST_TYPES.contains("minecraft:husk") && !BoundedCombatRequest.REQUEST_TYPES.contains("minecraft:drowned"),"existing generic Husk support unchanged; only escort opt-in added");
  var h=new BlazeEscortPolicy.Contact("husk-one",123,"minecraft:husk",2,true,true,true);
  var p=BlazeEscortChecks.policy();p.acquire(h,0);
  check(p.targetType.equals("minecraft:husk")&&p.targetUuid.equals("husk-one"),"lock actual Husk identity");
  check(!p.mayAttack(1,false,1,false)&&!p.mayAttack(1,true,.94,false)&&!p.mayAttack(1,true,1,true),"ray cooldown shield gates unchanged");
  check(p.mayAttack(1,true,.95,false),"real ready attack allowed");p.attackAttempt(1);
  check(!p.mayAttack(1,true,1,false),"at most one attempt per tick");
  Object ctx=new Object(),level=new Object();long n=5000000000L;
  var row=new NativeLivingSnapshot.Row("husk-one",123,"minecraft:husk",500,n,false,false,null,null);
  var batch=new NativeLivingSnapshot.Batch(ctx,level,"minecraft:overworld",Map.of("husk-one",row),true,1,"observed");
  var proof=NativeBlazeEscort.serverDeathEvidence(batch,ctx,"minecraft:overworld","generation","player","husk-one",123,"minecraft:husk",500,n+10);
  check(proof!=null&&!proof.get("alive").getAsBoolean()&&proof.get("entity_type").getAsString().equals("minecraft:husk"),"fresh server death real Husk not Zombie alias");
  check(NativeBlazeEscort.serverDeathEvidence(batch,ctx,"minecraft:overworld","generation","player","husk-one",123,"minecraft:zombie",500,n+10)==null,"same UUID wrong true type rejected");
  check(NativeBlazeEscort.serverDeathEvidence(batch,ctx,"minecraft:overworld","generation","player","missing",123,"minecraft:husk",500,n+10)==null,"missing not death");
  check(NativeBlazeEscort.serverDeathEvidence(batch,ctx,"minecraft:overworld","generation","player","husk-one",124,"minecraft:husk",500,n+10)==null,"ID mismatch rejected");
  check(NativeBlazeEscort.serverDeathEvidence(batch,new Object(),"minecraft:overworld","generation","player","husk-one",123,"minecraft:husk",500,n+10)==null,"context mismatch rejected");
  check(NativeBlazeEscort.serverDeathEvidence(batch,ctx,"minecraft:overworld","generation","player","husk-one",123,"minecraft:husk",500,n+250000001)==null,"stale death rejected");
  row=new NativeLivingSnapshot.Row("husk-one",123,"minecraft:husk",500,n,true,false,null,null);
  batch=new NativeLivingSnapshot.Batch(ctx,level,"minecraft:overworld",Map.of("husk-one",row),true,1,"observed");
  check(NativeBlazeEscort.serverDeathEvidence(batch,ctx,"minecraft:overworld","generation","player","husk-one",123,"minecraft:husk",500,n+10)==null,"alive not death");
  p.targetDead();check(p.kills==1&&p.phase==BlazeEscortPolicy.Phase.NAVIGATING,"confirmed death resumes route");
  p.acquire(h,2);p.targetDead();check(p.kills==1,"same UUID no double count");
  p.acquire(new BlazeEscortPolicy.Contact("second",124,"minecraft:zombie",2,true,true,true),3);
  check(p.targetUuid.equals("second")&&p.targetType.equals("minecraft:zombie"),"next real UUID normal type permitted");
  p.targetLost();check(p.kills==1&&p.phase==BlazeEscortPolicy.Phase.RETURNING,"lost target returns not fake kill");
  System.out.println("HuskEscortChecks PASS "+checks);
 }
}
