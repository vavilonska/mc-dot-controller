package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.*;
import com.sun.net.httpserver.*;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;

/** Real HTTP response methods, in-memory exchange only; no socket/server/game launch. */
class BridgeReadResponseTest {
    static final class Exchange extends HttpExchange {
        final Headers response = new Headers(), request = new Headers();
        final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        int status; long length; int sends;
        public Headers getRequestHeaders() { return request; }
        public Headers getResponseHeaders() { return response; }
        public URI getRequestURI() { return URI.create("/control/state"); }
        public String getRequestMethod() { return "GET"; }
        public HttpContext getHttpContext() { return null; }
        public void close() { }
        public InputStream getRequestBody() { return InputStream.nullInputStream(); }
        public OutputStream getResponseBody() { return bytes; }
        public void sendResponseHeaders(int status, long length) { this.status=status;this.length=length;sends++; }
        public InetSocketAddress getRemoteAddress() { return null; }
        public int getResponseCode() { return status; }
        public InetSocketAddress getLocalAddress() { return null; }
        public String getProtocol() { return "HTTP/1.1"; }
        public Object getAttribute(String key) { return null; }
        public void setAttribute(String key,Object value) { }
        public void setStreams(InputStream input,OutputStream output) { throw new AssertionError("No stream substitution"); }
        public HttpPrincipal getPrincipal() { return null; }
        JsonObject body() { return JsonParser.parseString(bytes.toString(StandardCharsets.UTF_8)).getAsJsonObject(); }
    }
    private void invoke(String name, Class<?>[] types, Object... args) throws Exception {
        Method method=BridgeServer.class.getDeclaredMethod(name,types);method.setAccessible(true);
        try { method.invoke(null,args); }
        catch (InvocationTargetException exception) {
            if (exception.getCause() instanceof Exception cause) throw cause;
            throw exception;
        }
    }
    private void json(Exchange exchange,int status,JsonObject body,BridgeReadTiming timing) throws Exception {
        invoke("respondJson",new Class<?>[]{HttpExchange.class,int.class,JsonObject.class,BridgeReadTiming.class},
                exchange,status,body,timing);
    }
    private BridgeReadTiming timing() throws Exception {
        var timing=new BridgeReadTiming();timing.dispatchRequested();timing.call(()->null);return timing;
    }
    private void common(Exchange exchange) {
        assertEquals(1,exchange.sends);assertEquals(exchange.bytes.size(),exchange.length);
        assertEquals("application/json; charset=utf-8",exchange.response.getFirst("Content-Type"));
        assertEquals("no-store",exchange.response.getFirst("Cache-Control"));
        assertEquals("nosniff",exchange.response.getFirst("X-Content-Type-Options"));
    }

    @Test void actualUtf8HttpBodyRetainsExplicitNullAndTiming() throws Exception {
        var exchange=new Exchange();
        var body=JsonParser.parseString("{\"text\":\"诊断 <&>\",\"result\":{\"combat\":{\"encounter\":{\"outcome_scope\":null,\"other\":null}}}}").getAsJsonObject();
        json(exchange,200,body,timing());common(exchange);assertEquals(200,exchange.status);
        assertTrue(exchange.body().getAsJsonObject("result").getAsJsonObject("combat").getAsJsonObject("encounter").get("outcome_scope").isJsonNull());
        assertFalse(exchange.body().getAsJsonObject("result").getAsJsonObject("combat").getAsJsonObject("encounter").has("other"));
        assertEquals("诊断 <&>",exchange.body().get("text").getAsString());
        assertEquals("complete",exchange.response.getFirst("X-MDC-Read-Timing-Status"));
    }

    @Test void untimedHttpResponsesKeepNoTimingHeaders() throws Exception {
        var exchange=new Exchange();var body=new JsonObject();body.addProperty("ok",true);
        invoke("respondJson",new Class<?>[]{HttpExchange.class,int.class,JsonObject.class},exchange,202,body);
        common(exchange);assertEquals(202,exchange.status);assertEquals(body,exchange.body());
        assertNull(exchange.response.getFirst("X-MDC-Read-Timing-Version"));
    }

    @Test void oversizedBodyRetainsExistingFailureStatusAndBoundedWire() throws Exception {
        var exchange=new Exchange();var body=new JsonObject();body.addProperty("data","x".repeat(256*1024));
        json(exchange,200,body,timing());common(exchange);assertEquals(500,exchange.status);
        assertEquals("response_too_large",exchange.body().get("error").getAsString());
        assertTrue(exchange.bytes.size()<1024);assertEquals("complete",exchange.response.getFirst("X-MDC-Read-Timing-Status"));
    }

    @Test void timeoutInterruptAndExecutionFailuresKeepStatusAndCarryPartialTiming() throws Exception {
        Exception[] failures={new TimeoutException(),new InterruptedException(),new ExecutionException(new IllegalStateException("synthetic_failure"))};
        int[] statuses={504,503,500};String[] codes={"minecraft_thread_timeout","request_interrupted","state_failed"};
        try {
            for(int i=0;i<failures.length;i++) {
                Thread.interrupted();var exchange=new Exchange();var timing=new BridgeReadTiming();timing.dispatchRequested();
                invoke("respondMinecraftFailure",new Class<?>[]{HttpExchange.class,String.class,Exception.class,BridgeReadTiming.class},exchange,"state_failed",failures[i],timing);
                common(exchange);assertEquals(statuses[i],exchange.status);assertEquals(codes[i],exchange.body().get("error").getAsString());
                assertEquals(i==1,Thread.currentThread().isInterrupted());
                assertEquals("partial",exchange.response.getFirst("X-MDC-Read-Timing-Status"));
                assertNull(exchange.response.getFirst("X-MDC-Client-Start-Offset-Nanos"));
                assertNotNull(exchange.response.getFirst("X-MDC-Encode-End-Offset-Nanos"));
            }
        } finally { Thread.interrupted(); }
    }
}
