package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Pure health samples and exact JSON evidence; no game, network, damage-source, or survival claims. */
class CombatHealthDiagnosticsTest {
    private static final long START = 1_000_000_000L;
    private static final long GAP = 150_000_000L;

    @Test void unsampledDiagnosticsHaveNoFabricatedObservation() {
        var guard = new CombatThreats.HealthGuard();
        assertNull(guard.diagnostics());
        var json = CombatHealthEvidence.snapshot(guard.diagnostics());
        assertFalse(json.get("sampled").getAsBoolean());
        assertTrue(json.get("current_observation").isJsonNull());
        assertTrue(json.get("latch_trigger").isJsonNull());
    }

    @Test void firstSampleUsesNullPreviousFieldsAndAllowsSignedNanoTimeOrigin() {
        var guard = new CombatThreats.HealthGuard();
        assertFalse(guard.sample(1, -START, 20).interrupted());
        var d = guard.diagnostics().current();
        assertEquals(1, d.sampleTick()); assertEquals(-START, d.sampleNanos());
        assertNull(d.previousValidSampleTick()); assertNull(d.previousValidSampleNanos());
        assertNull(d.sampleDeltaNanos()); assertNull(d.tickDelta());
        assertEquals(0, d.sameTickElapsedNanos());
        assertTrue(d.valid()); assertFalse(d.continuous());
        assertEquals("first_valid_sample", d.detail());
        assertNull(guard.diagnostics().trigger()); assertFalse(guard.diagnostics().latched());
    }

    @Test void exactly150MillisecondsIsAcceptedWithExactEvidence() {
        var guard = initial();
        var result = guard.sample(2, START + GAP, 20);
        assertFalse(result.interrupted());
        var d = guard.diagnostics().current();
        assertEquals(2, d.sampleTick()); assertEquals(START + GAP, d.sampleNanos());
        assertEquals(1, d.previousValidSampleTick()); assertEquals(START, d.previousValidSampleNanos());
        assertEquals(GAP, d.sampleDeltaNanos()); assertEquals(1, d.tickDelta());
        assertFalse(d.wallGap()); assertFalse(d.tickGap()); assertFalse(d.frozenTick());
        assertTrue(d.continuous());
    }

    @Test void oneNanosecondOver150MillisecondsLatchesWallGap() {
        var guard = initial();
        var result = guard.sample(2, START + GAP + 1, 20);
        assertEquals("health_observation_gap", result.reason()); assertFalse(result.known());
        var d = guard.diagnostics().current();
        assertEquals(GAP + 1, d.sampleDeltaNanos());
        assertTrue(d.wallGap()); assertFalse(d.tickGap()); assertFalse(d.frozenTick());
        assertEquals("wall_gap", d.detail()); assertFalse(d.continuous());
        assertSame(d, guard.diagnostics().trigger()); assertTrue(guard.diagnostics().latchTriggeredNow());
    }

    @Test void oneNanosecondBelow150MillisecondsIsAccepted() {
        var guard = initial();
        assertFalse(guard.sample(2, START + GAP - 1, 20).interrupted());
        assertEquals(GAP - 1, guard.diagnostics().current().sampleDeltaNanos());
    }

    @Test void tickDeltaThreeIsAcceptedAndFourIsAnIndependentGap() {
        var guard = initial();
        assertFalse(guard.sample(4, START + 1, 20).interrupted());
        assertEquals(3, guard.diagnostics().current().tickDelta());
        guard = initial();
        assertEquals("health_observation_gap", guard.sample(5, START + 1, 20).reason());
        var d = guard.diagnostics().current();
        assertEquals(4, d.tickDelta()); assertEquals(1, d.sampleDeltaNanos());
        assertTrue(d.tickGap()); assertFalse(d.wallGap()); assertFalse(d.frozenTick());
        assertEquals("tick_gap", d.detail());
    }

    @Test void simultaneousWallAndTickGapsBothAppearInDetail() {
        var guard = initial();
        guard.sample(5, START + GAP + 1, 20);
        var d = guard.diagnostics().current();
        assertTrue(d.wallGap()); assertTrue(d.tickGap()); assertFalse(d.frozenTick());
        assertEquals("wall_gap+tick_gap", d.detail());
    }

    @Test void frozenTickExactly150MillisecondsIsAcceptedButOneMoreNanosecondLatches() {
        var guard = initial();
        assertFalse(guard.sample(1, START + 100_000_000L, 20).interrupted());
        assertFalse(guard.sample(1, START + GAP, 20).interrupted());
        assertEquals(GAP, guard.diagnostics().current().sameTickElapsedNanos());
        assertFalse(guard.diagnostics().current().frozenTick());
        assertEquals("health_observation_gap", guard.sample(1, START + GAP + 1, 20).reason());
        var d = guard.diagnostics().current();
        assertEquals(1, d.sampleDeltaNanos()); assertEquals(0, d.tickDelta());
        assertEquals(GAP + 1, d.sameTickElapsedNanos());
        assertFalse(d.wallGap()); assertFalse(d.tickGap()); assertTrue(d.frozenTick());
        assertEquals("frozen_tick", d.detail());
    }

    @Test void sameTickGapCanBeBothWallAndFrozen() {
        var guard = initial();
        guard.sample(1, START + GAP + 1, 20);
        var d = guard.diagnostics().current();
        assertEquals("wall_gap+frozen_tick", d.detail());
        assertTrue(d.wallGap()); assertTrue(d.frozenTick()); assertFalse(d.tickGap());
    }

    @Test void exactly150MillisecondSampleDeltaDoesNotHideLongerFrozenTick() {
        var guard = initial();
        guard.sample(1, START + 100_000_000L, 20);
        guard.sample(1, START + 250_000_000L, 20);
        var d = guard.diagnostics().current();
        assertEquals(GAP, d.sampleDeltaNanos()); assertEquals(250_000_000L, d.sameTickElapsedNanos());
        assertFalse(d.wallGap()); assertTrue(d.frozenTick());
    }

    @Test void changingTickResetsOnlySameTickElapsedClock() {
        var guard = initial();
        guard.sample(1, START + GAP, 20);
        assertFalse(guard.sample(2, START + GAP + 1, 20).interrupted());
        assertEquals(0, guard.diagnostics().current().sameTickElapsedNanos());
        assertFalse(guard.sample(2, START + 2 * GAP + 1, 20).interrupted());
        assertEquals(GAP, guard.diagnostics().current().sameTickElapsedNanos());
    }

    @Test void wallClockRegressionIsDistinctFromObservationGapAndDoesNotAdvanceReference() {
        var guard = initial();
        var result = guard.sample(2, START - 1, 20);
        assertEquals("health_clock_invalid", result.reason()); assertFalse(result.known());
        var trigger = guard.diagnostics().trigger();
        assertEquals(-1, trigger.sampleDeltaNanos()); assertFalse(trigger.clockValid());
        assertEquals("wall_clock_regressed", trigger.detail());
        assertSame(result, guard.sample(2, START + 1, 20));
        var current = guard.diagnostics().current();
        assertEquals(1, current.previousValidSampleTick()); assertEquals(START, current.previousValidSampleNanos());
        assertEquals(1, current.sampleDeltaNanos()); assertTrue(current.continuous());
        assertSame(trigger, guard.diagnostics().trigger());
    }

    @Test void tickRegressionAndDualClockRegressionHavePreciseDetails() {
        var guard = initial();
        assertEquals("health_clock_invalid", guard.sample(0, START + 1, 20).reason());
        assertEquals("tick_clock_regressed", guard.diagnostics().current().detail());
        assertEquals(-1, guard.diagnostics().current().tickDelta());
        guard = initial();
        assertEquals("health_clock_invalid", guard.sample(0, START - 1, 20).reason());
        assertEquals("tick_and_wall_clock_regressed", guard.diagnostics().current().detail());
    }

    @Test void malformedHealthDoesNotBecomeThePreviousValidSample() {
        for (double health : new double[] { Double.NaN, Double.POSITIVE_INFINITY, -1 }) {
            var guard = initial();
            var result = guard.sample(2, START + 10, health);
            assertEquals("health_data_unknown", result.reason());
            assertFalse(guard.diagnostics().current().dataValid());
            assertEquals("invalid_health", guard.diagnostics().current().detail());
            assertSame(result, guard.sample(3, START + 20, 20));
            var current = guard.diagnostics().current();
            assertEquals(1, current.previousValidSampleTick()); assertEquals(20, current.sampleDeltaNanos());
            assertEquals(2, current.tickDelta()); assertTrue(current.valid());
        }
    }

    @Test void negativeTickIsInvalidAndAnInitialInvalidSampleHasNoValidPredecessor() {
        var guard = new CombatThreats.HealthGuard();
        assertEquals("health_data_unknown", guard.sample(-1, START, 20).reason());
        assertEquals("invalid_tick", guard.diagnostics().trigger().detail());
        guard.sample(1, START + 1, 20);
        assertNull(guard.diagnostics().current().previousValidSampleTick());
        assertEquals("first_valid_sample", guard.diagnostics().current().detail());
        assertTrue(guard.diagnostics().latched()); assertFalse(guard.diagnostics().latchTriggeredNow());
    }

    @Test void lowHealthInclusiveThresholdAndUnchangedLatchedResult() {
        var guard = new CombatThreats.HealthGuard();
        assertFalse(guard.sample(0, START, 14.000001).interrupted());
        var result = guard.sample(1, START + 1, 14);
        assertEquals("low_health", result.reason()); assertTrue(result.known());
        assertEquals(14, result.health()); assertEquals(0, result.damageInWindow());
        assertEquals(1, result.sampleCount());
        var trigger = guard.diagnostics().trigger();
        assertSame(result, guard.sample(2, START + 2, 20));
        assertEquals(20, guard.diagnostics().current().observedHealth());
        assertEquals(14, guard.diagnostics().trigger().observedHealth());
        assertSame(trigger, guard.diagnostics().trigger());
        assertTrue(guard.diagnostics().latched()); assertFalse(guard.diagnostics().latchTriggeredNow());
    }

    @Test void cumulativeFourHpLossPreservesPolicyAndFirstTriggerMetrics() {
        var guard = new CombatThreats.HealthGuard();
        for (int i = 0; i < 4; i++) assertFalse(guard.sample(i, START + i * 50_000_000L, 20 - i).interrupted());
        var result = guard.sample(4, START + 200_000_000L, 16);
        assertEquals("rapid_health_loss", result.reason()); assertTrue(result.known());
        assertEquals(4, result.damageInWindow()); assertEquals(5, result.sampleCount());
        assertEquals(3, guard.diagnostics().trigger().previousValidSampleTick());
        assertEquals(50_000_000L, guard.diagnostics().trigger().sampleDeltaNanos());
        assertSame(result, guard.sample(5, START + 250_000_000L, 20));
        assertSame(result, guard.diagnostics().triggerResult());
        assertEquals(16, guard.diagnostics().trigger().observedHealth());
        assertEquals(20, guard.diagnostics().current().observedHealth());
    }

    @Test void healingStillDoesNotRefundLossAndSameTickSamplesRetainAllLoss() {
        var guard = initial();
        guard.sample(1, START + 1, 18); guard.sample(1, START + 2, 20);
        var result = guard.sample(1, START + 3, 18);
        assertEquals("rapid_health_loss", result.reason()); assertEquals(4, result.damageInWindow());
        assertEquals(1, result.sampleCount());
        assertEquals(1, guard.diagnostics().current().sampleDeltaNanos());
        assertEquals(3, guard.diagnostics().current().sameTickElapsedNanos());
    }

    @Test void lossComparisonRetainsOriginalEpsilon() {
        var guard = initial();
        assertFalse(guard.sample(2, START + 1, 16.000001).interrupted());
        guard = initial();
        assertEquals("rapid_health_loss", guard.sample(2, START + 1, 16.00000005).reason());
    }

    @Test void rollingLossExpiresOnlyStrictlyAfterOneSecond() {
        var guard = new CombatThreats.HealthGuard();
        guard.sample(0, 0, 20); guard.sample(1, 50_000_000L, 18);
        for (int i = 2; i <= 21; i++) {
            var result = guard.sample(i, i * 50_000_000L, 20);
            assertFalse(result.interrupted()); assertEquals(2, result.damageInWindow());
        }
        assertEquals(0, guard.sample(22, 1_050_000_001L, 20).damageInWindow());
    }

    @Test void gapKeepsPrecedenceOverLowHealthWithoutAttributingDamage() {
        var guard = initial();
        var result = guard.sample(2, START + GAP + 1, 10);
        assertEquals("health_observation_gap", result.reason()); assertFalse(result.known());
        assertEquals(0, result.damageInWindow()); assertEquals(1, result.sampleCount());
        var json = CombatHealthEvidence.snapshot(guard.diagnostics());
        assertTrue(json.getAsJsonObject("current_observation").get("low_health_observed").getAsBoolean());
        assertEquals("wall_gap", json.getAsJsonObject("latch_trigger").get("detail").getAsString());
    }

    @Test void eightValidSamplesThenTickNineGapRetainsBothTimelines() {
        var guard = new CombatThreats.HealthGuard();
        for (int tick = 1; tick <= 8; tick++)
            assertFalse(guard.sample(tick, START + (tick - 1) * 50_000_000L, 20).interrupted());
        long eighth = START + 350_000_000L;
        long ninth = eighth + GAP + 1;
        var result = guard.sample(9, ninth, 19);
        var atTrigger = guard.diagnostics();
        assertEquals("health_observation_gap", result.reason());
        assertEquals(8, result.sampleCount()); assertEquals(0, result.damageInWindow());
        assertEquals(9, atTrigger.trigger().sampleTick()); assertEquals(ninth, atTrigger.trigger().sampleNanos());
        assertEquals(8, atTrigger.trigger().previousValidSampleTick());
        assertEquals(eighth, atTrigger.trigger().previousValidSampleNanos());
        assertEquals(GAP + 1, atTrigger.trigger().sampleDeltaNanos()); assertEquals(1, atTrigger.trigger().tickDelta());
        assertEquals("wall_gap", atTrigger.trigger().detail());
        assertSame(result, guard.sample(10, ninth + 50_000_000L, 20));
        var after = guard.diagnostics();
        assertTrue(after.latched()); assertFalse(after.latchTriggeredNow());
        assertSame(atTrigger.trigger(), after.trigger()); assertSame(result, after.triggerResult());
        assertEquals(10, after.current().sampleTick()); assertEquals(9, after.current().previousValidSampleTick());
        assertEquals(ninth, after.current().previousValidSampleNanos());
        assertEquals(50_000_000L, after.current().sampleDeltaNanos());
        assertEquals("continuous_sample", after.current().detail()); assertTrue(after.current().continuous());
        assertEquals(9, atTrigger.current().sampleTick(), "Older immutable snapshots must not change");
    }

    @Test void laterGapDoesNotReplaceTheFirstLowHealthTrigger() {
        var guard = initial();
        var result = guard.sample(2, START + 1, 14);
        var trigger = guard.diagnostics().trigger();
        assertSame(result, guard.sample(6, START + GAP + 2, 20));
        assertSame(trigger, guard.diagnostics().trigger());
        assertEquals("wall_gap+tick_gap", guard.diagnostics().current().detail());
        assertEquals("low_health", guard.diagnostics().triggerResult().reason());
        assertEquals("continuous_sample", guard.diagnostics().trigger().detail());
    }

    @Test void laterFrozenTickTracksItsOwnStartWithoutChangingTrigger() {
        var guard = initial();
        var result = guard.sample(2, START + 1, 14);
        guard.sample(3, START + 2, 20);
        guard.sample(3, START + 100_000_002L, 20);
        assertSame(result, guard.sample(3, START + GAP + 3, 20));
        assertEquals("frozen_tick", guard.diagnostics().current().detail());
        assertEquals(GAP + 1, guard.diagnostics().current().sameTickElapsedNanos());
        assertEquals(2, guard.diagnostics().trigger().sampleTick());
    }

    @Test void historyOverflowRemainsLatchedAndReportedWithoutEviction() {
        var guard = new CombatThreats.HealthGuard();
        for (int i = 0; i < 24; i++) assertFalse(guard.sample(i, START + i, 20).interrupted());
        var result = guard.sample(24, START + 24, 20);
        assertEquals("health_history_overflow", result.reason()); assertEquals(24, result.sampleCount());
        assertFalse(result.known()); assertEquals(24, guard.diagnostics().trigger().sampleTick());
        assertSame(result, guard.sample(25, START + GAP + 25, 20));
    }

    @Test void jsonKeepsExactNanosecondsThresholdsAndExplicitCurrentVersusTriggerSemantics() {
        var guard = new CombatThreats.HealthGuard();
        long start = 9_007_199_254_740_999L;
        guard.sample(1, start, 20);
        guard.sample(2, start + GAP + 1, 19);
        var data = new JsonObject();
        data.addProperty("existing_field", "preserved");
        CombatHealthEvidence.append(data, guard);
        var triggerSnapshot = JsonParser.parseString(data.toString()).getAsJsonObject().getAsJsonObject("health_diagnostics");
        assertEquals("preserved", data.get("existing_field").getAsString());
        assertTrue(triggerSnapshot.get("latch_triggered_now").getAsBoolean());
        assertTrue(triggerSnapshot.get("policy_evaluated_this_sample").getAsBoolean());
        assertEquals(start + GAP + 1, triggerSnapshot.getAsJsonObject("latch_trigger").get("sample_ns").getAsLong());
        assertEquals(start, triggerSnapshot.getAsJsonObject("latch_trigger").get("previous_valid_sample_ns").getAsLong());
        guard.sample(3, start + GAP + 2, 20);
        var after = CombatHealthEvidence.snapshot(guard.diagnostics());
        assertTrue(after.get("latched").getAsBoolean()); assertFalse(after.get("latch_triggered_now").getAsBoolean());
        assertFalse(after.get("policy_evaluated_this_sample").getAsBoolean());
        assertEquals(3, after.getAsJsonObject("current_observation").get("sample_tick").getAsInt());
        assertEquals(2, after.getAsJsonObject("latch_trigger").get("sample_tick").getAsInt());
        assertEquals(19, after.getAsJsonObject("latch_trigger").get("observed_health").getAsDouble());
        assertEquals(20, after.getAsJsonObject("current_observation").get("observed_health").getAsDouble());
        assertEquals("health_observation_gap", after.getAsJsonObject("latch_trigger").get("reason").getAsString());
        assertEquals(GAP + 1, after.getAsJsonObject("latch_trigger").get("sample_delta_ns").getAsLong());
        assertEquals(1, after.getAsJsonObject("current_observation").get("sample_delta_ns").getAsLong());
        var thresholds = after.getAsJsonObject("thresholds");
        assertEquals(GAP, thresholds.get("max_sample_delta_ns").getAsLong());
        assertEquals(GAP, thresholds.get("max_same_tick_elapsed_ns").getAsLong());
        assertEquals(3, thresholds.get("max_tick_delta").getAsInt());
        assertEquals(14, thresholds.get("low_health_hp").getAsDouble());
        assertEquals(4, thresholds.get("max_rolling_loss_hp").getAsDouble());
        assertEquals(1_000_000_000L, thresholds.get("rolling_loss_window_ns").getAsLong());
        assertEquals(1e-7, thresholds.get("rolling_loss_epsilon_hp").getAsDouble());
    }

    @Test void jsonRepresentsMissingPreviousAndNonfiniteHealthAsNull() {
        var guard = new CombatThreats.HealthGuard();
        guard.sample(1, START, Double.NaN);
        var json = CombatHealthEvidence.snapshot(guard.diagnostics());
        JsonParser.parseString(json.toString());
        var current = json.getAsJsonObject("current_observation");
        assertTrue(current.get("observed_health").isJsonNull());
        assertTrue(current.get("previous_valid_sample_tick").isJsonNull());
        assertTrue(current.get("previous_valid_sample_ns").isJsonNull());
        assertTrue(current.get("sample_delta_ns").isJsonNull());
        assertTrue(current.get("tick_delta").isJsonNull());
    }

    private static CombatThreats.HealthGuard initial() {
        var guard = new CombatThreats.HealthGuard();
        assertFalse(guard.sample(1, START, 20).interrupted());
        return guard;
    }
}
