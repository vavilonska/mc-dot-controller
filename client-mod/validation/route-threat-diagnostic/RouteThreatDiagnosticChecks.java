package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Exercises production snapshot -> policy -> rejected response -> actual HTTP JSON encoding. */
public final class RouteThreatDiagnosticChecks {
 static final String PLAYER="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",WORLD="11111111-2222-4333-8444-555555555555";
 static final String UUID="44444444-4444-4444-8444-444444444444",OTHER="55555555-5555-4555-8555-555555555555",DIM="minecraft:overworld";
 static final long TICK=100,NANO=1_000_000_000L;static final int ID=9;static int count;
 static final Object CONTEXT=new Object(),LEVEL=new Object();
 static void check(boolean ok,String why){count++;if(!ok)throw new AssertionError(why);}
 static NativeLivingSnapshot.Row source(String uuid,int id,long tick,long nano){return new NativeLivingSnapshot.Row(uuid,id,"minecraft:zombie",tick,nano,true,false,new NativeLivingSnapshot.Target(PLAYER,13,"minecraft:player"),null);}
 static NativeLivingSnapshot.Batch batch(NativeLivingSnapshot.Row row,boolean complete,String reason){return new NativeLivingSnapshot.Batch(CONTEXT,LEVEL,DIM,row==null?Map.of():Map.of(UUID,row),complete,50,reason);}
 static ScopedRouteThreatPolicy.Row entity(JsonObject n,String uuid,int id,double x){
  var p=new ScopedEntityPolicy.V(x,192,8.5);var box=new ScopedEntityPolicy.Box(x-.3,192,8.2,x+.3,193.95,8.8);
  return new ScopedRouteThreatPolicy.Row(id,uuid,"minecraft:zombie",ScopedRouteThreatPolicy.ZOMBIE_CLASS,false,p,box,new ScopedEntityPolicy.V(0,0,0),p,new ScopedEntityPolicy.Flags(true,true,false,false,false,false,false,false,0,0,null),box,n);
 }
 static JsonObject json(NativeLivingSnapshot.Batch b,Object context,String uuid,int id,long tick,long nano){return NativeLivingSnapshot.json(b,context,DIM,WORLD,PLAYER,uuid,id,"minecraft:zombie",tick,nano);}
 static RouteThreatDiagnostics.FailedRow rejected(ScopedRouteThreatPolicy.Row row,long tick,long nano,String expected){
  try{ScopedRouteThreatPolicy.active(row,tick,nano,PLAYER,WORLD,DIM);throw new AssertionError("admitted "+expected);}
  catch(RouteThreatDiagnostics.FailedRow failed){check(expected.equals(failed.getMessage()),"original reason");check(failed.row==row,"exact failed row");return failed;}
 }
 static JsonObject response(RouteThreatDiagnostics.FailedRow failed,NativeLivingSnapshot.Batch b,Object context,String phase)throws Exception{
  var rejected=RouteThreatDiagnostics.rejection(failed,b,context,UUID,phase);
  check(rejected.httpStatus==409,"status retained");check(rejected.getMessage().equals(failed.getMessage()),"reason retained");
  JsonObject body=rejected.response();String wire=BridgeJson.toJson(body);JsonObject decoded=JsonParser.parseString(wire).getAsJsonObject();
  check(decoded.equals(body),"actual BridgeJson retains explicit nulls exactly");
  JsonObject d=decoded.getAsJsonObject("route_threat_rejection");check(d!=null,"diagnostic present");
  check(d.toString().getBytes(StandardCharsets.UTF_8).length<=4096,"bounded");
  check(d.getAsJsonObject("context").get("final_check_nano").isJsonNull()==!phase.equals("final_fence"),"final check only fence");
  // The outgoing exception and each response are detached from later consumer mutation.
  body.getAsJsonObject("route_threat_rejection").getAsJsonObject("entity").addProperty("id",1234);
  check(rejected.response().equals(decoded),"response detached");
  return decoded;
 }
 public static void main(String[] args)throws Exception{
  Path out=Path.of(args[0]);Files.createDirectories(out);var cases=new JsonArray();
  var good=batch(source(UUID,ID,TICK,NANO),true,"observed");
  JsonObject fresh=json(good,CONTEXT,UUID,ID,TICK,NANO+1);
  check(ScopedRouteThreatPolicy.active(entity(fresh,UUID,ID,-277.5),TICK,NANO,PLAYER,WORLD,DIM),"fresh remains active");
  JsonObject exactAge=json(good,CONTEXT,UUID,ID,TICK,NANO+250_000_000L);
  check(ScopedRouteThreatPolicy.active(entity(exactAge,UUID,ID,-277.5),TICK,NANO+250_000_000L,PLAYER,WORLD,DIM),"250ms boundary unchanged");
  JsonObject exactSkew=json(good,CONTEXT,UUID,ID,TICK+5,NANO+1);
  check(ScopedRouteThreatPolicy.active(entity(exactSkew,UUID,ID,-277.5),TICK+5,NANO,PLAYER,WORLD,DIM),"5tick boundary unchanged");
  for(String cause:List.of("source_expired","source_tick_mismatch","entity_not_observed","native_read_failed","context_unavailable","entity_identity_changed","inspection_limit","row_limit","dimension_changed")){
   var b=good;Object context=CONTEXT;long tick=TICK,nano=NANO+1;
   if(cause.equals("source_expired"))nano=NANO+250_000_001L;
   if(cause.equals("source_tick_mismatch"))tick=TICK+6;
   if(cause.equals("entity_not_observed"))b=batch(null,true,"observed");
   if(Set.of("native_read_failed","inspection_limit","row_limit").contains(cause))b=batch(source(UUID,ID,TICK,NANO),false,cause);
   if(cause.equals("context_unavailable"))context=null;
   if(cause.equals("entity_identity_changed"))b=batch(source(UUID,ID+1,TICK,NANO),true,"observed");
   if(cause.equals("dimension_changed"))b=new NativeLivingSnapshot.Batch(CONTEXT,LEVEL,"minecraft:the_nether",good.rows(),true,50,"observed");
   JsonObject n=json(b,context,UUID,ID,tick,nano);check(cause.equals(n.get("reason").getAsString()),"actual producer cause");
   var failed=rejected(entity(n,UUID,ID,-277.5),tick,nano,"route_spatial_native_target_unconfirmed");
   for(String phase:List.of("capture","recheck")){
    JsonObject body=response(failed,b,CONTEXT,phase),d=body.getAsJsonObject("route_threat_rejection");
    check(cause.equals(d.getAsJsonObject("native").get("reason").getAsString()),"source reason preserved");
    check(d.getAsJsonObject("native").get("sample_nano").isJsonNull(),"unknown omitted original sample remains null");
    check(d.getAsJsonObject("native").get("source_nano").isJsonNull(),"unknown source not relabeled from captured row");
    check(d.getAsJsonObject("source").get("row_present").getAsBoolean()==!cause.equals("entity_not_observed"),"captured source availability");
    Files.writeString(out.resolve(cause+"-"+phase+".json"),BridgeJson.toJson(body));
   }
   JsonObject c=new JsonObject();c.addProperty("cause",cause);c.addProperty("verdict",failed.getMessage());cases.add(c);
  }
  // Actual Frame chooses the failed nonselected row, not the most recently successful selected one.
  JsonObject unknown=json(good,CONTEXT,OTHER,ID+1,TICK,NANO+1);
  try{new ScopedRouteThreatPolicy.Frame(TICK,NANO,0,1,new ScopedEntityPolicy.Box(-282,190,7,-277,195,10),new ScopedEntityPolicy.Box(-281,192,8,-279,194,9),new ScopedEntityPolicy.V(-279.5,192,8.5),PLAYER,WORLD,DIM,UUID,List.of(entity(fresh,UUID,ID,-277.5),entity(unknown,OTHER,ID+1,100)),true);throw new AssertionError("other unknown accepted");}
  catch(RouteThreatDiagnostics.FailedRow failed){
   var body=response(failed,good,CONTEXT,"capture");var e=body.getAsJsonObject("route_threat_rejection").getAsJsonObject("entity");
   check(e.get("uuid").getAsString().equals(OTHER)&&!e.get("selected").getAsBoolean(),"exact nonselected attribution");
   Files.writeString(out.resolve("other-row-capture.json"),BridgeJson.toJson(body));
  }
  for(String reason:List.of("route_spatial_native_target_unconfirmed","route_spatial_native_target_stale","route_spatial_clock_invalid","route_spatial_targetless_aggression_unknown","route_spatial_target_unknown","route_spatial_other_target_unknown")){
   JsonObject n=fresh.deepCopy();
   switch(reason){
    case "route_spatial_native_target_unconfirmed" -> n.addProperty("alive",false);
    case "route_spatial_native_target_stale" -> n.addProperty("sample_tick",TICK+1);
    case "route_spatial_clock_invalid" -> n.addProperty("sample_nano","not-a-clock");
    case "route_spatial_targetless_aggression_unknown" -> {n.add("current_target",JsonNull.INSTANCE);n.addProperty("aggressive",true);}
    case "route_spatial_target_unknown" -> n.addProperty("current_target",false);
    case "route_spatial_other_target_unknown" -> n.getAsJsonObject("current_target").addProperty("uuid",OTHER);
   }
   var failed=rejected(entity(n,UUID,ID,-277.5),TICK,NANO,reason);response(failed,good,CONTEXT,"capture");
  }
  JsonObject calm=fresh.deepCopy();calm.add("current_target",JsonNull.INSTANCE);
  check(!ScopedRouteThreatPolicy.active(entity(calm,UUID,ID,-277.5),TICK,NANO,PLAYER,WORLD,DIM),"known targetless remains inactive");
  long exactFinalCheck=NANO+250_000_001L;
  var fence=new RouteThreatDiagnostics.FailedRow(new IllegalArgumentException("route_spatial_native_target_stale"),entity(fresh,UUID,ID,-277.5),TICK,NANO,PLAYER,WORLD,DIM,exactFinalCheck);
  var fenceBody=response(fence,good,CONTEXT,"final_fence");
  check(fenceBody.getAsJsonObject("route_threat_rejection").getAsJsonObject("context").get("final_check_nano").getAsString().equals(Long.toString(exactFinalCheck)),"existing failed fence clock retained exactly");
  Files.writeString(out.resolve("final-fence.json"),BridgeJson.toJson(fenceBody));
  check(RouteThreatDiagnostics.json(fence,good,CONTEXT,UUID,"capture")==null,"mislabeled fence discarded");
  check(RouteThreatDiagnostics.json(fence,good,CONTEXT,"invalid","final_fence")==null,"invalid context discarded");
  var original=new RouteThreatDiagnostics.FailedRow(new IllegalArgumentException("route_spatial_native_target_unconfirmed"),entity(unknown,OTHER,ID+1,100),TICK,NANO,PLAYER,WORLD,DIM);
  var noDetail=RouteThreatDiagnostics.rejection(original,good,CONTEXT,"invalid","capture");
  check(noDetail.httpStatus==409&&noDetail.getMessage().equals(original.getMessage())&&!noDetail.response().has("route_threat_rejection"),"failed diagnostic retains original refusal");
  JsonObject evil=unknown.deepCopy();evil.addProperty("reason","private text "+"x".repeat(10000));
  var bounded=rejected(entity(evil,OTHER,ID+1,100),TICK,NANO,"route_spatial_native_target_unconfirmed");
  var safe=response(bounded,batch(source(UUID,ID,TICK,NANO),false,"private text"),CONTEXT,"capture");
  check(safe.getAsJsonObject("route_threat_rejection").getAsJsonObject("native").get("reason").getAsString().equals("unrecognized"),"unallowlisted source text redacted");
  check(!BridgeJson.toJson(safe).contains("private text"),"no raw error text");
  JsonObject unrelated=new JsonObject();JsonObject nullChild=new JsonObject();nullChild.add("missing",JsonNull.INSTANCE);unrelated.add("unrelated",nullChild);
  check(BridgeJson.toJson(unrelated).equals("{\"unrelated\":{}}"),"unrelated null omission unchanged");
  JsonObject result=new JsonObject();result.addProperty("status","passed");result.addProperty("assertions",count);result.add("producer_cases",cases);result.addProperty("wire_encoding","production BridgeJson.toJson(ClientActionRequest.Rejected.response())");
  Files.writeString(out.resolve("RESULT.json"),new GsonBuilder().setPrettyPrinting().create().toJson(result));System.out.println(result);
 }
}
