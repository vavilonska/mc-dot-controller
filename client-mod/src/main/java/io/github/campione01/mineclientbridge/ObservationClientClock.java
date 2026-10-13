package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.UUID;
import java.util.function.Supplier;

/** One thread-confined Pre/Post clock. Reads never create, advance or repair an epoch. */
final class ObservationClientClock {
    static final String CONTRACT="client-pre-tick-v1";
    static final long MAX_COUNT=9_007_199_254_740_991L;
    record Context(Object client,Object level,Object player,Object gameMode,Object server,
                   String runId,long processId,String serverInstance,String worldGeneration,
                   String dimension,String playerUuid,String actionSession) {
        boolean same(Context other) {
            return other!=null && client==other.client && level==other.level && player==other.player
                    && gameMode==other.gameMode && server==other.server && wire().equals(other.wire());
        }
        JsonObject wire() {
            var value=new JsonObject();value.addProperty("run_id",runId);value.addProperty("process_id",processId);
            value.addProperty("integrated_server_instance",serverInstance);value.addProperty("world_generation",worldGeneration);
            value.addProperty("dimension",dimension);value.addProperty("player_uuid",playerUuid);value.addProperty("action_session",actionSession);
            return value;
        }
        boolean valid() {
            return client!=null && level!=null && player!=null && gameMode!=null && server!=null
                    && text(runId) && processId>0 && processId<=MAX_COUNT && text(serverInstance)
                    && uuid(worldGeneration) && text(dimension) && uuid(playerUuid) && uuid(actionSession);
        }
    }
    record Stamp(String generation,long count,long originNano,Context context) {
        JsonObject json() {var value=domain();value.addProperty("count",count);return value;}
        JsonObject domain() {
            var value=new JsonObject();value.addProperty("contract",CONTRACT);value.addProperty("clock_generation",generation);
            value.addProperty("origin_nano",Long.toString(originNano));value.add("context",context.wire());return value;
        }
        boolean sameDomain(Stamp other) {return other!=null && context.same(other.context) && domain().equals(other.domain());}
        boolean sameTurn(Stamp other) {return sameDomain(other) && count==other.count;}
    }
    static final class Unavailable extends RuntimeException {
        final String reason;
        Unavailable(String reason) {super("observation_clock_unavailable");this.reason=reason;}
    }
    static long wireCount(JsonObject value,Stamp expected) {
        if(value==null || expected==null || !value.keySet().equals(java.util.Set.of("contract","clock_generation","origin_nano","context","count")))
            throw new Unavailable("context_changed");
        var count=value.get("count");
        if(!count.isJsonPrimitive() || !count.getAsJsonPrimitive().isNumber() || !count.getAsString().matches("0|[1-9][0-9]{0,15}"))
            throw new Unavailable("protocol_fault");
        long parsed;
        try {parsed=Long.parseLong(count.getAsString());}catch(NumberFormatException invalid){throw new Unavailable("protocol_fault");}
        JsonObject domain=value.deepCopy();domain.remove("count");
        if(!domain.get("context").isJsonObject())throw new Unavailable("protocol_fault");
        JsonObject context=domain.getAsJsonObject("context");
        if(context==null || context.get("process_id")==null || !context.get("process_id").isJsonPrimitive()
                || !context.get("process_id").getAsJsonPrimitive().isNumber()
                || !context.get("process_id").getAsString().matches("[1-9][0-9]{0,15}"))throw new Unavailable("context_changed");
        if(parsed>MAX_COUNT || !domain.equals(expected.domain()))throw new Unavailable("context_changed");
        return parsed;
    }
    private final Supplier<String> generations;
    private final long maximum;
    private boolean registered,inCallback,inTick,fault,seen;
    private Object lastPre,lastPost;
    private Thread thread;
    private Stamp stamp;
    private String lastGeneration;
    private String unavailable="uninitialized";
    ObservationClientClock() {this(()->UUID.randomUUID().toString(),MAX_COUNT);}
    /** Bounded synthetic constructor; production always uses the fixed default maximum. */
    ObservationClientClock(Supplier<String> generations,long maximum) {
        if(maximum<0 || maximum>MAX_COUNT)throw new IllegalArgumentException("clock_maximum");
        this.generations=generations;this.maximum=maximum;
    }
    synchronized void register() {
        if(registered || fault) {fail();return;}
        registered=true;
    }
    synchronized boolean seen() {return seen;}
    synchronized void invalidate() {stamp=null;if(!fault)unavailable=seen?"context_changed":"uninitialized";}
    synchronized void invalidateLevel(Object level) {if(stamp!=null && stamp.context.level==level)invalidate();}
    private void fail() {fault=true;stamp=null;unavailable="protocol_fault";throw new Unavailable(unavailable);}
    private void enter(boolean nativeThread) {
        if(fault || !registered || !nativeThread || inCallback || thread!=null && thread!=Thread.currentThread())fail();
        if(thread==null)thread=Thread.currentThread();
        inCallback=true;
    }
    synchronized void pre(Object event,Context context,long nano,boolean nativeThread) {
        enter(nativeThread);
        try {
            if(event==null || inTick || event==lastPre || event==lastPost)fail();
            inTick=true;lastPre=event;
            if(context==null || !context.valid()) {stamp=null;unavailable=seen?"context_changed":"not_in_world";return;}
            if(stamp==null || !stamp.context.same(context)) {
                String generation=generations.get();
                if(fault || !uuid(generation) || generation.equals(lastGeneration))fail();
                stamp=new Stamp(generation,0,nano,context);
                seen=true;lastGeneration=generation;
            } else {
                if(stamp.count>=maximum)fail();
                stamp=new Stamp(stamp.generation,stamp.count+1,stamp.originNano,context);
            }
            unavailable=null;
        } finally {inCallback=false;}
    }
    synchronized void post(Object event,Context context,boolean nativeThread) {
        enter(nativeThread);
        try {
            if(event==null || !inTick || event==lastPost || event==lastPre)fail();
            inTick=false;lastPost=event;
            if(stamp!=null && !stamp.context.same(context))invalidate();
        } finally {inCallback=false;}
    }
    synchronized Stamp sample(Context context,boolean nativeThread) {
        if(fault)throw new Unavailable("protocol_fault");
        if(!nativeThread || thread!=null && thread!=Thread.currentThread() || inCallback)fail();
        if(context==null || !context.valid()) {stamp=null;unavailable=seen?"context_changed":"not_in_world";throw new Unavailable(unavailable);}
        if(stamp==null)throw new Unavailable(seen?"context_changed":"uninitialized");
        if(!stamp.context.same(context)) {invalidate();throw new Unavailable("context_changed");}
        return stamp;
    }
    private static boolean text(String value) {return value!=null && !value.isBlank();}
    private static boolean uuid(String value) {
        if(value==null)return false;
        try {return UUID.fromString(value).toString().equals(value);} catch(IllegalArgumentException invalid){return false;}
    }
}
