package io.github.campione01.mineclientbridge;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.LongSupplier;

/** Bounded client-observed withdrawal checks. Admission never establishes safety or a kill. */
final class CombatRetreatPolicy {
    static final double WINDOW_DISTANCE = .65, PLAN_DISTANCE = 3, ARRIVAL_DISTANCE = .25;
    static final double MAX_PATH_DISTANCE = 4, MIN_OBSERVED_ADVANCE = .1;
    static final int MAX_CANDIDATES = 16, MAX_WINDOWS = 7, MAX_PROGRESS_TICKS = 10;
    static final long MAX_CHECK_NANOS = 8_000_000L, MAX_PROGRESS_NANOS = 500_000_000L;
    private static final double EPSILON = 1e-7;

    record Validation(boolean clear, String reason, int windows, boolean firstWindowRejected,
                      boolean budgetExhausted, CombatRetreatDiagnostics diagnostics) {
        Validation(boolean clear,String reason,int windows,boolean firstWindowRejected,boolean budgetExhausted) {
            this(clear,reason,windows,firstWindowRejected,budgetExhausted,null);
        }
    }
    record Plan(CombatDetour.Point goal, String reason, int candidateChecks, int windowChecks,
                int firstWindowRejections, boolean budgetExhausted, Map<String,Integer> rejections,
                CombatRetreatDiagnostics diagnostics) {
        Plan(CombatDetour.Point goal,String reason,int candidateChecks,int windowChecks,
             int firstWindowRejections,boolean budgetExhausted,Map<String,Integer> rejections) {
            this(goal,reason,candidateChecks,windowChecks,firstWindowRejections,budgetExhausted,rejections,null);
        }
    }

    /** The next endpoint is identical in planning and execution, including a short final window. */
    static CombatDetour.Point next(CombatDetour.Point from, CombatDetour.Point goal) {
        if (!valid(from) || !valid(goal)) return null;
        double distance=from.distance(goal);
        if (!Double.isFinite(distance) || distance<=ARRIVAL_DISTANCE || distance>MAX_PATH_DISTANCE+EPSILON) return null;
        double fraction=Math.min(WINDOW_DISTANCE,distance)/distance;
        return new CombatDetour.Point(from.x()+(goal.x()-from.x())*fraction,
                from.z()+(goal.z()-from.z())*fraction);
    }

    static Validation validate(CombatDetour.Point from, CombatDetour.Point goal,
                               CombatDetour.EdgeCheck check, LongSupplier clock) {
        return validate(from,goal,check,clock,()->null);
    }

    /** Optional rejected-cell capture runs after the callback, inside the same deadline. */
    static Validation validate(CombatDetour.Point from, CombatDetour.Point goal,
                               CombatDetour.EdgeCheck check, LongSupplier clock,
                               java.util.function.Supplier<FlatStepCorridor.CellRef> rejectedCell) {
        var diagnostics=new CombatRetreatDiagnostics(clock);
        diagnostics.beginCandidate(1);
        Validation result=validate(from,goal,check,rejectedCell,diagnostics);
        diagnostics.endCandidate(result);
        if(diagnostics.checkBudget("validation_complete"))
            result=budget(result.windows(),result.windows()<=1,diagnostics);
        return result;
    }

    private static Validation validate(CombatDetour.Point from, CombatDetour.Point goal,
                                        CombatDetour.EdgeCheck check,
                                        java.util.function.Supplier<FlatStepCorridor.CellRef> rejectedCell,
                                        CombatRetreatDiagnostics diagnostics) {
        if (next(from,goal)==null || check==null)
            return new Validation(false,"invalid_retreat_window",0,true,false,diagnostics);
        CombatDetour.Point cursor=from;
        int checked=0;
        // Stop only where execution also stops. Every issued short final window still requires >= 0.1.
        while (cursor.distance(goal)>ARRIVAL_DISTANCE) {
            if (diagnostics.checkBudget("pre_window")) return budget(checked,checked==0,diagnostics);
            if (checked>=MAX_WINDOWS) return new Validation(false,"retreat_window_limit",checked,false,false,diagnostics);
            double distance=cursor.distance(goal),fraction=Math.min(WINDOW_DISTANCE,distance)/distance;
            CombatDetour.Point end=new CombatDetour.Point(cursor.x()+(goal.x()-cursor.x())*fraction,
                    cursor.z()+(goal.z()-cursor.z())*fraction);
            if (!diagnostics.beginWindow(checked+1)) return budget(checked,checked==0,diagnostics);
            CombatDetour.EdgeResult result;
            FlatStepCorridor.CellRef cell=null;
            boolean observationFailed=false,callbackReturned=true;
            try { result=check.check(cursor,end); }
            catch(RuntimeException exception) { callbackReturned=false;result=new CombatDetour.EdgeResult(false,0,"retreat_window_exception"); }
            try { if(rejectedCell!=null) cell=rejectedCell.get(); }
            catch(RuntimeException exception) { observationFailed=true; }
            checked++;
            diagnostics.endWindow(result,cell,callbackReturned);
            if (diagnostics.checkBudget("post_window")) return budget(checked,checked==1,diagnostics);
            if (observationFailed) return new Validation(false,"retreat_observation_failed",checked,checked==1,false,diagnostics);
            if (result==null || !result.clear()) return new Validation(false,
                    result==null?"retreat_window_unknown":safeReason(result.reason()),checked,checked==1,false,diagnostics);
            cursor=end;
        }
        return new Validation(true,"retreat_windows_clear_risk_remaining",checked,false,false,diagnostics);
    }

    private static Validation budget(int windows,boolean firstRejected,CombatRetreatDiagnostics diagnostics) {
        return new Validation(false,"retreat_check_budget",windows,firstRejected,true,diagnostics);
    }
    private static String safeReason(String reason) { return reason==null?"retreat_window_unknown":reason; }

    /** Try observed nearest-threat away heading first, then alternate bounded angular offsets. */
    static Plan plan(CombatThreats.Snapshot threats, CombatDetour.Point from,
                     CombatDetour.EdgeCheck check, LongSupplier clock) {
        return plan(threats,from,check,clock,()->null);
    }

    static Plan plan(CombatThreats.Snapshot threats, CombatDetour.Point from,
                     CombatDetour.EdgeCheck check, LongSupplier clock,
                     java.util.function.Supplier<FlatStepCorridor.CellRef> rejectedCell) {
        return plan(threats,from,check,clock,rejectedCell,PLAN_DISTANCE);
    }

    /** Encounter segments may shorten, never enlarge, the existing plan/check budgets. */
    static Plan plan(CombatThreats.Snapshot threats, CombatDetour.Point from,
                     CombatDetour.EdgeCheck check, LongSupplier clock,
                     java.util.function.Supplier<FlatStepCorridor.CellRef> rejectedCell, double distance) {
        var diagnostics=new CombatRetreatDiagnostics(clock);
        if (!Double.isFinite(distance) || distance<=ARRIVAL_DISTANCE || distance>PLAN_DISTANCE)
            return finish(null,"invalid_retreat_segment_distance",0,0,0,false,Map.of(),diagnostics);
        CombatThreats.Observed nearest=nearest(threats,from);
        if (nearest==null) return finish(null,"retreat_direction_unknown",0,0,0,false,Map.of(),diagnostics);
        double dx=from.x()-nearest.x(),dz=from.z()-nearest.z();
        if (Math.hypot(dx,dz)<EPSILON) return finish(null,"retreat_direction_unknown",0,0,0,false,Map.of(),diagnostics);
        double base=Math.atan2(dz,dx);
        int candidates=0,windows=0,firstRejected=0;
        Map<String,Integer> rejected=new LinkedHashMap<>();
        for (int i=0;i<MAX_CANDIDATES;i++) {
            if (diagnostics.checkBudget("pre_candidate"))
                return finish(null,"retreat_check_budget",candidates,windows,firstRejected,true,rejected,diagnostics);
            int offset=i==0?0:(i+1)/2*(i%2==1?1:-1);
            double angle=base+offset*Math.PI/8;
            CombatDetour.Point goal=new CombatDetour.Point(from.x()+Math.cos(angle)*distance,from.z()+Math.sin(angle)*distance);
            candidates++;
            diagnostics.beginCandidate(candidates);
            Validation result=validate(from,goal,check,rejectedCell,diagnostics);
            windows+=result.windows();
            if (result.firstWindowRejected()) firstRejected++;
            diagnostics.endCandidate(result);
            if (result.clear()) return finish(goal,result.reason(),candidates,windows,firstRejected,false,rejected,diagnostics);
            rejected.merge(result.reason(),1,Integer::sum);
            if (result.budgetExhausted()) return finish(null,result.reason(),candidates,windows,firstRejected,true,rejected,diagnostics);
        }
        return finish(null,"no_safe_retreat_risk_remaining",candidates,windows,firstRejected,false,rejected,diagnostics);
    }

    private static Plan finish(CombatDetour.Point goal,String reason,int candidates,int windows,int firstRejected,
                               boolean exhausted,Map<String,Integer> rejections,CombatRetreatDiagnostics diagnostics) {
        Map<String,Integer> copy=Map.copyOf(rejections);
        // Diagnostic allocation/aggregation is not subtracted or given a fresh budget.
        if(diagnostics.checkBudget("plan_complete")) { goal=null;reason="retreat_check_budget";exhausted=true; }
        return new Plan(goal,reason,candidates,windows,firstRejected,exhausted,copy,diagnostics);
    }

    /** Identity changes and observed clearance decreases are refusals, never proof danger vanished. */
    static String continuity(CombatThreats.Snapshot before, CombatThreats.Snapshot after,
                             CombatDetour.Point previous, CombatDetour.Point current) {
        if (!valid(previous) || !valid(current) || !usable(before) || !usable(after)) return "retreat_observation_unknown";
        List<CombatThreats.Observed> old=dangers(before),live=dangers(after);
        if (old.size()!=live.size()) return "retreat_threat_identity_changed";
        for (CombatThreats.Observed was:old) {
            CombatThreats.Observed now=identity(live,was);
            if (now==null || !now.type().equals(was.type()) || now.dangerous()!=was.dangerous()) return "retreat_threat_identity_changed";
            if (clearance(current,now)+EPSILON<clearance(previous,was)) return "retreat_observed_clearance_decreased";
        }
        return null;
    }

    /** Actual progress is checked over finite intervals too; moving threats alone cannot supply it. */
    static final class Progress {
        private CombatThreats.Snapshot previous,checkpoint;
        private CombatDetour.Point previousPose,checkpointPose,goal;
        private int checkpointTick,lastTick;
        private long checkpointNanos,lastNanos;
        private String failure;
        private double observedAdvance,observedClearanceGain;

        void start(CombatThreats.Snapshot snapshot,CombatDetour.Point pose,CombatDetour.Point destination,int tick,long now) {
            if (previous!=null) throw new IllegalStateException("retreat_progress_already_started");
            previous=checkpoint=snapshot;previousPose=checkpointPose=pose;goal=destination;
            checkpointTick=lastTick=tick;checkpointNanos=lastNanos=now;
        }
        String observe(CombatThreats.Snapshot snapshot,CombatDetour.Point pose,int tick,long now) {
            if (failure!=null) return failure;
            if (previous==null || tick<=lastTick || now-lastNanos<0) return failure="retreat_progress_clock_invalid";
            String changed=continuity(previous,snapshot,previousPose,pose);
            if (changed!=null) return failure=changed;
            double distance=checkpointPose.distance(goal);
            observedAdvance=((pose.x()-checkpointPose.x())*(goal.x()-checkpointPose.x())
                    +(pose.z()-checkpointPose.z())*(goal.z()-checkpointPose.z()))/distance;
            CombatThreats.Observed closest=nearest(checkpoint,checkpointPose);
            CombatThreats.Observed current=closest==null?null:identity(dangers(snapshot),closest);
            if (current==null) return failure="retreat_direction_unknown";
            // Progress follows the minimum over ALL current dangers, even when the closest changes.
            CombatThreats.Observed liveClosest=nearest(snapshot,pose);
            observedClearanceGain=clearance(pose,liveClosest)-clearance(checkpointPose,closest);
            if ((long)tick-checkpointTick>=MAX_PROGRESS_TICKS || now-checkpointNanos>=MAX_PROGRESS_NANOS) {
                if (observedAdvance+EPSILON<MIN_OBSERVED_ADVANCE || observedClearanceGain+EPSILON<CombatThreats.ESCAPE_IMPROVEMENT)
                    return failure="retreat_observed_progress_insufficient";
                checkpoint=snapshot;checkpointPose=pose;checkpointTick=tick;checkpointNanos=now;
            }
            previous=snapshot;previousPose=pose;lastTick=tick;lastNanos=now;
            return null;
        }
        double observedAdvance() { return observedAdvance; }
        double observedClearanceGain() { return observedClearanceGain; }
    }

    private static boolean usable(CombatThreats.Snapshot s) {
        return s!=null && s.known() && !s.truncated() && s.entities().stream().allMatch(e->e!=null && e.valid());
    }
    private static List<CombatThreats.Observed> dangers(CombatThreats.Snapshot s) {
        return s.entities().stream().filter(e->e.alive() && e.isDangerous()).toList();
    }
    private static CombatThreats.Observed identity(List<CombatThreats.Observed> list,CombatThreats.Observed wanted) {
        for (CombatThreats.Observed e:list) if (e.entityId()==wanted.entityId() && e.uuid().equals(wanted.uuid())) return e;
        return null;
    }
    private static CombatThreats.Observed nearest(CombatThreats.Snapshot s,CombatDetour.Point p) {
        if (!usable(s) || !valid(p)) return null;
        CombatThreats.Observed nearest=null;
        for (CombatThreats.Observed e:dangers(s)) {
            if (nearest==null || clearance(p,e)<clearance(p,nearest)
                    || clearance(p,e)==clearance(p,nearest) && e.entityId()<nearest.entityId()) nearest=e;
        }
        return nearest;
    }
    private static double clearance(CombatDetour.Point p,CombatThreats.Observed e) { return Math.hypot(p.x()-e.x(),p.z()-e.z())-e.radius(); }
    private static boolean valid(CombatDetour.Point p) { return p!=null && Double.isFinite(p.x()) && Double.isFinite(p.z()); }
}
