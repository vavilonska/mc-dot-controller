package io.github.campione01.mineclientbridge;
/** Actual production injected-dispatch callees. A private test-only cleanup token
 * ensures refusal precedes all game access; no Minecraft instance is created. */
public final class FallRescueCleanupHeadChecks {
 static int checks;
 static void check(boolean value){checks++;if(!value)throw new AssertionError();}
 static void reject(Runnable run,String reason){checks++;try{run.run();throw new AssertionError("effect admitted");}
  catch(ClientActionRequest.Rejected expected){if(!reason.equals(expected.getMessage()))throw new AssertionError(expected);}}
 @SuppressWarnings("unchecked") public static void main(String[] args)throws Exception {
  var field=ScopedCombatDispatch.class.getDeclaredField("CLEANUP");field.setAccessible(true);
  ThreadLocal<Object> local=(ThreadLocal<Object>)field.get(null);
  var type=Class.forName("io.github.campione01.mineclientbridge.ScopedCombatDispatch$Cleanup");
  var constructor=type.getDeclaredConstructors()[0];constructor.setAccessible(true);
  local.set(constructor.newInstance(null,true));
  try {
   check(!ScopedCombatDispatch.beforeUse(null,null,false));
   check(!ScopedCombatDispatch.beforeUse(null,null,true));
   reject(()->ScopedCombatDispatch.beforeAttack(null,null),"scoped_combat_cleanup_nonrelease_effect");
   reject(()->ScopedCombatDispatch.packet(null),"scoped_combat_cleanup_nonrelease_packet");
  } finally {local.remove();}
  check(local.get()==null);
  // Test-only constructor-free instance: exercise the actual lifetime adapter without a game.
  var unsafeField=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");unsafeField.setAccessible(true);
  var unsafe=(sun.misc.Unsafe)unsafeField.get(null);
  var guard=(ScopedCombat)unsafe.allocateInstance(ScopedCombat.class);guard.markFallPreempted();
  var body=new com.google.gson.JsonObject();
  var request=new ClientActionRequest("old","combat_entity",30000,java.util.List.of(),null,null,null,-1,false,false,-1,-1,0,null,body);
  var entry=new ActionRegistry.Entry(request);
  var scopeField=ClientActions.class.getDeclaredField("FALL_CLEANUP");scopeField.setAccessible(true);
  var scope=(FallRescueCleanupScope)scopeField.get(null);Object owner=new Object();
  check(!ClientActions.hasRuntimeAction());
  var token=scope.open(owner,guard,entry,()->true);
  check(ClientActions.terminalCombatCleanup(guard,entry));scope.close(token);
  check(!ClientActions.terminalCombatCleanup(guard,entry));
  var foreign=scope.open(new Object(),new Object(),new ActionRegistry.Entry(request),()->true);
  check(!ClientActions.terminalCombatCleanup(guard,entry));scope.close(foreign);
  System.out.println("production cleanup HEAD/packet/lifetime refusal checks="+checks);
 }
}
