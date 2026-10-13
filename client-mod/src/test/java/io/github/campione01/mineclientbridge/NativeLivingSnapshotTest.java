package io.github.campione01.mineclientbridge;

import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class NativeLivingSnapshotTest {
    private final Object context = new Object();
    private NativeLivingSnapshot.Row row(long tick, long nano) {
        return new NativeLivingSnapshot.Row("bee-uuid", 7, "minecraft:bee", tick, nano, true, false, null,
                new NativeLivingSnapshot.BeeState(false, 0, null));
    }
    private NativeLivingSnapshot.Batch batch(NativeLivingSnapshot.Row row) {
        return new NativeLivingSnapshot.Batch(context, new Object(), "minecraft:overworld", Map.of("bee-uuid", row), true, 12, "observed");
    }
    private String reject(NativeLivingSnapshot.Batch b, long tick, long nano) {
        return NativeLivingSnapshot.rejection(b, context, "minecraft:overworld", "bee-uuid", 7, "minecraft:bee", tick, nano);
    }
    @Test void exactFreshBindingsExposeTypedNativeValues() {
        var out = NativeLivingSnapshot.json(batch(row(100, 1_000_000_000L)), context, "minecraft:overworld", "world", "player",
                "bee-uuid", 7, "minecraft:bee", 101, 1_050_000_000L);
        assertTrue(out.get("known").getAsBoolean()); assertTrue(out.get("current_target_known").getAsBoolean());
        assertTrue(out.get("coverage_complete").getAsBoolean()); assertTrue(out.get("alive").getAsBoolean());
        assertEquals("integrated_server_tick", out.get("source").getAsString());
        assertTrue(out.get("source_nano").getAsJsonPrimitive().isString());
        assertEquals(50.0, out.get("sample_age_ms").getAsDouble());
        assertFalse(out.get("aggressive").getAsBoolean()); assertTrue(out.get("current_target").isJsonNull());
        assertFalse(out.getAsJsonObject("bee").get("angry").getAsBoolean());
        assertTrue(out.getAsJsonObject("bee").get("persistent_anger_target_uuid").isJsonNull());
    }
    @Test void absentSourceNeverSerializesNullTargetAsKnownCalm() {
        var out = NativeLivingSnapshot.json(null, context, "minecraft:overworld", "world", "player", "bee-uuid", 7, "minecraft:bee", 1, 1);
        assertFalse(out.get("known").getAsBoolean()); assertFalse(out.get("current_target_known").getAsBoolean());
        assertFalse(out.has("current_target")); assertFalse(out.has("aggressive")); assertFalse(out.has("bee"));
        assertEquals("unavailable", out.get("source").getAsString());
    }
    @Test void exactAgeAndTickBoundsFailClosedOutsideTheirEdges() {
        var b = batch(row(100, 1_000_000_000L));
        assertNull(reject(b, 95, 1_250_000_000L)); assertNull(reject(b, 105, 1_000_000_000L));
        assertEquals("source_tick_mismatch", reject(b, 94, 1_050_000_000L));
        assertEquals("source_tick_mismatch", reject(b, 106, 1_050_000_000L));
        assertEquals("source_expired", reject(b, 100, 1_250_000_001L));
        assertEquals("source_expired", reject(b, 100, 999_999_999L));
    }
    @Test void contextDimensionAndExactEntityBindingAreMandatory() {
        var b = batch(row(100, 100));
        assertEquals("context_unavailable", NativeLivingSnapshot.rejection(b, new Object(), "minecraft:overworld", "bee-uuid", 7, "minecraft:bee", 100, 100));
        assertEquals("dimension_changed", NativeLivingSnapshot.rejection(b, context, "minecraft:the_nether", "bee-uuid", 7, "minecraft:bee", 100, 100));
        assertEquals("entity_not_observed", NativeLivingSnapshot.rejection(b, context, "minecraft:overworld", "another", 7, "minecraft:bee", 100, 100));
        assertEquals("entity_identity_changed", NativeLivingSnapshot.rejection(b, context, "minecraft:overworld", "bee-uuid", 8, "minecraft:bee", 100, 100));
        assertEquals("entity_identity_changed", NativeLivingSnapshot.rejection(b, context, "minecraft:overworld", "bee-uuid", 7, "minecraft:sheep", 100, 100));
    }
    @Test void partialCoverageInvalidatesEvenAnExistingRow() {
        var b = new NativeLivingSnapshot.Batch(context, new Object(), "minecraft:overworld", Map.of("bee-uuid", row(100, 100)), false, 4097, "inspection_limit");
        assertEquals("inspection_limit", reject(b, 100, 100));
    }
    @Test void publicationCopiesInputMapAndExposesNoMutableMap() {
        var rows = new HashMap<String, NativeLivingSnapshot.Row>(); rows.put("bee-uuid", row(100, 100));
        var b = new NativeLivingSnapshot.Batch(context, new Object(), "minecraft:overworld", rows, true, 1, "observed");
        rows.clear(); assertEquals(1, b.rows().size()); assertThrows(UnsupportedOperationException.class, () -> b.rows().clear());
    }
    @Test void aggressiveAndTargetedFactsAreReportedRatherThanHidden() {
        var target = new NativeLivingSnapshot.Target("target-uuid", 22, "minecraft:player");
        var r = new NativeLivingSnapshot.Row("bee-uuid", 7, "minecraft:bee", 100, 100, true, true, target,
                new NativeLivingSnapshot.BeeState(true, 99, "target-uuid"));
        var out = NativeLivingSnapshot.json(batch(r), context, "minecraft:overworld", "world", "player", "bee-uuid", 7, "minecraft:bee", 100, 100);
        assertTrue(out.get("known").getAsBoolean()); assertTrue(out.get("aggressive").getAsBoolean());
        assertEquals("target-uuid", out.getAsJsonObject("current_target").get("uuid").getAsString());
        assertEquals(99, out.getAsJsonObject("bee").get("remaining_anger_ticks").getAsInt());
    }
    @Test void invalidNegativeAngerIsUnknown() {
        var r = new NativeLivingSnapshot.Row("bee-uuid", 7, "minecraft:bee", 100, 100, true, false, null,
                new NativeLivingSnapshot.BeeState(false, -1, null));
        assertEquals("invalid_anger_time", reject(batch(r), 100, 100));
    }
    @Test void oldReadCannotPublishAfterUnloadOrSessionReplacement() {
        var store = new NativeLivingSnapshot.Store(); store.replace(context);
        var old = batch(row(100, 100)); assertTrue(store.publish(old));
        store.clear(); assertNull(store.context()); assertNull(store.snapshot()); assertFalse(store.publish(old));
        Object next = new Object(); store.replace(next); assertFalse(store.publish(old)); assertNull(store.snapshot());
        var fresh = new NativeLivingSnapshot.Batch(next, new Object(), "minecraft:overworld", Map.of(), true, 0, "observed");
        assertTrue(store.publish(fresh)); assertSame(fresh, store.snapshot());
    }
    @Test void discardedPrivateServerPublicationBecomesUnknownImmediately() {
        var store = new NativeLivingSnapshot.Store(); store.replace(context); assertTrue(store.publish(batch(row(100, 100))));
        store.discard(context); assertNull(store.snapshot()); assertNull(store.context());
        assertFalse(store.publish(batch(row(100, 100))), "A pre-discard frame cannot be republished");
        assertEquals("context_unavailable", reject(store.snapshot(), 100, 100));
    }
    @Test void replacingAnySessionTokenInvalidatesItsPublication() {
        var store = new NativeLivingSnapshot.Store(); store.replace(context); var old = batch(row(100, 100));
        assertTrue(store.publish(old));
        for (String reason : new String[]{"player", "client_level", "server", "dimension"}) {
            Object next = new Object(); store.replace(next); assertNull(store.snapshot(), reason); assertFalse(store.publish(old), reason);
        }
    }
}
