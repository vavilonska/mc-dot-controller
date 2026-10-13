package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Immutable rabbit evidence through the actual HTTP encoder, without loading Minecraft. */
class NativeRabbitSnapshotTest {
    private static final Object CONTEXT = new Object();
    private static final String UUID = "00000000-0000-4000-8000-000000000009";
    private NativeLivingSnapshot.Row row(String type, NativeLivingSnapshot.RabbitState rabbit) {
        return new NativeLivingSnapshot.Row(UUID, 9, type, 100, 1_000_000_000L, true, false, null, null, rabbit);
    }
    private NativeLivingSnapshot.Batch batch(NativeLivingSnapshot.Row row) {
        return new NativeLivingSnapshot.Batch(CONTEXT, new Object(), "minecraft:overworld", Map.of(UUID, row), true, 1, "observed");
    }
    private JsonObject facts(NativeLivingSnapshot.Row row, Object context, long tick, long nano) {
        return NativeLivingSnapshot.json(batch(row), context, "minecraft:overworld", "world", "player",
                UUID, 9, row.type(), tick, nano);
    }
    private JsonObject wire(JsonObject facts) throws Exception {
        JsonObject entity = new JsonObject(); entity.add("native_living", facts);
        JsonArray entities = new JsonArray(); entities.add(entity);
        JsonObject nearby = new JsonObject(); nearby.add("entities", entities);
        JsonObject root = new JsonObject(); root.add("nearby", nearby);
        JsonObject before = root.deepCopy();
        JsonObject parsed = JsonParser.parseString(BridgeJson.toJson(root)).getAsJsonObject()
                .getAsJsonObject("nearby").getAsJsonArray("entities").get(0).getAsJsonObject().getAsJsonObject("native_living");
        assertEquals(before, root); assertEquals(facts, parsed);
        return parsed;
    }
    @Test void allPinnedOrdinaryVariantsAndEvilPreserveDistinctTypedFactsOnHttpWire() throws Exception {
        for (int id : new int[]{0, 1, 2, 3, 4, 5, 99}) {
            var row = row("minecraft:rabbit", new NativeLivingSnapshot.RabbitState(id, id == 99, id != 99));
            JsonObject facts = wire(facts(row, CONTEXT, 101, 1_050_000_000L));
            assertTrue(facts.get("known").getAsBoolean()); assertTrue(facts.get("current_target").isJsonNull());
            assertFalse(facts.has("bee")); assertEquals(3, facts.getAsJsonObject("rabbit").size());
            assertEquals(id, facts.getAsJsonObject("rabbit").get("variant_id").getAsInt());
            assertEquals(id == 99, facts.getAsJsonObject("rabbit").get("killer_bunny").getAsBoolean());
            assertEquals(id != 99, facts.getAsJsonObject("rabbit").get("passive_goals_verified").getAsBoolean());
            assertEquals(100, facts.get("source_tick").getAsLong()); assertEquals(101, facts.get("sample_tick").getAsLong());
        }
    }
    @Test void retainedCombatGoalsAreNotHiddenByOrdinaryVariant() throws Exception {
        var row = row("minecraft:rabbit", new NativeLivingSnapshot.RabbitState(0, false, false));
        JsonObject facts = wire(facts(row, CONTEXT, 100, 1_000_000_000L));
        assertFalse(facts.getAsJsonObject("rabbit").get("passive_goals_verified").getAsBoolean());
        assertFalse(facts.getAsJsonObject("rabbit").get("killer_bunny").getAsBoolean());
    }
    @Test void absentRabbitProofIsNeverManufacturedForRabbitOrOtherMobs() throws Exception {
        for (String type : new String[]{"minecraft:rabbit", "minecraft:bee", "minecraft:cow"}) {
            JsonObject facts = wire(facts(row(type, null), CONTEXT, 100, 1_000_000_000L));
            assertTrue(facts.get("known").getAsBoolean()); assertFalse(facts.has("rabbit"));
            assertTrue(facts.get("current_target").isJsonNull());
        }
    }
    @Test void malformedVariantIdAndInconsistentKillerFlagInvalidateEvidence() throws Exception {
        for (var state : new NativeLivingSnapshot.RabbitState[]{
                new NativeLivingSnapshot.RabbitState(-1, false, true), new NativeLivingSnapshot.RabbitState(6, false, true),
                new NativeLivingSnapshot.RabbitState(100, false, true), new NativeLivingSnapshot.RabbitState(99, false, true),
                new NativeLivingSnapshot.RabbitState(0, true, true)}) {
            JsonObject facts = wire(facts(row("minecraft:rabbit", state), CONTEXT, 100, 1_000_000_000L));
            assertFalse(facts.get("known").getAsBoolean()); assertFalse(facts.has("rabbit"));
            assertEquals("invalid_rabbit_variant", facts.get("reason").getAsString());
        }
    }
    @Test void rabbitProofCannotAttachToAnotherEntityType() throws Exception {
        JsonObject facts = wire(facts(row("minecraft:cow", new NativeLivingSnapshot.RabbitState(0, false, true)), CONTEXT, 100, 1_000_000_000L));
        assertFalse(facts.get("known").getAsBoolean()); assertFalse(facts.has("rabbit"));
    }
    @Test void staleTickChangedContextAndPartialCoverageDiscardRabbitProof() throws Exception {
        var row = row("minecraft:rabbit", new NativeLivingSnapshot.RabbitState(0, false, true));
        for (JsonObject facts : new JsonObject[]{facts(row, new Object(), 100, 1_000_000_000L),
                facts(row, CONTEXT, 106, 1_000_000_000L), facts(row, CONTEXT, 100, 1_250_000_001L),
                NativeLivingSnapshot.json(new NativeLivingSnapshot.Batch(CONTEXT, new Object(), "minecraft:overworld", Map.of(UUID, row), false, 4097, "inspection_limit"),
                        CONTEXT, "minecraft:overworld", "world", "player", UUID, 9, row.type(), 100, 1_000_000_000L)}) {
            JsonObject parsed = wire(facts); assertFalse(parsed.get("known").getAsBoolean());
            assertFalse(parsed.has("rabbit")); assertFalse(parsed.has("current_target"));
        }
    }
}
