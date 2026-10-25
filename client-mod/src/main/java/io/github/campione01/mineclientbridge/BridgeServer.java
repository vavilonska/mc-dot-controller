package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.mojang.blaze3d.platform.InputConstants;
import com.mojang.blaze3d.platform.NativeImage;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.PriorityQueue;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;
import net.minecraft.client.gui.components.AbstractWidget;
import net.minecraft.client.gui.components.events.GuiEventListener;
import net.minecraft.client.gui.navigation.ScreenRectangle;
import net.minecraft.client.gui.screens.ChatScreen;
import net.minecraft.client.gui.screens.PauseScreen;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.util.Mth;
import net.minecraft.world.effect.MobEffectInstance;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import net.neoforged.neoforge.client.ClientHooks;
import org.lwjgl.glfw.GLFW;

public final class BridgeServer {
    private static final String PROTOCOL_NAME = "mineclient-bridge";
    private static final int PROTOCOL_SCHEMA_VERSION = 2;
    private static final int HTTP_BACKLOG = 16;
    private static final int HTTP_WORKERS = 4;
    private static final int MAX_BODY_BYTES = 64 * 1024;
    private static final int MAX_JSON_BYTES = 256 * 1024;
    private static final int MAX_FRAME_BYTES = 32 * 1024 * 1024;
    private static final int MAX_TEXT_LENGTH = 512;
    private static final int MAX_COMMAND_LENGTH = 256;
    private static final int MAX_GLFW_KEY_CODE = 348;
    private static final int MAX_KEYMAPS = 256;
    private static final int MAX_STATUS_EFFECTS = 64;
    private static final int MAX_NEARBY_ENTITIES = 64;
    private static final int MAX_SCREEN_CHILDREN = 128;
    private static final int MAX_CONTAINER_SLOTS = 256;
    private static final double DEFAULT_ENTITY_RADIUS = 16.0;
    private static final double MAX_ENTITY_RADIUS = 128.0;
    private static final double MAX_GUI_COORDINATE = 1_000_000.0;
    private static final long MINECRAFT_TIMEOUT_SECONDS = 5;
    private static final long FRAME_TIMEOUT_SECONDS = 15;
    private static final GuardedDispatch GUARDED_ACTIONS = new GuardedDispatch(System::nanoTime, false);
    private static final TerrainDispatch TERRAIN_DISPATCH = new TerrainDispatch();
    private static final TerrainAcquisition TERRAIN_ACQUISITION = new TerrainAcquisition(System::nanoTime,
            TERRAIN_DISPATCH,
            task -> Minecraft.getInstance().execute(() -> ClientInputIsolation.syntheticDispatch(task)),
            task -> {
                ExecutorService executor=BridgeServer.serverExecutor;
                if(executor==null)throw new RejectedExecutionException("acquisition_executor_closed");
                executor.execute(task);
            }, new AcquisitionSource());
    private static final AtomicInteger WORKER_SEQUENCE = new AtomicInteger();
    private static final LinkedHashSet<InputConstants.Key> HELD_RAW_KEYS = new LinkedHashSet<>();
    private static final LinkedHashSet<Integer> HELD_WORLD_MOUSE_BUTTONS = new LinkedHashSet<>();
    private static volatile HttpServer server;
    private static volatile ExecutorService serverExecutor;
    private static volatile BridgeConfig config;

    private BridgeServer() {
    }

    public static synchronized void start() {
        if (server != null) {
            return;
        }

        config = BridgeConfigStore.load();
        if (!config.enabled()) {
            BridgeLog.LOGGER.info("MineClient Bridge disabled by config");
            return;
        }

        HttpServer createdServer = null;
        ExecutorService createdExecutor = null;
        try {
            InetAddress bindAddress = InetAddress.getByName(config.host());
            if (!bindAddress.isLoopbackAddress()) {
                throw new IOException("MineClient Bridge refuses non-loopback host: " + config.host());
            }

            createdServer = HttpServer.create(new InetSocketAddress(bindAddress, config.port()), HTTP_BACKLOG);
            for(String root:new String[]{NativeRecoveryShortInput.ROOT,RecoveryInteraction.ROOT,RecoveryInteraction.V2_ROOT,RecoveryInteraction.V3_ROOT})for(String operation:new String[]{"observe","start","status","stop"})
                createdServer.createContext(root+operation,BridgeServer::handleRecoveryShortInput);
            createdServer.createContext(RecoveryDamageDiagnostics.ROOT,BridgeServer::handleRecoveryDamageDiagnostics);
            createdServer.createContext("/control/status", BridgeServer::handleControlStatus);
            createdServer.createContext("/control/backup/start", BridgeServer::handleBackupStart);
            createdServer.createContext("/control/defense/arm", BridgeServer::handleDefenseArm);
            createdServer.createContext("/control/defense/status", BridgeServer::handleDefenseStatus);
            createdServer.createContext("/control/defense/disarm", BridgeServer::handleDefenseDisarm);
            createdServer.createContext("/control/backup/status", BridgeServer::handleBackupStatus);
            createdServer.createContext("/control/backup/scheduler", BridgeServer::handleBackupScheduler);
            createdServer.createContext("/control/capabilities", BridgeServer::handleControlCapabilities);
            createdServer.createContext("/control/frame", BridgeServer::handleControlFrame);
            createdServer.createContext("/control/keymaps", BridgeServer::handleControlKeymaps);
            createdServer.createContext("/control/state", BridgeServer::handleControlState);
            createdServer.createContext("/control/capability-snapshot", BridgeServer::handleCapabilitySnapshot);
            createdServer.createContext("/control/compact-observation", BridgeServer::handleCompactObservation);
            createdServer.createContext("/control/terrain", BridgeServer::handleControlTerrain);
            for(String operation:new String[]{"prepare","activate","status","fetch","cancel"})
                createdServer.createContext(TerrainAcquisitionRequest.ROOT+operation,BridgeServer::handleTerrainAcquisition);
            createdServer.createContext("/control/scan", BridgeServer::handleScanStart);
            createdServer.createContext("/control/scan/status", BridgeServer::handleScanStatus);
            createdServer.createContext("/control/scan/cancel", BridgeServer::handleScanCancel);
            createdServer.createContext("/control/screen", BridgeServer::handleControlScreen);
            createdServer.createContext("/control/action", BridgeServer::handleClientAction);
            createdServer.createContext("/control/scoped-action", BridgeServer::handleScopedClientAction);
            createdServer.createContext("/control/action/status", BridgeServer::handleClientActionStatus);
            createdServer.createContext("/control/action/cancel", BridgeServer::handleClientActionCancel);
            createdServer.createContext("/control/pause", BridgeServer::handleEncounterPause);
            for(String operation:new String[]{"start","cancel","status"})
                createdServer.createContext("/control/managed-navigation/"+operation,BridgeServer::handleManagedNavigation);
            for(String operation:new String[]{"stop","status"})
                createdServer.createContext("/control/external-navigation/"+operation,BridgeServer::handleExternalNavigation);
            createdServer.createContext("/control/fall-rescue/adjudication",BridgeServer::handleFallAdjudication);
            for(String operation:new String[]{"arm","renew","disarm","status"})
                createdServer.createContext("/control/fall-rescue/"+operation,BridgeServer::handleFallRescue);
            createdServer.createContext("/control/key", BridgeServer::handleControlKey);
            createdServer.createContext("/control/raw-key", BridgeServer::handleControlRawKey);
            createdServer.createContext("/control/guarded-action", BridgeServer::handleControlGuardedAction);
            createdServer.createContext("/control/guarded-movement", BridgeServer::handleGuardedMovement);
            createdServer.createContext("/control/guarded-turn", BridgeServer::handleGuardedTurn);
            createdServer.createContext("/control/look", BridgeServer::handleControlLook);
            createdServer.createContext("/control/mouse", BridgeServer::handleControlMouse);
            createdServer.createContext("/control/text", BridgeServer::handleControlText);
            createdServer.createContext("/control/command", BridgeServer::handleControlCommand);
            createdServer.createContext("/control/release-all", BridgeServer::handleControlReleaseAll);
            createdServer.createContext("/control/close", BridgeServer::handleControlClose);
            createdServer.createContext("/", BridgeServer::handleRoot);

            createdExecutor = Executors.newFixedThreadPool(HTTP_WORKERS, workerThreadFactory());
            createdServer.setExecutor(createdExecutor);
            server = createdServer;
            serverExecutor = createdExecutor;
            NativeRecoveryShortInput.open();
            TERRAIN_ACQUISITION.open();
            GUARDED_ACTIONS.openAdmission();
            GuardedGameMovement.LEASES.openAdmission();
            createdServer.start();
            ManagedNavigationInputPolicy.openAdmission();
            BridgeLog.LOGGER.info("MineClient Bridge listening on http://{}:{} auth_enabled={}",
                    config.host(), config.port(), !config.token().isBlank());
        } catch (IOException | RuntimeException e) {
            ManagedNavigationInputPolicy.closeAdmission();
            GUARDED_ACTIONS.closeAdmission();
            GuardedGameMovement.LEASES.closeAdmission();
            server = null;
            serverExecutor = null;
            if (createdServer != null) {
                createdServer.stop(0);
            }
            if (createdExecutor != null) {
                createdExecutor.shutdownNow();
            }
            BridgeLog.LOGGER.warn("Failed to start MineClient Bridge", e);
        }
    }

    public static synchronized void restart() {
        stop();
        start();
    }

    public static synchronized void stop() {
        NativeRecoveryShortInput.close(); // Invalidate native tickets before any queued cleanup or executor stop.
        ManagedNavigationInputPolicy.Token managedShutdown=ManagedNavigationInputPolicy.closeAdmission();
        TERRAIN_ACQUISITION.close();
        GUARDED_ACTIONS.closeAdmission();
        GuardedGameMovement.LEASES.closeAdmission();
        releaseAllOnMinecraftThread(managedShutdown);

        HttpServer currentServer = server;
        server = null;
        if (currentServer != null) {
            currentServer.stop(0);
        }

        ExecutorService currentExecutor = serverExecutor;
        serverExecutor = null;
        if (currentExecutor != null) {
            TERRAIN_ACQUISITION.removedFromExecutor(currentExecutor.shutdownNow());
        }
    }

    public static boolean isRunning() {
        return server != null;
    }

    public static BridgeConfig config() {
        if (config == null) {
            config = BridgeConfigStore.load();
        }
        return config;
    }

    private static ThreadFactory workerThreadFactory() {
        return runnable -> {
            Thread thread = new Thread(runnable,
                    "MineClient-Bridge-" + WORKER_SEQUENCE.incrementAndGet());
            thread.setDaemon(true);
            return thread;
        };
    }

    private static void handleRoot(HttpExchange exchange) throws IOException {
        respondJson(exchange, 404, error("unknown_endpoint"));
    }

    private static void handleRecoveryDamageDiagnostics(HttpExchange exchange)throws IOException{
        if(!exchange.getRequestURI().getPath().equals(RecoveryDamageDiagnostics.ROOT)){respondJson(exchange,404,error("unknown_endpoint"));return;}
        if(!requireControlAccess(exchange,RecoveryDamageDiagnostics.ROOT,"GET"))return;
        if(exchange.getRequestURI().getRawQuery()!=null){respondJson(exchange,400,error("invalid_query"));return;}
        byte[] encoded;try{encoded=RecoveryDamageDiagnostics.encode(RecoveryDamageDiagnostics.snapshot());}
        catch(IllegalArgumentException overflow){respondJson(exchange,503,error("diagnostic_response_too_large"));return;}
        exchange.getResponseHeaders().set("Content-Type","application/json; charset=utf-8");exchange.getResponseHeaders().set("Cache-Control","no-store");
        exchange.sendResponseHeaders(200,encoded.length);try(OutputStream out=exchange.getResponseBody()){out.write(encoded);}
    }

    private static void handleRecoveryShortInput(HttpExchange exchange) throws IOException {
        String path=exchange.getRequestURI().getPath();
        String root=path.startsWith(RecoveryInteraction.V3_ROOT)?RecoveryInteraction.V3_ROOT:path.startsWith(RecoveryInteraction.V2_ROOT)?RecoveryInteraction.V2_ROOT:path.startsWith(RecoveryInteraction.ROOT)?RecoveryInteraction.ROOT:NativeRecoveryShortInput.ROOT;
        String profile=root.equals(RecoveryInteraction.V3_ROOT)?RecoveryShortInputLedger.INTERACTION_V3_PROFILE:root.equals(RecoveryInteraction.V2_ROOT)?RecoveryShortInputLedger.INTERACTION_V2_PROFILE:root.equals(RecoveryInteraction.ROOT)?RecoveryShortInputLedger.INTERACTION_PROFILE:RecoveryShortInputLedger.PROFILE;
        String operation=path.substring(root.length());
        if(!java.util.Set.of("observe","start","status","stop").contains(operation)){
            respondJson(exchange,404,error("unknown_endpoint"));return;
        }
        if(!requireControlAccess(exchange,root+operation,
                operation.equals("observe")||operation.equals("status")?"GET":"POST"))return;
        try {
            JsonObject response;
            if(operation.equals("observe")){
                if(exchange.getRequestURI().getRawQuery()!=null)throw new IllegalArgumentException("invalid_query");
                // Read-only wait is bounded; no movement callback is submitted by this operation.
                String observationProfile=RecoverySurvivalV6.ENABLED&&RecoveryShortInputLedger.INTERACTION_V3_PROFILE.equals(profile)?RecoveryShortInputLedger.SURVIVAL_V6_PROFILE:RecoveryMaintenanceV5.ENABLED&&RecoveryShortInputLedger.INTERACTION_V3_PROFILE.equals(profile)?RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE:RecoveryNavigationV4.observationProfile(profile);
                response=callOnMinecraftThread(()->NativeRecoveryShortInput.observe(observationProfile),1);
            }else if(operation.equals("status")){
                response=NativeRecoveryShortInput.status(RecoveryShortInputCodec.statusQuery(exchange.getRequestURI().getRawQuery()),profile);
            }else{
                if(exchange.getRequestURI().getRawQuery()!=null)throw new IllegalArgumentException("invalid_query");
                byte[] bytes;
                try(InputStream in=exchange.getRequestBody()){bytes=in.readNBytes(8193);}
                JsonObject body=RecoveryShortInputCodec.parse(bytes);
                String bodyProfile=RecoveryNavigationV4.bodyProfile(profile,body);
                if(RecoveryShortInputLedger.INTERACTION_V3_PROFILE.equals(profile)&&body.has("profile")&&body.get("profile").isJsonPrimitive()&&body.getAsJsonPrimitive("profile").isString()&&RecoveryMaintenanceV5.profile(body.get("profile").getAsString()))bodyProfile=RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE;
                if(RecoveryShortInputLedger.INTERACTION_V3_PROFILE.equals(profile)&&body.has("profile")&&body.get("profile").isJsonPrimitive()&&body.getAsJsonPrimitive("profile").isString()&&RecoverySurvivalV6.profile(body.get("profile").getAsString()))bodyProfile=RecoveryShortInputLedger.SURVIVAL_V6_PROFILE;
                response=operation.equals("start")?NativeRecoveryShortInput.start(body,bodyProfile):NativeRecoveryShortInput.stop(body,bodyProfile);
            }
            byte[] encoded=RecoveryShortInputCodec.encode(response);
            if(RecoveryNavigationV4.isResponse(response)||response.has("profile")&&RecoveryShortInputLedger.geometryProfile(response.get("profile").getAsString()))RecoveryNavigationV4.checkResponseBudget(encoded);
            exchange.getResponseHeaders().set("Content-Type","application/json; charset=utf-8");
            exchange.getResponseHeaders().set("Cache-Control","no-store");
            exchange.sendResponseHeaders(operation.equals("start")?202:200,encoded.length);
            try(OutputStream out=exchange.getResponseBody()){out.write(encoded);}
        }catch(RecoveryShortInputLedger.AdmissionNotCommitted failure){
            JsonObject rejected=error("admission_not_committed_no_input_possible");
            rejected.addProperty("admission_committed",false);rejected.addProperty("no_input_possible",true);
            respondJson(exchange,503,rejected);
        }catch(IllegalArgumentException rejected){respondJson(exchange,409,error(rejected.getMessage()));}
        catch(Exception failure){respondMinecraftFailure(exchange,"recovery_short_input_failed",failure);}
    }

    private static void handleControlStatus(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/status", "GET")) return;
        final boolean clock;
        try {clock=ObservationClockBridge.selected(exchange.getRequestURI().getRawQuery());}
        catch(IllegalArgumentException invalid){respondJson(exchange,400,error("invalid_observation_clock"));return;}
        try {
            JsonObject status = callOnMinecraftThread(
                    () -> {
                        if(!clock)return createControlStatus();
                        ObservationClientClock.Stamp before=null;String unavailable=null;
                        ObservationClockBridge.StatusContext captured=ObservationClockBridge.captureStatusContext();
                        try {before=ObservationClockBridge.sample(captured);}catch(ObservationClientClock.Unavailable invalid){unavailable=invalid.reason;}
                        JsonObject value=createControlStatus();
                        value.add("observation_clock_context",captured.eligibility());
                        if(unavailable==null)try {
                            ObservationClockBridge.requireSame(before,ObservationClockBridge.sample());
                            ObservationClockBridge.availableStatus(value,before);
                        }catch(ObservationClientClock.Unavailable invalid){unavailable=invalid.reason;}
                        if(unavailable!=null)ObservationClockBridge.unavailableStatus(value,unavailable);
                        return value;
                    },
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, 200, status);
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "status_failed", e);
        }
    }

    private static void handleControlCapabilities(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/capabilities", "GET")) return;
        respondJson(exchange, 200, createCapabilities());
    }

    private static void handleControlFrame(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/frame", "GET")) return;

        try {
            byte[] png = callOnMinecraftThread(
                    BridgeServer::captureFrame,
                    FRAME_TIMEOUT_SECONDS);
            respondBytes(exchange, 200, "image/png", png);
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "frame_capture_failed", e);
        }
    }

    private static void handleControlKeymaps(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/keymaps", "GET")) return;

        try {
            JsonObject keymaps = callOnMinecraftThread(
                    BridgeServer::createKeymapsSnapshot,
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, 200, keymaps);
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "keymaps_failed", e);
        }
    }

    private static void handleControlState(HttpExchange exchange) throws IOException {
        BridgeReadTiming timing = new BridgeReadTiming();
        if (!requireControlAccess(exchange, "/control/state", "GET")) return;

        final double radius;
        final boolean coordination;
        try {
            radius = queryDouble(exchange, "radius", DEFAULT_ENTITY_RADIUS, 0.0, MAX_ENTITY_RADIUS);
            coordination = queryDouble(exchange, "coordination_step", 0, 0, 1) == 1;
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return;
        }

        try {
            timing.dispatchRequested();
            EndpointResult result = callOnMinecraftThread(
                    () -> timing.call(() -> {
                        Minecraft mc = Minecraft.getInstance();
                        timing.clientState(mc.getFps(), mc.isWindowActive(), mc.isPaused());
                        return createStateSnapshot(radius, timing, coordination);
                    }),
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, result.status(), result.body(), timing);
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "state_failed", e, timing);
        }
    }

    private static void handleCapabilitySnapshot(HttpExchange exchange) throws IOException {
        BridgeReadTiming timing=new BridgeReadTiming();
        if(!requireControlAccess(exchange,"/control/capability-snapshot","GET"))return;
        final double radius;
        final boolean coordination;
        final boolean clock;
        try {
            radius=queryDouble(exchange,"radius",DEFAULT_ENTITY_RADIUS,0.0,MAX_ENTITY_RADIUS);
            coordination=queryDouble(exchange,"coordination_step",0,0,1)==1;
            clock=ObservationClockBridge.selected(exchange.getRequestURI().getRawQuery());
            if(clock && coordination)throw new IllegalArgumentException("clock_coordination_blocked");
        } catch(RequestException failure) { respondRequestFailure(exchange,failure);return; }
        catch(IllegalArgumentException invalid){respondJson(exchange,400,error("invalid_observation_clock"));return;}
        try {
            timing.dispatchRequested();
            EndpointResult result=callOnMinecraftThread(() -> timing.call(() -> {
                Minecraft mc=Minecraft.getInstance();
                timing.clientState(mc.getFps(),mc.isWindowActive(),mc.isPaused());
                try { return createCapabilitySnapshot(radius,timing,coordination,clock); }
                catch(ClientActionRequest.Rejected failure) { return new EndpointResult(failure.httpStatus,failure.response()); }
                catch(ObservationClientClock.Unavailable failure) {return new EndpointResult(409,error(failure.getMessage()));}
            }),MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange,result.status(),result.body(),timing);
        } catch(Exception failure) { respondMinecraftFailure(exchange,"capability_snapshot_failed",failure,timing); }
    }

    private static void handleCompactObservation(HttpExchange exchange) throws IOException {
        if(!requireControlAccess(exchange,"/control/compact-observation","GET"))return;
        final CompactObservation.Request request;
        try {request=CompactObservation.parse(exchange.getRequestURI().getRawQuery());}
        catch(RuntimeException invalid){respondJson(exchange,400,error("compact_observation_invalid_query"));return;}
        try {
            EndpointResult result=callOnMinecraftThread(()->{
                long started=System.nanoTime();Minecraft mc=Minecraft.getInstance();
                var diagnostic=new CompactObservation.Diagnostic(request,started);
                try {
                    var before=ObservationClockBridge.sample();var context=capabilityContext(mc);
                    diagnostic.enter("terrain_ids",System.nanoTime());JsonObject terrain=TerrainReader.compact(request.radius(),diagnostic);CompactObservation.budget(started,System.nanoTime());
                    diagnostic.enter("state",System.nanoTime());EndpointResult snapshot=createCapabilitySnapshot(0,new BridgeReadTiming(),false,true,true,diagnostic);
                    if(snapshot.status()!=200)return snapshot;
                    diagnostic.enter("final_context",System.nanoTime());CompactObservation.require(context.same(capabilityContext(mc)),"context_changed");
                    var after=ObservationClockBridge.sample();
                    CompactObservation.budget(started,System.nanoTime());
                    diagnostic.enter("projection",System.nanoTime());JsonObject body=CompactObservation.project(request,snapshot.body(),terrain,before,after,System.nanoTime()-started);
                    CompactObservation.complete(body,diagnostic,System.nanoTime());
                    CompactObservation.budget(started,System.nanoTime());
                    return new EndpointResult(200,body);
                } catch(ClientActionRequest.Rejected failure){JsonObject body=failure.response();body.add("compact_observation_diagnostic",diagnostic.json(System.nanoTime()));return new EndpointResult(failure.httpStatus,body);}
                catch(TerrainScan.Failure failure){return new EndpointResult(failure.status,error(failure.getMessage()));}
                catch(ObservationClientClock.Unavailable failure){return new EndpointResult(409,error(failure.getMessage()));}
            },MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange,result.status(),result.body());
        } catch(Exception failure){respondMinecraftFailure(exchange,"compact_observation_failed",failure);}
    }

    private static CapabilitySnapshot.Context capabilityContext(Minecraft mc) {
        return new CapabilitySnapshot.Context(mc.level,mc.player,mc.gameMode,mc.screen,
                mc.player==null?null:mc.player.containerMenu,WorldGeneration.current(mc.level),
                mc.player==null?null:mc.player.getUUID().toString(),
                mc.level==null?null:mc.level.dimension().location().toString(),ClientActions.session(),
                mc.level==null?-1:mc.level.getGameTime());
    }

    private static EndpointResult createCapabilitySnapshot(double radius,BridgeReadTiming timing,boolean coordination) {
        return createCapabilitySnapshot(radius,timing,coordination,false);
    }
    private static EndpointResult createCapabilitySnapshot(double radius,BridgeReadTiming timing,boolean coordination,boolean clock) {
        return createCapabilitySnapshot(radius,timing,coordination,clock,false);
    }
    private static EndpointResult createCapabilitySnapshot(double radius,BridgeReadTiming timing,boolean coordination,boolean clock,boolean compact) {
        return createCapabilitySnapshot(radius,timing,coordination,clock,compact,null);
    }
    private static EndpointResult createCapabilitySnapshot(double radius,BridgeReadTiming timing,boolean coordination,boolean clock,boolean compact,CompactObservation.Diagnostic diagnostic) {
        Minecraft mc=Minecraft.getInstance();
        if(!mc.isSameThread())throw new IllegalStateException("Capability snapshot requires client thread");
        if(mc.player==null || mc.level==null || mc.gameMode==null)return new EndpointResult(409,error(clock?"observation_clock_unavailable":"not_in_world"));
        CapabilitySnapshot.Context before=capabilityContext(mc);
        ObservationClientClock.Stamp clockBefore=clock?ObservationClockBridge.sample():null;
        // One actual registry/budget observation. Repeated ordinary status() calls would count
        // extra budget boundaries, so all three sibling views share this original observation.
        JsonObject action=ClientActions.status(null);
        JsonObject status=createControlStatus(action);
        EndpointResult state=createStateSnapshot(radius,timing,coordination,action,compact,diagnostic);
        if(state.status()!=200)return state;
        JsonObject screen=createScreenSnapshot();
        CapabilitySnapshot.Context after=capabilityContext(mc);
        JsonObject bundle=CapabilitySnapshot.assemble(before,after,status,action,state.body(),screen,
                ClientActions.statusWithoutObservation());
        if(clock)ObservationClockBridge.snapshot(bundle,clockBefore,ObservationClockBridge.sample());
        return new EndpointResult(200,bundle);
    }

    /** Read-only size preview for the distinct observed movement profile. Never registers or dispatches an action.
     * Uses the same three action-bearing sibling builders and exact final HTTP serializer.
     * Caller must repeat its original raw/owner/time fences after every preview hook returns.
     * The reserve covers this controller's bounded terminal metadata, not arbitrary future world-state growth.
     */
    static void requireScopedMovementResponseBudget(JsonObject proposedAction) {
        Minecraft mc=Minecraft.getInstance();
        if(!mc.isSameThread())throw new ClientActionRequest.Rejected(409,"scoped_movement_preview_thread");
        try {
            CapabilitySnapshot.Context before=capabilityContext(mc);
            JsonObject status=createControlStatus(proposedAction);
            EndpointResult state=createStateSnapshot(8,new BridgeReadTiming(),false,proposedAction);
            if(state.status()!=200)throw new ClientActionRequest.Rejected(409,"scoped_movement_preview_state_unavailable");
            JsonObject screen=createScreenSnapshot();
            CapabilitySnapshot.Context after=capabilityContext(mc);
            JsonObject bundle=CapabilitySnapshot.assemble(before,after,status,proposedAction,state.body(),screen,proposedAction);
            JsonObject standalone=clientActionResult(()->proposedAction.deepCopy(),true).body();
            // The shared assembler projects one authoritative movement witness and two fixed local refs.
            // Terminal action metadata still occurs three times, so all existing reserves remain unchanged.
            int one=BridgeJson.toJson(standalone).getBytes(StandardCharsets.UTF_8).length;
            int three=BridgeJson.toJson(bundle).getBytes(StandardCharsets.UTF_8).length;
            try {
                boolean spatial=proposedAction.getAsJsonObject("result").getAsJsonObject("scoped_native_preflight")
                    .get("profile").getAsString().equals(ScopedRouteThreatPolicy.PROFILE);
                if(spatial)ScopedRouteThreatPolicy.requireResponseSizes(one,three,MAX_JSON_BYTES);
                else ScopedEntityPolicy.requireResponseSizes(one,three,MAX_JSON_BYTES);
            }
            catch(IllegalArgumentException oversized){
                // Diagnostic rendering must never erase an already known size refusal.
                JsonObject diagnostic=null;
                try {diagnostic=ScopedMovementWire.sizeDiagnostic(proposedAction,one,three,MAX_JSON_BYTES);}
                catch(RuntimeException unavailable) { /* Preserve the original refusal even if diagnostics are unavailable. */ }
                throw new ClientActionRequest.Rejected(409,oversized.getMessage(),null,diagnostic);
            }
        } catch(ClientActionRequest.Rejected known){throw known;}
        catch(Exception unknown){throw new ClientActionRequest.Rejected(409,"scoped_movement_response_preview_failed");}
    }

    private static void handleControlTerrain(HttpExchange exchange) throws IOException {
        BridgeReadTiming timing = new BridgeReadTiming();
        if (!requireControlAccess(exchange, "/control/terrain", "GET")) return;
        final TerrainQuery query;
        try {
            query = TerrainQuery.parse(exchange.getRequestURI().getRawQuery());
        } catch (IllegalArgumentException e) {
            respondJson(exchange, 400, error("invalid_terrain_query", e.getMessage()));
            return;
        }
        try {
            timing.dispatchRequested();
            EndpointResult result = TERRAIN_DISPATCH.call(
                    task -> Minecraft.getInstance().execute(() -> ClientInputIsolation.syntheticDispatch(task)), () -> timing.call(() -> {
                Minecraft mc = Minecraft.getInstance();
                timing.clientState(mc.getFps(), mc.isWindowActive(), mc.isPaused());
                try {
                    JsonObject body = protocolOk();
                    for (var entry : TerrainReader.read(query).entrySet()) body.add(entry.getKey(), entry.getValue());
                    return new EndpointResult(200, body);
                } catch (TerrainScan.Failure e) {
                    return new EndpointResult(e.status, error(e.getMessage()));
                }
            }), MINECRAFT_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (result.status() == 429) exchange.getResponseHeaders().set("Retry-After", "1");
            respondJson(exchange, result.status(), result.body(), timing);
        } catch (TerrainScan.Failure e) {
            exchange.getResponseHeaders().set("Retry-After", "1");
            respondJson(exchange, e.status, error(e.getMessage()), timing);
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "terrain_failed", e, timing);
        }
    }

    /** New versioned lifecycle only; status/fetch/cancel do not dispatch game work. */
    private static void handleTerrainAcquisition(HttpExchange exchange) throws IOException {
        String path=exchange.getRequestURI().getPath();
        String operation=path.startsWith(TerrainAcquisitionRequest.ROOT)?path.substring(TerrainAcquisitionRequest.ROOT.length()):"";
        if(!java.util.Set.of("prepare","activate","status","fetch","cancel").contains(operation)) {
            respondJson(exchange,404,error("unknown_endpoint"));return;
        }
        String method=operation.equals("status")||operation.equals("fetch")?"GET":"POST";
        if(!requireControlAccess(exchange,TerrainAcquisitionRequest.ROOT+operation,method))return;
        TerrainAcquisitionRequest.Owner owner=null;
        boolean startsWork=false;
        try {
            byte[] response;
            String query=exchange.getRequestURI().getRawQuery();
            if(method.equals("POST") && query!=null)throw new TerrainScan.Failure(400,"acquisition_invalid_query");
            if(operation.equals("status")) {
                owner=TerrainAcquisitionRequest.status(query);response=TERRAIN_ACQUISITION.status(owner);
            } else if(operation.equals("fetch")) {
                var request=TerrainAcquisitionRequest.fetch(query);owner=request.owner();response=TERRAIN_ACQUISITION.fetch(request);
            } else {
                JsonObject body;
                try {body=TerrainAcquisitionRequest.parseBody(new String(readBody(exchange),StandardCharsets.UTF_8));}
                catch(RequestException rejected){respondRequestFailure(exchange,rejected);return;}
                if(operation.equals("prepare")) {
                    var request=TerrainAcquisitionRequest.prepare(body);owner=request.owner();startsWork=true;
                    response=TERRAIN_ACQUISITION.prepare(request);
                } else if(operation.equals("activate")) {
                    var request=TerrainAcquisitionRequest.activate(body);owner=request.owner();startsWork=true;
                    response=TERRAIN_ACQUISITION.activate(request);
                } else {
                    var request=TerrainAcquisitionRequest.cancel(body);owner=request.owner();response=TERRAIN_ACQUISITION.cancel(request);
                }
            }
            // Immutable captured bytes: no reserialization, clock headers, or native dispatch here.
            respondBytes(exchange,200,"application/json; charset=utf-8",response);
        } catch(TerrainScan.Failure failure) {
            respondJson(exchange,failure.status,error(failure.getMessage()));
        } catch(IOException transport) {
            if(startsWork && owner!=null)TERRAIN_ACQUISITION.transportFailed(owner);
            throw transport;
        } catch(Exception failure) {
            if(startsWork && owner!=null)TERRAIN_ACQUISITION.transportFailed(owner);
            Throwable cause=failure instanceof ExecutionException?failure.getCause():failure;
            if(cause instanceof TerrainScan.Failure rejected)respondJson(exchange,rejected.status,error(rejected.getMessage()));
            else if(cause instanceof ClientActionRequest.Rejected rejected)respondJson(exchange,rejected.httpStatus,rejected.response());
            else respondMinecraftFailure(exchange,"acquisition_failed",failure);
        }
    }

    static void terrainAcquisitionTick() { TERRAIN_ACQUISITION.tick(); }

    private static final class AcquisitionSource implements TerrainAcquisition.Source {
        private Minecraft client() {
            Minecraft mc=Minecraft.getInstance();
            if(!mc.isSameThread())throw new IllegalStateException("minecraft_thread_required");
            if(mc.level==null || mc.player==null || mc.gameMode==null)throw new TerrainScan.Failure(409,"not_in_world");
            return mc;
        }
        @Override public TerrainAcquisition.Context context() {return context(false);}
        @Override public TerrainAcquisition.Context context(boolean clock) {
            Minecraft mc=client();NavigationPositionGuard.observe(mc);
            JsonObject value=new JsonObject();
            value.addProperty("run_id",runId());value.addProperty("process_id",ProcessHandle.current().pid());
            value.addProperty("world_generation",WorldGeneration.current(mc.level));
            value.addProperty("dimension",mc.level.dimension().location().toString());
            value.addProperty("player_uuid",mc.player.getUUID().toString());value.addProperty("action_session",ClientActions.session());
            JsonObject origin=new JsonObject();BlockPos pos=mc.player.blockPosition();
            origin.addProperty("x",pos.getX());origin.addProperty("y",pos.getY());origin.addProperty("z",pos.getZ());value.add("origin",origin);
            value.addProperty("navigation_epoch",NavigationPositionGuard.epoch());
            return new TerrainAcquisition.Context(mc.level,mc.player,mc.gameMode,mc.screen,mc.player.containerMenu,
                    config(),value,mc.level.getGameTime(),clock?ObservationClockBridge.sample():null);
        }
        @Override public TerrainAcquisition.Capture capture() {return capture(false);}
        @Override public TerrainAcquisition.Capture capture(boolean clock) {
            client();EndpointResult result=createCapabilitySnapshot(48,new BridgeReadTiming(),false,clock);
            if(result.status()!=200) {
                String code=result.body().has("error")?result.body().get("error").getAsString():"acquisition_snapshot_failed";
                throw new TerrainScan.Failure(result.status(),code);
            }
            return new TerrainAcquisition.Capture(result.body(),context(clock));
        }
        @Override public boolean eligible(long now) { client();return TerrainReader.acquisitionEligible(now); }
        @Override public TerrainAcquisition.Page read(String cursor) {return read(cursor,false);}
        @Override public TerrainAcquisition.Page read(String cursor,boolean clock) {
            client();TerrainQuery query=cursor==null?new TerrainQuery(4,4,1024,null,true,clock):
                    TerrainQuery.parse("cursor="+cursor+(clock?"&observation_clock="+ObservationClientClock.CONTRACT:""));
            JsonObject body=protocolOk();
            for(var entry:TerrainReader.read(query).entrySet())body.add(entry.getKey(),entry.getValue());
            return new TerrainAcquisition.Page(body,TerrainReader.lastActualStart(),System.nanoTime());
        }
    }

    private static void handleScanStart(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/scan", "POST")) return;
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        final LoadedScanRequest request;
        try { request = LoadedScanRequest.parse(body); }
        catch (ClientActionRequest.Rejected failure) {
            respondJson(exchange, failure.httpStatus, error(failure.getMessage())); return;
        }
        respondActionOperation(exchange, () -> LoadedWorldScanner.start(request), true);
    }

    private static void handleScanStatus(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/scan/status", "GET")) return;
        final String id;
        try {
            String raw = exchange.getRequestURI().getRawQuery();
            if (raw == null || !raw.matches("id=[A-Za-z0-9_-]{1,64}")) throw new IllegalArgumentException();
            id = raw.substring(3);
        } catch (IllegalArgumentException failure) {
            respondJson(exchange, 400, error("invalid_scan_id")); return;
        }
        respondActionOperation(exchange, () -> LoadedWorldScanner.status(id), false);
    }

    private static void handleScanCancel(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/scan/cancel", "POST")) return;
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        final String id;
        try { LoadedScanRequest.keys(body, java.util.Set.of("id")); id = LoadedScanRequest.id(body); }
        catch (ClientActionRequest.Rejected failure) {
            respondJson(exchange, failure.httpStatus, error(failure.getMessage())); return;
        }
        respondActionOperation(exchange, () -> LoadedWorldScanner.cancel(id), false);
    }

    private static void handleControlScreen(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/screen", "GET")) return;

        try {
            JsonObject screen = callOnMinecraftThread(
                    BridgeServer::createScreenSnapshot,
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, 200, screen);
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "screen_failed", e);
        }
    }

    private static void handleDefenseArm(HttpExchange exchange) throws IOException {
        if(!requireControlAccess(exchange,"/control/defense/arm","POST"))return;
        JsonObject body=readJsonObjectOrRespond(exchange,false);if(body==null)return;
        respondActionOperation(exchange,()->NativeReactiveGuard.arm(body),false);
    }
    private static void handleDefenseStatus(HttpExchange exchange) throws IOException {
        if(!requireControlAccess(exchange,"/control/defense/status","GET"))return;
        respondActionOperation(exchange,NativeReactiveGuard::status,false);
    }
    private static void handleDefenseDisarm(HttpExchange exchange) throws IOException {
        if(!requireControlAccess(exchange,"/control/defense/disarm","POST"))return;
        JsonObject body=readJsonObjectOrRespond(exchange,false);if(body==null)return;
        respondActionOperation(exchange,()->NativeReactiveGuard.disarm(body),false);
    }
    private static void handleBackupStart(HttpExchange exchange) throws IOException {
        if(!requireControlAccess(exchange,"/control/backup/start","POST"))return;
        JsonObject body=readJsonObjectOrRespond(exchange,false);if(body==null)return;
        respondActionOperation(exchange,()->NativeWorldBackup.start(body),false);
    }
    private static void handleBackupStatus(HttpExchange exchange) throws IOException {
        if(!requireControlAccess(exchange,"/control/backup/status","GET"))return;
        String raw=exchange.getRequestURI().getRawQuery();
        if(raw==null||!raw.matches("job_id=[0-9a-fA-F-]{36}")){respondJson(exchange,400,error("backup_job_id_query_required"));return;}
        try {respondJson(exchange,200,NativeWorldBackup.status(raw.substring(7)));}
        catch(ClientActionRequest.Rejected denied){respondJson(exchange,denied.httpStatus,error(denied.getMessage()));}
    }

    private static void handleBackupScheduler(HttpExchange exchange) throws IOException {
        if(!requireControlAccess(exchange,"/control/backup/scheduler","GET"))return;
        if(exchange.getRequestURI().getRawQuery()!=null){respondJson(exchange,400,error("backup_scheduler_no_query"));return;}
        respondJson(exchange,200,NativeWorldBackup.schedulerStatus());
    }

    private static void handleClientAction(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/action", "POST")) return;
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        final ClientActionRequest request;
        try { request = ClientActionRequest.parse(body); }
        catch (ClientActionRequest.Rejected failure) {
            respondJson(exchange, failure.httpStatus, error(failure.getMessage())); return;
        }
        respondActionOperation(exchange, () -> NativeAdmission.run(body,false,ClientActions.session(),() -> ClientActions.start(request)), true);
    }

    private static void handleScopedClientAction(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/scoped-action", "POST")) return;
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        // Capture, parse, validate after hooks and admit inside this one callback.
        respondActionOperation(exchange, () -> NativeAdmission.run(body,true,ClientActions.session(),() -> ScopedNativePreflight.start(body)), true);
    }

    private static void handleClientActionStatus(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/action/status", "GET")) return;
        String id = null;
        try {
            String query = exchange.getRequestURI().getRawQuery();
            if (query != null) for (String part : query.split("&")) {
                String[] pair = part.split("=", 2);
                if (!URLDecoder.decode(pair[0], StandardCharsets.UTF_8).equals("action_id") || id != null || pair.length != 2)
                    throw new IllegalArgumentException();
                id = URLDecoder.decode(pair[1], StandardCharsets.UTF_8);
            }
        } catch (IllegalArgumentException failure) {
            respondJson(exchange, 400, error("invalid_query")); return;
        }
        final String actionId = id;
        respondActionOperation(exchange, () -> ClientActions.status(actionId), false);
    }

    private static void handleClientActionCancel(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/action/cancel", "POST")) return;
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        final String id, expectedSession;
        try {
            id = ClientActionRequest.string(body, "action_id");
            expectedSession = body.has("expected_action_session")
                    ? ClientActionRequest.string(body, "expected_action_session") : null;
        }
        catch (ClientActionRequest.Rejected failure) {
            respondJson(exchange, failure.httpStatus, error(failure.getMessage())); return;
        }
        respondActionOperation(exchange, () -> ClientActions.cancelId(id, expectedSession), false);
    }

    private static void handleManagedNavigation(HttpExchange exchange) throws IOException {
        String path=exchange.getRequestURI().getPath(),operation=path.substring(path.lastIndexOf('/')+1);
        if(!java.util.Set.of("start","cancel","status").contains(operation)){respondJson(exchange,404,error("unknown_endpoint"));return;}
        if(!requireControlAccess(exchange,"/control/managed-navigation/"+operation,operation.equals("status")?"GET":"POST"))return;
        if(operation.equals("status")){respondActionOperation(exchange,NativeManagedNavigation::status,false);return;}
        JsonObject body=readJsonObjectOrRespond(exchange,false);if(body==null)return;
        final ManagedNavigationLease.Request request;
        try{request=ManagedNavigationControl.parse(body);}catch(ClientActionRequest.Rejected e){respondJson(exchange,e.httpStatus,error(e.getMessage()));return;}
        respondActionOperation(exchange,()->operation.equals("start")?NativeManagedNavigation.start(request):NativeManagedNavigation.cancel(request),false);
    }

    private static void handleExternalNavigation(HttpExchange exchange) throws IOException {
        String path=exchange.getRequestURI().getPath(),operation=path.substring(path.lastIndexOf('/')+1);
        if(!java.util.Set.of("stop","status").contains(operation)){respondJson(exchange,404,error("unknown_endpoint"));return;}
        if(!requireControlAccess(exchange,"/control/external-navigation/"+operation,operation.equals("status")?"GET":"POST"))return;
        if(operation.equals("status")){respondActionOperation(exchange,NativeExternalNavigation::status,false);return;}
        JsonObject body=readJsonObjectOrRespond(exchange,false);if(body==null)return;
        final ExternalNavigationLease.Request request;
        try{request=ExternalNavigationControl.parse(body);}catch(ClientActionRequest.Rejected e){respondJson(exchange,e.httpStatus,error(e.getMessage()));return;}
        respondActionOperation(exchange,()->NativeExternalNavigation.stop(request),false);
    }

    private static void handleFallAdjudication(HttpExchange exchange) throws IOException {
        String root="/control/fall-rescue/adjudication",path=exchange.getRequestURI().getPath();
        if(path.equals(root+"/prepare")){
            if(!requireControlAccess(exchange,path,"GET"))return;
            if(exchange.getRequestURI().getRawQuery()!=null){respondJson(exchange,400,error("unexpected_query"));return;}
            respondActionOperation(exchange,NativeFallRescue::adjudicationSnapshot,false);return;
        }
        if(path.equals(root+"/status")){
            if(!requireControlAccess(exchange,path,"GET"))return;
            String query=exchange.getRequestURI().getRawQuery();
            if(query==null||!query.matches("adjudication_id=[A-Za-z0-9_-]{1,80}")){respondJson(exchange,400,error("fall_adjudication_id_required"));return;}
            String id=query.substring("adjudication_id=".length());
            respondActionOperation(exchange,()->NativeFallRescue.adjudicationReceipt(id),false);return;
        }
        if(!path.equals(root)){respondJson(exchange,404,error("unknown_endpoint"));return;}
        if(!requireControlAccess(exchange,root,"POST"))return;
        if(exchange.getRequestURI().getRawQuery()!=null){respondJson(exchange,400,error("unexpected_query"));return;}
        JsonObject body=readJsonObjectOrRespond(exchange,false);if(body==null)return;
        respondActionOperation(exchange,()->NativeFallRescue.adjudicate(FallRescueAdjudication.parse(body)),false);
    }

    private static void handleFallRescue(HttpExchange exchange) throws IOException {
        String path=exchange.getRequestURI().getPath();
        String operation=path.substring(path.lastIndexOf('/')+1);
        if(!java.util.Set.of("arm","renew","disarm","status").contains(operation)) { respondJson(exchange,404,error("unknown_endpoint")); return; }
        if(!requireControlAccess(exchange,"/control/fall-rescue/"+operation,operation.equals("status")?"GET":"POST"))return;
        if(operation.equals("status")){respondActionOperation(exchange,NativeFallRescue::status,false);return;}
        JsonObject body=readJsonObjectOrRespond(exchange,false);if(body==null)return;
        respondActionOperation(exchange,()->FallRescueControl.apply(operation,body,new FallRescueControl.Adapter(){
            public JsonObject arm(FallRescuePolicy.Arm request){return NativeFallRescue.arm(request);}
            public JsonObject renew(FallRescuePolicy.Renew request){return NativeFallRescue.renew(request);}
            public JsonObject disarm(FallRescuePolicy.Stop request){return NativeFallRescue.disarm(request);}
            public JsonObject status(){return NativeFallRescue.status();}
        }),false);
    }

    private static void handleEncounterPause(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/pause", "POST")) return;
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        final EncounterPause.Request request;
        try { request = EncounterPause.parse(body); }
        catch (ClientActionRequest.Rejected failure) {
            respondJson(exchange, failure.httpStatus, error(failure.getMessage())); return;
        }
        respondActionOperation(exchange, () -> pauseEncounterOnGameThread(request), false);
    }

    static void requireEncounterPauseAdmission() {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.level == null || mc.gameMode == null
                || !mc.hasSingleplayerServer() || mc.getSingleplayerServer() == null
                || mc.getSingleplayerServer().isPublished())
            throw new ClientActionRequest.Rejected(409, "pause_requires_private_singleplayer");
    }

    static JsonObject pauseEncounterOnGameThread(EncounterPause.Request request) {
        return pauseEncounterOnGameThread(request,false);
    }

    static JsonObject pauseEncounterTerminalOnGameThread(EncounterPause.Request request) {
        return pauseEncounterOnGameThread(request,true);
    }

    private static JsonObject pauseEncounterOnGameThread(EncounterPause.Request request,boolean originalTerminalHookCall) {
        if(!originalTerminalHookCall){NativeReactiveGuard.stop("explicit_pause");NativeFallRescue.stop("explicit_pause");}
        return EncounterPause.apply(request, new EncounterPause.Adapter() {
            final Minecraft mc = Minecraft.getInstance();
            public EncounterPause.Context context(String actionId) {
                JsonObject expected = null;
                try { expected = ClientActions.status(actionId); }
                catch (ClientActionRequest.Rejected failure) { if (failure.httpStatus != 404) throw failure; }
                boolean local = mc.player != null && mc.level != null && mc.gameMode != null
                        && mc.hasSingleplayerServer() && mc.getSingleplayerServer() != null
                        && !mc.getSingleplayerServer().isPublished();
                return new EncounterPause.Context(local, ClientActions.session(),
                        mc.level == null ? null : WorldGeneration.current(mc.level),
                        mc.player == null ? null : mc.player.getUUID().toString(),
                        GuardedGameMovement.LEASES.status().ownerRequestId() != null,
                        mc.screen == null ? null : mc.screen.getClass().getName(),
                        ClientActions.status(null), expected);
            }
            public void openPauseScreen() { mc.pauseGame(false); }
            public boolean pauseScreenInstalled() { return mc.screen != null && mc.screen.getClass() == PauseScreen.class; }
            public boolean clientPaused() { return mc.isPaused(); }
            public void cancelEncounter() { ClientActions.cancel("encounter_paused_risk_remaining"); }
            public JsonObject action(String actionId) { return ClientActions.status(actionId); }
        },originalTerminalHookCall);
    }

    private static void respondActionOperation(HttpExchange exchange, Callable<JsonObject> operation, boolean start) throws IOException {
        try {
            EndpointResult result = callOnMinecraftThread(() -> clientActionResult(operation,start), MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, result.status(), result.body());
        } catch (Exception failure) { respondMinecraftFailure(exchange, "client_action_failed", failure); }
    }

    static EndpointResult clientActionResult(Callable<JsonObject> operation,boolean start) throws Exception {
        return ActionResponses.result(operation,start);
    }

    /** Pure existing response wrapper; loading this nested class does not initialize the server. */
    static final class ActionResponses {
        static EndpointResult result(Callable<JsonObject> operation,boolean start) throws Exception {
            try {
                JsonObject response=operation.call();
                response.addProperty("protocol",PROTOCOL_NAME);response.addProperty("schema_version",PROTOCOL_SCHEMA_VERSION);
                boolean running=response.has("status") && response.get("status").getAsString().equals("running");
                return new EndpointResult(start && running?202:200,response);
            } catch(ClientActionRequest.Rejected failure) {
                return new EndpointResult(failure.httpStatus,failure.response());
            }
        }
        private ActionResponses() { }
    }

    private static void handleControlKey(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/key", "POST")) return;

        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;

        final String mapping;
        final String action;
        final boolean exact;
        try {
            mapping = requiredString(body, "mapping");
            action = requiredString(body, "action").trim().toLowerCase(Locale.ROOT);
            exact = optionalBoolean(body, "exact", false);
            if (mapping.isBlank()) {
                throw new RequestException(400, "invalid_mapping", "mapping must not be blank");
            }
            if (!action.equals("down") && !action.equals("up") && !action.equals("click")) {
                throw new RequestException(400, "invalid_action", "action must be down, up, or click");
            }
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return;
        }

        try {
            EndpointResult result = callOnMinecraftThread(
                    () -> NativeReactiveGuard.directInput(() -> { ClientActions.directTakeover(); return applyKeyAction(mapping, action, exact); }),
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, result.status(), result.body());
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "key_action_failed", e);
        }
    }

    private static void handleControlRawKey(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/raw-key", "POST")) return;

        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;

        final String key;
        final String action;
        try {
            key = requiredString(body, "key");
            action = requiredString(body, "action").trim().toLowerCase(Locale.ROOT);
            if (key.isBlank()) {
                throw new RequestException(400, "invalid_key", "key must not be blank");
            }
            if (!action.equals("down") && !action.equals("up") && !action.equals("click")) {
                throw new RequestException(400, "invalid_action", "action must be down, up, or click");
            }
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return;
        }

        try {
            EndpointResult result = callOnMinecraftThread(
                    () -> NativeReactiveGuard.directInput(() -> { ClientActions.directTakeover(); return applyRawKeyAction(key, action); }),
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, result.status(), result.body());
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "raw_key_action_failed", e);
        }
    }

    private static void handleControlGuardedAction(HttpExchange exchange) throws IOException {
        final long receivedNanos = System.nanoTime(); // Includes body parsing in the TTL.
        final long bridgeEpoch = GUARDED_ACTIONS.epoch(); // Captured before parsing or queueing.
        if (!requireControlAccess(exchange, "/control/guarded-action", "POST")) return;
        if (exchange.getHttpContext().getServer() != server) {
            respondJson(exchange, 409, error("bridge_lifecycle_changed"));
            return;
        }
        if (!GuardedGameActions.enabled()) {
            respondJson(exchange, 409, error("guarded_actions_disabled"));
            return;
        }
        if (exchange.getRequestURI().getRawQuery() != null) {
            respondJson(exchange, 400, error("unexpected_query"));
            return;
        }
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        final GuardedAction.Request request;
        try {
            String action = requiredString(body, "action");
            java.util.Set<String> fields = new java.util.HashSet<>(java.util.Set.of(
                    "guard_schema_version", "action", "expected_world_generation", "expected_player_uuid",
                    "expected_target_uuid", "expected_crosshair_uuid", "ttl_ms"));
            if (action.equals("look")) { fields.add("yaw"); fields.add("pitch"); }
            GuardedAction.require(body.keySet().equals(fields), "unexpected_or_missing_field");
            GuardedAction.require(optionalInteger(body, "guard_schema_version", -1) == GuardedAction.SCHEMA,
                    "unsupported_guard_schema");
            String crosshair = body.get("expected_crosshair_uuid").isJsonNull()
                    ? null : requiredString(body, "expected_crosshair_uuid");
            request = new GuardedAction.Request(action,
                    requiredString(body, "expected_world_generation"), requiredString(body, "expected_player_uuid"),
                    requiredString(body, "expected_target_uuid"), crosshair,
                    optionalInteger(body, "ttl_ms", -1),
                    action.equals("look") ? requiredFiniteDouble(body, "yaw") : 0,
                    action.equals("look") ? requiredFiniteDouble(body, "pitch") : 0);
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return;
        } catch (GuardedAction.Rejected e) {
            respondJson(exchange, 400, error(e.getMessage()));
            return;
        }
        try {
            GuardedDispatch.Ticket<GuardedGameActions.Outcome> ticket = GUARDED_ACTIONS.submit(
                    Minecraft.getInstance()::execute, receivedNanos, request.ttlMs(), bridgeEpoch,
                    active -> GuardedGameActions.apply(request, active));
            GuardedGameActions.Outcome outcome = ticket.await();
            JsonObject response = protocolOk();
            response.addProperty("guard_schema_version", GuardedAction.SCHEMA);
            response.addProperty("action", outcome.action());
            response.addProperty("dispatched", true);
            response.addProperty("damage_confirmed", false);
            response.addProperty("world_generation", outcome.worldGeneration());
            response.addProperty("player_uuid", outcome.playerUuid());
            response.addProperty("target_uuid", outcome.targetUuid());
            response.addProperty("yaw", outcome.yaw());
            response.addProperty("pitch", outcome.pitch());
            respondJson(exchange, 200, response);
        } catch (TimeoutException e) {
            respondJson(exchange, 408, error("guarded_action_expired"));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            respondJson(exchange, 503, error("request_interrupted"));
        } catch (Exception e) {
            Throwable cause = e instanceof ExecutionException && e.getCause() != null ? e.getCause() : e;
            if (cause instanceof GuardedAction.Rejected rejected) {
                int status = rejected.getMessage().equals("guarded_action_busy") ? 429
                        : rejected.getMessage().equals("guarded_action_expired") ? 408 : 409;
                respondJson(exchange, status, error(rejected.getMessage()));
            } else {
                respondJson(exchange, 500, error("guarded_action_failed"));
            }
        }
    }

    private static void handleGuardedMovement(HttpExchange exchange) throws IOException {
        final long receivedNanos = System.nanoTime();
        final String entrySession = GuardedGameMovement.LEASES.session();
        if (!requireControlAccess(exchange, "/control/guarded-movement", "POST")) return;
        if (exchange.getHttpContext().getServer() != server) {
            respondJson(exchange, 409, error("bridge_lifecycle_changed")); return;
        }
        if (!GuardedGameMovement.enabled()) {
            respondJson(exchange, 409, error("guarded_movement_disabled")); return;
        }
        if (exchange.getRequestURI().getRawQuery() != null) {
            respondJson(exchange, 400, error("unexpected_query")); return;
        }
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        final GuardedMovement.Request request;
        try {
            GuardedAction.require(body.keySet().equals(java.util.Set.of("movement_schema_version", "action",
                    "session", "request_id", "observation_id", "expected_world_generation", "expected_player_uuid", "expected_tick",
                    "expected_x", "expected_y", "expected_z", "expected_yaw", "ttl_ms", "duration_ms")),
                    "unexpected_or_missing_field");
            GuardedAction.require(optionalInteger(body, "movement_schema_version", -1) == GuardedMovement.SCHEMA,
                    "unsupported_movement_schema");
            GuardedAction.require(requiredString(body, "action").equals("forward_sample"), "invalid_action");
            double tick = requiredFiniteDouble(body, "expected_tick");
            GuardedAction.require(tick >= 0 && tick <= 9_007_199_254_740_991d && tick == Math.rint(tick), "invalid_expected_tick");
            request = new GuardedMovement.Request(requiredString(body, "session"), requiredString(body, "request_id"), requiredString(body, "observation_id"),
                    requiredString(body, "expected_world_generation"), requiredString(body, "expected_player_uuid"),
                    (long) tick, requiredFiniteDouble(body, "expected_x"), requiredFiniteDouble(body, "expected_y"),
                    requiredFiniteDouble(body, "expected_z"), requiredFiniteDouble(body, "expected_yaw"),
                    optionalInteger(body, "ttl_ms", -1), optionalInteger(body, "duration_ms", -1));
        } catch (RequestException failure) { respondRequestFailure(exchange, failure); return;
        } catch (GuardedAction.Rejected failure) { respondJson(exchange, 400, error(failure.getMessage())); return; }
        GuardedMovement.Ticket movementTicket = null;
        try {
            movementTicket = GuardedGameMovement.LEASES.submit(request, receivedNanos, entrySession);
            GuardedMovement.Outcome outcome = movementTicket.await();
            boolean ok = outcome.reason().equals("sample_released");
            JsonObject response = ok ? protocolOk() : error(outcome.reason());
            response.addProperty("movement_schema_version", GuardedMovement.SCHEMA);
            response.addProperty("request_id", outcome.requestId());
            response.addProperty("sampled", outcome.sampled());
            response.addProperty("released", outcome.released());
            response.addProperty("movement_confirmed", false);
            respondJson(exchange, ok ? 200 : outcome.reason().equals("movement_expired") ? 408 : 409, response);
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            JsonObject response = error("request_interrupted");
            GuardedMovement.Outcome outcome = movementTicket == null ? null : movementTicket.result.getNow(null);
            if (outcome != null) {
                response.addProperty("movement_schema_version", GuardedMovement.SCHEMA);
                response.addProperty("request_id", outcome.requestId());
                response.addProperty("sampled", outcome.sampled());
                response.addProperty("released", outcome.released());
                response.addProperty("movement_confirmed", false);
            }
            respondJson(exchange, 503, response);
        } catch (GuardedAction.Rejected failure) {
            int status = failure.getMessage().equals("movement_busy") ? 429 : failure.getMessage().equals("movement_expired") ? 408 : 409;
            respondJson(exchange, status, error(failure.getMessage()));
        } catch (Exception failure) { respondJson(exchange, 500, error("movement_failed")); }
    }

    private static void handleGuardedTurn(HttpExchange exchange) throws IOException {
        final long receivedNanos = System.nanoTime();
        final String entrySession = GuardedGameMovement.LEASES.session();
        if (!requireControlAccess(exchange, "/control/guarded-turn", "POST")) return;
        if (exchange.getHttpContext().getServer() != server) {
            respondJson(exchange, 409, error("bridge_lifecycle_changed")); return;
        }
        if (!GuardedGameTurning.enabled()) {
            respondJson(exchange, 409, error("guarded_turning_disabled")); return;
        }
        if (exchange.getRequestURI().getRawQuery() != null) {
            respondJson(exchange, 400, error("unexpected_query")); return;
        }
        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;
        final GuardedMovement.Request request;
        final double targetYaw;
        try {
            GuardedAction.require(body.keySet().equals(java.util.Set.of("turn_schema_version", "action",
                    "session", "request_id", "observation_id", "expected_world_generation", "expected_player_uuid", "expected_tick",
                    "expected_x", "expected_y", "expected_z", "expected_yaw", "ttl_ms", "target_yaw")),
                    "unexpected_or_missing_field");
            GuardedAction.require(optionalInteger(body, "turn_schema_version", -1) == GuardedGameTurning.SCHEMA,
                    "unsupported_turn_schema");
            GuardedAction.require(requiredString(body, "action").equals("yaw"), "invalid_action");
            double tick = requiredFiniteDouble(body, "expected_tick");
            GuardedAction.require(tick >= 0 && tick <= 9_007_199_254_740_991d && tick == Math.rint(tick), "invalid_expected_tick");
            int ttl = optionalInteger(body, "ttl_ms", -1);
            GuardedAction.require(ttl >= 1 && ttl <= GuardedMovement.MAX_TURN_TTL_MS, "invalid_turn_ttl_ms");
            targetYaw = requiredFiniteDouble(body, "target_yaw");
            GuardedAction.require(targetYaw >= -180 && targetYaw < 180, "invalid_target_yaw");
            request = new GuardedMovement.Request(requiredString(body, "session"), requiredString(body, "request_id"),
                    requiredString(body, "observation_id"), requiredString(body, "expected_world_generation"),
                    requiredString(body, "expected_player_uuid"), (long) tick, requiredFiniteDouble(body, "expected_x"),
                    requiredFiniteDouble(body, "expected_y"), requiredFiniteDouble(body, "expected_z"),
                    requiredFiniteDouble(body, "expected_yaw"), ttl, ttl);
            GuardedAction.require(Math.abs(Math.IEEEremainder(targetYaw - request.yaw(), 360)) <= GuardedMovement.MAX_TURN_STEP,
                    "turn_step_too_large");
        } catch (RequestException failure) { respondRequestFailure(exchange, failure); return;
        } catch (GuardedAction.Rejected failure) { respondJson(exchange, 400, error(failure.getMessage())); return; }
        GuardedMovement.Ticket turnTicket = null;
        try {
            turnTicket = GuardedGameTurning.submit(request, targetYaw, receivedNanos, entrySession);
            GuardedMovement.Outcome outcome = turnTicket.await();
            boolean ok = outcome.reason().equals("turn_dispatched");
            JsonObject response = turnOutcome(ok ? protocolOk() : error(outcome.reason()), outcome);
            respondJson(exchange, ok ? 200 : outcome.reason().equals("movement_expired") ? 408 : 409, response);
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            GuardedMovement.Outcome outcome = turnTicket == null ? null : turnTicket.result.getNow(null);
            respondJson(exchange, 503, turnOutcome(error("request_interrupted"), outcome));
        } catch (GuardedAction.Rejected failure) {
            int status = failure.getMessage().equals("movement_busy") ? 429 : failure.getMessage().equals("movement_expired") ? 408 : 409;
            respondJson(exchange, status, error(failure.getMessage()));
        } catch (Exception failure) { respondJson(exchange, 500, error("turn_failed")); }
    }

    private static JsonObject turnOutcome(JsonObject response, GuardedMovement.Outcome outcome) {
        if (outcome != null) {
            response.addProperty("turn_schema_version", GuardedGameTurning.SCHEMA);
            response.addProperty("request_id", outcome.requestId());
            response.addProperty("dispatched", outcome.turned());
            response.addProperty("released", outcome.released());
            response.addProperty("turn_confirmed", false);
        }
        return response;
    }

    private static void handleControlLook(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/look", "POST")) return;

        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;

        final double yaw;
        final double pitch;
        final boolean relative;
        final AimViewGuard guard;
        try {
            yaw = requiredFiniteDouble(body, "yaw");
            pitch = requiredFiniteDouble(body, "pitch");
            relative = optionalBoolean(body, "relative", false);
            guard = body.has("guard") ? AimViewGuard.parse(body.get("guard")) : null;
            if (guard != null && relative) throw new ClientActionRequest.Rejected(400, "guard_requires_absolute_look");
        } catch (ClientActionRequest.Rejected e) {
            respondJson(exchange, e.httpStatus, error(e.getMessage()));
            return;
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return;
        }

        try {
            EndpointResult result = callOnMinecraftThread(
                    () -> {
                        if (guard != null) return applyGuardedAimLook(yaw, pitch, guard);
                        return NativeReactiveGuard.directInput(()->{ClientActions.directTakeover(); return applyLook(yaw, pitch, relative);});
                    },
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, result.status(), result.body());
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "look_action_failed", e);
        }
    }

    private static void handleControlMouse(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/mouse", "POST")) return;

        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;

        final double x;
        final double y;
        final int button;
        final String action;
        final double scrollY;
        try {
            action = requiredString(body, "action").trim().toLowerCase(Locale.ROOT);
            if (!action.equals("move") && !action.equals("down") && !action.equals("up")
                    && !action.equals("release") && !action.equals("click") && !action.equals("scroll")) {
                throw new RequestException(400, "invalid_action",
                        "action must be move, down, up, release, click, or scroll");
            }
            boolean hasX = body.has("x");
            boolean hasY = body.has("y");
            if (hasX != hasY) {
                throw new RequestException(400, "incomplete_coordinates",
                        "x and y must either both be present or both be absent");
            }
            if (action.equals("move") && !hasX) {
                throw new RequestException(400, "missing_coordinates",
                        "move requires x and y");
            }
            x = hasX ? requiredBoundedCoordinate(body, "x") : Double.NaN;
            y = hasY ? requiredBoundedCoordinate(body, "y") : Double.NaN;
            button = optionalInteger(body, "button", 0);
            if (button < 0 || button > 7) {
                throw new RequestException(400, "invalid_button", "button must be between 0 and 7");
            }
            scrollY = action.equals("scroll") ? requiredFiniteDouble(body, "scrollY") : 0.0;
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return;
        }

        try {
            EndpointResult result = callOnMinecraftThread(
                    () -> NativeReactiveGuard.directInput(() -> { ClientActions.directTakeover(); return applyMouseAction(x, y, button, action, scrollY); }),
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, result.status(), result.body());
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "mouse_action_failed", e);
        }
    }

    private static void handleControlText(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/text", "POST")) return;

        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;

        final String text;
        final boolean submit;
        try {
            text = requiredString(body, "text");
            submit = optionalBoolean(body, "submit", false);
            validateScreenText(text);
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return;
        }

        try {
            EndpointResult result = callOnMinecraftThread(
                    () -> NativeReactiveGuard.directInput(() -> { ClientActions.directTakeover(); return applyScreenText(text, submit); }),
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, result.status(), result.body());
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "text_input_failed", e);
        }
    }

    private static void handleControlCommand(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/command", "POST")) return;

        JsonObject body = readJsonObjectOrRespond(exchange, false);
        if (body == null) return;

        final String command;
        try {
            command = normalizeCommand(requiredString(body, "command"));
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return;
        }

        try {
            EndpointResult result = callOnMinecraftThread(
                    () -> NativeReactiveGuard.directInput(() -> { ClientActions.directTakeover(); return applyCommand(command); }),
                    MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, result.status(), result.body());
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "command_submission_failed", e);
        }
    }

    private static void handleControlReleaseAll(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/release-all", "POST")) return;
        if (readJsonObjectOrRespond(exchange, true) == null) return;

        try {
            JsonObject result = callOnMinecraftThread(() -> {
                NativeReactiveGuard.stop("explicit_release_or_close");
                NativeFallRescue.stop("explicit_release_or_close");
                int rawKeysReleased = releaseAllInputs();
                JsonObject obj = ok();
                obj.addProperty("released", true);
                obj.addProperty("raw_keys_released", rawKeysReleased);
                return obj;
            }, MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, 200, result);
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "release_all_failed", e);
        }
    }

    private static void handleControlClose(HttpExchange exchange) throws IOException {
        if (!requireControlAccess(exchange, "/control/close", "POST")) return;
        if (readJsonObjectOrRespond(exchange, true) == null) return;

        try {
            JsonObject result = callOnMinecraftThread(() -> {
                NativeReactiveGuard.stop("explicit_release_or_close");
                NativeFallRescue.stop("explicit_release_or_close");
                int rawKeysReleased = releaseAllInputs();
                Minecraft.getInstance().stop();
                JsonObject obj = ok();
                obj.addProperty("released", true);
                obj.addProperty("raw_keys_released", rawKeysReleased);
                obj.addProperty("closing", true);
                return obj;
            }, MINECRAFT_TIMEOUT_SECONDS);
            respondJson(exchange, 200, result);
        } catch (Exception e) {
            respondMinecraftFailure(exchange, "close_failed", e);
        }
    }

    private static JsonObject createCapabilities() {
        JsonObject obj = protocolOk();
        JsonArray operations = new JsonArray();
        addOperation(operations, "GET", "/control/status", "session_identity");
        addOperation(operations, "GET", "/control/capabilities", "capability_discovery");
        addOperation(operations, "GET", "/control/frame", "framebuffer_png");
        addOperation(operations, "GET", "/control/keymaps", "keymap_discovery");
        addOperation(operations, "GET", "/control/state", "client_state_snapshot");
        addOperation(operations, "GET", "/control/capability-snapshot", "coherent_capability_snapshot");
        addOperation(operations,"GET","/control/compact-observation","bounded_atomic_compact_observation");
        addOperation(operations, "GET", "/control/terrain", "nearby_loaded_terrain");
        addOperation(operations, "POST", "/control/scan", "read_only_loaded_world_scan");
        addOperation(operations, "GET", "/control/scan/status", "loaded_world_scan_status");
        addOperation(operations, "POST", "/control/scan/cancel", "cancel_read_only_scan");
        addOperation(operations, "GET", "/control/screen", "screen_snapshot");
        addOperation(operations, "POST", "/control/action", "continuous_client_action");
        addOperation(operations, "POST", "/control/scoped-action", "scoped-native-preflight/1");
        addOperation(operations, "GET", "/control/action/status", "client_action_status");
        addOperation(operations, "POST", "/control/action/cancel", "cancel_client_action");
        addOperation(operations, "POST", "/control/pause", "ensure_bound_encounter_pause_screen");
        addOperation(operations, "POST", "/control/key", "keymap_input");
        addOperation(operations, "POST", "/control/raw-key", "internal_keyboard_input");
        addOperation(operations, "POST", "/control/guarded-action", "guarded_local_survival_action");
        addOperation(operations, "POST", "/control/guarded-movement", "guarded_local_movement_sample");
        addOperation(operations, "POST", "/control/guarded-turn", "guarded_local_player_yaw");
        addOperation(operations, "POST", "/control/look", "player_view");
        addOperation(operations, "POST", "/control/mouse", "screen_mouse_input");
        addOperation(operations, "POST", "/control/text", "focused_screen_text");
        addOperation(operations, "POST", "/control/command", "minecraft_command");
        addOperation(operations, "POST", "/control/release-all", "release_keymaps");
        addOperation(operations, "POST", "/control/close", "graceful_client_stop");
        obj.add("operations", operations);
        JsonObject actions = new JsonObject();
        actions.addProperty("schema_version", 1);
        actions.addProperty("session", ClientActions.session());
        actions.addProperty("single_flight", true);
        actions.addProperty("multiplayer", true);
        actions.addProperty("tick_driven", true);
        actions.addProperty("direct_input_takeover", true);
        actions.addProperty("deduplicate_action_ids", true);
        JsonArray actionNames = new JsonArray();
        ClientActionRequest.ACTIONS.stream().sorted().forEach(actionNames::add);
        actions.add("actions", actionNames);
        actions.addProperty("capability_guard_schema_version",1);
        actions.add("combat_capabilities",CapabilityCombatSafety.capabilities());
        actions.addProperty("movement_budget_schema_version",1);
        actions.addProperty("movement_budget_mode",MovementBudgetLedger.MODE);
        actions.addProperty("capability_guard_private_singleplayer_only",true);
        JsonObject boatTransfer = new JsonObject();
        boatTransfer.addProperty("schema_version", 1);
        boatTransfer.addProperty("private_singleplayer_only", true);
        boatTransfer.addProperty("max_sneak_ticks", 10);
        boatTransfer.addProperty("min_timeout_ms", 1000);
        boatTransfer.addProperty("max_timeout_ms", 5000);
        actions.add("boat_transfer", boatTransfer);
        obj.add("client_actions", actions);
        obj.add("native_fall_rescue",NativeFallRescue.capabilities());
        obj.add("scoped_native_preflight", ScopedNativePreflight.capabilities());
        JsonObject pause = new JsonObject();
        pause.addProperty("schema_version", 1);
        pause.addProperty("private_singleplayer_only", true);
        pause.addProperty("screen_installed_not_pause_proof", true);
        pause.addProperty("idempotent_non_toggling", true);
        pause.addProperty("native_terminal_opt_in", EncounterRequest.PAUSE_ON_TERMINAL);
        obj.add("encounter_pause", pause);
        obj.addProperty("aim_view_guard_schema_version", AimViewGuard.SCHEMA);
        obj.addProperty("combat_observation_schema_version", 1);
        JsonObject acquisition=new JsonObject();
        acquisition.addProperty("version",TerrainAcquisitionRequest.VERSION);acquisition.addProperty("schema_version",1);
        acquisition.addProperty("radius",4);acquisition.addProperty("vertical",4);acquisition.addProperty("entity_radius",48);
        acquisition.addProperty("max_pages",4);acquisition.addProperty("max_request_admissions",2);
        obj.add("terrain_acquisition",acquisition);
        JsonObject guarded = new JsonObject();
        guarded.addProperty("schema_version", GuardedAction.SCHEMA);
        guarded.addProperty("enabled", GuardedGameActions.enabled());
        guarded.addProperty("max_ttl_ms", GuardedAction.MAX_TTL_MS);
        guarded.addProperty("max_range", GuardedAction.MAX_RANGE);
        guarded.addProperty("max_yaw_step", GuardedAction.MAX_YAW_STEP);
        guarded.addProperty("max_pitch_step", GuardedAction.MAX_PITCH_STEP);
        guarded.addProperty("local_unpublished_survival_only", true);
        guarded.addProperty("single_flight", true);
        guarded.addProperty("synchronous_attack_attempt", true);
        guarded.addProperty("held_input", false);
        guarded.addProperty("unenchanted_axe_only", true);
        JsonArray targets = new JsonArray();
        GuardedAction.HOSTILE_TYPES.stream().sorted().forEach(targets::add);
        guarded.add("allowed_target_types", targets);
        obj.add("guarded_actions", guarded);
        obj.add("guarded_movement", GuardedGameMovement.status());
        obj.add("guarded_turn", GuardedGameTurning.capabilities());

        JsonObject limits = new JsonObject();
        limits.addProperty("request_body_bytes", MAX_BODY_BYTES);
        limits.addProperty("json_response_bytes", MAX_JSON_BYTES);
        limits.addProperty("frame_bytes", MAX_FRAME_BYTES);
        limits.addProperty("minecraft_timeout_seconds", MINECRAFT_TIMEOUT_SECONDS);
        limits.addProperty("frame_timeout_seconds", FRAME_TIMEOUT_SECONDS);
        limits.addProperty("scan_tick_block_reads_max", LoadedScan.BLOCKS_PER_TICK);
        limits.addProperty("scan_tick_budget_micros", LoadedScan.BUDGET_NANOS / 1000);
        limits.addProperty("scan_results_max", 256);
        limits.addProperty("scan_chunks_max", 8192);
        limits.addProperty("terrain_radius_max", TerrainQuery.MAX_RADIUS);
        limits.addProperty("terrain_vertical_max", TerrainQuery.MAX_VERTICAL);
        limits.addProperty("terrain_page_cells_max", TerrainQuery.MAX_LIMIT);
        limits.addProperty("terrain_total_cells_max", TerrainQuery.MAX_BLOCKS);
        limits.addProperty("terrain_page_budget_micros", TerrainScan.PAGE_BUDGET_NANOS / 1000);
        limits.addProperty("terrain_min_page_interval_ms", TerrainScan.MIN_PAGE_INTERVAL_NANOS / 1_000_000);
        limits.addProperty("terrain_cursor_ttl_seconds", TerrainScan.MAX_AGE_NANOS / 1_000_000_000);
        limits.addProperty("nearby_radius_max", MAX_ENTITY_RADIUS);
        limits.addProperty("nearby_entities_max", MAX_NEARBY_ENTITIES);
        limits.addProperty("keymaps_max", MAX_KEYMAPS);
        limits.addProperty("screen_children_max", MAX_SCREEN_CHILDREN);
        limits.addProperty("container_slots_max", MAX_CONTAINER_SLOTS);
        limits.addProperty("text_characters_max", MAX_TEXT_LENGTH);
        limits.addProperty("command_characters_max", MAX_COMMAND_LENGTH);
        obj.add("limits", limits);

        JsonObject safety = new JsonObject();
        safety.addProperty("loopback_only", true);
        safety.addProperty("bearer_required", true);
        safety.addProperty("authenticated_minecraft_commands", true);
        safety.addProperty("internal_keyboard_events", true);
        safety.addProperty("internal_mouse_events", true);
        safety.addProperty("mod_input_events_observed", InputEventProbe.installed());
        safety.addProperty("arbitrary_scripts", false);
        safety.addProperty("direct_file_api", false);
        safety.addProperty("direct_outbound_network_api", false);
        safety.addProperty("direct_world_mutation_api", false);
        safety.addProperty("input_can_trigger_gameplay_and_gui_actions", true);
        safety.addProperty("os_input", false);
        obj.add("safety", safety);
        return obj;
    }

    private static void addOperation(JsonArray operations, String method, String path, String capability) {
        JsonObject operation = new JsonObject();
        operation.addProperty("method", method);
        operation.addProperty("path", path);
        operation.addProperty("capability", capability);
        operations.add(operation);
    }

    private static JsonObject createKeymapsSnapshot() {
        Minecraft mc = Minecraft.getInstance();
        JsonObject obj = protocolOk();
        JsonArray entries = new JsonArray();
        int total = mc.options.keyMappings.length;
        int returned = Math.min(total, MAX_KEYMAPS);
        for (int i = 0; i < returned; i++) {
            KeyMapping mapping = mc.options.keyMappings[i];
            JsonObject entry = new JsonObject();
            entry.addProperty("name", boundedText(mapping.getName()));
            entry.addProperty("category", boundedText(mapping.getCategory()));
            entry.addProperty("bound_key", boundedText(mapping.saveString()));
            entry.addProperty("down", mapping.isDown());
            entry.addProperty("unbound", mapping.isUnbound());
            entries.add(entry);
        }
        obj.addProperty("total", total);
        obj.addProperty("returned", returned);
        obj.addProperty("truncated", total > returned);
        obj.add("keymaps", entries);
        return obj;
    }

    private static EndpointResult createStateSnapshot(double radius, BridgeReadTiming timing, boolean coordination) {
        return createStateSnapshot(radius,timing,coordination,null);
    }

    private static EndpointResult createStateSnapshot(double radius, BridgeReadTiming timing, boolean coordination, JsonObject sharedAction) {
        return createStateSnapshot(radius,timing,coordination,sharedAction,false);
    }
    private static EndpointResult createStateSnapshot(double radius, BridgeReadTiming timing, boolean coordination, JsonObject sharedAction, boolean compact) {
        return createStateSnapshot(radius,timing,coordination,sharedAction,compact,null);
    }
    private static EndpointResult createStateSnapshot(double radius, BridgeReadTiming timing, boolean coordination, JsonObject sharedAction, boolean compact,CompactObservation.Diagnostic diagnostic) {
        Minecraft mc = Minecraft.getInstance();
        WorldGeneration.current(mc.level);
        String integratedServerInstance=IntegratedServerIdentity.current(mc.getSingleplayerServer(),
                CapabilityGuard.privateSingleplayer(mc));
        if (mc.player == null || mc.level == null) {
            return new EndpointResult(409, error("not_in_world"));
        }

        // One exact player/level/server object frame for lifecycle telemetry.
        var sampledPlayer=mc.player;
        var sampledLevel=mc.level;
        var sampledServer=mc.getSingleplayerServer();
        var sampledUuid=sampledPlayer.getUUID();
        String playerGeneration=PlayerGeneration.current(sampledPlayer);
        JsonObject obj = protocolOk();
        obj.add("client_action", sharedAction==null?ClientActions.status(null):sharedAction.deepCopy());
        obj.add("movement_budget",sharedAction==null?MovementBudget.snapshot(mc):sharedAction.getAsJsonObject("movement_budget").deepCopy());
        obj.addProperty("aim_view_guard_schema_version", AimViewGuard.SCHEMA);
        obj.addProperty("combat_observation_schema_version", 1);
        obj.addProperty("screen_open", mc.screen != null);
        obj.addProperty("paused", mc.isPaused());
        obj.addProperty("focused",mc.isWindowActive());
        obj.addProperty("private_singleplayer",CapabilityGuard.privateSingleplayer(mc));
        obj.add("held_inputs",heldInputsSnapshot(mc));
        long externalStarted=diagnostic==null?0:System.nanoTime();
        try {obj.add("external_controller", ExternalControllerGuard.snapshot(mc));}
        finally {if(diagnostic!=null)diagnostic.external(externalStarted,System.nanoTime());}
        obj.add("managed_navigation",NativeManagedNavigation.capabilities());
        obj.add("managed_navigation_status",NativeManagedNavigation.status());
        obj.add("external_navigation",NativeExternalNavigation.capabilities());
        obj.add("external_navigation_status",NativeExternalNavigation.status());
        obj.add("menu", menuSnapshot(mc.player.containerMenu));
        JsonObject player = new JsonObject();
        player.addProperty("uuid", mc.player.getUUID().toString());
        player.addProperty("name", boundedText(mc.player.getGameProfile().getName()));
        player.addProperty("x", mc.player.getX());
        player.addProperty("y", mc.player.getY());
        player.addProperty("z", mc.player.getZ());
        player.addProperty("yaw", mc.player.getYRot());
        player.addProperty("pitch", mc.player.getXRot());
        player.add("velocity", vector(mc.player.getDeltaMovement()));
        player.add("vehicle", BoatObservation.snapshot(mc));
        player.add("enderman_shelter",CapabilityShelter.snapshot(mc));
        player.add("eye_position", vector(mc.player.getEyePosition()));
        player.addProperty("alive", mc.player.isAlive());
        player.addProperty("health", mc.player.getHealth());
        player.addProperty("max_health", mc.player.getMaxHealth());
        player.addProperty("food", mc.player.getFoodData().getFoodLevel());
        player.addProperty("saturation", mc.player.getFoodData().getSaturationLevel());
        player.addProperty("air", mc.player.getAirSupply());
        player.addProperty("max_air", mc.player.getMaxAirSupply());
        player.addProperty("xp_level", mc.player.experienceLevel);
        player.addProperty("xp_progress", mc.player.experienceProgress);
        player.addProperty("xp_total", mc.player.totalExperience);
        player.addProperty("gamemode", mc.gameMode == null
                ? "unknown"
                : mc.gameMode.getPlayerMode().getName());
        player.addProperty("dimension", mc.level.dimension().location().toString());
        player.addProperty("on_ground", mc.player.onGround());
        player.addProperty("environment_schema_version", 1);
        player.addProperty("in_water", mc.player.isInWater());
        player.addProperty("eye_in_water", mc.player.isEyeInFluid(net.minecraft.tags.FluidTags.WATER));
        player.addProperty("in_lava", mc.player.isInLava());
        player.addProperty("in_powder_snow", mc.player.isInPowderSnow);
        player.addProperty("frozen_ticks", mc.player.getTicksFrozen());
        player.addProperty("on_fire", mc.player.isOnFire());
        player.addProperty("fire_ticks", mc.player.getRemainingFireTicks());
        var playerBounds = mc.player.getBoundingBox();
        JsonObject playerBox = new JsonObject();
        playerBox.add("min", vector(new Vec3(playerBounds.minX, playerBounds.minY, playerBounds.minZ)));
        playerBox.add("max", vector(new Vec3(playerBounds.maxX, playerBounds.maxY, playerBounds.maxZ)));
        player.add("bounding_box", playerBox);

        player.addProperty("sprinting", mc.player.isSprinting());
        // Read the real client cooldown and item-use state. These are observed
        // mechanics, not confirmation that a later server attack will land.
        player.addProperty("attack_strength", mc.player.getAttackStrengthScale(0.5F));
        player.addProperty("attack_speed", mc.player.getAttributeValue(Attributes.ATTACK_SPEED));
        player.addProperty("entity_interaction_range", mc.player.entityInteractionRange());
        player.addProperty("block_interaction_range", mc.player.blockInteractionRange());
        player.addProperty("using_item", mc.player.isUsingItem());
        player.addProperty("blocking", mc.player.isBlocking());
        player.addProperty("use_ticks", mc.player.getTicksUsingItem());
        player.addProperty("shield_cooldown", mc.player.getCooldowns().isOnCooldown(Items.SHIELD));

        Inventory inventory = mc.player.getInventory();
        player.addProperty("selected_slot", inventory.selected);
        JsonArray inventoryItems = new JsonArray();
        for (int slot = 0; slot < inventory.items.size(); slot++) {
            JsonObject item = capabilityItemSnapshot(inventory.items.get(slot));
            item.addProperty("slot", slot);
            inventoryItems.add(item);
        }
        player.addProperty("inventory_total", inventory.items.size());
        player.addProperty("inventory_truncated", false);
        player.add("inventory", inventoryItems);

        JsonArray armor = new JsonArray();
        for (EquipmentSlot slot : new EquipmentSlot[]{
                EquipmentSlot.HEAD,
                EquipmentSlot.CHEST,
                EquipmentSlot.LEGS,
                EquipmentSlot.FEET}) {
            JsonObject item = capabilityItemSnapshot(mc.player.getItemBySlot(slot));
            item.addProperty("slot", slot.getName());
            armor.add(item);
        }
        player.add("armor", armor);
        player.add("offhand", capabilityItemSnapshot(mc.player.getOffhandItem()));
        player.add("mainhand", capabilityItemSnapshot(mc.player.getMainHandItem()));

        JsonArray effects = new JsonArray();
        int effectTotal = mc.player.getActiveEffects().size();
        int effectCount = 0;
        for (MobEffectInstance effect : mc.player.getActiveEffects()) {
            if (effectCount >= MAX_STATUS_EFFECTS) break;
            JsonObject effectJson = new JsonObject();
            effectJson.addProperty("id", BuiltInRegistries.MOB_EFFECT
                    .getKey(effect.getEffect().value()).toString());
            effectJson.addProperty("amplifier", effect.getAmplifier());
            effectJson.addProperty("duration_ticks", effect.getDuration());
            effectJson.addProperty("ambient", effect.isAmbient());
            effectJson.addProperty("visible", effect.isVisible());
            effects.add(effectJson);
            effectCount++;
        }
        player.addProperty("effects_total", effectTotal);
        player.addProperty("effects_returned", effectCount);
        player.addProperty("effects_truncated", effectTotal > effectCount);
        player.add("effects", effects);
        obj.add("player", player);

        obj.add("crosshair", crosshairSnapshot(mc));

        JsonObject world = new JsonObject();
        world.addProperty("dimension", mc.level.dimension().location().toString());
        // A registry fact at the player's feet, not an inference from nearby trees/blocks.
        world.addProperty("biome_id", mc.level.getBiome(mc.player.blockPosition())
                .unwrapKey().map(key -> key.location().toString()).orElse(null));
        long gameTime = mc.level.getGameTime();
        long sampleNano = System.nanoTime();
        if (timing != null) timing.stateGameTimeSample(gameTime, sampleNano);
        world.addProperty("game_time", gameTime);
        obj.add("capability_guard",CapabilityGuard.observation(gameTime,sampleNano));
        obj.add("scoped_native_preflight", ScopedNativePreflight.capabilities());
        obj.add("combat_capabilities",CapabilityCombatSafety.capabilities());
        obj.add("native_fall_rescue",NativeFallRescue.capabilities());
        obj.add("native_fall_rescue_status",NativeFallRescue.status());
        if (coordination) obj.add("coordination_step", CoordinationStepGuard.observation(mc, gameTime, sampleNano));
        world.addProperty("world_generation", WorldGeneration.current(mc.level));
        world.addProperty("integrated_server_instance",integratedServerInstance);
        world.add("navigation_guard", NavigationPositionGuard.snapshot(mc));
        world.addProperty("day_time", mc.level.getDayTime());
        world.addProperty("raining", mc.level.isRaining());
        world.addProperty("thundering", mc.level.isThundering());
        world.addProperty("rain_level", mc.level.getRainLevel(1.0F));
        world.addProperty("thunder_level", mc.level.getThunderLevel(1.0F));
        obj.add("world", world);
        obj.add("guarded_movement", GuardedGameMovement.observedStatus(mc));
        obj.add("guarded_turn", GuardedGameTurning.capabilities());
        if(!compact)obj.add("nearby", nearbyEntitiesSnapshot(mc, radius));
        // No callback-backed snapshot work follows the final actual-object fence.
        // Re-sample health/alive together so a death fact cannot borrow a new
        // player's generation from a mixed callback frame.
        var sampledData=sampledPlayer.getEntityData();
        boolean exactLifeReaders=mc.getClass()==net.minecraft.client.Minecraft.class
                &&sampledPlayer.getClass()==net.minecraft.client.player.LocalPlayer.class
                &&sampledLevel.getClass()==net.minecraft.client.multiplayer.ClientLevel.class
                &&sampledServer!=null&&sampledServer.getClass()==net.minecraft.client.server.IntegratedServer.class
                &&sampledData.getClass()==net.minecraft.network.syncher.SynchedEntityData.class;
        float finalHealth=exactLifeReaders?sampledPlayer.getHealth():Float.NaN;
        boolean finalAlive=exactLifeReaders&&sampledPlayer.isAlive();
        if(!PlayerGeneration.frameCurrent(sampledPlayer,mc.player,sampledLevel,mc.level,sampledPlayer.level(),
                sampledServer,mc.getSingleplayerServer(),sampledData,sampledPlayer.getEntityData(),sampledUuid,sampledPlayer.getUUID())
                ||!PlayerGeneration.matches(sampledPlayer,playerGeneration))
            return new EndpointResult(409,error("player_generation_changed_during_observation"));
        if(exactLifeReaders&&Float.isFinite(finalHealth)) {
            player.addProperty("uuid",sampledUuid.toString());
            player.addProperty("health",finalHealth);
            player.addProperty("alive",finalAlive);
            player.addProperty("generation_schema_version",1);
            player.addProperty("generation",playerGeneration);
        }
        return new EndpointResult(200, obj);
    }

    private static JsonObject crosshairSnapshot(Minecraft mc) {
        JsonObject target = new JsonObject();
        HitResult hit = mc.hitResult;
        if (hit == null || hit.getType() == HitResult.Type.MISS) {
            target.addProperty("type", "miss");
            return target;
        }

        target.addProperty("distance", hit.distanceTo(mc.player)); // Legacy field is squared; preserved for compatibility.
        target.addProperty("distance_squared", hit.distanceTo(mc.player));
        target.addProperty("distance_euclidean", Math.sqrt(hit.distanceTo(mc.player)));
        target.add("location", vector(hit.getLocation()));
        if (hit instanceof BlockHitResult blockHit) {
            BlockPos pos = blockHit.getBlockPos();
            target.addProperty("type", "block");
            target.addProperty("id", BuiltInRegistries.BLOCK
                    .getKey(mc.level.getBlockState(pos).getBlock()).toString());
            target.addProperty("x", pos.getX());
            target.addProperty("y", pos.getY());
            target.addProperty("z", pos.getZ());
            target.addProperty("face", blockHit.getDirection().getName());
            return target;
        }
        if (hit instanceof EntityHitResult entityHit) {
            Entity entity = entityHit.getEntity();
            target.addProperty("type", "entity");
            target.addProperty("entity_id", entity.getId());
            target.addProperty("uuid", entity.getUUID().toString());
            target.addProperty("entity_type", BuiltInRegistries.ENTITY_TYPE
                    .getKey(entity.getType()).toString());
            target.addProperty("name", boundedText(entity.getName().getString()));
            return target;
        }
        target.addProperty("type", hit.getType().name().toLowerCase(Locale.ROOT));
        return target;
    }

    private static JsonObject nearbyEntitiesSnapshot(Minecraft mc, double radius) {
        NativeLivingObservation.Frame nativeFrame = NativeLivingObservation.capture(mc);
        Comparator<EntityDistance> farthestFirst = Comparator
                .comparingDouble(EntityDistance::distance)
                .reversed();
        int limit=radius>48?128:MAX_NEARBY_ENTITIES;
        PriorityQueue<EntityDistance> nearest = new PriorityQueue<>(limit, farthestFirst);
        int total = 0;
        double radiusSquared = radius * radius;
        for (Entity entity : mc.level.entitiesForRendering()) {
            if (entity == mc.player) continue;
            double distanceSquared = entity.distanceToSqr(mc.player);
            if (distanceSquared > radiusSquared) continue;
            total++;
            EntityDistance candidate = new EntityDistance(entity, Math.sqrt(distanceSquared));
            if (nearest.size() < limit) {
                nearest.add(candidate);
            } else if (candidate.distance() < nearest.peek().distance()) {
                nearest.poll();
                nearest.add(candidate);
            }
        }

        ArrayList<EntityDistance> sorted = new ArrayList<>(nearest);
        sorted.sort(Comparator.comparingDouble(EntityDistance::distance));
        JsonArray entities = new JsonArray();
        for (EntityDistance entry : sorted) {
            Entity entity = entry.entity();
            JsonObject entityJson = new JsonObject();
            entityJson.addProperty("entity_id", entity.getId());
            entityJson.addProperty("uuid", entity.getUUID().toString());
            entityJson.addProperty("type", BuiltInRegistries.ENTITY_TYPE
                    .getKey(entity.getType()).toString());
            entityJson.addProperty("class", boundedText(entity.getClass().getName()));
            entityJson.addProperty("name", boundedText(entity.getName().getString()));
            entityJson.addProperty("x", entity.getX());
            entityJson.addProperty("y", entity.getY());
            entityJson.addProperty("z", entity.getZ());
            entityJson.addProperty("yaw", entity.getYRot());
            entityJson.addProperty("pitch", entity.getXRot());
            entityJson.add("velocity", vector(entity.getDeltaMovement()));
            if(entity instanceof net.minecraft.world.entity.monster.Creeper creeper) {
                JsonObject facts=new JsonObject();facts.addProperty("ignited",creeper.isIgnited());facts.addProperty("powered",creeper.isPowered());
                facts.addProperty("swell_ticks",creeper.swell);facts.addProperty("fuse_ticks",creeper.maxSwell);
                facts.addProperty("swell_direction",creeper.getSwellDir());facts.addProperty("explosion_radius",creeper.explosionRadius);
                entityJson.add("creeper",facts);
            }
            if(entity instanceof net.minecraft.world.entity.monster.Blaze blaze) {
                JsonObject facts=new JsonObject();facts.addProperty("charged",blaze.isCharged());entityJson.add("blaze",facts);
            }
            if(entity instanceof net.minecraft.world.entity.monster.EnderMan enderman) {
                entityJson.addProperty("aggressive",enderman.isCreepy()||enderman.hasBeenStaredAt()||enderman.getTarget()==mc.player);
            }
            if(entity instanceof net.minecraft.world.entity.monster.Shulker shulker)entityJson.addProperty("shell_open",CapabilityTargetAction.shulkerShellOpen(shulker));
            if(entity instanceof net.minecraft.world.entity.vehicle.Boat boat) {
                entityJson.addProperty("ordinary_boat",boat.getClass()==net.minecraft.world.entity.vehicle.Boat.class);
                entityJson.addProperty("passenger_count",boat.getPassengers().size());
                entityJson.addProperty("yaw_rate",boat.deltaRotation);
            }
            entityJson.addProperty("distance", entry.distance());
            entityJson.addProperty("alive", entity.isAlive());
            entityJson.addProperty("line_of_sight",mc.player.hasLineOfSight(entity));
            var bounds = entity.getBoundingBox();
            JsonObject box = new JsonObject();
            box.add("min", vector(new Vec3(bounds.minX, bounds.minY, bounds.minZ)));
            box.add("max", vector(new Vec3(bounds.maxX, bounds.maxY, bounds.maxZ)));
            entityJson.add("bounding_box", box);
            entityJson.addProperty("on_ground", entity.onGround());
            if (entity instanceof LivingEntity living) {
                entityJson.addProperty("health", living.getHealth());
                entityJson.addProperty("max_health", living.getMaxHealth());
                entityJson.addProperty("hurt_time", living.hurtTime);
                entityJson.addProperty("using_item", living.isUsingItem());
                entityJson.addProperty("use_ticks", living.getTicksUsingItem());
                entityJson.add("mainhand", itemSnapshot(living.getMainHandItem()));
                CapabilityItemBinding.append(living.getMainHandItem(),entityJson.getAsJsonObject("mainhand"));
            }
            if(entity instanceof net.minecraft.world.entity.item.ItemEntity itemEntity) {
                entityJson.add("item",capabilityItemSnapshot(itemEntity.getItem()));
            }
            if(entity instanceof net.minecraft.world.entity.boss.enderdragon.EnderDragon dragon) {
                var phase=dragon.getPhaseManager().getCurrentPhase().getPhase();
                entityJson.addProperty("phase_id",phase.getId());
                entityJson.addProperty("phase_name",phase.toString());
                JsonArray parts=new JsonArray();
                for(var part:dragon.getSubEntities()) {
                    JsonObject row=new JsonObject();row.addProperty("entity_id",part.getId());row.addProperty("name",part.name);
                    row.addProperty("x",part.getX());row.addProperty("y",part.getY());row.addProperty("z",part.getZ());
                    var bb=part.getBoundingBox();JsonObject boxPart=new JsonObject();
                    boxPart.add("min",vector(new Vec3(bb.minX,bb.minY,bb.minZ)));boxPart.add("max",vector(new Vec3(bb.maxX,bb.maxY,bb.maxZ)));
                    row.add("bounding_box",boxPart);parts.add(row);
                }
                entityJson.add("dragon_parts",parts);
            }
            NativeLivingObservation.append(mc, entity, entityJson, nativeFrame);
            entities.add(entityJson);
        }

        JsonObject nearby = new JsonObject();
        nearby.addProperty("radius", radius);
        nearby.addProperty("total", total);
        nearby.addProperty("returned", sorted.size());
        nearby.addProperty("truncated", total > sorted.size());
        nearby.add("entities", entities);
        JsonArray chunks=new JsonArray();
        int minX=(int)Math.floor((mc.player.getX()-radius)/16),maxX=(int)Math.floor((mc.player.getX()+radius)/16);
        int minZ=(int)Math.floor((mc.player.getZ()-radius)/16),maxZ=(int)Math.floor((mc.player.getZ()+radius)/16);
        for(int x=minX;x<=maxX;x++)for(int z=minZ;z<=maxZ;z++) {
            JsonObject chunk=new JsonObject();chunk.addProperty("x",x);chunk.addProperty("z",z);
            chunk.addProperty("loaded",mc.level.hasChunkAt(new BlockPos(x*16,mc.player.blockPosition().getY(),z*16)));
            chunks.add(chunk);
        }
        nearby.add("loaded_chunks",chunks);
        JsonArray gateways=new JsonArray();int inspected=0;boolean gatewayTruncated=false;
        gatewayScan: for(int x=minX;x<=maxX;x++)for(int z=minZ;z<=maxZ;z++) {
            var chunk=mc.level.getChunkSource().getChunk(x,z,net.minecraft.world.level.chunk.status.ChunkStatus.FULL,false);
            if(!(chunk instanceof net.minecraft.world.level.chunk.LevelChunk loaded))continue;
            for(var blockEntity:loaded.getBlockEntities().values()) {
                if(++inspected>4096){gatewayTruncated=true;break gatewayScan;}
                if(!(blockEntity instanceof net.minecraft.world.level.block.entity.TheEndGatewayBlockEntity gateway))continue;
                BlockPos pos=blockEntity.getBlockPos();
                if(Vec3.atCenterOf(pos).distanceToSqr(mc.player.position())>radiusSquared)continue;
                JsonObject row=new JsonObject();row.addProperty("x",pos.getX());row.addProperty("y",pos.getY());row.addProperty("z",pos.getZ());
                row.addProperty("loaded",true);row.addProperty("id","minecraft:end_gateway");row.add("properties",new JsonObject());row.addProperty("cooling_down",gateway.isCoolingDown());
                gateways.add(row);
            }
        }
        nearby.add("end_gateways",gateways);nearby.addProperty("end_gateways_truncated",gatewayTruncated);
        return nearby;
    }

    private static JsonObject createScreenSnapshot() {
        BoundedContainerSnapshot.beginSnapshot();
        Minecraft mc = Minecraft.getInstance();
        JsonObject obj = protocolOk();
        Screen screen = mc.screen;
        obj.add("world_selection", WorldSelectionObservation.capture(mc, screen,
                () -> new WorldSelectionSnapshot.Identity(ProcessHandle.current().pid(), runId(), ClientActions.session())));
        if (mc.player != null) obj.add("menu", menuSnapshot(mc.player.containerMenu));
        obj.addProperty("open", screen != null);
        if (screen == null) {
            obj.addProperty("children_total", 0);
            obj.addProperty("children_returned", 0);
            obj.addProperty("children_truncated", false);
            obj.add("children", new JsonArray());
            return obj;
        }

        obj.addProperty("class", screen.getClass().getName());
        obj.addProperty("title", boundedText(screen.getTitle().getString()));
        obj.addProperty("gui_width", screen.width);
        obj.addProperty("gui_height", screen.height);
        GuiEventListener focused = screen.getFocused();
        obj.addProperty("focused_class", focused == null ? "" : focused.getClass().getName());

        JsonArray children = new JsonArray();
        int totalChildren = screen.children().size();
        int childLimit = Math.min(totalChildren, MAX_SCREEN_CHILDREN);
        for (int i = 0; i < childLimit; i++) {
            GuiEventListener child = screen.children().get(i);
            JsonObject childJson = new JsonObject();
            childJson.addProperty("index", i);
            childJson.addProperty("class", boundedText(child.getClass().getName()));
            childJson.addProperty("focused", child == focused || child.isFocused());
            if (child instanceof AbstractWidget widget) {
                childJson.addProperty("visible", widget.visible);
                childJson.addProperty("active", widget.active);
                childJson.addProperty("message", boundedText(widget.getMessage().getString()));
                childJson.addProperty("x", widget.getX());
                childJson.addProperty("y", widget.getY());
                childJson.addProperty("width", widget.getWidth());
                childJson.addProperty("height", widget.getHeight());
            } else {
                addChildRectangle(childJson, child);
            }
            children.add(childJson);
        }
        obj.addProperty("children_total", totalChildren);
        obj.addProperty("children_returned", childLimit);
        obj.addProperty("children_truncated", totalChildren > childLimit);
        obj.add("children", children);

        if (screen instanceof AbstractContainerScreen<?> containerScreen) {
            AbstractContainerMenu menu = containerScreen.getMenu();
            obj.addProperty("menu_class", menu.getClass().getName());
            obj.addProperty("container_id", menu.containerId);
            JsonArray slots = new JsonArray();
            int totalSlots = menu.slots.size();
            int slotLimit = Math.min(totalSlots, MAX_CONTAINER_SLOTS);
            for (int i = 0; i < slotLimit; i++) {
                Slot slot = menu.slots.get(i);
                JsonObject slotJson = new JsonObject();
                slotJson.addProperty("menu_index", i);
                slotJson.addProperty("slot_index", slot.index);
                slotJson.addProperty("container_slot", slot.getContainerSlot());
                slotJson.addProperty("x", slot.x);
                slotJson.addProperty("y", slot.y);
                slotJson.addProperty("active", slot.isActive());
                slotJson.add("item", capabilityItemSnapshot(slot.getItem()));
                slots.add(slotJson);
            }
            obj.addProperty("slots_total", totalSlots);
            obj.addProperty("slots_returned", slotLimit);
            obj.addProperty("slots_truncated", totalSlots > slotLimit);
            obj.add("slots", slots);
        }
        return obj;
    }

    static JsonObject menuSnapshot(AbstractContainerMenu menu) {
        BoundedContainerSnapshot.beginSnapshot();
        Minecraft mc = Minecraft.getInstance();
        JsonObject obj = new JsonObject();
        obj.addProperty("menu_class", menu.getClass().getName());
        obj.addProperty("container_id", menu.containerId);
        obj.addProperty("state_id", menu.getStateId());
        obj.add("recovery_context", InventoryRecoveryGuard.context(menu));
        obj.add("carried", capabilityItemSnapshot(menu.getCarried()));
        if(menu instanceof net.minecraft.world.inventory.AbstractFurnaceMenu furnace) {
            JsonObject f=new JsonObject();f.addProperty("is_lit",furnace.isLit());
            f.addProperty("burn_progress",furnace.getBurnProgress());f.addProperty("lit_progress",furnace.getLitProgress());
            obj.add("furnace",f);
        }
        JsonArray slots = new JsonArray();
        int limit = Math.min(menu.slots.size(), MAX_CONTAINER_SLOTS);
        for (int i = 0; i < limit; i++) {
            Slot slot = menu.slots.get(i);
            JsonObject entry = new JsonObject();
            entry.addProperty("menu_index", i);
            entry.addProperty("slot_index", slot.index);
            entry.addProperty("container_slot", slot.getContainerSlot());
            boolean inventory = mc.player != null && slot.container == mc.player.getInventory();
            entry.addProperty("player_inventory", inventory);
            if (inventory) entry.addProperty("inventory_index", slot.getContainerSlot());
            entry.addProperty("active", slot.isActive());
            entry.add("item", capabilityItemSnapshot(slot.getItem()));
            slots.add(entry);
        }
        obj.add("slots", slots);
        obj.addProperty("slots_total", menu.slots.size());
        obj.addProperty("slots_returned", limit);
        obj.addProperty("slots_truncated", menu.slots.size() > limit);
        return obj;
    }

    private static void addChildRectangle(JsonObject childJson, GuiEventListener child) {
        try {
            ScreenRectangle rectangle = child.getRectangle();
            childJson.addProperty("x", rectangle.left());
            childJson.addProperty("y", rectangle.top());
            childJson.addProperty("width", rectangle.width());
            childJson.addProperty("height", rectangle.height());
            childJson.addProperty("geometry_available", true);
        } catch (RuntimeException e) {
            childJson.addProperty("geometry_available", false);
        }
    }

    static JsonObject capabilityItemSnapshot(ItemStack stack) {
        JsonObject out=itemSnapshot(stack);
        CapabilityItemBinding.append(stack,out);
        if(stack!=null && !stack.isEmpty()) {
            var contents=stack.get(net.minecraft.core.component.DataComponents.POTION_CONTENTS);
            if(contents!=null) {
                JsonArray effects=new JsonArray();int total=0;
                for(var effect:contents.getAllEffects()) {
                    total++;if(total>32)continue;
                    JsonObject row=new JsonObject();row.addProperty("id",BuiltInRegistries.MOB_EFFECT.getKey(effect.getEffect().value()).toString());
                    row.addProperty("amplifier",effect.getAmplifier());row.addProperty("duration_ticks",effect.getDuration());effects.add(row);
                }
                out.add("potion_effects",effects);out.addProperty("potion_effects_truncated",total>32);
            }
        }
        return out;
    }

    private static JsonObject itemSnapshot(ItemStack stack) {
        JsonObject item = new JsonObject();
        boolean empty = stack == null || stack.isEmpty();
        item.addProperty("empty", empty);
        if (empty) {
            item.addProperty("id", "");
            item.addProperty("count", 0);
            item.addProperty("damage", 0);
            item.addProperty("max_damage", 0);
            return item;
        }
        item.addProperty("id", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
        item.addProperty("count", stack.getCount());
        item.addProperty("damage", stack.getDamageValue());
        item.addProperty("max_damage", stack.getMaxDamage());
        BoundedContainerSnapshot.append(stack, item);
        return item;
    }

    private static JsonObject vector(Vec3 vector) {
        JsonObject obj = new JsonObject();
        obj.addProperty("x", vector.x);
        obj.addProperty("y", vector.y);
        obj.addProperty("z", vector.z);
        return obj;
    }

    private static JsonObject protocolOk() {
        JsonObject obj = ok();
        obj.addProperty("protocol", PROTOCOL_NAME);
        obj.addProperty("schema_version", PROTOCOL_SCHEMA_VERSION);
        return obj;
    }

    private static JsonObject createControlStatus() {
        return createControlStatus(null);
    }

    private static JsonObject createControlStatus(JsonObject sharedAction) {
        Minecraft mc = Minecraft.getInstance();
        WorldGeneration.current(mc.level);
        JsonObject obj = ok();
        obj.addProperty("process_id", ProcessHandle.current().pid());
        obj.addProperty("protocol", PROTOCOL_NAME);
        obj.addProperty("schema_version", PROTOCOL_SCHEMA_VERSION);
        obj.addProperty("run_id", runId());
        obj.addProperty("desktop_name", identityValue(
                "mineclientBridge.desktopName",
                "MINECLIENT_BRIDGE_DESKTOP_NAME"));
        obj.addProperty("runtime_root", identityValue(
                "mineclientBridge.runtimeRoot",
                "MINECLIENT_BRIDGE_RUNTIME_ROOT"));
        obj.addProperty("evidence_root", identityValue(
                "mineclientBridge.evidenceRoot",
                "MINECLIENT_BRIDGE_EVIDENCE_ROOT"));
        obj.add("client_action", sharedAction==null?ClientActions.status(null):sharedAction.deepCopy());
        obj.addProperty("coordination_step_protocol", 1);
        obj.addProperty("bridge_running", isRunning());
        obj.addProperty("in_world", mc.level != null && mc.player != null);

        JsonObject world = new JsonObject();
        world.addProperty("present", mc.level != null);
        if (mc.level != null) {
            world.addProperty("dimension", mc.level.dimension().location().toString());
            world.addProperty("game_time", mc.level.getGameTime());
            world.addProperty("world_generation", WorldGeneration.current(mc.level));
        }
        obj.add("world", world);
        obj.add("guarded_movement", GuardedGameMovement.status());
        obj.add("guarded_turn", GuardedGameTurning.capabilities());

        JsonObject player = new JsonObject();
        player.addProperty("present", mc.player != null);
        if (mc.player != null) {
            player.addProperty("name", boundedText(mc.player.getGameProfile().getName()));
            player.addProperty("uuid", mc.player.getUUID().toString());
            player.addProperty("x", mc.player.getX());
            player.addProperty("y", mc.player.getY());
            player.addProperty("z", mc.player.getZ());
            player.addProperty("yaw", mc.player.getYRot());
            player.addProperty("pitch", mc.player.getXRot());
        }
        obj.add("player", player);

        Screen currentScreen = mc.screen;
        JsonObject screen = new JsonObject();
        screen.addProperty("present", currentScreen != null);
        if (currentScreen != null) {
            screen.addProperty("class", currentScreen.getClass().getName());
            screen.addProperty("title", boundedText(currentScreen.getTitle().getString()));
            screen.addProperty("width", currentScreen.width);
            screen.addProperty("height", currentScreen.height);
        }
        obj.add("screen", screen);

        JsonObject window = new JsonObject();
        window.addProperty("width", mc.getWindow().getWidth());
        window.addProperty("height", mc.getWindow().getHeight());
        window.addProperty("screen_width", mc.getWindow().getScreenWidth());
        window.addProperty("screen_height", mc.getWindow().getScreenHeight());
        window.addProperty("gui_width", mc.getWindow().getGuiScaledWidth());
        window.addProperty("gui_height", mc.getWindow().getGuiScaledHeight());
        window.addProperty("gui_scale", mc.getWindow().getGuiScale());
        window.addProperty("fullscreen", mc.getWindow().isFullscreen());
        window.addProperty("active", mc.isWindowActive());
        obj.add("window", window);

        JsonObject pointer = new JsonObject();
        pointer.addProperty("grabbed", mc.mouseHandler.isMouseGrabbed());
        pointer.addProperty("left_pressed", mc.mouseHandler.isLeftPressed());
        pointer.addProperty("right_pressed", mc.mouseHandler.isRightPressed());
        pointer.addProperty("middle_pressed", mc.mouseHandler.isMiddlePressed());
        JsonArray heldButtons = new JsonArray();
        for (int button : HELD_WORLD_MOUSE_BUTTONS) {
            heldButtons.add(button);
        }
        pointer.add("held_world_buttons", heldButtons);
        obj.add("mouse", pointer);

        JsonArray heldMappings = new JsonArray();
        for (KeyMapping mapping : mc.options.keyMappings) {
            if (mapping.isDown()) {
                heldMappings.add(mapping.getName());
            }
        }
        obj.add("held_mappings", heldMappings);
        ClientInputIsolation.Statistics isolationStats = ClientInputIsolation.statistics();
        JsonObject isolation = new JsonObject();
        isolation.addProperty("enabled", ClientInputIsolation.enabled());
        isolation.addProperty("mode", ClientInputIsolation.enabled() ? "process_local_virtual" : "native");
        isolation.addProperty("synthetic_dispatches", isolationStats.syntheticDispatches());
        isolation.addProperty("synthetic_input_callbacks", isolationStats.syntheticInputCallbacks());
        isolation.addProperty("suppressed_native_callbacks", isolationStats.suppressedNativeCallbacks());
        isolation.addProperty("native_callback_registration_blocks", isolationStats.suppressedNativeRegistrations());
        isolation.addProperty("suppressed_cursor_operations", isolationStats.suppressedCursorOperations());
        isolation.addProperty("suppressed_raw_mouse_updates", isolationStats.suppressedRawMouseUpdates());
        isolation.addProperty("virtual_key_reads", isolationStats.virtualKeyReads());
        isolation.addProperty("virtual_clipboard_reads", isolationStats.virtualClipboardReads());
        isolation.addProperty("virtual_clipboard_writes", isolationStats.virtualClipboardWrites());
        isolation.addProperty("held_keys", isolationStats.heldKeys());
        obj.add("input_isolation", isolation);

        InputEventProbe.Statistics probeStats = InputEventProbe.statistics();
        JsonObject probe = new JsonObject();
        probe.addProperty("installed", probeStats.installed());
        probe.addProperty("mouse_button_events", probeStats.mouseButtonEvents());
        probe.addProperty("mouse_button_events_cancelled_by_mods", probeStats.mouseButtonEventsCancelled());
        probe.addProperty("key_events", probeStats.keyEvents());
        probe.addProperty("scroll_events", probeStats.scrollEvents());
        probe.addProperty("scroll_events_cancelled_by_mods", probeStats.scrollEventsCancelled());
        probe.addProperty("interaction_events", probeStats.interactionEvents());
        probe.addProperty("interaction_events_cancelled_by_mods", probeStats.interactionEventsCancelled());
        addObservation(probe, "last_mouse_button", probeStats.lastMouseButton());
        addObservation(probe, "last_key", probeStats.lastKey());
        addObservation(probe, "last_scroll", probeStats.lastScroll());
        addObservation(probe, "last_interaction", probeStats.lastInteraction());
        obj.add("mod_input_events", probe);
        return obj;
    }

    private static void addObservation(JsonObject parent, String name, InputEventProbe.Observation observation) {
        if (observation == null) {
            return;
        }
        JsonObject entry = new JsonObject();
        entry.addProperty("device", observation.device());
        if (observation.code() >= 0) {
            entry.addProperty("code", observation.code());
        }
        if (observation.action() >= 0) {
            entry.addProperty("action", observation.action());
        }
        entry.addProperty("cancelled_by_mod", observation.cancelled());
        if (!observation.mapping().isEmpty()) {
            entry.addProperty("mapping", observation.mapping());
        }
        parent.add(name, entry);
    }

    private static byte[] captureFrame() throws IOException {
        Minecraft mc = Minecraft.getInstance();
        if (mc.getMainRenderTarget() == null) {
            throw new IOException("Minecraft main render target is unavailable");
        }

        try (NativeImage image = Screenshot.takeScreenshot(mc.getMainRenderTarget())) {
            byte[] png = image.asByteArray();
            if (png.length > MAX_FRAME_BYTES) {
                throw new FrameTooLargeException(png.length);
            }
            return png;
        }
    }

    private static EndpointResult applyKeyAction(String mappingName, String action, boolean exact) {
        Minecraft mc = Minecraft.getInstance();
        KeyMapping selected = null;
        for (KeyMapping mapping : mc.options.keyMappings) {
            if (mappingName.equals(mapping.getName())) {
                selected = mapping;
                break;
            }
        }

        if (selected == null) {
            return new EndpointResult(404, error("mapping_not_found", "No exact KeyMapping.getName() match"));
        }

        // A mapping is only a name for the key the player would press. Drive that key through the
        // same client handler a real device drives, so KeyMapping bookkeeping and the NeoForge
        // input events both happen exactly as they do for a physical press.
        InputConstants.Key boundKey = selected.getKey();
        if (!exact && boundKey.getType() == InputConstants.Type.MOUSE && mc.screen != null) {
            // The screen route clicks whatever the virtual pointer sits on rather than publishing a
            // button event, so it would press a random widget instead of activating the mapping.
            return new EndpointResult(409, error(
                    "mouse_mapping_requires_no_screen",
                    "This mapping is bound to a mouse button. Close the screen, or use kind mouse "
                            + "with x and y for a GUI click, or exact for the mapping alone"));
        }
        EndpointResult delivered = exact ? borrowKeyForMapping(mc, selected, action) : switch (boundKey.getType()) {
            case MOUSE -> applyMouseAction(Double.NaN, Double.NaN, boundKey.getValue(), action, 0.0);
            case KEYSYM -> boundKey.getValue() < 0
                    ? borrowKeyForMapping(mc, selected, action)
                    : applyRawKeyForKey(mc, boundKey, action);
            default -> borrowKeyForMapping(mc, selected, action);
        };

        JsonObject obj = delivered.body().deepCopy();
        obj.addProperty("mapping", selected.getName());
        obj.addProperty("action", action);
        obj.addProperty("key", selected.saveString());
        obj.addProperty("key_type", boundKey.getType().name().toLowerCase(Locale.ROOT));
        obj.addProperty("exact", exact);
        obj.addProperty("mapping_down", selected.isDown());
        return new EndpointResult(delivered.status(), obj);
    }

    /**
     * Borrows a spare keyboard key for the length of one real keyboard event and gives it straight
     * back. This is how an unbound mapping is driven at all, and how an exact request activates only
     * the mapping it names instead of every mapping that shares the same physical key.
     */
    private static EndpointResult borrowKeyForMapping(Minecraft mc, KeyMapping selected, String action) {
        InputConstants.Key temporaryKey = findUnusedKeyboardKey(mc);
        if (temporaryKey == null) {
            return new EndpointResult(409, error(
                    "no_temporary_mapping_key",
                    "No unused keyboard key is available for an exact mapping click"));
        }
        if (!action.equals("click")) {
            // The mapping is only bound to the borrowed key for the length of one event, so a hold
            // cannot be delivered this way. Setting the mapping down by hand instead would publish
            // no event at all, which is the gap this route exists to close, so refuse it plainly.
            return new EndpointResult(409, error(
                    "borrowed_key_hold_unsupported",
                    "Only a click can be delivered for an unbound or exact mapping. Bind the mapping "
                            + "to a key, or use kind raw_key or mouse to hold that key"));
        }

        InputConstants.Key originalKey = selected.getKey();
        selected.setKey(temporaryKey);
        KeyMapping.resetMapping();
        try {
            EndpointResult borrowed = applyRawKeyForKey(mc, temporaryKey, "click");
            // The borrowed key is an implementation detail; do not report it as the mapping's key.
            JsonObject obj = borrowed.body().deepCopy();
            obj.remove("key");
            obj.addProperty("borrowed_key", temporaryKey.getName());
            obj.addProperty("borrowed_key_code", obj.remove("key_code").getAsInt());
            return new EndpointResult(borrowed.status(), obj);
        } finally {
            // The release dispatched above already cleared the mapping through KeyMapping.set,
            // so nothing here may touch its down state: it could belong to another held input.
            selected.setKey(originalKey);
            KeyMapping.resetMapping();
        }
    }

    private static InputConstants.Key findUnusedKeyboardKey(Minecraft mc) {
        for (int keyCode = MAX_GLFW_KEY_CODE; keyCode >= 32; keyCode--) {
            InputConstants.Key candidate = InputConstants.Type.KEYSYM.getOrCreate(keyCode);
            boolean used = false;
            for (KeyMapping mapping : mc.options.keyMappings) {
                if (candidate.equals(mapping.getKey())) {
                    used = true;
                    break;
                }
            }
            if (!used) {
                return candidate;
            }
        }
        return null;
    }

    private static EndpointResult applyRawKeyAction(String keyName, String action) {
        final InputConstants.Key key;
        try {
            key = resolveKeyboardKey(keyName);
        } catch (IllegalArgumentException e) {
            return new EndpointResult(400, error("invalid_key", e.getMessage()));
        }
        return applyRawKeyForKey(Minecraft.getInstance(), key, action);
    }

    private static EndpointResult applyRawKeyForKey(Minecraft mc, InputConstants.Key key, String action) {
        if (!mc.isSameThread()) {
            throw new IllegalStateException("Raw key input must run on the Minecraft thread");
        }
        long window = mc.getWindow().getWindow();
        boolean wasDown = HELD_RAW_KEYS.contains(key);
        ArrayList<InputEventProbe.Observation> observed = new ArrayList<>();
        int events = 0;
        switch (action) {
            case "down" -> {
                if (!wasDown) {
                    HELD_RAW_KEYS.add(key);
                    addObserved(observed, dispatchRawKeyboard(mc, window, key, InputConstants.PRESS));
                    events = 1;
                }
            }
            case "up" -> {
                if (wasDown) {
                    addObserved(observed, dispatchRawKeyboard(mc, window, key, InputConstants.RELEASE));
                    HELD_RAW_KEYS.remove(key);
                    events = 1;
                }
            }
            case "click" -> {
                if (!wasDown) {
                    HELD_RAW_KEYS.add(key);
                    addObserved(observed, dispatchRawKeyboard(mc, window, key, InputConstants.PRESS));
                    events++;
                }
                addObserved(observed, dispatchRawKeyboard(mc, window, key, InputConstants.RELEASE));
                HELD_RAW_KEYS.remove(key);
                events++;
            }
            default -> throw new IllegalArgumentException("Unsupported raw key action: " + action);
        }

        JsonObject obj = ok();
        obj.addProperty("key", key.getName());
        obj.addProperty("key_code", key.getValue());
        obj.addProperty("action", action);
        obj.addProperty("was_down", wasDown);
        obj.addProperty("down", HELD_RAW_KEYS.contains(key));
        obj.addProperty("events", events);
        addEventDelivery(obj, observed);
        return new EndpointResult(200, obj);
    }

    private static InputEventProbe.Observation dispatchRawKeyboard(
            Minecraft mc, long window, InputConstants.Key key, int action) {
        ClientInputIsolation.setKeyDown(key.getValue(), action != InputConstants.RELEASE);
        long probeSequence = InputEventProbe.keySequence();
        mc.keyboardHandler.keyPress(window, key.getValue(), -1, action, ClientInputIsolation.modifiers());
        return InputEventProbe.keySince(probeSequence, key.getValue(), action);
    }

    /**
     * Reports what a dispatch published. A press and its release are separate events and a mod may
     * cancel either, so each is listed; {@code event_cancelled_by_mod} is true when a mod cancelled
     * any of them. {@code event_fired} false does not always mean the input was lost: a screen that
     * consumes a key returns before Minecraft publishes the event, exactly as it does for a device.
     */
    private static void addEventDelivery(JsonObject obj, List<InputEventProbe.Observation> observations) {
        JsonObject delivery = new JsonObject();
        delivery.addProperty("probe_installed", InputEventProbe.installed());
        delivery.addProperty("event_fired", !observations.isEmpty());
        boolean cancelled = false;
        JsonArray events = new JsonArray();
        for (InputEventProbe.Observation observation : observations) {
            cancelled |= observation.cancelled();
            JsonObject entry = new JsonObject();
            entry.addProperty("action", observation.action());
            entry.addProperty("cancelled_by_mod", observation.cancelled());
            events.add(entry);
        }
        delivery.addProperty("event_cancelled_by_mod", cancelled);
        delivery.add("events", events);
        obj.add("mod_input_event", delivery);
    }

    private static void addObserved(
            List<InputEventProbe.Observation> observations, InputEventProbe.Observation observation) {
        if (observation != null) {
            observations.add(observation);
        }
    }

    private static InputConstants.Key resolveKeyboardKey(String input) {
        String keyName = input.trim().toLowerCase(Locale.ROOT);
        if (!keyName.startsWith("key.keyboard.")) {
            keyName = "key.keyboard." + keyName
                    .replace('_', '.')
                    .replace('-', '.')
                    .replace(' ', '.');
        }

        InputConstants.Key key = InputConstants.getKey(keyName);
        if (key.getType() != InputConstants.Type.KEYSYM
                || key.getValue() < 0
                || key.getValue() > MAX_GLFW_KEY_CODE) {
            throw new IllegalArgumentException("key must identify a valid GLFW keyboard key");
        }
        return key;
    }

    /** Compare and apply on the same game-thread turn, without taking any key ownership. */
    private static EndpointResult applyGuardedAimLook(double yaw, double pitch, AimViewGuard guard) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.level == null) return new EndpointResult(409, error("not_in_world"));
        if (!mc.player.isAlive()) return new EndpointResult(409, error("player_unavailable"));
        if (mc.screen != null) return new EndpointResult(409, error("screen_opened"));
        if (mc.isPaused()) return new EndpointResult(409, error("game_paused"));
        if (ClientActions.ownsInput() || GuardedGameMovement.LEASES.status().ownerRequestId() != null)
            return new EndpointResult(409, error("action_owns_view"));
        Entity target = mc.level.getEntity(guard.entityId());
        String rejected = guard.rejection(WorldGeneration.current(mc.level), mc.player.getUUID().toString(),
                ClientActions.session(), mc.level.getGameTime(), mc.player.getYRot(), mc.player.getXRot(),
                target == null ? null : target.getUUID().toString(), target != null && target.isAlive());
        if (rejected != null) return new EndpointResult(409, error(rejected));
        EndpointResult result = applyLook(yaw, pitch, false);
        result.body().addProperty("aim_view_guard_schema_version", AimViewGuard.SCHEMA);
        return result;
    }

    private static EndpointResult applyLook(double yawInput, double pitchInput, boolean relative) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.level == null) {
            return new EndpointResult(409, error("not_in_world"));
        }
        if (Math.abs(yawInput) > 1_000_000.0 || Math.abs(pitchInput) > 1_000_000.0) {
            return new EndpointResult(400, error("look_value_out_of_range"));
        }

        float yaw = relative
                ? mc.player.getYRot() + (float) yawInput
                : (float) yawInput;
        float pitch = relative
                ? mc.player.getXRot() + (float) pitchInput
                : (float) pitchInput;
        yaw = Mth.wrapDegrees(yaw);
        pitch = Mth.clamp(pitch, -90.0F, 90.0F);
        mc.player.setYRot(yaw);
        mc.player.setXRot(pitch);
        mc.player.setYHeadRot(yaw);
        mc.player.setYBodyRot(yaw);

        JsonObject obj = ok();
        obj.addProperty("yaw", mc.player.getYRot());
        obj.addProperty("pitch", mc.player.getXRot());
        obj.addProperty("relative", relative);
        return new EndpointResult(200, obj);
    }

    private static EndpointResult applyMouseAction(
            double x,
            double y,
            int button,
            String action,
            double scrollY) {
        Minecraft mc = Minecraft.getInstance();
        Screen currentScreen = mc.screen;
        if (currentScreen == null) {
            return applyWorldMouseAction(mc, button, action, scrollY);
        }

        if (HELD_WORLD_MOUSE_BUTTONS.contains(button) && action.equals("down")) {
            JsonObject obj = ok();
            obj.addProperty("screen", currentScreen.getClass().getName());
            obj.addProperty("action", action);
            obj.addProperty("scope", "world");
            obj.addProperty("button", button);
            obj.addProperty("handled", true);
            obj.addProperty("screen_transition", true);
            obj.addProperty("down", true);
            return new EndpointResult(200, obj);
        }

        if (HELD_WORLD_MOUSE_BUTTONS.contains(button)
                && (action.equals("up") || action.equals("release") || action.equals("click"))) {
            ArrayList<InputEventProbe.Observation> observed = new ArrayList<>();
            releaseHeldWorldMouseButton(mc, button, observed);
            JsonObject obj = ok();
            obj.addProperty("screen", currentScreen.getClass().getName());
            obj.addProperty("action", action);
            obj.addProperty("scope", "world");
            obj.addProperty("button", button);
            obj.addProperty("handled", true);
            obj.addProperty("screen_transition", true);
            obj.addProperty("down", false);
            addEventDelivery(obj, observed);
            return new EndpointResult(200, obj);
        }

        double screenX = Double.isNaN(x)
                ? mc.mouseHandler.xpos() * currentScreen.width / mc.getWindow().getScreenWidth()
                : x;
        double screenY = Double.isNaN(y)
                ? mc.mouseHandler.ypos() * currentScreen.height / mc.getWindow().getScreenHeight()
                : y;
        currentScreen.mouseMoved(screenX, screenY);
        boolean handled = false;
        boolean pressed = false;
        boolean released = false;
        switch (action) {
            case "move" -> handled = true;
            case "down" -> handled = pressed = currentScreen.mouseClicked(screenX, screenY, button);
            case "up", "release" -> handled = released = currentScreen.mouseReleased(screenX, screenY, button);
            case "click" -> {
                pressed = currentScreen.mouseClicked(screenX, screenY, button);
                released = currentScreen.mouseReleased(screenX, screenY, button);
                handled = pressed || released;
            }
            case "scroll" -> handled = currentScreen.mouseScrolled(screenX, screenY, 0.0, scrollY);
            default -> throw new IllegalArgumentException("Unsupported mouse action: " + action);
        }

        JsonObject obj = ok();
        obj.addProperty("screen", currentScreen.getClass().getName());
        obj.addProperty("action", action);
        obj.addProperty("scope", "screen");
        obj.addProperty("x", screenX);
        obj.addProperty("y", screenY);
        obj.addProperty("button", button);
        obj.addProperty("scroll_y", scrollY);
        obj.addProperty("handled", handled);
        if (action.equals("click")) {
            obj.addProperty("pressed", pressed);
            obj.addProperty("released", released);
        }
        return new EndpointResult(200, obj);
    }

    private static EndpointResult applyWorldMouseAction(
            Minecraft mc,
            int button,
            String action,
            double scrollY) {
        if (mc.player == null || mc.level == null) {
            return new EndpointResult(409, error("not_in_world"));
        }
        if (action.equals("move")) {
            return new EndpointResult(409, error(
                    "world_move_requires_look",
                    "Use /control/look for world camera movement"));
        }

        boolean wasDown = HELD_WORLD_MOUSE_BUTTONS.contains(button);
        ArrayList<InputEventProbe.Observation> observed = new ArrayList<>();
        int events = 0;
        boolean handled;
        if (action.equals("scroll")) {
            long probeSequence = InputEventProbe.scrollSequence();
            handled = ClientHooks.onMouseScroll(mc.mouseHandler, 0.0, scrollY);
            addObserved(observed, InputEventProbe.scrollSince(probeSequence));
            events = 1;
            if (!handled) {
                mc.player.getInventory().swapPaint(scrollY);
                handled = true;
            }
        } else {
            switch (action) {
                case "down" -> {
                    if (HELD_WORLD_MOUSE_BUTTONS.add(button)) {
                        addObserved(observed, dispatchWorldMouseButton(mc, button, GLFW.GLFW_PRESS));
                        events = 1;
                    }
                }
                case "up", "release" -> {
                    if (releaseHeldWorldMouseButton(mc, button, observed)) {
                        events = 1;
                    }
                }
                case "click" -> {
                    if (HELD_WORLD_MOUSE_BUTTONS.contains(button)) {
                        releaseHeldWorldMouseButton(mc, button, observed);
                        events = 1;
                    } else {
                        try {
                            addObserved(observed, dispatchWorldMouseButton(mc, button, GLFW.GLFW_PRESS));
                            events++;
                        } finally {
                            releaseWorldMouseButton(mc, button, observed);
                            events++;
                        }
                    }
                }
                default -> throw new IllegalArgumentException("Unsupported mouse action: " + action);
            }
            handled = true;
        }

        JsonObject obj = ok();
        obj.addProperty("scope", "world");
        obj.addProperty("action", action);
        obj.addProperty("button", button);
        obj.addProperty("scroll_y", scrollY);
        obj.addProperty("handled", handled);
        obj.addProperty("was_down", wasDown);
        obj.addProperty("down", HELD_WORLD_MOUSE_BUTTONS.contains(button));
        obj.addProperty("events", events);
        obj.addProperty("mouse_grabbed", mc.mouseHandler.isMouseGrabbed());
        addEventDelivery(obj, observed);
        return new EndpointResult(200, obj);
    }

    private static InputEventProbe.Observation dispatchWorldMouseButton(Minecraft mc, int button, int action) {
        long probeSequence = InputEventProbe.mouseButtonSequence();
        mc.mouseHandler.onPress(mc.getWindow().getWindow(), button, action, ClientInputIsolation.modifiers());
        return InputEventProbe.mouseButtonSince(probeSequence, button, action);
    }

    private static boolean releaseHeldWorldMouseButton(
            Minecraft mc, int button, List<InputEventProbe.Observation> observed) {
        if (HELD_WORLD_MOUSE_BUTTONS.remove(button)) {
            releaseWorldMouseButton(mc, button, observed);
            return true;
        }
        return false;
    }

    private static void releaseWorldMouseButton(
            Minecraft mc, int button, List<InputEventProbe.Observation> observed) {
        try {
            addObserved(observed, dispatchWorldMouseButton(mc, button, GLFW.GLFW_RELEASE));
        } finally {
            KeyMapping.set(InputConstants.Type.MOUSE.getOrCreate(button), false);
            if (button == GLFW.GLFW_MOUSE_BUTTON_LEFT) {
                mc.mouseHandler.isLeftPressed = false;
            } else if (button == GLFW.GLFW_MOUSE_BUTTON_RIGHT) {
                mc.mouseHandler.isRightPressed = false;
            } else if (button == GLFW.GLFW_MOUSE_BUTTON_MIDDLE) {
                mc.mouseHandler.isMiddlePressed = false;
            }
        }
    }

    private static EndpointResult applyScreenText(String text, boolean submit) {
        Minecraft mc = Minecraft.getInstance();
        Screen currentScreen = mc.screen;
        if (currentScreen == null) {
            return new EndpointResult(409, error("no_active_screen"));
        }

        if (submit) {
            if (!(currentScreen instanceof ChatScreen chatScreen)) {
                return new EndpointResult(409, error(
                        "submit_requires_chat_screen",
                        "submit=true is supported only for an active ChatScreen"));
            }
            chatScreen.handleChatInput(text, true);
            boolean closed = mc.screen == chatScreen;
            if (closed) {
                mc.setScreen(null);
            }
            JsonObject obj = ok();
            obj.addProperty("screen", chatScreen.getClass().getName());
            obj.addProperty("submitted", true);
            obj.addProperty("closed", closed);
            return new EndpointResult(200, obj);
        }

        GuiEventListener focused = currentScreen.getFocused();
        if (focused == null) {
            return new EndpointResult(409, error("no_focused_widget"));
        }
        int handledCharacters = 0;
        for (int i = 0; i < text.length(); i++) {
            if (currentScreen.charTyped(text.charAt(i), 0)) {
                handledCharacters++;
            }
        }

        JsonObject obj = ok();
        obj.addProperty("screen", currentScreen.getClass().getName());
        obj.addProperty("focused", focused.getClass().getName());
        obj.addProperty("characters", text.length());
        obj.addProperty("handled_characters", handledCharacters);
        obj.addProperty("handled", handledCharacters > 0);
        obj.addProperty("submitted", false);
        return new EndpointResult(200, obj);
    }

    private static EndpointResult applyCommand(String command) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.getConnection() == null) {
            return new EndpointResult(409, error("not_in_world"));
        }

        mc.getConnection().sendCommand(command);
        JsonObject obj = ok();
        obj.addProperty("submitted", true);
        return new EndpointResult(200, obj);
    }

    private static <T> T callOnMinecraftThread(Callable<T> operation, long timeoutSeconds)
            throws InterruptedException, ExecutionException, TimeoutException {
        CompletableFuture<T> result = new CompletableFuture<>();
        try {
            Minecraft.getInstance().execute(() -> {
                if (result.isDone()) {
                    return;
                }
                ClientInputIsolation.syntheticDispatch(() -> {
                    try {
                        result.complete(operation.call());
                    } catch (Throwable error) {
                        result.completeExceptionally(error);
                    }
                });
            });
        } catch (RejectedExecutionException | IllegalStateException e) {
            result.completeExceptionally(e);
        }
        try {
            return result.get(timeoutSeconds, TimeUnit.SECONDS);
        } catch (TimeoutException e) {
            result.cancel(false);
            throw e;
        }
    }

    private static boolean requireControlAccess(HttpExchange exchange, String path, String method)
            throws IOException {
        if (!path.equals(exchange.getRequestURI().getPath())) {
            respondJson(exchange, 404, error("unknown_endpoint"));
            return false;
        }

        InetAddress remoteAddress = exchange.getRemoteAddress().getAddress();
        if (remoteAddress == null || !remoteAddress.isLoopbackAddress()) {
            respondJson(exchange, 403, error("loopback_only"));
            return false;
        }
        if (!isBearerAuthorized(exchange)) {
            exchange.getResponseHeaders().set("WWW-Authenticate", "Bearer");
            respondJson(exchange, 401, error("unauthorized"));
            return false;
        }
        // The startup-only recovery profile never shares a live mutation catalogue with legacy owners.
        if(NativeRecoveryShortInput.ENABLED&&!method.equals("GET")&&!path.startsWith(NativeRecoveryShortInput.ROOT)&&!path.startsWith(RecoveryInteraction.ROOT)&&!path.startsWith(RecoveryInteraction.V2_ROOT)&&!path.startsWith(RecoveryInteraction.V3_ROOT)){
            respondJson(exchange,409,error("recovery_short_input_exclusive_mode"));return false;
        }
        if(!method.equals("GET") && NativeWorldBackup.blocksMutation(path)) {
            respondJson(exchange,409,error("world_backup_snapshot_in_progress"));return false;
        }
        return requireMethod(exchange, method);
    }

    private static boolean requireMethod(HttpExchange exchange, String method) throws IOException {
        if (method.equalsIgnoreCase(exchange.getRequestMethod())) {
            return true;
        }
        exchange.getResponseHeaders().add("Allow", method.toUpperCase(Locale.ROOT));
        respondJson(exchange, 405, error("method_not_allowed"));
        return false;
    }

    private static boolean isBearerAuthorized(HttpExchange exchange) {
        String expected = config().token();
        if (expected.isBlank()) {
            return false;
        }

        String authorization = exchange.getRequestHeaders().getFirst("Authorization");
        if (authorization == null || !authorization.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return false;
        }
        String supplied = authorization.substring(7);
        return BridgeSecurity.bearerMatches(expected, authorization);
    }

    private static JsonObject readJsonObjectOrRespond(HttpExchange exchange, boolean allowEmpty)
            throws IOException {
        try {
            byte[] bytes = readBody(exchange);
            if (bytes.length == 0) {
                if (allowEmpty) {
                    return new JsonObject();
                }
                throw new RequestException(400, "empty_body", "A JSON object body is required");
            }

            JsonElement parsed;
            try {
                parsed = JsonParser.parseString(new String(bytes, StandardCharsets.UTF_8));
            } catch (RuntimeException e) {
                throw new RequestException(400, "invalid_json", "Request body is not valid JSON");
            }
            if (!parsed.isJsonObject()) {
                throw new RequestException(400, "invalid_json", "Request body must be a JSON object");
            }
            return parsed.getAsJsonObject();
        } catch (RequestException e) {
            respondRequestFailure(exchange, e);
            return null;
        }
    }

    private static byte[] readBody(HttpExchange exchange) throws IOException, RequestException {
        String contentLength = exchange.getRequestHeaders().getFirst("Content-Length");
        if (contentLength != null) {
            try {
                long declaredLength = Long.parseLong(contentLength);
                if (declaredLength < 0) {
                    throw new RequestException(400, "invalid_content_length", "Content-Length must not be negative");
                }
                if (declaredLength > MAX_BODY_BYTES) {
                    throw new RequestException(413, "body_too_large",
                            "Request body exceeds " + MAX_BODY_BYTES + " bytes");
                }
            } catch (NumberFormatException e) {
                throw new RequestException(400, "invalid_content_length", "Content-Length is not a number");
            }
        }

        try (InputStream in = exchange.getRequestBody()) {
            byte[] bytes = in.readNBytes(MAX_BODY_BYTES + 1);
            if (bytes.length > MAX_BODY_BYTES) {
                throw new RequestException(413, "body_too_large",
                        "Request body exceeds " + MAX_BODY_BYTES + " bytes");
            }
            return bytes;
        }
    }

    private static void respondRequestFailure(HttpExchange exchange, RequestException e) throws IOException {
        respondJson(exchange, e.status(), error(e.code(), e.getMessage()));
    }

    private static void respondMinecraftFailure(HttpExchange exchange, String operationCode, Exception e)
            throws IOException {
        respondMinecraftFailure(exchange,operationCode,e,null);
    }

    private static void respondMinecraftFailure(HttpExchange exchange, String operationCode, Exception e,
                                                BridgeReadTiming timing) throws IOException {
        if (e instanceof TimeoutException) {
            respondJson(exchange, 504, error("minecraft_thread_timeout",
                    "Minecraft did not complete the operation within the configured timeout"), timing);
            return;
        }
        if (e instanceof InterruptedException) {
            Thread.currentThread().interrupt();
            respondJson(exchange, 503, error("request_interrupted"), timing);
            return;
        }

        Throwable cause = e instanceof ExecutionException && e.getCause() != null ? e.getCause() : e;
        if (cause instanceof FrameTooLargeException frameTooLarge) {
            respondJson(exchange, 500, error("frame_too_large", frameTooLarge.getMessage()), timing);
            return;
        }

        JsonObject obj = error(operationCode);
        obj.addProperty("detail", exceptionDetail(cause));
        respondJson(exchange, 500, obj, timing);
    }

    private static void respondJson(HttpExchange exchange, int status, JsonObject body) throws IOException {
        respondJson(exchange,status,body,null);
    }

    private static void respondJson(HttpExchange exchange, int status, JsonObject body, BridgeReadTiming timing) throws IOException {
        if(timing!=null) timing.encodingStarted();
        byte[] bytes = BridgeJson.toJson(body).getBytes(StandardCharsets.UTF_8);
        if (bytes.length > MAX_JSON_BYTES) {
            status = 500;
            bytes = BridgeJson.toJson(error("response_too_large",
                    "JSON response exceeds " + MAX_JSON_BYTES + " bytes"))
                    .getBytes(StandardCharsets.UTF_8);
        }
        if(timing!=null) { timing.encodingFinished();timing.addHeaders(exchange.getResponseHeaders()); }
        respondBytes(exchange, status, "application/json; charset=utf-8", bytes);
    }

    private static void respondBytes(HttpExchange exchange, int status, String contentType, byte[] bytes)
            throws IOException {
        exchange.getResponseHeaders().set("Content-Type", contentType);
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(bytes);
        }
    }

    private static JsonObject ok() {
        JsonObject obj = new JsonObject();
        obj.addProperty("ok", true);
        return obj;
    }

    private static JsonObject error(String code) {
        JsonObject obj = new JsonObject();
        obj.addProperty("ok", false);
        obj.addProperty("error", code);
        return obj;
    }

    private static JsonObject error(String code, String message) {
        JsonObject obj = error(code);
        obj.addProperty("message", boundedText(message));
        return obj;
    }

    private static String requiredString(JsonObject obj, String key) throws RequestException {
        JsonElement value = obj.get(key);
        if (value == null || value.isJsonNull() || !value.isJsonPrimitive()
                || !value.getAsJsonPrimitive().isString()) {
            throw new RequestException(400, "invalid_" + key, key + " must be a string");
        }
        String text = value.getAsString();
        if (text.length() > MAX_TEXT_LENGTH) {
            throw new RequestException(400, "invalid_" + key,
                    key + " exceeds " + MAX_TEXT_LENGTH + " characters");
        }
        return text;
    }

    private static double requiredFiniteDouble(JsonObject obj, String key) throws RequestException {
        JsonElement value = obj.get(key);
        if (value == null || value.isJsonNull() || !value.isJsonPrimitive()
                || !value.getAsJsonPrimitive().isNumber()) {
            throw new RequestException(400, "invalid_" + key, key + " must be a number");
        }
        double number = value.getAsDouble();
        if (!Double.isFinite(number)) {
            throw new RequestException(400, "invalid_" + key, key + " must be finite");
        }
        return number;
    }

    private static double requiredBoundedCoordinate(JsonObject obj, String key) throws RequestException {
        double coordinate = requiredFiniteDouble(obj, key);
        if (Math.abs(coordinate) > MAX_GUI_COORDINATE) {
            throw new RequestException(400, "invalid_" + key,
                    key + " is outside the supported GUI coordinate range");
        }
        return coordinate;
    }

    private static boolean optionalBoolean(JsonObject obj, String key, boolean fallback)
            throws RequestException {
        JsonElement value = obj.get(key);
        if (value == null || value.isJsonNull()) return fallback;
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isBoolean()) {
            throw new RequestException(400, "invalid_" + key, key + " must be a boolean");
        }
        return value.getAsBoolean();
    }

    private static int optionalInteger(JsonObject obj, String key, int fallback) throws RequestException {
        JsonElement value = obj.get(key);
        if (value == null || value.isJsonNull()) return fallback;
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()) {
            throw new RequestException(400, "invalid_" + key, key + " must be an integer");
        }
        double number = value.getAsDouble();
        if (!Double.isFinite(number) || number != Math.rint(number)
                || number < Integer.MIN_VALUE || number > Integer.MAX_VALUE) {
            throw new RequestException(400, "invalid_" + key, key + " must be an integer");
        }
        return (int) number;
    }

    private static double queryDouble(
            HttpExchange exchange,
            String key,
            double fallback,
            double minimum,
            double maximum) throws RequestException {
        String rawQuery = exchange.getRequestURI().getRawQuery();
        if (rawQuery == null || rawQuery.isBlank()) return fallback;

        String found = null;
        try {
            for (String part : rawQuery.split("&")) {
                int separator = part.indexOf('=');
                String rawName = separator < 0 ? part : part.substring(0, separator);
                String name = URLDecoder.decode(rawName, StandardCharsets.UTF_8);
                if (!key.equals(name)) continue;
                if (found != null) {
                    throw new RequestException(400, "duplicate_" + key,
                            key + " must be supplied at most once");
                }
                String rawValue = separator < 0 ? "" : part.substring(separator + 1);
                found = URLDecoder.decode(rawValue, StandardCharsets.UTF_8);
            }
        } catch (IllegalArgumentException e) {
            throw new RequestException(400, "invalid_query", "Query string encoding is invalid");
        }
        if (found == null) return fallback;

        final double value;
        try {
            value = Double.parseDouble(found);
        } catch (NumberFormatException e) {
            throw new RequestException(400, "invalid_" + key, key + " must be a number");
        }
        if (!Double.isFinite(value) || value < minimum || value > maximum) {
            throw new RequestException(400, "invalid_" + key,
                    key + " must be between " + minimum + " and " + maximum);
        }
        return value;
    }

    private static void validateScreenText(String text) throws RequestException {
        if (text.isEmpty()) {
            throw new RequestException(400, "empty_text", "text must not be empty");
        }
        for (int offset = 0; offset < text.length();) {
            int codePoint = text.codePointAt(offset);
            if (codePoint > Character.MAX_VALUE) {
                throw new RequestException(400, "unsupported_character",
                        "The active Screen charTyped API accepts only BMP characters");
            }
            if (Character.isISOControl(codePoint)) {
                throw new RequestException(400, "unsupported_character",
                        "Control characters are not accepted by the text endpoint");
            }
            offset += Character.charCount(codePoint);
        }
    }

    private static String normalizeCommand(String input) throws RequestException {
        String command = input.trim();
        if (command.startsWith("/")) {
            command = command.substring(1).stripLeading();
        }
        if (command.isEmpty()) {
            throw new RequestException(400, "empty_command", "command must not be empty");
        }
        if (command.length() > MAX_COMMAND_LENGTH) {
            throw new RequestException(400, "invalid_command",
                    "command exceeds " + MAX_COMMAND_LENGTH + " characters");
        }
        for (int offset = 0; offset < command.length();) {
            int codePoint = command.codePointAt(offset);
            if (Character.isISOControl(codePoint)) {
                throw new RequestException(400, "unsupported_character",
                        "Control characters are not accepted by the command endpoint");
            }
            offset += Character.charCount(codePoint);
        }
        return command;
    }

    static String runId() {
        String value = identityValue(
                "mineclientBridge.runId",
                "MINECLIENT_BRIDGE_RUN_ID");
        if (value.isBlank()) {
            return "manual";
        }
        return value;
    }

    private static String identityValue(String propertyName, String environmentName) {
        String value = System.getProperty(propertyName);
        if (value == null || value.isBlank()) {
            value = System.getenv(environmentName);
        }
        if (value == null || value.isBlank()) {
            return "";
        }
        return value.trim();
    }

    private static String boundedText(String value) {
        if (value == null) return "";
        if (value.length() <= MAX_TEXT_LENGTH) return value;
        return value.substring(0, MAX_TEXT_LENGTH);
    }

    private static String exceptionDetail(Throwable error) {
        String message = error.getMessage();
        String detail = error.getClass().getSimpleName();
        if (message != null && !message.isBlank()) {
            detail += ": " + message;
        }
        return boundedText(detail);
    }

    private static void releaseAllOnMinecraftThread(ManagedNavigationInputPolicy.Token managedShutdown) {
        if(NativeRecoveryShortInput.ENABLED)return; // Only the exact new ticket may release its captured Input.
        try {
            Minecraft mc = Minecraft.getInstance();
            if (mc.isSameThread()) {
                ClientInputIsolation.syntheticDispatch(() -> {
                    NativeManagedNavigation.bridgeStopping(mc,managedShutdown);
                    NativeReactiveGuard.stop("bridge_stopping");
                NativeFallRescue.stop("bridge_stopping");
                    releaseAllInputs();
                });
                return;
            }
            callOnMinecraftThread(() -> {
                NativeManagedNavigation.bridgeStopping(mc,managedShutdown);
                NativeReactiveGuard.stop("bridge_stopping");
                NativeFallRescue.stop("bridge_stopping");
                releaseAllInputs();
                return null;
            }, MINECRAFT_TIMEOUT_SECONDS);
        } catch (Exception e) {
            BridgeLog.LOGGER.warn("Failed to release held input while stopping bridge", e);
        }
    }

    static JsonObject heldInputsSnapshot(Minecraft mc) {
        JsonObject out=new JsonObject();JsonArray keys=new JsonArray();
        for(KeyMapping mapping:mc.options.keyMappings)if(mapping.isDown())keys.add(mapping.getName());
        out.add("keys",keys);out.addProperty("raw_keys",HELD_RAW_KEYS.size());
        out.addProperty("world_mouse_buttons",HELD_WORLD_MOUSE_BUTTONS.size());
        out.addProperty("neutral",keys.isEmpty() && !hasHeldInputs() && !mc.player.isUsingItem());
        return out;
    }
    static boolean hasHeldInputs() { return !HELD_RAW_KEYS.isEmpty() || !HELD_WORLD_MOUSE_BUTTONS.isEmpty(); }

    static int releaseAllInputs() {
        if(NativeRecoveryShortInput.ENABLED){NativeRecoveryShortInput.contextLost("legacy_release_requested");return 0;}
        ClientActions.cancel("inputs_released");
        GuardedGameMovement.cancelOnGameThread("inputs_released");
        Minecraft mc = Minecraft.getInstance();
        if (!mc.isSameThread()) {
            throw new IllegalStateException("Input cleanup must run on the Minecraft thread");
        }

        ArrayList<InputConstants.Key> rawKeys = new ArrayList<>(HELD_RAW_KEYS);
        RuntimeException failure = null;
        for (InputConstants.Key key : rawKeys) {
            try {
                dispatchRawKeyboard(mc, mc.getWindow().getWindow(), key, InputConstants.RELEASE);
                HELD_RAW_KEYS.remove(key);
            } catch (RuntimeException e) {
                if (failure == null) {
                    failure = e;
                } else {
                    failure.addSuppressed(e);
                }
            }
        }

        ArrayList<Integer> worldMouseButtons = new ArrayList<>(HELD_WORLD_MOUSE_BUTTONS);
        for (int button : worldMouseButtons) {
            try {
                releaseHeldWorldMouseButton(mc, button, new ArrayList<>());
            } catch (RuntimeException e) {
                if (failure == null) {
                    failure = e;
                } else {
                    failure.addSuppressed(e);
                }
            }
        }
        KeyMapping.releaseAll();
        ClientInputIsolation.releaseAllKeys();
        if (failure != null) {
            throw failure;
        }
        return rawKeys.size();
    }

    private record EntityDistance(Entity entity, double distance) {
    }

    record EndpointResult(int status, JsonObject body) {
    }

    private static final class RequestException extends Exception {
        private final int status;
        private final String code;

        private RequestException(int status, String code, String message) {
            super(message);
            this.status = status;
            this.code = code;
        }

        private int status() {
            return status;
        }

        private String code() {
            return code;
        }
    }

    private static final class FrameTooLargeException extends IOException {
        private FrameTooLargeException(int bytes) {
            super("Captured PNG is " + bytes + " bytes; limit is " + MAX_FRAME_BYTES + " bytes");
        }
    }
}
