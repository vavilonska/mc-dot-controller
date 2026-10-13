package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.*;
import org.junit.jupiter.api.Test;

/** Codec-only preparatory contracts; these do not enable encounter or pause actions. */
class BridgeJsonNullableContractTest {
    private static final Gson LEGACY = new GsonBuilder().disableHtmlEscaping().create();
    private JsonObject parse(String value) { return JsonParser.parseString(value).getAsJsonObject(); }
    private JsonObject roundTrip(JsonObject root) throws Exception {
        JsonObject before = root.deepCopy();
        JsonObject result = parse(BridgeJson.toJson(root));
        assertEquals(before, root, "Encoding must not mutate its input");
        return result;
    }

    @Test void encounterOutcomePreservesExplicitUnknownForEveryTerminalKind() throws Exception {
        for (String status : new String[]{"running", "failed", "cancelled", "succeeded"}) {
            JsonObject root = parse("{\"result\":{\"combat\":{\"encounter\":{\"outcome_scope\":null,\"legacy_null\":null},\"legacy_null\":null},\"legacy_null\":null}}");
            root.addProperty("status", status);
            JsonObject original = root.getAsJsonObject("result").getAsJsonObject("combat").getAsJsonObject("encounter");
            if (status.equals("succeeded")) original.addProperty("outcome_scope", "local_clearance");
            JsonObject result = roundTrip(root).getAsJsonObject("result");
            JsonObject combat = result.getAsJsonObject("combat"), encounter = combat.getAsJsonObject("encounter");
            assertEquals(original.get("outcome_scope"), encounter.get("outcome_scope"));
            assertFalse(result.has("legacy_null")); assertFalse(combat.has("legacy_null"));
            assertFalse(encounter.has("legacy_null"));
        }
    }

    @Test void missingOutcomeAndUnrelatedPathsRetainLegacyOmission() throws Exception {
        for (String json : new String[]{"{\"result\":null}", "{\"result\":{\"combat\":null}}",
                "{\"result\":{\"combat\":{\"encounter\":null}}}",
                "{\"outcome_scope\":null,\"result\":{\"outcome_scope\":null,\"combat\":{\"outcome_scope\":null,\"encounter\":{\"schema_version\":1}}}}"}) {
            JsonObject root = parse(json);
            assertEquals(LEGACY.toJson(root), BridgeJson.toJson(root));
        }
    }

    @Test void interruptionOnlyKeepsDocumentedUnknownClockAnchors() throws Exception {
        JsonObject root = parse("{\"result\":{\"combat\":{\"encounter\":{\"callback_interruption\":{\"last_tick_nanos\":null,\"snapshot_captured_nanos\":null,\"previous_callback_nanos\":null,\"previous_callback_phase\":null,\"callback_interval_nanos\":null,\"legacy_null\":null,\"evaluated_tick\":-1}}}}}");
        JsonObject callback = roundTrip(root).getAsJsonObject("result").getAsJsonObject("combat")
                .getAsJsonObject("encounter").getAsJsonObject("callback_interruption");
        for (String key : new String[]{"last_tick_nanos", "snapshot_captured_nanos", "previous_callback_nanos",
                "previous_callback_phase", "callback_interval_nanos"}) assertTrue(callback.get(key).isJsonNull());
        assertFalse(callback.has("legacy_null")); assertEquals(-1, callback.get("evaluated_tick").getAsInt());
    }

    @Test void terminalPauseOnlyKeepsItsThreeUnknownObservations() throws Exception {
        JsonObject root = parse("{\"reason\":\"original_failure\",\"result\":{\"legacy_null\":null,\"encounter_terminal_pause\":{\"pause_screen_installed\":null,\"already_pause_screen\":null,\"client_paused_observed\":null,\"legacy_null\":null}}}");
        JsonObject result = roundTrip(root);
        JsonObject pause = result.getAsJsonObject("result").getAsJsonObject("encounter_terminal_pause");
        for (String key : new String[]{"pause_screen_installed", "already_pause_screen", "client_paused_observed"})
            assertTrue(pause.get(key).isJsonNull());
        assertEquals(3, pause.size()); assertEquals("original_failure", result.get("reason").getAsString());
        assertFalse(result.getAsJsonObject("result").has("legacy_null"));
    }

    @Test void missingActionPauseEnvelopeKeepsNullOnlyWithExactDiscriminator() throws Exception {
        JsonObject root = parse("{\"pause_schema_version\":1,\"action\":\"ensure_paused\",\"client_action\":null,\"input_release_confirmed\":null,\"legacy_null\":null}");
        JsonObject decoded = roundTrip(root);
        assertTrue(decoded.get("client_action").isJsonNull());
        assertTrue(decoded.get("input_release_confirmed").isJsonNull()); assertFalse(decoded.has("legacy_null"));
        for (String value : new String[]{"null", "true", "\"1\"", "2", "{}", "[]"}) {
            JsonObject bad = root.deepCopy(); bad.add("pause_schema_version", JsonParser.parseString(value));
            assertFalse(roundTrip(bad).has("client_action")); assertFalse(roundTrip(bad).has("input_release_confirmed"));
        }
        root.remove("pause_schema_version"); assertFalse(roundTrip(root).has("client_action"));
    }

    @Test void missingFieldsAreNeverInventedOrAppliedToOtherPaths() throws Exception {
        JsonObject root = parse("{\"pause_schema_version\":1,\"action\":\"ensure_paused\",\"other\":{\"client_action\":null},\"result\":{\"encounter_terminal_pause\":{},\"other\":{\"client_paused_observed\":null}}}");
        JsonObject result = roundTrip(root);
        assertFalse(result.has("client_action")); assertFalse(result.has("input_release_confirmed"));
        assertEquals(0, result.getAsJsonObject("other").size());
        assertEquals(0, result.getAsJsonObject("result").getAsJsonObject("encounter_terminal_pause").size());
        assertEquals(0, result.getAsJsonObject("result").getAsJsonObject("other").size());
    }
}
