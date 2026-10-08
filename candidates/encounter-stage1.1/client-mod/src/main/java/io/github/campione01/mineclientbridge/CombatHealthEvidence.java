package io.github.campione01.mineclientbridge;

import com.google.gson.JsonNull;
import com.google.gson.JsonObject;

/** Exact client-observation evidence. No inference about a network or damage source. */
final class CombatHealthEvidence {
    private CombatHealthEvidence() { }

    /** Adds one self-contained snapshot; existing health/result fields keep their old semantics. */
    static void append(JsonObject evidence, CombatThreats.HealthGuard guard) {
        evidence.add("health_diagnostics", snapshot(guard == null ? null : guard.diagnostics()));
    }

    static JsonObject snapshot(CombatThreats.HealthGuard.Diagnostics diagnostics) {
        JsonObject data = new JsonObject();
        data.addProperty("scope", "client_health_observation_only");
        data.addProperty("previous_valid_sample_semantics",
                "latest_finite_nonnegative_health_and_monotonic_tick_and_ns_observation_including_gap_samples");
        data.addProperty("latch_semantics", "first_interruption_is_irrevocable_current_observation_does_not_clear_it");
        data.addProperty("sampled", diagnostics != null);
        JsonObject thresholds = new JsonObject();
        thresholds.addProperty("max_sample_delta_ns", CombatThreats.HealthGuard.MAX_GAP_NANOS);
        thresholds.addProperty("max_same_tick_elapsed_ns", CombatThreats.HealthGuard.MAX_GAP_NANOS);
        thresholds.addProperty("max_tick_delta", CombatThreats.HealthGuard.MAX_TICK_GAP);
        thresholds.addProperty("gap_comparison", "strictly_greater_than");
        thresholds.addProperty("low_health_hp", CombatThreats.HealthGuard.LOW_HEALTH);
        thresholds.addProperty("low_health_comparison", "less_than_or_equal");
        thresholds.addProperty("rolling_loss_window_ns", CombatThreats.HealthGuard.WINDOW_NANOS);
        thresholds.addProperty("max_rolling_loss_hp", CombatThreats.HealthGuard.MAX_ROLLING_LOSS);
        thresholds.addProperty("rolling_loss_comparison", "loss_plus_epsilon_greater_than_or_equal");
        thresholds.addProperty("rolling_loss_epsilon_hp", CombatThreats.HealthGuard.LOSS_EPSILON);
        data.add("thresholds", thresholds);
        if (diagnostics == null) {
            data.add("current_observation", JsonNull.INSTANCE);
            data.add("latch_trigger", JsonNull.INSTANCE);
            return data;
        }
        data.addProperty("latched", diagnostics.latched());
        data.addProperty("latch_triggered_now", diagnostics.latchTriggeredNow());
        data.addProperty("policy_evaluated_this_sample", !diagnostics.latched() || diagnostics.latchTriggeredNow());
        data.add("current_observation", observation(diagnostics.current()));
        if (diagnostics.trigger() == null) data.add("latch_trigger", JsonNull.INSTANCE);
        else {
            JsonObject trigger = observation(diagnostics.trigger());
            CombatThreats.HealthGuard.Result result = diagnostics.triggerResult();
            trigger.addProperty("reason", result.reason());
            trigger.addProperty("known", result.known());
            trigger.addProperty("rolling_loss_1s", result.damageInWindow());
            trigger.addProperty("sample_count", result.sampleCount());
            data.add("latch_trigger", trigger);
        }
        return data;
    }

    private static JsonObject observation(CombatThreats.HealthGuard.SampleDiagnostic diagnostic) {
        JsonObject data = new JsonObject();
        data.addProperty("sample_tick", diagnostic.sampleTick());
        data.addProperty("sample_ns", diagnostic.sampleNanos());
        if (Double.isFinite(diagnostic.observedHealth())) data.addProperty("observed_health", diagnostic.observedHealth());
        else data.add("observed_health", JsonNull.INSTANCE);
        data.addProperty("previous_valid_sample_tick", diagnostic.previousValidSampleTick());
        data.addProperty("previous_valid_sample_ns", diagnostic.previousValidSampleNanos());
        data.addProperty("sample_delta_ns", diagnostic.sampleDeltaNanos());
        data.addProperty("tick_delta", diagnostic.tickDelta());
        data.addProperty("same_tick_elapsed_ns", diagnostic.sameTickElapsedNanos());
        data.addProperty("data_valid", diagnostic.dataValid());
        data.addProperty("clock_valid", diagnostic.clockValid());
        data.addProperty("continuity_observed", diagnostic.continuous());
        data.addProperty("wall_gap", diagnostic.wallGap());
        data.addProperty("tick_gap", diagnostic.tickGap());
        data.addProperty("frozen_tick", diagnostic.frozenTick());
        data.addProperty("low_health_observed", diagnostic.dataValid()
                && diagnostic.observedHealth() <= CombatThreats.HealthGuard.LOW_HEALTH);
        data.addProperty("detail", diagnostic.detail());
        return data;
    }
}
