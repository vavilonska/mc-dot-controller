package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

class GuardedTurningTest {
    private static final String WORLD = UUID.randomUUID().toString(), PLAYER = UUID.randomUUID().toString();
    private final AtomicLong clock = new AtomicLong();
    private final GuardedMovement core = new GuardedMovement(clock::get);
    private final List<Runnable> queue = new ArrayList<>();
    GuardedTurningTest() { core.openAdmission(); }
    private GuardedMovement.State state(double yaw) {
        return new GuardedMovement.State(WORLD,PLAYER,100,.5,64,.5,yaw,true,true,true,true,true);
    }
    private GuardedMovement.Request request(double yaw) {
        String observation = core.observe(state(yaw));
        return new GuardedMovement.Request(core.session(),UUID.randomUUID().toString(),
                observation == null ? UUID.randomUUID().toString() : observation,WORLD,PLAYER,100,.5,64,.5,yaw,100,100);
    }
    private GuardedMovement.Ticket submit(double target, AtomicReference<Double> angle) {
        return core.submitTurn(request(0), clock.get(),core.session(),target,queue::add,()->state(0),angle::set);
    }
    private void reject(String reason,Runnable call) { assertEquals(reason,assertThrows(GuardedAction.Rejected.class,call::run).getMessage()); }

    @Test void oneBoundedYawDispatchNoMovementSampleOrHeldInput() throws Exception {
        var angle = new AtomicReference<Double>(0.0);var ticket=submit(30,angle);
        assertEquals("yaw",core.status().ownerAction());assertFalse(core.status().sampled());
        assertFalse(ticket.result.isDone());core.sample(()->state(0),()->fail("turn became forward input"),()->{});
        queue.get(0).run();var outcome=ticket.await();
        assertEquals(30.0,angle.get());assertTrue(outcome.turned());assertFalse(outcome.sampled());
        assertTrue(outcome.released());assertEquals("turn_dispatched",outcome.reason());assertNull(core.status().ownerRequestId());
        angle.set(40.0);queue.get(0).run();assertEquals(40.0,angle.get());
    }
    @Test void canonicalAngleAndShortestStepBounds() throws Exception {
        for(double yaw:new double[]{Double.NaN,Double.POSITIVE_INFINITY,-180.01,180})
            reject("invalid_target_yaw",()->core.submitTurn(request(0),clock.get(),core.session(),yaw,queue::add,()->state(0),v->{}));
        for(double yaw:new double[]{-30.001,30.001,179})
            reject("turn_step_too_large",()->core.submitTurn(request(0),clock.get(),core.session(),yaw,queue::add,()->state(0),v->{}));
        var seen=new AtomicReference<Double>();var ticket=core.submitTurn(request(179),clock.get(),core.session(),-179,queue::add,()->state(179),seen::set);
        queue.remove(0).run();assertTrue(ticket.await().turned());assertEquals(-179.0,seen.get());
    }
    @Test void exactAppliedFloatCannotExceedStepAndWrapsCanonicalDomain() throws Exception {
        double observed = 98.00029754638672, target = 128.00029754638672;
        reject("turn_step_too_large", () -> core.submitTurn(request(observed), 0, core.session(), target,
                queue::add, () -> state(observed), v -> fail("rounded over-limit turn")));
        var applied = new AtomicReference<Double>();
        var ticket = core.submitTurn(request(179), 0, core.session(), 179.999999,
                queue::add, () -> state(179), applied::set);
        queue.remove(0).run(); assertTrue(ticket.await().turned()); assertEquals(-180.0, applied.get());
    }

    @Test void actualLiveAngleAlsoMustRespectThirtyDegreeBound() throws Exception {
        var ticket=core.submitTurn(request(0),0,core.session(),30,queue::add,()->state(-1),v->fail("31-degree live turn"));
        queue.remove(0).run();assertFalse(ticket.await().turned());assertEquals("turn_step_too_large",ticket.await().reason());
    }
    @Test void turnTtlCannotExceedHundredOrUseDifferentSampleDuration() {
        var observed=core.observe(state(0));var request=new GuardedMovement.Request(core.session(),UUID.randomUUID().toString(),observed,WORLD,PLAYER,100,.5,64,.5,0,101,100);
        reject("invalid_turn_ttl_ms",()->core.submitTurn(request,0,core.session(),1,queue::add,()->state(0),v->{}));
        var shorter=new GuardedMovement.Request(core.session(),UUID.randomUUID().toString(),observed,WORLD,PLAYER,100,.5,64,.5,0,100,99);
        reject("invalid_turn_ttl_ms",()->core.submitTurn(shorter,0,core.session(),1,queue::add,()->state(0),v->{}));
    }
    @Test void expiredQueueAndExpiryDuringValidationCannotTurn() throws Exception {
        var ticket=submit(10,new AtomicReference<>(0.0));clock.set(TimeUnit.MILLISECONDS.toNanos(100));queue.remove(0).run();
        assertFalse(ticket.await().turned());assertEquals("movement_expired",ticket.await().reason());
        var next=core.submitTurn(request(0),clock.get(),core.session(),10,queue::add,()->{clock.addAndGet(TimeUnit.MILLISECONDS.toNanos(100));return state(0);},v->fail("late turn"));
        queue.remove(0).run();assertFalse(next.await().turned());
    }
    @Test void timeoutThenOldQueueCallbackCannotDispatchNewTicket() throws Exception {
        var oldAngle=new AtomicReference<>(0.0);var old=submit(10,oldAngle);clock.set(TimeUnit.MILLISECONDS.toNanos(101));
        assertFalse(old.await().turned());var newAngle=new AtomicReference<>(0.0);var next=submit(20,newAngle);
        queue.get(0).run();assertEquals(0.0,oldAngle.get());assertEquals(0.0,newAngle.get());assertFalse(next.result.isDone());
        queue.get(1).run();assertTrue(next.await().turned());assertEquals(20.0,newAngle.get());
    }
    @Test void movementAndTurningShareSingleFlightAdmission() throws Exception {
        var move=core.submit(request(0),0,core.session());
        reject("movement_busy",()->submit(10,new AtomicReference<>(0.0)));
        core.sample(()->state(0),()->{},()->{});reject("movement_busy",()->submit(10,new AtomicReference<>(0.0)));
        core.finishTick();assertTrue(move.await().sampled());
        var turn=submit(10,new AtomicReference<>(0.0));reject("movement_busy",()->core.submit(request(0),0,core.session()));
        core.sample(()->state(0),()->fail("pending turn became move"),()->{});queue.remove(0).run();assertTrue(turn.await().turned());
    }
    @Test void turnConsumesObservationAndNonceAcrossActionKinds() throws Exception {
        var request=request(0);var ticket=core.submitTurn(request,0,core.session(),10,queue::add,()->state(0),v->{});
        queue.remove(0).run();assertTrue(ticket.await().turned());
        reject("movement_request_replayed",()->core.submit(request,0,core.session()));
        var changedId=new GuardedMovement.Request(request.session(),UUID.randomUUID().toString(),request.observationId(),WORLD,PLAYER,100,.5,64,.5,0,100,100);
        reject("movement_observation_changed",()->core.submit(changedId,0,core.session()));
    }
    @Test void stopRestartCancelsQueuedTurnWithoutLateMutation() throws Exception {
        var angle=new AtomicReference<>(0.0);var ticket=submit(10,angle);core.closeAdmission();
        assertEquals("bridge_lifecycle_changed",ticket.await().reason());core.openAdmission();
        var next=submit(20,angle);queue.get(0).run();assertEquals(0.0,angle.get());assertFalse(next.result.isDone());
        queue.get(1).run();assertTrue(next.await().turned());assertEquals(20.0,angle.get());
    }
    @Test void screenWorldDeathAndExplicitReleaseCancelQueuedTurning() throws Exception {
        for(String reason:new String[]{"screen_transition","world_transition","player_not_ready","inputs_released"}) {
            var ticket=submit(10,new AtomicReference<>(0.0));core.cancelAndRelease(reason);queue.remove(0).run();
            assertFalse(ticket.await().turned());assertEquals(reason,ticket.await().reason());
        }
    }
    @Test void reentrantCancellationDuringValidationStopsTurning() throws Exception {
        var ticket=core.submitTurn(request(0),0,core.session(),10,queue::add,()->{core.cancelAndRelease("screen_transition");return state(0);},v->fail("late turn"));
        queue.remove(0).run();assertFalse(ticket.await().turned());
    }
    @Test void executorRejectionReleasesAdmissionButNeverPermitsReplay() {
        var request=request(0);
        assertThrows(RejectedExecutionException.class,()->core.submitTurn(request,0,core.session(),10,r->{throw new RejectedExecutionException();},()->state(0),v->fail("rejected input")));
        assertNull(core.status().ownerRequestId());reject("movement_request_replayed",()->core.submit(request,0,core.session()));
    }
    @Test void partialTurnFailureIsReportedAsDispatchedAndCannotReplay() throws Exception {
        var angle=new AtomicReference<>(0.0);var ticket=core.submitTurn(request(0),0,core.session(),10,queue::add,()->state(0),v->{angle.set(v);throw new IllegalStateException();});
        queue.remove(0).run();assertEquals(10.0,angle.get());assertTrue(ticket.await().turned());
        assertFalse(ticket.await().sampled());assertTrue(ticket.await().released());assertEquals("turn_failed",ticket.await().reason());
        assertNull(core.status().ownerRequestId());
    }
    @Test void timeoutRacingStartedTurnWaitsAndReturnsActualOutcome() throws Exception {
        var entered=new CountDownLatch(1);var finish=new CountDownLatch(1);var angle=new AtomicReference<>(0.0);
        var ticket=core.submitTurn(request(0),0,core.session(),10,queue::add,()->state(0),v->{entered.countDown();waitFor(finish);angle.set(v);});
        Thread runner=new Thread(queue.remove(0));runner.start();assertTrue(entered.await(2,TimeUnit.SECONDS));
        clock.set(TimeUnit.MILLISECONDS.toNanos(101));var result=new AtomicReference<GuardedMovement.Outcome>();
        Thread waiter=new Thread(()->{try{result.set(ticket.await());}catch(Exception e){throw new RuntimeException(e);}});waiter.start();
        Thread.sleep(20);assertNull(result.get());finish.countDown();runner.join(2000);waiter.join(2000);
        assertFalse(waiter.isAlive());assertEquals(10.0,angle.get());assertTrue(result.get().turned());assertEquals("turn_dispatched",result.get().reason());
    }
    @Test void interruptedWaitCannotLeaveQueuedTurnActive() throws Exception {
        var angle=new AtomicReference<>(0.0);var ticket=submit(10,angle);var interrupted=new AtomicBoolean();
        Thread waiter=new Thread(()->{try{ticket.await();}catch(InterruptedException expected){interrupted.set(true);}catch(Exception e){throw new RuntimeException(e);}});
        waiter.start();waiter.interrupt();waiter.join(2000);assertTrue(interrupted.get());queue.remove(0).run();assertEquals(0.0,angle.get());
        assertFalse(ticket.result.get().turned());assertTrue(ticket.result.get().released());
    }
    @Test void interruptRacingRunningTurnWaitsForItsRealOutcome() throws Exception {
        var entered=new CountDownLatch(1);var finish=new CountDownLatch(1);var interrupted=new AtomicBoolean();
        var ticket=core.submitTurn(request(0),0,core.session(),10,queue::add,()->state(0),v->{entered.countDown();waitFor(finish);});
        Thread runner=new Thread(queue.remove(0));runner.start();assertTrue(entered.await(2,TimeUnit.SECONDS));
        Thread waiter=new Thread(()->{try{ticket.await();}catch(InterruptedException expected){interrupted.set(true);}catch(Exception e){throw new RuntimeException(e);}});
        waiter.start();waiter.interrupt();Thread.sleep(20);assertFalse(interrupted.get());assertFalse(ticket.result.isDone());
        finish.countDown();runner.join(2000);waiter.join(2000);assertFalse(waiter.isAlive());assertTrue(interrupted.get());
        assertTrue(ticket.result.get().turned());assertTrue(ticket.result.get().released());
    }

    @Test void sameWorldPlayerPoseAndFreshnessRulesProtectYaw() throws Exception {
        var states=List.of(new GuardedMovement.State("other",PLAYER,100,.5,64,.5,0,true,true,true,true,true),
                new GuardedMovement.State(WORLD,"other",100,.5,64,.5,0,true,true,true,true,true),
                new GuardedMovement.State(WORLD,PLAYER,102,.5,64,.5,0,true,true,true,true,true),
                new GuardedMovement.State(WORLD,PLAYER,100,.54,64,.5,0,true,true,true,true,true),
                new GuardedMovement.State(WORLD,PLAYER,100,.5,64,.5,2,true,true,true,true,true),
                new GuardedMovement.State(WORLD,PLAYER,100,.5,64,.5,0,false,true,true,true,true),
                new GuardedMovement.State(WORLD,PLAYER,100,.5,64,.5,0,true,false,true,true,true),
                new GuardedMovement.State(WORLD,PLAYER,100,.5,64,.5,0,true,true,false,true,true),
                new GuardedMovement.State(WORLD,PLAYER,100,.5,64,.5,0,true,true,true,false,true));
        for(var state:states){var ticket=core.submitTurn(request(0),clock.get(),core.session(),10,queue::add,()->state,v->fail("unsafe context turn"));queue.remove(0).run();assertFalse(ticket.await().turned());}
    }
    @Test void sourceRouteIsDefaultDisabledPlayerOnlyAndStrictlyBounded() throws Exception {
        Path root=Path.of(System.getProperty("mineclientBridge.projectDir"));
        String turn=Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/GuardedGameTurning.java"));
        String bridge=Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        assertTrue(turn.contains("Boolean.getBoolean(\"mineclientBridge.guardedTurning\")"));
        assertTrue(turn.contains("GuardedGameMovement.LEASES.submitTurn"));assertTrue(turn.contains("GuardedGameMovement.snapshot(mc, mc.player.input, false, enabled())"));
        assertTrue(turn.contains("setYRot"));assertFalse(turn.contains("setXRot"));assertFalse(turn.contains("setDown"));assertFalse(turn.contains("targetUuid"));assertFalse(turn.contains("send("));
        int start=bridge.indexOf("private static void handleGuardedTurn(");int end=bridge.indexOf("private static void handleControlLook(",start);
        String handler=bridge.substring(start,end);assertTrue(handler.contains("requireControlAccess(exchange, \"/control/guarded-turn\", \"POST\")"));
        assertTrue(handler.contains("body.keySet().equals"));assertTrue(handler.contains("turnTicket.result.getNow(null)"));assertTrue(handler.contains("\"turn_confirmed\", false"));
        assertFalse(handler.contains("applyLook("));assertFalse(handler.contains("duration_ms"));
    }
    private static void waitFor(CountDownLatch latch){try{if(!latch.await(2,TimeUnit.SECONDS))throw new AssertionError("latch timeout");}catch(InterruptedException e){throw new AssertionError(e);}}
}
