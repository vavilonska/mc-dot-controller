package io.github.campione01.mineclientbridge;

import java.util.List;
import java.util.function.LongSupplier;

/** Production composition shared by every retreat planning and execution window. No game inputs. */
final class CombatRetreatWindow {
    record Result(CombatDetour.EdgeResult edge,FlatStepCorridor.Result terrain,int blockedEntityId) { }
    static Result check(CombatThreats.Snapshot threats,long now,int tick,FlatStepCorridor.Pose from,
                        CombatDetour.Point to,double originX,double originY,double originZ,
                        FlatStepCorridor.CellSource cells,List<CombatSpatial.Box> obstacles) {
        return check(threats,now,tick,from,to,originX,originY,originZ,cells,obstacles,null);
    }
    static Result check(CombatThreats.Snapshot threats,long now,int tick,FlatStepCorridor.Pose from,
                        CombatDetour.Point to,double originX,double originY,double originZ,
                        FlatStepCorridor.CellSource cells,List<CombatSpatial.Box> obstacles,Metrics metrics) {
        Result result;
        long windowStarted=start(metrics,Stage.WINDOW_TOTAL);
        try { result=checkObserved(threats,now,tick,from,to,originX,originY,originZ,cells,obstacles,metrics); }
        catch(RuntimeException exception) { result=denied("retreat_window_exception",null,-1); }
        finally { end(metrics,Stage.WINDOW_TOTAL,windowStarted); }
        if(metrics!=null && metrics.clockInvalid) return denied("retreat_window_clock_invalid",result.terrain(),result.blockedEntityId());
        return result;
    }
    private static Result checkObserved(CombatThreats.Snapshot threats,long now,int tick,FlatStepCorridor.Pose from,
                        CombatDetour.Point to,double originX,double originY,double originZ,
                        FlatStepCorridor.CellSource cells,List<CombatSpatial.Box> obstacles,Metrics metrics) {
        if(from==null || to==null) return denied("invalid_retreat_window",null,-1);
        double dx=to.x()-from.x(),dz=to.z()-from.z(),length=Math.hypot(dx,dz);
        if(!Double.isFinite(length) || length<=0 || length>CombatRetreatPolicy.WINDOW_DISTANCE+1e-7
                || !CombatSpatial.withinCombatArea(to.x(),from.y(),to.z(),originX,originY,originZ))
            return denied("route_area_or_length_limit",null,-1);
        CombatThreats.Route risk=threatRoute(threats,now,tick,from.x(),from.z(),to.x(),to.z(),metrics);
        if(!risk.safe()) return denied(risk.reason(),null,-1);
        if(risk.endpointClearance()+1e-7<risk.minimumClearance()+CombatThreats.ESCAPE_IMPROVEMENT)
            return denied("escape_no_minimum_clearance_progress",null,-1);
        // A short goal remainder must not shrink the original .65 motion lookahead. Lower forward
        // input is not braking: existing velocity may carry the player past the goal this tick.
        double probeX=dx/length*CombatRetreatPolicy.WINDOW_DISTANCE;
        double probeZ=dz/length*CombatRetreatPolicy.WINDOW_DISTANCE;
        if(!CombatSpatial.withinCombatArea(from.x()+probeX,from.y(),from.z()+probeZ,originX,originY,originZ))
            return denied("route_area_or_length_limit",null,-1);
        CombatThreats.Route envelopeRisk=threatRoute(threats,now,tick,from.x(),from.z(),from.x()+probeX,from.z()+probeZ,metrics);
        if(!envelopeRisk.safe()) return denied(envelopeRisk.reason(),null,-1);
        CombatSpatial.Result body=dynamic(from,probeX,probeZ,obstacles,metrics);
        if(!body.clear()) return denied(body.reason(),null,body.entityId());
        FlatStepCorridor.Result terrain=terrain(from,probeX,probeZ,cells,metrics,Stage.CENTER_TERRAIN);
        if(!terrain.clear()) return denied(terrain.reason(),terrain,-1);
        long envelopeStarted=start(metrics,Stage.ENVELOPE);
        try { terrain=CombatRouteEnvelope.check(from,probeX,probeZ,cells,obstacles,metrics); }
        finally { end(metrics,Stage.ENVELOPE,envelopeStarted); }
        if(!terrain.clear()) return denied(terrain.reason(),terrain,-1);
        return new Result(new CombatDetour.EdgeResult(true,Math.min(100,risk.minimumClearance()),"clear"),terrain,-1);
    }
    enum Stage { THREAT_ROUTES, DYNAMIC_OBSTACLES, CENTER_TERRAIN, ENVELOPE, ENVELOPE_TERRAIN,
        WINDOW_TOTAL, TERRAIN_CELL_READ }
    /** Aggregate-only observations; envelope duration contains its terrain/dynamic subdurations. */
    static final class Metrics {
        private final LongSupplier clock;
        final long[] calls=new long[Stage.values().length],nanos=new long[Stage.values().length];
        boolean clockInvalid;
        private boolean sampled;
        private long previous;
        Metrics() { this(System::nanoTime); }
        Metrics(LongSupplier clock) { this.clock=clock; }
        private long sample() {
            long now=previous;
            try { now=clock.getAsLong(); } catch(RuntimeException exception) { clockInvalid=true; }
            if(sampled && now-previous<0) clockInvalid=true;
            sampled=true;previous=now;return now;
        }
        long calls(Stage stage) { return calls[stage.ordinal()]; }
        long nanos(Stage stage) { return nanos[stage.ordinal()]; }
    }
    private static long start(Metrics metrics,Stage stage) {
        if(metrics==null) return 0;
        metrics.calls[stage.ordinal()]++;return metrics.sample();
    }
    private static void end(Metrics metrics,Stage stage,long started) {
        if(metrics==null) return;
        long duration=metrics.sample()-started;
        if(duration<0) metrics.clockInvalid=true;
        else if(Long.MAX_VALUE-metrics.nanos[stage.ordinal()]<duration) metrics.clockInvalid=true;
        else metrics.nanos[stage.ordinal()]+=duration;
    }
    private static CombatThreats.Route threatRoute(CombatThreats.Snapshot threats,long now,int tick,
                                                   double x,double z,double toX,double toZ,Metrics metrics) {
        long started=start(metrics,Stage.THREAT_ROUTES);
        try { return CombatThreats.escapeRoute(threats,now,tick,x,z,toX,toZ); }
        finally { end(metrics,Stage.THREAT_ROUTES,started); }
    }
    static CombatSpatial.Result dynamic(FlatStepCorridor.Pose pose,double dx,double dz,
                                         List<CombatSpatial.Box> obstacles,Metrics metrics) {
        long started=start(metrics,Stage.DYNAMIC_OBSTACLES);
        try { return CombatSpatial.check(pose.x(),pose.y(),pose.z(),dx,dz,obstacles); }
        finally { end(metrics,Stage.DYNAMIC_OBSTACLES,started); }
    }
    static FlatStepCorridor.Result terrain(FlatStepCorridor.Pose pose,double dx,double dz,
                                           FlatStepCorridor.CellSource cells,Metrics metrics,Stage stage) {
        long started=start(metrics,stage);
        try {
            FlatStepCorridor.CellSource measured=cells;
            if(metrics!=null && cells!=null) measured=new MeasuredCells(cells,metrics);
            return FlatStepCorridor.check(pose,dx,dz,measured);
        }
        finally { end(metrics,stage,started); }
    }
    private record MeasuredCells(FlatStepCorridor.CellSource source,Metrics metrics) implements FlatStepCorridor.CellSource {
        @Override public FlatStepCorridor.Cell read(int x,int y,int z) {
            long started=start(metrics,Stage.TERRAIN_CELL_READ);
            try { return source.read(x,y,z); }
            finally { end(metrics,Stage.TERRAIN_CELL_READ,started); }
        }
    }
    private static Result denied(String reason,FlatStepCorridor.Result terrain,int entityId) {
        return new Result(new CombatDetour.EdgeResult(false,0,reason),terrain,entityId);
    }
    private CombatRetreatWindow() { }
}
