package io.github.campione01.mineclientbridge;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Executable policy tests, not Minecraft physics or combat-win simulations. */
class CombatPursuitTest {
    private static CombatPursuit.Sample sample(double player, double target) {
        return new CombatPursuit.Sample(0, player, 0, target);
    }
    private static CombatPursuit.Result at(CombatPursuit p, int second, double player, double target) {
        return p.sample(second*20, second*1_000_000_000L, sample(player,target), true);
    }

    @Test void boundedCadenceStartsDefendedThenLowersForTwelveAdvancingTicks() {
        var p = new CombatPursuit();
        for (int tick=0; tick<60; tick++) {
            var r = p.sample(tick,tick*50_000_000L,sample(tick*.02,6),true);
            assertFalse(r.failed());
            assertEquals(tick%20 < 8, r.defend());
            assertEquals(tick%20, r.cycleTick());
        }
    }
    @Test void noShieldCadenceNeverAddsDefensiveStops() {
        var p = new CombatPursuit();
        assertFalse(p.sample(0,0,sample(0,6),false).defend());
        assertFalse(p.sample(1,50_000_000L,sample(.1,6),false).defend());
    }
    @Test void cadenceUsesElapsedTicksAndDoesNotRestartOnSkippedOrRepeatedCalls() {
        var p = new CombatPursuit();
        assertTrue(p.sample(3,0,sample(0,6),true).defend());
        assertFalse(p.sample(14,50_000_000L,sample(.1,6),true).defend());
        assertFalse(p.sample(14,50_000_000L,sample(.1,6),true).defend());
        assertTrue(p.sample(23,100_000_000L,sample(.2,6),true).defend());
    }
    @Test void regainedClosingBeyondHistoricMinimumIsStillProgress() {
        // The old historical-best rule stops after distance 3.452 -> >4.3 -> 3.563.
        var p = new CombatPursuit();
        at(p,0,0,3.452);
        at(p,1,.3,4.7); // separation 4.4
        at(p,2,.6,4.8); // 4.2, renewed local closure
        var r = at(p,3,.9,4.463); // 3.563, still worse than the historic minimum
        assertFalse(r.failed());
        assertEquals("closing_locally",r.progress());
        assertEquals(0,r.noClosingNanos());
    }
    @Test void retreatingTargetCannotConcealStationaryPlayer() {
        var p = new CombatPursuit();
        at(p,0,0,4);
        at(p,1,0,5); at(p,2,0,6);
        var r = at(p,3,0,7);
        assertTrue(r.failed()); assertEquals("approach_stalled",r.reason());
        assertEquals("no_forward_progress",r.progress());
    }
    @Test void confirmedSelfAdvanceAllowsBoundedRetreatGraceButStopsAtSixSeconds() {
        var p = new CombatPursuit();
        for (int second=0;second<6;second++) {
            var r=at(p,second,second*.3,4+second*.4);
            assertFalse(r.failed(),"second "+second);
        }
        var r=at(p,6,1.8,6.4);
        assertTrue(r.failed()); assertEquals("target_retreat_no_closure",r.reason());
    }
    @Test void lateralOrBackwardsMotionDoesNotCountAsForwardAdvance() {
        var p = new CombatPursuit();
        p.sample(0,0,new CombatPursuit.Sample(0,0,0,4),true);
        p.sample(20,1_000_000_000L,new CombatPursuit.Sample(1,0,1,4),true);
        p.sample(40,2_000_000_000L,new CombatPursuit.Sample(2,0,2,4),true);
        var r=p.sample(60,3_000_000_000L,new CombatPursuit.Sample(3,0,3,4),true);
        assertEquals("approach_stalled",r.reason());
    }
    @Test void oscillatingPlayerCannotClaimCumulativePathLengthAsNetAdvance() {
        var p = new CombatPursuit();
        for(int tick=0;tick<60;tick++)
            assertFalse(p.sample(tick,tick*50_000_000L,sample(tick%2*.03,5),true).failed());
        assertEquals("approach_stalled",p.sample(60,3_000_000_000L,sample(0,5),true).reason());
    }
    @Test void approachingTargetCanProvideGenuineClosingWhilePlayerRemainsStill() {
        var p = new CombatPursuit();
        for(int second=0;second<6;second++)
            assertFalse(at(p,second,0,6-second*.2).failed());
    }
    @Test void priorReachOrVerifiedRecoveryResetsOnlyTheLocalPursuitWindow() {
        var p = new CombatPursuit();
        at(p,0,0,4); at(p,2,0,4); p.rebaseAfterRecovery(3_000_000_000L);
        var r=at(p,4,0,4);
        assertFalse(r.failed()); assertTrue(r.defend()); assertEquals(0,r.noClosingNanos());
        assertEquals("approach_stalled",at(p,7,0,4).reason());
    }
    @Test void nonfiniteOrBackwardsClockFailsClosed() {
        var p = new CombatPursuit();
        assertEquals("invalid_pursuit_sample",p.sample(0,0,sample(Double.NaN,4),true).reason());
        at(p,1,0,4);
        assertEquals("invalid_pursuit_clock",p.sample(19,999_999_999L,sample(0,4),true).reason());
    }
    @Test void longObservationGapDoesNotPretendIntermediateProgressWasSeen() {
        var p = new CombatPursuit();
        at(p,0,0,4);
        assertEquals("approach_stalled",at(p,4,0,4).reason());
    }
    @Test void recoveryRebaseCannotRefundAccumulatedNoClosingBudget() {
        var p = new CombatPursuit();
        at(p,0,0,4); at(p,2,0,4);
        p.rebaseAfterRecovery(3_000_000_000L);
        at(p,3,0,4); at(p,5,0,4);
        p.rebaseAfterRecovery(6_000_000_000L);
        var r=at(p,6,0,4);
        assertTrue(r.failed()); assertEquals("pursuit_no_closure_budget",r.reason());
        assertEquals(6_000_000_000L,r.totalNonClosingNanos());
    }
    @Test void repeatedReachDoesNotRefundUnproductiveWindows() {
        var p = new CombatPursuit();
        for (int i=0;i<3;i++) {
            at(p,i*3,0,4); at(p,i*3+2,.5,4.8);
            p.reached();
        }
        assertEquals("pursuit_no_closure_budget",at(p,9,0,4).reason());
    }

    @Test void repeatedSubWindowRecoveriesStillConsumeTheTotalBudget() {
        var p = new CombatPursuit();
        for(int episode=0;episode<15;episode++) {
            long now=episode*400_000_000L;
            assertFalse(p.sample(episode*8,now,sample(0,4),true).failed());
            p.rebaseAfterRecovery(now+400_000_000L);
        }
        var r=p.sample(120,6_000_000_000L,sample(0,4),true);
        assertEquals("pursuit_no_closure_budget",r.reason());
        assertEquals(6_000_000_000L,r.totalNonClosingNanos());
    }

    @Test void realLocalClosingDoesNotRefundEarlierUnproductiveWindows() {
        var p = new CombatPursuit();
        for(int second=0;second<11;second++) {
            double player=second*.2;
            var r=at(p,second,player,player+(second%2==0 ? 4 : 4.2));
            assertFalse(r.failed(),"second "+second);
            if(second>0 && second%2==0) assertEquals("closing_locally",r.progress());
        }
        var r=at(p,11,2.2,6.4);
        assertEquals("pursuit_no_closure_budget",r.reason());
        assertEquals(6_000_000_000L,r.totalNonClosingNanos());
    }

}
