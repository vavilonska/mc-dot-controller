package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;

/** Actual production direct-fence and receipt predicates. Fake identities only; no game/input. */
public final class ReactiveDirectReleaseChecks {
 private static int checks,hooks;
 private static void yes(boolean value,String why){checks++;if(!value)throw new AssertionError(why);}
 private static void hook(boolean value,String why){hooks++;if(!value)throw new AssertionError(why);}
 private static ReactivePhysicalRelease.Context context(Object p,Object l,Object s){return new ReactivePhysicalRelease.Context(p,l,s,"session","generation","uuid");}
 private static ReactiveDefensePolicy.DirectFence pending(){var f=new ReactiveDefensePolicy.DirectFence();f.call(()->1,()->true,()->false);yes(f.state().equals("awaiting_neutral"),"normal exact return waits only for neutrality");return f;}
 public static void main(String[] args)throws Exception {
  var immediate=new ReactiveDefensePolicy.DirectFence();int[] effects={0};
  yes(immediate.call(()->{effects[0]++;yes(immediate.blocks(),"effect stays fenced");return 7;},()->true,()->true)==7,"return unchanged");
  yes(!immediate.blocks()&&effects[0]==1&&immediate.pendingToken()==null,"immediate proven release");
  var later=pending();Object token=later.pendingToken();int[] polls={0};
  yes(!later.reconcile(new Object(),()->{polls[0]++;return true;}),"wrong token cannot probe/close");
  yes(polls[0]==0&&later.blocks(),"wrong proof not run");
  yes(!later.reconcile(token,()->false)&&later.blocks(),"still nonneutral remains pending");
  yes(later.reconcile(token,()->true)&&!later.blocks(),"next neutral sample closes without new effect");
  yes(!later.reconcile(token,()->{polls[0]++;return true;})&&polls[0]==0,"closed token single use");
  var replacement=pending();Object old=replacement.pendingToken();replacement.call(()->2,()->true,()->false);Object fresh=replacement.pendingToken();
  yes(old!=fresh&&!replacement.reconcile(old,()->true)&&replacement.blocks(),"new direct operation invalidates old proof token");
  yes(replacement.reconcile(fresh,()->true),"only fresh pending token closes");

  for(String failure:new String[]{"effect","binding_throw","binding_false","neutral_throw","reentry","proof_throw","proof_reentry"}){
   var f=new ReactiveDefensePolicy.DirectFence();int[] attempts={0};
   try{
    f.call(()->{attempts[0]++;if(failure.equals("effect"))throw new IllegalStateException("effect then exception");
      if(failure.equals("reentry"))try{f.call(()->0,()->true);}catch(IllegalStateException swallowed){}return 1;},
      ()->{if(failure.equals("binding_throw"))throw new IllegalStateException("binding unavailable");return !failure.equals("binding_false");},
      ()->{if(failure.equals("neutral_throw"))throw new IllegalStateException("neutral unavailable");return false;});
    if(failure.startsWith("proof_")){Object t=f.pendingToken();f.reconcile(t,()->{
      if(failure.equals("proof_throw"))throw new IllegalStateException("deferred proof failed");
      try{f.call(()->0,()->true);}catch(IllegalStateException swallowed){}return true;});}
   }catch(IllegalStateException expected){}
   yes(f.state().equals("dispatch_uncertain")&&f.blocks(),failure+" remains uncertain");
   Object t=f.pendingToken();yes(!f.reconcile(t,()->true),failure+" neutral/native terminal cannot clear uncertainty");
   f.call(()->{attempts[0]++;return 3;},()->true,()->true);
   yes(f.blocks()&&f.state().equals("dispatch_uncertain"),failure+" later normal call does not erase uncertainty");
   yes(attempts[0]==2,failure+" no original effect replay");
  }
  var flight=pending();Object flightOld=flight.pendingToken();
  flight.call(()->{yes(!flight.reconcile(flightOld,()->true),"in-flight terminal callback cannot clear");yes(flight.blocks(),"in-flight still fenced");return 1;},()->true,()->false);
  yes(flight.blocks()&&flight.pendingToken()!=flightOld,"in-flight callback leaves new operation pending");
  Object p=new Object(),l=new Object(),s=new Object(),entry=new Object(),latest=new Object();var c=context(p,l,s);
  yes(ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,entry,c,1075,null),"exact returned operation at now-neutral sample");
  yes(!ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,latest,c,1075,null),"entry mismatch at same revision");
  yes(!ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,entry,c,1074,null),"older revision cannot close");
  yes(!ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,entry,c,1076,null),"new revision without terminal proof cannot close");
  var terminal=new ReactivePhysicalRelease(latest,c,1245,true);
  yes(ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,latest,c,1245,terminal),"g1422→g1428 newer exact physical native cleanup closes pending");
  for(var bad:new ReactivePhysicalRelease[]{new ReactivePhysicalRelease(latest,c,1245,false),new ReactivePhysicalRelease(entry,c,1245,true),new ReactivePhysicalRelease(latest,c,1244,true),new ReactivePhysicalRelease(latest,null,1245,true),new ReactivePhysicalRelease(latest,context(new Object(),l,s),1245,true),null})
   yes(!ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,latest,c,1245,bad),"invalid native receipt cannot supersede pending");
  for(var wrong:new ReactivePhysicalRelease.Context[]{context(new Object(),l,s),context(p,new Object(),s),context(p,l,new Object()),new ReactivePhysicalRelease.Context(p,l,s,"other","generation","uuid"),new ReactivePhysicalRelease.Context(p,l,s,"session","other","uuid"),new ReactivePhysicalRelease.Context(p,l,s,"session","generation","other"),null}){
   yes(!ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,entry,wrong,1075,null),"changed direct context blocks exact deferred release");
   yes(!ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,latest,wrong,1245,terminal),"changed context blocks terminal supersession");
  }
  for(int gate=0;gate<4;gate++){
   var f=pending();Object t=f.pendingToken();boolean[] g={true,true,true,true};g[gate]=false;
   yes(!f.reconcile(t,()->ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,latest,c,1245,terminal)&&ReactiveDefensePolicy.physicalReady(g[0],g[1],g[2],g[3],true,false)),"owner/dispatch/cleanup/neutral barrier "+gate);
   yes(f.blocks(),"barrier retains pending "+gate);
  }
  // Actual dispatcher + actual direct fence reproduces the cancelled-owner -> separate child handoff.
  var f=pending();Object t=f.pendingToken();JsonObject unknown=new JsonObject();unknown.addProperty("unknown_outcome",true);unknown.addProperty("requires_handoff",true);JsonObject saved=unknown.deepCopy();
  class Host implements ReactiveGuardDispatch.Host {
   boolean owner=true;int cancellations,starts;String reason;
   public boolean hasOwner(){return owner;}public boolean interruptAllowed(){return true;}
   public boolean cancelExactOriginal(){cancellations++;owner=false;yes(f.reconcile(t,()->ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,latest,c,1245,terminal)),"actual later cleanup closes returned pending");return true;}
   public boolean physicalReady(){return !f.blocks()&&ReactiveDefensePolicy.physicalReady(!owner,true,true,true,terminal.basis(latest,1245,c,false,true)!=ReactivePhysicalRelease.Basis.NONE,false);}
   public void startNewProtection(){starts++;owner=true;}public void waiting(String why){reason=why;}
  }
  Host host=new Host();ReactiveGuardDispatch.tick(host);yes(host.starts==0&&host.cancellations==1,"no successor inside original cancel stack");
  ReactiveGuardDispatch.tick(host);yes(host.starts==1,"next released tick starts separate child");
  yes(unknown.equals(saved)&&terminal.revision==1245&&terminal.entry==latest&&terminal.context==c,"old effect UNKNOWN and exact receipt unchanged");
  var respawn=context(new Object(),l,s);yes(terminal.basis(latest,1245,respawn,true,true)==ReactivePhysicalRelease.Basis.RELEASED_DEAD_PLAYER_REPLACED&&!f.blocks(),"properly closed direct fence allows existing proven dead-player receipt after respawn");
  var notClosed=pending();yes(!notClosed.reconcile(notClosed.pendingToken(),()->ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,latest,respawn,1245,terminal))&&notClosed.blocks(),"respawn alone never clears direct pending");

  Object arm=new Object();
  yes(ReactiveDefensePolicy.resumeDirectPause(arm,arm,7,7,true,true),"exact proven direct release retires its own pause without ten-tick synthetic idle");
  for(int gate=0;gate<6;gate++){
   Object oldArm=arm,currentArm=arm;long oldIntent=7,currentIntent=7;boolean suspended=true,clear=true;
   if(gate==0)oldArm=null;if(gate==1)currentArm=new Object();if(gate==2)currentIntent=8;if(gate==3)oldIntent=6;if(gate==4)suspended=false;if(gate==5)clear=false;
   yes(!ReactiveDefensePolicy.resumeDirectPause(oldArm,currentArm,oldIntent,currentIntent,suspended,clear),"pause identity/intent/uncertain gate "+gate);
  }
  // Reproduce the observed e90 defect: returned input was released, but successor movement
  // kept neutral=false forever and hence the old user pause survived until endpoint settling.
  var movingFence=pending();Object mt=movingFence.pendingToken();
  boolean pause=true;yes(movingFence.reconcile(mt,()->true),"actual returned food release closes");
  if(ReactiveDefensePolicy.resumeDirectPause(arm,arm,7,7,pause,!movingFence.blocks()))pause=false;
  class MovingHost implements ReactiveGuardDispatch.Host {
   boolean owner=true,bodyNeutral=false;int starts,cancels;
   public boolean hasOwner(){return owner;}public boolean interruptAllowed(){return true;}
   public boolean physicalReady(){return !movingFence.blocks()&&ReactiveDefensePolicy.physicalReady(!owner,true,true,bodyNeutral,true,false);}
   public boolean cancelExactOriginal(){cancels++;owner=false;bodyNeutral=true;return true;}
   public void startNewProtection(){starts++;owner=true;}public void waiting(String why){}
  }
  MovingHost moving=new MovingHost();yes(!pause&&!moving.bodyNeutral,"released user's pause cleared even though later native owner moves");
  if(!pause)ReactiveGuardDispatch.tick(moving);yes(moving.cancels==1&&moving.starts==0,"moving follow preempted before settling; no same-stack child");
  ReactiveGuardDispatch.tick(moving);yes(moving.starts==1,"next tick child after exact movement cleanup");
  yes(!ReactiveDefensePolicy.resumeDirectPause(arm,arm,7,8,true,true),"later real physical input remains paused even after stale direct release");
  var held=pending();yes(!ReactiveDefensePolicy.resumeDirectPause(arm,arm,7,7,true,!held.blocks()),"still held returned direct input does not resume");
  var bad=new ReactiveDefensePolicy.DirectFence();try{bad.call(()->{throw new IllegalStateException();},()->true);}catch(IllegalStateException expected){}
  yes(!ReactiveDefensePolicy.resumeDirectPause(arm,arm,7,7,true,!bad.blocks()),"unknown callback never resumes pause");
  var inflightPause=new ReactiveDefensePolicy.DirectFence();inflightPause.call(()->{
   yes(!ReactiveDefensePolicy.resumeDirectPause(arm,arm,7,7,true,!inflightPause.blocks()),"in-flight callback cannot retire pause");return 1;},()->true);
  var terminalPause=pending();Object terminalToken=terminalPause.pendingToken();
  yes(terminalPause.reconcile(terminalToken,()->ReactiveDefensePolicy.directReleaseMatches(entry,c,1075,latest,c,1245,terminal)),"native terminal closes exact returned pending token");
  yes(!ReactiveDefensePolicy.resumeDirectPause(arm,arm,7,8,true,!terminalPause.blocks()),"same native terminal cannot retire a newer user intent");
  yes(ReactiveDefensePolicy.resumeDirectPause(arm,arm,7,7,true,!terminalPause.blocks()),"same native terminal retires only stored original intent");

  String guard=Files.readString(Path.of(args[0]));
  hook(guard.contains("tick++;reconcileDirectRelease(mc);Arm a=arm;if(a==null)return;"),"deferred observation runs even disarmed");
  hook(guard.contains("reconcileDirectRelease(mc);require(physicalReady(mc)"),"fresh explicit arm checks pending closure without fake input");
  hook(guard.contains("release=new ReactivePhysicalRelease(e,releaseContext(mc,p,l),revision,actual);\n  reconcileDirectRelease(mc);"),"native terminal receipt closes returned pending after existing cleanup boundary");
  hook(guard.contains("if(revision==pending.revision)release=new ReactivePhysicalRelease(latest,current,revision,true);"),"newer original native receipt kept exact");
  hook(guard.contains("ReactiveDefensePolicy.directReleaseMatches(pending.entry,pending.context,pending.revision,latest,current,revision,release)"),"native closure uses tested same-context revision predicate");
  hook(guard.contains("direct_input_release_state")&&guard.contains("pending_direct_ownership_revision"),"hidden direct fence observable");
  hook(guard.contains("&&ClientActions.reactiveNoOwner()&&ClientActions.reactiveNoCleanup()&&ClientActions.reactiveNoDispatch()&&neutral(mc)"),"no active/dispatch/cleanup/nonneutral bypass");
  hook(guard.contains("Arm pausedArm=arm;")&&guard.contains("long pauseIntent=pausedArm==null?-1:pausedArm.intentRevision;"),"capture same pre-call arm and post-return input intent");
  hook(guard.contains("resumeDirectPause(pending.pausedArm,pending.pauseIntent);")&&guard.contains("else resumeDirectPause(pausedArm,pauseIntent);return result;"),"immediate and deferred proven paths retire exact direct pause");
  hook(guard.contains("ReactiveDefensePolicy.resumeDirectPause(pausedArm,current,pauseIntent,current==null?-1:current.intentRevision,current!=null&&current.suspended,!directFence.blocks())"),"native pause resume consumes exact tested intent and live fence");
  hook(guard.contains("if(a.suspended){if(tick<a.pausedUntil||!neutral(mc))return;a.suspended=false;}"),"unproven/manual user pause behavior not weakened");
  System.out.println("ReactiveDirectReleaseChecks PASS policy_dispatch="+checks+" source_hooks="+hooks+"; observed g1422/g1428 ordering modeled with fake identities, no live game");
 }
}
