package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.world.entity.monster.Zombie;

/** Production capture/recheck/fence and HTTP encoder with explicitly synthetic engine/server readers. */
public final class RouteThreatDiagnosticEngineChecks {
 static int assertions;
 static void check(boolean ok,String why){assertions++;if(!ok)throw new AssertionError(why);}
 static Minecraft environment(){var mc=SpatialThreatEngineChecks.environment();WorldGeneration.value="11111111-2222-4333-8444-555555555555";return mc;}
 static ScopedLocalSegmentPolicy.Bounds route(Minecraft mc){return ScopedLocalSegmentPolicy.route(mc.player.getX(),mc.player.getY(),mc.player.getZ(),SpatialThreatEngineChecks.request().waypoints().stream().map(p->new ScopedLocalSegmentPolicy.Point(p.x(),p.y(),p.z())).toList());}
 static ScopedRouteThreatEntities capture(Minecraft mc){return ScopedRouteThreatEntities.capture(mc,route(mc),0,SpatialThreatEngineChecks.TARGET,true);}
 static JsonObject refusal(Runnable action,String phase,String sourceReason)throws Exception{
  try{action.run();throw new AssertionError("accepted");}catch(ClientActionRequest.Rejected failed){
   check(failed.httpStatus==409,"409 retained");var body=failed.response();var wire=BridgeJson.toJson(body);
   check(JsonParser.parseString(wire).equals(body),"actual null preserving HTTP encoder");
   var diagnostic=body.getAsJsonObject("route_threat_rejection");check(diagnostic!=null,"capture catch carries diagnostic");
   check(diagnostic.get("phase").getAsString().equals(phase),"actual phase");
   check(diagnostic.getAsJsonObject("native").get("reason").getAsString().equals(sourceReason),"actual captured native reason");
   return body;
  }
 }
 public static void main(String[] args)throws Exception{
  Path out=Path.of(args[0]);Files.createDirectory(out);
  var mc=environment();var z=SpatialThreatEngineChecks.zombie(mc,2);
  SpatialThreatEngineChecks.publish(mc,z,true,300_000_000L,true,mc.player.getUUID().toString());
  final var expiredMc=mc;var body=refusal(()->capture(expiredMc),"capture","source_expired");
  check(body.get("error").getAsString().equals("route_spatial_native_target_unconfirmed"),"same original unconfirmed");
  check(body.getAsJsonObject("route_threat_rejection").getAsJsonObject("entity").get("selected").getAsBoolean(),"selected row bound");
  Files.writeString(out.resolve("capture-expired.json"),BridgeJson.toJson(body));
  mc=environment();z=SpatialThreatEngineChecks.zombie(mc,2);SpatialThreatEngineChecks.publish(mc,z,true);
  var captured=capture(mc);long oldSource=captured.serverFrame.batch().rows().get(SpatialThreatEngineChecks.TARGET).nano();
  Thread.sleep(275);SpatialThreatEngineChecks.publish(mc,z,true);
  long newSource=NativeLivingObservation.capture(mc).batch().rows().get(SpatialThreatEngineChecks.TARGET).nano();
  check(newSource>oldSource,"new publication exists, old witness immutable");
  body=refusal(captured::assertUnchanged,"recheck","source_expired");
  check(body.getAsJsonObject("route_threat_rejection").getAsJsonObject("source").get("row_nano").getAsString().equals(Long.toString(oldSource)),"recheck diagnostic refers to failed original batch");
  Files.writeString(out.resolve("recheck-expired.json"),BridgeJson.toJson(body));
  mc=environment();z=SpatialThreatEngineChecks.zombie(mc,2);SpatialThreatEngineChecks.publish(mc,z,true);captured=capture(mc);
  oldSource=captured.serverFrame.batch().rows().get(SpatialThreatEngineChecks.TARGET).nano();Thread.sleep(275);
  body=refusal(captured::finalFence,"final_fence","observed");
  long finalCheck=Long.parseLong(body.getAsJsonObject("route_threat_rejection").getAsJsonObject("context").get("final_check_nano").getAsString());
  check(finalCheck-oldSource>250_000_000L,"exact existing final check clock proves failed bound");
  check(body.get("error").getAsString().equals("route_spatial_native_target_stale"),"same final stale reason");
  Files.writeString(out.resolve("final-fence-expired.json"),BridgeJson.toJson(body));
  mc=environment();z=SpatialThreatEngineChecks.zombie(mc,2);SpatialThreatEngineChecks.publish(mc,z,true);
  var other=new Zombie();other.id=10;other.uuid=UUID.fromString("55555555-5555-4555-8555-555555555555");other.x=other.tx=100;other.y=other.ty=1;other.z=other.tz=100;mc.level.entities.add(other);
  final var otherMc=mc;body=refusal(()->capture(otherMc),"capture","entity_not_observed");
  var e=body.getAsJsonObject("route_threat_rejection").getAsJsonObject("entity");
  check(!e.get("selected").getAsBoolean()&&e.get("id").getAsInt()==10,"exact other loaded failed row");
  Files.writeString(out.resolve("other-loaded-row.json"),BridgeJson.toJson(body));
  check(ClientActions.active==null&&ClientActions.ACTIONS.active()==null,"all refused before registration/effect");
  JsonObject result=new JsonObject();result.addProperty("status","passed");result.addProperty("assertions",assertions);result.addProperty("scope","Actual production ScopedRouteThreatEntities capture/recheck/finalFence and BridgeJson; synthetic engine/server readers only, no real game");
  Files.writeString(out.resolve("RESULT.json"),result.toString());System.out.println(result);
 }
}
