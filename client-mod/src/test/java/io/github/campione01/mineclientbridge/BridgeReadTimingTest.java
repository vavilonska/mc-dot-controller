package io.github.campione01.mineclientbridge;

import com.sun.net.httpserver.Headers;
import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BridgeReadTimingTest {
    @Test void phaseOffsetsArePerRequestAndIncludeEncodingWithoutSerializingAgain() throws Exception {
        var clock=new AtomicLong(100);var timing=new BridgeReadTiming(clock::get);
        clock.set(110);timing.dispatchRequested();clock.set(600);
        Object value=new Object();assertSame(value,timing.call(()->{clock.set(605);return value;}));
        clock.set(620);timing.encodingStarted();clock.set(680);timing.encodingFinished();
        timing.clientState(2,true,true);var headers=new Headers();timing.addHeaders(headers);
        assertEquals("10",headers.getFirst("X-MDC-Dispatch-Offset-Nanos"));
        assertEquals("500",headers.getFirst("X-MDC-Client-Start-Offset-Nanos"));
        assertEquals("505",headers.getFirst("X-MDC-Client-End-Offset-Nanos"));
        assertEquals("520",headers.getFirst("X-MDC-Encode-Start-Offset-Nanos"));
        assertEquals("580",headers.getFirst("X-MDC-Encode-End-Offset-Nanos"));
        assertEquals("complete",headers.getFirst("X-MDC-Read-Timing-Status"));
        assertEquals("2",headers.getFirst("X-MDC-Client-Fps"));
        var another=new BridgeReadTiming(clock::get);var empty=new Headers();another.addHeaders(empty);
        assertEquals("partial",empty.getFirst("X-MDC-Read-Timing-Status"));
        assertNull(empty.getFirst("X-MDC-Client-Start-Offset-Nanos"));
    }
    @Test void originalExceptionIsPreservedAndEndIsMeasured() {
        var clock=new AtomicLong(10);var timing=new BridgeReadTiming(clock::get);timing.dispatchRequested();
        var expected=new IllegalStateException("original");clock.set(20);
        assertSame(expected,assertThrows(IllegalStateException.class,()->timing.call(()->{clock.set(30);throw expected;})));
        var headers=new Headers();timing.addHeaders(headers);
        assertEquals("20",headers.getFirst("X-MDC-Client-End-Offset-Nanos"));
        assertEquals("partial",headers.getFirst("X-MDC-Read-Timing-Status"));
        assertNull(headers.getFirst("X-MDC-Encode-End-Offset-Nanos"));
    }
    @Test void timedOutBeforeClientStartStillReportsEncodingWithoutInventingClientWork() {
        var clock=new AtomicLong(0);var timing=new BridgeReadTiming(clock::get);
        clock.set(10);timing.dispatchRequested();clock.set(1000);timing.encodingStarted();
        clock.set(1020);timing.encodingFinished();var headers=new Headers();timing.addHeaders(headers);
        assertEquals("partial",headers.getFirst("X-MDC-Read-Timing-Status"));
        assertEquals("1020",headers.getFirst("X-MDC-Encode-End-Offset-Nanos"));
        assertNull(headers.getFirst("X-MDC-Client-Start-Offset-Nanos"));
        assertNull(headers.getFirst("X-MDC-Client-End-Offset-Nanos"));
    }
    @Test void backwardsOrderIsNotClaimedAsValidTiming() throws Exception {
        var clock=new AtomicLong(0);var timing=new BridgeReadTiming(clock::get);
        clock.set(20);timing.dispatchRequested();clock.set(10);timing.call(()->null);
        clock.set(30);timing.encodingStarted();clock.set(40);timing.encodingFinished();
        var headers=new Headers();timing.addHeaders(headers);
        assertEquals("invalid_order",headers.getFirst("X-MDC-Read-Timing-Status"));
    }
    @Test void stateSampleIsActualTickReadWithSignedAbsoluteNanoAndNoExpectedEcho() {
        var clock=new AtomicLong(-1000);var reads=new java.util.concurrent.atomic.AtomicInteger();
        var timing=new BridgeReadTiming(()->{reads.incrementAndGet();return clock.get();});
        clock.set(-900);timing.stateGameTimeSample(42);
        var headers=new Headers();timing.addHeaders(headers);
        assertEquals("1",headers.getFirst("X-MDC-Sample-Timing-Version"));
        assertEquals("state_world_game_time_read",headers.getFirst("X-MDC-Sample-Point"));
        assertEquals("42",headers.getFirst("X-MDC-Sample-Game-Time"));
        assertEquals("-900",headers.getFirst("X-MDC-Sample-Nano-Time"));
        assertEquals("100",headers.getFirst("X-MDC-Sample-Offset-Nanos"));
        assertEquals(2,reads.get()); // Origin and sample only; exporting offsets does not read a clock.
        assertNull(headers.getFirst("X-MDC-Request-Expected-Game-Time"));
    }
    @Test void coordinationAndDiagnosticUseOneIdenticalSignedSample() throws Exception {
        var clock=new AtomicLong(Long.MIN_VALUE);var timing=new BridgeReadTiming(clock::get);
        long sampleNano=Long.MIN_VALUE+4;
        clock.set(123456);
        timing.stateGameTimeSample(10,sampleNano);
        var headers=new Headers();timing.addHeaders(headers);
        JsonObject body=new JsonObject();
        body.add("coordination_step",CoordinationStepGuard.sampleEvidence(10,sampleNano,"w","s","p",0,true));
        var parsed=com.google.gson.JsonParser.parseString(BridgeJson.toJson(body)).getAsJsonObject();
        assertEquals(Long.toString(sampleNano),parsed.getAsJsonObject("coordination_step").get("source_nano").getAsString());
        assertEquals(Long.toString(sampleNano),headers.getFirst("X-MDC-Sample-Nano-Time"));
        assertEquals("4",headers.getFirst("X-MDC-Sample-Offset-Nanos"));
    }
    @Test void sampleIsAbsentBeforeStateCallbackAndCannotLeakAcrossRequests() {
        var previous=new BridgeReadTiming(()->Long.MIN_VALUE);
        previous.stateGameTimeSample(10,Long.MIN_VALUE+3);
        var neverStarted=new BridgeReadTiming(()->20);
        neverStarted.dispatchRequested();neverStarted.encodingStarted();neverStarted.encodingFinished();
        var headers=new Headers();neverStarted.addHeaders(headers);
        assertEquals("partial",headers.getFirst("X-MDC-Read-Timing-Status"));
        for(String key:new String[]{"Sample-Timing-Version","Sample-Point","Sample-Game-Time","Sample-Nano-Time","Sample-Offset-Nanos","Request-Expected-Game-Time"})
            assertNull(headers.getFirst("X-MDC-"+key));
    }
    @Test void suppliedStateSamplePreservesPayloadAndExceptionWithoutExtraClockRead() throws Exception {
        var reads=new java.util.concurrent.atomic.AtomicInteger();
        var timing=new BridgeReadTiming(()->{reads.incrementAndGet();return Long.MIN_VALUE;});
        var response=new JsonObject();response.addProperty("unchanged",true);
        assertSame(response,timing.call(()->{timing.stateGameTimeSample(0,Long.MAX_VALUE);return response;}));
        var headers=new Headers();timing.addHeaders(headers);
        assertEquals(3,reads.get()); // Origin, callback start, callback end; supplied sample adds none.
        assertEquals(Long.toString(Long.MAX_VALUE),headers.getFirst("X-MDC-Sample-Nano-Time"));
        assertEquals("0",headers.getFirst("X-MDC-Sample-Game-Time"));
        assertEquals(1,response.size());
        var failure=new ClientActionRequest.Rejected(409,"not_in_world");
        assertSame(failure,assertThrows(ClientActionRequest.Rejected.class,()->timing.call(()->{throw failure;})));
    }
    @Test void productionStateReadsTickOnceAndSharesExactSampleWhilePostRemainsUntimed() throws Exception {
        String source=Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        String state=source.substring(source.indexOf("private static EndpointResult createStateSnapshot("),source.indexOf("private static JsonObject crosshairSnapshot("));
        assertTrue(state.contains("long gameTime = mc.level.getGameTime();\n        long sampleNano = System.nanoTime();\n        if (timing != null) timing.stateGameTimeSample(gameTime, sampleNano);\n        world.addProperty(\"game_time\", gameTime)"));
        assertEquals(1,state.split("mc.level.getGameTime\\(\\)",-1).length-1);
        assertTrue(state.contains("if (coordination) obj.add(\"coordination_step\", CoordinationStepGuard.observation(mc, gameTime, sampleNano))"));
        String start=source.substring(source.indexOf("private static void handleClientAction(HttpExchange"),source.indexOf("private static void handleClientActionStatus(HttpExchange"));
        assertFalse(start.contains("BridgeReadTiming"));
        assertFalse(source.contains("beforeActionStart"));
        assertFalse(source.contains("requestExpectedGameTime"));
    }
}
