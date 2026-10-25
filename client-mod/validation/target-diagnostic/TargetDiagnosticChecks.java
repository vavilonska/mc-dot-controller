package io.github.campione01.mineclientbridge;
import java.lang.reflect.*;import java.util.*;import java.util.function.LongSupplier;
import net.minecraft.network.protocol.game.ServerboundInteractPacket;
import static io.github.campione01.mineclientbridge.TargetActionEffectBudget.Effect;
/** Production hook methods with controlled fence clock; engine/world are explicit test doubles. */
public final class TargetDiagnosticChecks {
 static int checks;static void ok(boolean b){checks++;if(!b)throw new AssertionError("check "+checks);}
 static RuntimeException denied(Runnable r){try{r.run();throw new AssertionError("accepted");}catch(RuntimeException e){return e;}}
 static Object call() {try {Field f=ScopedTargetDispatch.class.getDeclaredField("CALL");f.setAccessible(true);return ((ThreadLocal<?>)f.get(null)).get();}catch(Exception e){throw new AssertionError(e);}}
 static void clock(ScopedTargetAction g,LongSupplier now){try{Object c=call();Field f=c.getClass().getDeclaredField("fence");f.setAccessible(true);f.set(c,new CombatCallbackFence(()->ClientActions.ownsScopedTarget(g,g.entry),now,()->g.level.tick));}catch(Exception e){throw new AssertionError(e);}}
 static ScopedTargetAction fresh(){BridgeLog.LOGGER.records.clear();BridgeLog.LOGGER.fail=false;BridgeLog.LOGGER.onWarn=()->{};return new ScopedTargetAction(false,false);}
 static Object[] diagnostic(){ok(BridgeLog.LOGGER.records.size()==1);return BridgeLog.LOGGER.records.get(0);}
 static void row(String phase,String stage,String code,String fence,int packets,int local){Object[] d=diagnostic();ok(d.length==7);ok(d[0].equals(phase));ok(d[1].equals(stage));ok(d[2].equals(code));ok(d[3].equals(fence));ok(((Long)d[4])>=-1&&((Long)d[4])<=1_000_000_000L);ok(d[5].equals(packets));ok(d[6].equals(local));}
 static void packet(){var p=new ServerboundInteractPacket();ScopedTargetDispatch.packet(p);ScopedTargetDispatch.send(p);}
 public static void main(String[] args){
  // Same counter pair can mean the final send fence threw BEFORE actual Connection.send.
  {var g=fresh();int[] connection={0};denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
   clock(g,()->g.budget.packets(Effect.MELEE)>0?CombatCallbackFence.MAX_NANOS+1:0);
   ScopedTargetDispatch.beforeAttack(g.player,g.target,false);packet();connection[0]++;
  }));ok(connection[0]==0&&g.unknown);row("FINAL_SEND","PRE_SEND_CHARGED","CALLBACK_FENCE","LIFETIME_EXPIRED",1,0);}
  // Or it can mean Connection.send returned, then the pre-local guard timed out.
  {var g=fresh();long[] time={0};int[] connection={0};denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
   clock(g,()->time[0]);ScopedTargetDispatch.beforeAttack(g.player,g.target,false);packet();connection[0]++;
   time[0]=CombatCallbackFence.MAX_NANOS+1;ScopedTargetDispatch.beforeAttack(g.player,g.target,true);
  }));ok(connection[0]==1&&g.unknown);row("ATTACK_LOCAL_ENTRY","CHECK_BEGIN","CALLBACK_FENCE","LIFETIME_EXPIRED",1,0);}
  {var g=fresh();long[] time={0};denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
   clock(g,()->time[0]);packet();ScopedTargetDispatch.beforeAttack(g.player,g.target,true);ScopedTargetDispatch.beforeMeleeSweep(g.player,false);
   time[0]=CombatCallbackFence.MAX_NANOS+1;ScopedTargetDispatch.beforeMeleeImpact(g.player,g.target);
  }));ok(g.unknown);row("MELEE_IMPACT","CHECK_BEGIN","CALLBACK_FENCE","LIFETIME_EXPIRED",1,0);}
  for(boolean tick:new boolean[]{false,true}){var g=fresh();denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
   clock(g,()->0);packet();if(tick)g.level.tick++;else g.valid=false;ScopedTargetDispatch.beforeAttack(g.player,g.target,true);
  }));ok(g.unknown);row("ATTACK_LOCAL_ENTRY","CHECK_BEGIN","CALLBACK_FENCE",tick?"TICK_CHANGED":"OWNER_BEFORE_READS",1,0);}
  {var g=fresh();ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{
   clock(g,()->0);ScopedTargetDispatch.beforeAttack(g.player,g.target,false);packet();ScopedTargetDispatch.beforeAttack(g.player,g.target,true);
   ScopedTargetDispatch.beforeMeleeSweep(g.player,false);ScopedTargetDispatch.beforeMeleeImpact(g.player,g.target);ScopedTargetDispatch.beforeMeleePostMutation(g.player);
  });ok(!g.unknown&&g.budget.local(Effect.MELEE)==1&&g.budget.packets(Effect.MELEE)==1&&BridgeLog.LOGGER.records.isEmpty());}
  {var g=fresh();denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{clock(g,()->0);g.budget.reserve(Effect.MELEE);}));row("CALL_ENTRY","BODY","RESERVATION_BUDGET","NONE",0,0);}
  {var g=fresh();RuntimeException original=new IllegalStateException("secret-token-value must never appear");ok(denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{throw original;}))==original);row("CALL_ENTRY","BODY","OTHER_ILLEGAL_STATE","NONE",0,0);for(Object value:diagnostic())ok(!value.toString().contains("secret-token"));}
  {var g=fresh();int[] reads={0};RuntimeException original=new IllegalStateException(){public String getMessage(){reads[0]++;throw new AssertionError("untrusted message reader");}};ok(denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{throw original;}))==original);ok(reads[0]==0);row("CALL_ENTRY","BODY","OTHER_RUNTIME_EXCEPTION","NONE",0,0);}
  {var g=fresh();BridgeLog.LOGGER.fail=true;BridgeLog.LOGGER.onWarn=()->ok(g.unknown);RuntimeException original=new IllegalStateException("private");ok(denied(()->ScopedTargetDispatch.run(g.action,Effect.MELEE,()->{throw original;}))==original);ok(g.unknown);BridgeLog.LOGGER.fail=false;}
  fenceReasons();System.out.println("TargetDiagnosticChecks passed "+checks+" checks; production hooks/controlled clock, test-double engine; no live-cause attribution");
 }
 static void fenceReasons(){
  long[] time={0},tick={1};boolean[] owner={true};
  var limit=new CombatCallbackFence(()->owner[0],()->time[0],()->tick[0]);time[0]=CombatCallbackFence.MAX_NANOS;limit.raw();ok(limit.failure()==CombatCallbackFence.Failure.NONE);time[0]++;denied(limit::raw);ok(limit.failure()==CombatCallbackFence.Failure.LIFETIME_EXPIRED);long observed=limit.sampledElapsed();owner[0]=false;denied(limit::raw);ok(limit.failure()==CombatCallbackFence.Failure.LIFETIME_EXPIRED&&limit.sampledElapsed()==observed);
  owner[0]=true;time[0]=100;var regressed=new CombatCallbackFence(()->true,()->time[0],()->1);time[0]--;denied(regressed::raw);ok(regressed.failure()==CombatCallbackFence.Failure.CLOCK_REGRESSED);
  var reentrant=new CombatCallbackFence(()->true,()->0,()->1);denied(()->reentrant.check(()->reentrant.check(()->{})));ok(reentrant.failure()==CombatCallbackFence.Failure.REENTRANT);
  var closed=new CombatCallbackFence(()->true,()->0,()->1);closed.close();denied(closed::raw);ok(closed.failure()==CombatCallbackFence.Failure.CLOSED);
  boolean[] mutate={false};owner[0]=true;var after=new CombatCallbackFence(()->owner[0],()->0,()->{if(mutate[0])owner[0]=false;return 1;});mutate[0]=true;denied(after::raw);ok(after.failure()==CombatCallbackFence.Failure.OWNER_AFTER_READS);
  var callback=new CombatCallbackFence(()->true,()->0,()->1);RuntimeException raw=new IllegalStateException("private");ok(denied(()->callback.check(()->{throw raw;}))==raw);ok(callback.failure()==CombatCallbackFence.Failure.CALLBACK_EXCEPTION);
  time[0]=0;var huge=new CombatCallbackFence(()->true,()->time[0],()->1);time[0]=Long.MAX_VALUE;denied(huge::raw);ok(huge.sampledElapsed()==1_000_000_000L);
 }
}
