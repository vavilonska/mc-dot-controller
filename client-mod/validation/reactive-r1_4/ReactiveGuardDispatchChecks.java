package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** Real production dispatcher/predicates, fake physical observations/effects; never a Minecraft instance. */
public final class ReactiveGuardDispatchChecks {
 private static int dispatchChecks,predicateChecks,sourceChecks;
 private static void dispatch(boolean yes,String why){dispatchChecks++;if(!yes)throw new AssertionError(why);}
 private static void predicate(boolean yes,String why){predicateChecks++;if(!yes)throw new AssertionError(why);}
 private static void source(boolean yes,String why){sourceChecks++;if(!yes)throw new AssertionError(why);}
 private static final class Host implements ReactiveGuardDispatch.Host {
  String owner;boolean interrupt,allowCancel=true,cancelThrows,physicalThrows;
  boolean noDispatch=true,noCleanup=true,neutral=true,receipt=true,registryEmpty;
  int starts,cancels,physicalReads;String waitReason;final List<String> events=new ArrayList<>();
  public boolean hasOwner(){events.add("owner");return owner!=null;}
  public boolean interruptAllowed(){events.add("interrupt");return interrupt;}
  public boolean physicalReady(){events.add("physical");physicalReads++;if(physicalThrows)throw new IllegalStateException("physical unavailable");return ReactiveDefensePolicy.physicalReady(owner==null,noDispatch,noCleanup,neutral,receipt,registryEmpty);}
  public boolean cancelExactOriginal(){events.add("cancel:"+owner);cancels++;if(cancelThrows)throw new IllegalStateException("cancel uncertain");if(allowCancel){owner=null;return true;}return false;}
  public void startNewProtection(){events.add("start");starts++;owner="new-protection";}
  public void waiting(String reason){events.add("wait:"+reason);waitReason=reason;}
 }
 public static void main(String[] args)throws Exception {
  Host idle=new Host();idle.registryEmpty=true;idle.receipt=false;
  ReactiveGuardDispatch.tick(idle);
  dispatch(idle.starts==1&&idle.cancels==0,"idle starts directly on tick, no HTTP host capability exists");
  dispatch(idle.events.equals(List.of("owner","physical","start")),"idle actual branch order");
  for(int tick=0;tick<12;tick++)ReactiveGuardDispatch.tick(idle);
  dispatch(idle.starts==1&&idle.cancels==0&&idle.owner.equals("new-protection"),"multiple ticks one owner when interruption disabled");
  dispatch(idle.physicalReads==1,"active owner does not bypass via physical-ready branch");

  JsonObject knownFailed=new JsonObject();knownFailed.addProperty("status","failed");knownFailed.addProperty("input_release_confirmed",true);
  JsonObject knownCopy=knownFailed.deepCopy();Host failed=new Host();ReactiveGuardDispatch.tick(failed);
  dispatch(failed.starts==1,"known failed with modeled matching physical release starts separate protection");
  dispatch(knownFailed.equals(knownCopy),"original failed evidence not rewritten by dispatcher");

  JsonObject original=new JsonObject();int[] effectCalls={0};
  try{NativeBlazeEscort.inputAttempt(original,()->{effectCalls[0]++;throw new IllegalStateException("effect then exception");},()->true);throw new AssertionError("effect exception missing");}
  catch(IllegalStateException expected){dispatch(effectCalls[0]==1,"actual inputAttempt effect invoked exactly once");}
  dispatch(original.get("unknown_outcome").getAsBoolean()&&original.get("requires_handoff").getAsBoolean(),"actual production inputAttempt retains original UNKNOWN");
  dispatch(!NativeBlazeEscort.dispatchInFlight(),"inputAttempt exits dispatch stack after throw, not evidence of physical release");
  JsonObject unknownCopy=original.deepCopy();Host unknown=new Host();unknown.receipt=false;
  ReactiveGuardDispatch.tick(unknown);dispatch(unknown.starts==0,"effect uncertainty plus absent release proof cannot start");
  unknown.receipt=true;ReactiveGuardDispatch.tick(unknown);
  dispatch(unknown.starts==1&&effectCalls[0]==1,"new independently released protection does not replay uncertain original effect");
  dispatch(original.equals(unknownCopy),"original UNKNOWN/handoff preserved after separate defense");

  for(String barrier:List.of("cleanup","dispatch","nonneutral","missing_receipt")){
   Host blocked=new Host();
   if(barrier.equals("cleanup"))blocked.noCleanup=false;
   if(barrier.equals("dispatch"))blocked.noDispatch=false;
   if(barrier.equals("nonneutral"))blocked.neutral=false;
   if(barrier.equals("missing_receipt"))blocked.receipt=false;
   ReactiveGuardDispatch.tick(blocked);
   dispatch(blocked.starts==0&&"physical_release_not_proven".equals(blocked.waitReason),"physical barrier "+barrier);
  }
  Host foreign=new Host();foreign.owner="foreign";foreign.interrupt=false;ReactiveGuardDispatch.tick(foreign);
  dispatch(foreign.cancels==0&&foreign.starts==0&&foreign.physicalReads==0,"foreign/noninterruptible owner preserved");
  Host cancel=new Host();cancel.owner="original-build";cancel.interrupt=true;cancel.noCleanup=false;
  ReactiveGuardDispatch.tick(cancel);
  dispatch(cancel.cancels==1&&cancel.starts==0&&cancel.physicalReads==0,"successful cancellation never starts in same callback stack");
  dispatch(cancel.events.equals(List.of("owner","interrupt","cancel:original-build","wait:original_cancelled_wait_cleanup")),"cancel exact original and wait ordering");
  ReactiveGuardDispatch.tick(cancel);dispatch(cancel.starts==0&&cancel.cancels==1,"next tick still blocks unfinished cleanup");
  cancel.noCleanup=true;ReactiveGuardDispatch.tick(cancel);dispatch(cancel.starts==1&&cancel.cancels==1,"later released tick starts exactly one successor");
  Host denied=new Host();denied.owner="original";denied.interrupt=true;denied.allowCancel=false;ReactiveGuardDispatch.tick(denied);
  dispatch(denied.owner.equals("original")&&denied.starts==0&&denied.physicalReads==0,"cancel false never starts");
  dispatch("active_owner_not_interruptible".equals(denied.waitReason),"cancel denial remains waiting");
  Host uncertain=new Host();uncertain.owner="original";uncertain.interrupt=true;uncertain.cancelThrows=true;
  try{ReactiveGuardDispatch.tick(uncertain);throw new AssertionError("missing cancel exception");}
  catch(IllegalStateException expected){dispatch(uncertain.starts==0&&uncertain.physicalReads==0,"cancel exception cannot fall through to start");}
  Host unavailable=new Host();unavailable.physicalThrows=true;
  try{ReactiveGuardDispatch.tick(unavailable);throw new AssertionError("missing physical exception");}
  catch(IllegalStateException expected){dispatch(unavailable.starts==0,"unavailable physical witness no start");}

  predicate(ReactiveDefensePolicy.physicalReady(true,true,true,true,true,false),"matching receipt can prove release even with old registry entry");
  predicate(ReactiveDefensePolicy.physicalReady(true,true,true,true,false,true),"genuinely empty registry");
  predicate(!ReactiveDefensePolicy.physicalReady(true,true,true,true,false,false),"nonempty no receipt denied");
  for(int gate=0;gate<4;gate++){boolean[] p={true,true,true,true};p[gate]=false;predicate(!ReactiveDefensePolicy.physicalReady(p[0],p[1],p[2],p[3],true,true),"hard physical gate "+gate);}
  predicate(ReactiveDefensePolicy.attackReady(true,true,2,3,.95,false),"real ready near attack");
  predicate(!ReactiveDefensePolicy.attackReady(false,true,2,3,1,false),"identity changed");
  predicate(!ReactiveDefensePolicy.attackReady(true,false,2,3,1,false),"no real ray");
  predicate(!ReactiveDefensePolicy.attackReady(true,true,2,3,.949,false),"cooldown not ready");
  predicate(!ReactiveDefensePolicy.attackReady(true,true,2,3,1,true),"using shield lowers before attack");
  predicate(!ReactiveDefensePolicy.attackReady(true,true,3.01,9,1,false),"reach capped3");
  predicate(!ReactiveDefensePolicy.attackReady(true,true,2.01,2,1,false),"actual shorter reach honored");
  predicate(!ReactiveDefensePolicy.attackReady(true,true,Double.NaN,3,1,false),"unknown distance denied");
  predicate(ReactiveDefensePolicy.clientDead(false,0),"nonremoved health0 death");
  predicate(!ReactiveDefensePolicy.clientDead(true,0),"removed not a death proof");
  predicate(!ReactiveDefensePolicy.clientDead(false,2),"alive health not death");
  predicate(!ReactiveDefensePolicy.clientDead(false,Double.NaN),"unknown health not death");
  predicate(!ReactiveDefensePolicy.clientDead(false,Double.POSITIVE_INFINITY),"nonfinite health not death");
  predicate(ReactiveDefensePolicy.trigger(true,true,true,false,16),"visible supported nearby trigger");
  predicate(ReactiveDefensePolicy.trigger(true,true,false,true,24),"known self-target farther trigger");
  predicate(!ReactiveDefensePolicy.trigger(true,true,false,false,2),"no visibility or target proof");
  predicate(!ReactiveDefensePolicy.trigger(true,true,true,false,16.01),"visible distance bound");
  predicate(!ReactiveDefensePolicy.trigger(true,true,false,true,24.01),"self-target distance bound");
  predicate(!ReactiveDefensePolicy.trigger(false,true,true,true,2),"unsupported not triggered");
  predicate(!ReactiveDefensePolicy.trigger(true,false,true,true,2),"dead not triggered");
  predicate(!ReactiveDefensePolicy.trigger(true,true,true,true,Double.NaN),"unknown distance not triggered");
  predicate(ReactiveDefensePolicy.priority("minecraft:zombie",2,true,true,true)>ReactiveDefensePolicy.priority("minecraft:skeleton",8,true,true,false),"hittable near target outranks distant archer");
  predicate(!ReactiveDefensePolicy.TYPES.contains("minecraft:enderman")&&ReactiveDefensePolicy.TYPES.size()==12,"closed explicit12-type set");

  if(args.length!=2)throw new IllegalArgumentException("requires actual ClientActions.java and NativeReactiveGuard.java paths");
  String actions=Files.readString(Path.of(args[0])),guard=Files.readString(Path.of(args[1]));
  int pre=actions.indexOf("private static void preTick()"),hook=actions.indexOf("NativeReactiveGuard.tick(mc);",pre),early=actions.indexOf("if (!context(mc,\"pre_tick\")) return;",pre);
  source(pre>=0&&hook>pre&&early>hook,"real idle tick hook precedes active-null context early return");
  int fall=actions.indexOf("NativeFallRescue.preTick(mc);",pre),observe=actions.indexOf("NativeThreatObservation.tick(mc);",pre);
  source(fall>pre&&fall<hook&&observe>pre&&observe<hook,"observer and priority hooks before guard");
  int actual=guard.indexOf("ReactiveGuardDispatch.tick(new ReactiveGuardDispatch.Host()");
  source(actual>=0&&guard.indexOf("if(a.child.running())return;")<actual&&guard.indexOf("if(a.child.running())return;")>=0,"real manager skips running child before dispatcher, not simulated as runtime proof");
  source(guard.contains("public void startNewProtection(){submit(mc,a);}")&&guard.contains("public boolean physicalReady(){return NativeReactiveGuard.physicalReady(mc);}"),"production manager delegates actual submission/physical witness to tested dispatcher");
  System.out.println("ReactiveGuardDispatchChecks PASS dispatcher="+dispatchChecks+" production_predicates="+predicateChecks+" source_hooks="+sourceChecks+"; fake physical host, real dispatcher/inputAttempt; no live AI/HTTP/game claimed");
 }
}
