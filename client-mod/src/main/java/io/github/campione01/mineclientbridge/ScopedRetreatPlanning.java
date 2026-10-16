package io.github.campione01.mineclientbridge;

import java.util.Set;
import java.util.function.LongSupplier;

/** Scoped-only scheduling. Proposals contain geometry, never a retained safety permit. */
final class ScopedRetreatPlanning {
    record Proposal(int index,CombatDetour.Point goal) { }
    record Checked(boolean clear,boolean hardFailure,String reason,int windows,long elapsedNanos,
                   boolean softBudgetExceeded) { }
    /** A cursor remembers only bounded enumeration progress, not previously checked windows. */
    static final class Cursor {
        private int next,lastTick=-1;
        private boolean closed;
        Proposal next(CombatThreats.Snapshot snapshot,CombatDetour.Point from,int tick) {
            if(closed || tick<=lastTick) throw new IllegalStateException("scoped_retreat_cursor_closed_or_tick_invalid");
            lastTick=tick;
            if(next>=CombatRetreatPolicy.MAX_CANDIDATES) { closed=true;return null; }
            int index=next++;
            CombatDetour.Point goal=CombatRetreatPolicy.proposal(snapshot,from,index);
            if(goal==null) { closed=true;return null; }
            return new Proposal(index,goal);
        }
        int attempts() { return next; }
        void close() { closed=true; }
    }
    // Only observed, ordinary geometric refusals permit trying another heading next tick.
    // Missing/unknown/stale data, exceptions and unrecognised reasons are terminal refusals.
    private static final Set<String> GEOMETRIC=Set.of("route_area_or_length_limit",
            "route_reduces_threat_clearance","escape_no_clearance_progress",
            "escape_no_minimum_clearance_progress","dynamic_entity_collision",
            "feet_collision","head_collision","fluid","hazard","missing_support","out_of_world");

    /** One complete candidate per invocation; no partial result can be resumed or authorize input.
     * The supplied real execution fence owns the existing context/tick/50ms hard boundary.
     * Eight milliseconds is reported as scheduling pressure, never a verdict about clear geometry.
     */
    static Checked validateAll(CombatDetour.Point from,CombatDetour.Point goal,CombatDetour.EdgeCheck check,
                               LongSupplier clock,Runnable hardFence) {
        Clock time;
        try { time=new Clock(clock); }
        catch(RuntimeException invalid) { return new Checked(false,true,"retreat_validation_clock_invalid",0,0,false); }
        int windows=0;
        try {
            fence(time,hardFence);
            if(CombatRetreatPolicy.next(from,goal)==null || check==null)
                return result(false,true,"invalid_retreat_window",windows,time);
            CombatDetour.Point cursor=from;
            while(cursor.distance(goal)>CombatRetreatPolicy.ARRIVAL_DISTANCE) {
                fence(time,hardFence);
                if(windows>=CombatRetreatPolicy.MAX_WINDOWS)
                    return result(false,true,"retreat_window_limit",windows,time);
                CombatDetour.Point end=CombatRetreatPolicy.next(cursor,goal);
                if(end==null) return result(false,true,"invalid_retreat_window",windows,time);
                CombatDetour.EdgeResult edge=check.check(cursor,end);
                windows++;
                fence(time,hardFence);
                if(edge==null) return result(false,true,"retreat_window_unknown",windows,time);
                if(!edge.clear()) return result(false,!GEOMETRIC.contains(edge.reason()),edge.reason(),windows,time);
                cursor=end;
            }
            fence(time,hardFence);
            return result(true,false,"retreat_windows_clear_risk_remaining",windows,time);
        } catch(ClockInvalid invalid) {
            return new Checked(false,true,"retreat_validation_clock_invalid",windows,time.elapsed,time.soft());
        } catch(RuntimeException refusal) {
            return new Checked(false,true,"retreat_execution_fence_or_callback_failed",windows,time.elapsed,time.soft());
        }
    }
    private static void fence(Clock time,Runnable hardFence) {
        time.sample();hardFence.run();time.sample();
    }
    private static Checked result(boolean clear,boolean hard,String reason,int windows,Clock time) {
        time.sample();return new Checked(clear,hard,reason,windows,time.elapsed,time.soft());
    }
    private static final class ClockInvalid extends RuntimeException { }
    private static final class Clock {
        final LongSupplier source;
        final long started;
        long previous,elapsed;
        Clock(LongSupplier source) { this.source=source;started=previous=source.getAsLong(); }
        void sample() {
            long now;
            try { now=source.getAsLong(); } catch(RuntimeException invalid) { throw new ClockInvalid(); }
            if(now-previous<0 || now-started<0) throw new ClockInvalid();
            previous=now;elapsed=now-started;
        }
        boolean soft() { return elapsed>=CombatRetreatPolicy.MAX_CHECK_NANOS; }
    }
    private ScopedRetreatPlanning() { }
}
