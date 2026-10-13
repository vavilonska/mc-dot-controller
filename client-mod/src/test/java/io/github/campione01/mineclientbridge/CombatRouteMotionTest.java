package io.github.campione01.mineclientbridge;

import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CombatRouteMotionTest {
    static CombatRecovery.Motion motion(double vx,double vy,double vz) {
        return new CombatRecovery.Motion(0,64,0,vx,vy,vz,true);
    }
    @Test void firstWithdrawalRefusesGroundedKnockbackInsteadOfWaitingNearDanger() {
        var r=new CombatRouteMotion().sample(1,motion(.2,0,0),0,1,true);
        assertFalse(r.ready());assertTrue(r.failed());assertEquals("retreat_motion_not_settled",r.reason());
    }
    @Test void nonfiniteSpeedAndUnsupportedHeightFailClosed() {
        assertTrue(new CombatRouteMotion().sample(1,motion(Double.NaN,0,0),1,0,true).failed());
        assertTrue(new CombatRouteMotion().sample(1,new CombatRecovery.Motion(0,64.5,0,0,0,0,true),1,0,false).failed());
    }
    @Test void detourSettlesBeforeTurningButContinuesAlignedMotion() {
        var g=new CombatRouteMotion();
        assertTrue(g.sample(1,motion(0,0,0),1,0,false).ready());
        assertTrue(g.sample(2,motion(.2,0,0),1,0,false).ready());
        var turn=g.sample(3,motion(.2,0,0),0,1,false);
        assertFalse(turn.ready());assertFalse(turn.failed());
        assertTrue(g.sample(4,motion(.02,0,0),0,1,false).ready());
    }
    @Test void lateralOrExcessiveSpeedRefusesContinuation() {
        var g=new CombatRouteMotion();assertTrue(g.sample(1,motion(0,0,0),1,0,false).ready());
        assertFalse(g.sample(2,motion(.2,0,.1),1,0,false).ready());
        assertTrue(g.sample(3,motion(.6,0,0),1,0,true).failed());
    }
    @Test void tenUnsettledTicksCannotLoopForever() {
        var g=new CombatRouteMotion();
        for(int i=1;i<10;i++) assertFalse(g.sample(i,motion(.2,0,0),0,1,false).failed());
        var r=g.sample(10,motion(.2,0,0),0,1,false);
        assertTrue(r.failed());assertEquals(10,r.totalSettleTicks());
    }
    @Test void completedSettlingDoesNotRefundCumulativeWaits() {
        var g=new CombatRouteMotion();int tick=0;
        for(int episode=0;episode<4;episode++) {
            for(int i=0;i<9;i++) assertFalse(g.sample(++tick,motion(.2,0,.2),1,0,false).failed());
            assertTrue(g.sample(++tick,motion(0,0,0),1,0,false).ready());
        }
        CombatRouteMotion.Result r=null;
        for(int i=0;i<4;i++) r=g.sample(++tick,motion(.2,0,.2),1,0,false);
        assertTrue(r.failed());assertEquals(40,r.totalSettleTicks());
    }
    @Test void sameTickCannotMutateBudgetTwice() {
        var g=new CombatRouteMotion();g.sample(1,motion(.2,0,0),0,1,false);
        var duplicate=g.sample(1,motion(.2,0,0),0,1,false);
        assertTrue(duplicate.failed());assertEquals(1,duplicate.totalSettleTicks());
    }
    @Test void fourShiftEnvelopeRejectsSupportWithinResidualMargin() {
        var solid=CombatSafetyIntegrationTest.SOLID;var air=CombatSafetyIntegrationTest.AIR;
        FlatStepCorridor.CellSource cells=(x,y,z)->y==63 && z>=0 ? solid:air;
        var pose=new FlatStepCorridor.Pose(.5,64,.33,true,0);
        assertTrue(FlatStepCorridor.check(pose,.65,0,cells).clear());
        assertFalse(CombatRouteEnvelope.check(pose,.65,0,cells,List.of()).clear());
    }
    @Test void envelopeUsesContinuousDiagonalAndDynamicEntityChecks() {
        var source=(FlatStepCorridor.CellSource)(x,y,z)->y==63?CombatSafetyIntegrationTest.SOLID:CombatSafetyIntegrationTest.AIR;
        var pose=new FlatStepCorridor.Pose(.5,64,.5,true,0);
        assertTrue(CombatRouteEnvelope.check(pose,.45,.45,source,List.of()).clear());
        assertFalse(CombatRouteEnvelope.check(pose,.45,.45,source,List.of(new CombatSpatial.Box(3,.9,64,.9,1.5,65.8,1.5))).clear());
    }
}
