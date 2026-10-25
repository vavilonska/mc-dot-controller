package io.github.campione01.mineclientbridge;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/** Actual pure production predicates + source wiring checks; no live AI/game/attack proof. */
public final class PhantomDefenseChecks {
 private static int predicates,sourceChecks;
 private static final String PHANTOM="minecraft:phantom";
 private static void check(boolean value,String why){predicates++;if(!value)throw new AssertionError(why);}
 private static void source(boolean value,String why){sourceChecks++;if(!value)throw new AssertionError(why);}
 private static boolean incoming(double distance,double x,double y,double z,double vx,double vy,double vz){return ReactiveDefensePolicy.phantomIncoming(distance,x,y,z,vx,vy,vz);}
 private static boolean trigger(boolean visible,boolean self,double distance,boolean incoming){return ReactiveDefensePolicy.trigger(PHANTOM,true,true,visible,self,distance,incoming);}
 public static void main(String[] args)throws Exception {
  check(ReactiveDefensePolicy.TYPES.size()==12&&ReactiveDefensePolicy.TYPES.contains(PHANTOM),"explicit twelve-type set includes Phantom");
  check(!ReactiveDefensePolicy.TYPES.contains("minecraft:enderman")&&!ReactiveDefensePolicy.TYPES.contains("minecraft:creeper"),"no broader target admission");
  check(!ReactiveDefensePolicy.ranged(PHANTOM),"Phantom is not ground ranged pursuit");
  check(incoming(8,8,0,0,-1,0,0),"straight approaching swoop");
  check(incoming(8,6,6,0,-.75,-.75,0),"descending diagonal swoop");
  check(incoming(12,12,0,0,-1,0,0),"inclusive distance and prediction horizon");
  check(incoming(7,8,3,0,-1,0,0),"inclusive three-block closest approach");
  check(!incoming(7,8,3.01,0,-1,0,0),"flyby misses defensive proximity");
  check(!incoming(8,8,0,0,1,0,0),"outbound not incoming");
  check(!incoming(8,8,0,0,0,0,1),"tangential circling not incoming");
  check(!incoming(8,8,0,0,0,0,0),"missing motion not incoming");
  check(!incoming(8,8,0,0,-.5,0,0),"approach beyond twelve ticks not imminent");
  check(!incoming(1,1,0,0,-.119,0,0),"slow drift not incoming");
  check(!incoming(12.01,12.01,0,0,-2,0,0),"far swoop not admitted early");
  check(!incoming(-1,1,0,0,-1,0,0),"negative distance rejected");
  check(!incoming(0,0,0,0,-1,0,0),"zero displacement handled without divide by zero");
  for(double invalid:new double[]{Double.NaN,Double.NEGATIVE_INFINITY,Double.POSITIVE_INFINITY}){
   check(!incoming(invalid,8,0,0,-1,0,0),"nonfinite distance");
   check(!incoming(8,invalid,0,0,-1,0,0),"nonfinite position");
   check(!incoming(8,8,0,0,invalid,0,0),"nonfinite velocity");
  }
  check(!incoming(8,Double.MAX_VALUE,0,0,-Double.MAX_VALUE,0,0),"overflow rejected");
  for(int degrees=0;degrees<360;degrees+=15){
   double angle=Math.toRadians(degrees),x=8*Math.cos(angle),z=8*Math.sin(angle);
   check(!incoming(8,x,0,z,-Math.sin(angle),0,Math.cos(angle)),"circling rejected independent of yaw");
   check(incoming(8,x,0,z,-Math.cos(angle),0,-Math.sin(angle)),"incoming independent of yaw");
  }
  check(trigger(true,false,8,true),"visible geometric incoming can defend despite unknown native target");
  check(trigger(true,true,8,true),"native self-target incoming");
  check(trigger(true,false,3,false),"visible contact proximity can defend without velocity");
  check(!trigger(true,true,3.01,false),"targeted circle outside contact does not trigger");
  check(!trigger(true,true,24,false),"targeted distant Phantom does not trigger");
  check(!trigger(true,true,12.01,true),"incoming flag cannot bypass range bound");
  check(!trigger(false,true,2,true),"occluded Phantom not a direct visible threat");
  check(!trigger(true,true,-1,true)&&!trigger(true,true,Double.NaN,true),"invalid distance cannot trigger");
  check(!ReactiveDefensePolicy.trigger(PHANTOM,false,true,true,true,2,true),"unsupported denied");
  check(!ReactiveDefensePolicy.trigger(PHANTOM,true,false,true,true,2,true),"dead denied");
  double swoop=ReactiveDefensePolicy.priority(PHANTOM,8,true,false,false,true);
  check(swoop>ReactiveDefensePolicy.priority("minecraft:skeleton",8,true,true,false),"incoming before out-of-reach ground shooter");
  check(swoop<ReactiveDefensePolicy.priority("minecraft:zombie",2,true,true,true),"reachable ground attacker before out-of-reach swoop");
  check(ReactiveDefensePolicy.priority(PHANTOM,2,true,true,true,true)>ReactiveDefensePolicy.priority("minecraft:zombie",2,true,true,true),"reachable swoop breaks equal-reach tie");
  check(!ReactiveDefensePolicy.keepRecentTarget(false,true),"incoming can break ground selection stickiness");
  check(ReactiveDefensePolicy.keepRecentTarget(false,false),"ordinary ground selection stickiness preserved");
  check(!ReactiveDefensePolicy.keepRecentTarget(true,false),"reachable target still breaks stickiness");
  check(!ReactiveDefensePolicy.groundPursuit(PHANTOM),"no ground chase at any Phantom distance");
  for(String type:ReactiveDefensePolicy.TYPES)if(!type.equals(PHANTOM)){
   check(ReactiveDefensePolicy.groundPursuit(type),"existing ground movement preserved: "+type);
   for(boolean visible:new boolean[]{false,true})for(boolean self:new boolean[]{false,true})for(double distance:new double[]{2,16,16.01,24,24.01}){
    check(ReactiveDefensePolicy.trigger(type,true,true,visible,self,distance,true)==ReactiveDefensePolicy.trigger(true,true,visible,self,distance),"unchanged ground trigger: "+type);
    check(ReactiveDefensePolicy.priority(type,distance,visible,self,false,true)==ReactiveDefensePolicy.priority(type,distance,visible,self,false),"unchanged ground priority: "+type);
   }
  }
  check(ReactiveDefensePolicy.attackReady(true,true,3,3,.95,false),"real ray/reach/cooldown attack path remains available");
  check(!ReactiveDefensePolicy.attackReady(true,false,2,3,1,false),"incoming prediction cannot replace real ray");
  check(!ReactiveDefensePolicy.attackReady(true,true,3.01,9,1,false),"never extended aerial reach");
  check(!ReactiveDefensePolicy.attackReady(true,true,2,3,.949,false),"cooldown remains required");
  check(!ReactiveDefensePolicy.attackReady(true,true,2,3,1,true),"shield must lower before attack");
  check(!ReactiveDefensePolicy.attackReady(false,true,2,3,1,false),"same target required");
  if(args.length!=2)throw new IllegalArgumentException("requires NativeReactiveDefense.java and prepare-defense-test-request.py paths");
  String nativeSource=Files.readString(Path.of(args[0])),helper=Files.readString(Path.of(args[1]));
  source(nativeSource.contains("getEntitiesOfClass(Mob.class")&&nativeSource.contains("config.types().contains(type(v))"),"existing native Mob filter remains the authority");
  source(nativeSource.contains("velocity=e.getDeltaMovement()")&&nativeSource.contains("ReactiveDefensePolicy.phantomIncoming(d,delta.x,delta.y,delta.z,velocity.x,velocity.y,velocity.z)"),"actual client motion feeds tested predictor");
  source(nativeSource.contains("ReactiveDefensePolicy.trigger(type,true,true,visible,self,d,incoming)"),"actual contacts use type-specific narrow trigger");
  source(nativeSource.contains("ReactiveDefensePolicy.priority(type,d,visible,self,reach,incoming)")&&nativeSource.contains("ReactiveDefensePolicy.keepRecentTarget(selected.reachable,selected.incoming)"),"actual selection uses tested priority and stickiness");
  int aim=nativeSource.indexOf("tracked.put(target.getUUID()"),attack=nativeSource.indexOf("ReactiveDefensePolicy.attackReady("),branch=nativeSource.indexOf("if(!ReactiveDefensePolicy.groundPursuit(selected.type))"),motion=nativeSource.indexOf("else moved=motion(mc,target,escape,now,tick)");
  source(aim>=0&&aim<attack&&nativeSource.substring(aim,attack).contains("aim(mc,target.getBoundingBox().getCenter())"),"faces actual selected target before picking/attacking");
  source(attack>=0&&branch>attack&&motion>branch,"Phantom hold follows identical guarded attack but precedes ground planner");
  String hold=nativeSource.substring(branch,nativeSource.indexOf("boolean escape=",branch));
  source(hold.contains("next=null;path=List.of()")&&hold.contains("return new NativeBlazeEscort.Step(0,0,water,null")&&!hold.contains("motion("),"Phantom hold clears old route and emits no horizontal motion or pursuit");
  source(nativeSource.substring(attack,branch).contains("shield(mc,config.shield());"),"Phantom hold raises optional actual shield before stationary branch");
  source(nativeSource.contains("mc.gameRenderer.pick(1.0F)")&&nativeSource.contains("ray(mc,target)")&&nativeSource.contains("player.getAttackStrengthScale(.5F)")&&nativeSource.contains("tick!=previousTick"),"fresh picker, actual ray, strength and once-per-tick attack guards remain");
  source(helper.contains("'blaze', 'phantom'")&&helper.contains("1 <= len(values) <= len(SUPPORTED_TYPES)")&&!helper.contains("1-11"),"independent TEST helper supports closed twelve-type set");
  System.out.println("PhantomDefenseChecks PASS production_predicates="+predicates+" source_hooks="+sourceChecks+"; no live AI/game/shield/sword proof claimed");
 }
}
