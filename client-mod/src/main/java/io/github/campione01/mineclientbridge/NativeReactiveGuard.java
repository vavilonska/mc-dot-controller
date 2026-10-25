package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.server.MinecraftServer;

/** Explicit persistent consent, not an input owner. Only registry children perform effects. */
final class NativeReactiveGuard {
 record Config(int weaponSlot,boolean shield,boolean interrupt,Set<String> types,int episodeMs,int quietTicks,double lowHealth){}
 private static final class Arm {
  final String id,session,generation,dimension;final LocalPlayer player;final ClientLevel level;final MinecraftServer server;final Config config;final JsonObject original;final java.util.Map<String,ReactiveDefensePolicy.Stalled> stalled=new java.util.HashMap<>();
  String phase="ARMED",reason="explicit_arm",childId,protectedAfterId;JsonObject originalOutcome;ActionRegistry.Entry child;long pausedUntil,intentRevision,navigationEpoch=NavigationPositionGuard.epoch();int episodes;boolean suspended;
  Arm(Minecraft mc,JsonObject body,Config config){id=ClientActionRequest.string(body,"arm_id");this.config=config;original=body.deepCopy();session=ClientActions.session();player=mc.player;level=mc.level;server=mc.getSingleplayerServer();generation=WorldGeneration.current(level);dimension=level.dimension().location().toString();}
  boolean same(Minecraft mc){return mc.player==player&&mc.level==level&&mc.getSingleplayerServer()==server&&server!=null&&!server.isPublished()&&session.equals(ClientActions.session())&&generation.equals(WorldGeneration.current(level));}
 }
 private static final java.util.Map<String,Arm> retired=new java.util.LinkedHashMap<>();
 private static Arm arm;private static ReactivePhysicalRelease release;private static JsonObject last=new JsonObject();
 private static ClientActionRequest permit;private static Arm permitArm;private static boolean permitEntered,permitTainted;private static long permitRevision;
 private static long tick;private static final ReactiveDefensePolicy.DirectFence directFence=new ReactiveDefensePolicy.DirectFence();
 private record PendingDirect(Object token,Object entry,ReactivePhysicalRelease.Context context,long revision,Arm pausedArm,long pauseIntent){}
 private static PendingDirect pendingDirect;
 static Config config(JsonObject b){
  var fields=Set.of("arm_id","expected_world_generation","expected_player_uuid","expected_action_session","expected_dimension","weapon_slot","use_shield","interrupt_actions","target_types","episode_timeout_ms","quiet_ticks","low_health");
  require(fields.equals(b.keySet()),"defense_arm_closed_fields");
  for(String k:java.util.List.of("arm_id","expected_world_generation","expected_player_uuid","expected_action_session"))try{UUID.fromString(ClientActionRequest.string(b,k));}catch(IllegalArgumentException e){throw new ClientActionRequest.Rejected(400,"invalid_"+k);}
  int slot=ClientActionRequest.integer(b,"weapon_slot",-1),ms=ClientActionRequest.integer(b,"episode_timeout_ms",60000),quiet=ClientActionRequest.integer(b,"quiet_ticks",30);
  double low=number(b,"low_health");
  require(slot>=0&&slot<=8&&ms>=1000&&ms<=120000&&quiet>=10&&quiet<=100&&low>0&&low<20,"defense_config_bounds");
  require(b.has("target_types")&&b.get("target_types").isJsonArray(),"defense_target_types_required");Set<String> types=new HashSet<>();
  for(var v:b.getAsJsonArray("target_types")){require(v.isJsonPrimitive()&&v.getAsJsonPrimitive().isString()&&ReactiveDefensePolicy.TYPES.contains(v.getAsString()),"defense_target_type_unsupported");require(types.add(v.getAsString()),"duplicate_defense_target_type");}
  require(!types.isEmpty(),"defense_target_types_empty");
  return new Config(slot,ClientActionRequest.bool(b,"use_shield",true),ClientActionRequest.bool(b,"interrupt_actions",true),Set.copyOf(types),ms,quiet,low);
 }
 static JsonObject arm(JsonObject b){
  Minecraft mc=Minecraft.getInstance();Config c=config(b);
  Arm seen=retired.get(ClientActionRequest.string(b,"arm_id"));if(seen!=null){require(seen.original.equals(b),"defense_arm_id_payload_mismatch");JsonObject prior=json(seen);prior.addProperty("ok",true);prior.addProperty("armed",false);return prior;}
  if(arm!=null){require(arm.id.equals(b.get("arm_id").getAsString())&&arm.original.equals(b),"defense_already_armed");return status();}
  require(mc.player!=null&&mc.level!=null&&mc.player.isAlive()&&mc.screen==null&&mc.getSingleplayerServer()!=null&&!mc.getSingleplayerServer().isPublished(),"defense_live_private_context_required");
  require(b.get("expected_world_generation").getAsString().equals(WorldGeneration.current(mc.level))&&b.get("expected_player_uuid").getAsString().equals(mc.player.getUUID().toString())&&b.get("expected_action_session").getAsString().equals(ClientActions.session())&&ClientActionRequest.string(b,"expected_dimension").equals(mc.level.dimension().location().toString()),"defense_context_changed");
  NativeWorldBackup.requireNoSnapshot();NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();ExternalControllerGuard.requireIdle(mc);
  reconcileDirectRelease(mc);require(physicalReady(mc),"defense_physical_owner_not_released");arm=new Arm(mc,b,c);last=new JsonObject();return status();
 }
 static JsonObject disarm(JsonObject body){String id=ClientActionRequest.string(body,"arm_id");require(body.keySet().equals(Set.of("arm_id")),"defense_disarm_closed_fields");if(arm!=null)require(arm.id.equals(id),"defense_arm_id_changed");stop("explicit_disarm");return status();}
 static void stop(String reason){Arm a=arm;if(a==null)return;arm=null;a.intentRevision++;a.phase="DISARMED";a.reason=reason;if(a.child!=null)ClientActions.cancelReactiveChild(a.child,"defense_"+reason);last=json(a);retired.put(a.id,a);}
 static void userPause(String reason){Arm a=arm;if(a==null)return;a.intentRevision++;a.suspended=true;a.pausedUntil=tick+10;a.reason=reason;a.phase="PAUSED_USER";if(a.child!=null)ClientActions.cancelReactiveChild(a.child,"defense_user_pause");}
 static void externalCancel(String id){if(arm!=null&&id.equals(arm.childId))stop("explicit_child_cancel");}
 static boolean captureRequested(){return arm!=null;}
 static <T>T directInput(java.util.function.Supplier<T> effect){
  Minecraft mc=Minecraft.getInstance();var p=mc.player;var l=mc.level;var context=releaseContext(mc,p,l);var old=ClientActions.reactiveLatest();long revision=ClientActions.ownershipRevision();Arm pausedArm=arm;
  pendingDirect=null;
  T result=directFence.call(effect,()->mc.player==p&&mc.level==l&&context.sameWorld(releaseContext(mc,mc.player,mc.level))&&ClientActions.reactiveLatest()==old&&ClientActions.ownershipRevision()==revision+1&&ClientActions.reactiveNoOwner()&&ClientActions.reactiveNoCleanup()&&ClientActions.reactiveNoDispatch(),()->{
   boolean proven=neutral(mc);
   if(proven)release=new ReactivePhysicalRelease(old,context,ClientActions.ownershipRevision(),true);return proven;
  });
  long pauseIntent=pausedArm==null?-1:pausedArm.intentRevision;
  Object token=directFence.pendingToken();if(token!=null)pendingDirect=new PendingDirect(token,old,context,revision+1,pausedArm,pauseIntent);
  else resumeDirectPause(pausedArm,pauseIntent);return result;
 }
 private static void resumeDirectPause(Arm pausedArm,long pauseIntent){
  Arm current=arm;
  if(ReactiveDefensePolicy.resumeDirectPause(pausedArm,current,pauseIntent,current==null?-1:current.intentRevision,current!=null&&current.suspended,!directFence.blocks())){
   current.suspended=false;current.pausedUntil=tick;current.phase="ARMED";current.reason="direct_input_released";
  }
 }
 private static void reconcileDirectRelease(Minecraft mc){
  PendingDirect pending=pendingDirect;if(pending==null)return;
  var current=releaseContext(mc,mc.player,mc.level);var latest=ClientActions.reactiveLatest();long revision=ClientActions.ownershipRevision();
  if(directFence.reconcile(pending.token,()->ReactiveDefensePolicy.directReleaseMatches(pending.entry,pending.context,pending.revision,latest,current,revision,release)
      &&ClientActions.reactiveNoOwner()&&ClientActions.reactiveNoCleanup()&&ClientActions.reactiveNoDispatch()&&neutral(mc)
      &&ClientActions.reactiveLatest()==latest&&ClientActions.ownershipRevision()==revision&&current.sameWorld(releaseContext(mc,mc.player,mc.level))&&current.player()==mc.player)){
   // A newer native terminal receipt already proves cleanup: retain that exact original receipt.
   if(revision==pending.revision)release=new ReactivePhysicalRelease(latest,current,revision,true);
   resumeDirectPause(pending.pausedArm,pending.pauseIntent);
   pendingDirect=null;
  }
 }
 static void released(ActionRegistry.Entry e,LocalPlayer p,ClientLevel l,long revision,boolean complete){
  Minecraft mc=Minecraft.getInstance();boolean actual=complete&&mc.player==p&&mc.level==l&&ClientActions.reactiveNoOwner()&&neutral(mc);
  release=new ReactivePhysicalRelease(e,releaseContext(mc,p,l),revision,actual);
  reconcileDirectRelease(mc);
 }
 private static ReactivePhysicalRelease.Context releaseContext(Minecraft mc,LocalPlayer p,ClientLevel l){return new ReactivePhysicalRelease.Context(p,l,mc.getSingleplayerServer(),ClientActions.session(),l==null||l!=mc.level?null:WorldGeneration.current(l),p==null?null:p.getUUID().toString());}
 private static ReactivePhysicalRelease.Basis releaseBasis(Minecraft mc){
  if(release==null)return ReactivePhysicalRelease.Basis.NONE;
  boolean dead=release.context!=null&&release.context.player() instanceof LocalPlayer old&&Float.isFinite(old.getHealth())&&old.getHealth()<=0;
  return release.basis(ClientActions.reactiveLatest(),ClientActions.ownershipRevision(),releaseContext(mc,mc.player,mc.level),dead,mc.player!=null&&mc.player.isAlive());
 }
 static boolean neutral(Minecraft mc){return mc.player!=null&&ScopedFlatMovement.neutral(mc.player.input)&&!ScopedFlatMovement.keysDown(mc)&&!BridgeServer.hasHeldInputs()&&ClientInputIsolation.statistics().heldKeys()==0&&GuardedGameMovement.LEASES.status().ownerRequestId()==null&&!mc.player.isUsingItem();}
 static boolean physicalReady(Minecraft mc){ActionRegistry.Entry e=ClientActions.reactiveLatest();return !directFence.blocks()&&ReactiveDefensePolicy.physicalReady(ClientActions.reactiveNoOwner(),ClientActions.reactiveNoDispatch(),ClientActions.reactiveNoCleanup(),neutral(mc),releaseBasis(mc)!=ReactivePhysicalRelease.Basis.NONE,e==null);}
 static void requireStart(ClientActionRequest request){
  if(!request.action().equals("reactive_defense"))return;
  if(request!=permit||permitArm==null||permitArm!=arm||permitEntered){permitTainted=true;throw new ClientActionRequest.Rejected(409,"defense_internal_exact_permit_required");}
  permitEntered=true;
 }
 static void finalFence(ClientActionRequest request){if(!request.action().equals("reactive_defense"))return;require(request==permit&&permitEntered&&!permitTainted&&arm==permitArm&&arm.same(Minecraft.getInstance())&&Minecraft.getInstance().player.isAlive()&&!arm.suspended&&arm.intentRevision==permitRevision&&Minecraft.getInstance().screen==null&&!Minecraft.getInstance().isPaused()&&ClientActions.reactiveChannelsAbsent()&&!directFence.blocks(),"defense_permit_changed");}
 static NativeReactiveDefense create(Minecraft mc,ClientActionRequest request,JsonObject result){finalFence(request);return new NativeReactiveDefense(mc,arm.config,result,arm.stalled);}
 static void registered(ClientActionRequest request,ActionRegistry.Entry entry){if(!request.action().equals("reactive_defense"))return;if(request==permit&&permitArm!=null){permitArm.child=entry;permitArm.childId=request.id();}finalFence(request);arm.phase="PROTECT";arm.reason="native_triggered";arm.episodes++;}
 static void observeLifecycle(Minecraft mc){Arm a=arm;if(a!=null&&(!a.same(mc)||!a.player.isAlive()))stop(!a.same(mc)?"context_changed":"death");}
 static void tick(Minecraft mc){
  try{tickChecked(mc);}catch(RuntimeException unavailable){if(arm!=null){arm.phase="OBSERVATION_WAIT";arm.reason="observation_unavailable_no_new_input";}}
 }
 private static void tickChecked(Minecraft mc){
  tick++;reconcileDirectRelease(mc);Arm a=arm;if(a==null)return;
  if(!a.same(mc)||!a.player.isAlive()){stop(!a.same(mc)?"context_changed":"death");return;}
  if(mc.screen!=null||mc.isPaused()){userPause("screen_open");return;}
  if(a.child!=null){
   if(a.child.running())return;
   a.phase="ARMED";a.reason="episode_terminal";a.child=null;
  }
  long epoch=NavigationPositionGuard.epoch();if(epoch!=a.navigationEpoch){a.navigationEpoch=epoch;if(a.suspended&&a.reason.equals("direct_takeover")&&physicalReady(mc))a.pausedUntil=tick;}
  if(a.suspended){if(tick<a.pausedUntil||!neutral(mc))return;a.suspended=false;}
  if(NativeFallRescue.blocksInput()||NativeExternalNavigation.blocksInput()||NativePortalHandoff.status().get("armed").getAsBoolean()) {a.phase="WAIT_OWNER";a.reason="priority_owner";return;}
  boolean threat=NativeReactiveDefense.triggered(mc,a.config,a.stalled);
  if(!threat){a.phase="ARMED";a.reason="no_direct_threat";return;}
  ReactiveGuardDispatch.tick(new ReactiveGuardDispatch.Host(){
   public boolean hasOwner(){return ClientActions.hasRuntimeAction();}
   public boolean interruptAllowed(){return a.config.interrupt;}
   public boolean physicalReady(){return NativeReactiveGuard.physicalReady(mc);}
   public boolean cancelExactOriginal(){return ClientActions.interruptForReactiveDefense();}
   public void startNewProtection(){submit(mc,a);}
   public void waiting(String reason){a.phase=reason.equals("original_cancelled_wait_cleanup")?"TAKEOVER_WAIT":"WAIT_OWNER";a.reason=reason;}
  });
 }
 private static void submit(Minecraft mc,Arm a){
  try{NativeWorldBackup.requireNoSnapshot();ExternalControllerGuard.requireIdle(mc);NativeFallRescue.requireOrdinaryAdmission();NativeExternalNavigation.requireOrdinaryAdmission();}
  catch(RuntimeException busy){a.phase="WAIT_OWNER";a.reason="native_admission_busy";return;}
  ActionRegistry.Entry previous=ClientActions.reactiveLatest();a.protectedAfterId=previous==null?null:previous.request.id();a.originalOutcome=previous==null?null:previous.json(false);
  JsonObject b=new JsonObject();b.addProperty("action_id",UUID.randomUUID().toString());b.addProperty("action","reactive_defense");b.addProperty("timeout_ms",a.config.episodeMs);b.addProperty("hotbar_slot",a.config.weaponSlot);b.addProperty("defense_arm_id",a.id);b.addProperty("expected_world_generation",a.generation);b.addProperty("expected_action_session",a.session);b.addProperty("expected_player_uuid",a.player.getUUID().toString());
  ClientActionRequest request=ClientActionRequest.parse(b);a.childId=request.id();permit=request;permitArm=a;permitEntered=permitTainted=false;permitRevision=a.intentRevision;
  try{NativeAdmission.run(b,false,a.session,()->ClientActions.start(request));}
  catch(Exception failed){
   a.reason="defense_start_failed_original_id_only";
   if(a.child!=null&&a.child.running())ClientActions.cancelReactiveChild(a.child,"reactive_defense_start_failed");
   if(failed instanceof ClientActionRequest.Rejected r&&preInput(r.nativeAdmission,request)&&a.child==null){a.phase="ADMISSION_WAIT";a.suspended=true;a.pausedUntil=tick+5;}
   else if(a.child!=null&&!a.child.running()&&physicalReady(mc)){a.phase="ARMED";}
   else {a.phase="BLOCKED_START";a.suspended=true;a.pausedUntil=Long.MAX_VALUE;}
  }
  finally{permit=null;permitArm=null;permitEntered=false;}
 }
 static boolean preInput(JsonObject proof,ClientActionRequest r){return proof!=null&&proof.has("boundary_schema_version")&&proof.get("boundary_schema_version").getAsInt()==2&&truth(proof,"ordinary_start_entered",true)&&truth(proof,"input_transfer_entered",false)&&truth(proof,"registration_entered",false)&&truth(proof,"reentry_observed",false)&&proof.has("action")&&proof.get("action").getAsString().equals(r.action())&&proof.has("action_session")&&proof.get("action_session").getAsString().equals(ClientActions.session())&&proof.has("action_id")&&proof.get("action_id").getAsString().equals(r.id())&&proof.has("request_payload_sha256")&&proof.get("request_payload_sha256").getAsString().equals(ScopedNativePreflight.digest(r.original()));}
 private static boolean truth(JsonObject j,String k,boolean expected){return j.has(k)&&j.get(k).isJsonPrimitive()&&j.getAsJsonPrimitive(k).isBoolean()&&j.get(k).getAsBoolean()==expected;}
 static JsonObject status(){JsonObject j=arm==null?last.deepCopy():json(arm);j.addProperty("ok",true);j.addProperty("schema_version",1);j.addProperty("armed",arm!=null);j.addProperty("direct_input_release_state",directFence.state());if(pendingDirect!=null)j.addProperty("pending_direct_ownership_revision",pendingDirect.revision);if(release!=null){JsonObject r=new JsonObject();r.addProperty("original_action_id",release.entry==null?null:((ActionRegistry.Entry)release.entry).request.id());r.addProperty("physical_release_observed",release.physical);r.addProperty("ownership_revision",release.revision);r.addProperty("current_context_basis",releaseBasis(Minecraft.getInstance()).name().toLowerCase(java.util.Locale.ROOT));j.add("last_local_physical_release",r);}return j;}
 private static JsonObject json(Arm a){JsonObject j=new JsonObject();j.addProperty("arm_id",a.id);j.addProperty("phase",a.phase);j.addProperty("reason",a.reason);j.addProperty("episode_count",a.episodes);j.addProperty("unreachable_targets_waiting_for_changed_evidence",a.stalled.size());j.addProperty("child_action_id",a.childId);j.addProperty("protected_after_action_id",a.protectedAfterId);if(a.originalOutcome!=null)j.add("prior_outcome_preserved",a.originalOutcome.deepCopy());j.addProperty("observed_client_tick",tick);j.addProperty("world_generation",a.generation);j.addProperty("action_session",a.session);j.addProperty("dimension",a.dimension);j.addProperty("player_uuid",a.player.getUUID().toString());if(a.child!=null)j.add("child",a.child.json(a.child.running()));return j;}
 private static double number(JsonObject j,String k){var v=j.get(k);require(v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isNumber()&&Double.isFinite(v.getAsDouble()),"invalid_"+k);return v.getAsDouble();}
 private static void require(boolean yes,String why){if(!yes)throw new ClientActionRequest.Rejected(409,why);}
 private NativeReactiveGuard(){}
}
