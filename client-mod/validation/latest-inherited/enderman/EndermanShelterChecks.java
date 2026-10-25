package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.util.*;
import java.nio.file.*;
import net.minecraft.world.phys.*;
public final class EndermanShelterChecks {
 static int n;static final String TARGET="2ee2bd64-951a-4bdc-9042-0360b6e28b65",PLAYER="19fe5b8a-a2cd-4869-b716-f6abc1c8c7d8";
 static void check(boolean b,String s){n++;if(!b)throw new AssertionError(s);}
 interface F{void run();}static void reject(F f,String s){n++;try{f.run();throw new AssertionError(s);}catch(ClientActionRequest.Rejected expected){}}
 static JsonObject request(){return JsonParser.parseString("""
 {"action_id":"offline-ender-test","action":"follow_path","timeout_ms":60000,"expected_action_session":"09fe5b8a-a2cd-4869-b716-f6abc1c8c7d8","expected_world_generation":"29fe5b8a-a2cd-4869-b716-f6abc1c8c7d8","expected_player_uuid":"19fe5b8a-a2cd-4869-b716-f6abc1c8c7d8","expected_navigation_epoch":4,"expected_origin":{"x":0.5,"y":64,"z":0.5},"waypoints":[{"x":2.5,"y":64,"z":0.5},{"x":0.5,"y":64,"z":0.5}],"enderman_shelter":{"schema_version":1,"known_route":true,"target_uuid":"2ee2bd64-951a-4bdc-9042-0360b6e28b65","shield":true,"stop_health":6,"maximum_observed_damage":20,"continuous_fire_ms":5000,"lure_timeout_ms":4000,"engage_timeout_ms":30000}}
 """).getAsJsonObject();}
 static void validate(JsonObject j){NativeShelteredEnderman.validate(ClientActionRequest.parse(j));}
 static EndermanShelterPolicy policy(){return new EndermanShelterPolicy(20,6,20,5000,4000,30000);}
 static JsonObject row(boolean alive,NativeLivingSnapshot.Target target){Object context=new Object();long now=1_000_000_000L;var r=new NativeLivingSnapshot.Row(TARGET,7,"minecraft:enderman",50,now,alive,false,target,null);var b=new NativeLivingSnapshot.Batch(context,new Object(),"minecraft:the_nether",Map.of(TARGET,r),true,1,"observed");return NativeLivingSnapshot.json(b,context,"minecraft:the_nether","generation",PLAYER,TARGET,7,"minecraft:enderman",50,now+1000);}
 public static void main(String[]args)throws Exception{
  var c=NativeShelteredEnderman.validate(ClientActionRequest.parse(request()));check(c.uuid().equals(TARGET)&&c.peek().x()==2.5&&c.cover().x()==.5,"actual parse explicit target/out-back");
  for(String f:NativeShelteredEnderman.FIELDS){var j=request();j.getAsJsonObject("enderman_shelter").remove(f);reject(()->validate(j),"missing "+f);}
  var extra=request();extra.getAsJsonObject("enderman_shelter").addProperty("nearest",true);reject(()->validate(extra),"no automatic candidate switch");
  for(String f:List.of("blaze_guard","capability_guard","coordination_step","capability_route","portal_handoff","portal_handoff_parent","sprint")){var j=request();j.addProperty(f,true);reject(()->validate(j),"mutually exclusive "+f);}
  var far=request();far.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("x",8);reject(()->validate(far),"not arbitrary route");
  var vertical=request();vertical.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("y",65);reject(()->validate(vertical),"no unknown stair chase");
  var badBack=request();badBack.getAsJsonArray("waypoints").get(1).getAsJsonObject().addProperty("z",1);reject(()->validate(badBack),"return original shelter only");
  var jump=request();jump.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("jump",true);reject(()->validate(jump),"no extra jump");
  var sneak=request();sneak.addProperty("sneak",true);reject(()->validate(sneak),"plain bounded route");
  var p=policy();check(!p.mayAttack(1,true,1,false,true),"outbound never attacks");p.atPeek(100,true);check(p.phase==EndermanShelterPolicy.Phase.GAZING,"real eyes only at peek");
  p.gaze(1000001000L,true);check(!p.aggroConfirmed&&p.phase==EndermanShelterPolicy.Phase.GAZING,"look alone does not fabricate aggro");
  p.confirmAggro(1000001001L);check(p.phase==EndermanShelterPolicy.Phase.RETURNING&&p.aggroConfirmed,"fresh server target initiates immediate same-owner return");
  check(!p.mayAttack(2,true,1,false,true),"no exposed return attack");p.atCover();check(p.phase==EndermanShelterPolicy.Phase.FIGHTING,"only actual cover arrival arms melee");
  check(!p.mayAttack(3,false,1,false,true)&&!p.mayAttack(3,true,.94,false,true)&&!p.mayAttack(3,true,1,true,true)&&!p.mayAttack(3,true,1,false,false),"fresh ray/strength/use/self all required");
  check(p.mayAttack(3,true,.95,false,true),"ready leg hit after true aggro");p.attack(3);check(!p.mayAttack(3,true,1,false,true)&&p.attacks==1,"one attack per native tick");
  long original=p.engagedSince;p.confirmAggro(original+1000);check(p.engagedSince==original,"observation does not renew engagement timer");p.dead();p.atCover();check(p.phase==EndermanShelterPolicy.Phase.DONE&&p.knownDead,"confirmed death at shelter closes without pickup");p.dead();check(p.phase==EndermanShelterPolicy.Phase.DONE,"same dead UUID not counted/reopened");
  p=policy();p.atPeek(0,false);p.atCover();check(p.aborted&&p.phase==EndermanShelterPolicy.Phase.DONE&&!p.aggroConfirmed,"no eye line returns, not indefinite wait");
  p=policy();p.atPeek(0,true);p.gaze(4_000_000_000L,true);p.atCover();check(p.aborted&&p.reason.equals("gaze_deadline_without_server_target"),"bounded gaze without target proof");
  p=policy();p.atPeek(0,true);p.gaze(1,false);check(p.phase==EndermanShelterPolicy.Phase.RETURNING,"eye line loss returns");
  p=policy();p.confirmAggro(0);p.atCover();p.deadline(30_000_000_000L);check(p.aborted&&p.reason.equals("engagement_deadline"),"engagement remains bounded");
  p=policy();p.health(16,false,false,0);p.health(20,false,false,1);p.health(3,false,false,2);check(p.health.observedDamage==21&&p.aborted,"healing does not erase damage budget");
  p=policy();p.health(20,false,true,0);check(p.aborted,"liquid danger returns");
  p=policy();p.abort("target_missing_not_a_kill");p.atCover();check(!p.knownDead&&p.phase==EndermanShelterPolicy.Phase.DONE,"teleport/unload is not a kill");
  check(!NativeShelteredEnderman.clientDead(true,20)&&!NativeShelteredEnderman.clientDead(true,0),"removed never proves death");check(NativeShelteredEnderman.clientDead(false,0)&&!NativeShelteredEnderman.clientDead(false,2),"nonremoved zero health only");
  var self=row(true,new NativeLivingSnapshot.Target(PLAYER,1,"minecraft:player"));check(NativeShelteredEnderman.targetSelf(self,PLAYER)&&!self.get("aggressive").getAsBoolean(),"real server target wins over false Mob.aggressive");
  check(!NativeShelteredEnderman.targetSelf(row(true,null),PLAYER),"known null not self");check(!NativeShelteredEnderman.targetSelf(row(true,new NativeLivingSnapshot.Target(TARGET,2,"minecraft:player")),PLAYER),"target other not self");
  check(NativeShelteredEnderman.knownDead(row(false,null))&&!NativeShelteredEnderman.knownDead(self),"individual server death vs alive");
  Object context=new Object();long now=5_000_000_000L;var dr=new NativeLivingSnapshot.Row(TARGET,9,"minecraft:enderman",100,now,false,false,null,null);var batch=new NativeLivingSnapshot.Batch(context,new Object(),"minecraft:the_nether",Map.of(TARGET,dr),true,1,"observed");
  for(int scenario=0;scenario<6;scenario++){
   var r=NativeLivingSnapshot.json(batch,scenario==0?new Object():context,scenario==1?"minecraft:overworld":"minecraft:the_nether","g",PLAYER,scenario==2?PLAYER:TARGET,scenario==3?10:9,"minecraft:enderman",scenario==4?106:100,scenario==5?now+250_000_001L:now+1000);
   check(!NativeShelteredEnderman.knownDead(r)&&!NativeShelteredEnderman.targetSelf(r,PLAYER),"unknown identity/freshness case "+scenario);
  }
  Vec3 eye=new Vec3(.5,65.62,.5);AABB ender=new AABB(2.2,64,.2,2.8,66.9,.8);Vec3 leg=NativeShelteredEnderman.legAim(ender);AABB roof=new AABB(-1,66,-1,2,67,2);
  check(leg.y>64&&leg.y<65,"leg aim inside current entity low bbox");check(roof.clip(eye,new Vec3(2.5,66.55,.5)).isPresent(),"actual AABB roof blocks eye-to-eye");check(roof.clip(eye,leg).isEmpty()&&ender.clip(eye,leg).isPresent(),"same roof does not block low leg segment");
  check(CombatRules.rayInReach(true,2.8,3)&&!CombatRules.rayInReach(true,3.01,4.5),"vanilla actual hit capped3 unchanged");
  JsonObject result=new JsonObject();int[] effects={0};NativeBlazeEscort.inputAttempt(result,()->effects[0]++,()->true);check(effects[0]==1&&!result.has("unknown_outcome"),"same-owner known native input");
  JsonObject uncertain=new JsonObject();try{NativeBlazeEscort.inputAttempt(uncertain,()->{effects[0]++;throw new IllegalStateException("fixture");},()->true);}catch(IllegalStateException expected){}
  check(uncertain.get("unknown_outcome").getAsBoolean()&&uncertain.get("requires_handoff").getAsBoolean(),"input throw remains top-level UNKNOWN");
  int before=effects[0];try{NativeBlazeEscort.inputAttempt(uncertain,()->effects[0]++,()->true);}catch(IllegalStateException expected){}check(effects[0]==before,"unknown original never reissued");
  JsonObject changedContext=new JsonObject();boolean[] sameContext={true};try{NativeBlazeEscort.inputAttempt(changedContext,()->sameContext[0]=false,()->sameContext[0]);}catch(IllegalStateException expected){}check(changedContext.get("unknown_outcome").getAsBoolean(),"callback context change preserves unknown before owner returns");
  ActionRegistry registry=new ActionRegistry();var entry=registry.begin(ClientActionRequest.parse(request()));try{NativeBlazeEscort.inputAttempt(entry.result,()->registry.finishAfterCleanup("cancelled","cancel_requested",true),()->registry.active()==entry);}catch(IllegalStateException expected){}
  check(entry.result.get("unknown_outcome").getAsBoolean()&&entry.result.get("input_release_confirmed").getAsBoolean(),"synchronous cancellation preserves independent unknown/release");
  String src=Files.readString(Path.of(args[0]));check(src.replaceAll("\\s+", "").contains("a.shelteredEnderman==null&&a.portalDefense==null"),"actual terminal cleanup scope includes new owner");check(src.contains("shelteredEnderman.bind(()->active==owner && ACTIONS.active()==owner.entry && owner.entry.running()"),"exact entry owner bind");check(src.contains("a.shelteredEnderman.release(Minecraft.getInstance(),()->requireCleanupOwner(a))"),"actual cleanup fenced release");
  String adapter=Files.readString(Path.of(args[0]).resolveSibling("NativeShelteredEnderman.java"));check(adapter.contains("mc.startAttack(),()->stillOwner(mc)")&&adapter.contains("InteractionHand.OFF_HAND),()->stillOwner(mc)"),"actual attack/use dispatch verify full captured context before clear");
  System.out.println("EndermanShelterChecks PASS "+n+"; real AI/renderer/shelter TEST NOT_RUN");
 }
}
