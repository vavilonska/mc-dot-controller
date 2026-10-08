package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Executable pure policy fixtures; these do not simulate server damage, fuse time, or survival. */
class CombatThreatsTest {
    private static final long NOW = 1_000_000_000L;
    private static final int TICK = 20;
    private static CombatThreats.Observed mob(int id, String type, double x, double z) {
        return new CombatThreats.Observed(id, "uuid-" + id, type, x, 64, z, .3, true, true);
    }
    private static CombatThreats.Observed passive(int id, String type, double x, double z) {
        return new CombatThreats.Observed(id, "uuid-" + id, type, x, 64, z, .3, false, true);
    }
    private static CombatThreats.Snapshot snapshot(CombatThreats.Observed... observations) {
        return new CombatThreats.Snapshot(Arrays.asList(observations), NOW, TICK, false, true);
    }
    private static CombatThreats.HealthGuard.Result healthy() {
        return new CombatThreats.HealthGuard().sample(TICK, NOW, 20);
    }
    private static CombatThreats.Gate gate(CombatThreats.Snapshot snapshot) {
        return CombatThreats.evaluate(snapshot, NOW, TICK, 0, 64, 0, 1, "uuid-1", healthy());
    }
    private static CombatThreats.Gate gate(CombatThreats.Observed... observations) { return gate(snapshot(observations)); }
    private static CombatThreats.Route route(CombatThreats.Snapshot s, double x, double z) {
        return CombatThreats.route(s, NOW, TICK, 0, 0, x, z, 1, "uuid-1");
    }
    private static CombatThreats.Route escape(CombatThreats.Snapshot s, double x, double z) {
        return CombatThreats.escapeRoute(s, NOW, TICK, 0, 0, x, z);
    }

    @Test void onlyTheSixSpecifiedAttackTypesAreSupported() {
        for (String type : List.of("zombie", "husk", "zombie_villager", "skeleton", "stray", "bogged")) {
            assertTrue(CombatThreats.supportsAttack(type));
            assertTrue(CombatThreats.supportsAttack("minecraft:" + type));
            assertTrue(CombatThreats.observableThreat(type));
            assertFalse(gate(mob(1, type, 2, 0)).stop());
        }
        for (String type : List.of("creeper", "spider", "enderman", "drowned", "wither_skeleton", "cow", "custom:zombie"))
            assertFalse(CombatThreats.supportsAttack(type), type);
        assertFalse(CombatThreats.supportsAttack(null));
    }

    @Test void oneSupportedTargetMayProceedButRiskIsStillPresent() {
        var g = gate(mob(1, "zombie", 2, 0));
        assertFalse(g.stop()); assertTrue(g.riskRemaining()); assertTrue(g.fresh());
        assertEquals(1, g.snapshotCount()); assertFalse(g.truncated()); assertEquals(-1, g.emergencyId());
    }

    @Test void emptyCompleteObservationCanProceedWithoutATargetOrRisk() {
        var g = CombatThreats.evaluate(snapshot(), NOW, TICK, 0, 64, 0, -1, "", healthy());
        assertFalse(g.stop()); assertFalse(g.riskRemaining());
    }

    @Test void nearbyCreeperStopsEvenWithoutIgnitionOrSwellData() {
        var g = gate(mob(1, "zombie", 2, 0), mob(2, "creeper", 8.3, 0));
        assertTrue(g.stop()); assertEquals("critical_creeper_near", g.reason());
        assertEquals(2, g.emergencyId()); assertEquals("uuid-2", g.emergencyUuid());
        assertTrue(g.riskRemaining());
    }

    @Test void creeperAlwaysForbiddenAsCollateralOrSelectedTarget() {
        assertFalse(CombatThreats.allowsSweepCollateral("creeper"));
        assertEquals("unsupported_attack_target", CombatThreats.sweep(snapshot(mob(1, "creeper", 2, 0)), NOW, TICK, 1, "uuid-1").reason());
        var g = CombatThreats.sweep(snapshot(mob(1, "zombie", 2, 0), mob(2, "creeper", 3, 0)), NOW, TICK, 1, "uuid-1");
        assertTrue(g.stop()); assertEquals("sweep_collateral_forbidden", g.reason()); assertEquals(2, g.emergencyId());
    }

    @Test void nearbyUnsupportedSpiderStopsBeforeOffense() {
        for (String type : List.of("spider", "cave_spider", "drowned", "witch", "mod:unknown_hostile")) {
            var g = gate(mob(1, "zombie", 2, 0), mob(2, type, 7.5, 0));
            assertTrue(g.stop()); assertEquals("unsupported_threat_near", g.reason(), type);
            assertEquals(2, g.emergencyId()); assertTrue(g.riskRemaining());
        }
    }

    @Test void everyObservedEndermanBlocksGazeBeforeAimEvenOutsideEightBlocks() {
        var g = gate(mob(1, "zombie", 2, 0), passive(2, "enderman", 15.9, 0));
        assertTrue(g.stop()); assertEquals("enderman_gaze_unplanned", g.reason()); assertEquals(2, g.emergencyId());
    }

    @Test void classifierIndependentlyRecognizesKnownDangerWhenAdapterFlagIsFalse() {
        var g = gate(mob(1, "zombie", 2, 0), passive(2, "creeper", 5, 0));
        assertEquals("critical_creeper_near", g.reason());
    }

    @Test void twoSupportedHostilesStopRatherThanClaimingMultikill() {
        var g = gate(mob(1, "zombie", 2, 0), mob(2, "skeleton", -3, 0));
        assertTrue(g.stop()); assertEquals("multiple_threats_near", g.reason()); assertTrue(g.riskRemaining());
    }

    @Test void oneNearbyNonTargetBlocksPursuitOfADistantSelectedTarget() {
        var g = gate(mob(1, "zombie", 10, 0), mob(2, "skeleton", 2, 0));
        assertTrue(g.stop()); assertEquals("non_target_threat_near", g.reason());
        assertEquals(2, g.emergencyId()); assertTrue(g.riskRemaining());
    }

    @Test void emergencyIdentityIsDeterministicForEqualDistances() {
        var a = mob(1, "zombie", 2, 0); var b = mob(2, "skeleton", -2, 0);
        assertEquals(1, gate(a, b).emergencyId()); assertEquals(1, gate(b, a).emergencyId());
    }

    @Test void distantDangerRemainsObservableButDoesNotAloneStopSingleTarget() {
        var g = gate(mob(1, "zombie", 2, 0), mob(2, "spider", 12, 0));
        assertFalse(g.stop()); assertTrue(g.riskRemaining()); assertEquals(2, g.snapshotCount());
    }

    @Test void aliveFilterDoesNotCountKnownDeadObservationAsThreatOrCollateral() {
        var dead = new CombatThreats.Observed(2, "uuid-2", "creeper", 2, 64, 0, .3, true, false);
        var s = snapshot(mob(1, "zombie", 2, 0), dead);
        assertFalse(gate(s).stop()); assertFalse(CombatThreats.sweep(s, NOW, TICK, 1, "uuid-1").stop());
    }

    @Test void missingOrReusedEntityIdNeverAuthorizesAnotherTarget() {
        assertEquals("target_missing_from_snapshot", gate(snapshot()).reason());
        var replacement = new CombatThreats.Observed(1, "replacement-uuid", "zombie", 2, 64, 0, .3, true, true);
        assertEquals("non_target_threat_near", gate(replacement).reason());
        assertTrue(CombatThreats.sweep(snapshot(replacement), NOW, TICK, 1, "uuid-1").stop());
    }

    @Test void truncatedSnapshotAlwaysFailsClosedAndPreservesDiagnostics() {
        var s = new CombatThreats.Snapshot(List.of(mob(1, "zombie", 2, 0)), NOW, TICK, true, true);
        var g = gate(s);
        assertTrue(g.stop()); assertEquals("threat_snapshot_truncated", g.reason());
        assertTrue(g.truncated()); assertTrue(g.fresh()); assertTrue(g.riskRemaining());
        assertFalse(route(s, 1, 0).safe()); assertFalse(escape(s, -1, 0).safe());
    }

    @Test void snapshotCopyHasFixedCapAndNoMutableListAlias() {
        var input = new ArrayList<CombatThreats.Observed>();
        for (int i = 0; i < 200; i++) input.add(passive(i, "cow", 10, i));
        var s = new CombatThreats.Snapshot(input, NOW, TICK, false, true);
        assertEquals(CombatThreats.MAX_OBSERVED, s.count()); assertTrue(s.truncated());
        input.clear(); assertEquals(CombatThreats.MAX_OBSERVED, s.count());
        assertThrows(UnsupportedOperationException.class, () -> s.entities().clear());
        assertTrue(gate(s).stop());
    }

    @Test void exactlyAtObservationCapIsCompleteOnlyWhenAdapterSaysComplete() {
        var input = new ArrayList<CombatThreats.Observed>();
        for (int i = 0; i < CombatThreats.MAX_OBSERVED; i++) input.add(passive(i, "cow", 10, i));
        var s = new CombatThreats.Snapshot(input, NOW, TICK, false, true);
        assertEquals(128, s.count()); assertFalse(s.truncated());
        assertFalse(CombatThreats.evaluate(s, NOW, TICK, 0, 64, 0, -1, "", healthy()).stop());
    }

    @Test void unknownNullAndMalformedSnapshotDataFailClosed() {
        assertEquals("threat_snapshot_unknown", gate((CombatThreats.Snapshot)null).reason());
        assertEquals("threat_snapshot_unknown", gate(new CombatThreats.Snapshot(null, NOW, TICK, false, true)).reason());
        assertEquals("threat_snapshot_unknown", gate(new CombatThreats.Snapshot(List.of(), NOW, TICK, false, false)).reason());
        var invalid = new CombatThreats.Observed(2, "uuid-2", "spider", Double.NaN, 64, 0, .3, true, true);
        assertEquals("threat_snapshot_invalid", gate(mob(1, "zombie", 2, 0), invalid).reason());
        assertEquals("threat_snapshot_invalid", gate(snapshot((CombatThreats.Observed)null)).reason());
    }

    @Test void duplicateIdentityMakesThreatCountUntrustworthy() {
        assertEquals("threat_snapshot_invalid", gate(mob(1, "zombie", 2, 0), mob(1, "skeleton", 3, 0)).reason());
    }

    @Test void oldTimestampPreviousTickAndFutureTimestampAreNotFresh() {
        for (CombatThreats.Snapshot s : List.of(
                new CombatThreats.Snapshot(List.of(mob(1, "zombie", 2, 0)), NOW - CombatThreats.MAX_SNAPSHOT_AGE_NANOS - 1, TICK, false, true),
                new CombatThreats.Snapshot(List.of(mob(1, "zombie", 2, 0)), NOW, TICK - 1, false, true),
                new CombatThreats.Snapshot(List.of(mob(1, "zombie", 2, 0)), NOW + 1, TICK, false, true))) {
            var g = gate(s);
            assertTrue(g.stop()); assertFalse(g.fresh()); assertTrue(g.riskRemaining());
            assertEquals("threat_snapshot_stale", g.reason());
            assertTrue(CombatThreats.sweep(s, NOW, TICK, 1, "uuid-1").stop());
        }
    }

    @Test void unknownHealthRefusesOffenseEvenWithCompleteThreatData() {
        var g = CombatThreats.evaluate(snapshot(mob(1, "zombie", 2, 0)), NOW, TICK, 0, 64, 0, 1, "uuid-1", null);
        assertTrue(g.stop()); assertEquals("health_unknown", g.reason()); assertTrue(g.riskRemaining());
    }

    @Test void lowHealthSafetyResultStopsGateAndIsLatchedAcrossHealing() {
        var health = new CombatThreats.HealthGuard();
        var low = health.sample(0, 0, 14);
        assertTrue(low.interrupted()); assertEquals("low_health", low.reason());
        assertEquals(low, health.sample(20, NOW, 20));
        var g = CombatThreats.evaluate(snapshot(mob(1, "zombie", 2, 0)), NOW, TICK, 0, 64, 0, 1, "uuid-1", low);
        assertTrue(g.stop()); assertEquals("low_health", g.reason());
    }

    @Test void sustainedSmallLossesAccumulateToFourHpWithinOneSecond() {
        var h = new CombatThreats.HealthGuard();
        for (int i = 0; i < 4; i++) assertFalse(h.sample(i, i * 50_000_000L, 20 - i).interrupted());
        var r = h.sample(4, 200_000_000L, 16);
        assertTrue(r.interrupted()); assertEquals("rapid_health_loss", r.reason()); assertEquals(4, r.damageInWindow());
        assertEquals(r, h.sample(100, 10_000_000_000L, 20));
    }

    @Test void healingDoesNotRefundDamageAndRepeatedSameTickSamplesCannotResetIt() {
        var h = new CombatThreats.HealthGuard();
        h.sample(0, 0, 20); h.sample(1, 50_000_000L, 18); h.sample(2, 100_000_000L, 20);
        for (int i = 0; i < 100; i++) assertFalse(h.sample(2, 100_000_000L + i, 20).interrupted());
        var r = h.sample(3, 150_000_000L, 18);
        assertEquals("rapid_health_loss", r.reason()); assertEquals(4, r.damageInWindow()); assertEquals(4, r.sampleCount());
    }

    @Test void multipleHealthChangesWithinOneTickRetainEachLossWithoutGrowingRing() {
        var h = new CombatThreats.HealthGuard();
        h.sample(0, 0, 20); h.sample(0, 1, 18); h.sample(0, 2, 20);
        var r = h.sample(0, 3, 18);
        assertTrue(r.interrupted()); assertEquals(4, r.damageInWindow()); assertEquals(1, r.sampleCount());
    }

    @Test void normalTwentyHzHistoryIsBoundedAcrossLongHealthyRun() {
        var h = new CombatThreats.HealthGuard();
        for (int tick = 0; tick < 10_000; tick++) {
            var r = h.sample(tick, tick * 50_000_000L, 20);
            assertFalse(r.interrupted()); assertTrue(r.sampleCount() <= 21);
        }
    }

    @Test void damageExpiresOnlyAfterRollingWindowWithContinuousObservations() {
        var h = new CombatThreats.HealthGuard();
        h.sample(0, 0, 20); h.sample(1, 50_000_000L, 18);
        for (int tick = 2; tick <= 21; tick++) {
            var r = h.sample(tick, tick * 50_000_000L, 20);
            assertFalse(r.interrupted()); assertEquals(2, r.damageInWindow());
        }
        var r = h.sample(22, 1_100_000_000L, 18);
        assertFalse(r.interrupted()); assertEquals(2, r.damageInWindow());
    }

    @Test void healthHistoryOverflowRefusesInsteadOfDroppingUnexpiredLosses() {
        var h = new CombatThreats.HealthGuard();
        for (int i = 0; i < CombatThreats.HealthGuard.CAPACITY; i++)
            assertFalse(h.sample(i, i * 1_000_000L, 20).interrupted());
        var r = h.sample(24, 24_000_000L, 20);
        assertTrue(r.interrupted()); assertEquals("health_history_overflow", r.reason()); assertFalse(r.known());
    }

    @Test void unknownHealthNonmonotonicClockAndObservationGapsLatch() {
        for (double value : new double[] { Double.NaN, Double.POSITIVE_INFINITY, -1 }) {
            var h = new CombatThreats.HealthGuard();
            assertEquals("health_data_unknown", h.sample(0, 0, value).reason());
            assertTrue(h.sample(1, 50_000_000L, 20).interrupted());
        }
        var h = new CombatThreats.HealthGuard(); h.sample(1, 100, 20);
        assertEquals("health_clock_invalid", h.sample(0, 101, 20).reason());
        h = new CombatThreats.HealthGuard(); h.sample(1, 100, 20);
        assertEquals("health_clock_invalid", h.sample(2, 99, 20).reason());
        h = new CombatThreats.HealthGuard(); h.sample(0, 0, 20);
        assertEquals("health_observation_gap", h.sample(1, 150_000_001L, 20).reason());
        h = new CombatThreats.HealthGuard(); h.sample(0, 0, 20);
        assertEquals("health_observation_gap", h.sample(4, 10, 20).reason());
    }

    @Test void repeatedFrozenTickCannotRefreshHealthForever() {
        var h = new CombatThreats.HealthGuard(); h.sample(0, 0, 20);
        assertFalse(h.sample(0, 100_000_000L, 20).interrupted());
        assertEquals("health_observation_gap", h.sample(0, 150_000_001L, 20).reason());
    }

    @Test void sweepRejectsSupportedHostileAndPassiveCollateralToo() {
        for (CombatThreats.Observed other : List.of(mob(2, "husk", 3, 0), passive(2, "cow", 3, 0), passive(2, "player", 3, 0))) {
            var g = CombatThreats.sweep(snapshot(mob(1, "zombie", 2, 0), other), NOW, TICK, 1, "uuid-1");
            assertTrue(g.stop()); assertEquals("sweep_collateral_forbidden", g.reason());
        }
    }

    @Test void isolatedSwordTargetHasNoCollateralAndVerticalSeparationIsConservative() {
        assertFalse(CombatThreats.sweep(snapshot(mob(1, "zombie", 2, 0)), NOW, TICK, 1, "uuid-1").stop());
        var high = new CombatThreats.Observed(2, "uuid-2", "cow", 2, 67, 0, .3, false, true);
        assertTrue(CombatThreats.sweep(snapshot(mob(1, "zombie", 2, 0), high), NOW, TICK, 1, "uuid-1").stop());
    }

    @Test void sweepBoxIncludesDiagonalCollateralMissedByARadialCheck() {
        var s = snapshot(mob(1, "zombie", 2, 0), passive(2, "cow", 3.55, 1.55));
        assertTrue(CombatThreats.sweep(s, NOW, TICK, 1, "uuid-1").stop());
    }

    @Test void unsupportedTargetCannotBeExemptedFromRouteThreatChecks() {
        var s = snapshot(mob(1, "creeper", 12, 0));
        var r = route(s, 1, 0);
        assertFalse(r.safe()); assertEquals("unsupported_attack_target", r.reason());
    }

    @Test void normalRouteExcludesOnlyTheExactSelectedTarget() {
        var s = snapshot(mob(1, "zombie", 2, 0));
        assertTrue(route(s, 1, 0).safe());
        assertFalse(CombatThreats.route(s, NOW, TICK, 0, 0, 1, 0, 1, "wrong-uuid").safe());
    }

    @Test void routeMustNotApproachAnyNonTargetDangerEvenOutsideEightBlocks() {
        var s = snapshot(mob(1, "zombie", 0, 2), mob(2, "spider", 12, 0));
        assertFalse(route(s, 1, 0).safe()); assertEquals("route_reduces_threat_clearance", route(s, 1, 0).reason());
        assertTrue(route(s, -1, 0).safe());
    }

    @Test void distantEndpointsDoNotHideAMidSegmentApproach() {
        // Start/end both 10 blocks from the spider; the segment passes directly through it.
        var s = snapshot(mob(1, "zombie", 0, 2), mob(2, "spider", 10, 0));
        var r = route(s, 20, 0);
        assertFalse(r.safe()); assertEquals("route_reduces_threat_clearance", r.reason());
        assertTrue(r.minimumClearance() < 0); assertEquals(9.7, r.endpointClearance(), 1e-9);
    }

    @Test void edgeApproachFailsEvenWhenEndpointIsFartherFromDanger() {
        var s = snapshot(mob(1, "zombie", 0, 2), mob(2, "creeper", 9, 1));
        var r = route(s, 20, 0);
        assertFalse(r.safe()); assertTrue(r.endpointClearance() > Math.hypot(9, 1) - .3);
        assertEquals(.7, r.minimumClearance(), 1e-9);
    }

    @Test void normalRouteCannotClaimAWithdrawalFromAlreadyNearbyOtherDanger() {
        var s = snapshot(mob(1, "zombie", 0, 2), mob(2, "spider", 5, 0));
        assertEquals("route_starts_near_nontarget_threat", route(s, -1, 0).reason());
    }

    @Test void escapeCanExitCriticalRadiusOnlyWithPositiveClearanceProgress() {
        var s = snapshot(mob(1, "creeper", 3, 0));
        var r = escape(s, -1, 0);
        assertTrue(r.safe()); assertEquals("escape_clearance_improves", r.reason());
        assertEquals(2.7, r.minimumClearance(), 1e-9); assertEquals(3.7, r.endpointClearance(), 1e-9);
        assertFalse(escape(s, .5, 0).safe()); assertFalse(escape(s, -.05, 0).safe());
        assertEquals("escape_no_clearance_progress", escape(s, 0, 0).reason());
    }

    @Test void escapeIncludesSelectedAttackerAndCannotMoveCloserToOtherDanger() {
        var s = snapshot(mob(1, "zombie", 3, 0), mob(2, "creeper", -5, 0));
        assertFalse(escape(s, 1, 0).safe()); assertFalse(escape(s, -1, 0).safe());
    }

    @Test void routeScoreRanksFartherEndpointWhileCheckingTheWholeSegment() {
        var s = snapshot(mob(1, "creeper", 3, 0));
        var near = escape(s, -1, 0); var farther = escape(s, -2, 0);
        assertTrue(near.safe()); assertTrue(farther.safe());
        assertEquals(near.minimumClearance(), farther.minimumClearance());
        assertTrue(farther.endpointClearance() > near.endpointClearance());
    }

    @Test void nonfiniteRouteAndUnknownSnapshotNeverAuthorizeMovement() {
        assertFalse(route(snapshot(mob(1, "zombie", 2, 0)), Double.NaN, 0).safe());
        assertFalse(escape(null, -1, 0).safe());
        var old = new CombatThreats.Snapshot(List.of(), NOW, TICK - 1, false, true);
        assertFalse(escape(old, -1, 0).safe());
    }
}
