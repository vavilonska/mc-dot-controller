package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.function.BooleanSupplier;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.Mob;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.item.AxeItem;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.SwordItem;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.Vec3;

/** Opt-in ordinary follow_path owner. Only vanilla view, movement, use and attack inputs.
 * No new registry, packets, world/entity/inventory/position/velocity writes or remote planner. */
final class NativeBlazeEscort {
    record Config(boolean shield,double stopHealth,double maximumDamage,int fireMs,int engageMs,int holdMs,Set<String> targetTypes,boolean creeperEscape) { }
    static final Set<String> SUPPORTED_TARGET_TYPES=Set.of("minecraft:blaze","minecraft:zombie","minecraft:drowned","minecraft:husk");
    record Step(float forward,float strafe,boolean jump,String terminal,String reason) {
        Step(float forward,boolean jump,String terminal,String reason){this(forward,0,jump,terminal,reason);}
        static Step waitFor(String why){return new Step(0,false,null,why);}
        static Step end(String status,String why){return new Step(0,false,status,why);}
    }
    private final LocalPlayer player;
    private final ClientLevel level;
    private final Config config;
    private final BlazeEscortPolicy policy;
    private final BlazeEscortPolicy.Route route;
    private final JsonObject evidence;
    private JsonObject originalResult;
    private final JsonArray transitions=new JsonArray();
    private BooleanSupplier owned=()->false;
    private boolean shieldOwned,returnStarted,jumped,attemptInFlight;
    private int stableTicks,stuckTicks,blockingTicks,triggerCount,unknownAggro,attackTicks,transitionCount;
    private final BlazeEscortPolicy.Progress movementProgress=new BlazeEscortPolicy.Progress();
    private long heldAt=-1,blockedAt=-1;
    private String previousPhase="",previousReason="";
    private Vec3 navigationStart;
    private NativeThreatObservation.Contact escapeThreat;
    private float escapeYaw;
    private long escapeBlocked=-1;
    private final boolean portalDeparture;

    static Config validate(ClientActionRequest request) {
        JsonObject body=request.original();
        if(!body.has("blaze_guard"))return null;
        require(request.action().equals("follow_path"),"blaze_guard_requires_follow_path");
        require(!body.has("capability_guard")&&!body.has("coordination_step")&&!body.has("capability_route")&&!body.has("sprint"),"blaze_guard_plain_ordinary_owner_required");
        require(body.get("blaze_guard").isJsonObject(),"blaze_guard_object_required");
        JsonObject p=body.getAsJsonObject("blaze_guard");
        var fields=new java.util.HashSet<>(p.keySet());fields.remove("target_types");fields.remove("creeper_escape");
        require(fields.equals(Set.of("schema_version","known_route","shield","stop_health","maximum_observed_damage","continuous_fire_ms","engage_timeout_ms","arrival_hold_ms")),"blaze_guard_closed_fields");
        Set<String> targetTypes=targetTypes(p);
        require(ClientActionRequest.integer(p,"schema_version",0)==1 && ClientActionRequest.bool(p,"known_route",false),"blaze_guard_known_route_required");
        for(String k:List.of("expected_world_generation","expected_player_uuid","expected_action_session")) {
            try {UUID.fromString(ClientActionRequest.string(body,k));}catch(IllegalArgumentException e){throw new ClientActionRequest.Rejected(400,"invalid_"+k);}
        }
        require(body.has("expected_navigation_epoch")&&body.has("expected_origin"),"blaze_guard_original_navigation_binding_required");
        double stop=number(p,"stop_health"),damage=number(p,"maximum_observed_damage");
        int fire=ClientActionRequest.integer(p,"continuous_fire_ms",0),engage=ClientActionRequest.integer(p,"engage_timeout_ms",0),hold=ClientActionRequest.integer(p,"arrival_hold_ms",-1);
        require(stop>0&&stop<20&&damage>0&&damage<=100,"blaze_guard_health_policy_bounds");
        require(fire>=1000&&fire<=30000&&engage>=1000&&engage<=60000&&hold>=0&&hold<=600000,"blaze_guard_time_bounds");
        require(request.timeoutMs()>=1000,"blaze_guard_job_timeout_too_short");
        require(!request.sneak(),"blaze_guard_route_walk_not_sneak");
        JsonObject origin=body.getAsJsonObject("expected_origin");
        double x=number(origin,"x"),y=number(origin,"y"),z=number(origin,"z");
        for(var point:request.waypoints()) {
            require(Math.abs(point.y()-y)<=1.25&&Math.hypot(point.x()-x,point.z()-z)<=16,"blaze_guard_known_segment_bounds");
            x=point.x();y=point.y();z=point.z();
        }
        return new Config(ClientActionRequest.bool(p,"shield",false),stop,damage,fire,engage,hold,targetTypes,ClientActionRequest.bool(p,"creeper_escape",false));
    }
    static Set<String> targetTypes(JsonObject settings) {
        if(!settings.has("target_types"))return Set.of("minecraft:blaze");
        var value=settings.get("target_types");require(value.isJsonArray(),"target_types_array_required");
        var result=new java.util.HashSet<String>();
        require(value.getAsJsonArray().size()>=1&&value.getAsJsonArray().size()<=4,"target_types_count_1_to_4");
        for(var item:value.getAsJsonArray()) {
            require(item.isJsonPrimitive()&&item.getAsJsonPrimitive().isString(),"target_type_string_required");
            String type=item.getAsString();require(SUPPORTED_TARGET_TYPES.contains(type),"escort_target_type_unsupported");
            require(result.add(type),"duplicate_escort_target_type");
        }
        return Set.copyOf(result);
    }
    NativeBlazeEscort(Minecraft mc,ClientActionRequest request,JsonObject evidence) {
        config=validate(request);this.evidence=evidence;player=mc.player;level=mc.level;
        portalDeparture=request.original().has("portal_handoff_parent");
        if(!mc.hasSingleplayerServer()||mc.getSingleplayerServer()==null||mc.getSingleplayerServer().isPublished())reject("blaze_guard_private_singleplayer_required");
        if(player==null||level==null||!weapon(player))reject("blaze_guard_selected_sword_or_axe_required");
        JsonObject o=request.original().getAsJsonObject("expected_origin");
        route=new BlazeEscortPolicy.Route(request.waypoints(),new ClientActionRequest.Point(number(o,"x"),number(o,"y"),number(o,"z"),false));
        navigationStart=player.position();
        policy=new BlazeEscortPolicy(player.getHealth(),config.stopHealth,config.maximumDamage,config.fireMs,config.engageMs);
        evidence.addProperty("schema_version",1);evidence.addProperty("single_native_owner",true);
        JsonArray types=new JsonArray();config.targetTypes.stream().sorted().forEach(types::add);evidence.add("configured_target_types",types);
        evidence.addProperty("uses_server_target_snapshot",true);evidence.addProperty("shield_requested",config.shield);
        evidence.add("transitions",transitions);
    }
    void bind(BooleanSupplier owner,JsonObject result){owned=owner;originalResult=result;}
    private static JsonObject dispatchOriginal;
    static boolean dispatchInFlight(){return dispatchOriginal!=null;}
    static void inputAttempt(JsonObject original,Runnable effect,BooleanSupplier stillOwner) {
        if(dispatchOriginal!=null)throw new IllegalStateException("blaze_guard_nested_dispatch_forbidden");
        if(original.has("unknown_outcome")&&original.get("unknown_outcome").getAsBoolean())throw new IllegalStateException("original_input_unresolved_no_reissue");
        original.addProperty("unknown_outcome",true);original.addProperty("requires_handoff",true);
        dispatchOriginal=original;
        try {
            effect.run();
            if(!stillOwner.getAsBoolean())throw new IllegalStateException("blaze_guard_owner_changed_during_input");
            original.remove("unknown_outcome");original.remove("requires_handoff");
        } finally {dispatchOriginal=null;}
    }
    private void owner(Minecraft mc){if(!owned.getAsBoolean()||mc.player!=player||mc.level!=level||mc.gameMode==null||!mc.hasSingleplayerServer()||mc.getSingleplayerServer()==null||mc.getSingleplayerServer().isPublished())throw new IllegalStateException("blaze_guard_owner_changed");}

    Step tick(Minecraft mc,int tick,long deadline) {
        owner(mc);long now=System.nanoTime();
        policy.health(player.getHealth(),player.isOnFire(),player.isInLava()||player.isInWater()||player.isInPowderSnow,now);
        policy.deadline(now);
        if(!weapon(player))policy.beginReturn("selected_weapon_unavailable");
        if(player.isBlocking())blockingTicks++;
        if(config.creeperEscape){
            var threat=NativeThreatObservation.creeper(mc);
            if(threat!=null){if(escapeThreat==null)escapeYaw=player.getYRot();escapeThreat=threat;
                evidence.add("creeper_escape_trigger",threat.json());if(!portalDeparture)policy.beginReturn("creeper_threat_escape");}
        }
        // Leave enough of the existing job lifetime for the known prefix; never extend it.
        if(!portalDeparture && policy.phase!=BlazeEscortPolicy.Phase.RETURNING && deadline-now<estimatedReturnNanos())policy.beginReturn("job_deadline_return_reserve");
        Step step;
        if(portalDeparture&&(escapeThreat!=null||policy.phase==BlazeEscortPolicy.Phase.RETURNING)){
            step=departure(mc,now);
        } else if(policy.phase==BlazeEscortPolicy.Phase.RETURNING)step=retreat(mc,tick,now);
        else {
            if(policy.phase!=BlazeEscortPolicy.Phase.ENGAGING) {
                var candidate=observeCandidate(mc);
                if(candidate!=null){policy.acquire(candidate,now);triggerCount++;resetMotion();}
            }
            if(policy.phase==BlazeEscortPolicy.Phase.ENGAGING)step=engage(mc,tick,now);
            else step=navigate(mc,tick,now);
        }
        record(tick,step);return step;
    }
    private BlazeEscortPolicy.Contact observeCandidate(Minecraft mc) {
        var source=NativeLivingObservation.capture(mc);
        var contacts=new ArrayList<BlazeEscortPolicy.Contact>();unknownAggro=0;
        for(Mob blaze:level.getEntitiesOfClass(Mob.class,player.getBoundingBox().inflate(16),e->e.isAlive()&&!e.isRemoved()&&config.targetTypes.contains(entityType(e)))) {
            if(contacts.size()>=128)break;
            if(!policy.mayAcquire(blaze.getUUID().toString()))continue;
            JsonObject entity=new JsonObject();NativeLivingObservation.append(mc,blaze,entity,source);
            JsonObject n=entity.getAsJsonObject("native_living");
            boolean known=n!=null&&n.has("known")&&n.get("known").getAsBoolean();
            boolean targets=known&&n.has("current_target")&&!n.get("current_target").isJsonNull()
                &&n.getAsJsonObject("current_target").get("uuid").getAsString().equals(player.getUUID().toString());
            if(!known)unknownAggro++;
            double d=eyeDistance(player.getEyePosition(),blaze.getBoundingBox());
            boolean reachable=d<=Math.min(3,player.entityInteractionRange())&&player.hasLineOfSight(blaze);
            contacts.add(new BlazeEscortPolicy.Contact(blaze.getUUID().toString(),blaze.getId(),entityType(blaze),d,true,reachable,targets));
            if(targets){evidence.add("latest_target_player_source",n.deepCopy());}
        }
        return BlazeEscortPolicy.candidate(contacts);
    }
    private Step engage(Minecraft mc,int tick,long now) {
        // Client health/removal packets need not expose the server's death interval. Read the
        // existing immutable, identity-bound server snapshot before treating absence as a loss.
        var deathFrame=NativeLivingObservation.capture(mc);
        JsonObject death=serverDeathEvidence(deathFrame.batch(),NativeLivingObservation.current(deathFrame)?deathFrame.context():null,
            level.dimension().location().toString(),WorldGeneration.current(level),player.getUUID().toString(),
            policy.targetUuid,policy.targetId,policy.targetType,level.getGameTime(),now);
        if(death!=null) {
            evidence.add("confirmed_target_death",death);
            policy.targetDead();shield(mc,false);navigationStart=player.position();resetMotion();
            return Step.waitFor("server_target_dead_observed_resume_route");
        }
        Entity e=level.getEntity(policy.targetId);
        if(e==null || !e.getUUID().toString().equals(policy.targetUuid)) {policy.targetLost();return retreat(mc,tick,now);}
        if(!(e instanceof Mob target)||!entityType(e).equals(policy.targetType)||!config.targetTypes.contains(policy.targetType)){policy.targetLost();return retreat(mc,tick,now);}
        if(!target.isAlive()) {
            policy.targetDead();shield(mc,false);navigationStart=player.position();resetMotion();
            return Step.waitFor("target_dead_observed_resume_route");
        }
        if(target.isRemoved()){policy.targetLost();return retreat(mc,tick,now);}
        if(policy.phase==BlazeEscortPolicy.Phase.RETURNING)return retreat(mc,tick,now);
        float navigationYaw=player.getYRot(); // Preserve prior route steering before the fresh combat pick.
        aim(mc,target.getBoundingBox().getCenter());
        owner(mc);mc.gameRenderer.pick(1.0F);owner(mc);
        boolean ray=ray(mc,target);double strength=player.getAttackStrengthScale(.5F);
        evidence.addProperty("target_health",target.getHealth());evidence.addProperty("target_picked_in_reach",ray);
        evidence.addProperty("attack_strength",strength);evidence.addProperty("target_uuid",policy.targetUuid);evidence.addProperty("target_type",policy.targetType);
        if(!ray)return approachOnOriginalRoute(mc,target,tick,now,navigationYaw);
        movementProgress.reset(); // Deliberate in-reach combat is not failed navigation progress.
        if(!CombatRules.cooldownReady(strength)) {shield(mc,config.shield);return Step.waitFor("cooldown_shield");}
        if(shieldOwned||player.isUsingItem()){shield(mc,false);return Step.waitFor("lowering_shield_for_cooldown_ready_attack");}
        // A fresh pick/reach/cooldown check after the last input hook. No stored ray is attack authority.
        owner(mc);mc.gameRenderer.pick(1.0F);owner(mc);
        if(!policy.mayAttack(tick,ray(mc,target),player.getAttackStrengthScale(.5F),player.isUsingItem()))return Step.waitFor("attack_precondition_changed");
        policy.attackAttempt(tick);attackTicks++;attemptInFlight=true;
        try {inputAttempt(originalResult,()->mc.startAttack(),owned);owner(mc);attemptInFlight=false;}
        catch(RuntimeException uncertain){evidence.addProperty("unknown_attack_outcome",true);throw uncertain;}
        shield(mc,config.shield);
        return Step.waitFor("attack_dispatched_once");
    }
    private Step approachOnOriginalRoute(Minecraft mc,Mob target,int tick,long now,float navigationYaw) {
        AABB box=target.getBoundingBox();
        boolean canReach=BlazeEscortPolicy.routeCanReach(route.points,route.next,new ClientActionRequest.Point(player.getX(),player.getY(),player.getZ(),false),player.getEyePosition().y-player.getY(),
            box.minX,box.minY,box.minZ,box.maxX,box.maxY,box.maxZ,Math.min(3,player.entityInteractionRange()));
        evidence.addProperty("original_remaining_route_can_reach",canReach);
        if(route.outboundDone()||!canReach){policy.beginReturn("no_reachable_point_on_original_route");return retreat(mc,tick,now);}
        shield(mc,config.shield);
        Step moved=move(mc,route.outbound(),false,now,navigationYaw);
        if(moved.terminal()!=null){policy.beginReturn(moved.reason());return retreat(mc,tick,now);}
        if(moved.reason().equals("waypoint_settled")) {
            navigationStart=point(route.outbound());route.arrived();resetMotion();
            return Step.waitFor("engagement_original_waypoint_complete");
        }
        // No target-coordinate waypoint, extra jump or reset of target/deadline is introduced.
        return new Step(moved.forward(),moved.jump(),null,moved.forward()>0?"approaching_on_original_route":moved.reason());
    }
    private Step navigate(Minecraft mc,int tick,long now) {
        if(route.outboundDone()) {
            if(config.holdMs==0)return Step.end("succeeded","blaze_guard_route_reached");
            policy.phase=BlazeEscortPolicy.Phase.HOLDING;
            if(heldAt<0)heldAt=now;
            if(now-heldAt>=config.holdMs*1_000_000L){policy.beginReturn("arrival_hold_completed");return retreat(mc,tick,now);}
            shield(mc,config.shield);return Step.waitFor("arrival_guard_armed");
        }
        shield(mc,false);
        var step=move(mc,route.outbound(),false,now);
        if(step.terminal()!=null){policy.beginReturn(step.reason());return retreat(mc,tick,now);}
        if(step.reason().equals("waypoint_settled")){navigationStart=point(route.outbound());route.arrived();resetMotion();return Step.waitFor("route_waypoint_complete");}
        return step;
    }
    private Step departure(Minecraft mc,long now) {
        // This is an explicitly pre-authorized destination exit, not an unwalked return prefix.
        // A health/engagement budget stops further attacks, but must not send the player back into the portal.
        if(route.outboundDone())return Step.end("succeeded","portal_departure_complete");
        if(escapeThreat!=null)return escape(mc,route.outbound(),now);
        shield(mc,config.shield);Step step=move(mc,route.outbound(),false,now);
        if(step.terminal()!=null)return Step.end("failed","portal_departure_blocked:"+step.reason());
        if(step.reason().equals("waypoint_settled")){navigationStart=point(route.outbound());route.arrived();resetMotion();}
        return step;
    }
    private Step retreat(Minecraft mc,int tick,long now) {
        if(portalDeparture)return departure(mc,now);
        if(!returnStarted){route.beginReturn();returnStarted=true;navigationStart=player.position();resetMotion();}
        var goal=route.retreat();
        if(escapeThreat!=null)return escape(mc,goal,now);
        shield(mc,false); // Ordinary retreat retains its original behavior.
        var step=move(mc,goal,true,now);
        if(step.terminal()!=null)return Step.end("failed","blaze_guard_return_blocked:"+step.reason());
        if(step.reason().equals("waypoint_settled")) {
            navigationStart=point(goal);resetMotion();
            if(route.returnArrived()){policy.phase=BlazeEscortPolicy.Phase.DONE;return Step.end("succeeded","blaze_guard_returned_to_cover");}
            return Step.waitFor("return_waypoint_complete");
        }
        return step;
    }
    /** Same owner, same already-walked return prefix; no melee attempt against a fuse. */
    private Step escape(Minecraft mc,ClientActionRequest.Point goal,long now) {
        var current=NativeThreatObservation.creeper(mc);
        if(current!=null)escapeThreat=current;
        Entity entity=level.getEntity(escapeThreat.id());
        boolean same=entity instanceof net.minecraft.world.entity.monster.Creeper && entity.isAlive()
            &&entity.getUUID().toString().equals(escapeThreat.uuid());
        if(!same){escapeThreat=null;escapeBlocked=-1;return portalDeparture?departure(mc,now):retreat(mc,0,now);}
        Vec3 p=player.position(),q=point(goal),e=entity.position();
        boolean alreadyThere=Math.hypot(q.x-p.x,q.z-p.z)<.25 && Math.abs(q.y-p.y)<.6;
        // A verified prefix can still lead toward the current threat. Do not walk into it.
        if(!alreadyThere&&!escapeDirectionNonClosing(p.x,p.z,q.x-p.x,q.z-p.z,e.x,e.z)) {
            aim(mc,entity.getBoundingBox().getCenter());shield(mc,true);
            if(escapeBlocked<0)escapeBlocked=now;
            return now-escapeBlocked>=2_000_000_000L?Step.end("failed","creeper_escape_known_prefix_toward_threat"):Step.waitFor("creeper_escape_blocked_shield");
        }
        escapeBlocked=-1;
        Step moved=move(mc,goal,true,now,escapeYaw);escapeYaw=player.getYRot();
        if(moved.terminal()!=null)return Step.end("failed","creeper_escape_return_blocked:"+moved.reason());
        aim(mc,entity.getBoundingBox().getCenter());shield(mc,true);
        if(moved.reason().equals("waypoint_settled")){
            navigationStart=point(goal);resetMotion();
            if(portalDeparture){route.arrived();return route.outboundDone()?Step.end("succeeded","portal_departure_complete"):Step.waitFor("portal_escape_waypoint_complete");}
            if(route.returnArrived()){policy.phase=BlazeEscortPolicy.Phase.DONE;return Step.end("succeeded","creeper_escape_returned_known_origin_not_safety_proof");}
            return Step.waitFor("creeper_escape_return_waypoint_complete");
        }
        // A limited turn can temporarily point across the threat even when the desired segment is safe.
        if(moved.forward()>0&&!escapeDirectionNonClosing(p.x,p.z,-Math.sin(Math.toRadians(escapeYaw)),Math.cos(Math.toRadians(escapeYaw)),e.x,e.z))
            return Step.waitFor("creeper_escape_turning_without_closing");
        float[] v=relativeMotion(escapeYaw,player.getYRot(),moved.forward());
        return new Step(v[0],v[1],moved.jump(),null,"creeper_escape_shield_known_prefix");
    }
    static boolean escapeDirectionNonClosing(double px,double pz,double dx,double dz,double ex,double ez){
        return Double.isFinite(px+pz+dx+dz+ex+ez)&&(px-ex)*dx+(pz-ez)*dz>=-1e-8;
    }
    static float[] relativeMotion(float routeYaw,float shieldYaw,float forward){
        double d=Math.toRadians(routeYaw-shieldYaw);return new float[]{(float)(Math.cos(d)*forward),(float)(-Math.sin(d)*forward)};
    }
    private Step move(Minecraft mc,ClientActionRequest.Point goal,boolean returning,long now) {
        return move(mc,goal,returning,now,player.getYRot());
    }
    private Step move(Minecraft mc,ClientActionRequest.Point goal,boolean returning,long now,float navigationYaw) {
        owner(mc);var p=player.position();
        // Actual knockback position must remain joinable to this known segment; never assume a ray through a wall.
        if(horizontalSegmentDistance(p,navigationStart,point(goal))>1.25 || p.y<Math.min(navigationStart.y,goal.y())-1.5 || p.y>Math.max(navigationStart.y,goal.y())+2.0)
            return Step.end("failed","outside_known_segment_corridor");
        var effective=new ClientActionRequest.Point(goal.x(),goal.y(),goal.z(),goal.jump()&&!jumped);
        var step=PathSteering.toward(p.x,p.y,p.z,navigationYaw,player.onGround(),player.horizontalCollision,effective,true);
        if(step.reached()) {
            Vec3 v=player.getDeltaMovement();
            if(PathSteering.settledAt(p.x,p.y,p.z,v.x,v.z,player.onGround(),goal))stableTicks++;else stableTicks=0;
            return Step.waitFor(stableTicks>=2?"waypoint_settled":"settling_at_known_waypoint");
        }
        stableTicks=0;
        if(!loadedLocalStep(mc,goal)) {
            if(blockedAt<0)blockedAt=now;
            if(now-blockedAt>2_000_000_000L)return Step.end("failed","local_loaded_support_or_clearance_changed");
            return Step.waitFor("waiting_local_collision_support");
        }
        blockedAt=-1;
        owner(mc);player.setYRot(step.yaw());owner(mc);player.setYHeadRot(step.yaw());owner(mc);
        if(movementProgress.stuck(step.distance(),player.onGround(),now))return Step.end("failed","known_route_no_progress_4s");
        if(step.jump())jumped=true;
        return new Step(step.forward(),step.jump(),null,returning?"returning_known_prefix":"navigating_known_route");
    }
    /** Only the next physical step; partial support is valid. Unknown chunks/liquids are not a route. */
    private boolean loadedLocalStep(Minecraft mc,ClientActionRequest.Point goal) {
        Vec3 p=player.position();double dx=goal.x()-p.x,dz=goal.z()-p.z,len=Math.hypot(dx,dz);
        if(len<.01)return true;
        double scale=Math.min(.35,len)/len;
        AABB next=player.getBoundingBox().move(dx*scale,0,dz*scale);
        for(int dy:new int[]{0,1,-1}) {
            if(dy==1&&goal.y()<=p.y+.3&&!player.horizontalCollision)continue;
            if(dy==-1&&goal.y()>=p.y-.3)continue;
            AABB box=next.move(0,dy,0);boolean loaded=true;
            for(BlockPos cell:BlockPos.betweenClosed(BlockPos.containing(box.minX,box.minY-.12,box.minZ),BlockPos.containing(box.maxX,box.maxY,box.maxZ))) {
                if(!level.hasChunkAt(cell)||!level.getFluidState(cell).isEmpty()){loaded=false;break;}
            }
            if(loaded&&level.noCollision(player,box)&&!level.noCollision(player,box.move(0,-.12,0)))return true;
        }
        // During a native jump, retain only verified destination support; never invent extra jumping.
        return !player.onGround()&&level.hasChunkAt(BlockPos.containing(goal.x(),goal.y()-1,goal.z()))
            &&level.getFluidState(BlockPos.containing(goal.x(),goal.y()-1,goal.z())).isEmpty()
            &&!level.noCollision(player,player.getBoundingBox().move(goal.x()-p.x,goal.y()-p.y-.12,goal.z()-p.z));
    }
    private boolean ray(Minecraft mc,Mob target){return mc.hitResult instanceof EntityHitResult h && h.getEntity()==target
        &&target.isAlive()&&player.hasLineOfSight(target)&&CombatRules.rayInReach(true,player.getEyePosition().distanceTo(h.getLocation()),player.entityInteractionRange());}
    private void aim(Minecraft mc,Vec3 center) {
        Vec3 d=center.subtract(player.getEyePosition());float yaw=(float)Math.toDegrees(Math.atan2(-d.x,d.z)),pitch=(float)-Math.toDegrees(Math.atan2(d.y,Math.hypot(d.x,d.z)));
        owner(mc);player.setYRot(yaw);owner(mc);player.setXRot(pitch);owner(mc);player.setYHeadRot(yaw);owner(mc);
    }
    private void shield(Minecraft mc,boolean wanted) {
        owner(mc);wanted=wanted&&player.getOffhandItem().is(Items.SHIELD)&&!player.getCooldowns().isOnCooldown(Items.SHIELD);
        if(!wanted){releaseShield(mc,()->owner(mc));return;}
        if(!player.isUsingItem()) {
            shieldOwned=true;owner(mc);inputAttempt(originalResult,()->mc.gameMode.useItem(player,InteractionHand.OFF_HAND),owned);owner(mc);
            if(player.isUsingItem()&&player.getUsedItemHand()==InteractionHand.OFF_HAND&&player.getUseItem().is(Items.SHIELD)){
                owner(mc);mc.options.keyUse.setDown(true);owner(mc);
            } else releaseShield(mc,()->owner(mc));
        }
    }
    void release(Minecraft mc,Runnable cleanupFence) {releaseShield(mc,cleanupFence);cleanupFence.run();evidence.addProperty("cleanup_completed",true);}
    private void releaseShield(Minecraft mc,Runnable fence) {
        if(!shieldOwned)return;
        fence.run();
        mc.options.keyUse.setDown(false);
        fence.run();
        if(mc.player==player&&mc.gameMode!=null&&player.isUsingItem())mc.gameMode.releaseUsingItem(player);
        fence.run();shieldOwned=false;
    }
    private void resetMotion(){stableTicks=stuckTicks=0;movementProgress.reset();blockedAt=-1;jumped=false;}
    private long estimatedReturnNanos(){double d=player.position().distanceTo(route.next==0?point(route.cover):point(route.points.get(route.next-1)));for(int i=route.next-1;i>=0;i--)d+=point(route.points.get(i)).distanceTo(i==0?point(route.cover):point(route.points.get(i-1)));return (long)((d/2.5+3)*1_000_000_000L);}
    private void record(int tick,Step step) {
        String phase=policy.phase.name();
        if(!phase.equals(previousPhase)||!step.reason().equals(previousReason)) {
            transitionCount++;
            if(transitions.size()<128){JsonObject e=new JsonObject();e.addProperty("tick",tick);e.addProperty("phase",phase);e.addProperty("reason",step.reason());e.addProperty("health",player.getHealth());transitions.add(e);}
            previousPhase=phase;previousReason=step.reason();
        }
        evidence.addProperty("phase",phase);evidence.addProperty("reason",step.reason());evidence.addProperty("return_cause",policy.reason);
        evidence.addProperty("waypoint_index",route.next);evidence.addProperty("return_prefix_index",route.returning);
        evidence.addProperty("attack_attempts",policy.attacks);evidence.addProperty("known_dead_observations",policy.kills);evidence.addProperty("lost_targets_not_kills",policy.lostTargets);
        evidence.addProperty("trigger_count",triggerCount);evidence.addProperty("aggro_unknown_count",unknownAggro);evidence.addProperty("blocking_ticks",blockingTicks);
        evidence.addProperty("health",player.getHealth());evidence.addProperty("observed_damage",policy.observedDamage);evidence.addProperty("on_fire",player.isOnFire());
        evidence.addProperty("transitions_total",transitionCount);evidence.addProperty("transitions_truncated",transitionCount>128);evidence.addProperty("attack_in_flight",attemptInFlight);
    }
    /** Missing/stale/unloaded is not death; server rows are collected only for non-removed mobs. */
    static JsonObject serverDeathEvidence(NativeLivingSnapshot.Batch batch,Object context,String dimension,String generation,
            String playerUuid,String targetUuid,int targetId,long tick,long now) {
        return serverDeathEvidence(batch,context,dimension,generation,playerUuid,targetUuid,targetId,"minecraft:blaze",tick,now);
    }
    static JsonObject serverDeathEvidence(NativeLivingSnapshot.Batch batch,Object context,String dimension,String generation,
            String playerUuid,String targetUuid,int targetId,String targetType,long tick,long now) {
        if(!SUPPORTED_TARGET_TYPES.contains(targetType))return null;
        JsonObject row=NativeLivingSnapshot.json(batch,context,dimension,generation,playerUuid,targetUuid,targetId,targetType,tick,now);
        if(!row.get("known").getAsBoolean() || row.get("alive").getAsBoolean())return null;
        row.addProperty("death_evidence","fresh_integrated_server_nonremoved_mob_not_alive");
        return row;
    }
    private static String entityType(Entity entity){return BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString();}
    static boolean weapon(LocalPlayer player){return player.getMainHandItem().getItem() instanceof SwordItem || player.getMainHandItem().getItem() instanceof AxeItem;}
    static double eyeDistance(Vec3 eye,AABB box){double x=Math.max(box.minX,Math.min(box.maxX,eye.x)),y=Math.max(box.minY,Math.min(box.maxY,eye.y)),z=Math.max(box.minZ,Math.min(box.maxZ,eye.z));return eye.distanceTo(new Vec3(x,y,z));}
    static double horizontalSegmentDistance(Vec3 p,Vec3 a,Vec3 b){double dx=b.x-a.x,dz=b.z-a.z,n=dx*dx+dz*dz,t=n==0?0:Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.z-a.z)*dz)/n));return Math.hypot(p.x-a.x-t*dx,p.z-a.z-t*dz);}
    private static Vec3 point(ClientActionRequest.Point p){return new Vec3(p.x(),p.y(),p.z());}
    private static double number(JsonObject p,String k){var v=p.get(k);require(v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isNumber()&&Double.isFinite(v.getAsDouble()),"invalid_"+k);return v.getAsDouble();}
    private static void require(boolean b,String r){ClientActionRequest.require(b,r);}
    private static void reject(String r){throw new ClientActionRequest.Rejected(409,r);}
}
