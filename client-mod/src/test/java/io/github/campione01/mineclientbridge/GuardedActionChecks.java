package io.github.campione01.mineclientbridge;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/** Dependency-free logic/race checks. Does not load Minecraft or send HTTP. */
public final class GuardedActionChecks {
    private static final String WORLD = "00000000-0000-0000-0000-000000000001";
    private static final String PLAYER = "00000000-0000-0000-0000-000000000002";
    private static final String TARGET = "00000000-0000-0000-0000-000000000003";
    private static int checks;

    public static void main(String[] args) throws Exception { run(); }
    static void run() throws Exception {
        checks = 0;
        requestBounds();
        weaponBounds();
        executionGuards();
        queuedTimeoutAndGate();
        deadlineAtExecution();
        exceptionsAndInterruption();
        lifecycleAdmission();
        runningMutationCannotOutliveTimeoutResponse();
        sourceContract();
        System.out.println("Guarded action core: " + checks + " checks passed");
    }

    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
    private static void rejected(String code, Runnable action) {
        try { action.run(); throw new AssertionError("Accepted " + code); }
        catch (GuardedAction.Rejected expected) { check(code.equals(expected.getMessage()), code); }
    }
    private static GuardedAction.Request attack() {
        return new GuardedAction.Request("attack", WORLD, PLAYER, TARGET, TARGET, 250, 0, 0);
    }
    private static GuardedAction.Request look(double yaw, double pitch, String crosshair) {
        return new GuardedAction.Request("look", WORLD, PLAYER, TARGET, crosshair, 250, yaw, pitch);
    }
    private static final class Live {
        String world = WORLD, player = PLAYER, target = TARGET, kind = "minecraft:zombie", crosshair = TARGET;
        boolean local = true, ready = true, weapon = true, allowed = true, visible = true;
        double range = 2.0, reach = 3.0, yaw, pitch;
        GuardedAction.State state() {
            return new GuardedAction.State(world, player, local, ready, weapon, target, kind, allowed,
                    crosshair, range, reach, visible, yaw, pitch);
        }
    }
    private static void requestBounds() {
        attack(); checks++;
        look(-180, -90, null); look(179.99, 90, TARGET); checks += 2;
        rejected("invalid_action", () -> new GuardedAction.Request("command", WORLD, PLAYER, TARGET, TARGET, 250, 0, 0));
        for (String bad : new String[]{null, "", "1-1-1-1-1", "not-a-uuid", "f".repeat(512)}) {
            rejected("invalid_identity", () -> new GuardedAction.Request("look", bad, PLAYER, TARGET, null, 250, 0, 0));
            rejected("invalid_identity", () -> new GuardedAction.Request("look", WORLD, bad, TARGET, null, 250, 0, 0));
            rejected("invalid_identity", () -> new GuardedAction.Request("look", WORLD, PLAYER, bad, null, 250, 0, 0));
            if (bad != null) rejected("invalid_identity", () -> look(0, 0, bad));
        }
        for (int ttl : new int[]{Integer.MIN_VALUE, -1, 0, 251, Integer.MAX_VALUE}) {
            rejected("invalid_ttl_ms", () -> new GuardedAction.Request("attack", WORLD, PLAYER, TARGET, TARGET, ttl, 0, 0));
        }
        for (double yaw : new double[]{Double.NaN, Double.POSITIVE_INFINITY, -180.01, 180, 360})
            rejected("invalid_angles", () -> look(yaw, 0, null));
        for (double pitch : new double[]{Double.NaN, Double.NEGATIVE_INFINITY, -90.01, 90.01})
            rejected("invalid_angles", () -> look(0, pitch, null));
        rejected("unexpected_angles", () -> new GuardedAction.Request("attack", WORLD, PLAYER, TARGET, TARGET, 250, 1, 0));
        rejected("attack_requires_expected_crosshair", () -> new GuardedAction.Request("attack", WORLD, PLAYER, TARGET, null, 250, 0, 0));
        rejected("attack_requires_expected_crosshair", () -> new GuardedAction.Request("attack", WORLD, PLAYER, TARGET, PLAYER, 250, 0, 0));
    }
    private static void executionGuards() {
        for (String kind : GuardedAction.HOSTILE_TYPES) {
            Live live = new Live(); live.kind = kind;
            GuardedAction.validate(attack(), live.state()); checks++;
        }
        Live live = new Live(); live.ready = false;
        rejected("player_not_ready", () -> GuardedAction.validate(attack(), live.state()));
        live.ready = true; live.local = false;
        rejected("local_survival_required", () -> GuardedAction.validate(attack(), live.state()));
        live.local = true; live.weapon = false;
        rejected("unenchanted_vanilla_axe_required", () -> GuardedAction.validate(attack(), live.state()));
        live.weapon = true; live.world = TARGET;
        rejected("world_generation_changed", () -> GuardedAction.validate(attack(), live.state()));
        live.world = WORLD; live.player = TARGET;
        rejected("player_changed", () -> GuardedAction.validate(attack(), live.state()));
        live.player = PLAYER; live.target = PLAYER;
        rejected("target_changed", () -> GuardedAction.validate(attack(), live.state()));
        live.target = TARGET; live.crosshair = PLAYER;
        rejected("crosshair_changed", () -> GuardedAction.validate(attack(), live.state()));
        live.crosshair = null;
        rejected("crosshair_changed", () -> GuardedAction.validate(attack(), live.state()));
        GuardedAction.validate(look(30, 20, null), live.state()); checks++;
        live.crosshair = TARGET;
        for (String kind : new String[]{"minecraft:player", "minecraft:wolf", "minecraft:cat", "minecraft:villager",
                "minecraft:enderman", "minecraft:creeper", "mod:zombie", "minecraft:ender_dragon"}) {
            live.kind = kind;
            rejected("target_not_allowed", () -> GuardedAction.validate(attack(), live.state()));
        }
        live.kind = "minecraft:zombie"; live.allowed = false;
        rejected("target_not_allowed", () -> GuardedAction.validate(attack(), live.state()));
        live.allowed = true;
        for (double distance : new double[]{-1, 2.750001, 3, Double.NaN, Double.POSITIVE_INFINITY}) {
            live.range = distance;
            rejected("target_out_of_range", () -> GuardedAction.validate(attack(), live.state()));
        }
        live.range = 2.75; GuardedAction.validate(attack(), live.state()); checks++;
        live.reach = 2.5;
        rejected("target_out_of_range", () -> GuardedAction.validate(attack(), live.state()));
        for (double reach : new double[]{0, -1, Double.NaN, Double.POSITIVE_INFINITY}) {
            live.reach = reach;
            rejected("target_out_of_range", () -> GuardedAction.validate(attack(), live.state()));
        }
        live.reach = 20; live.range = 2.76; // A reach mod still cannot expand this endpoint.
        rejected("target_out_of_range", () -> GuardedAction.validate(attack(), live.state()));
        live.reach = 3; live.range = 2; live.visible = false;
        rejected("target_not_visible", () -> GuardedAction.validate(attack(), live.state()));
        live.visible = true;
        rejected("look_step_too_large", () -> GuardedAction.validate(look(30.001, 0, TARGET), live.state()));
        rejected("look_step_too_large", () -> GuardedAction.validate(look(0, 20.001, TARGET), live.state()));
        live.yaw = 179;
        GuardedAction.validate(look(-179, 0, TARGET), live.state()); checks++;
        live.yaw = Double.NaN;
        rejected("invalid_live_angles", () -> GuardedAction.validate(look(0, 0, TARGET), live.state()));
    }
    private static void weaponBounds() {
        for (String kind : GuardedAction.WEAPON_TYPES) {
            check(GuardedAction.weaponAllowed(kind, false, false), "Plain vanilla axe accepted");
            check(!GuardedAction.weaponAllowed(kind, true, false), "Enchanted axe rejected");
            check(!GuardedAction.weaponAllowed(kind, false, true), "Sweep-capable axe rejected");
        }
        for (String kind : new String[]{null, "minecraft:air", "minecraft:diamond_sword", "mod:axe", "minecraft:trident"})
            check(!GuardedAction.weaponAllowed(kind, false, false), "Unsupported weapon rejected");
    }
    private static final class Queue implements Executor {
        Runnable task;
        public void execute(Runnable command) {
            if (task != null) throw new AssertionError("More than one queued callback");
            task = command;
        }
        void drain() { Runnable current = task; task = null; current.run(); }
    }
    private static void queuedTimeoutAndGate() throws Exception {
        AtomicLong clock = new AtomicLong(); AtomicInteger mutations = new AtomicInteger();
        GuardedDispatch dispatch = new GuardedDispatch(clock::get); Queue queue = new Queue();
        var ticket = dispatch.submit(queue, 0, 250, active -> { active.checkLive(); return mutations.incrementAndGet(); });
        check(dispatch.busy(), "Gate acquired before queue");
        rejected("guarded_action_busy", () -> dispatch.submit(queue, 0, 250, ignored -> 0));
        clock.set(250_000_000);
        try { ticket.await(); throw new AssertionError("Expected timeout"); }
        catch (TimeoutException expected) { checks++; }
        check(dispatch.busy(), "Timeout does not release gate");
        rejected("guarded_action_busy", () -> dispatch.submit(queue, clock.get(), 250, ignored -> 0));
        queue.drain();
        check(mutations.get() == 0 && !dispatch.busy(), "Cancelled queue drains without mutation");
        var next = dispatch.submit(queue, clock.get(), 250, active -> { active.checkLive(); return mutations.incrementAndGet(); });
        queue.drain();
        check(Integer.valueOf(1).equals(next.await()) && !dispatch.busy(), "New action admitted after drain");
    }
    private static void deadlineAtExecution() throws Exception {
        AtomicLong clock = new AtomicLong(); AtomicInteger mutations = new AtomicInteger();
        GuardedDispatch dispatch = new GuardedDispatch(clock::get); Queue queue = new Queue();
        var expired = dispatch.submit(queue, 0, 1, active -> mutations.incrementAndGet());
        clock.set(1_000_000); queue.drain();
        executionRejected("guarded_action_expired", expired);
        check(mutations.get() == 0, "Deadline checked before starting callback");
        var slowValidation = dispatch.submit(queue, clock.get(), 1, active -> {
            clock.addAndGet(1_000_000); active.checkLive(); return mutations.incrementAndGet();
        });
        queue.drain(); executionRejected("guarded_action_expired", slowValidation);
        check(mutations.get() == 0, "Deadline checked again after validation");
        var stopped = dispatch.submit(queue, clock.get(), 250, active -> mutations.incrementAndGet());
        dispatch.cancelOutstanding(); check(dispatch.busy(), "Stop retains queued gate");
        queue.drain(); executionRejected("guarded_action_expired", stopped);
        check(mutations.get() == 0, "Stop prevents queued mutation");
        // System.nanoTime subtraction stays correct across signed long wraparound.
        clock.set(Long.MIN_VALUE + 50);
        var wrap = dispatch.submit(Runnable::run, Long.MAX_VALUE - 50, 1, active -> 7);
        check(Integer.valueOf(7).equals(wrap.await()), "Monotonic wraparound arithmetic");
    }
    private static void executionRejected(String code, GuardedDispatch.Ticket<?> ticket) throws Exception {
        try { ticket.await(); throw new AssertionError("Expected " + code); }
        catch (ExecutionException expected) {
            check(expected.getCause() instanceof GuardedAction.Rejected
                    && code.equals(expected.getCause().getMessage()), code);
        }
    }
    private static void exceptionsAndInterruption() throws Exception {
        AtomicLong clock = new AtomicLong(); GuardedDispatch dispatch = new GuardedDispatch(clock::get);
        try { dispatch.submit(task -> { throw new RejectedExecutionException(); }, 0, 250, ignored -> 0);
            throw new AssertionError("Executor accepted"); }
        catch (RejectedExecutionException expected) { check(!dispatch.busy(), "Rejected executor releases gate"); }
        var failed = dispatch.submit(Runnable::run, 0, 250, ignored -> { throw new IllegalStateException("test"); });
        try { failed.await(); throw new AssertionError("Expected failure"); }
        catch (ExecutionException expected) { check(!dispatch.busy(), "Callback failure releases gate"); }
        Queue queue = new Queue(); AtomicInteger mutations = new AtomicInteger();
        var interrupted = dispatch.submit(queue, 0, 250, ignored -> mutations.incrementAndGet());
        Thread.currentThread().interrupt();
        try { interrupted.await(); throw new AssertionError("Expected interruption"); }
        catch (InterruptedException expected) { checks++; }
        finally { Thread.interrupted(); }
        check(dispatch.busy(), "Interrupted HTTP worker does not release queued gate");
        queue.drain(); executionRejected("guarded_action_expired", interrupted);
        check(mutations.get() == 0, "Interrupted worker cancels queued mutation");
    }
    private static void runningMutationCannotOutliveTimeoutResponse() throws Exception {
        GuardedDispatch dispatch = new GuardedDispatch(System::nanoTime);
        CountDownLatch started = new CountDownLatch(1), finish = new CountDownLatch(1), responded = new CountDownLatch(1);
        AtomicInteger mutations = new AtomicInteger(); AtomicReference<Object> response = new AtomicReference<>();
        var ticket = dispatch.submit(task -> new Thread(task, "guard-test-game").start(), System.nanoTime(), 100, active -> {
            active.checkLive(); started.countDown();
            if (!finish.await(3, TimeUnit.SECONDS)) throw new AssertionError("Test release missing");
            return mutations.incrementAndGet();
        });
        check(started.await(1, TimeUnit.SECONDS), "Mutation callback started");
        Thread http = new Thread(() -> {
            try { response.set(ticket.await()); } catch (Exception failure) { response.set(failure); }
            responded.countDown();
        }, "guard-test-http");
        http.start();
        try {
            check(!responded.await(200, TimeUnit.MILLISECONDS), "No timeout response while synchronous mutation runs");
            check(dispatch.busy(), "Gate held during mutation");
        } finally { finish.countDown(); }
        check(responded.await(1, TimeUnit.SECONDS), "Response follows completed mutation");
        http.join(1000);
        check(Integer.valueOf(1).equals(response.get()) && mutations.get() == 1,
                "Completed action reported instead of false timeout");
    }
    private static void lifecycleAdmission() throws Exception {
        AtomicLong clock = new AtomicLong(); AtomicInteger mutations = new AtomicInteger();
        GuardedDispatch dispatch = new GuardedDispatch(clock::get, false); Queue queue = new Queue();
        long beforeStart = dispatch.epoch();
        rejected("bridge_lifecycle_changed", () -> dispatch.submit(queue, 0, 250, beforeStart, ignored -> 1));
        dispatch.openAdmission();
        rejected("bridge_lifecycle_changed", () -> dispatch.submit(queue, 0, 250, beforeStart, ignored -> 1));
        long parsedBeforeStop = dispatch.epoch();
        var queued = dispatch.submit(queue, 0, 250, parsedBeforeStop, active -> mutations.incrementAndGet());
        dispatch.closeAdmission();
        rejected("bridge_lifecycle_changed", () -> dispatch.submit(queue, 0, 250, parsedBeforeStop, ignored -> 1));
        dispatch.openAdmission();
        rejected("bridge_lifecycle_changed", () -> dispatch.submit(queue, 0, 250, parsedBeforeStop, ignored -> 1));
        check(dispatch.busy(), "Restart does not forget an old queued callback");
        queue.drain(); executionRejected("guarded_action_expired", queued);
        check(mutations.get() == 0 && !dispatch.busy(), "Restarted queue drains without mutation");
        var current = dispatch.submit(queue, 0, 250, dispatch.epoch(), active -> mutations.incrementAndGet());
        queue.drain(); check(Integer.valueOf(1).equals(current.await()), "New lifecycle admits only its own handler");
    }
    private static void sourceContract() throws Exception {
        Path project = Path.of(System.getProperty("mineclientBridge.projectDir", "."));
        Path source = project.resolve("src/main/java/io/github/campione01/mineclientbridge");
        String bridge = Files.readString(source.resolve("BridgeServer.java"));
        String game = Files.readString(source.resolve("GuardedGameActions.java"));
        check(bridge.contains("requireControlAccess(exchange, \"/control/guarded-action\", \"POST\")"), "Authenticated exact endpoint");
        check(bridge.contains("body.keySet().equals(fields)"), "Reject unknown and missing fields");
        check(bridge.contains("GUARDED_ACTIONS.closeAdmission()"), "Stop atomically closes admission and cancels work");
        check(bridge.contains("final long bridgeEpoch = GUARDED_ACTIONS.epoch()")
                && bridge.contains("request.ttlMs(), bridgeEpoch"), "Handlers retain their pre-parse bridge epoch");
        check(bridge.contains("exchange.getHttpContext().getServer() != server"),
                "Old accepted exchanges cannot inherit a restarted server's epoch");
        check(game.contains("mc.isSameThread()"), "Explicit game-thread assertion");
        check(game.contains("Boolean.getBoolean(\"mineclientBridge.guardedActions\")"), "Default disabled");
        check(game.contains("!mc.getSingleplayerServer().isPublished()"), "No LAN or multiplayer");
        check(game.contains("mc.gameRenderer.pick(1.0F)"), "Fresh crosshair before guard");
        check(game.indexOf("GuardedAction.validate(request, live)") < game.lastIndexOf("ticket.checkLive()")
                && game.lastIndexOf("ticket.checkLive()") < game.indexOf("mc.startAttack()"), "Final deadline before synchronous attack");
        check(!game.contains("KeyMapping") && !game.contains("sendCommand") && !game.contains("setBlock")
                && !game.contains("gameMode.attack("), "No queued keys, commands, world edits, or custom attack path");
        String at = Files.readString(project.resolve("src/main/resources/META-INF/accesstransformer.cfg"));
        check(at.contains("public net.minecraft.client.Minecraft startAttack()Z"), "Only ordinary attack access");
    }
}
