package io.github.campione01.mineclientbridge;

import com.sun.net.httpserver.Headers;
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
}
