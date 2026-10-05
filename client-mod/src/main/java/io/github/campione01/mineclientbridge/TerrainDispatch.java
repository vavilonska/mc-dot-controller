package io.github.campione01.mineclientbridge;

import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;

/** Keeps one terrain admission until the game-thread task exits, even after an HTTP timeout. */
final class TerrainDispatch {
    private final AtomicBoolean busy = new AtomicBoolean();

    <T> T call(Executor gameThread, Callable<T> operation, long timeout, TimeUnit unit)
            throws InterruptedException, ExecutionException, TimeoutException {
        if (!busy.compareAndSet(false, true)) throw new TerrainScan.Failure(429, "terrain_busy");
        CompletableFuture<T> result = new CompletableFuture<>();
        try {
            gameThread.execute(() -> {
                try {
                    if (!result.isDone()) result.complete(operation.call());
                } catch (Throwable failure) {
                    result.completeExceptionally(failure);
                } finally {
                    busy.set(false);
                }
            });
        } catch (RuntimeException rejected) {
            busy.set(false);
            throw rejected;
        }
        try {
            return result.get(timeout, unit);
        } catch (TimeoutException | InterruptedException cancelled) {
            // Cancellation suppresses queued work, but cannot interrupt a running Minecraft callback.
            // Its admission remains held until that callback (or skipped queued task) actually exits.
            result.cancel(false);
            throw cancelled;
        }
    }
}
