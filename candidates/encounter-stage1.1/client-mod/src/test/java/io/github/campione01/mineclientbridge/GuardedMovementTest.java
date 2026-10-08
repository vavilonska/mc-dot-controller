package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

class GuardedMovementTest {
    private static final String WORLD = UUID.randomUUID().toString();
    private static final String PLAYER = UUID.randomUUID().toString();
    private final AtomicLong clock = new AtomicLong();
    private final GuardedMovement core = new GuardedMovement(clock::get);
    GuardedMovementTest() { core.openAdmission(); }
    private GuardedMovement.Request request() { return request(UUID.randomUUID().toString()); }
    private GuardedMovement.Request request(String id) {
        return new GuardedMovement.Request(core.session(), id, observation(), WORLD, PLAYER, 100, .5, 64, .5, 0, 250, 100);
    }
    private String observation() { String id = core.observe(state()); return id == null ? UUID.randomUUID().toString() : id; }
    private GuardedMovement.State state() {
        return new GuardedMovement.State(WORLD, PLAYER, 100, .5, 64, .5, 0, true, true, true, true, true);
    }
    private GuardedMovement.Ticket submit() { return core.submit(request(), clock.get(), core.session()); }
    private void reject(String code, Runnable task) {
        assertEquals(code, assertThrows(GuardedAction.Rejected.class, task::run).getMessage());
    }

    @Test void singleSampleAlwaysReleasesBeforeAcknowledgement() throws Exception {
        var ticket = submit(); var held = new AtomicBoolean(); var count = new AtomicInteger();
        core.sample(this::state, () -> { held.set(true); count.incrementAndGet(); }, () -> held.set(false));
        assertTrue(held.get()); assertFalse(ticket.result.isDone()); assertFalse(core.status().released());
        core.sample(this::state, count::incrementAndGet, () -> fail("second cleanup"));
        assertEquals(1, count.get());
        core.finishTick(); var outcome = ticket.await();
        assertFalse(held.get()); assertTrue(outcome.sampled()); assertTrue(outcome.released());
        assertEquals("sample_released", outcome.reason()); assertNull(core.status().ownerRequestId());
        core.finishTick(); assertEquals(1, count.get());
    }

    @Test void pendingTimeoutPreventsEveryLaterSample() throws Exception {
        var ticket = submit(); clock.set(TimeUnit.MILLISECONDS.toNanos(100));
        var result = ticket.await();
        assertFalse(result.sampled()); assertTrue(result.released()); assertEquals("movement_expired", result.reason());
        core.sample(this::state, () -> fail("late input"), () -> fail("never owned"));
        assertNull(core.status().ownerRequestId());
    }

    @Test void expiryAtExecutionAndDuringValidationCannotInject() throws Exception {
        var ticket = submit(); clock.set(TimeUnit.MILLISECONDS.toNanos(100));
        core.sample(this::state, () -> fail("expired injection"), () -> fail("never owned"));
        assertEquals("movement_expired", ticket.await().reason());
        var next = submit();
        core.sample(() -> { clock.addAndGet(TimeUnit.MILLISECONDS.toNanos(100)); return state(); },
                () -> fail("validation consumed lease"), () -> fail("never owned"));
        assertFalse(next.await().sampled());
    }

    @Test void partialMutationExceptionRunsCleanup() throws Exception {
        var held = new AtomicBoolean(); var ticket = submit();
        core.sample(this::state, () -> { held.set(true); throw new IllegalStateException(); }, () -> held.set(false));
        assertFalse(held.get()); var outcome = ticket.await();
        assertTrue(outcome.sampled()); assertTrue(outcome.released()); assertEquals("movement_failed", outcome.reason());
    }

    @Test void cleanupFailureKeepsAdmissionUntilSuccessfulRelease() throws Exception {
        var held = new AtomicBoolean(); var attempts = new AtomicInteger(); var ticket = submit();
        core.sample(this::state, () -> held.set(true), () -> {
            if (attempts.incrementAndGet() == 1) throw new IllegalStateException(); held.set(false);
        });
        core.finishTick(); assertTrue(held.get()); assertFalse(ticket.result.isDone());
        reject("movement_busy", this::submit);
        core.finishTick(); assertFalse(held.get()); assertTrue(ticket.await().released());
        assertEquals("movement_cleanup_failed", ticket.await().reason()); submit();
    }

    @Test void requestNonceNeverReplayedEvenAfterFailure() throws Exception {
        var request = request(); var ticket = core.submit(request, 0, core.session());
        ticket.cancel("cancelled"); assertFalse(ticket.await().sampled());
        reject("movement_request_replayed", () -> core.submit(request, 0, core.session()));
        var expired = request(); clock.set(TimeUnit.MILLISECONDS.toNanos(101));
        reject("movement_expired", () -> core.submit(expired, 0, core.session()));
        reject("movement_request_replayed", () -> core.submit(expired, clock.get(), core.session()));
    }

    @Test void sessionBudgetDoesNotEvictReplayProtection() {
        var bounded = new GuardedMovement(clock::get, 1); bounded.openAdmission();
        var first = new GuardedMovement.Request(bounded.session(), UUID.randomUUID().toString(), bounded.observe(state()), WORLD, PLAYER,
                100, .5, 64, .5, 0, 100, 100);
        bounded.submit(first, 0, bounded.session()).cancel("done");
        var second = new GuardedMovement.Request(bounded.session(), UUID.randomUUID().toString(), bounded.observe(state()), WORLD, PLAYER,
                100, .5, 64, .5, 0, 100, 100);
        reject("movement_session_budget_exhausted", () -> bounded.submit(second, 0, bounded.session()));
        reject("movement_request_replayed", () -> bounded.submit(first, 0, bounded.session()));
    }

    @Test void stopAndRestartInvalidateBodyParsingAndOldRequests() throws Exception {
        String oldSession = core.session(); var oldRequest = request(); var queued = submit();
        core.closeAdmission(); assertEquals("bridge_lifecycle_changed", queued.await().reason());
        reject("movement_session_changed", this::submit); core.openAdmission();
        reject("movement_session_changed", () -> core.submit(oldRequest, 0, oldSession));
        reject("movement_session_changed", () -> core.submit(request(), 0, oldSession));
        reject("movement_session_changed", () -> core.submit(oldRequest, 0, core.session()));
        core.sample(this::state, () -> fail("no inherited callback"), () -> {});
    }

    @Test void stopDoesNotForgetSampledLeaseAndBlocksRestartUntilRelease() throws Exception {
        var ticket = submit(); var held = new AtomicBoolean();
        core.sample(this::state, () -> held.set(true), () -> held.set(false)); core.closeAdmission();
        reject("movement_cleanup_pending", core::openAdmission); assertFalse(ticket.result.isDone());
        core.finishTick(); assertFalse(held.get()); assertEquals("bridge_lifecycle_changed", ticket.await().reason());
        core.openAdmission(); assertTrue(core.status().admissionOpen());
    }

    @Test void reentrantWorldScreenDeathAndReleaseCancellationStopsBeforeApply() throws Exception {
        for (String reason : new String[]{"world_transition", "screen_transition", "player_not_ready", "inputs_released"}) {
            var ticket = submit();
            core.sample(() -> { core.cancelAndRelease(reason); return state(); },
                    () -> fail("cancelled during state validation"), () -> fail("never owned"));
            assertEquals(reason, ticket.await().reason()); assertFalse(ticket.await().sampled());
        }
    }

    @Test void cancellationAfterSampleReleasesOnlyItsOwnLease() throws Exception {
        var ticket = submit(); var held = new AtomicBoolean();
        core.sample(this::state, () -> held.set(true), () -> held.set(false));
        ticket.cancel("screen_transition"); assertTrue(held.get()); assertFalse(ticket.result.isDone());
        core.cancelAndRelease("screen_transition"); assertFalse(held.get()); assertTrue(ticket.await().released());
        var next = submit(); ticket.cancel("late_old_cancel"); assertFalse(next.result.isDone());
        core.cancelAndRelease("finish");
    }

    @Test void timeoutRacingMutationWaitsForReleaseAndNeverAddsInput() throws Exception {
        var ticket = submit(); var inside = new CountDownLatch(1); var unblock = new CountDownLatch(1);
        var held = new AtomicBoolean(); var count = new AtomicInteger();
        Thread sampler = new Thread(() -> core.sample(this::state, () -> {
            held.set(true); count.incrementAndGet(); inside.countDown(); waitFor(unblock);
        }, () -> held.set(false)));
        sampler.start(); assertTrue(inside.await(2, TimeUnit.SECONDS));
        clock.set(TimeUnit.MILLISECONDS.toNanos(101)); var result = new AtomicReference<GuardedMovement.Outcome>();
        Thread waiter = new Thread(() -> { try { result.set(ticket.await()); } catch (Exception e) { throw new RuntimeException(e); } });
        waiter.start(); Thread.sleep(20); assertNull(result.get()); unblock.countDown(); sampler.join(2000);
        Thread.sleep(20); assertNull(result.get()); assertTrue(held.get());
        core.finishTick(); waiter.join(2000); assertFalse(waiter.isAlive()); assertFalse(held.get());
        assertTrue(result.get().released()); assertEquals(1, count.get());
        core.sample(this::state, () -> fail("late replay"), () -> {});
    }

    @Test void interruptedHttpWorkerCancelsPendingAndWaitsForOwnedCleanup() throws Exception {
        var ticket = submit(); var interrupted = new AtomicBoolean(); var waiting = new CountDownLatch(1);
        Thread thread = new Thread(() -> {
            waiting.countDown(); try { ticket.await(); } catch (InterruptedException expected) { interrupted.set(true); }
            catch (Exception failure) { throw new RuntimeException(failure); }
        });
        thread.start(); waiting.await(); thread.interrupt(); thread.join(2000);
        assertTrue(interrupted.get()); core.sample(this::state, () -> fail("late interrupted input"), () -> {});
        var owned = submit(); var held = new AtomicBoolean(); core.sample(this::state, () -> held.set(true), () -> held.set(false));
        interrupted.set(false);
        Thread ownedWaiter = new Thread(() -> { try { owned.await(); } catch (InterruptedException expected) { interrupted.set(true); }
            catch (Exception failure) { throw new RuntimeException(failure); } });
        ownedWaiter.start(); ownedWaiter.interrupt(); Thread.sleep(20); assertFalse(interrupted.get());
        core.finishTick(); ownedWaiter.join(2000); assertTrue(interrupted.get()); assertFalse(held.get());
    }

    @Test void identityContextAndFreshPoseFailClosed() {
        var r = request(); var s = state(); GuardedMovement.validate(r, s);
        reject("world_generation_changed", () -> GuardedMovement.validate(r, new GuardedMovement.State("other", PLAYER, 100, .5,64,.5,0,true,true,true,true,true)));
        reject("player_changed", () -> GuardedMovement.validate(r, new GuardedMovement.State(WORLD, "other",100,.5,64,.5,0,true,true,true,true,true)));
        for (long tick : new long[]{99,102,Long.MAX_VALUE}) reject("movement_state_stale", () -> GuardedMovement.validate(r,
                new GuardedMovement.State(WORLD,PLAYER,tick,.5,64,.5,0,true,true,true,true,true)));
        GuardedMovement.validate(r,new GuardedMovement.State(WORLD,PLAYER,101,.5,64,.5,0,true,true,true,true,true));
        for (double x : new double[]{.531, Double.NaN, Double.POSITIVE_INFINITY}) reject("movement_position_changed", () -> GuardedMovement.validate(r,
                new GuardedMovement.State(WORLD,PLAYER,100,x,64,.5,0,true,true,true,true,true)));
        reject("movement_yaw_changed", () -> GuardedMovement.validate(r,new GuardedMovement.State(WORLD,PLAYER,100,.5,64,.5,1.01,true,true,true,true,true)));
        for (int field=0;field<5;field++) {
            String[] reasons={"guarded_movement_disabled","local_survival_required","player_not_ready","movement_input_not_neutral","movement_corridor_unsafe"};
            final int f=field; reject(reasons[field], () -> GuardedMovement.validate(r,
                    new GuardedMovement.State(WORLD,PLAYER,100,.5,64,.5,0,f!=0,f!=1,f!=2,f!=3,f!=4)));
        }
    }

    @Test void wireValueBoundsAndMonotonicWraparound() throws Exception {
        for (int duration : new int[]{0,-1,101,Integer.MAX_VALUE}) reject("invalid_duration_ms", () -> new GuardedMovement.Request(core.session(),UUID.randomUUID().toString(),UUID.randomUUID().toString(),WORLD,PLAYER,100,.5,64,.5,0,250,duration));
        for (int ttl : new int[]{0,-1,251}) reject("invalid_ttl_ms", () -> new GuardedMovement.Request(core.session(),UUID.randomUUID().toString(),UUID.randomUUID().toString(),WORLD,PLAYER,100,.5,64,.5,0,ttl,1));
        reject("invalid_duration_ms", () -> new GuardedMovement.Request(core.session(),UUID.randomUUID().toString(),UUID.randomUUID().toString(),WORLD,PLAYER,100,.5,64,.5,0,99,100));
        reject("invalid_identity", () -> request("not-a-uuid"));
        reject("invalid_position", () -> new GuardedMovement.Request(core.session(),UUID.randomUUID().toString(),UUID.randomUUID().toString(),WORLD,PLAYER,100,Double.NaN,64,.5,0,100,100));
        clock.set(Long.MAX_VALUE - 1000); var ticket=submit(); clock.addAndGet(2000);
        core.sample(this::state,()->{},()->{}); core.finishTick(); assertTrue(ticket.await().sampled());
        var future = request(); reject("movement_expired", () -> core.submit(future, clock.get()+1, core.session()));
    }

    @Test void observationIsOneUseAndNewerReadInvalidatesOldSnapshot() throws Exception {
        var old = request(); var current = request();
        reject("movement_observation_changed", () -> core.submit(old, 0, core.session()));
        core.submit(current, 0, core.session()).cancel("done");
        var alternate = new GuardedMovement.Request(current.session(), UUID.randomUUID().toString(), current.observationId(),
                WORLD, PLAYER,100,.5,64,.5,0,100,100);
        reject("movement_observation_changed", () -> core.submit(alternate, 0, core.session()));
    }

    @Test void cancelIsBarrierForObservedButNotYetAdmittedRequests() {
        for (String reason : new String[]{"inputs_released", "screen_transition", "world_transition", "player_not_ready"}) {
            var delayed = request(); core.cancelAndRelease(reason);
            reject("movement_observation_changed", () -> core.submit(delayed, clock.get(), core.session()));
        }
    }

    @Test void delayedHttpHandlerCannotRenewOldObservationEvenWithSameTick() {
        var stale = request(); clock.set(TimeUnit.MILLISECONDS.toNanos(150));
        reject("movement_observation_expired", () -> core.submit(stale, clock.get(), core.session()));
        reject("movement_request_replayed", () -> core.submit(stale, clock.get(), core.session()));
        var changed = request();
        var forged = new GuardedMovement.Request(changed.session(), changed.requestId(), changed.observationId(),
                WORLD, PLAYER,100,.51,64,.5,0,100,100);
        reject("movement_observation_mismatch", () -> core.submit(forged, clock.get(), core.session()));
    }

    @Test void observationMayExpireAfterAdmissionBeforeSample() throws Exception {
        var request = request(); clock.set(TimeUnit.MILLISECONDS.toNanos(120));
        var ticket = core.submit(request, clock.get(), core.session());
        clock.set(TimeUnit.MILLISECONDS.toNanos(150));
        core.sample(this::state, () -> fail("old observation injected"), () -> {});
        assertFalse(ticket.await().sampled()); assertEquals("movement_expired", ticket.await().reason());
    }

    @Test void integrationDefaultOffOneSampleNoKeysAndLifecycleWiring() throws Exception {
        Path root = Path.of(System.getProperty("mineclientBridge.projectDir"));
        String game=Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/GuardedGameMovement.java"));
        String bridge=Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        assertTrue(game.contains("Boolean.getBoolean(\"mineclientBridge.guardedMovement\")"));
        assertTrue(game.contains("MovementInputUpdateEvent.class")); assertTrue(game.contains("ClientTickEvent.Post.class"));
        assertTrue(game.contains("ScreenEvent.Opening.class")); assertTrue(game.contains("ClientPlayerNetworkEvent.LoggingOut.class"));
        assertTrue(game.contains("LivingDeathEvent.class")); assertTrue(game.contains("LevelEvent.Unload.class"));
        assertTrue(game.contains("input.forwardImpulse = 0;")); assertTrue(game.contains("input.up = false;"));
        assertTrue(game.contains("ChunkStatus.FULL, false")); assertTrue(game.contains("!player.isAutoJumpEnabled()"));
        assertTrue(game.contains("player.autoJumpTime == 0")); assertTrue(game.contains("player.getSpeed() <= 0.10000001"));
        assertTrue(game.contains("horizontalDistance() <= 0.001")); assertTrue(game.contains("finalLocal, finalReady, finalNeutral, safe"));
        int refreshedPredicates = game.indexOf("boolean finalLocal");
        assertTrue(refreshedPredicates >= 0 && game.indexOf("player.getX() == x", refreshedPredicates) > refreshedPredicates);
        assertTrue(bridge.contains("movementTicket.result.getNow(null)"));
        assertFalse(game.contains(".setDown(")); assertFalse(game.contains(".keyPress(")); assertFalse(game.contains(".send("));
        assertTrue(bridge.contains("requireControlAccess(exchange, \"/control/guarded-movement\", \"POST\")"));
        assertTrue(bridge.contains("final String entrySession = GuardedGameMovement.LEASES.session();"));
        assertTrue(bridge.contains("GuardedGameMovement.LEASES.closeAdmission();"));
        assertTrue(bridge.contains("GuardedGameMovement.cancelOnGameThread(\"inputs_released\")"));
    }
    @Test void onlyStateIssuesObservationAndStatusBracketingDoesNotInvalidateIt() throws Exception {
        Path root = Path.of(System.getProperty("mineclientBridge.projectDir"));
        String bridge = Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        assertEquals(1, bridge.split("GuardedGameMovement\\.observedStatus\\(mc\\)", -1).length - 1);
        int start = bridge.indexOf("private static JsonObject createControlStatus(");
        String status = bridge.substring(start, bridge.indexOf("\n    private static ", start + 1));
        assertTrue(status.contains("GuardedGameMovement.status()")); assertFalse(status.contains("observedStatus"));
        var request = request(); core.status(); core.status();
        var ticket = core.submit(request, clock.get(), core.session());
        core.sample(this::state, () -> {}, () -> {}); core.finishTick(); assertTrue(ticket.await().sampled());
    }

    private static void waitFor(CountDownLatch latch) {
        try { if (!latch.await(2, TimeUnit.SECONDS)) throw new AssertionError("latch timeout"); }
        catch (InterruptedException failure) { throw new AssertionError(failure); }
    }
}
