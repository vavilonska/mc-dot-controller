package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.List;
import static io.github.campione01.mineclientbridge.WireV1Fixture.*;
/** Actual native serializers over controller-generated synthetic-engine footprint and terminal. No live claim. */
public final class LocalSegmentWireProducer {
 static JsonObject read(Path p)throws Exception{return JsonParser.parseString(Files.readString(p)).getAsJsonObject();}
 static void write(Path p,JsonObject j)throws Exception{Files.writeString(p,BridgeJson.toJson(j),StandardOpenOption.CREATE_NEW);}
 static JsonObject bundle(JsonObject action,JsonObject meta,long tick,long nano){
  Object level=new Object(),playerId=new Object(),mode=new Object(),menuId=new Object();
  String world=meta.get("world_generation").getAsString(),uuid=meta.get("player_uuid").getAsString(),session=meta.get("action_session").getAsString();
  var context=new CapabilitySnapshot.Context(level,playerId,mode,null,menuId,world,uuid,"minecraft:overworld",session,tick);
  JsonObject worldJson=new JsonObject();worldJson.addProperty("present",true);worldJson.addProperty("world_generation",world);worldJson.addProperty("dimension","minecraft:overworld");worldJson.addProperty("game_time",tick);
  JsonObject player=point(.5,1,.5);player.addProperty("present",true);player.addProperty("uuid",uuid);player.addProperty("alive",true);player.addProperty("health",20);player.addProperty("dimension","minecraft:overworld");player.addProperty("yaw",0);player.addProperty("pitch",0);
  JsonObject status=protocol(new JsonObject());status.addProperty("in_world",true);status.addProperty("run_id","synthetic-action-tick");status.addProperty("process_id",1);status.add("world",worldJson.deepCopy());status.add("player",player.deepCopy());status.add("client_action",action.deepCopy());JsonObject screenState=new JsonObject();screenState.addProperty("present",false);status.add("screen",screenState);
  JsonObject state=protocol(new JsonObject());state.add("world",worldJson.deepCopy());state.add("player",player.deepCopy());state.add("client_action",action.deepCopy());state.add("movement_budget",action.get("movement_budget").deepCopy());state.add("capability_guard",guard(tick,nano));state.add("menu",menu());state.addProperty("screen_open",false);state.addProperty("paused",false);state.addProperty("focused",true);state.addProperty("private_singleplayer",true);JsonObject held=new JsonObject();held.addProperty("neutral",true);state.add("held_inputs",held);JsonObject nearby=new JsonObject();nearby.addProperty("radius",8);nearby.addProperty("returned",0);nearby.addProperty("total",0);nearby.addProperty("truncated",false);nearby.add("entities",new JsonArray());state.add("nearby",nearby);
  JsonObject screen=protocol(new JsonObject());screen.addProperty("open",false);screen.add("menu",menu());return CapabilitySnapshot.assemble(context,context,status,action,state,screen,action);
 }

 public static void main(String[] args)throws Exception{
  Path source=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectory(out);
  JsonObject meta=read(source.resolve("actual-metadata.json")),terminal=read(source.resolve("actual-terminal.json")),footprint=read(source.resolve("actual-footprint.json"));
  int goalY=footprint.get("end_y").getAsInt();
  String id="synthetic-segment",session=meta.get("action_session").getAsString();long tick=meta.get("source_tick").getAsLong(),nano=Long.parseLong(meta.get("source_nano").getAsString());
  JsonObject intent=intent();intent.addProperty("action_id",id);for(String k:List.of("world_generation","player_uuid","action_session"))intent.addProperty("expected_"+k,meta.get(k).getAsString());
  intent.add("expected_origin",point(.5,1,.5));JsonArray route=new JsonArray();JsonObject point=point(1.5,goalY,.5);point.addProperty("jump",false);route.add(point);intent.add("waypoints",route);intent.add("capability_guard",guard(tick-1,nano-100_000_000));intent.addProperty("expected_hotbar_slot",0);intent.add("expected_held_item",emptyStack());intent.addProperty("min_health",12);
  JsonObject scope=request();scope.addProperty("profile",ScopedLocalSegmentMovement.PROFILE);scope.addProperty("job_id","synthetic_local_segment");
  JsonObject compiled=intent.deepCopy();compiled.add("capability_guard",guard(tick,nano));
  JsonObject facts=facts(entities());for(String k:List.of("world_generation","player_uuid","action_session","integrated_server_instance"))facts.getAsJsonObject("context").addProperty(k,meta.get(k).getAsString());facts.addProperty("x",.5);facts.addProperty("y",1);facts.addProperty("z",.5);facts.remove("movement");facts.add("local_segment",footprint);
  JsonObject witness=ScopedNativePreflight.serializeWitness(scope,id,session,0,meta.get("integrated_server_instance").getAsString(),ScopedNativePreflight.digest(intent),ScopedNativePreflight.digest(compiled),tick,nano,Long.parseLong(meta.get("admitted_nano").getAsString()),facts,intent.getAsJsonObject("capability_guard"));
  ClientActionRequest nativeRequest=new ClientActionRequest(id,"follow_path",8000,List.of(new ClientActionRequest.Point(1.5,goalY,.5,false)),null,null,null,-1,false,false,-1,-1,0,null,compiled);ActionRegistry.Entry entry=new ActionRegistry.Entry(nativeRequest);entry.status=meta.get("native_status").getAsString().equals("running")?"succeeded":meta.get("native_status").getAsString();entry.reason=entry.status.equals("succeeded")?"path_reached":meta.get("native_reason").getAsString();for(var extra:read(source.resolve("actual-result.json")).entrySet())entry.result.add(extra.getKey(),extra.getValue().deepCopy());entry.ticks=terminal.get("last_entity_check_action_tick").getAsInt();entry.result.add("scoped_native_preflight",witness);entry.result.add("local_segment",terminal);entry.result.addProperty("input_release_confirmed",true);entry.result.addProperty("world_generation",meta.get("world_generation").getAsString());
  JsonObject action=entry.json(false);action.addProperty("action_session",session);JsonObject budget=new JsonObject();budget.addProperty("schema_version",1);budget.addProperty("status","unarmed");budget.addProperty("position_hook_seen",false);budget.addProperty("move_hook_seen",false);action.add("movement_budget",budget);
  JsonObject standalone=actionEndpoint(action,false),coherent=bundle(action,meta,meta.get("last_world_tick").getAsLong(),nano+1_000_000);
  int one=BridgeJson.toJson(standalone).getBytes(java.nio.charset.StandardCharsets.UTF_8).length,all=BridgeJson.toJson(coherent).getBytes(java.nio.charset.StandardCharsets.UTF_8).length;ScopedEntityPolicy.requireResponseSizes(one,all,262144);
  write(out.resolve("generated-standalone.json"),standalone);write(out.resolve("generated-coherent.json"),coherent);write(out.resolve("generated-intent.json"),intent);write(out.resolve("generated-request.json"),scope);write(out.resolve("generated-size-diagnostic.json"),ScopedMovementWire.sizeDiagnostic(action,262144,262144,262144));
  JsonObject report=new JsonObject();report.addProperty("standalone_bytes",one);report.addProperty("coherent_bytes",all);report.addProperty("scope","Fresh complete production witness/digest/Entry/HTTP/CapabilitySnapshot/BridgeJson serializers; footprint and terminal from actual candidate controller under explicit synthetic readers");write(out.resolve("wire-result.json"),report);System.out.println("PASS production native wire sizes "+one+"/"+all);
 }
}
