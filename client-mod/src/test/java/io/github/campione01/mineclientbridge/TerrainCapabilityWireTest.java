package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.*;
import com.sun.net.httpserver.HttpExchange;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;

/** Actual production scan, reader assembly and HTTP codec. Cells are explicitly synthetic. */
class TerrainCapabilityWireTest {
    static JsonObject ordinaryCell() {
        return JsonParser.parseString("""
                {"known":true,"block_light":0,"sky_light":15,"id":"minecraft:stone",
                 "id_truncated":false,"air":false,"properties":{},"properties_truncated":false,
                 "fluid":"minecraft:empty","fluid_truncated":false,"fluid_source":false,
                 "hazards":[],"hazards_exhaustive":false,"collision_known":true,
                 "collision_empty":false,"full_top_support":true,"collision_bounds":[0,0,0,1,1,1]}
                """).getAsJsonObject();
    }
    static TerrainScan.Source<JsonObject> source(JsonObject data) {
        return new TerrainScan.Source<>() {
            public TerrainScan.Availability availability(int x, int y, int z) { return TerrainScan.Availability.LOADED; }
            public JsonObject readLoaded(int x, int y, int z) { return data; }
            public int encodedCellBytes(TerrainScan.Cell<JsonObject> cell) { return TerrainReader.encodedCellBytes(cell); }
        };
    }
    static BridgeReadResponseTest.Exchange http(JsonObject body) throws Exception {
        var exchange = new BridgeReadResponseTest.Exchange();
        var method = BridgeServer.class.getDeclaredMethod("respondJson", HttpExchange.class, int.class, JsonObject.class);
        method.setAccessible(true); method.invoke(null, exchange, 200, body);
        return exchange;
    }
    static JsonObject pageJson(TerrainScan.Page<JsonObject> page) throws Exception {
        var method = BridgeServer.class.getDeclaredMethod("protocolOk"); method.setAccessible(true);
        var json = (JsonObject) method.invoke(null);
        var terrain = TerrainReader.pageJson(page, "11111111-2222-4333-8444-555555555555", "minecraft:overworld", 100, 101);
        for (var entry : terrain.entrySet()) json.add(entry.getKey(), entry.getValue());
        return json;
    }

    @Test void productionReaderAndHttpKeepLargePageBoundedWithoutCompactingCells() throws Exception {
        var data = ordinaryCell(); var original = data.deepCopy();
        var time = new AtomicLong(); var world = new Object(); var scan = new TerrainScan<JsonObject>(time::get);
        var page = scan.page(TerrainQuery.parse("radius=4&vertical=4&limit=1024&capability=1"), world, 12, 64, 25, source(data));
        var pages = new JsonArray(); int offset = 0; int largestPage = 0;
        while (true) {
            assertEquals(offset, page.offset()); assertEquals(1024, page.pageLimit());
            var body = pageJson(page); var exchange = http(body); var decoded = exchange.body();
            assertEquals(200, exchange.status); assertTrue(exchange.bytes.size() < 256 * 1024);
            assertEquals(1, decoded.get("capability_page_schema_version").getAsInt());
            assertEquals(1024, decoded.get("page_limit").getAsInt());
            assertEquals("live_pages", decoded.get("consistency").getAsString());
            assertEquals(100, decoded.get("game_time").getAsLong()); assertEquals(101, decoded.get("response_game_time").getAsLong());
            for (var cell : decoded.getAsJsonArray("cells")) {
                var copy = cell.getAsJsonObject().deepCopy();
                for (String field : new String[]{"x", "y", "z", "status"}) copy.remove(field);
                assertEquals(original, copy, "All original cell fields remain intact");
            }
            largestPage = Math.max(largestPage, page.cells().size()); pages.add(decoded);
            offset = page.nextOffset(); if (page.nextCursor() == null) break;
            assertTrue(page.payloadBudgetExhausted()); assertFalse(page.budgetExhausted());
            time.addAndGet(TerrainScan.MIN_PAGE_INTERVAL_NANOS);
            page = scan.page(TerrainQuery.parse("cursor=" + page.nextCursor()), world, 12, 64, 25, source(data));
        }
        assertEquals(729, offset); assertTrue(largestPage > 128); assertEquals(2, pages.size()); assertEquals(original, data);
        var evidence = new JsonObject(); evidence.addProperty("synthetic_input_not_live_evidence", true);
        evidence.addProperty("actual_production_scan_reader_http_codec", true); evidence.add("pages", pages);
        Path path = Path.of(System.getProperty("mineclientBridge.projectDir"), "build", "terrain-capability-wire.json");
        Files.writeString(path, new GsonBuilder().setPrettyPrinting().create().toJson(evidence));
    }

    @Test void tinyRealEncodedCellsCanReach1024AndLegacyEnvelopeIsUnchanged() throws Exception {
        var tiny = new JsonObject(); tiny.addProperty("known", true);
        var page = new TerrainScan<JsonObject>(() -> 0L).page(TerrainQuery.parse("capability=1&limit=1024"), new Object(), 0, 64, 0, source(tiny));
        assertEquals(1024, page.cells().size()); assertEquals(200, http(pageJson(page)).status);
        var legacy = new TerrainScan<JsonObject>(() -> 0L).page(TerrainQuery.parse("limit=128"), new Object(), 0, 64, 0, source(tiny));
        var decoded = http(pageJson(legacy)).body();
        assertFalse(decoded.has("capability_page_schema_version")); assertFalse(decoded.has("page_limit"));
        assertFalse(decoded.has("payload_budget_exhausted")); assertEquals(128, decoded.get("returned").getAsInt());
    }

    @Test void conservativeUtf8SizingBoundsRealHttpCellsIncludingEscapesNullsAndUnknowns() throws Exception {
        for (String value : new String[]{"ASCII", "诊断 <&> 😀", "quote\" slash\\\n\t\r\b\f\u0000\u001f\u2028\u2029", "\ud800", "\udc00"}) {
            JsonObject data = ordinaryCell(); data.addProperty("test_value", value); data.add("optional_null", JsonNull.INSTANCE);
            for (var availability : TerrainScan.Availability.values()) {
                var cell = new TerrainScan.Cell<>(-123, 999, Integer.MIN_VALUE, availability,
                        availability == TerrainScan.Availability.LOADED ? data : null);
                var page = new TerrainScan.Page<>("g", 0, 64, 0, 0, 0, 0, 1, 1,
                        java.util.List.of(cell), null, false, 0, 1024, true, false);
                var decoded = http(pageJson(page)).body();
                String body = BridgeJson.toJson(decoded);
                int start = body.indexOf("\"cells\":[") + "\"cells\":[".length();
                int end = body.lastIndexOf(']');
                assertTrue(end >= start);
                int exact = body.substring(start, end).getBytes(StandardCharsets.UTF_8).length + 1;
                assertTrue(TerrainReader.encodedCellBytes(cell) >= exact, value + " " + availability);
            }
        }
    }

    @Test void conservativeSizerCoversEveryUtf16CodeUnitAndNestedNumericJson() throws Exception {
        for (int base = 0; base <= 0xffff; base += 256) {
            StringBuilder text = new StringBuilder();
            for (int offset = 0; offset < 256; offset++) text.append((char) (base + offset));
            JsonObject data = ordinaryCell(); data.addProperty("all_utf16_" + base, text.toString());
            assertSizeBound(data);
        }
        JsonObject data = ordinaryCell(); var nested = new JsonObject();
        nested.add("\u0000quoted\"\\😀\u2028", JsonNull.INSTANCE);
        var numbers = new JsonArray();
        for (Number number : new Number[]{Integer.MIN_VALUE, Integer.MAX_VALUE, Long.MIN_VALUE, Long.MAX_VALUE,
                -0.0, Double.MIN_VALUE, Double.MAX_VALUE, 1.234567890123456e-200,
                new java.math.BigDecimal("0.0000000000000000000000000012345000000000"),
                new java.math.BigInteger("1234567890123456789012345678901234567890")}) numbers.add(number);
        numbers.add(JsonNull.INSTANCE); numbers.add(true); numbers.add(false);
        nested.add("numbers", numbers); nested.add("empty_array", new JsonArray()); nested.add("empty_object", new JsonObject());
        data.add("nested", nested); data.addProperty("x", "replaced existing field"); data.addProperty("y", 12);
        data.addProperty("z", -33); data.addProperty("status", "replaced"); data.addProperty("known", false);
        assertSizeBound(data);
    }

    private void assertSizeBound(JsonObject data) throws Exception {
        var cell = new TerrainScan.Cell<>(Integer.MIN_VALUE, Integer.MAX_VALUE, -1, TerrainScan.Availability.LOADED, data);
        var page = new TerrainScan.Page<>("g", 0, 64, 0, 0, 0, 0, 1, 1,
                java.util.List.of(cell), null, false, 0, 1024, true, false);
        String body = BridgeJson.toJson(pageJson(page));
        int start = body.indexOf("\"cells\":[") + "\"cells\":[".length(); int end = body.lastIndexOf(']');
        int exact = body.substring(start, end).getBytes(StandardCharsets.UTF_8).length + 1;
        assertTrue(TerrainReader.encodedCellBytes(cell) >= exact,
                "Native byte visitor must not undercount actual HTTP UTF-8: " + exact + " > " + TerrainReader.encodedCellBytes(cell));
    }


    @Test void productionEncoderStillRejectsOversizedPayloadRatherThanIncreasingGlobalCap() throws Exception {
        var body = new JsonObject(); body.addProperty("capability_page_schema_version", 1);
        body.addProperty("page_limit", 1024); body.addProperty("data", "x".repeat(256 * 1024));
        var exchange = http(body); assertEquals(500, exchange.status);
        assertEquals("response_too_large", exchange.body().get("error").getAsString());
        JsonObject oversized = ordinaryCell(); oversized.addProperty("too_large", "x".repeat(224 * 1024));
        var scan = new TerrainScan<JsonObject>(() -> 0L);
        assertEquals(TerrainScan.CAPABILITY_CELL_BYTES + 1,
                TerrainReader.encodedCellBytes(new TerrainScan.Cell<>(0, 0, 0, TerrainScan.Availability.LOADED, oversized)));
        assertEquals("terrain_cell_too_large", assertThrows(TerrainScan.Failure.class,
                () -> scan.page(TerrainQuery.parse("capability=1&limit=1024"), new Object(), 0, 64, 0, source(oversized))).getMessage());
    }
}
