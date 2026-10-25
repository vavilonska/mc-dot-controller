package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

/** Actual release-context policy and registry, fake context identities; no game or input. */
public final class ReactiveRespawnLifecycleChecks {
 private static int checks,hooks;
 private static void yes(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
 private static void hook(boolean value,String message){hooks++;if(!value)throw new AssertionError(message);}
 private static ReactivePhysicalRelease.Context context(Object player,Object world,Object server){return new ReactivePhysicalRelease.Context(player,world,server,"session","generation","player-uuid");}
 private static ActionRegistry.Entry original(ActionRegistry registry,boolean unknown){
  JsonObject b=new JsonObject();b.addProperty("action_id",UUID.randomUUID().toString());b.addProperty("action","break_block");
  JsonObject target=new JsonObject();target.addProperty("x",0);target.addProperty("y",64);target.addProperty("z",9);b.add("target",target);
  var entry=registry.begin(ClientActionRequest.parse(b));
  if(unknown){entry.result.addProperty("unknown_outcome",true);entry.result.addProperty("requires_handoff",true);entry.result.addProperty("effect_outcome","unknown");}
  registry.finishAfterCleanup("failed",unknown?"effect_uncertain":"target_not_in_reach_or_visible",true);
  return entry;
 }
 private static void caseOf(boolean unknown){
  Object oldPlayer=new Object(),newPlayer=new Object(),world=new Object(),server=new Object();
  ActionRegistry registry=new ActionRegistry();var entry=original(registry,unknown);JsonObject original=entry.json(false).deepCopy();
  var old=context(oldPlayer,world,server);var fresh=context(newPlayer,world,server);
  var receipt=new ReactivePhysicalRelease(entry,old,17,true);
  yes(receipt.basis(entry,17,old,false,true)==ReactivePhysicalRelease.Basis.SAME_PLAYER,"unchanged context still ready");
  yes(receipt.basis(entry,17,fresh,true,true)==ReactivePhysicalRelease.Basis.RELEASED_DEAD_PLAYER_REPLACED,"actual old bug: released dead LocalPlayer replacement accepted");
  for(int i=0;i<5;i++)yes(receipt.basis(entry,17,fresh,true,true)!=ReactivePhysicalRelease.Basis.NONE,"repeated read is stable and does not require synthetic input");
  yes(receipt.context==old&&receipt.physical&&receipt.revision==17,"original physical receipt never rewritten as new release");
  yes(original.equals(entry.json(false))&&registry.get(entry.request.id())==entry,"original action history preserved exactly");
  if(unknown)yes(entry.result.get("unknown_outcome").getAsBoolean()&&entry.result.get("effect_outcome").getAsString().equals("unknown"),"effect UNKNOWN is not input uncertainty and remains UNKNOWN");
  yes(receipt.basis(entry,17,fresh,false,true)==ReactivePhysicalRelease.Basis.NONE,"replacing a still-alive player does not imply respawn");
  yes(receipt.basis(entry,17,fresh,true,false)==ReactivePhysicalRelease.Basis.NONE,"unavailable successor is not ready");
  yes(receipt.basis(entry,18,fresh,true,true)==ReactivePhysicalRelease.Basis.NONE,"intervening ownership revision blocks stale receipt");
  yes(receipt.basis(new Object(),17,fresh,true,true)==ReactivePhysicalRelease.Basis.NONE,"another original action cannot borrow receipt");
  yes(new ReactivePhysicalRelease(entry,old,17,false).basis(entry,17,fresh,true,true)==ReactivePhysicalRelease.Basis.NONE,"unconfirmed physical release cannot be reset by respawn");
  yes(new ReactivePhysicalRelease(entry,null,17,true).basis(entry,17,fresh,true,true)==ReactivePhysicalRelease.Basis.NONE,"absent old context not release proof");
  for(var wrong:new ReactivePhysicalRelease.Context[]{context(newPlayer,new Object(),server),context(newPlayer,world,new Object()),
      new ReactivePhysicalRelease.Context(newPlayer,world,server,"other-session","generation","player-uuid"),
      new ReactivePhysicalRelease.Context(newPlayer,world,server,"session","other-generation","player-uuid"),
      new ReactivePhysicalRelease.Context(newPlayer,world,server,"session","generation","other-player"),
      new ReactivePhysicalRelease.Context(null,world,server,"session","generation","player-uuid"),null})
   yes(receipt.basis(entry,17,wrong,true,true)==ReactivePhysicalRelease.Basis.NONE,"changed or absent context cannot inherit prior release");
  boolean matching=receipt.basis(entry,17,fresh,true,true)!=ReactivePhysicalRelease.Basis.NONE;
  yes(ReactiveDefensePolicy.physicalReady(true,true,true,true,matching,false),"released old player plus neutral idle fresh context ready");
  for(int i=0;i<4;i++){boolean[] gates={true,true,true,true};gates[i]=false;yes(!ReactiveDefensePolicy.physicalReady(gates[0],gates[1],gates[2],gates[3],matching,false),"active/dispatch/cleanup/nonneutral barrier survives respawn "+i);}
  var direct=new ReactiveDefensePolicy.DirectFence();int[] calls={0};
  try{direct.call(()->{calls[0]++;throw new IllegalStateException("dispatched_unconfirmed");},()->true);}catch(IllegalStateException expected){}
  yes(direct.blocks()&&calls[0]==1,"uncertain direct effect remains blocked, never replayed");
  yes(!(!direct.blocks()&&ReactiveDefensePolicy.physicalReady(true,true,true,true,matching,false)),"respawn receipt cannot override direct effect fence");
  yes(original.equals(entry.json(false)),"all lifecycle reads leave exact original history intact");
 }
 public static void main(String[] args)throws Exception {
  caseOf(false);caseOf(true);
  String guard=Files.readString(Path.of(args[0]));
  hook(guard.contains("releaseBasis(mc)!=ReactivePhysicalRelease.Basis.NONE"),"native readiness consumes actual tested lifecycle policy");
  hook(guard.contains("return !directFence.blocks()&&ReactiveDefensePolicy.physicalReady(ClientActions.reactiveNoOwner(),ClientActions.reactiveNoDispatch(),ClientActions.reactiveNoCleanup(),neutral(mc)"),"native physical barriers kept");
  hook(guard.contains("Float.isFinite(old.getHealth())&&old.getHealth()<=0")&&guard.contains("mc.player!=null&&mc.player.isAlive()"),"native old death and fresh alive evidence is explicit");
  hook(guard.contains("l==null||l!=mc.level?null:WorldGeneration.current(l)"),"obsolete-level cleanup cannot rotate the current world generation");
  hook(guard.contains("stop(!a.same(mc)?\"context_changed\":\"death\")")&&guard.contains("require(physicalReady(mc),\"defense_physical_owner_not_released\");arm=new Arm(mc,b,c);"),"death stops prior arm; separate explicit arm required");
  hook(guard.contains("r.addProperty(\"current_context_basis\",releaseBasis(Minecraft.getInstance()).name().toLowerCase(java.util.Locale.ROOT))"),"status distinguishes lifecycle basis from original physical release");
  System.out.println("ReactiveRespawnLifecycleChecks PASS policy_registry="+checks+" source_hooks="+hooks+"; fake context identities, actual immutable release policy; live respawn NOT_RUN");
 }
}
