package io.github.campione01.mineclientbridge;

import com.sun.net.httpserver.Headers;
import java.util.concurrent.Callable;
import java.util.function.LongSupplier;

/** Per-read diagnostics only. Offsets begin at HTTP handler entry, not socket arrival. */
final class BridgeReadTiming {
    private final LongSupplier clock;
    private final long origin;
    private volatile long dispatch=-1, start=-1, end=-1, encodeStart=-1, encodeEnd=-1;
    private volatile int fps=-1;
    private volatile Boolean focused,paused;
    BridgeReadTiming() { this(System::nanoTime); }
    BridgeReadTiming(LongSupplier clock) { this.clock=clock;origin=clock.getAsLong(); }
    void dispatchRequested() { dispatch=clock.getAsLong()-origin; }
    <T> T call(Callable<T> operation) throws Exception {
        start=clock.getAsLong()-origin;
        try { return operation.call(); }
        finally { end=clock.getAsLong()-origin; }
    }
    void clientState(int fps,boolean focused,boolean paused) { this.fps=fps;this.focused=focused;this.paused=paused; }
    void encodingStarted() { encodeStart=clock.getAsLong()-origin; }
    void encodingFinished() { encodeEnd=clock.getAsLong()-origin; }
    void addHeaders(Headers headers) {
        // Volatile snapshot: a timed-out callback may still finish later. Missing stays missing.
        long[] times={dispatch,start,end,encodeStart,encodeEnd};
        String[] names={"Dispatch","Client-Start","Client-End","Encode-Start","Encode-End"};
        headers.set("X-MDC-Read-Timing-Version","1");
        long previous=-1;boolean valid=true,complete=true;
        for(int i=0;i<times.length;i++) {
            long value=times[i];
            if(value<0) { complete=false;continue; }
            if(value<previous) valid=false;
            previous=value;headers.set("X-MDC-"+names[i]+"-Offset-Nanos",Long.toString(value));
        }
        headers.set("X-MDC-Read-Timing-Status",!valid?"invalid_order":complete?"complete":"partial");
        if(fps>=0) headers.set("X-MDC-Client-Fps",Integer.toString(fps));
        if(focused!=null) headers.set("X-MDC-Client-Focused",focused.toString());
        if(paused!=null) headers.set("X-MDC-Client-Paused",paused.toString());
    }
}
