package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.util.*;
import java.util.function.BooleanSupplier;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.monster.EnderMan;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.phys.*;

/** Explicit opt-in: one UUID, existing flat shelter/peek segment, vanilla view/use/attack only.
 * No target mutation, teleport, item grant, alternate registry or generic combat whitelist. */
final class NativeShelteredEnderman {
 record Config(String uuid,boolean shield,double stop,double damage,int fire,int lure,int engage,
               ClientActionRequest.Point cover,ClientActionRequest.Point peek){}
 static final Set<String> FIELDS=Set.of("schema_version","known_route","target_uuid","shield","stop_health","maximum_observed_damage","continuous_fire_ms","lure_timeout_ms","engage_timeout_ms");
 private final Config config;
 private final LocalPlayer player;
 private final ClientLevel level;
 private final net.minecraft.server.MinecraftServer server;
 private final EnderMan originalTarget;
 private final int targetId;
 private final BlockPos coverFeet;
 private final EndermanShelterPolicy policy;
 private final JsonObject evidence;
 private final JsonArray transitions=new JsonArray();
 private final BlazeEscortPolicy.Progress progress=new BlazeEscortPolicy.Progress();
 private BooleanSupplier owned=()->false;
 private JsonObject originalResult;
 private boolean shieldOwned;
 private int stableTicks,blockingTicks,transitionCount;
 private long blockedSince=-1;
 private String lastPhase="",lastReason="";
 private EndermanShelterPolicy.Phase lastMovementPhase;

 static Config validate(ClientActionRequest request){
  JsonObject b=request.original();require(request.action().equals("follow_path"),"enderman_shelter_requires_follow_path");
  for(String incompatible:List.of("blaze_guard","capability_guard","coordination_step","capability_route","portal_handoff","portal_handoff_parent","sprint"))
   require(!b.has(incompatible),"enderman_shelter_plain_owner_only");
  require(!request.sneak()&&request.timeoutMs()>=2000,"enderman_shelter_bounded_plain_walk");
  require(b.has("enderman_shelter")&&b.get("enderman_shelter").isJsonObject(),"enderman_shelter_object_required");
  JsonObject c=b.getAsJsonObject("enderman_shelter");require(c.keySet().equals(FIELDS),"enderman_shelter_closed_fields");
  require(ClientActionRequest.integer(c,"schema_version",0)==1&&ClientActionRequest.bool(c,"known_route",false),"enderman_shelter_known_route_required");
  String uuid=ClientActionRequest.string(c,"target_uuid");uuid(uuid);
  for(String k:List.of("expected_action_session","expected_player_uuid","expected_world_generation"))uuid(ClientActionRequest.string(b,k));
  require(b.has("expected_navigation_epoch")&&b.has("expected_origin")&&b.get("expected_origin").isJsonObject(),"enderman_shelter_fresh_navigation_required");
  JsonObject o=b.getAsJsonObject("expected_origin");var cover=new ClientActionRequest.Point(number(o,"x"),number(o,"y"),number(o,"z"),false);
  require(request.waypoints().size()==2,"enderman_shelter_exact_out_and_back");var peek=request.waypoints().get(0);var back=request.waypoints().get(1);
  double distance=Math.hypot(peek.x()-cover.x(),peek.z()-cover.z());
  require(distance>=.25&&distance<=4&&Math.abs(peek.y()-cover.y())<=.15&&!peek.jump()&&!back.jump(),"enderman_shelter_flat_short_known_segment");
  require(point(back).distanceTo(point(cover))<=.05,"enderman_shelter_return_is_original_cover");
  double stop=number(c,"stop_health"),damage=number(c,"maximum_observed_damage");
  int fire=ClientActionRequest.integer(c,"continuous_fire_ms",0),lure=ClientActionRequest.integer(c,"lure_timeout_ms",0),engage=ClientActionRequest.integer(c,"engage_timeout_ms",0);
  require(stop>0&&stop<20&&damage>0&&damage<=100,"enderman_shelter_health_bounds");
  require(fire>=1000&&fire<=30000&&lure>=500&&lure<=10000&&engage>=1000&&engage<=60000,"enderman_shelter_time_bounds");
  return new Config(uuid,ClientActionRequest.bool(c,"shield",false),stop,damage,fire,lure,engage,cover,peek);
 }
 NativeShelteredEnderman(Minecraft mc,ClientActionRequest request,JsonObject evidence){
  config=validate(request);player=mc.player;level=mc.level;server=mc.getSingleplayerServer();this.evidence=evidence;
  if(player==null||level==null||!mc.hasSingleplayerServer()||mc.getSingleplayerServer()==null||mc.getSingleplayerServer().isPublished())reject("enderman_shelter_private_singleplayer_required");
  if(!NativeBlazeEscort.weapon(player))reject("enderman_shelter_sword_or_axe_required");
  coverFeet=BlockPos.containing(point(config.cover));
  if(!atCoverPosition()||!shelterGeometry(mc))reject("enderman_shelter_fixed_center_loaded_roof_required");
  EnderMan found=null;
  for(EnderMan e:level.getEntitiesOfClass(EnderMan.class,player.getBoundingBox().inflate(32),e->e.isAlive()&&!e.isRemoved()))
   if(e.getUUID().toString().equals(config.uuid)&&type(e).equals("minecraft:enderman")){found=e;break;}
  if(found==null)reject("enderman_shelter_explicit_loaded_target_required");
  originalTarget=found;targetId=found.getId();
  if(net.neoforged.neoforge.common.CommonHooks.shouldSuppressEnderManAnger(found,player,player.getInventory().armor.get(3)))reject("enderman_shelter_gaze_suppressed_by_equipment");
  policy=new EndermanShelterPolicy(player.getHealth(),config.stop,config.damage,config.fire,config.lure,config.engage);
  evidence.addProperty("schema_version",1);evidence.addProperty("target_uuid",config.uuid);evidence.addProperty("target_entity_id",targetId);evidence.addProperty("target_type","minecraft:enderman");
  evidence.addProperty("single_native_owner",true);evidence.addProperty("known_flat_route_only",true);evidence.addProperty("no_pickup_or_chase",true);evidence.add("transitions",transitions);
 }
 void bind(BooleanSupplier owned,JsonObject result){this.owned=owned;this.originalResult=result;}
 private boolean stillOwner(Minecraft mc){return owned.getAsBoolean()&&mc.player==player&&mc.level==level&&mc.gameMode!=null&&server!=null&&mc.getSingleplayerServer()==server&&!server.isPublished();}
 private void owner(Minecraft mc){if(!stillOwner(mc))throw new IllegalStateException("enderman_shelter_owner_changed");}
 NativeBlazeEscort.Step tick(Minecraft mc,int tick,long deadline){
  owner(mc);long now=System.nanoTime();policy.health(player.getHealth(),player.isOnFire(),player.isInWaterOrBubble()||player.isInLava()||player.isInPowderSnow,now);policy.deadline(now);
  if(player.isBlocking())blockingTicks++;
  if(!NativeBlazeEscort.weapon(player))policy.abort("selected_weapon_unavailable");
  if(NativeThreatObservation.creeper(mc)!=null)policy.abort("creeper_threat_return_to_original_shelter");
  // This short route's total job budget is never extended by gaze, teleport or observation loss.
  double homeDistance=player.position().distanceTo(point(config.cover));
  if(deadline-now<(long)((homeDistance/2.5+2)*1_000_000_000L))policy.abort("job_deadline_return_reserve");
  if(!shelterGeometry(mc))policy.abort("original_shelter_geometry_changed");
  JsonObject nativeRow=targetRow(mc,now);boolean self=targetSelf(nativeRow,player.getUUID().toString());
  evidence.add("native_target",nativeRow.deepCopy());
  if(knownDead(nativeRow)){policy.dead();evidence.add("confirmed_target_death",nativeRow.deepCopy());}
  Entity current=level.getEntity(targetId);
  boolean same=current==originalTarget&&current.getUUID().toString().equals(config.uuid)&&type(current).equals("minecraft:enderman");
  if(!policy.knownDead&&same&&clientDead(originalTarget.isRemoved(),originalTarget.getHealth())){policy.dead();evidence.addProperty("client_target_dead_observed",true);}
  if(!policy.knownDead&&(!same||originalTarget.isRemoved()))policy.abort("target_missing_not_a_kill");
  if(!policy.knownDead&&same&&self)policy.confirmAggro(now);
  NativeBlazeEscort.Step result;
  if(policy.phase==EndermanShelterPolicy.Phase.RETURNING){
   lookDown(mc);shield(mc,config.shield);result=move(mc,config.cover,true,now);
   if(result.terminal()==null&&result.reason().equals("waypoint_settled")){
    if(!atCoverPosition()||!shelterGeometry(mc))result=NativeBlazeEscort.Step.end("failed","original_shelter_not_restored");
    else{policy.atCover();result=policy.phase==EndermanShelterPolicy.Phase.DONE?NativeBlazeEscort.Step.end("succeeded",policy.knownDead?"enderman_dead_returned_to_shelter":"enderman_returned_to_shelter:"+policy.reason):NativeBlazeEscort.Step.waitFor("returned_to_fixed_shelter_melee");}
   }
  }else if(policy.phase==EndermanShelterPolicy.Phase.OUTBOUND){
   lookDown(mc);shield(mc,false);result=move(mc,config.peek,false,now);
   if(result.terminal()!=null){policy.abort(result.reason());result=NativeBlazeEscort.Step.waitFor("outbound_failed_return_original_segment");}
   else if(result.reason().equals("waypoint_settled")){boolean visible=same&&player.hasLineOfSight(originalTarget);policy.atPeek(now,visible);result=NativeBlazeEscort.Step.waitFor(policy.reason);}
  }else if(policy.phase==EndermanShelterPolicy.Phase.GAZING){
   boolean visible=same&&player.hasLineOfSight(originalTarget);policy.gaze(now,visible);
   if(policy.phase==EndermanShelterPolicy.Phase.GAZING){aim(mc,originalTarget.getEyePosition());shield(mc,config.shield);result=NativeBlazeEscort.Step.waitFor("tracking_exact_target_eyes_waiting_server_aggro");}
   else{lookDown(mc);result=NativeBlazeEscort.Step.waitFor(policy.reason);}
  }else if(policy.phase==EndermanShelterPolicy.Phase.FIGHTING)result=fight(mc,tick,same,self);
  else result=NativeBlazeEscort.Step.end("succeeded","enderman_shelter_done");
  record(tick,result);return result;
 }
 private NativeBlazeEscort.Step fight(Minecraft mc,int tick,boolean same,boolean freshTargetSelf){
  if(!atCoverPosition()||!shelterGeometry(mc)){policy.abort("displaced_from_original_shelter");return NativeBlazeEscort.Step.waitFor(policy.reason);}
  if(!same){policy.abort("target_missing_not_a_kill");return NativeBlazeEscort.Step.waitFor(policy.reason);}
  // Aim below the roof. Eye-to-eye LOS is intentionally NOT a melee condition.
  aim(mc,legAim(originalTarget.getBoundingBox()));owner(mc);mc.gameRenderer.pick(1.0F);owner(mc);
  boolean ray=legRay(mc);double strength=player.getAttackStrengthScale(.5F);
  evidence.addProperty("leg_ray_in_reach",ray);evidence.addProperty("attack_strength",strength);evidence.addProperty("target_health",originalTarget.getHealth());
  if(!freshTargetSelf||!ray||!CombatRules.cooldownReady(strength)){shield(mc,config.shield);return NativeBlazeEscort.Step.waitFor(!freshTargetSelf?"waiting_fresh_original_target_self":!ray?"stationary_wait_target_leg_reach":"cooldown_shield");}
  if(shieldOwned||player.isUsingItem()){shield(mc,false);return NativeBlazeEscort.Step.waitFor("lowering_shield_for_ready_attack");}
  owner(mc);mc.gameRenderer.pick(1.0F);owner(mc);
  // Refresh server identity/target again after input hooks; do not keep a stale self-target boolean.
  boolean targetNow=targetSelf(targetRow(mc,System.nanoTime()),player.getUUID().toString());
  if(!atCoverPosition()||!shelterGeometry(mc)||!policy.mayAttack(tick,legRay(mc),player.getAttackStrengthScale(.5F),player.isUsingItem(),targetNow))return NativeBlazeEscort.Step.waitFor("attack_precondition_changed");
  policy.attack(tick);
  NativeBlazeEscort.inputAttempt(originalResult,()->mc.startAttack(),()->stillOwner(mc));owner(mc);
  shield(mc,config.shield);return NativeBlazeEscort.Step.waitFor("enderman_leg_attack_dispatched_once");
 }
 private JsonObject targetRow(Minecraft mc,long now){var f=NativeLivingObservation.capture(mc);return NativeLivingSnapshot.json(f.batch(),NativeLivingObservation.current(f)?f.context():null,level.dimension().location().toString(),WorldGeneration.current(level),player.getUUID().toString(),config.uuid,targetId,"minecraft:enderman",level.getGameTime(),now);}
 static boolean targetSelf(JsonObject row,String playerUuid){return row!=null&&row.has("known")&&row.get("known").getAsBoolean()&&row.has("current_target_known")&&row.get("current_target_known").getAsBoolean()&&row.has("alive")&&row.get("alive").getAsBoolean()&&row.has("current_target")&&row.get("current_target").isJsonObject()&&row.getAsJsonObject("current_target").has("uuid")&&row.getAsJsonObject("current_target").get("uuid").getAsString().equals(playerUuid);}
 static boolean clientDead(boolean removed,float health){return !removed&&Float.isFinite(health)&&health<=0;}
 static boolean knownDead(JsonObject row){return row!=null&&row.has("known")&&row.get("known").getAsBoolean()&&row.has("alive")&&!row.get("alive").getAsBoolean();}
 static Vec3 legAim(AABB b){return new Vec3((b.minX+b.maxX)/2,b.minY+Math.min(.8,(b.maxY-b.minY)*.25),(b.minZ+b.maxZ)/2);}
 private boolean legRay(Minecraft mc){
  if(!(mc.hitResult instanceof EntityHitResult h)||h.getEntity()!=originalTarget||!originalTarget.isAlive()||originalTarget.isRemoved())return false;
  Vec3 eye=player.getEyePosition();return CombatRules.rayInReach(true,eye.distanceTo(h.getLocation()),player.entityInteractionRange())
   &&level.clip(new ClipContext(eye,h.getLocation(),ClipContext.Block.COLLIDER,ClipContext.Fluid.NONE,player)).getType()==HitResult.Type.MISS;
 }
 private boolean atCoverPosition(){return player.blockPosition().equals(coverFeet)&&Math.abs(player.getY()-config.cover.y())<=.15&&Math.hypot(player.getX()-config.cover.x(),player.getZ()-config.cover.z())<=.25&&player.onGround();}
 private boolean shelterGeometry(Minecraft mc){
  if(Math.abs(config.cover.y()-coverFeet.getY())>.15||Math.hypot(config.cover.x()-coverFeet.getX()-.5,config.cover.z()-coverFeet.getZ()-.5)>.25)return false;
  for(int x=-1;x<=1;x++)for(int z=-1;z<=1;z++){
   BlockPos roof=coverFeet.offset(x,2,z);
   if(!level.hasChunkAt(roof)||!level.getFluidState(roof).isEmpty()||!level.getBlockState(roof).isCollisionShapeFullBlock(level,roof))return false;
  }
  AABB at=player.getBoundingBox().move(config.cover.x()-player.getX(),config.cover.y()-player.getY(),config.cover.z()-player.getZ());
  return loadedDry(at)&&level.noCollision(player,at)&&!level.noCollision(player,at.move(0,-.12,0));
 }
 private boolean loadedDry(AABB box){for(BlockPos p:BlockPos.betweenClosed(BlockPos.containing(box.minX,box.minY-.12,box.minZ),BlockPos.containing(box.maxX,box.maxY,box.maxZ)))if(!level.hasChunkAt(p)||!level.getFluidState(p).isEmpty())return false;return true;}
 private NativeBlazeEscort.Step move(Minecraft mc,ClientActionRequest.Point goal,boolean returning,long now){
  if(lastMovementPhase!=policy.phase){progress.reset();stableTicks=0;blockedSince=-1;lastMovementPhase=policy.phase;}
  Vec3 p=player.position();
  if(NativeBlazeEscort.horizontalSegmentDistance(p,point(config.cover),point(config.peek))>.65||p.y<config.cover.y()-.35||p.y>config.cover.y()+1.25)return NativeBlazeEscort.Step.end("failed","outside_authorized_shelter_segment");
  var step=PathSteering.toward(p.x,p.y,p.z,player.getYRot(),player.onGround(),player.horizontalCollision,goal,true);
  if(step.reached()){
   Vec3 v=player.getDeltaMovement();if(PathSteering.settledAt(p.x,p.y,p.z,v.x,v.z,player.onGround(),goal))stableTicks++;else stableTicks=0;
   return NativeBlazeEscort.Step.waitFor(stableTicks>=2?"waypoint_settled":"settling_known_shelter_point");
  }
  stableTicks=0;
  double dx=goal.x()-p.x,dz=goal.z()-p.z,length=Math.hypot(dx,dz),scale=Math.min(.25,length)/Math.max(.0001,length);
  AABB next=player.getBoundingBox().move(dx*scale,0,dz*scale);
  if(!player.onGround()||!loadedDry(next)||!level.noCollision(player,next)||level.noCollision(player,next.move(0,-.12,0))){
   if(blockedSince<0)blockedSince=now;
   return now-blockedSince>2_000_000_000L?NativeBlazeEscort.Step.end("failed","shelter_segment_support_or_clearance_changed"):NativeBlazeEscort.Step.waitFor("waiting_local_shelter_segment_settle");
  }
  blockedSince=-1;
  owner(mc);player.setYRot(step.yaw());owner(mc);player.setYHeadRot(step.yaw());owner(mc);
  if(progress.stuck(step.distance(),player.onGround(),now))return NativeBlazeEscort.Step.end("failed","shelter_segment_no_progress_4s");
  return new NativeBlazeEscort.Step(step.forward(),false,null,returning?"returning_original_shelter_segment":"walking_authorized_eye_line_point");
 }
 private void lookDown(Minecraft mc){owner(mc);player.setXRot(75);owner(mc);}
 private void aim(Minecraft mc,Vec3 point){Vec3 d=point.subtract(player.getEyePosition());float yaw=(float)Math.toDegrees(Math.atan2(-d.x,d.z)),pitch=(float)-Math.toDegrees(Math.atan2(d.y,Math.hypot(d.x,d.z)));owner(mc);player.setYRot(yaw);owner(mc);player.setXRot(pitch);owner(mc);player.setYHeadRot(yaw);owner(mc);}
 private void shield(Minecraft mc,boolean wanted){owner(mc);wanted=wanted&&player.getOffhandItem().is(Items.SHIELD)&&!player.getCooldowns().isOnCooldown(Items.SHIELD);if(!wanted){releaseShield(mc,()->owner(mc));return;}if(!player.isUsingItem()){shieldOwned=true;NativeBlazeEscort.inputAttempt(originalResult,()->mc.gameMode.useItem(player,InteractionHand.OFF_HAND),()->stillOwner(mc));owner(mc);if(player.isUsingItem()&&player.getUsedItemHand()==InteractionHand.OFF_HAND&&player.getUseItem().is(Items.SHIELD)){mc.options.keyUse.setDown(true);owner(mc);}else releaseShield(mc,()->owner(mc));}}
 void release(Minecraft mc,Runnable fence){releaseShield(mc,fence);fence.run();evidence.addProperty("cleanup_completed",true);}
 private void releaseShield(Minecraft mc,Runnable fence){if(!shieldOwned)return;fence.run();mc.options.keyUse.setDown(false);fence.run();if(mc.player==player&&mc.gameMode!=null&&player.isUsingItem())mc.gameMode.releaseUsingItem(player);fence.run();shieldOwned=false;}
 private void record(int tick,NativeBlazeEscort.Step step){String phase=policy.phase.name();if(!phase.equals(lastPhase)||!step.reason().equals(lastReason)){transitionCount++;if(transitions.size()<128){JsonObject row=new JsonObject();row.addProperty("tick",tick);row.addProperty("phase",phase);row.addProperty("reason",step.reason());row.addProperty("health",player.getHealth());transitions.add(row);}lastPhase=phase;lastReason=step.reason();}evidence.addProperty("phase",phase);evidence.addProperty("reason",step.reason());evidence.addProperty("aggro_confirmed",policy.aggroConfirmed);evidence.addProperty("known_dead",policy.knownDead?1:0);evidence.addProperty("attacks",policy.attacks);evidence.addProperty("health",player.getHealth());evidence.addProperty("observed_damage",policy.health.observedDamage);evidence.addProperty("blocking_ticks",blockingTicks);evidence.addProperty("transitions_total",transitionCount);evidence.addProperty("transitions_truncated",transitionCount>128);}
 private static Vec3 point(ClientActionRequest.Point p){return new Vec3(p.x(),p.y(),p.z());}
 private static String type(Entity e){return BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).toString();}
 private static double number(JsonObject j,String k){var v=j.get(k);require(v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isNumber()&&Double.isFinite(v.getAsDouble()),"invalid_"+k);return v.getAsDouble();}
 private static void uuid(String s){try{require(UUID.fromString(s).toString().equals(s),"enderman_shelter_uuid_required");}catch(IllegalArgumentException ex){throw new ClientActionRequest.Rejected(400,"enderman_shelter_uuid_required");}}
 private static void require(boolean b,String r){ClientActionRequest.require(b,r);}
 private static void reject(String r){throw new ClientActionRequest.Rejected(409,r);}
}
