package io.github.campione01.mineclientbridge;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Pure offline production-helper tests. No running Minecraft, server, damage, or fuse simulation. */
class CombatRetreatPolicyTest {
    static final CombatDetour.Point START=new CombatDetour.Point(0,0),AWAY=new CombatDetour.Point(0,-3);
    static final FlatStepCorridor.Cell SOLID=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:stone",true,false,true,"minecraft:empty",false);
    static final FlatStepCorridor.Cell AIR=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:air",true,true,false,"minecraft:empty",false);
    static final FlatStepCorridor.Cell UNKNOWN=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNKNOWN,null,false,false,false,null,false);
    static final FlatStepCorridor.CellSource FLOOR=(x,y,z)->y==63?SOLID:AIR;
    static CombatThreats.Observed mob(int id,String type,double x,double z) {
        return new CombatThreats.Observed(id,"uuid-"+id,type,x,64,z,.3,true,true);
    }
    static CombatThreats.Snapshot snapshot(int tick,CombatThreats.Observed... mobs) {
        return new CombatThreats.Snapshot(List.of(mobs),tick*50_000_000L,tick,false,true);
    }
    static CombatDetour.EdgeCheck windows(CombatThreats.Snapshot s,FlatStepCorridor.CellSource cells,List<CombatSpatial.Box> boxes) {
        return (a,b)->CombatRetreatWindow.check(s,s.capturedNanos(),s.capturedTick(),
                new FlatStepCorridor.Pose(a.x(),64,a.z(),true,0),b,0,64,0,cells,boxes).edge();
    }
    static CombatDetour.EdgeCheck geometry(CombatThreats.Snapshot s) {
        return (a,b)-> {
            var r=CombatThreats.escapeRoute(s,s.capturedNanos(),s.capturedTick(),a.x(),a.z(),b.x(),b.z());
            return new CombatDetour.EdgeResult(r.safe(),r.minimumClearance(),r.reason());
        };
    }
    @Test void exactTickNineFormerLongSegmentsPassButUnifiedFirstWindowRefuses() {
        var from=new CombatDetour.Point(14.50080425262464,21.793858576194303);
        var middle=new CombatDetour.Point(from.x()-1.5,from.z());
        var end=new CombatDetour.Point(from.x()-3,from.z());
        var s=snapshot(9,mob(1,"minecraft:zombie",14.575927734375,27.0615234375));
        assertTrue(geometry(s).check(from,middle).clear());assertTrue(geometry(s).check(middle,end).clear());
        var first=CombatRetreatPolicy.next(from,end);
        double gain=Math.hypot(first.x()-s.entities().getFirst().x(),first.z()-s.entities().getFirst().z())
                -Math.hypot(from.x()-s.entities().getFirst().x(),from.z()-s.entities().getFirst().z());
        assertEquals(.049138781384,gain,1e-11);
        var planned=CombatRetreatPolicy.validate(from,end,geometry(s),()->0);
        assertFalse(planned.clear());assertTrue(planned.firstWindowRejected());assertEquals(1,planned.windows());
        assertEquals("escape_no_clearance_progress",planned.reason());assertFalse(geometry(s).check(from,first).clear());
    }
    @Test void exactTickTenStillFailsUnchangedPointOneRequirement() {
        var from=new CombatDetour.Point(14.50080425262464,21.817242852192017);
        var goal=new CombatDetour.Point(11.50080425262464,21.793858576194303);
        var s=snapshot(10,mob(1,"minecraft:zombie",14.56396484375,26.950032552083332));
        var next=CombatRetreatPolicy.next(from,goal);
        double gain=Math.hypot(next.x()-s.entities().getFirst().x(),next.z()-s.entities().getFirst().z())
                -Math.hypot(from.x()-s.entities().getFirst().x(),from.z()-s.entities().getFirst().z());
        assertEquals(.053934159633,gain,1e-11);
        assertFalse(CombatRetreatPolicy.validate(from,goal,geometry(s),()->0).clear());
    }
    @Test void clearFloorAwayPlanAndEveryExecutionOffsetUseSameProductionWindows() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));
        var check=windows(s,FLOOR,List.of());
        var plan=CombatRetreatPolicy.plan(s,START,check,()->0);
        assertNotNull(plan.goal());assertEquals(0,plan.goal().x(),1e-12);assertEquals(-3,plan.goal().z(),1e-12);
        assertEquals(1,plan.candidateChecks());assertEquals(5,plan.windowChecks());
        for(double z=0;z>-2.75;z-=.03125) {
            var current=new CombatDetour.Point(0,z);
            assertTrue(CombatRetreatPolicy.validate(current,plan.goal(),check,()->0).clear(),"z="+z);
            assertTrue(check.check(current,CombatRetreatPolicy.next(current,plan.goal())).clear());
        }
    }
    @Test void completeWindowsArePointSixFiveWithIdenticalShortTerminalWindow() {
        var segments=new ArrayList<Double>();
        var result=CombatRetreatPolicy.validate(START,AWAY,(a,b)->{
            segments.add(a.distance(b));return new CombatDetour.EdgeResult(true,1,"clear");
        },()->0);
        assertTrue(result.clear());assertEquals(5,segments.size());
        for(int i=0;i<4;i++) assertEquals(.65,segments.get(i),1e-12);
        assertEquals(.4,segments.get(4),1e-12);
        assertEquals(.26,START.distance(CombatRetreatPolicy.next(START,new CombatDetour.Point(0,-.26))),1e-12);
        assertNull(CombatRetreatPolicy.next(START,new CombatDetour.Point(0,-.25)));
    }
    @Test void plannerDoesNotRequireUnissuedTailInsideArrivalTolerance() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));
        var result=CombatRetreatPolicy.validate(START,new CombatDetour.Point(0,-.7),windows(s,FLOOR,List.of()),()->0);
        assertTrue(result.clear());assertEquals(1,result.windows());
    }
    @Test void shortIssuedTailKeepsFullImprovementRequirement() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));
        assertFalse(CombatRetreatPolicy.validate(START,new CombatDetour.Point(.27,0),windows(s,FLOOR,List.of()),()->0).clear());
        assertTrue(CombatRetreatPolicy.validate(START,new CombatDetour.Point(0,-.27),windows(s,FLOOR,List.of()),()->0).clear());
    }
    @Test void safeLateralRouteNeedsEveryWindowAndCanBeUsedOnlyWhenPreferredHeadingsBlocked() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,1));
        var base=windows(s,FLOOR,List.of());
        var plan=CombatRetreatPolicy.plan(s,START,(a,b)->Math.abs(b.z())>.001
                ?new CombatDetour.EdgeResult(false,0,"test_heading_blocked"):base.check(a,b),()->0);
        assertNotNull(plan.goal());assertTrue(plan.candidateChecks()>1);
        assertEquals(0,plan.goal().z(),1e-12);
        assertTrue(CombatRetreatPolicy.validate(START,plan.goal(),base,()->0).clear());
    }
    @Test void nearCreeperAdmissionNeverChangesThreatGateOrSafetyClaim() {
        var s=snapshot(1,mob(1,"minecraft:creeper",0,1));
        assertTrue(CombatRetreatPolicy.validate(START,AWAY,windows(s,FLOOR,List.of()),()->0).clear());
        var gate=CombatThreats.evaluate(s,s.capturedNanos(),1,0,64,0,-1,"",new CombatThreats.HealthGuard().sample(1,s.capturedNanos(),20));
        assertTrue(gate.stop());assertTrue(gate.riskRemaining());assertEquals("critical_creeper_near",gate.reason());
        assertFalse(CombatRetreatPolicy.validate(START,new CombatDetour.Point(.27,0),windows(s,FLOOR,List.of()),()->0).clear());
    }
    @Test void tangentAndSlightTowardPathsRefuseBeforeInput() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));
        for(var goal:List.of(new CombatDetour.Point(3,0),new CombatDetour.Point(3,.01)))
            assertFalse(CombatRetreatPolicy.validate(START,goal,windows(s,FLOOR,List.of()),()->0).clear());
    }
    @Test void multipleOpposingThreatsCannotBeEscapedByApproachingEitherOne() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5),mob(2,"minecraft:creeper",0,-5));
        assertNull(CombatRetreatPolicy.plan(s,START,windows(s,FLOOR,List.of()),()->0).goal());
    }
    @Test void newDynamicBodyAndNewUnknownTerrainInvalidateLiveRoute() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));
        assertTrue(CombatRetreatPolicy.validate(START,AWAY,windows(s,FLOOR,List.of()),()->0).clear());
        assertFalse(CombatRetreatPolicy.validate(START,AWAY,windows(s,FLOOR,
                List.of(new CombatSpatial.Box(7,-.2,64,-.8,.2,66,-.4))),()->0).clear());
        assertFalse(CombatRetreatPolicy.validate(START,AWAY,windows(s,(x,y,z)->z<0?UNKNOWN:FLOOR.read(x,y,z),List.of()),()->0).clear());
        assertFalse(CombatRetreatPolicy.validate(START,AWAY,windows(s,(x,y,z)->z==-2&&y==64?SOLID:FLOOR.read(x,y,z),List.of()),()->0).clear());
    }
    @Test void motionEnvelopeChecksOffCenterCollisionToo() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));
        var obstacle=new CombatSpatial.Box(7,.33,64,-.5,.6,66,-.4);
        assertTrue(CombatSpatial.check(0,64,0,0,-.65,List.of(obstacle)).clear());
        assertFalse(windows(s,FLOOR,List.of(obstacle)).check(START,new CombatDetour.Point(0,-.65)).clear());
    }
    @Test void unknownStaleTruncatedEndermanAndMalformedThreatsFailClosed() {
        var good=snapshot(1,mob(1,"minecraft:zombie",0,5));
        for(var s:List.of(new CombatThreats.Snapshot(good.entities(),0,1,false,true),
                new CombatThreats.Snapshot(good.entities(),0,1,true,true),
                new CombatThreats.Snapshot(good.entities(),0,1,false,false),
                snapshot(1,mob(1,"minecraft:enderman",0,5)))) {
            var r=CombatRetreatWindow.check(s,200_000_001L,1,new FlatStepCorridor.Pose(0,64,0,true,0),
                    new CombatDetour.Point(0,-.65),0,64,0,FLOOR,List.of());
            assertFalse(r.edge().clear());
        }
        assertNull(CombatRetreatPolicy.plan(null,START,windows(good,FLOOR,List.of()),()->0).goal());
        assertNull(CombatRetreatPolicy.plan(snapshot(1),START,windows(good,FLOOR,List.of()),()->0).goal());
    }
    @Test void invalidPoseAreaAndOversizedWindowRefuse() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));
        for(double length:new double[]{0,.6501,Double.NaN,Double.POSITIVE_INFINITY})
            assertFalse(windows(s,FLOOR,List.of()).check(START,new CombatDetour.Point(0,-length)).clear());
        assertFalse(CombatRetreatWindow.check(s,s.capturedNanos(),1,new FlatStepCorridor.Pose(0,64,0,false,0),
                new CombatDetour.Point(0,-.65),0,64,0,FLOOR,List.of()).edge().clear());
        assertFalse(CombatRetreatWindow.check(s,s.capturedNanos(),1,new FlatStepCorridor.Pose(0,64,0,true,0),
                new CombatDetour.Point(0,-.65),30,64,0,FLOOR,List.of()).edge().clear());
        assertNull(CombatRetreatPolicy.next(START,new CombatDetour.Point(0,-4.1)));
    }
    @Test void deadlineDuringWindowDiscardsOtherwiseSafeCandidate() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));var clock=new AtomicLong();
        var r=CombatRetreatPolicy.plan(s,START,(a,b)->{
            clock.set(CombatRetreatPolicy.MAX_CHECK_NANOS);return new CombatDetour.EdgeResult(true,1,"clear");
        },clock::get);
        assertNull(r.goal());assertTrue(r.budgetExhausted());assertEquals(1,r.windowChecks());
    }
    @Test void allBlockedDirectionsBoundAttemptsAndRecordFirstWindowReasons() {
        var s=snapshot(1,mob(1,"minecraft:zombie",0,5));
        var r=CombatRetreatPolicy.plan(s,START,(a,b)->new CombatDetour.EdgeResult(false,0,"blocked"),()->0);
        assertNull(r.goal());assertFalse(r.budgetExhausted());assertEquals(16,r.candidateChecks());
        assertEquals(16,r.windowChecks());assertEquals(16,r.firstWindowRejections());assertEquals(16,r.rejections().get("blocked"));
    }
    @Test void identityAppearanceDisappearanceDeathTypeAndReuseAllRefuse() {
        var old=snapshot(1,mob(1,"minecraft:zombie",0,5));
        for(var live:List.of(snapshot(2),snapshot(2,mob(1,"minecraft:zombie",0,5),mob(2,"minecraft:creeper",2,5)),
                snapshot(2,new CombatThreats.Observed(1,"reused","minecraft:zombie",0,64,5,.3,true,true)),
                snapshot(2,mob(1,"minecraft:skeleton",0,5)),
                snapshot(2,new CombatThreats.Observed(1,"uuid-1","minecraft:zombie",0,64,5,.3,true,false))))
            assertEquals("retreat_threat_identity_changed",CombatRetreatPolicy.continuity(old,live,START,START));
    }
    @Test void approachingThreatOrActualPlayerBackslideRefusesEvenWithValidFutureRoute() {
        var old=snapshot(1,mob(1,"minecraft:zombie",0,5));
        var live=snapshot(2,mob(1,"minecraft:zombie",0,4.9));
        assertTrue(CombatRetreatPolicy.validate(START,AWAY,windows(live,FLOOR,List.of()),()->0).clear());
        assertEquals("retreat_observed_clearance_decreased",CombatRetreatPolicy.continuity(old,live,START,START));
        assertEquals("retreat_observed_clearance_decreased",CombatRetreatPolicy.continuity(old,old,START,new CombatDetour.Point(0,.01)));
        assertNull(CombatRetreatPolicy.continuity(old,live,START,new CombatDetour.Point(0,-.2)));
    }
    @Test void nearestSwitchStillChecksAllThreatsAndReevaluatesNextWindow() {
        var old=snapshot(1,mob(1,"minecraft:zombie",0,5),mob(2,"minecraft:skeleton",1,5));
        var live=snapshot(2,mob(1,"minecraft:zombie",0,6),mob(2,"minecraft:skeleton",1,5));
        assertNull(CombatRetreatPolicy.continuity(old,live,START,START));
        assertTrue(CombatRetreatPolicy.validate(START,AWAY,windows(live,FLOOR,List.of()),()->0).clear());
    }
    @Test void unchangedPoseExpiresAtExactTickProgressBoundaryAndLatches() {
        var s=snapshot(0,mob(1,"minecraft:zombie",0,5));var p=new CombatRetreatPolicy.Progress();p.start(s,START,AWAY,0,0);
        for(int i=1;i<10;i++) assertNull(p.observe(s,START,i,i*40_000_000L));
        assertEquals("retreat_observed_progress_insufficient",p.observe(s,START,10,400_000_000L));
        assertEquals("retreat_observed_progress_insufficient",p.observe(s,new CombatDetour.Point(0,-1),11,440_000_000L));
    }
    @Test void unchangedPoseExpiresAtExactWallTimeBoundaryToo() {
        var s=snapshot(0,mob(1,"minecraft:zombie",0,5));var p=new CombatRetreatPolicy.Progress();p.start(s,START,AWAY,0,0);
        assertNull(p.observe(s,START,1,499_999_999L));
        assertEquals("retreat_observed_progress_insufficient",p.observe(s,START,2,500_000_000L));
    }
    @Test void movingEnemyAloneCannotSatisfyOwnProgressAndPointOneIsAccepted() {
        var old=snapshot(0,mob(1,"minecraft:zombie",0,5));var p=new CombatRetreatPolicy.Progress();p.start(old,START,AWAY,0,0);
        assertEquals("retreat_observed_progress_insufficient",p.observe(snapshot(10,mob(1,"minecraft:zombie",0,6)),START,10,500_000_000L));
        p=new CombatRetreatPolicy.Progress();p.start(old,START,AWAY,0,0);
        assertNull(p.observe(old,new CombatDetour.Point(0,-.1),10,500_000_000L));
        assertEquals(.1,p.observedAdvance(),1e-12);assertEquals(.1,p.observedClearanceGain(),1e-12);
        assertNull(p.observe(old,new CombatDetour.Point(0,-.2),20,1_000_000_000L));
    }
    @Test void lateralPlayerAdvanceWithoutEnoughActualClearanceFailsBoundedProgress() {
        var s=snapshot(0,mob(1,"minecraft:zombie",0,1));var p=new CombatRetreatPolicy.Progress();
        p.start(s,START,new CombatDetour.Point(3,0),0,0);
        assertEquals("retreat_observed_progress_insufficient",p.observe(s,new CombatDetour.Point(.1,0),10,500_000_000L));
    }
    @Test void progressClockAndObservationProblemsRefuse() {
        var s=snapshot(0,mob(1,"minecraft:zombie",0,5));
        var p=new CombatRetreatPolicy.Progress();p.start(s,START,AWAY,1,100);
        assertEquals("retreat_progress_clock_invalid",p.observe(s,START,1,101));
        p=new CombatRetreatPolicy.Progress();p.start(s,START,AWAY,1,100);
        assertEquals("retreat_progress_clock_invalid",p.observe(s,START,2,99));
        assertEquals("retreat_observation_unknown",CombatRetreatPolicy.continuity(s,null,START,START));
    }
    @Test void shortGoalKeepsFullLookaheadForAlreadyAdmittedVelocity() {
        var s=snapshot(0,mob(1,"minecraft:zombie",-3,0));
        var box=new CombatSpatial.Box(7,.615,64,-.1,.62,66,.1);
        var motion=new CombatRouteMotion();
        assertTrue(motion.sample(0,new CombatRecovery.Motion(0,64,0,0,0,0,true),1,0,true).ready());
        assertTrue(motion.sample(1,new CombatRecovery.Motion(0,64,0,.35,0,0,true),.26,0,true).ready());
        assertFalse(CombatSpatial.check(0,64,0,.35,0,List.of(box)).clear());
        assertFalse(windows(s,FLOOR,List.of(box)).check(START,new CombatDetour.Point(.26,0)).clear());
        assertFalse(CombatRetreatPolicy.validate(START,new CombatDetour.Point(.26,0),windows(s,FLOOR,List.of(box)),()->0).clear());
    }
    @Test void nearestSwitchCannotBorrowPointOneGainFromAnOldNearestEnemy() {
        var initial=snapshot(0,mob(1,"minecraft:zombie",-1,0),mob(2,"minecraft:zombie",-1.01,0));
        var progress=new CombatRetreatPolicy.Progress();var goal=new CombatDetour.Point(3,0);
        progress.start(initial,START,goal,0,0);
        for(int tick=1;tick<=10;tick++) {
            var live=snapshot(tick,mob(1,"minecraft:zombie",-1,0),mob(2,"minecraft:zombie",-1.01+.0095*tick,0));
            var pose=new CombatDetour.Point(.01*tick,0);
            assertTrue(CombatRetreatPolicy.validate(pose,goal,windows(live,FLOOR,List.of()),()->0).clear());
            String result=progress.observe(live,pose,tick,tick*50_000_000L);
            if(tick<10) assertNull(result);else assertEquals("retreat_observed_progress_insufficient",result);
        }
        assertEquals(.1,progress.observedAdvance(),1e-12);
        assertEquals(.015,progress.observedClearanceGain(),1e-12);
    }
    @Test void adapterUsesSharedHelperOnBothSidesWithReleaseAndRiskContracts() throws Exception {
        var dir=Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge");
        String adapter=Files.readString(dir.resolve("BoundedCombat.java"));
        String safety=adapter.substring(adapter.indexOf("private Step safetyRetreat("),adapter.indexOf("private void observeDecisionMotion("));
        assertEquals(2,safety.split("\\(from,to\\)->retreatWindow\\(mc,from,to\\)",-1).length-1);
        assertTrue(safety.contains("CombatRetreatPolicy.plan(threats,current"));
        assertTrue(safety.contains("CombatRetreatPolicy.validate(current,retreatGoal"));
        assertTrue(safety.contains("CombatRetreatWindow.check(threats,System.nanoTime(),currentTick"));
        assertFalse(safety.contains("plannedRouteEdge(mc,current,mid,true)"));
        assertTrue(safety.indexOf("retreatProgress.observe")<safety.indexOf("faceMovement(mc,dx,dz)"));
        assertTrue(safety.contains("tick-retreatStartTick>=60"));assertTrue(safety.contains("retreatDistance>=4"));
        assertTrue(safety.contains("3_000_000_000L"));assertTrue(safety.contains("risk_remaining"));
        assertTrue(adapter.contains("evidence.addProperty(\"safety_assured\",false)"));
        assertTrue(adapter.contains("static Step end(String status, String reason) { return new Step(0, status, reason); }"));
        String actions=Files.readString(dir.resolve("ClientActions.java"));
        assertTrue(actions.indexOf("a.forward = 0;")<actions.indexOf("a.combat.tick(mc, a.entry.ticks)"));
        assertTrue(actions.contains("a.combat.release(Minecraft.getInstance())"));
    }
}
