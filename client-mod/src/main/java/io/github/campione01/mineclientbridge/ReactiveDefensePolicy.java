package io.github.campione01.mineclientbridge;

import java.util.Set;

/** Pure decisions shared by the actual native observer and offline checks. */
final class ReactiveDefensePolicy {
 static final Set<String> TYPES=Set.of("minecraft:skeleton","minecraft:stray","minecraft:bogged","minecraft:zombie","minecraft:husk","minecraft:drowned","minecraft:spider","minecraft:cave_spider","minecraft:magma_cube","minecraft:slime","minecraft:blaze","minecraft:phantom");
 static boolean phantom(String type){return "minecraft:phantom".equals(type);}
 // Client-observed velocity is only a short-horizon defensive cue, never attack/range proof.
 // Displacement is from the player's current eye to the Phantom's current box center.
 static boolean phantomIncoming(double distance,double dx,double dy,double dz,double vx,double vy,double vz){
  if(!Double.isFinite(distance+dx+dy+dz+vx+vy+vz)||distance<0||distance>12)return false;
  double separation2=dx*dx+dy*dy+dz*dz,speed2=vx*vx+vy*vy+vz*vz,dot=dx*vx+dy*vy+dz*vz;
  if(!Double.isFinite(separation2+speed2+dot)||separation2<=0||speed2<=0||-dot/Math.sqrt(separation2)<.12)return false;
  double ticks=-dot/speed2;
  if(ticks<=0||ticks>12)return false;
  double x=dx+vx*ticks,y=dy+vy*ticks,z=dz+vz*ticks;
  return x*x+y*y+z*z<=9;
 }
 static boolean trigger(String type,boolean supported,boolean alive,boolean visible,boolean targetSelf,double distance,boolean incoming){
  if(!phantom(type))return trigger(supported,alive,visible,targetSelf,distance);
  return supported&&alive&&visible&&Double.isFinite(distance)&&distance>=0&&(distance<=3||distance<=12&&incoming);
 }
 static boolean keepRecentTarget(boolean selectedReachable,boolean incomingPhantom){return !selectedReachable&&!incomingPhantom;}
 static boolean groundPursuit(String type){return !phantom(type);}
 static double priority(String type,double distance,boolean visible,boolean targetSelf,boolean inReach,boolean incoming){return priority(type,distance,visible,targetSelf,inReach)+(phantom(type)&&incoming?300:0);}
 static boolean needsLocalPlan(boolean nextPresent,boolean pathEmpty){return !nextPresent||pathEmpty;}
 static boolean ranged(String type){return Set.of("minecraft:skeleton","minecraft:stray","minecraft:bogged","minecraft:blaze").contains(type);}
 static boolean trigger(boolean supported,boolean alive,boolean visible,boolean targetSelf,double distance){return supported&&alive&&Double.isFinite(distance)&&(targetSelf&&distance<=24 || visible&&distance<=16);}
 static double priority(String type,double distance,boolean visible,boolean targetSelf,boolean inReach){return (inReach?1000:0)+(targetSelf?120:0)+(ranged(type)&&visible?80:0)-distance*4;}
 static boolean physicalReady(boolean noActive,boolean noDispatch,boolean noCleanup,boolean neutral,boolean matchingReceipt,boolean registryEmpty){return noActive&&noDispatch&&noCleanup&&neutral&&(matchingReceipt||registryEmpty);}
 static boolean clientDead(boolean removed,double health){return !removed&&Double.isFinite(health)&&health<=0;}
 static boolean attackReady(boolean sameTarget,boolean ray,double hitDistance,double reach,double strength,boolean using){return sameTarget&&ray&&Double.isFinite(hitDistance+reach+strength)&&hitDistance<=Math.min(3,reach)&&strength>=.95&&!using;}
 static record Stalled(double px,double py,double pz,double tx,double ty,double tz,double health,boolean visible,boolean self) {
  boolean unchanged(double x,double y,double z,double ex,double ey,double ez,double hp,boolean los,boolean aggro,boolean reachable){
   return !reachable&&hp>=health&&visible==los&&self==aggro&&square(x-px)+square(y-py)+square(z-pz)<4&&square(ex-tx)+square(ey-ty)+square(ez-tz)<1;
  }
  private static double square(double v){return v*v;}
 }
 static final class DirectFence {
  private boolean inFlight,unknown;private Object pending;
  boolean blocks(){return inFlight||unknown||pending!=null;}
  String state(){return inFlight?"in_flight":unknown?"dispatch_uncertain":pending!=null?"awaiting_neutral":"clear";}
  Object pendingToken(){return pending;}
  <T>T call(java.util.function.Supplier<T> effect,java.util.function.BooleanSupplier proof){
   return call(effect,()->true,proof);
  }
  <T>T call(java.util.function.Supplier<T> effect,java.util.function.BooleanSupplier binding,java.util.function.BooleanSupplier neutral){
   if(inFlight){unknown=true;throw new IllegalStateException("reactive_direct_dispatch_reentry");}
   inFlight=true;pending=null;boolean returned=false;
   try{
    T result=effect.get();boolean exact=binding.getAsBoolean();
    if(!exact){unknown=true;returned=true;return result;}
    boolean released=neutral.getAsBoolean();returned=true;
    if(!unknown&&!released)pending=new Object();return result;
   }finally{if(!returned)unknown=true;inFlight=false;}
  }
  boolean reconcile(Object token,java.util.function.BooleanSupplier proof){
   if(inFlight||unknown||token==null||pending!=token)return false;
   inFlight=true;boolean returned=false;
   try{boolean proven=proof.getAsBoolean();returned=true;if(!unknown&&pending==token&&proven){pending=null;return true;}return false;}
   finally{if(!returned)unknown=true;inFlight=false;}
  }
 }
 // A new dead-player object is deliberately NOT a deferred direct-release witness.
 static boolean directReleaseMatches(Object entry,ReactivePhysicalRelease.Context pending,long revision,
     Object latest,ReactivePhysicalRelease.Context current,long currentRevision,ReactivePhysicalRelease terminal){
  if(pending==null||!pending.sameWorld(current)||pending.player()!=current.player())return false;
  if(currentRevision==revision)return entry==latest;
  return currentRevision>revision&&terminal!=null&&terminal.physical&&terminal.entry==latest&&terminal.revision==currentRevision
      &&terminal.context!=null&&terminal.context.sameWorld(current)&&terminal.context.player()==current.player();
 }
 // Native successor motion is not a new user intent. Only the exact proven direct call may
 // retire its own pause; a later physical key/mouse event advances intent and keeps its pause.
 static boolean resumeDirectPause(Object pausedArm,Object currentArm,long pauseIntent,long currentIntent,boolean suspended,boolean directClear){
  return pausedArm!=null&&pausedArm==currentArm&&pauseIntent==currentIntent&&suspended&&directClear;
 }
 private ReactiveDefensePolicy(){}
}
