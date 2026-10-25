package io.github.campione01.mineclientbridge;
import java.lang.reflect.*;import java.util.function.LongSupplier;
import net.minecraft.network.protocol.game.ServerboundInteractPacket;
import static io.github.campione01.mineclientbridge.TargetActionEffectBudget.Effect;
/** Actual production hook methods; controlled fence clock and explicit engine doubles. */
public final class TargetActionDeadlineChecks {
 static int checks;static void ok(boolean b){checks++;if(!b)throw new AssertionError("check "+checks);}
 static RuntimeException denied(Runnable body){try{body.run();throw new AssertionError("accepted");}catch(RuntimeException e){return e;}}
 static Object field(Object owner,String name){try{Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(owner);}catch(Exception e){throw new AssertionError(e);}}
 static Object call(){try{Field f=ScopedTargetDispatch.class.getDeclaredField("CALL");f.setAccessible(true);return ((ThreadLocal<?>)f.get(null)).get();}catch(Exception e){throw new AssertionError(e);}}
 static CombatCallbackFence controlled(ScopedTargetAction g,long[] time,boolean cleanup){
  Object c=call();CombatCallbackFence actual=(CombatCallbackFence)field(c,"fence");ok((boolean)field(actual,"actionBound")==!cleanup);
  long captured=(long)field(actual,"actionDeadline");if(!cleanup)ok(captured==g.deadline);
  CombatCallbackFence f=cleanup?new CombatCallbackFence(()->ClientActions.terminalTargetCleanup(g,g.entry),()->time[0],()->g.level.tick)
   :CombatCallbackFence.forAction(()->ClientActions.ownsScopedTarget(g,g.entry),()->time[0],()->g.level.tick,captured);
  try{Field slot=c.getClass().getDeclaredField("fence");slot.setAccessible(true);slot.set(c,f);}catch(Exception e){throw new AssertionError(e);}return f;
 }
 static ScopedTargetAction fresh(){BridgeLog.LOGGER.records.clear();BridgeLog.LOGGER.fail=false;BridgeLog.LOGGER.onWarn=()->{};return new ScopedTargetAction(false,false);}
 static void packet(){var p=new ServerboundInteractPacket();ScopedTargetDispatch.packet(p);ScopedTargetDispatch.send(p);}
 static void local(ScopedTargetAction g){ScopedTargetDispatch.beforeAttack(g.player,g.target,true);ScopedTargetDispatch.beforeMeleeSweep(g.player,false);ScopedTargetDispatch.beforeMeleeImpact(g.player,g.target);ScopedTargetDispatch.beforeMeleePostMutation(g.player);}
 static void reason(String expected){ok(BridgeLog.LOGGER.records.size()==1);ok(BridgeLog.LOGGER.records.get(0)[3].equals(expected));}
 public static void main(String[] ignored){
  // The exact observed 51.446713ms is valid under the original five-second action budget.
  for(long duration:new long[]{50_000_001L,51_446_713L,500_000_000L,4_999_999_999L}){
   var g=fresh();long start=System.nanoTime();g.deadline=start+5_000_000_000L;long[] time={start};
   ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{controlled(g,time,false);ScopedTargetDispatch.beforeAttack(g.player,g.target,false);packet();time[0]=start+duration;local(g);});
   ok(!g.unknown&&g.budget.packets(Effect.MELEE)==1&&g.budget.local(Effect.MELEE)==1&&BridgeLog.LOGGER.records.isEmpty());
  }
  // Exact original deadline is exclusive, both before and after callback-backed validation.
  for(boolean after:new boolean[]{false,true}){var g=fresh();long start=System.nanoTime();long original=start+5_000_000_000L;g.deadline=original;long[] time={start};
   denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{controlled(g,time,false);if(after)g.finalHook=()->time[0]=original;else time[0]=original;packet();}));
   ok(g.unknown&&g.budget.packets(Effect.MELEE)==0&&g.budget.local(Effect.MELEE)==0);reason("ACTION_DEADLINE_EXPIRED");
  }
  // A copied future replacement cannot renew the captured original deadline.
  {var g=fresh();long start=System.nanoTime();long original=start+5_000_000_000L;g.deadline=original;long[] time={start};
   denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{controlled(g,time,false);g.deadline=Long.MAX_VALUE;time[0]=original;packet();}));reason("ACTION_DEADLINE_EXPIRED");ok(g.budget.packets(Effect.MELEE)==0);}
  // Charge-before-send remains explicit; expiry after packet charge prevents the simulated send.
  {var g=fresh();long start=System.nanoTime();g.deadline=start+5_000_000_000L;int[] connection={0};
   denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{Object c=call();CombatCallbackFence actual=(CombatCallbackFence)field(c,"fence");long original=(long)field(actual,"actionDeadline");
    try{Field f=c.getClass().getDeclaredField("fence");f.setAccessible(true);f.set(c,CombatCallbackFence.forAction(()->ClientActions.ownsScopedTarget(g,g.entry),()->g.budget.packets(Effect.MELEE)>0?original:start,()->g.level.tick,original));}catch(Exception e){throw new AssertionError(e);}packet();connection[0]++;}));
   reason("ACTION_DEADLINE_EXPIRED");ok(connection[0]==0&&g.budget.packets(Effect.MELEE)==1&&g.budget.local(Effect.MELEE)==0);ok(BridgeLog.LOGGER.records.get(0)[0].equals("FINAL_SEND")&&BridgeLog.LOGGER.records.get(0)[1].equals("PRE_SEND_CHARGED"));}
  // A later pre-local check still refuses expiry after a simulated send returned.
  {var g=fresh();long start=System.nanoTime();g.deadline=start+5_000_000_000L;long[] time={start};int[] connection={0};
   denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{controlled(g,time,false);packet();connection[0]++;time[0]=g.deadline;local(g);}));reason("ACTION_DEADLINE_EXPIRED");ok(connection[0]==1&&g.budget.packets(Effect.MELEE)==1&&g.budget.local(Effect.MELEE)==0);}
  for(String fault:new String[]{"clock","tick","owner","geometry","external","reentrant","duplicate"}){
   var g=fresh();long start=System.nanoTime();g.deadline=start+5_000_000_000L;long[] time={start};
   denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{controlled(g,time,false);time[0]=start+51_446_713L;
    switch(fault){case "clock"->time[0]=start-1;case "tick"->g.level.tick++;case "owner"->ClientActions.owner=new ScopedTargetAction(false,false);case "geometry"->g.finalHook=()->g.geometry++;case "external"->g.finalHook=()->g.externalIdle=false;case "reentrant"->g.hook=()->ScopedTargetDispatch.beforeAttack(g.player,g.target,false);default->{}}
    packet();if(fault.equals("duplicate"))packet();}));ok(g.unknown&&g.budget.local(Effect.MELEE)==0);if(!fault.equals("duplicate"))ok(g.budget.packets(Effect.MELEE)==0);
   if(fault.equals("clock"))reason("CLOCK_REGRESSED");if(fault.equals("tick"))reason("TICK_CHANGED");if(fault.equals("owner"))reason("OWNER_BEFORE_READS");if(fault.equals("reentrant"))reason("REENTRANT");
  }
  // DRAW and RELEASE are distinct ordinary production Calls sharing one original deadline.
  {var g=new ScopedTargetAction(true,false);BridgeLog.LOGGER.records.clear();long start=System.nanoTime();long original=start+5_000_000_000L;g.deadline=original;long[] time={start};g.player.stack.item=net.minecraft.world.item.Items.BOW;
   ScopedTargetDispatch.run(g.action,Effect.DRAW,()->{controlled(g,time,false);time[0]=start+51_446_713L;
    ScopedTargetDispatch.beforeUse(g.player,net.minecraft.world.InteractionHand.MAIN_HAND,false,false);ScopedTargetDispatch.beforeUse(g.player,net.minecraft.world.InteractionHand.MAIN_HAND,false,true);
    ScopedTargetDispatch.beforeStartUseMutation(g.player,net.minecraft.world.InteractionHand.MAIN_HAND,g.player.stack,72000);g.player.using=true;
    var p=new net.minecraft.network.protocol.game.ServerboundUseItemPacket();ScopedTargetDispatch.packet(p);ScopedTargetDispatch.send(p);});
   ok(g.budget.local(Effect.DRAW)==1&&g.budget.packets(Effect.DRAW)==1&&!g.unknown);time[0]=original-1;
   denied(()->ScopedTargetDispatch.run(g.action,Effect.BOW_RELEASE,()->{controlled(g,time,false);time[0]=original;ScopedTargetDispatch.beforeRelease(g.player,false);}));
   reason("ACTION_DEADLINE_EXPIRED");ok(g.unknown&&g.budget.local(Effect.BOW_RELEASE)==0&&g.budget.packets(Effect.BOW_RELEASE)==0&&g.deadline==original);
  }
  // Cleanup remains release-only, exact-owner and 50ms, even after ordinary action expiry.
  for(long elapsed:new long[]{50_000_000L,50_000_001L}){
   var g=new ScopedTargetAction(true,false);BridgeLog.LOGGER.records.clear();g.deadline=0;ClientActions.cleanup=g;g.player.using=true;g.player.stack.item=net.minecraft.world.item.Items.BOW;g.budget.reserve(Effect.DRAW);g.budget.chargeLocal(Effect.DRAW);g.budget.chargePacket(Effect.DRAW);long[] time={0};
   Runnable cleanup=()->ScopedTargetDispatch.cleanup(g.action,Effect.ABORT,()->{controlled(g,time,true);time[0]=elapsed;ScopedTargetDispatch.beforeStopUsing(g.player);ScopedTargetDispatch.beforeStopMutation(g.player);g.player.using=false;});
   if(elapsed==50_000_000L){cleanup.run();ok(g.budget.local(Effect.ABORT)==1&&!g.player.using);}else{denied(cleanup);reason("LIFETIME_EXPIRED");ok(g.budget.local(Effect.ABORT)==0);}ClientActions.cleanup=null;
  }
  pureDeadline();System.out.println("TargetActionDeadlineChecks passed "+checks+" checks; production hook methods, explicit engine doubles, immutable original deadline");
 }
 static void pureDeadline(){
  long[] now={100};long deadline=1_000_000_100L;boolean[] owner={true};long[] tick={7};
  var first=CombatCallbackFence.forAction(()->owner[0],()->now[0],()->tick[0],deadline);now[0]=deadline-1;first.raw();ok(first.failure()==CombatCallbackFence.Failure.NONE);
  var later=CombatCallbackFence.forAction(()->owner[0],()->now[0],()->tick[0],deadline);now[0]=deadline;denied(later::raw);ok(later.failure()==CombatCallbackFence.Failure.ACTION_DEADLINE_EXPIRED);now[0]=100;denied(later::raw);ok(later.failure()==CombatCallbackFence.Failure.ACTION_DEADLINE_EXPIRED);
  now[0]=deadline;var expired=CombatCallbackFence.forAction(()->true,()->now[0],()->7,deadline);denied(expired::raw);ok(expired.failure()==CombatCallbackFence.Failure.ACTION_DEADLINE_EXPIRED);
  now[0]=100;boolean[] mutate={false};var after=CombatCallbackFence.forAction(()->owner[0],()->now[0],()->{if(mutate[0])owner[0]=false;return 7;},deadline);mutate[0]=true;denied(after::raw);ok(after.failure()==CombatCallbackFence.Failure.OWNER_AFTER_READS);
  owner[0]=true;var closed=CombatCallbackFence.forAction(()->true,()->100,()->7,deadline);closed.close();denied(closed::raw);ok(closed.failure()==CombatCallbackFence.Failure.CLOSED);
  var futureClock=CombatCallbackFence.forAction(()->true,()->now[0],()->7,deadline);now[0]=Long.MAX_VALUE;denied(futureClock::raw);ok(futureClock.failure()==CombatCallbackFence.Failure.ACTION_DEADLINE_EXPIRED);
 }
}
