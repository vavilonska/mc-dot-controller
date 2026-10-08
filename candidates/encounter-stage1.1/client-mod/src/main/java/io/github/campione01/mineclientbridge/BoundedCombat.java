package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
import java.util.ArrayList;
import java.util.List;
import net.minecraft.world.entity.NeutralMob;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.phys.AABB;
import net.minecraft.client.Minecraft;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.item.AxeItem;
import net.minecraft.world.item.SwordItem;
import net.minecraft.world.item.Items;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.Vec3;

/** Bounded, real-client tick loop. ClientActions owns lifetime, cancellation and movement. */
final class BoundedCombat {
    record Step(float forward, String terminal, String reason) {
        static Step waitFor(String phase) { return new Step(0, null, phase); }
        static Step end(String status, String reason) { return new Step(0, status, reason); }
    }
    private final BoundedCombatRequest request;
    private final JsonObject evidence;
    private final Vec3 origin;
    private final BoundedEncounter encounter;
    private final CombatRecovery recovery = new CombatRecovery();
    private final CombatPursuit pursuit = new CombatPursuit();
    private boolean shieldOwned;
    private final CombatDetour detour = new CombatDetour();
    private final CombatRouteMotion routeMotion = new CombatRouteMotion();
    private final CombatRetreatPolicy.Progress retreatProgress = new CombatRetreatPolicy.Progress();
    private final CombatThreats.HealthGuard healthGuard = new CombatThreats.HealthGuard();
    private CombatThreats.Snapshot threats;
    private List<CombatSpatial.Box> obstacles = List.of();
    private CombatCellCache tickCells;
    private TerrainReader.ReadMetrics tickTerrainReads;
    private CombatRetreatWindow.Metrics retreatWindowMetrics;
    private CombatRetreatDiagnostics pendingRetreatDiagnostics;
    private JsonObject pendingRetreatEvidence;
    private boolean pendingRetreatPlan;
    private int waypointIndex, retreatStartTick = -1, healthTriggerTick = -1;
    private long retreatStartNanos;
    private String safetyReason;
    private CombatDetour.Point retreatGoal;
    private double retreatDistance;
    private Vec3 previousRetreatPose;
    private FlatStepCorridor.Result lastRouteTerrain;
    private String lastRouteReason = "not_checked";
    private Vec3 lastDecisionPlayer, lastDecisionTarget;
    private String lastDecisionPhase;
    private final JsonObject phaseMotion = new JsonObject();
    private float expectedYaw, expectedPitch;
    private float lastPlayerHealth, lastTargetHealth;
    private double playerHealthLost, targetHealthLost;
    private int attacks, healthDecreases, shieldBlockingTicks, currentTick;
    private int lastAttackTick = -1, selectedTick = -1;

    BoundedCombat(Minecraft mc, BoundedCombatRequest request, JsonObject evidence, long deadline) {
        this.request = request;
        this.evidence = evidence;
        if (!request.world().equals(WorldGeneration.current(mc.level))
                || !request.player().equals(mc.player.getUUID().toString())
                || !request.session().equals(ClientActions.session())) reject("bounded_combat_context_changed");
        if (mc.screen != null || mc.isPaused() || !mc.player.isAlive() || mc.player.isSpectator())
            reject("bounded_combat_player_unavailable");
        LivingEntity target = target(mc);
        if (target == null || !target.isAlive()) reject("bounded_combat_target_unavailable");
        if (!weapon(mc.player.getMainHandItem().getItem())) reject("bounded_combat_requires_selected_weapon");
        origin = mc.player.position();
        encounter = request.encounter()==null ? null : new BoundedEncounter(request.encounter(), evidence,
                origin.x,origin.y,origin.z,deadline,System::nanoTime,healthGuard);
        expectedYaw = mc.player.getYRot(); expectedPitch = mc.player.getXRot();
        lastPlayerHealth = mc.player.getHealth(); lastTargetHealth = target.getHealth();
        CombatInitialEvidence.initialize(request,evidence,lastPlayerHealth,lastTargetHealth);
    }


    Step tick(Minecraft mc, int tick) {
        currentTick = tick;
        pendingRetreatDiagnostics=null;pendingRetreatEvidence=null;pendingRetreatPlan=false;
        Step step = tickCombat(mc, tick);
        evidence.addProperty("combat_tick", tick);
        evidence.addProperty("requested_forward", step.forward());
        evidence.addProperty("shield_owned", shieldOwned);
        evidence.addProperty("using_item_after_decision", mc.player.isUsingItem());
        evidence.addProperty("blocking_after_decision", mc.player.isBlocking());
        observeDecisionMotion(mc, target(mc), step.reason());
        evidence.addProperty("decision_phase", step.reason());
        JsonObject pose = new JsonObject();
        number(pose,"x",mc.player.getX()); number(pose,"y",mc.player.getY()); number(pose,"z",mc.player.getZ());
        number(pose,"yaw",mc.player.getYRot()); number(pose,"pitch",mc.player.getXRot());
        pose.addProperty("on_ground", mc.player.onGround());
        evidence.add("decision_pose", pose);
        // The tick's final observation work also belongs to the same retreat deadline.
        if(pendingRetreatDiagnostics!=null) {
            if(pendingRetreatDiagnostics.checkBudget("tick_decision_return")) {
                pendingRetreatEvidence.addProperty("reason","retreat_check_budget");
                pendingRetreatEvidence.addProperty("budget_exhausted",true);
                if(pendingRetreatPlan) { retreatGoal=null;evidence.remove("retreat_goal"); }
                else {
                    pendingRetreatEvidence.addProperty("all_remaining_windows_revalidated",false);
                    evidence.addProperty("retreat_corridor_reason","retreat_check_budget");
                }
                step=Step.end("failed",pendingRetreatPlan?"retreat_planning_budget_risk_remaining":"retreat_revalidation_budget_risk_remaining");
                evidence.addProperty("requested_forward",step.forward());
                evidence.addProperty("decision_phase",step.reason());lastDecisionPhase=step.reason();
            }
            CombatRetreatEvidence.stamp(pendingRetreatEvidence,pendingRetreatDiagnostics);
        }
        return step;
    }

    boolean isEncounter() { return encounter!=null; }
    String encounterCallbackInterruption(long now) { return encounter==null?null:encounter.callbackInterruption(now); }
    void terminal(String status,String reason) { if(encounter!=null) encounter.terminal(status,reason); }

    private Step tickEncounter(Minecraft mc,int tick,CombatThreats.HealthGuard.Result health) {
        shield(mc,false); // Offense and shield choreography are outside stage 1.
        Vec3 v=mc.player.getDeltaMovement();
        CombatRecovery.Motion motion=new CombatRecovery.Motion(mc.player.getX(),mc.player.getY(),mc.player.getZ(),
                v.x,v.y,v.z,mc.player.onGround());
        retreatWindowMetrics=null;lastRouteTerrain=null;
        var decision=encounter.tick(tick,threats,motion,health,(from,to)->retreatWindow(mc,from,to),
                this::retreatRejectedCell,(data,diagnostics)->CombatRetreatEvidence.append(data,diagnostics,
                        retreatWindowMetrics,tickCells,tickTerrainReads));
        if(decision.forward()>0) {
            faceMovement(mc,decision.goal().x()-mc.player.getX(),decision.goal().z()-mc.player.getZ());
        }
        if(decision.diagnostics()!=null) {
            pendingRetreatDiagnostics=decision.diagnostics();pendingRetreatEvidence=decision.diagnosticEvidence();
            pendingRetreatPlan=decision.planning();
        }
        return new Step(decision.forward(),decision.terminal(),decision.reason());
    }

    private Step tickCombat(Minecraft mc, int tick) {
        if (CombatRules.manualViewChanged(mc.player.getYRot(),mc.player.getXRot(),expectedYaw,expectedPitch))
            return Step.end("cancelled", "manual_view_changed");
        captureThreats(mc, tick);
        CombatThreats.HealthGuard.Result health = healthGuard.sample(tick, System.nanoTime(), mc.player.getHealth());
        LivingEntity target = target(mc);
        CombatThreats.Gate gate = CombatThreats.evaluate(threats, System.nanoTime(), tick,
                mc.player.getX(), mc.player.getY(), mc.player.getZ(),
                target != null && !target.isAlive() ? -1 : request.targetId(), request.targetUuid(), health);
        observeThreatGate(gate, health);
        if (encounter != null) return tickEncounter(mc,tick,health);
        if (target == null) return Step.end("failed", "target_missing_not_a_kill");
        observe(mc, target);
        if (mc.player.position().distanceTo(origin) > 12) return Step.end("failed", "combat_area_limit");
        if (!weapon(mc.player.getMainHandItem().getItem())) return Step.end("failed", "selected_weapon_changed");
        if (gate.stop() && safetyReason == null) safetyReason = gate.reason();
        // Safety latches for this action, before any target-facing view or attack.
        if (safetyReason != null) return safetyRetreat(mc, tick, gate);
        if (!target.isAlive()) {
            evidence.addProperty("target_dead_observed", true);
            evidence.addProperty("attack_completed", true);
            evidence.addProperty("outcome_kind", "attack_completed");
            evidence.addProperty("risk_remaining", gate.riskRemaining());
            return Step.end("succeeded", "target_dead_observed");
        }
        Vec3 velocity = mc.player.getDeltaMovement();
        CombatRecovery.Motion motion = new CombatRecovery.Motion(mc.player.getX(), mc.player.getY(), mc.player.getZ(),
                velocity.x, velocity.y, velocity.z, mc.player.onGround());
        if (!motion.finite()) {
            recovery.sample(tick, motion, 0, direction -> false);
            observeRecovery(motion);
            return Step.end("failed", "invalid_combat_motion");
        }
        Vec3 eye = mc.player.getEyePosition();
        Vec3 center = target.getBoundingBox().getCenter();
        Vec3 delta = center.subtract(eye);
        expectedYaw = (float)Math.toDegrees(Math.atan2(-delta.x,delta.z));
        expectedPitch = (float)-Math.toDegrees(Math.atan2(delta.y,Math.hypot(delta.x,delta.z)));
        mc.player.setYRot(expectedYaw); mc.player.setXRot(expectedPitch); mc.player.setYHeadRot(expectedYaw);
        mc.gameRenderer.pick(1.0F);
        double separation = Math.hypot(target.getX()-mc.player.getX(),target.getZ()-mc.player.getZ());
        boolean picked = mc.hitResult instanceof EntityHitResult hit
                && CombatRules.rayInReach(hit.getEntity()==target,eye.distanceTo(hit.getLocation()),mc.player.entityInteractionRange());
        number(evidence,"target_distance", separation);
        number(evidence,"attack_strength", mc.player.getAttackStrengthScale(.5F));
        evidence.addProperty("target_picked_in_reach", picked);
        boolean creeper = request.targetType().equals("minecraft:creeper");
        int recoveryDirection = creeper ? (separation > 8 ? 0 : -1)
                : (!picked && request.approach() && separation > 2.5 ? 1 : 0);
        CombatRecovery.Result recovered = recovery.sample(tick, motion, recoveryDirection,
                direction -> corridorClear(mc, target, 0));
        observeRecovery(motion);
        if (recovered.state() == CombatRecovery.State.FAILED) return Step.end("failed", recovered.reason());
        if (recovered.state() == CombatRecovery.State.WAIT) {
            shield(mc, request.shield() && !creeper);
            return Step.waitFor(recovered.reason());
        }
        if (recovered.state() == CombatRecovery.State.RECOVERED) {
            // Rebase local motion once; recovery cannot refund the no-closing budget.
            pursuit.rebaseAfterRecovery(System.nanoTime());
            detour.rebaseAfterRecovery(); waypointIndex = 0;
        }
        if (request.targetType().equals("minecraft:creeper")) {
            shield(mc, false);
            // Distance alone is never a completed attack or a verified safe disengagement.
            if (separation > 8) return Step.end("failed", "creeper_outside_warning_risk_remaining");
            return Step.end("failed", "creeper_risk_remaining");
        }
        if (!picked) {
            if (!request.approach()) {
                shield(mc, request.shield());
                return Step.waitFor("waiting_target_ray");
            }
            boolean ranged = request.targetType().equals("minecraft:skeleton")
                    || request.targetType().equals("minecraft:stray") || request.targetType().equals("minecraft:bogged");
            boolean shieldAvailable = request.shield() && mc.player.getOffhandItem().is(Items.SHIELD)
                    && !mc.player.getCooldowns().isOnCooldown(Items.SHIELD);
            CombatPursuit.Result approach = pursuit.sample(tick, System.nanoTime(),
                    new CombatPursuit.Sample(mc.player.getX(), mc.player.getZ(), target.getX(), target.getZ()),
                    ranged && shieldAvailable);
            observePursuit(approach);
            if (approach.failed()) return Step.end("failed", approach.reason());
            // Only ranged pursuit changes shield cadence. Existing melee shielding remains.
            shield(mc, ranged ? approach.defend() : request.shield());
            if (approach.defend()) {
                if (!corridorClear(mc, target, 0)) return Step.end("failed", "local_flat_corridor_blocked");
                return Step.waitFor(approach.reason());
            }
            if (ranged && mc.player.isUsingItem()) return Step.waitFor("waiting_approach_item_release");
            // A blocked nearby ray permits only a completely validated lateral route,
            // never blindly closing into the target or the protected ray occluder.
            if (separation <= 2.5)
                return detour.activePlan() == null ? replan(mc,target) : followDetour(mc,target);
            return move(mc,target,1,"approaching");
        }
        pursuit.reached();
        detour.clear(); waypointIndex = 0;
        if (mc.player.getMainHandItem().getItem() instanceof SwordItem && sweepRisk(mc,target)) {
            shield(mc,false);
            for (int slot=0;slot<9;slot++) {
                if (mc.player.getInventory().getItem(slot).getItem() instanceof AxeItem) {
                    mc.player.getInventory().selected=slot; selectedTick=tick;
                    return Step.waitFor("selecting_axe_for_protected_bystander");
                }
            }
            return Step.end("failed","protected_sweep_overlap");
        }
        if (tick <= selectedTick || tick == lastAttackTick) return Step.waitFor("waiting_next_tick");
        if (!CombatRules.cooldownReady(mc.player.getAttackStrengthScale(.5F))) {
            shield(mc,request.shield());
            return Step.waitFor(mc.player.isBlocking() ? "blocking_observed" : "waiting_attack_cooldown");
        }
        if (shieldOwned || mc.player.isUsingItem()) {
            shield(mc,false);
            return Step.waitFor("lowering_shield");
        }
        // Both sword and axe dispatches must obey the same final local age policy.
        CombatThreats.Gate dispatchGate=CombatThreats.evaluate(threats,System.nanoTime(),tick,
                mc.player.getX(),mc.player.getY(),mc.player.getZ(),request.targetId(),request.targetUuid(),health);
        if(dispatchGate.stop()) {
            safetyReason=dispatchGate.reason();
            evidence.addProperty("safety_interrupt_reason",safetyReason);
            evidence.addProperty("outcome_kind","risk_remaining");
            return Step.end("failed","attack_dispatch_gate_"+safetyReason);
        }
        // Fresh renderer pick and cooldown above are from this same game tick.
        // Native startAttack honours normal hooks and server interaction rules.
        lastAttackTick=tick; attacks++;
        mc.startAttack();
        evidence.addProperty("attack_dispatches",attacks);
        return Step.waitFor("attack_dispatched");
    }

    private Step move(Minecraft mc, LivingEntity target, int direction, String phase) {
        if (detour.activePlan() != null && direction > 0) return followDetour(mc, target);
        if (!corridorClear(mc, target, direction)) {
            evidence.addProperty("outcome_kind", "blocked");
            if (direction > 0) return replan(mc, target);
            return Step.end("failed","local_flat_corridor_blocked");
        }
        if (detour.attempts()>0 && direction>0) {
            double dx=target.getX()-mc.player.getX(),dz=target.getZ()-mc.player.getZ(),length=Math.hypot(dx,dz);
            Step motionStep=routeMotionStep(mc,dx,dz,false);
            if(motionStep!=null) return motionStep;
            CombatDetour.Point from=point(mc.player.position());
            CombatDetour.EdgeResult edge=liveRouteEdge(mc,from,new CombatDetour.Point(from.x()+dx/length*.65,from.z()+dz/length*.65),false);
            if(!edge.clear()) return replan(mc,target);
        }
        return new Step(direction,null,phase);
    }

    private boolean corridorClear(Minecraft mc, LivingEntity target, int direction) {
        double dx=target.getX()-mc.player.getX(), dz=target.getZ()-mc.player.getZ();
        double length=Math.hypot(dx,dz);
        if (direction != 0 && (!Double.isFinite(length) || length < .01)) {
            evidence.addProperty("corridor_direction", direction);
            evidence.addProperty("corridor_reason", "invalid_target_direction");
            evidence.remove("corridor");
            return false;
        }
        FlatStepCorridor.Result result = TerrainReader.flatStepResult(mc,
                direction == 0 ? 0 : dx/length*.65*direction,
                direction == 0 ? 0 : dz/length*.65*direction);
        if (result.clear()) {
            CombatDetour.Point from = point(mc.player.position());
            CombatDetour.Point to = new CombatDetour.Point(from.x()+result.dx(),from.z()+result.dz());
            CombatDetour.EdgeResult edge = routeEdge(mc, from, to, false);
            if (!edge.clear()) result = FlatStepCorridor.rejected(edge.reason(), result.pose(), result.dx(), result.dz());
        }
        recordCorridor(result, direction);
        return result.clear();
    }

    private void recordCorridor(FlatStepCorridor.Result result, int direction) {
        JsonObject corridor = new JsonObject();
        corridor.addProperty("evaluated_tick", currentTick);
        corridor.addProperty("clear", result.clear()); corridor.addProperty("reason", result.reason());
        corridor.addProperty("direction", direction);
        number(corridor,"dx",result.dx()); number(corridor,"dz",result.dz());
        if (result.pose() != null) {
            FlatStepCorridor.Pose p = result.pose();
            JsonObject pose = new JsonObject();
            number(pose,"x",p.x()); number(pose,"y",p.y()); number(pose,"z",p.z());
            number(pose,"yaw",p.yaw()); pose.addProperty("on_ground", p.onGround());
            corridor.add("pose", pose);
        }
        if (result.cell() != null) {
            FlatStepCorridor.CellRef c = result.cell();
            JsonObject cell = new JsonObject();
            cell.addProperty("x", c.x()); cell.addProperty("y", c.y()); cell.addProperty("z", c.z());
            cell.addProperty("layer", c.layer()); cell.addProperty("id", c.id());
            corridor.add("rejected_cell", cell);
        }
        evidence.addProperty("corridor_direction", direction);
        evidence.addProperty("corridor_reason", result.reason());
        evidence.add("corridor", corridor);
    }

    private static CombatDetour.Point point(Vec3 p) { return new CombatDetour.Point(p.x,p.z); }

    /** Snapshot is bounded, local, client-observed, and refreshed before every combat decision. */
    private void captureThreats(Minecraft mc, int tick) {
        long started = System.nanoTime();
        List<CombatThreats.Observed> observed = new ArrayList<>();
        List<CombatSpatial.Box> boxes = new ArrayList<>();
        JsonArray entities = new JsonArray();
        int examined = 0; boolean truncated = false, known = true;
        try {
            for (Entity entity : mc.level.entitiesForRendering()) {
                if (++examined > 1024 || System.nanoTime()-started > 4_000_000L) { truncated=true; break; }
                if (entity == mc.player || !entity.isAlive()) continue;
                if (entity.distanceToSqr(mc.player) > 16*16) continue;
                AABB bb = entity.getBoundingBox();
                if (entity instanceof LivingEntity || entity.canBeCollidedWith() || entity.canCollideWith(mc.player)) {
                    if (boxes.size() >= 128) { truncated=true; break; }
                    boxes.add(new CombatSpatial.Box(entity.getId(),bb.minX,bb.minY,bb.minZ,bb.maxX,bb.maxY,bb.maxZ));
                }
                if (!(entity instanceof LivingEntity)) continue;
                if (observed.size() >= 128) { truncated=true; break; }
                String type = BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString();
                boolean dangerous = entity instanceof Enemy || entity instanceof NeutralMob
                        || CombatThreats.observableThreat(type);
                observed.add(new CombatThreats.Observed(entity.getId(), entity.getUUID().toString(), type,
                        entity.getX(), entity.getY(), entity.getZ(),
                        Math.max(bb.maxX-bb.minX,bb.maxZ-bb.minZ)/2, dangerous, entity.isAlive()));
                JsonObject item = new JsonObject();
                item.addProperty("entity_id",entity.getId()); item.addProperty("uuid",entity.getUUID().toString());
                item.addProperty("type",type); item.addProperty("dangerous_or_potential",dangerous);
                number(item,"x",entity.getX());number(item,"y",entity.getY());number(item,"z",entity.getZ());
                entities.add(item);
            }
        } catch (RuntimeException ex) { known=false; }
        threats = new CombatThreats.Snapshot(observed, started, tick, truncated, known);
        tickTerrainReads=new TerrainReader.ReadMetrics();
        tickCells=new CombatCellCache(TerrainReader.flatCellSource(mc,tickTerrainReads));
        obstacles = List.copyOf(boxes);
        JsonObject data = new JsonObject();
        data.addProperty("evaluated_tick",tick);data.addProperty("captured_nanos",started);
        data.addProperty("examined",examined);data.addProperty("count",observed.size());data.addProperty("dynamic_obstacles",boxes.size());
        data.addProperty("truncated",truncated);data.addProperty("known",known);
        data.addProperty("scan_elapsed_micros",(System.nanoTime()-started)/1000);
        data.addProperty("max_examined",1024);data.addProperty("max_observed",128);
        data.addProperty("scope","client_loaded_living_within_16_not_server_complete");
        data.add("entities",entities);evidence.add("threat_snapshot",data);
    }

    private void observeThreatGate(CombatThreats.Gate gate, CombatThreats.HealthGuard.Result health) {
        JsonObject data = new JsonObject();
        if(health.interrupted() && healthTriggerTick<0) healthTriggerTick=currentTick;
        data.addProperty("evaluated_tick",currentTick);data.addProperty("stop_offense",gate.stop());
        data.addProperty("reason",gate.reason());data.addProperty("fresh",gate.fresh());
        data.addProperty("emergency_entity_id",gate.emergencyId());
        data.addProperty("emergency_uuid",gate.emergencyUuid());
        data.addProperty("thresholds_live_calibrated",false);
        data.addProperty("health_gate_reason",health.reason());data.addProperty("health_known",health.known());
        data.addProperty("health_value_semantics",health.interrupted()?"latched_trigger_metrics":"current_sample");
        data.addProperty("health_sample_tick",health.interrupted()?healthTriggerTick:currentTick);
        number(data,"health",health.health());number(data,"rolling_loss_1s",health.damageInWindow());
        data.addProperty("health_sample_count",health.sampleCount());
        CombatHealthEvidence.append(data,healthGuard);
        evidence.add("threat_gate",data);
        evidence.addProperty("risk_remaining",true);
        evidence.addProperty("safety_assured",false);
    }

    private CombatDetour.EdgeResult routeEdge(Minecraft mc, CombatDetour.Point from,
                                               CombatDetour.Point to, boolean escape) {
        lastRouteTerrain=null;
        double dx=to.x()-from.x(), dz=to.z()-from.z(), length=Math.hypot(dx,dz);
        if (!Double.isFinite(length) || length>2.001 || !CombatSpatial.withinCombatArea(to.x(),mc.player.getY(),to.z(),origin.x,origin.y,origin.z))
            return routeDenied("route_area_or_length_limit");
        long now=System.nanoTime();
        CombatThreats.Route risk=escape ? CombatThreats.escapeRoute(threats,now,currentTick,from.x(),from.z(),to.x(),to.z())
                : CombatThreats.route(threats,now,currentTick,from.x(),from.z(),to.x(),to.z(),request.targetId(),request.targetUuid());
        if (!risk.safe()) return routeDenied(risk.reason());
        CombatSpatial.Result dynamic=CombatSpatial.check(from.x(),mc.player.getY(),from.z(),dx,dz,obstacles);
        if (!dynamic.clear()) {
            evidence.addProperty("blocked_entity_id",dynamic.entityId());
            return routeDenied(dynamic.reason());
        }
        int pieces=Math.max(1,(int)Math.ceil(length/.65));
        FlatStepCorridor.CellSource source=tickCells;
        for(int i=0;i<pieces;i++) {
            FlatStepCorridor.Pose pose=new FlatStepCorridor.Pose(from.x()+dx*i/pieces,mc.player.getY(),
                    from.z()+dz*i/pieces,mc.player.onGround(),mc.player.getYRot());
            lastRouteTerrain=FlatStepCorridor.check(pose,dx/pieces,dz/pieces,source);
            if (!lastRouteTerrain.clear()) return routeDenied(lastRouteTerrain.reason());
        }
        lastRouteReason="clear";
        return new CombatDetour.EdgeResult(true,Math.min(100,risk.minimumClearance()),"clear");
    }
    private CombatDetour.EdgeResult plannedRouteEdge(Minecraft mc, CombatDetour.Point from,
                                                      CombatDetour.Point to, boolean escape) {
        CombatDetour.EdgeResult edge=routeEdge(mc,from,to,escape);
        if(!edge.clear()) return edge;
        double dx=to.x()-from.x(),dz=to.z()-from.z();
        int pieces=Math.max(1,(int)Math.ceil(Math.hypot(dx,dz)/.65));
        for(int i=0;i<pieces;i++) {
            FlatStepCorridor.Pose pose=new FlatStepCorridor.Pose(from.x()+dx*i/pieces,mc.player.getY(),
                    from.z()+dz*i/pieces,mc.player.onGround(),mc.player.getYRot());
            lastRouteTerrain=CombatRouteEnvelope.check(pose,dx/pieces,dz/pieces,tickCells,obstacles);
            if(!lastRouteTerrain.clear()) return routeDenied(lastRouteTerrain.reason());
        }
        return edge;
    }

    private CombatDetour.EdgeResult liveRouteEdge(Minecraft mc, CombatDetour.Point from,
                                                   CombatDetour.Point to, boolean escape) {
        CombatDetour.EdgeResult edge=routeEdge(mc,from,to,escape);
        FlatStepCorridor.Pose pose=new FlatStepCorridor.Pose(mc.player.getX(),mc.player.getY(),mc.player.getZ(),
                mc.player.onGround(),mc.player.getYRot());
        FlatStepCorridor.Result result;
        if(lastRouteTerrain!=null && !lastRouteTerrain.clear() && lastRouteTerrain.reason().equals(edge.reason()))
            result=lastRouteTerrain;
        else result=new FlatStepCorridor.Result(edge.clear(),edge.reason(),pose,to.x()-from.x(),to.z()-from.z(),null);
        if(edge.clear()) {
            result=CombatRouteEnvelope.check(pose,to.x()-from.x(),to.z()-from.z(),tickCells,obstacles);
            if(!result.clear()) edge=routeDenied(result.reason());
        }
        recordCorridor(result,1);
        evidence.getAsJsonObject("corridor").addProperty("motion_envelope_margin",CombatRouteMotion.ENVELOPE);
        return edge;
    }

    private Step routeMotionStep(Minecraft mc,double dx,double dz,boolean urgent) {
        Vec3 velocity=mc.player.getDeltaMovement();
        CombatRecovery.Motion motion=new CombatRecovery.Motion(mc.player.getX(),mc.player.getY(),mc.player.getZ(),
                velocity.x,velocity.y,velocity.z,mc.player.onGround());
        CombatRouteMotion.Result result=routeMotion.sample(currentTick,motion,dx,dz,urgent);
        JsonObject data=new JsonObject();data.addProperty("evaluated_tick",currentTick);
        data.addProperty("reason",result.reason());data.addProperty("ready",result.ready());
        data.addProperty("settle_ticks",result.settleTicks());data.addProperty("total_settle_ticks",result.totalSettleTicks());
        evidence.add("route_motion",data);
        if(result.ready()) return null;
        if(result.failed()) return Step.end("failed",result.reason()+"_risk_remaining");
        return Step.waitFor(result.reason());
    }

    private CombatDetour.EdgeResult routeDenied(String reason) {
        lastRouteReason=reason;return new CombatDetour.EdgeResult(false,0,reason);
    }

    private Step replan(Minecraft mc, LivingEntity target) {
        if (evidence.has("corridor")) evidence.add("blocked_corridor",evidence.get("corridor").deepCopy());
        CombatDetour.Result result=detour.plan(point(mc.player.position()),point(target.position()),
                (from,to)->plannedRouteEdge(mc,from,to,false));
        waypointIndex=0;
        JsonObject data=new JsonObject();data.addProperty("evaluated_tick",currentTick);
        data.addProperty("attempts",result.attempts());data.addProperty("reason",result.reason());
        data.addProperty("candidate_checks",result.candidateChecks());data.addProperty("edge_checks",result.edgeChecks());
        data.addProperty("last_edge_reason",lastRouteReason);
        JsonArray waypoints=new JsonArray();
        if(result.plan()!=null) for(CombatDetour.Point p:result.plan().waypoints()) {
            JsonObject w=new JsonObject();w.addProperty("x",p.x());w.addProperty("z",p.z());waypoints.add(w);
        }
        data.add("waypoints",waypoints);evidence.add("detour",data);
        if(result.plan()==null) {
            evidence.addProperty("outcome_kind","no_safe_route");
            return Step.end("failed","no_safe_route_"+result.reason());
        }
        evidence.addProperty("outcome_kind","replanning");
        return Step.waitFor("replanning");
    }

    private Step followDetour(Minecraft mc, LivingEntity target) {
        List<CombatDetour.Point> points=detour.activePlan().waypoints();
        CombatDetour.Point current=point(mc.player.position());
        while(waypointIndex<points.size() && Math.hypot(points.get(waypointIndex).x()-current.x(),
                points.get(waypointIndex).z()-current.z())<=.18) waypointIndex++;
        evidence.addProperty("detour_waypoint_index",waypointIndex);
        if(waypointIndex>=points.size()) {detour.clear();return Step.waitFor("detour_completed_recheck_target");}
        CombatDetour.Point next=points.get(waypointIndex);
        double dx=next.x()-current.x(),dz=next.z()-current.z(),distance=Math.hypot(dx,dz);
        Step motionStep=routeMotionStep(mc,dx,dz,false);
        if(motionStep!=null) return motionStep;
        CombatDetour.Point step=new CombatDetour.Point(current.x()+dx/distance*.65,current.z()+dz/distance*.65);
        CombatDetour.EdgeResult edge=liveRouteEdge(mc,current,step,false);
        if(!edge.clear()) {
            if(lastRouteTerrain!=null && !lastRouteTerrain.clear()) recordCorridor(lastRouteTerrain,1);
            detour.clear();return replan(mc,target);
        }
        faceMovement(mc,dx,dz);
        evidence.addProperty("outcome_kind","replanning");
        return new Step(distance<.45 ? .35F:1F,null,"detour_advancing");
    }

    private void faceMovement(Minecraft mc,double dx,double dz) {
        expectedYaw=(float)Math.toDegrees(Math.atan2(-dx,dz));
        // Lowered gaze avoids intentionally looking at a neutral Enderman while disengaging.
        // It is not a complete gaze-cone proof or teleport strategy.
        expectedPitch=65;
        mc.player.setYRot(expectedYaw);mc.player.setXRot(expectedPitch);mc.player.setYHeadRot(expectedYaw);
    }

    private Step safetyRetreat(Minecraft mc,int tick,CombatThreats.Gate gate) {
        shield(mc,false);detour.clear();
        evidence.addProperty("safety_interrupt_reason",safetyReason);
        evidence.addProperty("risk_remaining",true);evidence.addProperty("outcome_kind","risk_remaining");
        // A later Enderman supersedes an earlier latched health/creeper cause as well.
        if (threats.entities().stream().anyMatch(e -> e.alive() && e.type().equals("minecraft:enderman")))
            return Step.end("failed","enderman_gaze_unplanned_risk_remaining");
        if (!finite(mc.player.getDeltaMovement()))
            return Step.end("failed","invalid_retreat_motion_risk_remaining");
        if(!gate.fresh() || threats.truncated() || !threats.known())
            return Step.end("failed","threat_observation_risk_remaining");
        if(!mc.player.onGround() || Math.abs(mc.player.getY()-Math.rint(mc.player.getY()))>.05)
            return Step.end("failed","unsafe_retreat_pose_risk_remaining");
        if(retreatStartTick<0) {retreatStartTick=tick;retreatStartNanos=System.nanoTime();}
        if(previousRetreatPose!=null) retreatDistance+=mc.player.position().distanceTo(previousRetreatPose);
        previousRetreatPose=mc.player.position();
        evidence.addProperty("retreat_distance_observed",retreatDistance);
        evidence.addProperty("retreat_elapsed_ticks",tick-retreatStartTick);
        if(tick-retreatStartTick>=60 || System.nanoTime()-retreatStartNanos>=3_000_000_000L || retreatDistance>=4)
            return Step.end("failed","retreat_budget_risk_remaining");
        CombatDetour.Point current=point(mc.player.position());
        if(retreatGoal==null) {
            retreatWindowMetrics=null;lastRouteTerrain=null;
            CombatRetreatPolicy.Plan plan=CombatRetreatPolicy.plan(threats,current,
                    (from,to)->retreatWindow(mc,from,to),System::nanoTime,this::retreatRejectedCell);
            JsonObject diagnostics=new JsonObject();
            diagnostics.addProperty("evaluated_tick",tick);
            diagnostics.addProperty("reason",plan.reason());
            diagnostics.addProperty("candidate_checks",plan.candidateChecks());
            diagnostics.addProperty("window_checks",plan.windowChecks());
            diagnostics.addProperty("first_window_rejections",plan.firstWindowRejections());
            diagnostics.addProperty("budget_exhausted",plan.budgetExhausted());
            diagnostics.addProperty("budget_nanos",CombatRetreatPolicy.MAX_CHECK_NANOS);
            diagnostics.addProperty("heading_policy","nearest_threat_away_then_alternating_angles_first_admitted");
            JsonObject rejected=new JsonObject();plan.rejections().forEach(rejected::addProperty);
            diagnostics.add("rejections",rejected);evidence.add("retreat_plan",diagnostics);
            CombatRetreatEvidence.append(diagnostics,plan.diagnostics(),retreatWindowMetrics,tickCells,tickTerrainReads);
            boolean observationBudget=plan.diagnostics().checkBudget("post_diagnostics");
            CombatRetreatEvidence.stamp(diagnostics,plan.diagnostics());
            if(observationBudget) {
                diagnostics.addProperty("reason","retreat_check_budget");diagnostics.addProperty("budget_exhausted",true);
                return Step.end("failed","retreat_planning_budget_risk_remaining");
            }
            retreatGoal=plan.goal();
            if(retreatGoal==null) return Step.end("failed",plan.budgetExhausted()
                    ?"retreat_planning_budget_risk_remaining":"no_safe_retreat_risk_remaining");
            JsonObject goal=new JsonObject();goal.addProperty("x",retreatGoal.x());goal.addProperty("z",retreatGoal.z());
            evidence.add("retreat_goal",goal);
            if(plan.diagnostics().checkBudget("plan_publication")) {
                retreatGoal=null;evidence.remove("retreat_goal");
                diagnostics.addProperty("reason","retreat_check_budget");diagnostics.addProperty("budget_exhausted",true);
                CombatRetreatEvidence.stamp(diagnostics,plan.diagnostics());
                return Step.end("failed","retreat_planning_budget_risk_remaining");
            }
            CombatRetreatEvidence.stamp(diagnostics,plan.diagnostics());
            retreatProgress.start(threats,current,retreatGoal,tick,System.nanoTime());
            if(plan.diagnostics().checkBudget("plan_decision_return")) {
                retreatGoal=null;evidence.remove("retreat_goal");
                diagnostics.addProperty("reason","retreat_check_budget");diagnostics.addProperty("budget_exhausted",true);
                CombatRetreatEvidence.stamp(diagnostics,plan.diagnostics());
                return Step.end("failed","retreat_planning_budget_risk_remaining");
            }
            CombatRetreatEvidence.stamp(diagnostics,plan.diagnostics());
            pendingRetreatDiagnostics=plan.diagnostics();pendingRetreatEvidence=diagnostics;pendingRetreatPlan=true;
            return Step.waitFor("safety_retreat_planned_risk_remaining");
        }
        String progressProblem=retreatProgress.observe(threats,current,tick,System.nanoTime());
        JsonObject progress=new JsonObject();
        progress.addProperty("evaluated_tick",tick);progress.addProperty("reason",progressProblem==null?"observed_continuity_clear":progressProblem);
        number(progress,"window_player_advance",retreatProgress.observedAdvance());
        number(progress,"window_clearance_gain",retreatProgress.observedClearanceGain());
        progress.addProperty("max_window_ticks",CombatRetreatPolicy.MAX_PROGRESS_TICKS);
        progress.addProperty("max_window_nanos",CombatRetreatPolicy.MAX_PROGRESS_NANOS);
        progress.addProperty("min_player_advance",CombatRetreatPolicy.MIN_OBSERVED_ADVANCE);
        progress.addProperty("min_clearance_gain",CombatThreats.ESCAPE_IMPROVEMENT);
        evidence.add("retreat_progress",progress);
        if(progressProblem!=null) return Step.end("failed",progressProblem+"_risk_remaining");
        double dx=retreatGoal.x()-current.x(),dz=retreatGoal.z()-current.z(),distance=Math.hypot(dx,dz);
        if(distance<=CombatRetreatPolicy.ARRIVAL_DISTANCE) return Step.end("failed","retreat_segment_completed_risk_remaining");
        Step motionStep=routeMotionStep(mc,dx,dz,true);
        if(motionStep!=null) return motionStep;
        // Recompute ALL remaining windows from the actual pose and this tick's live snapshot.
        // Changed threat geometry never inherits a previous admission; identities/decreases refuse above.
        retreatWindowMetrics=null;lastRouteTerrain=null;
        CombatRetreatPolicy.Validation validation=CombatRetreatPolicy.validate(current,retreatGoal,
                (from,to)->retreatWindow(mc,from,to),System::nanoTime,this::retreatRejectedCell);
        JsonObject checked=new JsonObject();checked.addProperty("evaluated_tick",tick);
        checked.addProperty("reason",validation.reason());checked.addProperty("window_checks",validation.windows());
        checked.addProperty("budget_exhausted",validation.budgetExhausted());
        checked.addProperty("window_distance",CombatRetreatPolicy.WINDOW_DISTANCE);
        checked.addProperty("minimum_motion_probe_distance",CombatRetreatPolicy.WINDOW_DISTANCE);
        checked.addProperty("required_clearance_gain",CombatThreats.ESCAPE_IMPROVEMENT);
        checked.addProperty("all_remaining_windows_revalidated",validation.clear());
        evidence.add("retreat_live_validation",checked);
        evidence.addProperty("retreat_corridor_reason",validation.reason());
        CombatRetreatEvidence.append(checked,validation.diagnostics(),retreatWindowMetrics,tickCells,tickTerrainReads);
        boolean observationBudget=validation.diagnostics().checkBudget("post_diagnostics");
        CombatRetreatEvidence.stamp(checked,validation.diagnostics());
        if(observationBudget) {
            checked.addProperty("reason","retreat_check_budget");checked.addProperty("budget_exhausted",true);
            checked.addProperty("all_remaining_windows_revalidated",false);
            evidence.addProperty("retreat_corridor_reason","retreat_check_budget");
        }
        if(!validation.clear() || observationBudget) {
            if(lastRouteTerrain!=null && !lastRouteTerrain.clear()) recordCorridor(lastRouteTerrain,1);
            return Step.end("failed",validation.budgetExhausted() || observationBudget
                    ?"retreat_revalidation_budget_risk_remaining":"retreat_blocked_risk_remaining");
        }
        CombatDetour.Point next=CombatRetreatPolicy.next(current,retreatGoal);
        if(next==null) return Step.end("failed","invalid_retreat_window_risk_remaining");
        recordCorridor(new FlatStepCorridor.Result(true,"retreat_windows_clear_risk_remaining",
                new FlatStepCorridor.Pose(current.x(),mc.player.getY(),current.z(),mc.player.onGround(),mc.player.getYRot()),
                next.x()-current.x(),next.z()-current.z(),null),1);
        evidence.getAsJsonObject("corridor").addProperty("motion_envelope_margin",CombatRouteMotion.ENVELOPE);
        // Include corridor/JSON observation work before view mutation or issuing movement.
        if(validation.diagnostics().checkBudget("pre_motion")) {
            checked.addProperty("reason","retreat_check_budget");checked.addProperty("budget_exhausted",true);
            checked.addProperty("all_remaining_windows_revalidated",false);
            evidence.addProperty("retreat_corridor_reason","retreat_check_budget");
            CombatRetreatEvidence.stamp(checked,validation.diagnostics());
            return Step.end("failed","retreat_revalidation_budget_risk_remaining");
        }
        CombatRetreatEvidence.stamp(checked,validation.diagnostics());
        faceMovement(mc,dx,dz);
        if(validation.diagnostics().checkBudget("motion_decision_return")) {
            checked.addProperty("reason","retreat_check_budget");checked.addProperty("budget_exhausted",true);
            checked.addProperty("all_remaining_windows_revalidated",false);
            evidence.addProperty("retreat_corridor_reason","retreat_check_budget");
            CombatRetreatEvidence.stamp(checked,validation.diagnostics());
            return Step.end("failed","retreat_revalidation_budget_risk_remaining");
        }
        CombatRetreatEvidence.stamp(checked,validation.diagnostics());
        pendingRetreatDiagnostics=validation.diagnostics();pendingRetreatEvidence=checked;pendingRetreatPlan=false;
        return new Step(distance<.5?.35F:1F,null,"safety_retreating_risk_remaining");
    }

    /** Identical window safety composition for both planned and live retreat paths. */
    private CombatDetour.EdgeResult retreatWindow(Minecraft mc,CombatDetour.Point from,CombatDetour.Point to) {
        lastRouteTerrain=null;lastRouteReason="not_checked";
        if(retreatWindowMetrics==null) retreatWindowMetrics=new CombatRetreatWindow.Metrics();
        FlatStepCorridor.Pose pose=new FlatStepCorridor.Pose(from.x(),mc.player.getY(),from.z(),mc.player.onGround(),mc.player.getYRot());
        CombatRetreatWindow.Result result=CombatRetreatWindow.check(threats,System.nanoTime(),currentTick,pose,to,
                origin.x,origin.y,origin.z,tickCells,obstacles,retreatWindowMetrics);
        lastRouteTerrain=result.terrain();lastRouteReason=result.edge().reason();
        if(result.blockedEntityId()>=0) evidence.addProperty("blocked_entity_id",result.blockedEntityId());
        return result.edge();
    }

    private FlatStepCorridor.CellRef retreatRejectedCell() {
        return lastRouteTerrain==null?null:lastRouteTerrain.cell();
    }

    private void observeDecisionMotion(Minecraft mc, LivingEntity target, String phase) {
        Vec3 player = mc.player.position(), destination = target == null ? null : target.position();
        evidence.remove("motion_since_previous_decision");
        if (finite(player) && finite(destination) && finite(lastDecisionPlayer) && finite(lastDecisionTarget)) {
            Vec3 own = player.subtract(lastDecisionPlayer), other = destination.subtract(lastDecisionTarget);
            double distance = Math.hypot(lastDecisionTarget.x-lastDecisionPlayer.x, lastDecisionTarget.z-lastDecisionPlayer.z);
            double ux = distance > .01 ? (lastDecisionTarget.x-lastDecisionPlayer.x)/distance : 0;
            double uz = distance > .01 ? (lastDecisionTarget.z-lastDecisionPlayer.z)/distance : 0;
            JsonObject delta = new JsonObject();
            delta.addProperty("attributed_to_previous_phase", lastDecisionPhase);
            delta.add("player", vector(own)); delta.add("target", vector(other));
            delta.addProperty("player_forward", own.x*ux+own.z*uz);
            delta.addProperty("target_forward", other.x*ux+other.z*uz);
            delta.addProperty("distance_change", Math.hypot(destination.x-player.x,destination.z-player.z)-distance);
            evidence.add("motion_since_previous_decision", delta);
            JsonObject total = phaseMotion.has(lastDecisionPhase) ? phaseMotion.getAsJsonObject(lastDecisionPhase) : new JsonObject();
            add(total,"sample_intervals",1);
            add(total,"player_horizontal_distance",Math.hypot(own.x,own.z));
            add(total,"target_horizontal_distance",Math.hypot(other.x,other.z));
            add(total,"player_forward",own.x*ux+own.z*uz);
            add(total,"target_forward",other.x*ux+other.z*uz);
            phaseMotion.add(lastDecisionPhase,total);
            evidence.add("phase_motion_observed",phaseMotion);
        }
        lastDecisionPlayer = player; lastDecisionTarget = destination; lastDecisionPhase = phase;
    }
    private static boolean finite(Vec3 v) {
        return v != null && Double.isFinite(v.x) && Double.isFinite(v.y) && Double.isFinite(v.z);
    }
    private static JsonObject vector(Vec3 v) {
        JsonObject result = new JsonObject();
        number(result,"x",v.x); number(result,"y",v.y); number(result,"z",v.z);
        return result;
    }
    private static void number(JsonObject data, String key, double value) {
        data.addProperty(key,Double.isFinite(value) ? value : null);
    }
    private static void add(JsonObject data, String key, double value) {
        number(data,key,(data.has(key) ? data.get(key).getAsDouble() : 0)+value);
    }

    private void observePursuit(CombatPursuit.Result result) {
        JsonObject data = new JsonObject();
        data.addProperty("policy", "local_window_v1");
        data.addProperty("evaluated_tick", currentTick);
        data.addProperty("progress", result.progress());
        data.addProperty("reason", result.reason());
        data.addProperty("defending", result.defend());
        data.addProperty("cycle_tick", result.cycleTick());
        data.addProperty("window_closing", result.windowClosing());
        data.addProperty("window_player_advance", result.windowPlayerAdvance());
        data.addProperty("window_target_advance", result.windowTargetAdvance());
        data.addProperty("no_closing_ms", result.noClosingNanos()/1_000_000);
        data.addProperty("no_advance_ms", result.noAdvanceNanos()/1_000_000);
        data.addProperty("total_non_closing_ms", result.totalNonClosingNanos()/1_000_000);
        evidence.add("pursuit", data);
    }

    private void observeRecovery(CombatRecovery.Motion motion) {
        evidence.addProperty("player_on_ground", motion.onGround());
        evidence.addProperty("player_feet_height_offset", motion.finite() ? motion.heightOffset() : null);
        JsonObject velocity = new JsonObject();
        velocity.addProperty("x", Double.isFinite(motion.vx()) ? motion.vx() : null);
        velocity.addProperty("y", Double.isFinite(motion.vy()) ? motion.vy() : null);
        velocity.addProperty("z", Double.isFinite(motion.vz()) ? motion.vz() : null);
        evidence.add("player_velocity", velocity);
        evidence.addProperty("airborne_recovery_active", recovery.active());
        evidence.addProperty("airborne_recovery_episodes", recovery.episodes());
        evidence.addProperty("airborne_recovery_ticks", recovery.episodeTicks());
        evidence.addProperty("airborne_recovery_total_ticks", recovery.totalTicks());
        evidence.addProperty("airborne_recovery_settled_samples", recovery.settledSamples());
        evidence.addProperty("airborne_recoveries_completed", recovery.completed());
        evidence.addProperty("airborne_recovery_reason", recovery.reason());
    }

    private void shield(Minecraft mc, boolean wanted) {
        wanted = wanted && mc.player.getOffhandItem().is(Items.SHIELD)
                && !mc.player.getCooldowns().isOnCooldown(Items.SHIELD);
        if (!wanted) {
            if (shieldOwned) {
                mc.options.keyUse.setDown(false);
                if (mc.player != null && mc.gameMode != null && mc.player.isUsingItem())
                    mc.gameMode.releaseUsingItem(mc.player);
            }
            shieldOwned=false;
        } else if (!mc.player.isUsingItem()) {
            // A previous use can be interrupted while its key is still ours.
            // Clear that old hold before retrying, including a rejected use.
            if (shieldOwned) mc.options.keyUse.setDown(false);
            shieldOwned=true; // Cleanup also owns a use attempt that throws.
            // The explicit offhand shield use cannot open the block under the ray.
            mc.gameMode.useItem(mc.player,InteractionHand.OFF_HAND);
            boolean activeShield=mc.player.isUsingItem() && mc.player.getUsedItemHand() == InteractionHand.OFF_HAND
                    && mc.player.getUseItem().is(Items.SHIELD);
            if (activeShield) mc.options.keyUse.setDown(true);
            else shield(mc,false);
        }
    }
    void release(Minecraft mc) { shield(mc,false); }
    private LivingEntity target(Minecraft mc) {
        Entity entity=mc.level.getEntity(request.targetId());
        if (!(entity instanceof LivingEntity living) || !entity.getUUID().toString().equals(request.targetUuid())
                || !BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString().equals(request.targetType())) return null;
        return living;
    }
    private void observe(Minecraft mc, LivingEntity target) {
        float player=mc.player.getHealth(), health=target.getHealth();
        if (player < lastPlayerHealth) playerHealthLost += lastPlayerHealth-player;
        if (health < lastTargetHealth) { targetHealthLost += lastTargetHealth-health; healthDecreases++; }
        lastPlayerHealth=player; lastTargetHealth=health;
        if (mc.player.isBlocking()) shieldBlockingTicks++;
        number(evidence,"player_health",player);
        number(evidence,"target_health",health);
        number(evidence,"player_health_lost_observed",playerHealthLost);
        number(evidence,"target_health_lost_observed",targetHealthLost);
        evidence.addProperty("target_health_decreases_observed",healthDecreases);
        evidence.addProperty("shield_blocking_ticks_observed",shieldBlockingTicks);
        evidence.addProperty("blocking",mc.player.isBlocking());
        evidence.addProperty("shield_use_ticks",mc.player.getTicksUsingItem());
    }
    private boolean sweepRisk(Minecraft mc, LivingEntity target) {
        CombatThreats.Gate sweep=CombatThreats.sweep(threats,System.nanoTime(),currentTick,
                target.getId(),target.getUUID().toString());
        evidence.addProperty("sweep_reason",sweep.reason());
        evidence.addProperty("sweep_collateral_entity_id",sweep.emergencyId());
        return sweep.stop();
    }
    private static boolean weapon(Object item) { return item instanceof SwordItem || item instanceof AxeItem; }
    private static void reject(String reason) { throw new ClientActionRequest.Rejected(409,reason); }
}
