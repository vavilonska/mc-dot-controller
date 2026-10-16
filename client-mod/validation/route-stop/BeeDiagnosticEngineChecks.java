package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.animal.Bee;
/** Original producer/policy/HTTP serializer with explicit synthetic client/server values. No world or AI execution. */
public final class BeeDiagnosticEngineChecks {
 static int assertions;static JsonArray cases=new JsonArray();static Path out;
 static final String WORLD="00000000-0000-4000-8000-000000000001";
 static void ok(boolean value,String message){assertions++;if(!value)throw new AssertionError(message);}
 static Minecraft env(){var m=BeeRouteEngineChecks.env();WorldGeneration.value=WORLD;return m;}
 static ScopedLocalSegmentPolicy.Bounds route(){return ScopedLocalSegmentPolicy.route(.5,1,.5,List.of(new ScopedLocalSegmentPolicy.Point(1.5,1,.5)));}
 static void publish(Minecraft m,NativeLivingSnapshot.Row row,boolean complete,int inspected,String reason,String dimension){NativeLivingObservation.STORE.publish(new NativeLivingSnapshot.Batch(NativeLivingObservation.context,m.level,dimension,row==null?Map.of():Map.of(row.uuid(),row),complete,inspected,reason));}
 static JsonObject reject(String name,Minecraft m,String expected,String nativeReason,String routeStatus)throws Exception{
  var e=BeeRouteEngineChecks.refused(()->ScopedRouteStopEntities.capture(m,route(),0,true));
  ok(e.httpStatus==409&&e.getMessage().equals(expected),name+" refusal unchanged");
  JsonObject diagnostic=e.routeEntityRejection;ok(diagnostic.get("schema_version").getAsInt()==2,name+" new schema");
  JsonObject d=diagnostic.getAsJsonObject("native_bee_diagnostic");
  ok(d.keySet().equals(Set.of("schema_version","entity","native","route","source","context")),name+" exact root");
  ok(d.getAsJsonObject("native").get("reason").getAsString().equals(nativeReason),name+" reason");
  ok(d.getAsJsonObject("route").get("read_status").getAsString().equals(routeStatus),name+" read status");
  ok(d.getAsJsonObject("context").get("world_generation").getAsString().equals(WORLD),name+" context");
  String bytes=BridgeJson.toJson(e.response());JsonObject parsed=JsonParser.parseString(bytes).getAsJsonObject();
  ok(parsed.equals(e.response()),name+" original HTTP serializer retains every null");
  ok(bytes.length()<8192,name+" bounded");ok(ClientActions.active==null,name+" no effect ownership");
  Files.writeString(out.resolve("bee-diagnostics/bee-diagnostic-"+name+".json"),bytes,StandardOpenOption.CREATE_NEW);cases.add(name);return d;
 }
 static class UnknownPosition extends BlockPos {UnknownPosition(){super(1,2,3);}public int getX(){throw new AssertionError("unknown position getter invoked");}}
 static class UnknownMutable extends BlockPos.MutableBlockPos {UnknownMutable(){super(1,2,3);}public int getX(){throw new AssertionError("unknown mutable getter invoked");}}
 public static void main(String[]args)throws Exception{out=Path.of(args[0]);Files.createDirectory(out.resolve("bee-diagnostics"));
  for(String reason:List.of("inspection_limit","row_limit","duplicate_entity_uuid","native_read_failed")){
   var m=env();var c=BeeRouteEngineChecks.bee(m);var s=BeeRouteEngineChecks.server(c);var row=NativeLivingObservation.read(s,m.level.time,System.nanoTime());
   publish(m,row,false,reason.equals("inspection_limit")?4097:257,reason,m.level.dimension);
   var d=reject(reason,m,"route_bee_native_unconfirmed",reason,"observed");ok(!d.getAsJsonObject("native").get("coverage_complete").getAsBoolean(),"partial stays false");
   ok(!d.getAsJsonObject("native").get("known").getAsBoolean()&&d.getAsJsonObject("route").get("captured").getAsBoolean()&&!d.getAsJsonObject("route").get("present").getAsBoolean(),"captured route not authority");
  }
  for(String kind:List.of("context_unavailable","dimension_changed","entity_not_observed","entity_identity_changed","source_expired","source_future","source_tick_mismatch","invalid_anger_time","route_extension_missing")){
   var m=env();var c=BeeRouteEngineChecks.bee(m);var s=BeeRouteEngineChecks.server(c);long tick=m.level.time,nano=System.nanoTime();
   if(kind.equals("entity_identity_changed"))s.id++;if(kind.equals("source_expired"))nano-=251_000_000L;if(kind.equals("source_future"))nano+=1_000_000_000L;if(kind.equals("source_tick_mismatch"))tick-=6;if(kind.equals("invalid_anger_time"))s.anger=-1;
   var row=NativeLivingObservation.read(s,tick,nano);
   if(kind.equals("route_extension_missing"))row=new NativeLivingSnapshot.Row(row.uuid(),row.entityId(),row.type(),row.tick(),row.nano(),row.alive(),row.aggressive(),row.target(),row.bee(),row.rabbit(),null);
   if(!kind.equals("context_unavailable"))publish(m,kind.equals("entity_not_observed")?null:row,true,2,"observed",kind.equals("dimension_changed")?"minecraft:the_nether":m.level.dimension);
   String reason=kind.equals("source_future")?"source_expired":kind.equals("route_extension_missing")?"observed":kind;
   String status=kind.equals("context_unavailable")||kind.equals("entity_not_observed")?"row_unavailable":kind.equals("route_extension_missing")?"not_recorded":"observed";
   var d=reject(kind,m,"route_bee_native_unconfirmed",reason,status);
   if(kind.equals("source_expired")||kind.equals("source_future")||kind.equals("source_tick_mismatch")){
    ok(d.getAsJsonObject("native").get("source_nano").getAsString().equals(Long.toString(row.nano())),"exact unavailable row clock retained");
    ok(d.getAsJsonObject("native").get("sample_nano").isJsonNull(),"never invent unavailable original sample clock");
   }
  }
  for(int kind=0;kind<4;kind++){
   var m=env();var c=BeeRouteEngineChecks.bee(m);var s=BeeRouteEngineChecks.server(c);
   if(kind==0||kind==2)s.hive=new UnknownPosition();if(kind==1||kind==2)s.flower=new UnknownPosition();if(kind==3)s.flower=new UnknownMutable();
   BeeRouteEngineChecks.publish(m,s);String status=kind==0?"hive_position_class_untrusted":kind==2?"positions_class_untrusted":"flower_position_class_untrusted";
   reject("unknown_position_"+kind,m,"route_bee_native_unconfirmed","observed",status);
  }
  // The pinned vanilla pollination bytecode returns its exact MutableBlockPos without immutable().
  // Reproduce that stored-reference shape through the unchanged production owning-thread row reader.
  var m=env();var c=BeeRouteEngineChecks.bee(m);var s=BeeRouteEngineChecks.server(c);
  var flower=new BlockPos.MutableBlockPos(4,5,6);var hive=new BlockPos.MutableBlockPos(1,2,3);s.flower=flower;s.hive=hive;
  var sampled=NativeLivingObservation.read(s,m.level.time,System.nanoTime());ok(sampled.beeRoute()!=null&&sampled.beeRouteReadStatus().equals("observed"),"exact vanilla mutable accepted");
  flower.set(40,50,60);hive.set(10,20,30);ok(sampled.beeRoute().flower().equals(new NativeLivingSnapshot.BeePosition(4,5,6))&&sampled.beeRoute().hive().equals(new NativeLivingSnapshot.BeePosition(1,2,3)),"coordinates immutable after sampling");
  publish(m,sampled,true,2,"observed",m.level.dimension);var captured=ScopedRouteStopEntities.capture(m,route(),0,true);captured.finalFence();ok(captured.entries.size()==1,"pollination-shaped immutable evidence admitted");cases.add("exact_mutable_position_copied_and_accepted");
  var entity=captured.entries.get(0).row();var original=entity.nativeLiving();
  original.addProperty("inspected",1.0);original.addProperty("reason","secret arbitrary diagnostic text");original.addProperty("sample_nano","-0");
  var sanitized=RouteBeeDiagnostics.json(entity,captured.serverFrame,captured.beeContext);
  ok(sanitized.getAsJsonObject("native").get("inspected").isJsonNull(),"noncanonical integer is unavailable");
  ok(sanitized.getAsJsonObject("native").get("sample_nano").isJsonNull(),"noncanonical nano is unavailable");
  ok(sanitized.getAsJsonObject("native").get("reason").getAsString().equals("unrecognized")&&!sanitized.toString().contains("secret"),"closed reason no arbitrary strings");
  // Legacy unknown types remain byte-for-byte unchanged; arbitrary exception text is never exposed.
  RouteEntityDiagnostics old=new RouteEntityDiagnostics();old.trustedType("minecraft:bat");old.phase(RouteEntityDiagnostics.Phase.POLICY);
  String legacy=BridgeJson.toJson(old.rejection(new ClientActionRequest.Rejected(409,"route_stop_far_context_conflict")).response());
  ok(legacy.equals("{\"ok\":false,\"error\":\"route_stop_far_context_conflict\",\"route_entity_rejection\":{\"schema_version\":1,\"profile\":\"movement-local-segment-spatial-stop-v1\",\"policy\":\"route-spatial-stop-v1\",\"phase\":\"policy\",\"entity_type\":\"minecraft:bat\",\"exception_type\":\"rejected\",\"rejection_code\":\"route_stop_far_context_conflict\"}}"),"legacy schema1 bytes unchanged");
  JsonObject report=new JsonObject();report.addProperty("assertions",assertions);report.add("cases",cases);report.addProperty("scope","Production snapshot row reader, route capture/policy, diagnostic and HTTP serializer; synthetic engine values; no AI or game runtime");Files.writeString(out.resolve("diagnostic-result.json"),report.toString(),StandardOpenOption.CREATE_NEW);System.out.println("PASS bee diagnostic assertions="+assertions);
 }
}
