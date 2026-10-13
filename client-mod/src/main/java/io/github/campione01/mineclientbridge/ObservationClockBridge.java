package io.github.campione01.mineclientbridge;

import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.neoforged.bus.api.EventPriority;
import net.neoforged.neoforge.client.event.ClientPlayerNetworkEvent;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.level.LevelEvent;
import net.neoforged.neoforge.event.server.ServerStoppedEvent;

/** Supported native event adapter. No action record, server sampling or clock translation. */
final class ObservationClockBridge {
    private static final ObservationClientClock CLOCK=new ObservationClientClock();
    static synchronized void install() {
        CLOCK.register(); // A duplicate install faults before a second listener can be added.
        NeoForge.EVENT_BUS.addListener(EventPriority.HIGHEST,false,ClientTickEvent.Pre.class,event->{
            Minecraft mc=Minecraft.getInstance();
            try {CLOCK.pre(event,context(mc),System.nanoTime(),mc.isSameThread());}
            catch(ObservationClientClock.Unavailable closed) { /* Retain fault; readers refuse. */ }
        });
        NeoForge.EVENT_BUS.addListener(EventPriority.HIGHEST,false,ClientTickEvent.Post.class,event->{
            Minecraft mc=Minecraft.getInstance();
            try {CLOCK.post(event,context(mc),mc.isSameThread());}
            catch(ObservationClientClock.Unavailable closed) { /* Retain fault; readers refuse. */ }
        });
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.LoggingOut.class,event->CLOCK.invalidate());
        NeoForge.EVENT_BUS.addListener(LevelEvent.Unload.class,event->CLOCK.invalidateLevel(event.getLevel()));
        NeoForge.EVENT_BUS.addListener(ServerStoppedEvent.class,event->CLOCK.invalidate());
    }
    /** One capture supplies the selected status sample and its bounded eligibility evidence. */
    record StatusContext(ObservationClientClock.Context context,boolean nativeThread,JsonObject eligibility) { }
    static StatusContext captureStatusContext() {return captureContext(Minecraft.getInstance());}
    private static StatusContext captureContext(Minecraft mc) {
        boolean nativeThread=mc.isSameThread();
        // Wrong-thread reads retain the clock's existing latched protocol-fault behavior.
        if(!nativeThread) {CLOCK.sample(null,false);throw new AssertionError("unreachable");}
        var level=mc.level;var player=mc.player;var gameMode=mc.gameMode;
        var server=mc.getSingleplayerServer();
        boolean singleplayer=mc.hasSingleplayerServer();
        boolean published=server!=null && server.isPublished();
        boolean eligible=level!=null && player!=null && gameMode!=null && server!=null && singleplayer && !published;
        var evidence=new JsonObject();
        evidence.addProperty("native_thread",nativeThread);
        evidence.addProperty("level_present",level!=null);
        evidence.addProperty("player_present",player!=null);
        evidence.addProperty("game_mode_present",gameMode!=null);
        evidence.addProperty("integrated_server_present",server!=null);
        evidence.addProperty("has_singleplayer_server",singleplayer);
        evidence.addProperty("server_published",published);
        evidence.addProperty("eligible",eligible);
        ObservationClientClock.Context context=eligible?new ObservationClientClock.Context(mc,level,player,gameMode,server,
                BridgeServer.runId(),ProcessHandle.current().pid(),IntegratedServerIdentity.current(server,true),
                WorldGeneration.current(level),level.dimension().location().toString(),
                player.getUUID().toString(),ClientActions.session()):null;
        return new StatusContext(context,nativeThread,evidence);
    }
    static ObservationClientClock.Stamp sample(StatusContext captured) {
        return CLOCK.sample(captured.context(),captured.nativeThread());
    }
    private static ObservationClientClock.Context context(Minecraft mc) {
        if(!mc.isSameThread())return null;
        var server=mc.getSingleplayerServer();
        if(mc.level==null || mc.player==null || mc.gameMode==null || server==null
                || !mc.hasSingleplayerServer() || server.isPublished())return null;
        return new ObservationClientClock.Context(mc,mc.level,mc.player,mc.gameMode,server,
                BridgeServer.runId(),ProcessHandle.current().pid(),IntegratedServerIdentity.current(server,true),
                WorldGeneration.current(mc.level),mc.level.dimension().location().toString(),
                mc.player.getUUID().toString(),ClientActions.session());
    }
    static ObservationClientClock.Stamp sample() {
        Minecraft mc=Minecraft.getInstance();
        return CLOCK.sample(context(mc),mc.isSameThread());
    }
    static void requireSame(ObservationClientClock.Stamp before,ObservationClientClock.Stamp after) {
        if(before==null || !before.sameTurn(after)) {CLOCK.invalidate();throw new ObservationClientClock.Unavailable("context_changed");}
    }
    static boolean selected(String query) {
        return ObservationClockWire.selected(query);
    }
    static void unavailableStatus(JsonObject status,String reason) {
        status.addProperty("observation_clock_profile","read_only");
        status.add("observation_clock",JsonNull.INSTANCE);status.addProperty("observation_clock_seen",CLOCK.seen());
        status.addProperty("observation_clock_unavailable",reason);
    }
    static void availableStatus(JsonObject status,ObservationClientClock.Stamp stamp) {
        status.addProperty("observation_clock_profile","read_only");status.add("observation_clock",stamp.json());
        status.addProperty("observation_clock_seen",true);status.add("observation_clock_unavailable",JsonNull.INSTANCE);
    }
    static JsonObject snapshot(JsonObject bundle,ObservationClientClock.Stamp before,ObservationClientClock.Stamp after) {
        requireSame(before,after);
        return ObservationClockWire.snapshot(bundle,before,after);
    }
    private ObservationClockBridge() { }
}
