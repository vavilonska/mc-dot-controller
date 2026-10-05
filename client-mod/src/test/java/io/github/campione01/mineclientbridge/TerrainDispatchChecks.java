package io.github.campione01.mineclientbridge;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

public final class TerrainDispatchChecks {
    private static int checks;
    public static void main(String[] args) throws Exception { run(); }
    static void run() throws Exception {
        checks = 0;
        TerrainDispatch dispatch = new TerrainDispatch();
        Runnable[] queued = new Runnable[1];
        AtomicInteger reads = new AtomicInteger();
        try {
            dispatch.call(task -> queued[0] = task, () -> reads.incrementAndGet(), 1, TimeUnit.MILLISECONDS);
            throw new AssertionError("Expected queued timeout");
        } catch (TimeoutException expected) { checks++; }
        expectBusy(dispatch);
        queued[0].run();
        check(reads.get() == 0, "Timed-out queued read is skipped");
        check(dispatch.call(Runnable::run, () -> 7, 1, TimeUnit.SECONDS) == 7, "Admission released after skip");
        try {
            dispatch.call(task -> { throw new RejectedExecutionException(); }, () -> 1, 1, TimeUnit.SECONDS);
            throw new AssertionError("Expected rejection");
        } catch (RejectedExecutionException expected) { checks++; }
        check(dispatch.call(Runnable::run, () -> 8, 1, TimeUnit.SECONDS) == 8, "Rejection releases admission");
        CountDownLatch release = new CountDownLatch(1), finished = new CountDownLatch(1);
        ExecutorService game = Executors.newSingleThreadExecutor();
        try {
            try {
                dispatch.call(game, () -> { release.await(); return 9; }, 50, TimeUnit.MILLISECONDS);
                throw new AssertionError("Expected running timeout");
            } catch (TimeoutException expected) { checks++; }
            expectBusy(dispatch);
            release.countDown();
            game.execute(finished::countDown);
            check(finished.await(2, TimeUnit.SECONDS), "Game thread finished callback");
            check(dispatch.call(Runnable::run, () -> 10, 1, TimeUnit.SECONDS) == 10, "Admission released after running callback exits");
        } finally {
            release.countDown();
            game.shutdownNow();
        }
        try {
            Thread.currentThread().interrupt();
            dispatch.call(task -> queued[0] = task, () -> reads.incrementAndGet(), 1, TimeUnit.SECONDS);
            throw new AssertionError("Expected interruption");
        } catch (InterruptedException expected) { checks++; }
        finally { Thread.interrupted(); }
        expectBusy(dispatch);
        queued[0].run();
        check(reads.get() == 0, "Interrupted queued read is skipped");
        System.out.println("Terrain dispatch: " + checks + " checks passed");
    }
    private static void expectBusy(TerrainDispatch dispatch) throws Exception {
        try {
            dispatch.call(Runnable::run, () -> 1, 1, TimeUnit.SECONDS);
            throw new AssertionError("Expected busy");
        } catch (TerrainScan.Failure expected) { check(expected.status == 429, "Single queued/running admission"); }
    }
    private static void check(boolean success, String message) { checks++; if (!success) throw new AssertionError(message); }
}
