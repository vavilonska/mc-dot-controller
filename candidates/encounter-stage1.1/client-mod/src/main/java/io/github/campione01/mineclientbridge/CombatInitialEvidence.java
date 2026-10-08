package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;

/** Native initial receipt fields shared with cross-language emitted-wire regressions. */
final class CombatInitialEvidence {
    /** Shared native receipt initialization; pure so generated-wire regression uses production fields. */
    static void initialize(BoundedCombatRequest request,JsonObject evidence,float lastPlayerHealth,float lastTargetHealth) {
        evidence.addProperty("combat_loop_schema_version", 1);
        evidence.addProperty("pursuit_diagnostics_schema_version", 1);
        evidence.addProperty("threat_safety_schema_version", 2);
        evidence.addProperty("retreat_window_schema_version", 2);
        evidence.addProperty("local_detour_schema_version", 1);
        evidence.addProperty("risk_remaining", true);
        evidence.addProperty("safety_assured", false);
        evidence.addProperty("attack_completed", false);
        evidence.addProperty("damage_attribution", "unknown");
        evidence.addProperty("target_uuid", request.targetUuid());
        evidence.addProperty("target_entity_id", request.targetId());
        evidence.addProperty("target_type", request.targetType());
        number(evidence,"initial_player_health", lastPlayerHealth);
        number(evidence,"initial_target_health", lastTargetHealth);
        evidence.addProperty("hits_confirmed", false);
        evidence.addProperty("server_confirmed", false);
        evidence.addProperty("cadence_source", "live_client_attack_strength");
        evidence.addProperty("attack_dispatches", 0);
        evidence.addProperty("target_dead_observed", false);
    }

    private static void number(JsonObject data,String key,double value) { data.addProperty(key,Double.isFinite(value)?value:null); }
    private CombatInitialEvidence() {}
}
