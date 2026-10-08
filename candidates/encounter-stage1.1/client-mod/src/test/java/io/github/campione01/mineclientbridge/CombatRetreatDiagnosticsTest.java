package io.github.campione01.mineclientbridge;

import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.LongSupplier;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CombatRetreatDiagnosticsTest {
    private static final long LIMIT=8_000_000L;
    private static final CombatDetour.Point START=new CombatDetour.Point(0,0),GOAL=new CombatDetour.Point(0,-3);
    private static final CombatThreats.Snapshot THREATS=new CombatThreats.Snapshot(List.of(
            new CombatThreats.Observed(1,"one","minecraft:zombie",0,64,5,.3,true,true)),0,0,false,true);
    private static final CombatDetour.EdgeResult CLEAR=new CombatDetour.EdgeResult(true,1,"clear");
    private static final FlatStepCorridor.Cell SOLID=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:stone",true,false,true,"minecraft:empty",false);
    private static final FlatStepCorridor.Cell AIR=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:air",true,true,false,"minecraft:empty",false);
    private static final FlatStepCorridor.CellSource FLOOR=(x,y,z)->y==63?SOLID:AIR;
    private static LongSupplier sequence(long... values) {
        AtomicInteger index=new AtomicInteger();return ()->values[Math.min(index.getAndIncrement(),values.length-1)];
    }
    @Test void failedWindowThenBudgetKeepsOriginalCellAndReason() {
        AtomicLong clock=new AtomicLong();
        var cell=new FlatStepCorridor.CellRef(14,64,20,"feet","minecraft:grass_block");
        var plan=CombatRetreatPolicy.plan(THREATS,START,(a,b)-> {
            clock.set(LIMIT);return new CombatDetour.EdgeResult(false,0,"feet_collision");
        },clock::get,()->cell);
        assertNull(plan.goal());assertTrue(plan.budgetExhausted());assertEquals("retreat_check_budget",plan.reason());
        assertEquals(1,plan.candidateChecks());assertEquals(1,plan.windowChecks());
        var diagnostic=plan.diagnostics();var window=diagnostic.lastWindow();
        assertEquals("post_window",diagnostic.budgetCheckStage());assertFalse(window.clear());
        assertEquals("feet_collision",window.reason());assertEquals(cell,window.rejectedCell());
        assertEquals(LIMIT,window.elapsedNanos());assertEquals(0,diagnostic.preFirstWindowElapsedNanos());
        assertEquals(LIMIT,diagnostic.lastWindowElapsedNanos());assertEquals(LIMIT,diagnostic.elapsedNanos());
        assertEquals(1,plan.rejections().get("retreat_check_budget"));
    }
    @Test void successfulWindowThenBudgetStaysRejectedWithClearOriginalResult() {
        AtomicLong clock=new AtomicLong();
        var result=CombatRetreatPolicy.validate(START,GOAL,(a,b)->{clock.set(LIMIT);return CLEAR;},clock::get);
        assertFalse(result.clear());assertTrue(result.budgetExhausted());
        assertTrue(result.diagnostics().lastWindow().clear());assertNull(result.diagnostics().lastWindow().rejectedCell());
        assertEquals("clear",result.diagnostics().lastWindow().reason());assertEquals("post_window",result.diagnostics().budgetCheckStage());
    }
    @Test void preCandidateExpiryDoesNotInventCandidateOrWindow() {
        AtomicInteger callbacks=new AtomicInteger();
        var plan=CombatRetreatPolicy.plan(THREATS,START,(a,b)->{callbacks.incrementAndGet();return CLEAR;},sequence(0,LIMIT));
        assertNull(plan.goal());assertEquals(0,callbacks.get());assertEquals(0,plan.candidateChecks());assertEquals(0,plan.windowChecks());
        assertEquals("pre_candidate",plan.diagnostics().budgetCheckStage());assertEquals(-1,plan.diagnostics().preFirstWindowElapsedNanos());
        assertTrue(plan.diagnostics().candidates().isEmpty());assertTrue(plan.diagnostics().windows().isEmpty());
    }
    @Test void preWindowExpiryKeepsZeroWindowCandidateAndExactBoundary() {
        AtomicInteger callbacks=new AtomicInteger();
        var plan=CombatRetreatPolicy.plan(THREATS,START,(a,b)->{callbacks.incrementAndGet();return CLEAR;},sequence(0,0,0,LIMIT));
        assertNull(plan.goal());assertTrue(plan.budgetExhausted());assertEquals(0,callbacks.get());
        assertEquals(1,plan.candidateChecks());assertEquals(0,plan.windowChecks());assertEquals(1,plan.diagnostics().candidates().size());
        assertEquals(0,plan.diagnostics().candidates().getFirst().windows());assertNull(plan.diagnostics().lastWindow());
        assertEquals("pre_window",plan.diagnostics().budgetCheckStage());
    }
    @Test void candidateGeometryAndObserverEntryRemainInsideBudget() {
        var plan=CombatRetreatPolicy.plan(THREATS,START,(a,b)->fail("callback after expiry"),sequence(0,0,0,0,LIMIT));
        assertNull(plan.goal());assertEquals(0,plan.windowChecks());assertEquals("pre_window_callback",plan.diagnostics().budgetCheckStage());
        assertEquals(-1,plan.diagnostics().preFirstWindowElapsedNanos());
    }
    @Test void observerFailurePreservesReturnedWindowWhileFailingClosed() {
        var result=CombatRetreatPolicy.validate(START,GOAL,(a,b)->new CombatDetour.EdgeResult(false,0,"feet_collision"),()->0,
                ()->{throw new IllegalStateException("observer");});
        assertFalse(result.clear());assertEquals("retreat_observation_failed",result.reason());
        assertEquals("feet_collision",result.diagnostics().lastWindow().reason());
        assertFalse(result.diagnostics().lastWindow().clear());
        var safe=CombatRetreatPolicy.validate(START,GOAL,(a,b)->CLEAR,()->0,()->{throw new IllegalStateException();});
        assertFalse(safe.clear());assertTrue(safe.diagnostics().lastWindow().clear());
    }
    @Test void observerTimeCannotRescueFailedOrSuccessfulWindow() {
        AtomicLong clock=new AtomicLong();
        var result=CombatRetreatPolicy.validate(START,GOAL,(a,b)->CLEAR,clock::get,()->{clock.set(LIMIT);return null;});
        assertFalse(result.clear());assertTrue(result.budgetExhausted());assertTrue(result.diagnostics().lastWindow().clear());
    }
    @Test void finalAggregationExpiryDiscardsFullyClearPlan() {
        AtomicInteger windows=new AtomicInteger(),afterLast=new AtomicInteger();
        LongSupplier clock=()->windows.get()<5?0:afterLast.incrementAndGet()<3?LIMIT-1:LIMIT;
        var result=CombatRetreatPolicy.plan(THREATS,START,(a,b)->{windows.incrementAndGet();return CLEAR;},clock);
        assertNull(result.goal());assertTrue(result.budgetExhausted());assertEquals(5,result.windowChecks());
        assertEquals("plan_complete",result.diagnostics().budgetCheckStage());assertTrue(result.diagnostics().lastWindow().clear());
    }
    @Test void allCountsAndDurationsSumWithinBoundedPlan() {
        AtomicLong clock=new AtomicLong();AtomicInteger callback=new AtomicInteger();
        var plan=CombatRetreatPolicy.plan(THREATS,START,(a,b)-> {
            clock.addAndGet(100);int call=callback.incrementAndGet();
            return call<4?new CombatDetour.EdgeResult(false,0,"blocked"):CLEAR;
        },clock::get);
        assertNotNull(plan.goal());assertEquals(4,plan.candidateChecks());assertEquals(8,plan.windowChecks());
        var d=plan.diagnostics();assertEquals(4,d.candidates().size());assertEquals(8,d.windows().size());
        assertEquals(plan.windowChecks(),d.candidates().stream().mapToInt(CombatRetreatDiagnostics.Candidate::windows).sum());
        assertEquals(d.totalWindowElapsedNanos(),d.windows().stream().mapToLong(CombatRetreatDiagnostics.Window::elapsedNanos).sum());
        assertEquals(800,d.totalWindowElapsedNanos());assertEquals(100,d.lastWindowElapsedNanos());
        assertEquals(800,d.elapsedNanos());assertEquals("none",d.budgetCheckStage());
        var blocked=CombatRetreatPolicy.plan(THREATS,START,(a,b)->new CombatDetour.EdgeResult(false,0,"blocked"),()->0);
        assertEquals(16,blocked.diagnostics().candidates().size());assertEquals(16,blocked.diagnostics().windows().size());
    }
    @Test void backwardClockEvenAboveStartCannotAdmitAndClockExceptionsFailClosed() {
        var plan=CombatRetreatPolicy.plan(THREATS,START,(a,b)->CLEAR,sequence(0,100,90));
        assertNull(plan.goal());assertTrue(plan.budgetExhausted());assertTrue(plan.diagnostics().clockInvalid());
        var broken=CombatRetreatPolicy.plan(THREATS,START,(a,b)->CLEAR,()->{throw new IllegalStateException();});
        assertNull(broken.goal());assertTrue(broken.budgetExhausted());assertTrue(broken.diagnostics().clockInvalid());
    }
    @Test void nullResultCallbackExceptionsInvalidRequestAndMissingClockFailClosed() {
        var unknown=CombatRetreatPolicy.validate(START,GOAL,(a,b)->null,()->0);
        assertFalse(unknown.clear());assertEquals("retreat_window_unknown",unknown.reason());assertTrue(unknown.diagnostics().lastWindow().returned());assertFalse(unknown.diagnostics().lastWindow().resultPresent());
        var exception=CombatRetreatPolicy.validate(START,GOAL,(a,b)->{throw new IllegalStateException();},()->0);
        assertFalse(exception.clear());assertEquals("retreat_window_exception",exception.reason());
        assertFalse(exception.diagnostics().lastWindow().returned());
        assertFalse(CombatRetreatPolicy.validate(START,GOAL,null,()->0).clear());
        assertFalse(CombatRetreatPolicy.validate(START,GOAL,(a,b)->CLEAR,null).clear());
        assertFalse(CombatRetreatPolicy.validate(START,START,(a,b)->CLEAR,()->0).clear());
    }
    private static CombatRetreatWindow.Result window(FlatStepCorridor.CellSource cells,List<CombatSpatial.Box> boxes,CombatRetreatWindow.Metrics metrics) {
        return CombatRetreatWindow.check(THREATS,0,0,new FlatStepCorridor.Pose(0,64,0,true,0),
                new CombatDetour.Point(0,-.65),0,64,0,cells,boxes,metrics);
    }
    @Test void fullWindowStageCountsPreserveAllChecksAndNestedScope() {
        AtomicLong clock=new AtomicLong();var metrics=new CombatRetreatWindow.Metrics(clock::getAndIncrement);
        assertTrue(window(FLOOR,List.of(),metrics).edge().clear());
        assertEquals(2,metrics.calls(CombatRetreatWindow.Stage.THREAT_ROUTES));
        assertEquals(5,metrics.calls(CombatRetreatWindow.Stage.DYNAMIC_OBSTACLES));
        assertEquals(1,metrics.calls(CombatRetreatWindow.Stage.CENTER_TERRAIN));
        assertEquals(1,metrics.calls(CombatRetreatWindow.Stage.ENVELOPE));
        assertEquals(4,metrics.calls(CombatRetreatWindow.Stage.ENVELOPE_TERRAIN));
        assertEquals(2,metrics.nanos(CombatRetreatWindow.Stage.THREAT_ROUTES));
        assertEquals(17,metrics.nanos(CombatRetreatWindow.Stage.ENVELOPE));assertFalse(metrics.clockInvalid);
    }
    @Test void terrainAndDynamicEarlyExitsDoNotInventLaterWork() {
        var terrain=new CombatRetreatWindow.Metrics(()->0);
        var result=window((x,y,z)->SOLID,List.of(),terrain);
        assertFalse(result.edge().clear());assertEquals("feet_collision",result.edge().reason());assertNotNull(result.terrain().cell());
        assertEquals(1,terrain.calls(CombatRetreatWindow.Stage.CENTER_TERRAIN));assertEquals(0,terrain.calls(CombatRetreatWindow.Stage.ENVELOPE));
        var dynamic=new CombatRetreatWindow.Metrics(()->0);
        assertFalse(window(FLOOR,List.of(new CombatSpatial.Box(5,-.1,64,-.6,.1,66,-.5)),dynamic).edge().clear());
        assertEquals(1,dynamic.calls(CombatRetreatWindow.Stage.DYNAMIC_OBSTACLES));assertEquals(0,dynamic.calls(CombatRetreatWindow.Stage.CENTER_TERRAIN));
        var failure=new CombatRetreatWindow.Metrics(()->0);
        var bad=window((x,y,z)->{throw new IllegalStateException();},List.of(),failure);
        assertEquals("cell_read_failed",bad.edge().reason());assertNotNull(bad.terrain().cell());
        assertEquals(0,failure.calls(CombatRetreatWindow.Stage.ENVELOPE));
    }
    @Test void stageClockRegressionCannotMakeWindowClear() {
        var metrics=new CombatRetreatWindow.Metrics(sequence(10,9,9));
        assertFalse(window(FLOOR,List.of(),metrics).edge().clear());assertTrue(metrics.clockInvalid);
    }
    @Test void finalSerializationBoundaryCanOnlyRevokeAdmission() {
        AtomicLong clock=new AtomicLong();
        var plan=CombatRetreatPolicy.plan(THREATS,START,(a,b)->CLEAR,clock::get);
        assertNotNull(plan.goal());clock.set(LIMIT);
        assertTrue(plan.diagnostics().checkBudget("post_diagnostics"));
        assertEquals("post_diagnostics",plan.diagnostics().budgetCheckStage());
        clock.set(0);assertTrue(plan.diagnostics().checkBudget("motion_decision_return"));
    }
}
