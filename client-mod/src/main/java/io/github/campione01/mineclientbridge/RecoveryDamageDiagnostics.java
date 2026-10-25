package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.entity.living.LivingDamageEvent;
import net.neoforged.neoforge.event.tick.PlayerTickEvent;

/** Opt-in one-window getter-only diagnostics. No world/control mutation, persistence or reset endpoint. */
final class RecoveryDamageDiagnostics {
    static final String ROOT="/control/recovery-diagnostics/v1/events",PROFILE="recovery_damage_diagnostics_v1";
    static final boolean ENABLED=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoveryDamageDiagnostics","false"));
    static final long WINDOW_NANOS=15_000_000_000L;
    static final Recorder RECORDER=new Recorder(ENABLED);
    static void install(){if(!ENABLED)return;NeoForge.EVENT_BUS.addListener(PlayerTickEvent.Pre.class,RecoveryDamageDiagnostics::serverTick);NeoForge.EVENT_BUS.addListener(PlayerTickEvent.Post.class,RecoveryDamageDiagnostics::clientTick);NeoForge.EVENT_BUS.addListener(LivingDamageEvent.Post.class,RecoveryDamageDiagnostics::damage);}
    static boolean local(ServerPlayer p){return p.server instanceof IntegratedServer&&p.server.getSingleplayerProfile()!=null&&p.getUUID().equals(p.server.getSingleplayerProfile().getId());}
    private static void serverTick(PlayerTickEvent.Pre event){if(!(event.getEntity() instanceof ServerPlayer p))return;try{if(!p.server.isSameThread()){RECORDER.error();return;}if(!local(p))return;long now=System.nanoTime();if(RECORDER.accepts(now))RECORDER.server(server(p,now),now);}catch(RuntimeException failure){RECORDER.error();}}
    private static void clientTick(PlayerTickEvent.Post event){
        if(!(event.getEntity() instanceof net.minecraft.client.player.LocalPlayer))return;
        try{Minecraft mc=Minecraft.getInstance();if(!mc.isSameThread()){RECORDER.error();return;}if(event.getEntity()!=mc.player||mc.player==null||mc.getSingleplayerServer()==null)return;long now=System.nanoTime();if(!RECORDER.accepts(now))return;var p=mc.player;JsonObject j=new JsonObject();j.addProperty("nano_time",now);j.addProperty("client_tick",p.tickCount);j.addProperty("player_uuid",p.getUUID().toString());j.addProperty("health",p.getHealth());j.add("position",position(p));
            JsonObject input=new JsonObject();input.addProperty("forward",p.input.forwardImpulse);input.addProperty("strafe",p.input.leftImpulse);input.addProperty("jump",p.input.jumping);j.add("input",input);j.add("native",NativeRecoveryShortInput.diagnosticSnapshot());RECORDER.client(j,now);
        }catch(RuntimeException failure){RECORDER.error();}
    }
    private static void damage(LivingDamageEvent.Post event){
        if(!(event.getEntity() instanceof ServerPlayer p))return;
        try{if(!p.server.isSameThread()){RECORDER.error();return;}if(!local(p))return;long now=System.nanoTime();if(!RECORDER.accepts(now))return;var source=event.getSource();JsonObject j=server(p,now);j.remove("health");j.addProperty("health_after",p.getHealth());j.addProperty("original_damage",event.getOriginalDamage());j.addProperty("new_damage",event.getNewDamage());j.addProperty("blocked_damage",event.getBlockedDamage());j.addProperty("source_key",source.typeHolder().unwrapKey().map(k->bounded(k.location().toString())).orElse(null));j.add("direct",entity(source.getDirectEntity()));j.add("causing",entity(source.getEntity()));
            JsonObject latest=RECORDER.latestClient; j.add("client_snapshot_nanos",latest==null?JsonNull.INSTANCE:latest.get("nano_time"));j.add("native_snapshot",latest==null?JsonNull.INSTANCE:latest.get("native").deepCopy());RECORDER.damage(j,now);
        }catch(RuntimeException failure){RECORDER.error();}
    }
    private static JsonObject server(ServerPlayer p,long now){JsonObject j=new JsonObject();j.addProperty("nano_time",now);j.addProperty("server_tick",p.server.getTickCount());j.addProperty("game_time",p.level().getGameTime());j.addProperty("player_uuid",p.getUUID().toString());j.addProperty("health",p.getHealth());j.add("position",position(p));return j;}
    private static JsonObject position(Entity p){JsonObject j=new JsonObject();j.addProperty("x",finite(p.getX()));j.addProperty("y",finite(p.getY()));j.addProperty("z",finite(p.getZ()));return j;}
    private static JsonElement entity(Entity e){if(e==null)return JsonNull.INSTANCE;JsonObject j=position(e);j.addProperty("type",bounded(BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).toString()));j.addProperty("uuid",e.getUUID().toString());return j;}
    private static double finite(double v){if(!Double.isFinite(v))throw new IllegalArgumentException("nonfinite_diagnostic");return v;}
    private static String bounded(String s){if(s.length()>128)throw new IllegalArgumentException("diagnostic_identifier_too_long");return s;}
    static JsonObject snapshot(){return RECORDER.snapshot(System.nanoTime());}
    static byte[] encode(JsonObject snapshot){byte[] bytes=RecoveryShortInputCodec.encode(snapshot);if(bytes.length>131072)throw new IllegalArgumentException("diagnostic_response_too_large");return bytes;}
    static final class Recorder {
        final boolean enabled;final String boot=UUID.randomUUID().toString();Long start;JsonObject firstServer,firstClient;volatile JsonObject latestClient;final ArrayDeque<JsonObject> clients=new ArrayDeque<>(),damages=new ArrayDeque<>();
        long total,nonzero,clientDropped,damageTotal,damageDropped,errors;Integer firstNonzero;long lastRetainedTick=Long.MIN_VALUE;JsonObject lastRetained;
        Recorder(boolean enabled){this.enabled=enabled;}
        synchronized boolean accepts(long now){return enabled&&(start==null||now-start>=0&&now-start<WINDOW_NANOS);}
        private boolean begin(long now){if(!accepts(now))return false;if(start==null)start=now;return true;}
        synchronized void server(JsonObject j,long now){if(begin(now)&&firstServer==null)firstServer=j.deepCopy();}
        synchronized void client(JsonObject j,long now){if(!begin(now))return;JsonObject copy=j.deepCopy();if(firstClient==null)firstClient=copy;latestClient=copy;total++;var input=copy.getAsJsonObject("input");int tick=copy.get("client_tick").getAsInt();if(input.get("forward").getAsDouble()!=0||input.get("strafe").getAsDouble()!=0||input.get("jump").getAsBoolean()){nonzero++;if(firstNonzero==null)firstNonzero=tick;}
            boolean changed=lastRetained==null||!input.equals(lastRetained.get("input"))||!copy.get("health").equals(lastRetained.get("health"));if(changed||tick-lastRetainedTick>=20){if(clients.size()==32){clients.removeFirst();clientDropped++;}clients.addLast(copy);lastRetained=copy;lastRetainedTick=tick;}}
        synchronized void damage(JsonObject j,long now){if(!begin(now))return;damageTotal++;if(damages.size()==32){damageDropped++;return;}JsonObject copy=j.deepCopy();copy.addProperty("sequence",damageTotal);damages.addLast(copy);}
        synchronized void error(){errors++;}
        synchronized JsonObject snapshot(long now){JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("profile",PROFILE);j.addProperty("enabled",enabled);j.addProperty("boot_id",boot);j.addProperty("window_ms",15000);j.addProperty("window_started",start!=null);j.addProperty("window_closed",start!=null&&(now-start<0||now-start>=WINDOW_NANOS));j.addProperty("window_start_nanos",start);j.addProperty("query_nanos",now);j.add("server_first",firstServer==null?JsonNull.INSTANCE:firstServer.deepCopy());j.add("client_first",firstClient==null?JsonNull.INSTANCE:firstClient.deepCopy());j.add("client_latest",latestClient==null?JsonNull.INSTANCE:latestClient.deepCopy());j.addProperty("client_total",total);j.addProperty("client_nonzero_count",nonzero);j.addProperty("first_nonzero_tick",firstNonzero);j.addProperty("client_dropped",clientDropped);j.add("client_samples",array(clients));j.addProperty("damage_total",damageTotal);j.addProperty("damage_dropped",damageDropped);j.add("damage_events",array(damages));j.addProperty("capture_errors",errors);return j;}
        private JsonArray array(Collection<JsonObject> values){JsonArray a=new JsonArray();for(JsonObject value:values)a.add(value.deepCopy());return a;}
    }
}
