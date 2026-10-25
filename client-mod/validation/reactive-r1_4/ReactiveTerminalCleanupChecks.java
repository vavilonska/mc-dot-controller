package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
/** Real registry/scope and production early-terminal seam; fake cleanup callback, not a Minecraft instance. */
public final class ReactiveTerminalCleanupChecks {
 static int checks,hooks;static void yes(boolean b){checks++;if(!b)throw new AssertionError("check "+checks);}
 static ClientActionRequest request(String action){JsonObject j=new JsonObject();j.addProperty("action_id",UUID.randomUUID().toString());j.addProperty("action",action);JsonObject p=new JsonObject();p.addProperty("x",0);p.addProperty("y",64);p.addProperty("z",7);if(action.equals("place_block")){j.add("support",p);j.addProperty("face","up");}else j.add("target",p);return ClientActionRequest.parse(j);}
 static void scoped(String action,String status,boolean priorUnknown,boolean cleanupThrows){
  ActionRegistry r=new ActionRegistry();var e=r.begin(request(action));Object runtime=new Object();var s=new ScopedTerminalCleanupScope();var token=s.enter(runtime,e,7);int[] called={0,0};
  if(priorUnknown){e.result.addProperty("dispatched",true);e.result.addProperty("unknown_outcome",true);e.result.addProperty("requires_handoff",true);}JsonObject original=e.result.deepCopy();
  boolean managed=ClientActions.beginTerminalCleanup(false,runtime,runtime,()->{called[0]++;r.finish(status,"legacy_early");});
  yes(managed);yes(called[0]==0);yes(r.active()==e);yes(s.bound(runtime,e,7,null,r.active()));yes(e.running());
  try{
   Runnable cleanup=()->{yes(s.bound(runtime,e,7,null,r.active()));yes(r.active()==e);called[1]++;if(cleanupThrows)throw new IllegalStateException("injected_cleanup_failure");};cleanup.run();
   yes(managed);r.finishAfterCleanup(status,action.equals("break_block")?"target_not_in_reach_or_visible":"placement_effect_unconfirmed",true);
  }catch(IllegalStateException expected){yes(expected.getMessage().equals("injected_cleanup_failure"));yes(r.active()==e);e.result.addProperty("unknown_outcome",true);e.result.addProperty("requires_handoff",true);r.finishAfterCleanup("failed","scoped_terminal_cleanup_unconfirmed",false);}
  yes(called[0]==0&&called[1]==1);yes(r.active()==null);yes(!e.running());yes(e.result.get("input_release_confirmed").getAsBoolean()==!cleanupThrows);
  if(priorUnknown){yes(e.result.get("unknown_outcome").getAsBoolean());yes(e.result.get("requires_handoff").getAsBoolean());yes(e.result.get("dispatched").getAsBoolean());for(String k:original.keySet())yes(e.result.get(k).equals(original.get(k)));}
  else if(!cleanupThrows){yes(!e.result.has("unknown_outcome"));yes(!e.result.has("requires_handoff"));}
  s.close(token);yes(!s.active());yes(r.get(e.request.id())==e);
 }
 public static void main(String[] args)throws Exception{
  scoped("break_block","failed",false,false);scoped("break_block","succeeded",false,false);scoped("place_block","failed",true,false);scoped("break_block","failed",false,true);
  ActionRegistry old=new ActionRegistry();var e=old.begin(request("break_block"));Object runtime=new Object();int[] n={0};
  yes(!ClientActions.beginTerminalCleanup(false,null,runtime,()->{n[0]++;old.finish("failed","target_not_in_reach_or_visible");}));yes(n[0]==1);yes(old.active()==null);yes(!e.result.has("input_release_confirmed"));yes(!e.result.has("unknown_outcome"));
  ActionRegistry repro=new ActionRegistry();var re=repro.begin(request("break_block"));var scope=new ScopedTerminalCleanupScope();var token=scope.enter(runtime,re,8);yes(scope.bound(runtime,re,8,null,repro.active()));repro.finish("failed","old_order_reproduced");yes(!scope.bound(runtime,re,8,null,repro.active()));scope.close(token);
  String source=Files.readString(Path.of(args[0]));String begin="managedCleanup=beginTerminalCleanup(managedCleanup,terminalCleanupOwner,a,()->ACTIONS.finish(earlyStatus,earlyReason));";
  if(!source.contains(begin+"\n        requireCleanupOwner(a);"))throw new AssertionError("production early-finish hook");hooks++;
  if(!source.contains("ACTIONS.finishAfterCleanup(status, reason, released);"))throw new AssertionError("production post-cleanup terminal");hooks++;
  if(!source.contains("terminalCleanupOwner=a;")||!source.contains("finally {terminalCleanupOwner=null;TERMINAL_CLEANUP.close(token);"))throw new AssertionError("scope lifecycle");hooks++;
  System.out.println("ReactiveTerminalCleanupChecks PASS registry_scope_production_seam="+checks+" source_hooks="+hooks+"; real Registry/Scope+actual early-finish seam, fake cleanup callback, full live ClientActions cleanup NOT_RUN");
 }
}
