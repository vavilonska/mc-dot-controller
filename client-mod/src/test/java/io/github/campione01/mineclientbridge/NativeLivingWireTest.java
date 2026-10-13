package io.github.campione01.mineclientbridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Native snapshot -> exact HTTP encoder -> parser; no substitute Gson configuration. */
class NativeLivingWireTest {
    private static final Gson LEGACY = new GsonBuilder().disableHtmlEscaping().create();
    private static final Object CONTEXT = new Object();
    private static final String UUID = "00000000-0000-4000-8000-000000000009";
    private static final String TARGET = "00000000-0000-4000-8000-000000000008";

    private JsonObject facts(boolean hasSource, boolean targeted, boolean persistent, long sampleNano) {
        var row = new NativeLivingSnapshot.Row(UUID, 9, "minecraft:bee", 100, 1_000_000_000L,
                true, false, targeted ? new NativeLivingSnapshot.Target(TARGET, 8, "minecraft:player") : null,
                new NativeLivingSnapshot.BeeState(false, 0, persistent ? TARGET : null));
        var batch = hasSource ? new NativeLivingSnapshot.Batch(CONTEXT, new Object(), "minecraft:overworld",
                Map.of(UUID, row), true, 1, "observed") : null;
        return NativeLivingSnapshot.json(batch, CONTEXT, "minecraft:overworld", "world", "player",
                UUID, 9, "minecraft:bee", 100, sampleNano);
    }
    private JsonObject calm() { return facts(true, false, false, 1_050_000_000L); }
    private JsonObject envelope(JsonObject facts) {
        JsonObject row = new JsonObject(); row.addProperty("entity_id", 9); row.addProperty("uuid", UUID);
        row.add("native_living", facts);
        JsonArray rows = new JsonArray(); rows.add(row);
        JsonObject nearby = new JsonObject(); nearby.addProperty("radius", 48);
        nearby.addProperty("total", 1); nearby.addProperty("returned", 1); nearby.addProperty("truncated", false);
        nearby.add("entities", rows);
        JsonObject root = new JsonObject(); root.add("nearby", nearby); return root;
    }
    private JsonObject roundTrip(JsonObject root) throws Exception {
        JsonObject before = root.deepCopy();
        String wire = BridgeJson.toJson(root);
        JsonObject parsed = JsonParser.parseString(wire).getAsJsonObject();
        assertEquals(before, root, "The HTTP encoder must not mutate any input element");
        assertEquals(wire, BridgeJson.toJson(root), "Repeated encoding must be stable");
        return parsed;
    }
    private JsonArray rows(JsonObject root) { return root.getAsJsonObject("nearby").getAsJsonArray("entities"); }
    private JsonObject nativeFacts(JsonObject root) { return rows(root).get(0).getAsJsonObject().getAsJsonObject("native_living"); }
    private void assertKnownNulls(JsonObject facts) {
        assertTrue(facts.get("known").getAsBoolean());
        assertTrue(facts.has("current_target"), "A known absent target must be present as JSON null on the HTTP wire");
        assertTrue(facts.get("current_target").isJsonNull());
        assertTrue(facts.getAsJsonObject("bee").has("persistent_anger_target_uuid"));
        assertTrue(facts.getAsJsonObject("bee").get("persistent_anger_target_uuid").isJsonNull());
    }

    @Test void actualKnownNoTargetSnapshotKeepsBothExplicitNullsOnHttpWire() throws Exception {
        JsonObject input = calm();
        assertKnownNulls(nativeFacts(roundTrip(envelope(input))));
    }

    @Test void actualCurrentAndPersistentTargetsRetainTheirValuesIndependently() throws Exception {
        for (boolean target : new boolean[]{false, true}) for (boolean persistent : new boolean[]{false, true}) {
            JsonObject input = facts(true, target, persistent, 1_050_000_000L);
            JsonObject result = nativeFacts(roundTrip(envelope(input)));
            assertEquals(input, result);
            if (target) {
                JsonObject observed = result.getAsJsonObject("current_target");
                assertEquals(TARGET, observed.get("uuid").getAsString());
                assertEquals(8, observed.get("entity_id").getAsInt());
                assertEquals("minecraft:player", observed.get("type").getAsString());
            }
            if (persistent) assertEquals(TARGET, result.getAsJsonObject("bee").get("persistent_anger_target_uuid").getAsString());
        }
    }

    @Test void unavailableAndStaleSnapshotsNeverAcquireAbsentFields() throws Exception {
        for (JsonObject input : new JsonObject[]{facts(false, false, false, 1_050_000_000L),
                facts(true, false, false, 1_250_000_001L)}) {
            JsonObject result = nativeFacts(roundTrip(envelope(input)));
            assertEquals(input, result); assertFalse(result.get("known").getAsBoolean());
            assertFalse(result.has("current_target")); assertFalse(result.has("bee"));
            assertFalse(result.has("aggressive"));
        }
    }

    @Test void missingContractMembersAreNeverManufactured() throws Exception {
        JsonObject input = calm(); input.remove("current_target");
        input.getAsJsonObject("bee").remove("persistent_anger_target_uuid");
        JsonObject result = nativeFacts(roundTrip(envelope(input)));
        assertFalse(result.has("current_target"));
        assertFalse(result.getAsJsonObject("bee").has("persistent_anger_target_uuid"));
        JsonObject empty = envelope(new JsonObject());
        assertEquals(0, nativeFacts(roundTrip(empty)).size());
    }

    @Test void unrelatedNullsAreOmittedAtEveryTraversedDepthIncludingActualTargetObject() throws Exception {
        JsonObject root = envelope(facts(true, true, true, 1_050_000_000L));
        JsonObject nearby = root.getAsJsonObject("nearby"), row = rows(root).get(0).getAsJsonObject();
        JsonObject facts = nativeFacts(root), bee = facts.getAsJsonObject("bee"), target = facts.getAsJsonObject("current_target");
        for (JsonObject object : new JsonObject[]{root, nearby, row, facts, bee, target}) object.add("legacy_null", JsonNull.INSTANCE);
        facts.add("unrelated_object", JsonParser.parseString("{\"current_target\":null,\"nested_null\":null}"));
        JsonObject result = roundTrip(root), decoded = nativeFacts(result);
        for (JsonObject object : new JsonObject[]{result, result.getAsJsonObject("nearby"), rows(result).get(0).getAsJsonObject(),
                decoded, decoded.getAsJsonObject("bee"), decoded.getAsJsonObject("current_target")}) assertFalse(object.has("legacy_null"));
        assertEquals(0, decoded.getAsJsonObject("unrelated_object").size());
    }

    @Test void heterogeneousArrayKeepsOrderShapeNonMobRowsAndOnlyDirectRowContracts() throws Exception {
        JsonObject root = envelope(calm()); JsonArray rows = rows(root);
        rows.add(JsonNull.INSTANCE); rows.add("text"); rows.add(42); rows.add(true);
        rows.add(JsonParser.parseString("{\"entity_id\":2,\"type\":\"minecraft:boat\",\"legacy_null\":null}"));
        JsonObject second = rows.get(0).getAsJsonObject().deepCopy(); second.addProperty("entity_id", 10); rows.add(second);
        JsonArray nested = new JsonArray(); nested.add(rows.get(0).deepCopy()); rows.add(nested);
        JsonObject before = root.deepCopy(); JsonArray result = rows(roundTrip(root));
        assertEquals(8, result.size()); assertEquals(before, root);
        assertTrue(result.get(1).isJsonNull()); assertEquals("text", result.get(2).getAsString());
        assertEquals(42, result.get(3).getAsInt()); assertTrue(result.get(4).getAsBoolean());
        assertEquals("minecraft:boat", result.get(5).getAsJsonObject().get("type").getAsString());
        assertFalse(result.get(5).getAsJsonObject().has("native_living")); assertFalse(result.get(5).getAsJsonObject().has("legacy_null"));
        assertKnownNulls(result.get(0).getAsJsonObject().getAsJsonObject("native_living"));
        assertKnownNulls(result.get(6).getAsJsonObject().getAsJsonObject("native_living"));
        assertFalse(result.get(7).getAsJsonArray().get(0).getAsJsonObject().getAsJsonObject("native_living").has("current_target"));
    }

    @Test void identicalFieldNamesOutsideExactRootArrayPathRetainLegacyOmission() throws Exception {
        for (String source : new String[]{
                "{\"native_living\":{\"current_target\":null,\"bee\":{\"persistent_anger_target_uuid\":null}}}",
                "{\"nearby\":{\"entities\":{\"native_living\":{\"current_target\":null}}}}",
                "{\"nearby\":{\"entities\":null,\"current_target\":null}}",
                "{\"nearby\":{\"entities\":[{\"current_target\":null,\"native_living\":null,\"bee\":{\"persistent_anger_target_uuid\":null}}]}}",
                "{\"nearby\":{\"entities\":[{\"native_living\":{\"bee\":null}}]}}",
                "{\"result\":{\"nearby\":{\"entities\":[{\"native_living\":{\"current_target\":null}}]}}}",
                "{\"nearby\":{\"other\":[{\"native_living\":{\"current_target\":null}}]}}"}) {
            JsonObject root = JsonParser.parseString(source).getAsJsonObject();
            assertEquals(LEGACY.toJson(root), BridgeJson.toJson(root)); roundTrip(root);
        }
    }
}
