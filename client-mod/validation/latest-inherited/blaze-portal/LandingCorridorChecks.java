package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import net.minecraft.world.phys.Vec3;
public final class LandingCorridorChecks {
 static int n;static void ok(boolean b,String why){n++;if(!b)throw new AssertionError(why);}
 static NativePortalHandoff.Permit permit(){var request=ThreatPortalChecks.portal();var p=request.getAsJsonObject("portal_handoff");
  p.add("landing_min",JsonParser.parseString("{\"x\":3.85,\"y\":69.8,\"z\":-0.15}"));p.add("landing_max",JsonParser.parseString("{\"x\":5.15,\"y\":70.2,\"z\":1.15}"));
  p.add("destination_waypoints",JsonParser.parseString("[{\"x\":4.5,\"y\":70,\"z\":2.5},{\"x\":4.5,\"y\":70,\"z\":5.5},{\"x\":4.5,\"y\":70,\"z\":8.5}]"));
  var r=ClientActionRequest.parse(request);var e=new ActionRegistry.Entry(r);return new NativePortalHandoff.Permit(NativePortalHandoff.validate(r),new Object(),"p","s","old",e,0);}
 public static void main(String[] args){
  var p=permit();ok(!NativePortalHandoff.locationAllowed(p,new Vec3(4.5,70,1.56))&&!p.landingAccepted,"first destination must be inside exact authorized landing box");
  Vec3 anchor=new Vec3(4.5,70,.5);ok(NativePortalHandoff.locationAllowed(p,anchor)&&p.landingAccepted,"first valid actual landing consumed once");
  ok(NativePortalHandoff.locationAllowed(p,new Vec3(4.5,70.205375,.748)),"trial13 normal upward knockback no longer thin-box false reject");
  ok(NativePortalHandoff.locationAllowed(p,new Vec3(4.5,70,1.563038)),"trial13 forward knockback inside verified first exit segment");
  ok(p.landingOrigin==anchor,"accepted origin not rebased by later knockback");
  ok(!NativePortalHandoff.locationAllowed(p,new Vec3(6,70,1.5)),"lateral route escape still denied");
  ok(!NativePortalHandoff.locationAllowed(p,new Vec3(4.5,72.01,1.5)),"vertical drift bounded");
  ok(!NativePortalHandoff.locationAllowed(p,new Vec3(4.5,68.49,1.5)),"fall below known route bounded");
  ok(!NativePortalHandoff.locationAllowed(p,new Vec3(4.5,70,5.5)),"defense cannot claim later future segment as landing drift");
  ok(!NativePortalHandoff.locationAllowed(p,new Vec3(Double.NaN,70,.5)),"nonfinite location rejected");
  ok(p.deadline==30_000_000_000L&&!p.routeSubmitted&&!p.defenseSubmitted,"location proof does not extend ttl or create any action");
  p.routeSubmitted=true;ok(NativePortalHandoff.locationAllowed(p,new Vec3(4.5,70,5.5)),"actual registered route thereafter owns existing per-step corridor checks");
  System.out.println("LandingCorridorChecks PASS checks="+n+"; exact trial13 knockback, fixed consumed anchor, no new UUID or TTL mutation; no live claim");
 }
}
