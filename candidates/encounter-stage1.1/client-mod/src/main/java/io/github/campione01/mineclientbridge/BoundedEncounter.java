package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.function.BiConsumer;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/**
 * Stage-1 native owner state machine. Executes no attack and does not restart an action.
 * Production and replay use this same code and the existing retreat window composition.
 * All limits are cooperative observations, not a hard realtime or survival guarantee.
 */
final class BoundedEncounter {
    static final double MAX_DISTANCE=4, SEGMENT_DISTANCE=1.5;
    static final int MAX_TICKS=60, CLEAR_SAMPLES=3;
    static final long MAX_NANOS=3_000_000_000L;
    record Decision(float forward,CombatDetour.Point goal,String terminal,String reason,
                    CombatRetreatDiagnostics diagnostics,JsonObject diagnosticEvidence,boolean planning) { }
    private final EncounterRequest request;
    private final JsonObject evidence,root;
    private final double originX,originY,originZ;
    private final long deadline,started;
    private final LongSupplier clock;
    // Deliberately the same guard for the entire action; segment changes cannot replace it.
    private final CombatThreats.HealthGuard healthGuard;
    private final CombatRouteMotion motionGuard=new CombatRouteMotion();
    private CombatRetreatPolicy.Progress progress;
    private CombatThreats.Snapshot previous;
    private CombatRecovery.Motion previousPose;
    private CombatDetour.Point goal;
    private int startTick=-1,lastTick=-1,segments,revocations,clearSamples;
    private long lastNanos,lastObservationNanos;
    private double travelled;
    private String terminalStatus,terminalReason;

    BoundedEncounter(EncounterRequest request,JsonObject root,double x,double y,double z,long deadline,
                     LongSupplier clock,CombatThreats.HealthGuard healthGuard) {
        this.request=request;this.root=root;this.originX=x;this.originY=y;this.originZ=z;
        this.deadline=deadline;this.clock=clock;this.started=clock.getAsLong();this.lastObservationNanos=started;this.healthGuard=healthGuard;
        evidence=new JsonObject();root.add("encounter",evidence);
        evidence.addProperty("encounter_schema_version",1);evidence.addProperty("encounter_mode",EncounterRequest.MODE);
        evidence.add("encounter_scope",request.json());evidence.addProperty("offense_disabled",true);
        evidence.addProperty("risk_remaining",true);evidence.addProperty("requires_handoff",true);
        evidence.addProperty("safety_assured",false);evidence.addProperty("danger_radius",CombatThreats.DANGER_RADIUS);
        evidence.addProperty("clearance_observations",0);evidence.add("scoped_living_threats",new JsonArray());
        evidence.addProperty("outcome_scope",(String)null);
        evidence.addProperty("max_total_distance",MAX_DISTANCE);evidence.addProperty("max_total_ticks",MAX_TICKS);
        evidence.addProperty("max_total_nanos",MAX_NANOS);evidence.addProperty("segment_distance",SEGMENT_DISTANCE);
        evidence.addProperty("release_timing","next_client_thread_callback_not_hard_realtime");
    }

    /** Used by every existing client context callback, including input/post, before replaying a.forward. */
    String callbackInterruption(long now) {
        if(now-started<0 || lastTick>=0 && now-lastNanos<0) return "encounter_clock_invalid_risk_remaining";
        if(now>=deadline) return "deadline_exceeded";
        if(now-started>=MAX_NANOS) return "retreat_budget_risk_remaining";
        if(now-Math.min(lastTick<0?started:lastNanos,lastObservationNanos)>CombatThreats.MAX_SNAPSHOT_AGE_NANOS)
            return "encounter_callback_observation_gap_risk_remaining";
        return null;
    }

    static String lifecycle(boolean paused,boolean focused,boolean spectator) {
        if(paused) return "encounter_paused_risk_remaining";
        if(!focused) return "encounter_window_unfocused_risk_remaining";
        if(spectator) return "encounter_player_unavailable_risk_remaining";
        return null;
    }

    Decision tick(int tick,CombatThreats.Snapshot snapshot,CombatRecovery.Motion pose,
                  CombatThreats.HealthGuard.Result health,CombatDetour.EdgeCheck window,
                  Supplier<FlatStepCorridor.CellRef> rejectedCell,
                  BiConsumer<JsonObject,CombatRetreatDiagnostics> append) {
        if(terminalStatus!=null) return decision(0,terminalStatus,terminalReason,null,null,false);
        long now=clock.getAsLong();
        if(startTick<0) startTick=tick;
        // Prior movement is never an input authorization for a new tick.
        evidence.addProperty("movement_authorized",false);
        evidence.addProperty("evaluated_tick",tick);evidence.addProperty("scope_current",false);
        evidence.addProperty("snapshot_captured_nanos",snapshot==null?null:snapshot.capturedNanos());
        CombatHealthEvidence.append(evidence,healthGuard);
        if(tick<0 || tick<=lastTick || now-started<0 || lastTick>=0 && now-lastNanos<0)
            return fail("encounter_clock_invalid_risk_remaining");
        lastTick=tick;lastNanos=now;
        if(pose==null || !pose.finite()) return fail("invalid_retreat_motion_risk_remaining");
        double distance=previousPose==null ? distance(originX,originY,originZ,pose)
                : distance(previousPose.x(),previousPose.y(),previousPose.z(),pose);
        travelled+=distance;
        CombatRecovery.Motion priorPose=previousPose;previousPose=pose;
        evidence.addProperty("total_distance_observed",travelled);
        evidence.addProperty("elapsed_ticks",tick-startTick);evidence.addProperty("elapsed_nanos",now-started);
        evidence.addProperty("remaining_distance",Math.max(0,MAX_DISTANCE-travelled));
        evidence.addProperty("segments_planned",segments);evidence.addProperty("route_revocations",revocations);
        if(now>=deadline) return fail("deadline_exceeded");
        if(tick-startTick>=MAX_TICKS || now-started>=MAX_NANOS || travelled>=MAX_DISTANCE)
            return fail("retreat_budget_risk_remaining");
        if(!CombatSpatial.withinCombatArea(pose.x(),pose.y(),pose.z(),originX,originY,originZ))
            return fail("combat_area_limit");
        if(!pose.onGround() || pose.heightOffset()>.05) return fail("unsafe_retreat_pose_risk_remaining");
        String invalid=CombatThreats.snapshotProblem(snapshot,now,tick);
        if(invalid!=null) return fail(invalid+"_risk_remaining");
        lastObservationNanos=snapshot.capturedNanos();
        // Higher-priority unsupported threats are never hidden by the old target or health latch.
        for(var e:snapshot.entities()) if(e.alive() && e.type().equals("minecraft:creeper"))
            return fail("critical_creeper_near_risk_remaining");
        for(var e:snapshot.entities()) if(e.alive() && e.type().equals("minecraft:enderman"))
            return fail("enderman_gaze_unplanned_risk_remaining");
        for(var e:snapshot.entities()) if(e.alive() && e.isDangerous() && !e.type().equals("minecraft:zombie"))
            return fail("encounter_unsupported_threat_risk_remaining");
        for(var e:snapshot.entities()) if(e.alive() && e.isDangerous() && request.scope().stream().noneMatch(i->i.matches(e)))
            return fail("encounter_threat_outside_scope_risk_remaining");
        var diagnostics=healthGuard.diagnostics();
        var currentHealth=diagnostics==null?null:diagnostics.current();
        // Trigger metrics stay latched. Current sample continuity is a separate nonrenewable gate.
        if(currentHealth==null || currentHealth.sampleTick()!=tick || !currentHealth.dataValid())
            return fail("health_data_unknown_risk_remaining");
        if(!currentHealth.clockValid()) return fail("health_clock_invalid_risk_remaining");
        if(currentHealth.wallGap() || currentHealth.tickGap() || currentHealth.frozenTick())
            return fail("health_observation_gap_risk_remaining");
        if(health==null || !health.known()) return fail((health==null?"health_unknown":health.reason())+"_risk_remaining");
        evidence.addProperty("health_interruption_latched",health.interrupted());
        evidence.addProperty("health_reason",health.reason());
        CombatDetour.Point current=new CombatDetour.Point(pose.x(),pose.z());
        boolean initialScope=previous==null;
        String changed=previous==null?null:CombatRetreatPolicy.continuity(previous,snapshot,
                new CombatDetour.Point(priorPose.x(),priorPose.z()),current);
        previous=snapshot;
        JsonArray observed=new JsonArray();
        boolean clear=true;int living=0;
        for(var identity:request.scope()) {
            var found=snapshot.entities().stream().filter(identity::matches).filter(CombatThreats.Observed::alive).findFirst().orElse(null);
            if(found==null) { clear=false;continue; }
            living++;
            double clearance=Math.hypot(pose.x()-found.x(),pose.z()-found.z())-found.radius();
            JsonObject item=new JsonObject();item.addProperty("entity_id",found.entityId());item.addProperty("uuid",found.uuid());
            item.addProperty("type",found.type());item.addProperty("known",true);item.addProperty("alive",true);
            item.addProperty("clearance",clearance);observed.add(item);
            if(clearance<=CombatThreats.DANGER_RADIUS) clear=false;
        }
        evidence.add("scoped_living_threats",observed);
        evidence.addProperty("scope_evaluated_tick",tick);evidence.addProperty("scope_current",true);
        evidence.addProperty("scope_fully_observed",living==2);
        evidence.addProperty("missing_scope_is_kill",false);
        if(initialScope && living!=2) return fail("encounter_initial_scope_unobserved_risk_remaining");
        if(changed!=null && (goal!=null || clearSamples>0)) return revoke(changed);
        if(changed!=null) evidence.addProperty("last_unpermitted_snapshot_change",changed);
        if(living==0) return fail("encounter_scope_unobserved_risk_remaining");
        // Limited completion requires actual fresh full-scope evidence and settled motion.
        boolean settled=Math.hypot(pose.vx(),pose.vz())<=CombatRecovery.MAX_HORIZONTAL_SPEED
                && Math.abs(pose.vy())<=CombatRecovery.MAX_VERTICAL_SPEED;
        if(clear && !health.interrupted()) {
            goal=null;progress=null;evidence.remove("goal");
            clearSamples=settled?clearSamples+1:0;
            evidence.addProperty("clearance_observations",clearSamples);
            if(clearSamples>=CLEAR_SAMPLES) {
                evidence.addProperty("outcome_scope","two_scoped_living_zombies_beyond_8_for_3_samples");
                terminal("succeeded","encounter_clearance_observed");
                return decision(0,"succeeded",terminalReason,null,null,false);
            }
            return decision(0,null,"encounter_observing_clearance_risk_remaining",null,null,false);
        }
        clearSamples=0;evidence.addProperty("clearance_observations",0);
        double remaining=MAX_DISTANCE-travelled;
        // Reserve the unchanged .65 lookahead before issuing a new movement request.
        if(remaining<CombatRetreatPolicy.WINDOW_DISTANCE+1e-7)
            return fail("retreat_distance_budget_risk_remaining");
        if(goal==null) {
            double length=Math.min(SEGMENT_DISTANCE,remaining-CombatRetreatPolicy.WINDOW_DISTANCE);
            if(length<=CombatRetreatPolicy.ARRIVAL_DISTANCE+CombatThreats.ESCAPE_IMPROVEMENT)
                return fail("retreat_segment_budget_risk_remaining");
            var plan=CombatRetreatPolicy.plan(snapshot,current,window,clock,rejectedCell,length);
            JsonObject data=new JsonObject();data.addProperty("reason",plan.reason());
            data.addProperty("evaluated_tick",tick);data.addProperty("candidate_checks",plan.candidateChecks());
            data.addProperty("window_checks",plan.windowChecks());data.addProperty("budget_exhausted",plan.budgetExhausted());
            JsonObject rejections=new JsonObject();plan.rejections().forEach(rejections::addProperty);data.add("rejections",rejections);
            data.addProperty("segment_distance",length);evidence.add("plan",data);
            append.accept(data,plan.diagnostics());
            if(plan.diagnostics().checkBudget("encounter_plan_publication"))
                return budgetFailure(true,data,plan.diagnostics());
            CombatRetreatEvidence.stamp(data,plan.diagnostics());
            if(plan.goal()==null) return fail(plan.reason().equals("retreat_check_budget")
                    ?"retreat_planning_budget_risk_remaining":"no_safe_retreat_risk_remaining");
            goal=plan.goal();progress=new CombatRetreatPolicy.Progress();progress.start(snapshot,current,goal,tick,now);
            segments++;evidence.addProperty("segments_planned",segments);writeGoal();
            // This is a new permit against the current snapshot, never the revoked route.
            // Planning already checked every window; motion admission and diagnostics share its 8ms budget.
            var motion=motionGuard.sample(tick,pose,goal.x()-current.x(),goal.z()-current.z(),true);
            evidence.addProperty("motion_reason",motion.reason());
            if(!motion.ready()) return fail(motion.reason()+"_risk_remaining");
            evidence.addProperty("movement_authorized",true);
            return checkedDecision(length<.5?.35F:1F,null,"encounter_retreat_planned_risk_remaining",plan.diagnostics(),data,true);
        }
        String problem=progress.observe(snapshot,current,tick,now);
        if(problem!=null) return fail(problem+"_risk_remaining");
        double toGoal=current.distance(goal);
        if(toGoal<=CombatRetreatPolicy.ARRIVAL_DISTANCE) return revoke("retreat_segment_completed");
        var motion=motionGuard.sample(tick,pose,goal.x()-current.x(),goal.z()-current.z(),true);
        evidence.addProperty("motion_reason",motion.reason());
        if(!motion.ready()) return fail(motion.reason()+"_risk_remaining");
        var validation=CombatRetreatPolicy.validate(current,goal,window,clock,rejectedCell);
        JsonObject data=new JsonObject();data.addProperty("reason",validation.reason());
        data.addProperty("evaluated_tick",tick);data.addProperty("window_checks",validation.windows());
        data.addProperty("all_remaining_windows_revalidated",validation.clear());data.addProperty("budget_exhausted",validation.budgetExhausted());
        evidence.add("live_validation",data);append.accept(data,validation.diagnostics());
        if(validation.diagnostics().checkBudget("encounter_pre_motion"))
            return budgetFailure(false,data,validation.diagnostics());
        CombatRetreatEvidence.stamp(data,validation.diagnostics());
        if(!validation.clear()) return fail(validation.budgetExhausted()?"retreat_revalidation_budget_risk_remaining":"retreat_blocked_risk_remaining");
        evidence.addProperty("movement_authorized",true);
        return checkedDecision(toGoal<.5?.35F:1F,null,"encounter_retreating_risk_remaining",validation.diagnostics(),data,false);
    }

    private Decision checkedDecision(float forward,String status,String reason,CombatRetreatDiagnostics d,JsonObject data,boolean planning) {
        if(d.checkBudget("encounter_decision_return")) return budgetFailure(planning,data,d);
        String expired=callbackInterruption(clock.getAsLong());
        if(expired!=null) return fail(expired);
        CombatRetreatEvidence.stamp(data,d);return decision(forward,status,reason,d,data,planning);
    }
    private Decision budgetFailure(boolean plan,JsonObject data,CombatRetreatDiagnostics d) {
        data.addProperty("reason","retreat_check_budget");data.addProperty("budget_exhausted",true);
        data.addProperty("all_remaining_windows_revalidated",false);CombatRetreatEvidence.stamp(data,d);
        return fail(plan?"retreat_planning_budget_risk_remaining":"retreat_revalidation_budget_risk_remaining");
    }
    private Decision revoke(String reason) {
        goal=null;progress=null;revocations++;clearSamples=0;
        evidence.remove("goal");evidence.addProperty("movement_authorized",false);
        evidence.addProperty("last_revocation_reason",reason);evidence.addProperty("route_revocations",revocations);
        evidence.addProperty("clearance_observations",0);
        return decision(0,null,"encounter_reassess_"+reason+"_risk_remaining",null,null,false);
    }
    private Decision fail(String reason) { terminal("failed",reason);return decision(0,"failed",reason,null,null,false); }
    void terminal(String status,String reason) {
        goal=null;progress=null;terminalStatus=status;terminalReason=reason;
        evidence.remove("goal");evidence.addProperty("movement_authorized",false);
        if(evidence.has("state") && !evidence.get("state").getAsString().equals(reason))
            evidence.add("previous_decision_state",evidence.get("state").deepCopy());
        evidence.addProperty("state",reason);
        if(root.has("decision_phase") && !root.get("decision_phase").getAsString().equals(reason))
            root.add("previous_decision_phase",root.get("decision_phase").deepCopy());
        root.addProperty("requested_forward",0);root.addProperty("decision_phase",reason);
        evidence.addProperty("terminal_status",status);evidence.addProperty("terminal_reason",reason);
        if(!status.equals("succeeded")) evidence.addProperty("outcome_scope",(String)null);
        evidence.addProperty("risk_remaining",true);evidence.addProperty("requires_handoff",true);evidence.addProperty("safety_assured",false);
        root.addProperty("risk_remaining",true);root.addProperty("safety_assured",false);
        root.addProperty("attack_completed",false);root.addProperty("outcome_kind",status.equals("succeeded")?"bounded_clearance_observed":"risk_remaining");
    }
    private Decision decision(float forward,String status,String reason,CombatRetreatDiagnostics d,JsonObject data,boolean plan) {
        evidence.addProperty("state",reason);return new Decision(forward,goal,status,reason,d,data,plan);
    }
    private void writeGoal() {
        JsonObject data=new JsonObject();data.addProperty("x",goal.x());data.addProperty("z",goal.z());evidence.add("goal",data);
    }
    private static double distance(double x,double y,double z,CombatRecovery.Motion to) {
        return Math.sqrt(Math.pow(x-to.x(),2)+Math.pow(y-to.y(),2)+Math.pow(z-to.z(),2));
    }
}
