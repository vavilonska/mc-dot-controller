package io.github.campione01.mineclientbridge;

import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/** Single-use, one-input-sample lease. Never owns a physical or mapped key. */
final class GuardedMovement {
    static final int SCHEMA = 1;
    static final int MAX_DURATION_MS = 100;
    static final int MAX_TTL_MS = 250;
    static final int MAX_REQUESTS = 4096;
    static final int MAX_OBSERVATION_AGE_MS = 150;
    static final double POSITION_TOLERANCE = 0.03;
    static final double YAW_TOLERANCE = 1.0;
    static final float FORWARD_IMPULSE = 0.5F; // Below vanilla's double-tap sprint threshold.

    record Request(String session, String requestId, String observationId, String worldGeneration, String playerUuid,
                   long expectedTick, double x, double y, double z, double yaw, int ttlMs, int durationMs) {
        Request {
            require(uuid(session) && uuid(requestId) && uuid(observationId) && uuid(worldGeneration) && uuid(playerUuid), "invalid_identity");
            require(expectedTick >= 0, "invalid_expected_tick");
            require(Double.isFinite(x) && Double.isFinite(y) && Double.isFinite(z)
                    && Math.abs(x) <= 30_000_000 && Math.abs(z) <= 30_000_000 && Math.abs(y) <= 30_000_000,
                    "invalid_position");
            require(Double.isFinite(yaw) && yaw >= -180 && yaw < 180, "invalid_yaw");
            require(ttlMs >= 1 && ttlMs <= MAX_TTL_MS, "invalid_ttl_ms");
            require(durationMs >= 1 && durationMs <= MAX_DURATION_MS && durationMs <= ttlMs, "invalid_duration_ms");
        }
    }

    record State(String worldGeneration, String playerUuid, long tick, double x, double y, double z,
                 double yaw, boolean enabled, boolean localSurvival, boolean ready,
                 boolean neutralInput, boolean safeCorridor) { }
    record Outcome(String requestId, boolean sampled, boolean released, String reason) { }
    record Status(String session, String ownerRequestId, boolean sampled, boolean released,
                  boolean admissionOpen, int requestsRemaining) { }

    private final LongSupplier clock;
    private final int maxRequests;
    private final Set<String> seen = new HashSet<>();
    private String session = UUID.randomUUID().toString();
    private boolean open;
    private Ticket active;
    private Observation observation;
    private record Observation(String id, State state, long createdNanos) { }

    GuardedMovement(LongSupplier clock) { this(clock, MAX_REQUESTS); }
    GuardedMovement(LongSupplier clock, int maxRequests) { this.clock = clock; this.maxRequests = maxRequests; }

    synchronized void openAdmission() {
        // A previous tick must release before reopening. Never forget its owner.
        require(active == null, "movement_cleanup_pending");
        session = UUID.randomUUID().toString(); seen.clear(); observation = null; open = true;
    }
    synchronized void closeAdmission() { open = false; observation = null; cancelOutstanding("bridge_lifecycle_changed"); }
    synchronized String session() { return session; }
    synchronized Status status() {
        return new Status(session, active == null ? null : active.request.requestId(),
                active != null && active.sampled, active == null || active.cleanup == null, open,
                maxRequests - seen.size());
    }

    /** Latest /state snapshot only. A newer observation invalidates its predecessor. */
    synchronized String observe(State state) {
        if (!open || active != null) return null;
        observation = new Observation(UUID.randomUUID().toString(), state, clock.getAsLong());
        return observation.id();
    }

    synchronized Ticket submit(Request request, long receivedNanos, String entrySession) {
        require(open && session.equals(entrySession) && session.equals(request.session()), "movement_session_changed");
        require(!seen.contains(request.requestId()), "movement_request_replayed");
        require(active == null, "movement_busy");
        require(seen.size() < maxRequests, "movement_session_budget_exhausted");
        require(observation != null && observation.id().equals(request.observationId()), "movement_observation_changed");
        Observation observed = observation;
        observation = null; // A valid challenge is single-use, even if the request subsequently fails.
        // Failed/expired requests also consume their nonce; no eviction permits replay.
        seen.add(request.requestId());
        long observationAge = clock.getAsLong() - observed.createdNanos();
        require(observationAge >= 0 && observationAge < TimeUnit.MILLISECONDS.toNanos(MAX_OBSERVATION_AGE_MS),
                "movement_observation_expired");
        State snapshot = observed.state();
        require(request.worldGeneration().equals(snapshot.worldGeneration()) && request.playerUuid().equals(snapshot.playerUuid())
                && request.expectedTick() == snapshot.tick() && request.x() == snapshot.x() && request.y() == snapshot.y()
                && request.z() == snapshot.z() && request.yaw() == snapshot.yaw(), "movement_observation_mismatch");
        Ticket ticket = new Ticket(request, receivedNanos, observed.createdNanos());
        require(!expired(ticket), "movement_expired");
        active = ticket;
        return ticket;
    }

    /** Game-thread-only callbacks. Monitor spans fresh checks and the sole input mutation. */
    synchronized void sample(Supplier<State> liveState, Runnable apply, Runnable release) {
        Ticket ticket = active;
        if (ticket == null || ticket.sampled) return;
        try {
            checkLive(ticket);
            validate(ticket.request, liveState.get());
            checkLive(ticket); // World inspection can consume the lease or synchronously cancel it.
            ticket.cleanup = release; // Ownership is established even if apply throws midway.
            ticket.sampled = true;
            apply.run();
        } catch (RuntimeException | Error failure) {
            ticket.reason = failure instanceof GuardedAction.Rejected ? failure.getMessage() : "movement_failed";
            finish(ticket);
        }
    }

    /** At client tick end, and at game-thread screen/world/death/stop cleanup. */
    synchronized void finishTick() {
        if (active == null) return;
        if (active.sampled) finish(active);
        else if (expired(active)) { active.reason = "movement_expired"; finish(active); }
    }
    synchronized void cancelOutstanding(String reason) {
        observation = null; // Cancellation is also a barrier to pre-cancel, not-yet-admitted requests.
        if (active == null) return;
        active.reason = reason;
        if (!active.sampled) finish(active); // No game mutation/cleanup is needed.
    }
    synchronized void cancelAndRelease(String reason) {
        cancelOutstanding(reason);
        if (active != null) finish(active);
    }

    private boolean expired(Ticket ticket) {
        long age = clock.getAsLong() - ticket.receivedNanos;
        // Duration is a receipt-to-sample lease, not a held-key timer.
        long observationAge = clock.getAsLong() - ticket.observedNanos;
        return age < 0 || age >= TimeUnit.MILLISECONDS.toNanos(Math.min(ticket.request.ttlMs(), ticket.request.durationMs()))
                || observationAge < 0 || observationAge >= TimeUnit.MILLISECONDS.toNanos(MAX_OBSERVATION_AGE_MS);
    }
    private void checkLive(Ticket ticket) {
        require(active == ticket && ticket.reason == null && !expired(ticket), "movement_expired");
        require(open && session.equals(ticket.request.session()), "movement_session_changed");
    }
    private void finish(Ticket ticket) {
        if (ticket.cleanup != null) {
            // Do not free admission or acknowledge release if cleanup fails. Retry at later tick.
            try { ticket.cleanup.run(); }
            catch (RuntimeException | Error failure) { ticket.reason = "movement_cleanup_failed"; return; }
            ticket.cleanup = null;
        }
        if (active == ticket) active = null;
        ticket.result.complete(new Outcome(ticket.request.requestId(), ticket.sampled, true,
                ticket.reason == null ? "sample_released" : ticket.reason));
    }

    static void validate(Request request, State live) {
        require(live.enabled(), "guarded_movement_disabled");
        require(live.localSurvival(), "local_survival_required");
        require(live.ready(), "player_not_ready");
        require(live.neutralInput(), "movement_input_not_neutral");
        require(request.worldGeneration().equals(live.worldGeneration()), "world_generation_changed");
        require(request.playerUuid().equals(live.playerUuid()), "player_changed");
        require(live.tick() >= request.expectedTick() && live.tick() - request.expectedTick() <= 1, "movement_state_stale");
        require(finite(live.x(), live.y(), live.z(), live.yaw())
                && Math.abs(request.x() - live.x()) <= POSITION_TOLERANCE
                && Math.abs(request.y() - live.y()) <= POSITION_TOLERANCE
                && Math.abs(request.z() - live.z()) <= POSITION_TOLERANCE, "movement_position_changed");
        double delta = Math.IEEEremainder(request.yaw() - live.yaw(), 360);
        require(Math.abs(delta) <= YAW_TOLERANCE, "movement_yaw_changed");
        require(live.safeCorridor(), "movement_corridor_unsafe");
    }
    private static boolean finite(double... values) { for (double value : values) if (!Double.isFinite(value)) return false; return true; }
    private static boolean uuid(String value) {
        if (value == null) return false;
        try { return UUID.fromString(value).toString().equals(value); } catch (IllegalArgumentException ignored) { return false; }
    }
    private static void require(boolean test, String reason) { GuardedAction.require(test, reason); }

    final class Ticket {
        final Request request;
        final long receivedNanos;
        final long observedNanos;
        final CompletableFuture<Outcome> result = new CompletableFuture<>();
        boolean sampled;
        Runnable cleanup;
        String reason;
        Ticket(Request request, long receivedNanos, long observedNanos) { this.request = request; this.receivedNanos = receivedNanos; this.observedNanos = observedNanos; }

        Outcome await() throws InterruptedException, ExecutionException {
            try {
                long remaining = Math.min(TimeUnit.MILLISECONDS.toNanos(Math.min(request.ttlMs(), request.durationMs()))
                        - (clock.getAsLong() - receivedNanos), TimeUnit.MILLISECONDS.toNanos(MAX_OBSERVATION_AGE_MS)
                        - (clock.getAsLong() - observedNanos));
                if (remaining <= 0) throw new TimeoutException();
                return result.get(remaining, TimeUnit.NANOSECONDS);
            } catch (TimeoutException timeout) {
                cancel("movement_expired");
                // If sampling began, the game thread must finish cleanup before acknowledgement.
                return result.join();
            } catch (InterruptedException interruption) {
                cancel("request_interrupted");
                result.join(); // Do not answer while this lease can still own input.
                throw interruption;
            }
        }
        void cancel(String reason) {
            synchronized (GuardedMovement.this) {
                if (active == this) cancelOutstanding(reason);
            }
        }
    }
}
