package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.sun.net.httpserver.HttpExchange;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CapabilityFreshnessTest {
    @Test void bothOriginalInclusiveBoundariesRemainRequired() {
        assertDoesNotThrow(()->CapabilityGuard.requireFresh(123,10,800_000_123L,15,"guard_start"));
        assertDoesNotThrow(()->CapabilityGuard.requireFresh(123,10,123,10,"guard_start"));
        for(long[] values:new long[][]{{800_000_124L,15},{800_000_123L,16},{122,10},{123,9}})
            assertEquals("capability_source_expired",assertThrows(ClientActionRequest.Rejected.class,
                    ()->CapabilityGuard.requireFresh(123,10,values[0],values[1],"guard_start")).getMessage());
    }

    @Test void exactPredicatesExplainEachIndependentBranchAndCombinedExpiry() throws Exception {
        long source=35_539_557_059_677L;
        for(int branch=0;branch<5;branch++) {
            long now=source+(branch==0?-1:branch==1||branch==4?800_000_001L:1);
            long tick=branch==2?192035:branch==3||branch==4?192042:192036;
            var failure=assertThrows(ClientActionRequest.Rejected.class,
                    ()->CapabilityGuard.requireFresh(source,192036,now,tick,"before_input_release"));
            JsonObject evidence=failure.response().getAsJsonObject("capability_source_freshness");
            assertEquals(409,failure.httpStatus);assertEquals(1,evidence.get("schema_version").getAsInt());
            assertEquals(Long.toString(source),evidence.get("source_nano").getAsString());
            assertEquals(Long.toString(now),evidence.get("current_nano").getAsString());
            assertEquals(Long.toString(now-source),evidence.get("elapsed_nanos").getAsString());
            assertEquals(tick-192036,evidence.get("tick_delta").getAsLong());
            assertEquals(branch==0,evidence.get("nano_age_negative").getAsBoolean());
            assertEquals(branch==1||branch==4,evidence.get("nano_age_exceeded").getAsBoolean());
            assertEquals(branch==2,evidence.get("tick_reversed").getAsBoolean());
            assertEquals(branch==3||branch==4,evidence.get("tick_delta_exceeded").getAsBoolean());
        }
    }

    @Test void delayedAdmissionPreservesOriginalSampleAtEveryExistingCheckSiteThroughRealErrorAndHttpPaths() throws Exception {
        long original=9_007_199_254_741_123L;
        var cases=new com.google.gson.JsonArray();
        for(String phase:new String[]{"guard_start","before_input_release","after_input_release"}) {
            var result=BridgeServer.clientActionResult(()->{
                CapabilityGuard.requireFresh(original,10,original+800_000_000L,15,"guard_start");
                CapabilityGuard.requireFresh(original,10,original+800_000_001L,16,phase);
                fail("Must not admit an expired source");return new JsonObject();
            },true);
            var exchange=new BridgeReadResponseTest.Exchange();
            var respond=BridgeServer.class.getDeclaredMethod("respondJson",HttpExchange.class,int.class,JsonObject.class);
            respond.setAccessible(true);respond.invoke(null,exchange,result.status(),result.body());
            assertEquals(409,exchange.status);JsonObject body=exchange.body();
            assertEquals("capability_source_expired",body.get("error").getAsString());
            var evidence=body.getAsJsonObject("capability_source_freshness");
            assertEquals(phase,evidence.get("phase").getAsString());
            assertEquals(Long.toString(original),evidence.get("source_nano").getAsString());
            assertEquals("800000001",evidence.get("elapsed_nanos").getAsString());
            assertEquals(6,evidence.get("tick_delta").getAsInt());
            assertFalse(body.has("action_id"));assertFalse(body.has("admitted"));
            var row=new JsonObject();row.addProperty("name",phase);row.addProperty("http_status",exchange.status);
            row.addProperty("response_json",exchange.bytes.toString(java.nio.charset.StandardCharsets.UTF_8));cases.add(row);
        }
        Path output=Path.of(System.getProperty("mineclientBridge.projectDir"),"build/validation/capability-freshness-wire.json");
        Files.createDirectories(output.getParent());Files.writeString(output,cases.toString());
        String source=Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge/ClientActions.java"));
        assertEquals(2,source.split("capabilityGuard.requireFresh\\(",-1).length-1);
        assertTrue(source.contains("capabilityGuard.requireFresh(mc,\"before_input_release\")"));
        assertTrue(source.contains("capabilityGuard.requireFresh(mc,\"after_input_release\")"));
    }

    @Test void nonFreshnessErrorsRetainLegacyShapeAndEvidenceIsDefensivelyCopied() throws Exception {
        var result=BridgeServer.clientActionResult(()->{throw new ClientActionRequest.Rejected(409,"action_busy");},true);
        assertEquals("{\"ok\":false,\"error\":\"action_busy\"}",BridgeJson.toJson(result.body()));
        JsonObject input=new JsonObject();input.addProperty("source_nano","-9223372036854775808");
        var rejected=new ClientActionRequest.Rejected(409,"synthetic",input);input.addProperty("source_nano","0");
        var first=rejected.response();first.getAsJsonObject("capability_source_freshness").addProperty("source_nano","1");
        assertEquals("-9223372036854775808",rejected.response().getAsJsonObject("capability_source_freshness").get("source_nano").getAsString());
    }

    @Test void signedNanoWrapKeepsExistingSubtractionSemantics() {
        assertDoesNotThrow(()->CapabilityGuard.requireFresh(Long.MAX_VALUE-4,1,Long.MIN_VALUE+4,1,"guard_start"));
    }
}
