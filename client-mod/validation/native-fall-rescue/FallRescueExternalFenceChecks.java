package io.github.campione01.mineclientbridge;
/** Pure production callback/arbiter fences; no game class initialization. */
public final class FallRescueExternalFenceChecks {
 static int checks;static void ok(boolean b){checks++;if(!b)throw new AssertionError();}
 public static void main(String[] args){
  for(int mode=0;mode<5;mode++){
   var arbiter=new SingleInputArbiter();var lease=arbiter.claim("original");var operations=new FallRescueFence();long revision=operations.stamp();boolean[] live={true};int m=mode;
   boolean allowed=FallRescueFence.afterHook(()->{if(m==1)arbiter.stop();if(m==2){arbiter.stop();arbiter.claim("replacement");}if(m==3)live[0]=false;if(m==4)operations.changed();return true;},
       ()->arbiter.owns(lease)&&operations.stamp()==revision&&live[0]);
   ok(allowed==(mode==0));
  }
  var arbiter=new SingleInputArbiter();arbiter.quarantine("unknown");
  ok(!FallRescueFence.afterHook(()->true,()->!arbiter.blocked()));ok(arbiter.quarantined());
  var op=new FallRescueFence();long stamp=op.stamp();op.changed();boolean rejected=false;try{op.commit(stamp);}catch(IllegalStateException expected){rejected=true;}ok(rejected);
  Object oldArm=new Object(),newArm=new Object(),oldEpisode=new Object(),newEpisode=new Object();
  ok(FallRescueFence.sameContext(oldArm,1,oldEpisode,oldArm,1,oldEpisode));
  ok(!FallRescueFence.sameContext(oldArm,1,oldEpisode,newArm,3,newEpisode));
  ok(!FallRescueFence.sameContext(oldArm,1,oldEpisode,oldArm,2,oldEpisode));
  ok(!FallRescueFence.sameContext(oldArm,1,null,oldArm,1,newEpisode));
  var replacementArbiter=new SingleInputArbiter();var original=replacementArbiter.claim("old");replacementArbiter.stop();var replacement=replacementArbiter.claim("new");
  if(FallRescueFence.sameContext(oldArm,1,oldEpisode,newArm,3,newEpisode))replacementArbiter.stop();
  ok(replacementArbiter.owns(replacement));ok(!replacementArbiter.owns(original));
  System.out.println("external query callback fences: "+checks+" passed");
 }
}
