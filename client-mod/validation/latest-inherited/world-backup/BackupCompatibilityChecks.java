package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.util.*;
import java.nio.file.*;
public final class BackupCompatibilityChecks {
 static int n;static void check(boolean b,String s){n++;if(!b)throw new AssertionError(s);}
 static ClientActionRequest request(String action,boolean guarded){
  JsonObject b=new JsonObject();b.addProperty("action_id",UUID.randomUUID().toString());b.addProperty("action",action);
  b.addProperty("timeout_ms",5000);
  switch(action){
   case "break_block" -> b.add("target",JsonParser.parseString("{\"x\":0,\"y\":64,\"z\":0}"));
   case "place_block" -> {b.add("support",JsonParser.parseString("{\"x\":0,\"y\":63,\"z\":0}"));b.addProperty("face","up");}
   case "click_slot" -> {b.addProperty("container_id",0);b.addProperty("slot",1);b.addProperty("button",0);b.addProperty("click_type","pickup");}
   case "follow_path" -> b.add("waypoints",JsonParser.parseString("[{\"x\":0,\"y\":64,\"z\":0}]"));
  }
  var r=ClientActionRequest.parse(b); // Use actual parsing, no substitute action or registry.
  if(!guarded)return r;
  b.add("capability_guard",new JsonObject());
  // Registry-only fixture: an admitted guarded request; no claim this incomplete guard is wire-valid.
  return new ClientActionRequest(r.id(),r.action(),r.timeoutMs(),r.waypoints(),r.target(),r.support(),r.face(),r.hotbarSlot(),r.jump(),r.sneak(),r.containerId(),r.slot(),r.button(),r.clickType(),b);
 }
 static ActionRegistry legacy(String action,String status){var r=new ActionRegistry();r.begin(request(action,false));r.finish(status,"test_known_terminal");return r;}
 public static void main(String[]args)throws Exception{
  for(String action:List.of("break_block","place_block","click_slot")) for(String status:List.of("succeeded","failed","cancelled")){
   var r=legacy(action,status);String before=r.status(null).toString();check(r.backupSafe(),action+" "+status+" legacy schema");
   check(before.equals(r.status(null).toString())&&!r.get(null).result.has("input_release_confirmed"),"history/fields unchanged");
  }
  for(JsonElement v:List.of(new JsonPrimitive(false),new JsonPrimitive("true"),JsonNull.INSTANCE,new JsonObject())){
   var r=legacy("place_block","succeeded");r.get(null).result.add("input_release_confirmed",v);check(!r.backupSafe(),"explicit false/malformed release");
  }
  for(String flag:List.of("unknown_outcome","requires_handoff","no_auto_resume","requires_reconciliation_before_retry","unknown_attack_outcome")){
   var r=legacy("break_block","succeeded");JsonObject nested=new JsonObject();nested.addProperty(flag,true);JsonArray a=new JsonArray();a.add(nested);r.get(null).result.add("nested",a);
   check(!r.backupSafe(),"nested explicit "+flag);nested.addProperty(flag,false);check(r.backupSafe(),"explicit false is not unknown");
   nested.addProperty(flag,"false");check(!r.backupSafe(),"malformed unknown flag refused");
  }
  for(String action:List.of("break_block","place_block","click_slot")){
   var r=new ActionRegistry();r.begin(request(action,true));r.finish("succeeded","test_guarded");check(!r.backupSafe(),"managed guard requires release");
   r.get(null).result.addProperty("input_release_confirmed",true);check(r.backupSafe(),"managed release attested");
  }
  var follow=legacy("follow_path","succeeded");check(!follow.backupSafe(),"follow always managed");follow.get(null).result.addProperty("input_release_confirmed",true);check(follow.backupSafe(),"follow released");
  var discontinuity=legacy("break_block","failed");discontinuity.get(null).reason="position_discontinuity_rebind_required";check(!discontinuity.backupSafe(),"discontinuity managed cleanup");
  var placed=legacy("place_block","failed");placed.get(null).result.addProperty("dispatched",true);check(!placed.backupSafe(),"failed dispatched placement not known");placed.get(null).result.addProperty("dispatched",false);check(placed.backupSafe(),"undispatched known failure");
  var click=legacy("click_slot","failed");click.get(null).result.addProperty("dispatched",true);check(!click.backupSafe(),"failed dispatched menu click uncertain even absent old flag");click.get(null).result.addProperty("dispatched","false");check(!click.backupSafe(),"malformed dispatch refuses");click.get(null).result.addProperty("dispatched",false);check(click.backupSafe(),"known undispatched menu failure");
  var history=legacy("place_block","succeeded");var first=history.get(null);first.result.addProperty("unknown_outcome",true);
  history.begin(request("follow_path",false));history.finishAfterCleanup("succeeded","path_reached",true);check(!history.backupSafe(),"later success does not wash old unknown");
  first.result.remove("unknown_outcome");check(history.backupSafe(),"mixed legacy and released full history");history.begin(request("click_slot",false));check(!history.backupSafe(),"current active always refuses");
  var managed=legacy("follow_path","failed");managed.begin(request("place_block",false));managed.finish("succeeded","known_place");check(!managed.backupSafe(),"old managed missing release still refuses");
  // Pin the unchanged real caller gates rather than inventing a fake Minecraft/owner implementation.
  String caller=Files.readString(Path.of(args[0]));String nativeSource=Files.readString(Path.of(args[1]));
  check(caller.contains("active==null && !TERMINAL_CLEANUP.active() && scopedDispatchInFlight==null && ACTIONS.backupSafe()"),"real current owner/cleanup/dispatch gate");
  check(nativeSource.contains("!ClientActions.backupSafe()||ClientActions.ownsInput()||!ExternalControllerGuard.idle(mc)"),"real current direct/external owner gate");
  check(nativeSource.contains("!BridgeServer.heldInputsSnapshot(mc).get(\"neutral\").getAsBoolean()||GuardedGameMovement.LEASES.status().ownerRequestId()!=null"),"real held-neutral/lease gate");
  System.out.println("BackupCompatibilityChecks PASS "+n);
 }
}
