package io.github.campione01.mineclientbridge;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.LongSupplier;

/** One callback in flight. Cancellation and mutation share a monitor. */
final class GuardedDispatch {
    @FunctionalInterface
    interface Operation<T> { T run(Ticket<T> ticket) throws Exception; }

    private final AtomicReference<Ticket<?>> active = new AtomicReference<>();
    private final Object admission = new Object();
    private final LongSupplier clock;
    private volatile long epoch;
    private volatile boolean open;

    GuardedDispatch(LongSupplier clock) { this(clock, true); }
    GuardedDispatch(LongSupplier clock, boolean initiallyOpen) { this.clock = clock; open = initiallyOpen; }

    long epoch() { return epoch; }

    void openAdmission() {
        synchronized (admission) { epoch++; open = true; }
    }

    void closeAdmission() {
        final Ticket<?> ticket;
        synchronized (admission) {
            open = false;
            epoch++;
            ticket = active.get();
        }
        // Never take the ticket monitor while holding admission: an executing
        // action may need to inspect lifecycle state before its final mutation.
        if (ticket != null) ticket.cancel();
    }

    <T> Ticket<T> submit(Executor executor, long receivedNanos, int ttlMs, Operation<T> operation) {
        return submit(executor, receivedNanos, ttlMs, epoch(), operation);
    }

    <T> Ticket<T> submit(Executor executor, long receivedNanos, int ttlMs,
                         long expectedEpoch, Operation<T> operation) {
        GuardedAction.require(ttlMs >= 1 && ttlMs <= GuardedAction.MAX_TTL_MS, "invalid_ttl_ms");
        Ticket<T> ticket = new Ticket<>(receivedNanos, TimeUnit.MILLISECONDS.toNanos(ttlMs), expectedEpoch);
        synchronized (admission) {
            GuardedAction.require(open && epoch == expectedEpoch, "bridge_lifecycle_changed");
            GuardedAction.require(active.compareAndSet(null, ticket), "guarded_action_busy");
        }
        try {
            executor.execute(() -> {
                try {
                    synchronized (ticket) {
                        try {
                            ticket.checkLive();
                            ticket.result.complete(operation.run(ticket));
                        } catch (Throwable error) {
                            ticket.result.completeExceptionally(error);
                        }
                    }
                } finally {
                    // An expired queued task must drain before another is admitted.
                    active.compareAndSet(ticket, null);
                }
            });
        } catch (RuntimeException error) {
            ticket.cancel();
            active.compareAndSet(ticket, null); // Executor did not admit a callback.
            throw error;
        }
        return ticket;
    }

    void cancelOutstanding() {
        Ticket<?> ticket = active.get();
        if (ticket != null) ticket.cancel();
    }

    boolean busy() { return active.get() != null; }

    final class Ticket<T> {
        private final long receivedNanos;
        private final long ttlNanos;
        private final long admittedEpoch;
        private final CompletableFuture<T> result = new CompletableFuture<>();
        private boolean cancelled;

        private Ticket(long receivedNanos, long ttlNanos, long admittedEpoch) {
            this.receivedNanos = receivedNanos;
            this.ttlNanos = ttlNanos;
            this.admittedEpoch = admittedEpoch;
        }

        // Called while holding this ticket's monitor immediately before mutation.
        synchronized void checkLive() {
            GuardedAction.require(!cancelled && clock.getAsLong() - receivedNanos < ttlNanos,
                    "guarded_action_expired");
            GuardedAction.require(open && epoch == admittedEpoch, "bridge_lifecycle_changed");
        }

        synchronized void cancel() { cancelled = true; }

        T await() throws InterruptedException, ExecutionException, TimeoutException {
            try {
                long remaining = ttlNanos - (clock.getAsLong() - receivedNanos);
                if (remaining <= 0) throw new TimeoutException();
                return result.get(remaining, TimeUnit.NANOSECONDS);
            } catch (TimeoutException timeout) {
                synchronized (this) {
                    // If execution began first, wait for its entire synchronous
                    // operation before answering. Never report timeout while it runs.
                    if (result.isDone()) return result.get();
                    cancelled = true;
                }
                throw timeout;
            } catch (InterruptedException interrupted) {
                cancel(); // Also waits for any already-running mutation to finish.
                throw interrupted;
            }
        }
    }
}
