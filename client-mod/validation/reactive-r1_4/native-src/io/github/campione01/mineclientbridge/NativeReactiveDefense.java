package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.*;
import java.util.function.BooleanSupplier;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.*;
import net.minecraft.world.entity.monster.Creeper;
import net.minecraft.world.entity.monster.Slime;
import net.minecraft.world.entity.projectile.Projectile;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.phys.*;

/** A registry-owned episode: ordinary attacks/use/motion only, never world/entity writes. */
final class NativeReactiveDefense {
 record Contact(Mob entity,String type,double distance,boolean visible,boolean self,boolean reachable,boolean incoming,double priority){}
 private final LocalPlayer player;private final ClientLevel level;private final Object server;
 private final NativeReactiveGuard.Config config;private final JsonObject result,evidence=new JsonObject();
 private final JsonArray deaths=new JsonArray(),changes=new JsonArray();private final Set<String> dead=new HashSet<>();
 private final Map<String,Mob> tracked=new HashMap<>();private final Map<String,Long> cooling=new HashMap<>();
 private final Map<String,ReactiveDefensePolicy.Stalled> stalled;
 private BooleanSupplier owned=()->false;private Mob target;private String phase="TRIGGERED";
 private boolean shieldOwned;private int attacks,blockingTicks,quiet,previousTick=-1,selectedAt,changeCount,pathSteps;
 private float lastHealth,minHealth;private double damage;private long planAt,progressAt,navigationEpoch=NavigationPositionGuard.epoch();private double best=Double.POSITIVE_INFINITY;
 private List<ReactiveLocalPlanner.Cell> path=List.of();private ReactiveLocalPlanner.Cell next;private Vec3 plannedFrom;
 NativeReactiveDefense(Minecraft mc,NativeReactiveGuard.Config config,JsonObject result,Map<String,ReactiveDefensePolicy.Stalled> stalled){this.stalled=stalled;this.player=mc.player;this.level=mc.level;this.server=mc.getSingleplayerServer();this.config=config;this.result=result;lastHealth=minHealth=player.getHealth();result.add("reactive_defense",evidence);evidence.add("confirmed_deaths",deaths);evidence.add("transitions",changes);}
 void bind(BooleanSupplier owner){owned=owner;}
 private boolean own(Minecraft mc){return owned.getAsBoolean()&&mc.player==player&&mc.level==level&&mc.gameMode!=null&&mc.getSingleplayerServer()==server&&mc.getSingleplayerServer()!=null&&!mc.getSingleplayerServer().isPublished();}
 private void owner(Minecraft mc){if(!own(mc))throw new IllegalStateException("reactive_defense_owner_changed");}
 static String type(Entity e){return BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).toString();}
 static boolean triggered(Minecraft mc,NativeReactiveGuard.Config config,Map<String,ReactiveDefensePolicy.Stalled> stalled){return NativeThreatObservation.creeper(mc)!=null||contacts(mc,config).stream().anyMatch(c->!suppressed(mc,c,stalled))||mc.player.isEyeInFluid(FluidTags.WATER)&&mc.player.getAirSupply()<180||mc.player.isInLava();}
 static boolean suppressed(Minecraft mc,Contact c,Map<String,ReactiveDefensePolicy.Stalled> stalled){var old=stalled.get(c.entity.getUUID().toString());if(old==null)return false;
  boolean unchanged=old.unchanged(mc.player.getX(),mc.player.getY(),mc.player.getZ(),c.entity.getX(),c.entity.getY(),c.entity.getZ(),mc.player.getHealth(),c.visible,c.self,c.reachable);if(!unchanged)stalled.remove(c.entity.getUUID().toString());return unchanged;
 }
 static List<Contact> contacts(Minecraft mc,NativeReactiveGuard.Config config){
  var source=NativeLivingObservation.capture(mc);var out=new ArrayList<Contact>();
  for(Mob e:mc.level.getEntitiesOfClass(Mob.class,mc.player.getBoundingBox().inflate(24),v->v.isAlive()&&!v.isRemoved()&&config.types().contains(type(v)))){
   if(out.size()>=128)break;String type=type(e);double d=NativeBlazeEscort.eyeDistance(mc.player.getEyePosition(),e.getBoundingBox());boolean visible=mc.player.hasLineOfSight(e);
   JsonObject row=new JsonObject();NativeLivingObservation.append(mc,e,row,source);JsonObject n=row.getAsJsonObject("native_living");boolean self=n!=null&&n.get("known").getAsBoolean()&&n.has("current_target")&&!n.get("current_target").isJsonNull()&&n.getAsJsonObject("current_target").get("uuid").getAsString().equals(mc.player.getUUID().toString());
   if((type.equals("minecraft:spider")||type.equals("minecraft:cave_spider"))&&!self&&!e.isAggressive())continue;
   if(type.equals("minecraft:slime")&&e instanceof Slime s&&s.getSize()<=1)continue;
   Vec3 delta=e.getBoundingBox().getCenter().subtract(mc.player.getEyePosition()),velocity=e.getDeltaMovement();
   boolean incoming=ReactiveDefensePolicy.phantom(type)&&ReactiveDefensePolicy.phantomIncoming(d,delta.x,delta.y,delta.z,velocity.x,velocity.y,velocity.z);
   if(!ReactiveDefensePolicy.trigger(type,true,true,visible,self,d,incoming))continue;
   boolean reach=d<=Math.min(3,mc.player.entityInteractionRange())&&visible;
   out.add(new Contact(e,type,d,visible,self,reach,incoming,ReactiveDefensePolicy.priority(type,d,visible,self,reach,incoming)));
  }
  out.sort(Comparator.comparingDouble(Contact::priority).reversed());return out;
 }
 NativeBlazeEscort.Step tick(Minecraft mc,int tick,long deadline){
  owner(mc);long epoch=NavigationPositionGuard.epoch();if(epoch!=navigationEpoch){navigationEpoch=epoch;next=null;path=List.of();planAt=progressAt=0;best=Double.POSITIVE_INFINITY;evidence.addProperty("local_route_rebound_epoch",epoch);}
  long now=System.nanoTime();float hp=player.getHealth();damage+=Math.max(0,lastHealth-hp);lastHealth=hp;minHealth=Math.min(minHealth,hp);if(player.isBlocking())blockingTicks++;
  try{checkDeaths(mc);}catch(RuntimeException unavailable){next=null;evidence.addProperty("observation_unavailable",true);return NativeBlazeEscort.Step.waitFor("observation_unavailable_keep_owned_inputs");}
  boolean water=player.isInWater(),breath=player.isEyeInFluid(FluidTags.WATER)&&player.getAirSupply()<180;
  if(player.isInLava()||breath){shield(mc,false);next=null;record(tick,"ENVIRONMENT_RECOVERY",null);return new NativeBlazeEscort.Step(0,0,true,null,"environment_flotation_priority");}
  var creeper=NativeThreatObservation.creeper(mc);
  if(creeper!=null){Entity e=level.getEntity(creeper.id());if(e instanceof Creeper c&&c.getUUID().toString().equals(creeper.uuid())){
   target=null;quiet=0;aim(mc,c.getBoundingBox().getCenter());shield(mc,config.shield());var moved=motion(mc,c,true,now,tick);record(tick,"ESCAPE_CREEPER",null);return addFloat(moved,water);
  }}
  List<Contact> seen;try{seen=contacts(mc,config);}catch(RuntimeException unavailable){next=null;evidence.addProperty("observation_unavailable",true);return NativeBlazeEscort.Step.waitFor("observation_unavailable_keep_owned_inputs");}
  evidence.addProperty("observation_unavailable",false);seen.removeIf(c->dead.contains(c.entity.getUUID().toString())||suppressed(mc,c,stalled));
  evidence.addProperty("observed_threat_count",seen.size());
  Contact selected=null;
  for(Contact c:seen){if(c.reachable||cooling.getOrDefault(c.entity.getUUID().toString(),0L)<=now){selected=c;break;}}
  if(selected!=null&&target!=null&&tick-selectedAt<8&&ReactiveDefensePolicy.keepRecentTarget(selected.reachable,selected.incoming)){for(Contact c:seen)if(c.entity==target){selected=c;break;}}
  boolean forcedEvade=selected==null&&!seen.isEmpty();if(forcedEvade)selected=seen.get(0);
  if(selected==null){
   target=null;next=null;shield(mc,config.shield());quiet++;record(tick,"QUIET",null);
   return quiet>=config.quietTicks()?NativeBlazeEscort.Step.end("succeeded","reactive_threats_quiet"):new NativeBlazeEscort.Step(0,0,water,null,"quiet_observation");
  }
  quiet=0;if(target!=selected.entity){target=selected.entity;selectedAt=tick;path=List.of();planAt=progressAt=0;best=Double.POSITIVE_INFINITY;}
  tracked.put(target.getUUID().toString(),target);aim(mc,target.getBoundingBox().getCenter());owner(mc);mc.gameRenderer.pick(1.0F);owner(mc);
  boolean ray=ray(mc,target);double cooldown=player.getAttackStrengthScale(.5F);
  evidence.addProperty("target_uuid",target.getUUID().toString());evidence.addProperty("target_type",selected.type);evidence.addProperty("target_health",target.getHealth());evidence.addProperty("target_in_actual_ray",ray);evidence.addProperty("attack_strength",cooldown);evidence.addProperty("target_incoming_phantom",selected.incoming);
  if(ray&&cooldown>=.95){
   next=null;
   if(shieldOwned||player.isUsingItem()){shield(mc,false);record(tick,"LOWER_SHIELD",selected);return new NativeBlazeEscort.Step(0,0,water,null,"lower_shield_before_fresh_attack");}
   owner(mc);mc.gameRenderer.pick(1.0F);owner(mc);
   if(tick!=previousTick&&ReactiveDefensePolicy.attackReady(!target.isRemoved()&&target.isAlive(),ray(mc,target),mc.hitResult==null?Double.POSITIVE_INFINITY:player.getEyePosition().distanceTo(mc.hitResult.getLocation()),player.entityInteractionRange(),player.getAttackStrengthScale(.5F),player.isUsingItem())){
    previousTick=tick;attacks++;NativeBlazeEscort.inputAttempt(result,()->mc.startAttack(),()->own(mc));owner(mc);shield(mc,config.shield());record(tick,"STRIKE",selected);return new NativeBlazeEscort.Step(0,0,water,null,"one_fresh_attack");
   }
  }
  shield(mc,config.shield());
  // A flying target never supplies a ground pursuit destination. Face/block the swoop;
  // only the identical fresh real-ray/reach/cooldown path above may attempt a strike.
  if(!ReactiveDefensePolicy.groundPursuit(selected.type)){
   next=null;path=List.of();progressAt=0;best=Double.POSITIVE_INFINITY;
   record(tick,ray?"BLOCK_COOLDOWN":"BLOCK_PHANTOM_APPROACH",selected);
   return new NativeBlazeEscort.Step(0,0,water,null,ray?"cooldown_block":"phantom_face_block_no_chase");
  }
  boolean escape=forcedEvade||hp<=config.lowHealth()&&!ray;
  NativeBlazeEscort.Step moved;
  if(ray){next=null;path=List.of();progressAt=0;best=Double.POSITIVE_INFINITY;moved=NativeBlazeEscort.Step.waitFor("cooldown_block");}
  else moved=motion(mc,target,escape,now,tick);
  record(tick,escape?"EVADE_LOW_HEALTH":ray?"BLOCK_COOLDOWN":"APPROACH",selected);return addFloat(moved,water);
 }
 private NativeBlazeEscort.Step addFloat(NativeBlazeEscort.Step s,boolean water){return new NativeBlazeEscort.Step(s.forward(),s.strafe(),s.jump()||water,s.terminal(),s.reason());}
 private NativeBlazeEscort.Step motion(Minecraft mc,Entity threat,boolean escape,long now,int tick){
  owner(mc);Vec3 p=player.position();
  // Keep the same next center through cell-boundary crossings; every actual step is still revalidated.
  if(ReactiveDefensePolicy.needsLocalPlan(next!=null,path.isEmpty())){
   var start=new ReactiveLocalPlanner.Cell(BlockPos.containing(p).getX(),(int)Math.floor(p.y+.05),BlockPos.containing(p).getZ());
   var terrain=new ReactiveLocalPlanner.Terrain(){public boolean standable(ReactiveLocalPlanner.Cell c){return NativeReactiveDefense.this.standable(mc,c);}public boolean edge(ReactiveLocalPlanner.Cell a,ReactiveLocalPlanner.Cell b){return edgeClear(mc,a,b)&&(!escape||NativeBlazeEscort.escapeDirectionNonClosing(a.x()+.5,a.z()+.5,b.x()-a.x(),b.z()-a.z(),threat.getX(),threat.getZ()));}};
   final AABB targetBox=threat.getBoundingBox();double vx=threat.getX()-p.x,vz=threat.getZ()-p.z,vl=Math.max(.01,Math.hypot(vx,vz));final double sideX=-vz/vl,sideZ=vx/vl;final boolean unshielded=!config.shield()||!player.getOffhandItem().is(Items.SHIELD)||player.getCooldowns().isOnCooldown(Items.SHIELD);
   path=ReactiveLocalPlanner.path(start,c->{Vec3 eye=new Vec3(c.x()+.5,c.y()+player.getEyeHeight(),c.z()+.5);double d=NativeBlazeEscort.eyeDistance(eye,targetBox);double travel=Math.hypot(c.x()+.5-p.x,c.z()+.5-p.z);
    if(escape){double away=eye.distanceTo(threat.getEyePosition());boolean cover=level.clip(new ClipContext(eye,threat.getEyePosition(),ClipContext.Block.COLLIDER,ClipContext.Fluid.NONE,player)).getType()!=HitResult.Type.MISS;return -Math.min(away,12)*2+(cover?-10:0)+travel*.15;}
    double side=(c.x()+.5-p.x)*sideX+(c.z()+.5-p.z)*sideZ;return d+travel*.12+(unshielded&&ReactiveDefensePolicy.ranged(type(threat))?Math.abs(side-1.25)*.18:0);
   },terrain,12,384);planAt=now;next=path.isEmpty()?null:path.get(0);plannedFrom=p;
  }
  if(next==null){
   if(progressAt==0)progressAt=now;
   if(now-progressAt>1_500_000_000L){noProgress(mc,threat,escape,now);target=null;progressAt=0;}
   return NativeBlazeEscort.Step.waitFor("local_route_temporarily_unavailable_reselect");
  }
  Vec3 goal=new Vec3(next.x()+.5,next.y(),next.z()+.5);double d=p.distanceTo(goal);
  if(d<best-.025){best=d;progressAt=now;}else if(progressAt>0&&now-progressAt>2_000_000_000L){noProgress(mc,threat,escape,now);path=List.of();next=null;target=null;return NativeBlazeEscort.Step.waitFor("local_no_progress_reselect");}
  if(Math.hypot(p.x-goal.x,p.z-goal.z)<.2&&Math.abs(p.y-goal.y)<.4){pathSteps++;path=List.of();next=null;best=Double.POSITIVE_INFINITY;return NativeBlazeEscort.Step.waitFor("local_step_arrived");}
  if(!motionAllowed(mc)){path=List.of();next=null;return NativeBlazeEscort.Step.waitFor("local_step_changed_replan");}
  double dx=goal.x-p.x,dz=goal.z-p.z;
  if(escape&&!NativeBlazeEscort.escapeDirectionNonClosing(p.x,p.z,dx,dz,threat.getX(),threat.getZ())){next=null;path=List.of();return NativeBlazeEscort.Step.waitFor("escape_does_not_close_threat");}
  float routeYaw=(float)Math.toDegrees(Math.atan2(-dx,dz));float[] v=NativeBlazeEscort.relativeMotion(routeYaw,player.getYRot(),1);
  return new NativeBlazeEscort.Step(v[0],v[1],goal.y>p.y+.25&&player.onGround(),null,escape?"escape_fresh_local_steps":"approach_fresh_local_steps");
 }
 private void noProgress(Minecraft mc,Entity threat,boolean escape,long now){
  cooling.put(threat.getUUID().toString(),now+2_000_000_000L);
  if(escape&&threat instanceof Mob mob&&!(threat instanceof Creeper)){
   for(Contact c:contacts(mc,config))if(c.entity==mob){stalled.put(mob.getUUID().toString(),new ReactiveDefensePolicy.Stalled(player.getX(),player.getY(),player.getZ(),mob.getX(),mob.getY(),mob.getZ(),player.getHealth(),c.visible,c.self));evidence.addProperty("local_no_progress_target_deferred",mob.getUUID().toString());break;}
  }
 }
 boolean motionAllowed(Minecraft mc){
  owner(mc);if(next==null)return true;Vec3 p=player.position();double dx=next.x()+.5-p.x,dz=next.z()+.5-p.z,len=Math.hypot(dx,dz);if(len<.01)return true;
  if(plannedFrom!=null&&p.distanceTo(plannedFrom)>4)return false;
  if(!standable(mc,next))return false;double s=Math.min(.35,len)/len;
  AABB box=player.getBoundingBox().move(dx*s,0,dz*s);int dy=Integer.compare(next.y(),(int)Math.floor(p.y+.05));
  if(level.noCollision(player,box)&&supported(box))return true;
  if(dy==1&&level.noCollision(player,box.move(0,1,0))&&supported(box.move(0,1,0)))return true;
  if(dy==-1&&level.noCollision(player,box)&&supported(box.move(0,-1,0)))return true;
  return !player.onGround()&&level.noCollision(player,box)&&standable(mc,next);
 }
 private boolean supported(AABB box){return !level.noCollision(player,box.move(0,-.15,0));}
 private boolean standable(Minecraft mc,ReactiveLocalPlanner.Cell c){
  AABB box=new AABB(c.x()+.2,c.y()+.01,c.z()+.2,c.x()+.8,c.y()+1.79,c.z()+.8);
  for(BlockPos pos:BlockPos.betweenClosed(BlockPos.containing(box.minX,box.minY-.2,box.minZ),BlockPos.containing(box.maxX,box.maxY,box.maxZ))){if(!level.hasChunkAt(pos)||level.getFluidState(pos).is(FluidTags.LAVA))return false;}
  if(!level.noCollision(player,box)||!supported(box))return false;
  // Shallow supported water is traversable; do not plan head-submerged ground routes.
  return level.getFluidState(BlockPos.containing(c.x()+.5,c.y()+1.6,c.z()+.5)).isEmpty();
 }
 private boolean edgeClear(Minecraft mc,ReactiveLocalPlanner.Cell a,ReactiveLocalPlanner.Cell b){
  int dy=b.y()-a.y();if(Math.abs(dy)>1)return false;double high=Math.max(a.y(),b.y())+.01;
  AABB swept=new AABB(Math.min(a.x(),b.x())+.2,high,Math.min(a.z(),b.z())+.2,Math.max(a.x(),b.x())+.8,high+1.78,Math.max(a.z(),b.z())+.8);
  return level.noCollision(player,swept)&&standable(mc,b);
 }
 private boolean ray(Minecraft mc,Mob t){return !t.isRemoved()&&t.isAlive()&&mc.hitResult instanceof EntityHitResult h&&h.getEntity()==t&&CombatRules.rayInReach(true,player.getEyePosition().distanceTo(h.getLocation()),player.entityInteractionRange());}
 private void checkDeaths(Minecraft mc){var source=NativeLivingObservation.capture(mc);for(var e:tracked.entrySet())if(!dead.contains(e.getKey())){
  Mob m=e.getValue();JsonObject row=NativeLivingSnapshot.json(source.batch(),NativeLivingObservation.current(source)?source.context():null,level.dimension().location().toString(),WorldGeneration.current(level),player.getUUID().toString(),e.getKey(),m.getId(),type(m),level.getGameTime(),System.nanoTime());
  boolean serverDead=row.get("known").getAsBoolean()&&!row.get("alive").getAsBoolean();
  if(serverDead||ReactiveDefensePolicy.clientDead(m.isRemoved(),m.getHealth())){dead.add(e.getKey());JsonObject proof=new JsonObject();proof.addProperty("uuid",e.getKey());proof.addProperty("type",type(m));proof.addProperty("source",serverDead?"fresh_integrated_server":"client_nonremoved_health_zero");if(serverDead)proof.add("native_living",row);deaths.add(proof);}
 }}
 private void aim(Minecraft mc,Vec3 point){Vec3 d=point.subtract(player.getEyePosition());owner(mc);player.setYRot((float)Math.toDegrees(Math.atan2(-d.x,d.z)));owner(mc);player.setXRot((float)-Math.toDegrees(Math.atan2(d.y,Math.hypot(d.x,d.z))));owner(mc);player.setYHeadRot(player.getYRot());owner(mc);}
 private void shield(Minecraft mc,boolean want){owner(mc);want=want&&player.getOffhandItem().is(Items.SHIELD)&&!player.getCooldowns().isOnCooldown(Items.SHIELD);if(!want){releaseShield(mc,()->owner(mc));return;}if(!player.isUsingItem()){
  shieldOwned=true;NativeBlazeEscort.inputAttempt(result,()->mc.gameMode.useItem(player,InteractionHand.OFF_HAND),()->own(mc));owner(mc);
  if(player.isUsingItem()&&player.getUsedItemHand()==InteractionHand.OFF_HAND&&player.getUseItem().is(Items.SHIELD)){mc.options.keyUse.setDown(true);owner(mc);}else releaseShield(mc,()->owner(mc));
 }}
 private void releaseShield(Minecraft mc,Runnable fence){if(!shieldOwned)return;fence.run();mc.options.keyUse.setDown(false);fence.run();if(mc.player==player&&mc.gameMode!=null&&player.isUsingItem())mc.gameMode.releaseUsingItem(player);fence.run();shieldOwned=false;}
 void release(Minecraft mc,Runnable fence){releaseShield(mc,fence);fence.run();evidence.addProperty("cleanup_completed",true);}
 private void record(int tick,String state,Contact c){if(!state.equals(phase)){phase=state;changeCount++;if(changes.size()<128){JsonObject j=new JsonObject();j.addProperty("tick",tick);j.addProperty("phase",state);j.addProperty("health",player.getHealth());changes.add(j);}}
  evidence.addProperty("phase",phase);evidence.addProperty("attack_attempts",attacks);evidence.addProperty("blocking_ticks",blockingTicks);evidence.addProperty("shield_available",player.getOffhandItem().is(Items.SHIELD));evidence.addProperty("actually_blocking",player.isBlocking());evidence.addProperty("use_ticks",player.getTicksUsingItem());evidence.addProperty("minimum_health",minHealth);evidence.addProperty("health",player.getHealth());evidence.addProperty("observed_damage",damage);evidence.addProperty("known_dead_observations",dead.size());evidence.addProperty("local_steps_completed",pathSteps);evidence.addProperty("transitions_total",changeCount);}
}
