package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static io.github.campione01.mineclientbridge.CombatRecovery.State.*;

class CombatRecoveryTest {
    private static CombatRecovery.Motion motion(boolean ground, double y, double vx, double vy, double vz) {
        return new CombatRecovery.Motion(1.5, y, 2.5, vx, vy, vz, ground);
    }
    private static CombatRecovery.Motion airborne() { return motion(false, 64.275125, .12, -.1, 0); }
    private static CombatRecovery.Motion landed() { return motion(true, 64, .01, -.0784, 0); }

    @Test void groundedOrdinaryCombatDoesNotEnterRecoveryOrReuseACorridor() {
        var recovery = new CombatRecovery();
        assertEquals(CONTINUE, recovery.sample(1, landed(), 1, d -> fail("No recovery corridor needed")).state());
        assertFalse(recovery.active());
        assertEquals(0, recovery.episodes());
    }

    @Test void recordedAirbornePoseWaitsThenRequiresTwoGroundedSamplesAndFreshCorridor() {
        var recovery = new CombatRecovery();
        var checks = new AtomicInteger();
        assertEquals("waiting_airborne_recovery", recovery.sample(20, airborne(), 1, d -> {
            fail("Airborne terrain must not authorize motion"); return true;
        }).reason());
        assertEquals(WAIT, recovery.sample(21, landed(), 1, d -> { checks.incrementAndGet(); return true; }).state());
        assertEquals(0, checks.get());
        assertEquals(RECOVERED, recovery.sample(22, landed(), 1, d -> { checks.incrementAndGet(); return true; }).state());
        assertEquals(1, checks.get());
        assertEquals(1, recovery.episodes());
        assertEquals(3, recovery.episodeTicks());
        assertEquals(3, recovery.totalTicks());
        assertEquals(1, recovery.completed());
        assertFalse(recovery.active());
        assertEquals(CONTINUE, recovery.sample(23, landed(), 1, d -> fail("No cached recovery/rebase")).state());
    }

    @Test void bothApproachAndRetreatAndStationaryResumeUseCurrentDirection() {
        for (int direction : new int[]{1, -1, 0}) {
            var recovery = new CombatRecovery();
            List<Integer> checked = new ArrayList<>();
            recovery.sample(1, airborne(), -direction, d -> false);
            recovery.sample(2, landed(), -direction, d -> false);
            assertEquals(RECOVERED, recovery.sample(3, landed(), direction, d -> {
                checked.add(d); return true;
            }).state());
            assertEquals(List.of(direction), checked);
        }
    }

    @Test void persistentAirborneExpiresOnTwentiethTickWithoutCorridorRead() {
        var recovery = new CombatRecovery();
        for (int tick = 50; tick < 69; tick++)
            assertEquals(WAIT, recovery.sample(tick, airborne(), 1, d -> fail("Still airborne")).state());
        var result = recovery.sample(69, airborne(), 1, d -> fail("Still airborne"));
        assertEquals(FAILED, result.state());
        assertEquals("airborne_recovery_timeout", result.reason());
        assertEquals(20, recovery.episodeTicks());
        assertEquals(1, recovery.episodes());
    }

    @Test void repeatedKnockbackResetsSettlementButNeverExtendsEpisode() {
        var recovery = new CombatRecovery();
        for (int tick = 1; tick < 20; tick++) {
            assertEquals(WAIT, recovery.sample(tick, tick % 2 == 0 ? landed() : airborne(), 1,
                    d -> fail("Never settled twice")).state());
        }
        assertEquals("airborne_recovery_timeout", recovery.sample(20, landed(), 1, d -> false).reason());
        assertEquals(20, recovery.totalTicks());
        assertEquals(0, recovery.completed());
    }

    @Test void freshEpisodeAfterVerifiedRecoveryHasNewCountWithoutOldSettledSamples() {
        var recovery = new CombatRecovery();
        recovery.sample(1, airborne(), 1, d -> true);
        recovery.sample(2, landed(), 1, d -> true);
        recovery.sample(3, landed(), 1, d -> true);
        assertEquals(WAIT, recovery.sample(4, airborne(), 1, d -> true).state());
        assertEquals(0, recovery.settledSamples());
        assertEquals(WAIT, recovery.sample(5, landed(), 1, d -> true).state());
        assertEquals(RECOVERED, recovery.sample(6, landed(), 1, d -> true).state());
        assertEquals(2, recovery.episodes());
        assertEquals(2, recovery.completed());
        assertEquals(6, recovery.totalTicks());
    }

    @Test void finalBudgetTickMaySettleButLateOrNonconsecutiveSamplesCannot() {
        var recovery = new CombatRecovery();
        recovery.sample(1, airborne(), 1, d -> false);
        assertEquals(WAIT, recovery.sample(19, landed(), 1, d -> true).state());
        assertEquals(RECOVERED, recovery.sample(20, landed(), 1, d -> true).state());
        var expired = new CombatRecovery();
        expired.sample(1, airborne(), 1, d -> false);
        expired.sample(20, landed(), 1, d -> false);
        assertEquals(FAILED, expired.sample(21, landed(), 1, d -> fail("Budget expired")).state());
        var skipped = new CombatRecovery();
        skipped.sample(1, airborne(), 1, d -> true);
        skipped.sample(2, landed(), 1, d -> true);
        assertEquals(WAIT, skipped.sample(4, landed(), 1, d -> fail("Samples were not consecutive")).state());
    }

    @Test void horizontalOrVerticalMotionMustSettleAndGroundFlagIsRequired() {
        for (var unstable : List.of(motion(true, 64, .03001, 0, 0), motion(true, 64, .025, 0, .025),
                motion(true, 64, 0, .08001, 0), motion(true, 64, 0, -.08001, 0), motion(false, 64, 0, 0, 0))) {
            var recovery = new CombatRecovery();
            recovery.sample(1, airborne(), 1, d -> true);
            recovery.sample(2, landed(), 1, d -> true);
            assertEquals(WAIT, recovery.sample(3, unstable, 1, d -> fail("Motion is not settled")).state());
            assertEquals(0, recovery.settledSamples());
            assertEquals(WAIT, recovery.sample(4, landed(), 1, d -> true).state());
            assertEquals(RECOVERED, recovery.sample(5, landed(), 1, d -> true).state());
        }
    }

    @Test void nonFinitePositionOrVelocityFailsClosedEvenBeforeRecovery() {
        for (double invalid : new double[]{Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY}) {
            for (int field = 0; field < 6; field++) {
                double[] values = {1.5, 64, 2.5, 0, 0, 0}; values[field] = invalid;
                var bad = new CombatRecovery.Motion(values[0], values[1], values[2], values[3], values[4], values[5], true);
                for (boolean active : new boolean[]{false, true}) {
                    var recovery = new CombatRecovery();
                    if (active) recovery.sample(1, airborne(), 1, d -> true);
                    var result = recovery.sample(2, bad, 1, d -> fail("Invalid motion cannot authorize a corridor"));
                    assertEquals(FAILED, result.state());
                    assertEquals("invalid_combat_motion", result.reason());
                }
            }
        }
    }

    @Test void groundedFractionalLandingIsUnsupportedNotRoundedIntoSafety() {
        for (double height : new double[]{64.275125, 64.5, 63.9375, 64.125}) {
            var recovery = new CombatRecovery();
            recovery.sample(1, airborne(), 1, d -> true);
            var result = recovery.sample(2, motion(true, height, 0, 0, 0), 1, d -> fail("Unsupported pose"));
            assertEquals(FAILED, result.state());
            assertEquals("unsupported_recovery_pose", result.reason());
        }
    }

    @Test void anyUnsafeFreshLandingCorridorPreventsResumeInBothDirections() {
        // Adapter contract separately verifies the actual loaded/support/fluid/hazard/collision predicates.
        for (String hazard : new String[]{"missing_support", "drop", "water", "lava", "contact_hazard",
                "feet_collision", "head_collision", "unloaded", "unknown_collision"}) {
            for (int direction : new int[]{-1, 0, 1}) {
                var recovery = new CombatRecovery();
                recovery.sample(1, airborne(), direction, d -> true);
                recovery.sample(2, landed(), direction, d -> true);
                var result = recovery.sample(3, landed(), direction, d -> false);
                assertEquals(FAILED, result.state(), hazard);
                assertEquals("recovery_landing_corridor_blocked", result.reason());
                assertEquals(0, recovery.completed());
            }
        }
    }
}
