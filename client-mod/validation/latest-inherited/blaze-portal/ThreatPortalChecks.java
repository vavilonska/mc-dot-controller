package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.lang.reflect.Field;
/** Production parser, registry, identity fences and observation decisions. No live TEST claim. */
public final class ThreatPortalChecks {
 static int checks; static void ok(boolean v,String why){checks++;if(!v)throw new AssertionError(why);}
 static void reject(Runnable f,String why){checks++;try{f.run();throw new AssertionError(why);}catch(ClientActionRequest.Rejected expected){}}
 static JsonObject body(){var j=BlazeEscortChecks.request();j.getAsJsonObject("blaze_guard").addProperty("creeper_escape",true);return j;}
 static JsonObject portal(){var j=body();var p=JsonParser.parseString("""
 {"schema_version":1,"from_dimension":"minecraft:overworld","to_dimension":"minecraft:the_nether",
  "ttl_ms":30000,"defend_ms":1500,"destination_timeout_ms":15000,
  "landing_min":{"x":0,"y":63.9,"z":0},"landing_max":{"x":1,"y":64.1,"z":1},
  "destination_waypoints":[{"x":0.5,"y":64,"z":2.5}]}
 """).getAsJsonObject();var guard=j.getAsJsonObject("blaze_guard").deepCopy();guard.addProperty("arrival_hold_ms",0);p.add("destination_guard",guard);j.add("portal_handoff",p);return j;}
 static void field(String name,Object value)throws Exception{Field f=NativePortalHandoff.class.getDeclaredField(name);f.setAccessible(true);f.set(null,value);}
 static NativeThreatObservation.Contact c(double d,boolean creeper,boolean ignited,int dir){return new NativeThreatObservation.Contact(1,"u","minecraft:creeper",0,0,0,d,creeper,ignited,false,0,30,dir);}
 public static void main(String[] args)throws Exception {
  ok(!NativeBlazeEscort.validate(ClientActionRequest.parse(BlazeEscortChecks.request())).creeperEscape(),"default old guard unchanged");
  ok(NativeBlazeEscort.validate(ClientActionRequest.parse(body())).creeperEscape(),"explicit escape opt-in");
  ok(c(2.9,true,false,0).imminent(),"close creeper before ignition");ok(c(7,true,false,1).imminent(),"synced swell direction triggers");
  ok(c(7,true,true,-1).imminent(),"ignited cannot be mistaken for unswelling");ok(!c(9,true,true,1).imminent(),"warning range is not escape authority");
  ok(!c(5,true,false,-1).imminent()&&!c(1,false,true,1).imminent(),"ordinary mob and far idle creeper not fuse event");
  var p=BlazeEscortChecks.policy();p.acquire(BlazeEscortChecks.contact("locked-zombie",true,true,2),0);p.beginReturn("creeper_threat_escape");
  ok(!p.mayAttack(1,true,1,false)&&p.phase==BlazeEscortPolicy.Phase.RETURNING,"fuse interrupts already engaged attack");
  for(float yaw:new float[]{0,90,-90,180}){float[] v=NativeBlazeEscort.relativeMotion(yaw,0,1);double x=-v[0]*Math.sin(0)+v[1]*Math.cos(0),z=v[0];ok(Math.abs(x+Math.sin(Math.toRadians(yaw)))<1e-5&&Math.abs(z-Math.cos(Math.toRadians(yaw)))<1e-5,"shield-facing vector preserves known route world direction "+yaw);}
  ok(!NativeBlazeEscort.escapeDirectionNonClosing(0,0,3,0,1,0),"farther endpoint across fuse is not escape");
  ok(NativeBlazeEscort.escapeDirectionNonClosing(0,0,-3,0,1,0),"away along known route");
  ok(NativeBlazeEscort.escapeDirectionNonClosing(0,0,0,3,1,0),"lateral tangent increases distance");
  ok(!NativeBlazeEscort.escapeDirectionNonClosing(0,0,.5,.5,1,0),"temporary smooth turn toward fuse holds movement");
  var r=ClientActionRequest.parse(portal());var plan=NativePortalHandoff.validate(r);ok(plan.to().equals("minecraft:the_nether")&&plan.route().size()==1,"real destination parser binds explicit short route");
  for(String key:new String[]{"from_dimension","to_dimension"}){var bad=portal();bad.getAsJsonObject("portal_handoff").addProperty(key,"minecraft:the_end");reject(()->ClientActionRequest.parse(bad),"unapproved dimension");}
  var bad=portal();bad.getAsJsonObject("portal_handoff").addProperty("to_dimension","minecraft:overworld");reject(()->ClientActionRequest.parse(bad),"same dimension not portal authorization");
  for(int ttl:new int[]{0,120001}){var x=portal();x.getAsJsonObject("portal_handoff").addProperty("ttl_ms",ttl);reject(()->ClientActionRequest.parse(x),"ttl bounded");}
  var big=portal();big.getAsJsonObject("portal_handoff").getAsJsonObject("landing_max").addProperty("x",100);reject(()->ClientActionRequest.parse(big),"landing region bounded");
  var hold=portal();hold.getAsJsonObject("portal_handoff").getAsJsonObject("destination_guard").addProperty("arrival_hold_ms",30000);reject(()->ClientActionRequest.parse(hold),"destination not automatic return into portal");
  var missing=portal();missing.getAsJsonObject("portal_handoff").getAsJsonObject("destination_guard").remove("creeper_escape");reject(()->ClientActionRequest.parse(missing),"destination explicit fuse response required");
  var extra=portal();extra.getAsJsonObject("portal_handoff").addProperty("teleport",true);reject(()->ClientActionRequest.parse(extra),"closed authorization scope");
  var reg=new ActionRegistry();var original=reg.begin(r);ok(!NativePortalHandoff.exactTransition(original),"running source never hands off");
  reg.finishAfterCleanup("cancelled","world_transition",true);ok(NativePortalHandoff.exactTransition(original),"actual original registry terminal release transition");
  for(String flag:new String[]{"unknown_outcome","requires_handoff","no_auto_resume"}){for(JsonElement value:new JsonElement[]{new JsonPrimitive(true),new JsonPrimitive("false"),JsonNull.INSTANCE}){original.result.add(flag,value);ok(!NativePortalHandoff.exactTransition(original),"uncertain/malformed original flags reject "+flag);}original.result.remove(flag);}
  original.status="unknown";ok(!NativePortalHandoff.knownReleased(original),"unrecognized terminal never classified known");original.status="cancelled";
  original.result.addProperty("input_release_confirmed",false);ok(!NativePortalHandoff.exactTransition(original),"cleanup failure cannot be a handoff");original.result.addProperty("input_release_confirmed",true);
  for(String reason:new String[]{"cancel_requested","player_dead","deadline_exceeded","direct_takeover","external_controller_owner_unconfirmed"}){original.reason=reason;ok(!NativePortalHandoff.exactTransition(original),"not a portal completion: "+reason);}original.reason="world_transition";
  Object server=new Object();var permit=new NativePortalHandoff.Permit(plan,server,"player","session","oldworld",original,0);
  ok(NativePortalHandoff.contextProblem(permit,1,server,"session","player",true)==null,"same identity before deadline");
  ok(NativePortalHandoff.contextProblem(permit,permit.deadline,server,"session","player",true).equals("authorization_expired"),"fixed total ttl never resets");
  ok(NativePortalHandoff.contextProblem(permit,1,new Object(),"session","player",true).equals("server_changed"),"same-looking different server rejected");
  ok(NativePortalHandoff.contextProblem(permit,1,server,"new-session","player",true).equals("action_session_changed"),"new boot rejects old permit");
  ok(NativePortalHandoff.contextProblem(permit,1,server,"session","player",false).equals("player_dead_or_changed"),"death revokes");
  ok(NativePortalHandoff.contextProblem(permit,1,server,"session","other",true).equals("player_dead_or_changed"),"different player rejected");
  ok(NativePortalHandoff.allowedClone(true,true,"p","p","p","minecraft:overworld","minecraft:the_nether","minecraft:overworld","minecraft:the_nether",true),"real alive cross-dimension Clone permitted");
  ok(!NativePortalHandoff.allowedClone(false,true,"p","p","p","minecraft:overworld","minecraft:the_nether","minecraft:overworld","minecraft:the_nether",true),"death-respawn cannot reuse pending permit");
  ok(!NativePortalHandoff.allowedClone(true,true,"p","p","p","minecraft:overworld","minecraft:overworld","minecraft:overworld","minecraft:the_nether",true),"same dimension clone not authorized");
  ok(!NativePortalHandoff.allowedClone(true,true,"p","p","p","minecraft:overworld","minecraft:the_nether","minecraft:overworld","minecraft:the_nether",false),"clone does not convert uncertain old record");
  // Real production one-use entry/final fences. Copying the exact JSON is not the in-process request object.
  var internal=JsonParser.parseString("{\"action\":\"portal_defend\",\"action_id\":\"new-child\",\"timeout_ms\":1500,\"portal_handoff_parent\":\"offline-blaze-001\"}").getAsJsonObject();
  var child=ClientActionRequest.parse(internal);reject(()->NativePortalHandoff.beforeStart(child),"HTTP cannot forge internal child");
  permit=new NativePortalHandoff.Permit(plan,server,"player","session","oldworld",original,System.nanoTime());
  field("permit",permit);field("authorizedPermit",permit);field("authorizedRequest",child);field("executing",true);
  reject(()->NativePortalHandoff.beforeStart(ClientActionRequest.parse(internal)),"equal JSON distinct object denied");
  NativePortalHandoff.beforeStart(child);NativePortalHandoff.requireFinal(child);ok(true,"exact internal request accepted once");
  reject(()->NativePortalHandoff.beforeStart(child),"swallowed reentrant start cannot borrow consumed authorization");
  field("permit",null);reject(()->NativePortalHandoff.requireFinal(child),"revocation between hooks and input denied");
  field("authorizedPermit",null);field("authorizedRequest",null);field("inFlightPermit",null);field("inFlightRequest",null);field("executing",false);
  ok(reg.get(r.id())==original&&original.reason.equals("world_transition"),"old registry record remains unmodified");
  System.out.println("ThreatPortalChecks PASS checks="+checks+"; production parser/registry/identity/fuse math, no live game claimed");
 }
}
