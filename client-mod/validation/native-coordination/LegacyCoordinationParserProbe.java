package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

/** Executes the frozen root parser, not a model or copied parser implementation. */
public final class LegacyCoordinationParserProbe {
    public static void main(String[] args) {
        JsonObject request = JsonParser.parseString("""
            {"action_id":"coordination-baseline-malformed","action":"follow_path","timeout_ms":1000,
             "waypoints":[{"x":1.5,"y":64,"z":0.5}],
             "expected_origin":{"x":0.5,"y":64,"z":0.5},"expected_navigation_epoch":0,
             "expected_world_generation":"world","expected_player_uuid":"player","expected_action_session":"session",
             "coordination_step":"malformed-not-an-object"}
            """).getAsJsonObject();
        ClientActionRequest parsed = ClientActionRequest.parse(request);
        if (!parsed.action().equals("follow_path") || !parsed.original().equals(request))
            throw new AssertionError("Baseline fixture did not reach the original follow_path contract");
        System.out.println("BASELINE_REQUEST=" + request);
        System.out.println("BASELINE_ACTUAL=accepted_follow_path_with_malformed_coordination_step");
        throw new AssertionError("EXPECTED_RED: frozen root parser accepted malformed coordination_step");
    }
}
