package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.LongSupplier;

/** Actual production pure helpers, deterministic synthetic observations; no engine initialization. */
public final class ScopedRetreatPlanningChecks {
    private static int assertions,scenarios;
    private static final CombatDetour.Point START=new CombatDetour.Point(0,0),AWAY=new CombatDetour.Point(0,-3);
    private static final CombatDetour.EdgeResult CLEAR=new CombatDetour.EdgeResult(true,1,"clear");
    private static final FlatStepCorridor.Cell SOLID=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:stone",true,false,true,"minecraft:empty",false);
    private static final FlatStepCorridor.Cell AIR=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:air",true,true,false,"minecraft:empty",false);
    private static final FlatStepCorridor.Cell UNKNOWN=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNKNOWN,null,false,false,false,null,false);
    private static final FlatStepCorridor.CellSource FLOOR=(x,y,z)->y==63?SOLID:AIR;
    private static void yes(boolean value,String message) { assertions++;if(!value)throw new AssertionError(message); }
    private static void eq(Object a,Object b,String message) { yes(java.util.Objects.equals(a,b),message+" expected="+b+" got="+a); }
    private static void throwsRuntime(Runnable callback,String message) {
        boolean refused=false;try { callback.run(); } catch(RuntimeException expected) { refused=true; }
        yes(refused,message);
    }
    private static CombatThreats.Snapshot snapshot(int tick,long ns,double z) {
        return new CombatThreats.Snapshot(List.of(new CombatThreats.Observed(1,"one","minecraft:zombie",0,64,z,.3,true,true)),ns,tick,false,true);
    }
    private static Runnable fence(AtomicLong now,long started,AtomicInteger gameTick,int expectedTick,CombatThreats.Snapshot snapshot) {
        return ()->{
            if(now.get()-started<0 || now.get()-started>50_000_000L || gameTick.get()!=expectedTick)
                throw new IllegalStateException("existing_scoped_callback_fence");
            if(CombatThreats.snapshotProblem(snapshot,now.get(),expectedTick)!=null)
                throw new IllegalStateException("freshness");
        };
    }
    private static CombatDetour.EdgeCheck world(CombatThreats.Snapshot snapshot,AtomicLong now,FlatStepCorridor.CellSource cells,List<CombatSpatial.Box> boxes) {
        return (a,b)->CombatRetreatWindow.check(snapshot,now.get(),snapshot.capturedTick(),
                new FlatStepCorridor.Pose(a.x(),64,a.z(),true,0),b,0,64,0,cells,boxes).edge();
    }
    private static void t44ColdClear() {
        scenarios++;
        AtomicLong now=new AtomicLong();AtomicInteger calls=new AtomicInteger(),tick=new AtomicInteger(4);
        var snapshot=snapshot(4,0,5);
        var checked=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->{
            now.addAndGet(calls.getAndIncrement()==0?15_439_656L:100_000L);return world(snapshot,now,FLOOR,List.of()).check(a,b);
        },now::get,fence(now,0,tick,4,snapshot));
        yes(checked.clear(),"T44-sized cold first window can finish the complete candidate");
        eq(checked.windows(),5,"all five windows required");yes(checked.softBudgetExceeded(),"8ms recorded as scheduling pressure");
        yes(!checked.hardFailure(),"no unsafe claim for clear geometry");eq(checked.elapsedNanos(),15_839_656L,"complete observed duration");
        now.set(0);calls.set(0);
        var legacy=CombatRetreatPolicy.plan(snapshot,START,(a,b)->{now.addAndGet(15_439_656L);calls.incrementAndGet();return CLEAR;},now::get);
        yes(legacy.goal()==null && legacy.budgetExhausted(),"legacy policy remains 8ms hard refusal");
        eq(calls.get(),1,"legacy still fails first window");eq(legacy.diagnostics().budgetCheckStage(),"post_window","legacy exact stage");
    }
    private static void boundaries() {
        scenarios++;
        for(long elapsed:new long[]{7_999_999L,8_000_000L,8_000_001L,50_000_000L,50_000_001L}) {
            AtomicLong now=new AtomicLong();AtomicInteger calls=new AtomicInteger(),tick=new AtomicInteger(1);
            var snapshot=snapshot(1,0,5);
            var result=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->{if(calls.getAndIncrement()==0)now.set(elapsed);return CLEAR;},now::get,fence(now,0,tick,1,snapshot));
            eq(result.clear(),elapsed<=50_000_000L,"existing 50ms hard boundary");
            eq(result.softBudgetExceeded(),elapsed>=8_000_000L,"exact 8ms soft boundary");
            if(elapsed>50_000_000L) {yes(result.hardFailure(),"hard excess terminal");eq(result.windows(),1,"no further window after hard fence");}
            else eq(result.windows(),5,"no truncated clear result");
        }
        for(long age:new long[]{150_000_000L,150_000_001L}) {
            AtomicLong now=new AtomicLong(age);AtomicInteger tick=new AtomicInteger(1);var snapshot=snapshot(1,0,5);
            var result=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->CLEAR,now::get,fence(now,age,tick,1,snapshot));
            eq(result.clear(),age==150_000_000L,"existing snapshot freshness unchanged");
        }
    }
    private static void cursorBounded() {
        scenarios++;var cursor=new ScopedRetreatPlanning.Cursor();var snapshot=snapshot(0,0,5);
        var first=cursor.next(snapshot,START,0);eq(first.index(),0,"first heading");
        yes(Math.abs(first.goal().x())<1e-12 && Math.abs(first.goal().z()+3)<1e-12,"away proposal geometry");
        throwsRuntime(()->cursor.next(snapshot,START,0),"one candidate per tick");
        for(int i=1;i<16;i++)eq(cursor.next(snapshot,START,i).index(),i,"bounded cursor progress");
        yes(cursor.next(snapshot,START,16)==null,"sixteen candidate cap");eq(cursor.attempts(),16,"attempts never refunded");
        throwsRuntime(()->cursor.next(snapshot,START,17),"exhaustion latched");
        var stopped=new ScopedRetreatPlanning.Cursor();stopped.close();throwsRuntime(()->stopped.next(snapshot,START,1),"hard close never resumes");
        yes(CombatRetreatPolicy.proposal(snapshot,START,-1)==null,"negative proposal refused");
        yes(CombatRetreatPolicy.proposal(snapshot,START,16)==null,"extra proposal refused");
        yes(CombatRetreatPolicy.proposal(null,START,0)==null,"unknown proposal refused");
    }
    private static void cannotResumeWindows() {
        scenarios++;AtomicLong now=new AtomicLong();AtomicInteger tick=new AtomicInteger(1),calls=new AtomicInteger();
        var old=snapshot(1,0,5);
        var incomplete=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->{
            if(calls.incrementAndGet()==2)tick.set(2);return CLEAR;
        },now::get,fence(now,0,tick,1,old));
        yes(!incomplete.clear() && incomplete.hardFailure(),"midway tick change cannot admit");eq(incomplete.windows(),2,"stop on changed tick");
        var fresh=snapshot(2,0,5);List<Double> starts=new ArrayList<>();
        var rechecked=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->{starts.add(a.z());return new CombatDetour.EdgeResult(false,0,"feet_collision");},now::get,fence(now,0,tick,2,fresh));
        eq(starts,List.of(0.0),"new full validation starts at actual pose, not third window");
        yes(!rechecked.clear() && !rechecked.hardFailure(),"observed obstacle permits only another proposal, no motion");
    }
    private static void finalFreshRoute() {
        scenarios++;AtomicLong now=new AtomicLong();AtomicInteger tick=new AtomicInteger(1);var first=snapshot(1,0,5);
        var planning=ScopedRetreatPlanning.validateAll(START,AWAY,world(first,now,FLOOR,List.of()),now::get,fence(now,0,tick,1,first));
        yes(planning.clear(),"initial complete proposal");
        tick.set(2);var fresh=snapshot(2,0,5);
        FlatStepCorridor.CellSource blocked=(x,y,z)->z==-3 && y==64?SOLID:FLOOR.read(x,y,z);
        yes(world(fresh,now,blocked,List.of()).check(START,new CombatDetour.Point(0,-.65)).clear(),"near .65m remains clear");
        var finalCheck=ScopedRetreatPlanning.validateAll(START,AWAY,world(fresh,now,blocked,List.of()),now::get,fence(now,0,tick,2,fresh));
        yes(!finalCheck.clear(),"far remaining obstacle invalidates final execution");yes(finalCheck.windows()>1,"full remaining path was read");
        var unknown=ScopedRetreatPlanning.validateAll(START,AWAY,world(fresh,now,(x,y,z)->z==-3?UNKNOWN:FLOOR.read(x,y,z),List.of()),now::get,fence(now,0,tick,2,fresh));
        yes(!unknown.clear() && unknown.hardFailure(),"new unknown is not retryable heading evidence");
        var body=ScopedRetreatPlanning.validateAll(START,AWAY,world(fresh,now,FLOOR,List.of(new CombatSpatial.Box(7,.33,64,-.5,.6,66,-.4))),now::get,fence(now,0,tick,2,fresh));
        yes(!body.clear(),"off-center envelope collision remains checked");
    }
    private static void unknownAndClock() {
        scenarios++;AtomicLong now=new AtomicLong();
        for(String reason:List.of("unknown_cell","unloaded","collision_unknown","cell_read_failed","threat_snapshot_stale","retreat_window_exception","unrecognised")) {
            var result=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->new CombatDetour.EdgeResult(false,0,reason),now::get,()->{});
            yes(result.hardFailure() && !result.clear(),reason+" is not retried");
        }
        var nullResult=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->null,now::get,()->{});yes(nullResult.hardFailure(),"null callback hard");
        var thrown=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->{throw new IllegalStateException();},now::get,()->{});yes(thrown.hardFailure(),"callback exception hard");
        AtomicInteger count=new AtomicInteger();LongSupplier backward=()->count.getAndIncrement()==0?10:9;
        var badClock=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->CLEAR,backward,()->{});
        eq(badClock.reason(),"retreat_validation_clock_invalid","backward clock terminal");
        var clockThrows=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->CLEAR,()->{throw new IllegalStateException();},()->{});
        yes(clockThrows.hardFailure(),"missing clock cannot admit");
        var changedOwner=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->CLEAR,now::get,()->{throw new IllegalStateException("owner");});
        yes(changedOwner.hardFailure() && changedOwner.windows()==0,"owner fails before callback");
    }
    private static void geometryAndProgress() {
        scenarios++;AtomicLong now=new AtomicLong();var snapshot=snapshot(0,0,5);
        for(var goal:List.of(new CombatDetour.Point(3,0),new CombatDetour.Point(3,.01))) {
            var result=ScopedRetreatPlanning.validateAll(START,goal,world(snapshot,now,FLOOR,List.of()),now::get,()->{});
            yes(!result.clear(),"unchanged toward/tangent clearance refuses");
        }
        List<Double> segments=new ArrayList<>();
        var full=ScopedRetreatPlanning.validateAll(START,AWAY,(a,b)->{segments.add(a.distance(b));return CLEAR;},now::get,()->{});
        yes(full.clear() && full.windows()==5,"five complete windows");
        for(int i=0;i<4;i++)yes(Math.abs(segments.get(i)-.65)<1e-12,"unchanged .65 window");
        yes(Math.abs(segments.get(4)-.4)<1e-12,"unchanged final .4 tail");
        yes(!ScopedRetreatPlanning.validateAll(START,new CombatDetour.Point(0,-4.1),(a,b)->CLEAR,now::get,()->{}).clear(),"four-meter path cap retained");
        var progress=new CombatRetreatPolicy.Progress();progress.start(snapshot,START,AWAY,0,0);
        eq(progress.observe(snapshot,START,10,500_000_000L),"retreat_observed_progress_insufficient","progress not refunded by scheduler");
        yes(CombatRetreatPolicy.continuity(snapshot,snapshot(1,0,4.9),START,START)!=null,"approaching threat continuity still refuses");
    }
    public static void main(String[] args) {
        t44ColdClear();boundaries();cursorBounded();cannotResumeWindows();finalFreshRoute();unknownAndClock();geometryAndProgress();
        System.out.println("{\"status\":\"passed\",\"assertions\":"+assertions+",\"scenarios\":"+scenarios+",\"scope\":\"production pure helpers with synthetic time, cells and snapshots; no game, loader or network\"}");
    }
}
